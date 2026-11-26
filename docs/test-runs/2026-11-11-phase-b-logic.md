# 2026-11-11 阶段 B（逻辑层 + 真实导出接线）

## 范围

新增 `app/batch.py`、`app/batch_export.py`、`runtime/batch_mixed_check.py`，
并在 `app/pipeline.py` 增加 `bake_video_cube`。按《开发指导》§4.1 / §4.2 / §3.3
实现批次模型、输出规划、调度语义与真实图片/视频导出。**仍未接 UI**。

## 改动

| 文件 | 内容 |
| --- | --- |
| `app/batch.py` | `MediaKind`/`ItemStatus`/`Strategy`/`ConflictPolicy`；`BatchItem`、`BatchTaskSnapshot`、`BatchRecord`、`BatchState`、`BatchUpdate`；`plan_target`/`plan_batch`；`BatchRunner`（FIFO、三项取消、进度、shutdown）；`detect_kind` |
| `app/batch_export.py` | `BatchExportWorker`：图片走 `pipeline.export_image`，视频走 `bake_video_cube` + `video_io.export_graded`，逐项释放解码像素、清理临时 cube |
| `app/pipeline.py` | 新增 `bake_video_cube`（把 strength 烘进 cube，供批量视频复用）；现有导出路径未改 |
| `tests/test_batch.py` | 33 个纯逻辑用例 |
| `tests/test_batch_export.py` | 9 个 worker 适配用例外加取消/失败映射 |
| `runtime/batch_mixed_check.py` | 真实引擎 + ffmpeg 的混合队列端到端 |
| `docs/decisions/ADR-010-batch-workspace.md` | 模型、队列、取消、状态机、命名规则、worker 接线与推迟决策 |

## 覆盖

模型：基线/覆盖互不污染、显式“应用到全部”、重复源拒绝、只移除未开始项、
失败可重试而完成项不可、进度不回退、完成项不可被改写为取消。

规划：命名与扩展名、默认跳过冲突、改名递增、批内重名、覆盖需显式、拒绝覆盖源、
`SOURCE_MISSING`/`PARAMS_MISSING`/`OUTPUT_MISSING`、快照冻结、只规划待处理项。

调度：FIFO 顺序、单消费者（`max_active == 1`）、失败继续、取消排队项幂等、
取消当前项协作停止、`cancel_pending` 保留当前项、`cancel_all`、完成后取消无副作用、
无视取消的 worker 不会记为成功、进度去重、shutdown 清理、重复提交去重。

## 自动化结果

```
python -m unittest tests.test_batch -q
Ran 33 tests in 0.420s
OK
```

连续 5 次重复运行均通过（线程用例无抖动）。

```
python -m unittest tests.test_batch_export -q
Ran 9 tests in 0.037s
OK

python -m unittest discover -s tests -q
Ran 202 tests in 33.425s
OK
```

## 端到端结果（真实引擎 + ffmpeg）

```
python runtime/batch_mixed_check.py
-- phase 1: mixed queue (2 stills + 1 clip) --
   still-a.jpg    done       ...\out-mixed\still-a_graded.png
   clip.mp4       done       ...\out-mixed\clip_graded.mp4
   still-b.png    done       ...\out-mixed\still-b_graded.png
-- phase 2: a missing source does not stop the queue --
   statuses: ['done', 'failed', 'done']
-- phase 3: cancel pending keeps the running item --
   statuses: ['done', 'cancelled', 'cancelled']
-- phase 4: cancel the current item, keep the queue --
   statuses: ['cancelled', 'done', 'done']
elapsed: 10.4s
OK
```

两次连续运行结果一致。覆盖：混合队列顺序、输出尺寸/时长保持、进度单调且到 1.0、
临时 cube 清理、规划后删除源导致的失败被隔离、三种取消组合。

## 写入与清理

- 单元测试只用 `tempfile.mkdtemp` + `rmtree`，不写 `runtime/`。
- 端到端全部输出在 `tempfile.mkdtemp(prefix="batch-mixed-check-")` 内并整体删除。
- 真实渲染会写 `runtime/cache/{full,preview,lut}`，由既有 LRU 预算裁剪，未新增目录。
- 未触碰用户素材；视频由 ffmpeg 合成。

## 未验证

- 批次 UI 的导入、列表、进度展示与人工可用性验收。
- 峰值内存与长批次 RSS 曲线（阶段 D 才做，本阶段只保证逐项释放）。
- 暂停/继续、落盘续跑、参考协调、并行 worker：按 ADR-010 推迟。
