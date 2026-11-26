# ADR-004：在编码 sRGB 域查表，不启用隐式 sRGB 转换

## 状态

已采用（P0）。

## 背景

P0 只处理单帧 SDR sRGB JPEG/PNG。图像加载后统一为直通（非预乘）RGBA8，像素值是
编码 sRGB。3D LUT 的 domain 也以编码 sRGB `[0,1]` 表示。若 GPU 管线或帧缓冲自动
做 sRGB 编解码，而 CPU 参考实现不做，同一张 LUT 会得到两套结果。

> 后续扩展（MPO/WebP/TIFF、视频帧）仍然遵守本 ADR，见
> `ADR-008-media-types-and-video.md`。

## 决策

1. 2D 图像纹理与 3D LUT 纹理都按普通 `GL_RGBA8` / `GL_RGB8` 使用，不启用
   `GL_FRAMEBUFFER_SRGB`。
2. 着色器直接对编码 sRGB 值做 domain 映射、voxel-center 校正、三线性采样和强度
   混合，输出仍是编码 sRGB。
3. `grade.frag` 只执行 `clamp`，不做 gamma、色调映射或隐式色彩空间转换。
4. ICC 转换只在 Python 加载阶段做一次；没有 ICC 的普通 SDR 图按 sRGB 解释并在
   UI 中说明。
5. Log/相机 Log LUT 不会被自动识别；导入外部 LUT 时明确提示按 sRGB 解释。

## 后果

- GPU 输出与 CPU 参考可以直接逐像素比较（T01/T03 的 ≤1/255 门槛）。
- 任意隐式色彩管理都必须显式改写本 ADR，并同步更新 CPU 参考与测试。
- 本工程不声称支持 HDR、广色域工作流或专业 Log 管线。
