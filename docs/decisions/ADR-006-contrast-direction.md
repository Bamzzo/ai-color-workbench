# ADR-006：对比度指数方向修正（v1 → v1.1）

## 状态

已采用（P0）。这是对交接规格公式的有意偏离，已单独记录。

## 背景

交接规格给出的对比度步骤为：

```
p = 2 ** (contrast / 100)
c = 0.5 + 0.5 * sign(2c-1) * |2c-1| ** p
```

当 `c` 在 `(0,1)` 内时 `|2c-1| < 1`。此时 `p > 1` 会把中间调**压向** 0.5，
也就是正对比度反而降低对比度；负对比度则展开。这与规格对 `contrast` 的正负语义
（`+` 增强对比度）相反，也与 `test_contrast_direction` 的验收方向相反。

## 决策

自 `sdr-srgb-v1.1` 起使用倒数指数：

```
p = 2 ** (-contrast / 100)
```

- 正对比度：`p < 1`，暗部更暗、亮部更亮，0 和 1 保持不动。
- 负对比度：`p > 1`，向 0.5 收敛。
- 端点 0/1 仍然精确不变。

同时更新了：

- `baker/params.py` 的 `ALGORITHM_VERSION`
- `schemas/color_params.v1.schema.json` 中的 `algorithm_version` 常量
- 四个预设文件
- AI 系统提示中的示例文档
- LUT 缓存键（版本号进入 canonical JSON，旧缓存自然失效）

## 证据

- `tests/test_color.py::test_contrast_direction`：0.25 → 更小，0.75 → 更大。
- `tests/test_color.py::test_contrast_keeps_endpoints`：0/1 不变。
- `tools/measure_lut.py`：33³ LUT 相对直接公式的最大误差 ≤ 2.4/255（T08 门槛 8）。

## 如果评审要求逐字复现规格公式

需要把指数改回 `2 ** (contrast / 100)`，将版本号降回 `sdr-srgb-v1`，并反转
`test_contrast_direction` 的期望。除此之外没有其他代码依赖该方向；但 UI 的滑块
“+”方向会与用户直觉相反，因此默认不采用该方案。
