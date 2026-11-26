# ADR-003：参数语义由 Python 独占，C++ worker 只应用 LUT

## 状态

已采用（P0）。

## 背景

调色参数（曝光、对比度、色温、色调、高光、阴影、饱和度以及后续新增的白色、
黑色、自然饱和、色相旋转、分离色调，强度）需要同时服务于预览、导出、LUT 导出
和 AI 校验。如果 Python 与 GLSL 各写一份公式，任何一次修改都会引入两套结果，且
很难证明导出与预览一致。

## 决策

1. 参数到颜色的全部数学只存在于 `baker/color_transform.py`，版本号为
   `sdr-srgb-v2`（v1.1 见 ADR-006/007 的历史说明）。
2. Python 把参数烘焙成 3D LUT（`.cube`），并负责强度混合、缓存键和导出校验。
3. `render_worker.exe` 不接收参数值，只接收“输入 RGBA + LUT + 强度”，在 GLSL 中
   做三线性查表与强度混合。
4. CPU 参考实现 `sample_lut()` / `apply_effect_to_rgb()` 与 GPU 使用相同的
   voxel-center 映射，用于测试和导出比对。

## 后果

- 修改参数公式必须同时提升 `ALGORITHM_VERSION`，使 LUT 缓存键失效。
- worker 协议保持稳定，不需要为每个新参数改 C++ 代码。
- 参数模式的预览与导出都经过同一张 33³/65³ LUT；LUT 近似误差由 T08 单独度量，
  不与 GPU 采样正确性混为一谈。
- 外部 LUT 模式绕过参数公式，直接把用户 LUT 交给同一个着色器。
