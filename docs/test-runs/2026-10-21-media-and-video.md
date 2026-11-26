# 2026-10-21 素材类型扩展（MPO 修复 + 视频）

本轮起因：用户打开一张手机照片时报
`IMAGE_INVALID: P0 仅支持单帧 JPEG/PNG，当前文件格式为 MPO`。
排查后确认这是**普通手机照片**被误拒，不是异常输入；顺带把素材类型扩展到视频。

## 1. 静态图：从“只认 JPEG/PNG”到“能解就收”

| 容器 | 处理方式 |
| --- | --- |
| JPEG / PNG | 与原来一致 |
| MPO | 手机常见容器（JPEG 主图 + 景深/增益图）；只解第 1 帧并在状态行说明 |
| WebP / BMP / TIFF | 直接解码为 RGBA8 |
| GIF / 多帧 WebP/TIFF | 取第 1 帧并提示“只使用第 1 帧” |
| HEIC / HEIF / AVIF | 未装 `pillow-heif` 时给出安装命令，而不是 Pillow 的 `cannot identify image file` |

APNG 仍然拒绝：动画 PNG 的语义通常是动画本身，而不是“照片里附带另一张图”。

关键改动：

- `DECODABLE_FORMATS` / `MULTIFRAME_OK` 明确“能解”和“允许取首帧”是两个集合。
- `_check_container()` 改为返回提示字符串，提示随 `SourceImage.notes` 进入状态行。
- `Image.open` 抛 `UnidentifiedImageError` 时按扩展名给可执行提示（HEIF 专项）。
- 尺寸/模式/文件大小限制、EXIF 1–8、ICC→sRGB 全部保持原行为。

实测（GUI，真实 `load_path`）：

```
container: MPO
notes: ['MPO 多图容器：只使用主图（第 1 帧），不读取景深/增益图']
status: 已载入 1200×900 · assumed-srgb · 174 ms · MPO 多图容器：…
```

## 2. 视频：取帧调色 + LUT 重编码

不实现实时播放器，而是沿用“一帧一调色”的工作流：

1. `ffprobe` 读时长、帧率、尺寸、色彩矩阵、旋转、是否含音频。
2. `ffmpeg` 解出当前时间点的一帧 PNG（BT.709 → RGB），交给原有静态图管线。
3. 时间轴拖动 → 220 ms 防抖 + token 丢弃过期结果；参数与 revision 保留。
4. “导出视频”：先用现有 `export_lut` 烘焙并回读校验 `.cube`，再用
   `lut3d` + libx264 重编码；音频转 AAC；进度来自 `-progress pipe:1`。
5. 取消 → kill 编码进程并删除 `.partial`；失败保留 stderr 最后一行作为错误。

新增 `app/video_io.py`（probe / extract_frame / export_graded / 指纹），
`AppState.video` + `video_time`，UI 增加视频时间轴条与“导出视频”按钮。
两者只在视频文档下出现/可用，静态图布局不变。

## 3. 实测数据（本机 ARM64 + Mesa 软渲染）

| 项目 | 结果 |
| --- | --- |
| 1080p 30fps 5 s 素材 → 单帧提取 | 0.39–0.57 s（冷启动首次 1.54 s） |
| 33³ LUT 烘焙（Python） | 1.04 s |
| 1080p 5 s → H.264 重编码（crf 18） | 11.6 s（约 0.43× 实时），输出 5.86 MB |
| 640×360 2 s 素材端到端（打开→拖动→导出） | 24.8 s（含 GUI 启动、LUT 校验烘焙） |
| 导出取消 | 无目标文件、无 `.partial` 残留 |

## 4. 过程中修掉的真实缺陷

1. **MPO 被整体拒绝**：手机照片打不开的直接原因。
2. **`.mp4.partial` 无法被 ffmpeg 识别容器**：改为 `name.partial.mp4`；
   否则报 `Error opening output files: Invalid argument`。
3. **跨线程 `root.after` 被 Tk 拒绝**：worker 线程改为投递 `queue.Queue`，
   主线程 `_poll` 每 40 ms 取出；否则拖动时间轴“看起来没反应”且无报错。
4. **seek 到片尾解不出帧**：回退一帧（低帧率时 50 ms），仍失败再退回 t=0。
5. **`timecode()` 把总时长之外的时间截断**：只保留非负钳制，格式化交给调用方。
6. **ffmpeg 管道未关闭**：显式 drain/close stdout 与 stderr，`-W error::ResourceWarning` 下干净。

## 5. 自动测试

```
python -W error::ResourceWarning -m unittest discover -s tests -q
Ran 150 tests in 37.3s
OK
```

- 新增 `tests/test_image_io.py` 5 项：MPO 主图、WebP/BMP/TIFF/GIF、多帧 GIF 提示、
  HEIF 提示、未知格式提示。
- 新增 `tests/test_video.py` 12 项：probe 元数据/非视频、取帧可加载、片尾钳制、
  时间码、LUT 实际生效（灰 128 → 158/149/140）、进度单调到 100%、
  无音频素材、取消无残留、坏文件、指纹区分、ffmpeg 缺失提示。

端到端（真实窗口 + 真实 worker）：

```
python runtime\ui_video_check.py
loaded: 640x360 2.00s 30.00fps
after scrub: t=1.50 rev=2
exported: …graded.mp4 · 2.00 s · 30.00 fps · 0.3 MB · H.264
OK: video open, scrub and graded export all worked
```

## 6. 仍未做（明确边界）

- 无实时视频预览/播放；预览始终是当前帧。
- HDR / Log / 杜比视界不做，视频按 BT.709 解释。
- 视频导出只能整段，没有入点/出点裁剪、缩放、码率/分辨率选项。
- 逐帧调色（关键帧、曲线动画）属于 P2；现在一段视频共用一组参数与一个 LUT。
- HEIF 需要用户自行安装可选的 `pillow-heif`。
