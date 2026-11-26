# 2026-11-11 阶段 A：单素材导出门控与导出归属

## 范围

按《AI 调色项目后续开发指导》§2.1 / §3.1 / 阶段 A 实现三项：

1. 存在运行中或排队导出时，禁止加载/切换素材。
2. 导出完成/失败/取消通知标明素材名、类型、revision 和目标路径。
3. `_poll` 改为逐 outcome 处理，单个 handler 抛错不再吞掉同批其余结果。

未实施：批次模型、参考协调、并行渲染、日志轮转、单素材导出取消入口。

## 改动

| 文件 | 内容 |
| --- | --- |
| `app/ui.py` | 新增 `_ExportTicket`；`_export_started(kind, rev, material)` 返回 token；`_export_take`、`_outstanding_exports`、`_export_block_reason`；`load_path` 在解码前门控；`_material_name`、`_submit_export`；`_dispatch_outcome` + 逐项异常隔离；通知文案带素材名 |
| `tests/test_matrix.py` | `BusyStatusTests` 改用 token；新增同 kind 同 revision 区分、通知归属、失败归属用例；新增 `PollIsolationTests`、`MaterialSwitchGateTests` |
| `runtime/ui_export_queue_check.py` | 新增“导出中切换被拒”“导出后切换可用”检查 |
| `runtime/ui_video_check.py`、`runtime/ui_stress_check.py` | 跟进 `_export_labels` → `_export_tickets` 与“导出完成”文案 |
| `docs/decisions/ADR-009-local-log-paths.md` | 修订 ADR-005 §3 的路径日志口径 |

## 门控语义

- 判定为“有未完成导出”= 票据数 > 0，或 FIFO 队列非空（防御票据泄漏）。
- 预览不计入：预览可合并且拖动时不断取消，计入会几乎永久锁死切换。
- 检查点在解码之前、`new_document` 之前；`state.source is None` 时不拦截，保证
  `--image` 启动加载可用。
- 提示为阻断式，不提供绕过；文案与文档一致，多个任务时补“剩余 N 项”。

## 自动化结果

```
python -m unittest discover -s tests -q
Ran 160 tests in 39.019s
OK
```

## 端到端结果

```
python runtime/ui_export_queue_check.py
after submit: 正在导出图片（scene.jpg） rev 1…
blocked switch: 当前素材仍有导出任务正在进行，暂时无法切换。请等待导出完成后再试。
mid-flight: 正在导出图片（scene.jpg） rev 1…（等待当前渲染完成）
message: 图片导出完成（scene.jpg，rev 1）：...\runtime\export-queue-check.png · PNG · 1289 ms
switch after export: pattern.png
OK
```

## 写入与清理

- `runtime/export-queue-check.png`：脚本自行删除。
- `runtime/cache/{preview,lut,video,full}`：由既有 LRU 预算裁剪，未新增目录。
- 测试临时目录：`tempfile.mkdtemp()` + `shutil.rmtree`，沿用既有测试写法。
- 未改动用户素材；端到端只读 `runtime/test-fixtures/`。

## 仍未验证 / 已知缺口

- 高 DPI（125%/150%）、最小窗口、侧栏滚动、A/B 拖动仍需**人工**验收。
- 导出失败通知会弹 `messagebox`，在无人值守脚本中会阻塞（脚本已 mock）。
- 日志无轮转（见 ADR-009 已知缺口）。
- 单素材工作流仍无“取消导出”入口；按文档 §2.2 归入阶段 B。
