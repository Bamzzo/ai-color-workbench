# ADR-010：批处理工作区的数据模型与调度语义（逻辑层）

## 状态

已采用（阶段 B：逻辑层 + 真实 worker + 批次窗口 UI 第一版）。参考素材协调仍未启用。

## 范围

本 ADR 覆盖 `app/batch.py`（模型/规划/队列）、`app/batch_export.py`（真实
worker）与 `app/batch_ui.py`（批次窗口）。不包含参考素材协调、并行渲染、
跨重启恢复。单素材编辑器（`app/ui.py`）只增加互锁与“打开批次窗口”，未改
颜色数学、渲染协议或图像 I/O。

## 背景

单素材工作流里，`AppState` 是一个 document，`LatestJobRunner` 用
`coalesce_key` 区分“可合并的预览”和“不可丢弃的导出”。批次不能用同一套语义：

- 预览按 key 合并是有意的；批次项各有身份，不能互相顶掉。
- `cancel(key)` 是类别语义；批次要按 item 精确取消。
- 用户可在运行中移除、排序、重试，索引不再稳定。

因此批次另起模型与队列，`AppState` 与 `LatestJobRunner` 不改。

## 决策

### 1. 规格与状态分离

| 类型 | 可变性 | 归属线程 | 用途 |
| --- | --- | --- | --- |
| `BatchItem` | frozen | 任意 | 源、类型、参数覆盖、LUT、强度 |
| `BatchTaskSnapshot` | frozen | 任意 | 启动某项时冻结的一切输入与目标 |
| `BatchRecord` | mutable | 仅主线程 | 状态、进度、错误、输出、耗时 |
| `BatchState` | mutable | 仅主线程 | 承载 items/records/基线/输出配置 |
| `BatchUpdate` | frozen | worker → 主线程 | 唯一的跨线程产物 |

worker 只拿到 `BatchTaskSnapshot`，只返回 `BatchUpdate`；它不碰 `BatchRecord`，
也不可能碰到 Tk 变量。主线程用 `apply_update` 落到状态机。

`ColorParams` 本身是 frozen dataclass，所以“统一基线”是共享引用而非共享可变对象，
不存在一项改参数污染其他项的问题。

### 2. 队列

- 单消费者 FIFO，任一时刻最多一个重型任务；提交顺序即执行顺序。
- `submit` 对同一 `item_id` 去重；已终结的 item 不会被再次接受。
- 线程在首次提交时启动，队列排空后退出；再次提交会重启，不泄漏线程。
- 进度按 1% 粒度去重（同一 tick 不重复入队），进度在 `apply_update` 中单调不减。
- `is_idle()` 是 UI 的完成信号；只看 `is_running()` 会与线程启动竞争。

### 3. 取消语义

| 操作 | 排队项 | 当前项 | 已完成项 |
| --- | --- | --- | --- |
| `cancel_item(id)` | 移出队列 → 已取消 | 置 cancel event，协作停止 | 返回 False，不改状态 |
| `cancel_pending()` | 全部 → 已取消 | 不受影响，继续运行 | 不受影响 |
| `cancel_all()` | 全部 → 已取消 | 置 cancel event | 不受影响 |

- 三者都幂等：第二次调用返回 False / 0，不产生第二个终态更新。
- worker 无论是否理会 cancel event，只要事件已置位，结果一律记为已取消，
  不会被报告为已完成。
- worker 抛 `BatchCancelled` → 已取消；抛其他异常 → 失败，队列继续。
- 失败项不会被下次 `plan_batch` 自动重跑，必须显式 `retry()`。

### 4. 状态机

待处理 → 准备中 → 处理中 → 已完成 / 失败 / 已取消 / 已跳过；
失败、已取消、已跳过 → 待处理（显式重试）；已完成没有出边。

非法迁移由 `can_transition` 拒绝，`apply_update` 返回 False 而不是抛异常——
迟到的取消更新不能把已完成项改写掉。

### 5. 输出规划

- 默认命名：`{源主名}_graded{扩展名}`；视频用 `.mp4`，图片用 `.png`。
- 冲突默认 `SKIP`；`RENAME` 追加 `-2`、`-3`……；`OVERWRITE` 必须显式选择。
- 目标与源同一路径时一律拒绝，即使策略是覆盖。
- `taken` 集合保证同一批次内两项不会算出同一个目标名。
- 输出目录不存在时整批报 `OUTPUT_MISSING`，不生成任何快照。

### 6. 逐项错误

| 错误码 | 含义 | 队列影响 |
| --- | --- | --- |
| `SOURCE_MISSING` | 执行前源文件不存在 | 该项失败，其余继续 |
| `SOURCE_CHANGED` | 导入后源文件大小/修改时间变化 | 该项失败，要求移除后重新添加 |
| `PARAMS_MISSING` | 既无覆盖也无基线 | 该项失败，其余继续 |
| `OUTPUT_MISSING` | 输出目录不可用 | 整批中止 |
| `OUTPUT_INVALID` | 扩展名/质量参数非法 | 构造配置时抛出 |
| `BATCH_FAILED` | worker 未提供错误码时的兜底 | 该项失败，其余继续 |

`plan_batch` 只规划 `PENDING` 项；`apply_plan` 把跳过/错误写回记录，执行前不写任何文件。

### 7. 真实导出接线（`app/batch_export.py`）

`BatchExportWorker` 是 `BatchRunner` 唯一认识的 worker 形状：
`worker(snapshot, cancel, report) -> Path`。调度器因此不认识图片、视频、引擎或 ffmpeg。

- 图片：`load_source_image` → `prepare_preview` → 构造 `RenderSnapshot` →
  `pipeline.export_image(..., cancel)`，与 UI 导出完全同一条路径。
- 视频：`video_io.probe` → `pipeline.bake_video_cube`（把 strength 烘进 .cube）→
  `video_io.export_graded`，临时 cube 在 `finally` 中删除。
- 每项结束关闭解码后的 PIL 图像，批次内不累积像素；只有 pipeline 的磁盘缓存共享。
- `BatchTaskSnapshot` 冻结 `image_quality` / `video_quality` / `video_preset`，
  批次设置中途改动不会影响已启动的项。
- 引擎/ffmpeg 用各自的 `CANCELLED` 错误码表示取消，runner 据此记为已取消而非失败。

新增 `RenderPipeline.bake_video_cube`，与预览烘焙同源但不做用户级 LUT 等价校验；
现有 `export_lut` / `export_image` 行为未改。

## 8. 参数编辑（UI 侧）

模型层已提供 `set_override` / `apply_baseline`，批次窗口只把两个明确意图暴露出来：

- **用当前参数填充所选**：把编辑器当前的 `ColorParams` 写入所选且仍为 `PENDING` 的
  item；未选中的项一律不动，这就是“复制参数到所选项”的安全版本。
- **恢复统一参数**：清除所选 `PENDING` item 的覆盖，回到共享基线。
- 运行中两个按钮禁用；已开始/已完成的项不接受参数修改（快照已冻结）。
- 列表新增“参数”列显示 `统一` / `单独`，用户不必猜测某项用的是哪套参数。
- `start()` 会用编辑器当前参数刷新 `state.baseline`，所以“改全局参数 → 开始”就是
  自然的“更新未覆盖项”，不需要额外传播逻辑。
- 选择“逐项微调”策略时，新导入项在导入瞬间捕获当前参数作为 override，避免继承
  上一项或上一批次的编辑结果。

## 9. 批次窗口（`app/batch_ui.py`）

- 窗口自持 `BatchState` 与 `BatchRunner`，主窗口只负责单文档编辑。
- Tk 单线程纪律：所有控件与 `PhotoImage` 只在主线程创建/更新；窗口在 `after`
  轮询里排空 runner 更新与缩略图结果。
- 缩略图线程只做解码：图片走 `draft()` 缩小后 decode，视频用 `VIDEO_CACHE`
  首帧；失败只记录“预览不可用”，不把 item 判失败。
- 主窗口互锁：`ColorApp.set_batch_active(True)` 禁用单素材导出按钮与素材切换，
  并取消在途预览；批次结束或窗口关闭时恢复。互锁期间再点导出/打开会得到提示。
- 关闭确认汇总当前项与剩余队列数；确认后 `cancel_all()` + `shutdown(3.0)`，
  超时未清理干净时提示用户核对输出目录，而不是宣称已完成。
- 失败/跳过/取消都在“说明”列给出可读原因，选中行在底部显示错误码与详情。
- 列表默认列宽总和约 980 px，适配默认窗口；窗口更窄或名字更长时用横向滚动条，
  `ttk.Treeview` 不做省略号，长名会被裁切而不是静默改写。
- **行高与缩略图**：`Treeview` 的 `rowheight` 必须与缩略图匹配（当前 64 px 缩略图 /
  68 px 行高，均按显示缩放换算），否则图片会溢出到相邻行并与文字重叠。
- **文件名放在值列**：树列（`#0`）只承载缩略图，文件名是普通列 `name`。原因是在
  本机 Tk/主题组合下，带 `-image` 的树项不再绘制自身 `-text`（实测文字消失），
  值列则始终绘制。这条是平台行为，不是设计偏好，改动前请先复测。
- 顶部配置分两行（输出目录 / 图片格式·质量·视频预设·后缀·冲突），操作按钮分三行
  （文件 / 运行控制 / 参数），避免窄窗口下按钮被右边缘裁掉。

## 10. 执行前校验与源变化检测

- `start()` 预检：输出目录存在、`os.access(W_OK)` 可写、没有单素材导出在途。
- `BatchItem.create` 记录 `(st_size, st_mtime_ns)` 指纹；`plan_batch` 在执行前比对，
  不一致报 `SOURCE_CHANGED`，提示移除后重新添加（重新导入会取得新指纹）。
- 指纹为 `0` 表示导入时文件已不可读，此时跳过变化检测，交给 `SOURCE_MISSING`。
- 磁盘空间预检暂缓：需要按输出体积估算，先只保证目录可写。

## 被推迟的决策

- 暂停/继续：首版不做，取消已覆盖需求。
- 批次落盘与重启续跑：不承诺。
- 参考素材协调：阶段 C，需独立 ADR 与样片评审。
- 并行 worker：等阶段 D 的吞吐/内存数据。
- 磁盘空间预检：需要按输出估算体积，当前只检查目录存在且可写。

## 后果

- 批次逻辑可以脱离 Tk 与 GPU 单独测试（`tests/test_batch.py` 35 个用例，
  `tests/test_batch_export.py` 9 个用例，合计 0.5 s 内）。
- 接 UI 时只需：导入 → `BatchState`、开始 → `plan_batch` → `submit`、
  轮询 → `apply_update`、取消 → 三个方法。
- 批次与单素材工作流共用 `ColorParams` 与 LUT 语义，但队列互不干扰。
- 批次运行时主窗口进入互锁，保证软件 OpenGL 下只有一个重型任务在跑。
