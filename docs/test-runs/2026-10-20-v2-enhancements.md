# 测试记录：2026-10-20 v2 增强（直方图 / 16 参数 / AI 提示词）

本记录只覆盖本轮新增或改动的部分；T01–T15 的基线结论见
`2026-10-20-baseline.md`，本轮没有降低任何既有断言。

## 1. 自动测试

命令：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
```

结果：**107 项通过，0 失败**（基线 90 项 + 本轮新增 17 项）。

新增/调整的断言：

| 用例 | 关注点 |
| --- | --- |
| `test_legacy_v1_document_is_upgraded_with_zero_defaults` | v1 文档仍可读，9 个新字段补 0 |
| `test_wrong_version_rejected` | 3.0 被拒绝 |
| `test_hue_out_of_range_rejected` | `hue=200` 被拒绝 |
| `test_split_amounts_must_be_non_negative` | 着色强度不允许负值 |
| `test_whites_and_blacks_only_move_the_extremes` | 中灰不动，仅端点移动 |
| `test_vibrance_protects_saturated_colours` | 低饱和相对增益 > 高饱和 |
| `test_shadows_highlight_tint_hues` | 蓝阴影 / 暖高光方向 |
| `test_hue_rotation_moves_red_towards_green` | 红→绿 |
| `test_hue_rotation_preserves_gray` | 灰色像素旋转后不变 |
| `test_lut_approximation_33_with_split_toning` | 含分离色调时 33³ 仍 ≤8/255（p99 ≤3/255） |
| `test_retired_model_is_flagged` | `deepseek-chat` 状态栏提示已停用 |
| `test_prompt_targets_v2_schema_and_carries_current_params` | 提示词含 v2 字段与当前参数 |
| `test_histogram.py`（6 项） | 分桶、裁剪比例、通道分离、绘制尺寸、空直方图、透明像素按白底合成 |

## 2. 真实 DeepSeek 调用

`AI_MODEL=deepseek-flash`、`AI_OFFLINE_ONLY=false`，使用本机 `.env` 中的密钥
（未打印、未写入本记录）。

输入：

> 电影感青橙调，阴影偏青，高光偏暖，不要过饱和

返回（`source=ai`，`model=deepseek-flash`）：

```
contrast 16, temperature 3, highlights -16, shadows 8,
whites -4, blacks -6, saturation -8, vibrance 5,
split_shadow_hue 195 / amount 26,
split_highlight_hue 35 / amount 20,
split_balance 4
```

观察：

- 一次请求即通过本地 Schema v2 校验，没有触发修复重试。
- 幅度落在提示词的“明显风格”区间，没有出现把多个字段推到 ±80 的旧问题。
- 光影方向符合需求：压高光、提阴影、降饱和、青影暖高光。

## 3. LUT 近似质量（T08）

命令 `.\.venv\Scripts\python.exe tools\measure_lut.py`，145,937 个采样点。

| 预设 | 33³ max (0–255) | 33³ p99 | 65³ max |
| --- | --- | --- | --- |
| identity | 0.00 | 0.00 | 0.00 |
| warm | 2.31 | 1.18 | 1.16 |
| cool | 1.68 | 0.38 | 0.86 |
| soft | 2.23 | 0.71 | 1.12 |
| cinematic | 1.66 | 0.94 | 0.83 |
| mono | 1.59 | 0.81 | 0.67 |

结论：新增参数没有破坏 LUT 可近似性；`warm` 超过 2/255，导出流程会按既有规则
自动升到 65³。

## 4. GUI 布局检查

用 `runtime/ui_layout_check.py`（1284×781 窗口）实例化真实 UI 并载入测试照片：

- 直方图条 893×84，随画布宽度变化重绘；图例与高光裁切提示正常。
- 侧栏滚动视口 344×674，内容高度 878，滚动条生效；参数页 0 无控件溢出。
- 参数页签 2 个，滑条总数 16（11 + 5）。
- 截图：`runtime/ui-check.png`、`runtime/ui-check-split.png`；
  直方图单独渲染：`runtime/histogram-preview.png`。

## 5. 仍需人工验收

1. 目视确认直方图配色、图例与照片观感（自动测试只能验证像素分布）。
2. 分离色调页签在 100% 与 200% 缩放下是否可读。
3. 风格预设按钮连点后，文本框内容是否仍然可编辑、可清空。
4. 窗口最小尺寸（1120×760）下，直方图与画布比例是否合适。
