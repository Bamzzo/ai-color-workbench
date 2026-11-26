# ADR-008：素材类型扩展（多图容器 + 视频帧）

## 状态

已采用（P1 扩展，非课程 P0 范围）。

## 背景

原始实现只接受 Pillow 报出 `JPEG` 或 `PNG` 的单帧文件。实际拍摄的手机照片
经常是 **MPO**（Multi-Picture Object：JPEG 主图 + 景深/增益图），Pillow 的
`format` 会报 `MPO` 而不是 `JPEG`，于是普通手机照片被整体拒绝，报
“P0 仅支持单帧 JPEG/PNG，当前文件格式为 MPO”。

视频是自然的下一步：调色工作流里“先调一帧、再套到整段素材”很常见，而
ffmpeg 的 `lut3d` 滤镜可以直接复用我们导出的 `.cube`。

## 决策

1. **静态图接受任何 Pillow 能解到 8 位 RGB(A) 的容器**：JPEG、PNG、MPO、
   WebP、BMP、TIFF、GIF，以及安装了可选 `pillow-heif` 时的 HEIF/AVIF。
   模式检查（拒绝 16 位/浮点/CMYK）和尺寸检查保持不变。
2. **多图容器取第 1 帧并明确提示**：MPO 提示“只使用主图，不读取景深/增益图”；
   GIF/WebP/TIFF 多帧提示“只使用第 1 帧”。APNG 仍然拒绝，因为动画 PNG 的
   语义通常是动画而非“带附加图的照片”。
3. **缺少 HEIF 插件时给可执行提示**，而不是 Pillow 的
   `cannot identify image file`。
4. **视频是“取帧调色 + LUT 重编码”**，不是实时播放器：
   - 打开视频时用 ffprobe 读取时长/帧率/尺寸/色彩矩阵，用 ffmpeg 解出一帧 PNG，
     走与静态图完全相同的加载、预览、直方图与渲染路径。
   - 时间轴拖动只更新“当前帧”，参数与 revision 保留。
   - “导出视频”先用现有 `export_lut` 烘焙并校验 `.cube`，再把整段素材通过
     `lut3d` + libx264 重新编码；音频转 AAC，进度来自 ffmpeg `-progress`。
5. **ffmpeg 是可选外部依赖**：缺失时只禁用视频功能并给出安装提示，
   静态图路径完全不受影响。

## 后果

- 缓存需要区分“视频帧”：帧文件按 `视频指纹 + 时间码 + 长边` 命名，落在
  `runtime/cache/video/`；原有的 320 MB LRU 上限同样覆盖它。
- 视频帧的上限是单边 8192 像素（8K 仍在 40 MP 预算内）。
- 视频导出是单线程 FIFO 任务，可取消；取消时删除 `.partial` 文件。
- 预览并不实时：拖动时间轴每次约等于一次静态图加载，因此 UI 先做 220 ms
  防抖，再用 token 丢弃过期帧。
- 颜色管理仍是“编码 sRGB 域”：FFmpeg 按 BT.709 把 YUV 解到 RGB，LUT 在该域
  生效；HDR/杜比视界不在此范围。
