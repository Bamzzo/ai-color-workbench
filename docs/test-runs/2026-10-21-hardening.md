# 测试记录：2026-10-21 一致性加固（任务队列 / 头部检查 / 缓存 / 40MP）

本轮处理 `docs/优化空间扫描与开发评估清单.md` 中**第一批 + 第二批**：队列语义、
解码前检查、job 目录回收、缓存上限、可自动化的验收脚本。发布形态（清单 #4）与
颜色公式/观感评审（#6）不在本轮范围内。

## 1. 结论摘要

| 清单项 | 处理 | 证据 |
| --- | --- | --- |
| #1 跨类型任务互相覆盖 | 已修复，导出进 FIFO | 复现脚本 + 3 个回归测试 |
| #2 尺寸检查晚于解码 | 已修复，头部检查前置 | 断言 `Image.load` 未被调用 |
| #3 job 目录无限增长 | 已修复，成功后即时删除 | 215 MB → 每个渲染 0 残留 |
| #3 缓存无上限 | 已修复，320 MB + LRU | `tests/test_paths.py`（6 项） |
| #5 40MP 验收 | 已自动化，并发现内存峰值问题 | 2.90 GB → 0.70 GB |
| #4 发布形态 | 未处理（判定为本次交付不做） | — |
| #6 观感评审 | 未处理（需要样片与人工判断） | — |

自动测试：**133 项通过，0 失败**（上一轮 107 项，本轮 +26）。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t .
# Ran 133 tests — OK
```

## 2. 导出现在不会被预览挤掉

### 复现（修复前）

```python
runner.submit("preview", slow, coalesce_key="preview", revision=1)
runner.submit("export-image", export, coalesce_key="export-image")
runner.submit("preview", quick, coalesce_key="preview", revision=2)
# outcomes: [('preview','preview-running'), ('preview','preview-2')]
# export ran? False   ← 既没执行，也没有 cancelled/error 事件
```

根因：`submit()` 无论 key 是否相同都执行 `self._pending = spec`，导出被后来的预览
覆盖，且旧 pending 的取消事件未置位，所以 UI 连「已取消」都收不到。

### 修复

`app/jobs.py` 现在区分两种排队策略，仍是**一个** worker 线程（本机 Mesa 软件渲染，
并行只会互相拖慢）：

| 策略 | 调用方 | 行为 |
| --- | --- | --- |
| `coalesce=True` | 预览 | 只保留最新；同 key 的在跑任务会被取消 |
| `coalesce=False` | 导出图片 / 导出 LUT | 进入 FIFO，任何提交都不能替换 |

调度顺序：FIFO 优先，其次最新的可合并任务。`_current` 与出队在同一把锁内完成，
避免刚出队时到达的提交找不到取消目标。

UI 侧配套修改：

- 导出走 `coalesce=False`。
- 新增 `_export_labels` / `_refresh_busy()`：busy 行只显示导出状态，预览完成不再
  擦掉「正在导出 rev N…」；多个导出排队时显示「另有 N 个导出排队」。
- 载图、AI、导入 LUT 的清除也改走 `_refresh_busy()`，避免互相覆盖。

### 回归测试

| 用例 | 断言 |
| --- | --- |
| `test_t10_export_is_not_dropped_by_a_preview` | 导出执行且顺序为 `[A, EXPORT, P3]`，被合并的 P2 不执行 |
| `test_queued_exports_keep_fifo_order` | 图片 → LUT 严格按提交顺序执行 |
| `test_shutdown_cancels_queued_exports` | 关闭时排队导出不执行、`is_busy()` 为假 |
| `BusyStatusTests`（2 项） | 预览结束不清除导出提示；排队计数正确 |

### 端到端验证

`runtime/ui_export_queue_check.py` 用真实 UI + 真实 worker 驱动：载图 → 请求导出
（此时首帧预览仍在渲染，导出排进 FIFO）→ 连续两次拖动滑杆（各触发一次预览提交）
→ 等待队列清空。

```
after submit: 正在导出图片 rev 1…
mid-flight: 正在导出图片 rev 1…（等待当前渲染完成）
busy at end: ''
message: 预览已更新 rev 3 · 2187 ms（GPU 读写回 23.8 ms）
export size: 0.4 MB
OK
```

## 3. 超限图像在解码前被拒绝

`load_source_image` 现在先跑 `_check_container()`（`Image.open` 已完成 JPEG SOF /
PNG IHDR 解析，格式、模式、帧数、尺寸都已可得），再调用 `load()`；EXIF 旋转后的
像素数二次校验保留。

验证方式不是「看起来更早了」，而是断言解码从未发生：

- `test_oversize_rejected_before_pixels_are_decoded`：构造一个只有 IHDR 的 7000×7000
  PNG（49 MP），把 `Image.Image.load` 替换为抛 `AssertionError`。结果是被像素上限
  拒绝，而不是「无法解码」（若顺序未改，截断文件会先报解码错误）。
- `test_truncated_header_only_file_reports_decode_error`：同样的构造但 32×32，
  失败原因必须是解码错误，证明头部检查不会误杀正常小图。
- `test_pixel_limit_boundary_is_inclusive`：上限恰好等于像素数时允许加载。

## 4. job 目录与缓存不再无限增长

### 修复前的实测占用

| 目录 | 修复前 | 说明 |
| --- | --- | --- |
| `runtime/jobs` | 215.3 MB / 420 个目录 | 每次预览留下约 3.9 MB `output.rgba`，只在下次启动按 24h 清理 |
| `runtime/cache/lut` | 42.9 MB / 38 文件 | 每个 33³ 文本 `.cube` 约 1.1 MB，每拖一次滑杆新增一个 |
| `runtime/cache/full` | 11.1 MB / 3 文件 | 40 MP 单图约 160 MB，之前无上限 |

### 修复

1. **成功的渲染即时删除 job 目录**：像素已读入内存、stdout/stderr 已捕获，目录没有
   后续用途。失败时保留（用于诊断），`keep_job_dir=True` 可强制保留。
2. **缓存上限 + LRU**：`paths.prune_cache()`，默认上限 320 MB，按 mtime 从旧到新删除；
   写入新 LUT 与新 full 缓存后调用，启动时也调用一次。**10 分钟内写过的文件永不删除**
   ——渲染进程在启动时解析输入路径，删掉刚写的文件会让进行中的任务失败。

### 回归测试

| 用例 | 断言 |
| --- | --- |
| `test_successful_render_cleans_its_job_directory` | 渲染成功后 `job_dir` 不存在，`runtime/jobs` 名字集合不变 |
| `test_keep_job_dir_flag_leaves_diagnostics_on_disk` | `keep_job_dir=True` 保留 `response.json` |
| `test_t14_foreign_binary_as_worker_is_reported` | 用 `where.exe` 冒充 worker：报 `PROCESS_CRASHED`，失败目录保留 |
| `tests/test_paths.py`（6 项） | 计数、上限内不动、最旧优先淘汰、最近文件免疫、目录缺失容错 |

## 5. 40MP 验收：发现并修掉一个内存峰值

新增 `tools/measure_large_image.py`（3920 万像素、82 MB PNG）：

```powershell
.\.venv\Scripts\python.exe tools\measure_large_image.py --export
.\.venv\Scripts\python.exe tools\measure_large_image.py --repeats 12
```

首轮结果暴露了清单没提到的问题：**预览阶段峰值 RSS 达到 2.90 GB**
（本机 15.4 GB）。原因是 `_resize_premultiplied` 对整幅 40 MP 图像做 float32 运算，
每个临时缓冲区约 640 MB，连续几个叠加。

修复：**不透明图像走快速路径**。alpha 全为 255 时预乘是恒等变换，直接对 RGB 做
LANCZOS 缩放的结果与浮点路径逐像素相同，因此完全跳过浮点缓冲区。带真实透明通道的
图仍走原浮点路径（保留去色晕效果，代价不变）。

| 指标 | 修复前 | 修复后 |
| --- | --- | --- |
| load（40 MP） | 1.4 s | 1.3–3.4 s |
| 预览渲染（每次都要起一个 worker 进程 + GL 初始化） | 1.5 s | 1.1–4.3 s（另有约 24 ms 为 GPU 读写回） |
| 峰值 RSS（load + 预览） | **2902 MB** | **701 MB** |
| 峰值 RSS（+ 导出 40 MP PNG） | —（未记录） | 1197 MB |
| 导出耗时 | — | 11.9–16.4 s |

稳态 RSS 约 236 MB；导出结束后回落。

连续编辑验证（`--repeats 12`）：12 次不同曝光的预览后，**`runtime/jobs` 目录数保持
445 → 445 不变**（修复前每次会新增约 3.9 MB，12 次约 47 MB）；`runtime/cache` 从
238.7 MB 增至 257.8 MB（新增 12 个 LUT），仍在 320 MB 上限内。

## 6. 仍然只能人工验收的部分

1. 高 DPI（200%）下侧栏文字、直方图、A/B 拖动的视觉与命中位置。
2. 快速连续拖滑杆时是否出现旧 revision 回跳（自动测试只验证「只保留最新」）。
3. AI 慢响应期间改参数 / 关窗；晚到提案是否只作为提案。
4. 预设按钮连点后文本框仍可编辑。
5. 最小窗口（1120×720）下直方图与画布比例。
6. 样片观感（清单 #6）：肤色、天空高饱和、夜景、逆光、低对比、透明 PNG。

## 7. 已知残留

- 本轮修复前遗留的 215 MB job 目录不会被追溯删除；下次启动的 24h 清理会处理。
  新产生的渲染不再堆积。
- 40 MP **带真实 alpha** 的 PNG 仍走浮点路径，峰值仍是 GB 级；这类输入在 P0 里少见，
  如果要处理需要按条带分块，未在本轮实施。
- `_dpi_scale()` 在本机恒为 1.0（Tk 在 200% 缩放下报告逻辑像素）。相关分支是惰性
  代码，不代表已做 DPI 适配；不要把这条写进「高 DPI 已完成」的结论里。
- 单个预览的延迟主要来自每次都要起一个 worker 进程并初始化 GL（本机为 Mesa 软件
  渲染），不是本轮改动引入的回归。

## 8. 交付前自检又发现并修掉的五项

这五项不在原清单里，是改完第一批后做整体复扫时发现的。

### 8.1 AI 请求被新请求替换时会误报「已取消」

`LatestJobRunner` 对同 key 的 AI 请求会取消旧的一个，旧请求随后返回
`cancelled=True`。原实现不看代次，于是「再点一次 AI」会让状态行先闪一句
「AI 请求已取消」，并把 `_ai_busy` 提前置回 False，而新请求其实还在跑。

修复：`JobSpec`/`JobOutcome` 增加可选的 `token`（调用方自有的不透明戳），
UI 提交 AI 请求时带上 `_ai_request_seq`；`_handle_ai` 在 `token` 落后时直接忽略该
结果（它已被新请求取代，新请求会自己报告结果）。

| 用例 | 断言 |
| --- | --- |
| `test_stale_ai_outcome_is_ignored` | 旧代次结果不改消息、不清 `_ai_busy` |
| `test_current_ai_cancellation_is_reported` | 当前代次的取消仍提示「AI 请求已取消」 |

### 8.2 状态行只能显示一个活动

导出与 AI 请求可以同时在跑，但 `busy_var` 是谁最后写谁生效：AI 请求会盖掉导出提示，
反之亦然。现在 `_refresh_busy()` 把各来源拼成一行：

```
正在导出图片 rev 4… · AI 请求中…
```

导出的排队计数也按真实 FIFO 长度计算，区分「等待当前渲染完成」与「另有 N 个导出排队」。

| 用例 | 断言 |
| --- | --- |
| `test_queued_exports_are_counted_while_one_runs` | 一个在跑、一个排队时的完整文案 |
| `test_two_exports_waiting_report_the_total` | 两个都未开始时显示「共 2 个导出排队」 |
| `test_ai_and_export_share_the_line` | AI 与导出同时可见 |
| `test_finishing_an_unknown_export_keeps_the_other_label` | 完成事件只移除对应 revision |

### 8.3 导出完成提示会被下一次预览消息覆盖

压力脚本第一次运行就抓到：图片已导出，但状态行在一秒内变成「预览已更新 rev 6」，
用户看不到文件路径和导出时的 revision。

修复：`_preview_message()` 在导出成功后的 6 秒内不写预览消息（`EXPORT_NOTICE_SECONDS`）；
错误消息不受影响，仍立即显示。

| 用例 | 断言 |
| --- | --- |
| `test_export_notice_is_not_overwritten_by_a_preview` | 保留期内预览不改消息，过期后恢复 |

### 8.4 目录遍历未关闭 `scandir` 句柄

`cache_usage()` / `prune_cache()` 里 `os.scandir()` 的结果没有关闭，在
`-W error::ResourceWarning` 下会暴露。已抽出 `_walk_files()` 用上下文管理器统一处理，
两个函数共用同一套遍历逻辑。

验证：全套测试在 `-W error::ResourceWarning` 下通过。

### 8.5 被取消的渲染会留下空 job 目录

成功渲染已即时回收目录，但**取消**走的是另一条分支（worker 进程被 kill 后抛
`CANCELLED`），在回收之前就返回了。快速拖滑杆时每次被取代的预览都会留下一个目录，
虽然只有几百字节的 `request.json`，但一小时内能积出上百个。

修复：取消分支同样回收目录；超时、崩溃、GPU 失败仍保留，因为这些才需要诊断。

| 用例 | 断言 |
| --- | --- |
| `test_cancelled_render_leaves_no_job_directory` | 取消后 `runtime/jobs` 名字集合不变 |

压力验证：连续提交 10 个互相取代的预览（每 120 ms 一次），`runtime/jobs` 目录数
**88 → 88**。

## 9. 真实 UI + 真实 worker 压力脚本

`runtime/ui_stress_check.py`（需要窗口，约 30 秒）：

```
PASS phase1 first preview arrives
PASS phase2 export completed           # 导出期间连续拖 4 次滑杆
PASS phase2 file written
PASS phase2 export notice retired
PASS phase2 no stale export labels
PASS phase3 three exports tracked      # 图片 + LUT + 图片 同时排队
PASS phase3 all three exports finished
PASS phase3 stress-b.png / stress-c.png / stress-d.cube
PASS phase3 completion message
PASS phase4 close is prompt            # 导出进行中关窗
OK
```

补充观察：

- 关窗耗时 0.25–1.6 秒，进程退出后 `render_worker.exe` 残留数为 0，没有半成品文件。
- 导出期间继续拖滑杆，导出使用的仍是点击时的 snapshot（消息里的 rev 保持为导出时的值）。

`runtime/ui_export_queue_check.py` 是更早的针对性复现脚本，结论一致。
