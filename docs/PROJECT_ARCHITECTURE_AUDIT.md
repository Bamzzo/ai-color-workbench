# AI 智能调色工作台（ai_color_app）现状与架构深度剖析

**文档性质：** 基于仓库真实源码的只读盘点（盘点日：2026-11-18）  
**代码根目录：** `<project-root>`  
**自动化基线：** `python -m unittest discover -s tests -q` → **Ran 204 tests … OK**（本机复跑 80.5s）

---

## 1. 工程全景与目录职责清单

### 1.1 目录树（排除 `.venv`、`__pycache__`、`build-*` 中间产物）

```
ai_color_app/
├── .env / .env.example          # AI 密钥与超时（不入库敏感值）
├── README.md                    # 环境、构建、运行与 P0/P1 范围说明
├── requirements.txt
├── requirements-lock.txt
├── run.ps1                      # 启动入口包装
├── CMakeLists.txt               # render_worker（C++）构建
├── glad.c                       # OpenGL 加载（与 worker 链接）
├── main.cpp                     # 仓库根遗留/别名（主 worker 在 engine/main.cpp）
├── identity17.cube              # 测试/自检用 LUT 样例
├── ai/                          # 自然语言 → ColorParams
├── app/                         # 桌面 UI、流水线、I/O、批处理编排
├── baker/                       # 参数数学、LUT 烘焙与 .cube 读写
├── engine/                      # C++ 离屏 OpenGL worker 源码
├── shaders/                     # GLSL（worker 使用）
├── presets/                     # 6 套离线 JSON 预设
├── schemas/                     # ColorParams JSON Schema v1/v2
├── tests/                       # 204 项单元/集成测试
├── docs/                        # ADR、验收记录、指导文档
└── runtime/                     # 运行态目录（jobs/cache/logs/test-fixtures/脚本）
    ├── jobs/                    # 每次渲染请求独立 job 目录（request/response/output.rgba）
    ├── cache/{preview,lut,full,video,external}/
    ├── logs/app.log
    ├── test-fixtures/
    └── *.py                     # UI/批次/导出门控等端到端检查脚本
```

> **说明：** `runtime/cache` 与 `runtime/jobs` 为运行产物，可清理；文档树中不展开具体缓存文件。

### 1.2 分模块核心文件职责

#### `app/`（Python 控制层 + Tkinter UI）

| 文件 | 职责 | 主要输入/输出 | 依赖 |
| --- | --- | --- | --- |
| `main.py` | 进程入口：DPI、日志、`ColorApp` | `argv` → `mainloop` | `ui.ColorApp`, `paths` |
| `ui.py` | 主窗口 `ColorApp`：布局、事件、预览/导出/AI/视频/批次 UI | Tk 事件 ↔ `AppState`、运行器结果 | `pipeline`, `jobs`, `state`, `ai.*`, `theme`, `batch_ui` |
| `batch_ui.py` | 批处理 `Toplevel`：队列表格、策略、取消/重试 | `BatchState` ↔ `batch` 调度器 | `batch`, `batch_export`, `theme` |
| `state.py` | 单文档状态与 **revision** 递增 | `ColorParams`、视图、视频时间点 | `baker.params`, `image_io`, `video_io` |
| `pipeline.py` | 预览/导出/LUT 烘焙编排 | `RenderSnapshot` → `PreviewResult`/`ExportResult` | `baker.*`, `engine_client`, `image_io` |
| `engine_client.py` | 启动 **一次性** `render_worker.exe` 子进程 | `request.json` → `response.json` + RGBA 文件 | `paths`, `image_io` |
| `jobs.py` | `LatestJobRunner`：预览 coalesce + 导出 FIFO | `submit(fn)` → `poll()` `JobOutcome` | 纯标准库 |
| `image_io.py` | 解码、规范化 sRGB、**ACRGBA01** 桥接文件 | 磁盘图像 ↔ `SourceImage` / RGBA | Pillow, numpy |
| `video_io.py` | ffprobe/ffmpeg：探针、抽帧、LUT 成片导出 | 视频路径 ↔ `VideoInfo` / 编码输出 | subprocess |
| `histogram.py` | 256-bin RGB/亮度直方图图元 | PIL 预览图 → `Histogram` → PIL 条带 | numpy |
| `batch.py` | 批次模型、FIFO 单消费者调度、取消语义 | `BatchTaskSnapshot` 队列 | `baker.params`（无 Tk） |
| `batch_export.py` | 单项批处理 worker 适配 | `BatchTaskSnapshot` → 输出路径 | `pipeline`, `video_io` |
| `paths.py` | 运行目录、worker 路径、缓存 LRU | 环境变量 / 默认 `build-arm64` | 文件系统 |
| `theme.py` | 深灰工作台 ttk `clam` 主题与 DWM 标题栏 | `tk.Tk` → `Theme` | ctypes (Win) |
| `widgets.py` | `Tooltip`、`StatusChip`、路径省略 | UI 辅助 | tk/ttk |

#### `ai/`

| 文件 | 职责 | 输入/输出 | 依赖 |
| --- | --- | --- | --- |
| `prompts.py` | System/User 提示词、风格预设文案 | 用户意图 + 当前参数 → 消息列表 | `ColorParams` |
| `provider.py` | `AIConfig`、`Proposal`、`load_config`、`build_provider` | `.env` → 配置 | `baker.params` |
| `deepseek.py` | HTTPS Chat Completions + JSON 校验 + 一次 repair | intent → `Proposal` | httpx, `parse_params_text` |
| `offline.py` | 关键词匹配 → `presets/*.json` | intent → `Proposal` | `load_preset` |

#### `baker/`

| 文件 | 职责 | 输入/输出 | 依赖 |
| --- | --- | --- | --- |
| `params.py` | **唯一**参数契约：Schema 校验、`ColorParams` | JSON/文件 → 归一化 dict | jsonschema |
| `color_transform.py` | `sdr-srgb-v2` 数学、`bake_lut`、`lut_grid` | `ColorParams` → float32 样本 | numpy |
| `cube_writer.py` | 原子写 `.cube`、导出校验 | samples → 磁盘 | numpy |
| `cube_reader.py` | 严格读 `.cube` → `CubeLut` | 路径 → `CubeLut` | numpy |

#### `engine/`（C++ worker，与 Python 通过 JSON + RGBA 文件通信）

| 文件 | 职责 |
| --- | --- |
| `main.cpp` | CLI：`--request`/`--response`/`--shaders`，解析协议、加载图像/LUT、调用 `GlRenderer`、写响应 |
| `gl_renderer.cpp/.h` | 隐藏 GLFW 窗口、上传 2D/3D 纹理、全屏三角绘制、读回 RGBA |
| `rgba_bridge.cpp/.h` | `ACRGBA01` 二进制 RGBA8 读写 |
| `json_lite.cpp/.h` | 无第三方 JSON 解析（请求/响应字段校验） |
| `cube.cpp/.h` | worker 侧 `.cube` 加载（与 Python 子集一致） |

#### `shaders/`

| 文件 | 职责 |
| --- | --- |
| `fullscreen.vert` | 全屏三角形，`vUv` 传递给片段着色器 |
| `grade.frag` | 2D 纹理采样 + 3D LUT 查找 + `uStrength` 混合，保留 alpha |

#### `presets/`

6 个 JSON，结构与 `ColorParams.to_document()` 一致（`schema_version` 2.0、`algorithm_version` `sdr-srgb-v2`）：`identity`, `warm`, `cool`, `soft`, `cinematic`, `mono`。

#### `schemas/`

| 文件 | 说明 |
| --- | --- |
| `color_params.v2.schema.json` | 当前 16 字段全量契约 |
| `color_params.v1.schema.json` | 遗留 7 字段；读取时缺失字段补 0 |

#### `tests/`（204 项）

| 模块 | 文件 | 约条数 | 覆盖重点 |
| --- | --- | ---: | --- |
| 批次 | `test_batch.py` | 35 | 调度、取消、状态机 |
| 批次导出 | `test_batch_export.py` | 9 | worker 适配 |
| 集成 | `test_matrix.py` | 31 | pipeline、runner、UI 互锁（mock） |
| 视频 | `test_video.py` | 12 | probe/抽帧/编码（条件跳过无 ffmpeg） |
| 图像 I/O | `test_image_io.py` | 27 | 解码、RGBA 桥、导出 |
| 引擎 | `test_engine.py` | 13 | `EngineClient` 协议（需 worker 或 mock） |
| 路径 | `test_paths.py` | 6 | 运行目录、缓存 |
| 直方图 | `test_histogram.py` | 6 | 256-bin 计算 |
| AI | `test_ai.py` | 17 | 提示词、离线、DeepSeek mock |
| 颜色数学 | `test_color.py` | 19 | `transform_rgb`、LUT 一致性 |
| 参数 | `test_params.py` | 15 | Schema、裁剪、预设 |
| LUT | `test_cube.py` | 14 | 读写 round-trip |
| 辅助 | `helpers.py` | — | fixture 路径、worker 探测 |

**运行命令：**

```powershell
cd .
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

**补充端到端脚本（非 unittest 计数）：** `runtime/ui_layout_check.py`、`ui_export_queue_check.py`、`batch_mixed_check.py`、`ui_video_check.py`、`ui_theme_check.py` 等（见 `docs/test-runs/`）。

---

## 2. 核心数据模型与参数契约（真实代码定义）

### 2.1 十六维调色参数（`baker/params.py` + Schema v2）

**算法版本常量：** `SCHEMA_VERSION = "2.0"`，`ALGORITHM_VERSION = "sdr-srgb-v2"`。

**字段清单、类型、范围（代码与 `schemas/color_params.v2.schema.json` 一致）：**

| 字段 | 类型 | 范围 | 默认 | 物理/语义（编码 sRGB 域） |
| --- | --- | --- | --- | --- |
| `exposure_ev` | float | [-2, 2] | 0 | 线性光曝光，约 1 EV = ×2 亮度 |
| `contrast` | float | [-100, 100] | 0 | 中灰对比（ADR-006 方向已修正） |
| `temperature` | float | [-100, 100] | 0 | 相对暖/冷（非开尔文） |
| `tint` | float | [-100, 100] | 0 | 品红/绿偏移 |
| `highlights` | float | [-100, 100] | 0 | 高光区 tone |
| `shadows` | float | [-100, 100] | 0 | 阴影区 tone |
| `whites` | float | [-100, 100] | 0 | 最亮 ~10% tone |
| `blacks` | float | [-100, 100] | 0 | 最暗 ~10% tone（正=抬黑位） |
| `saturation` | float | [-100, 100] | 0 | 全局饱和度，-100=灰度 |
| `vibrance` | float | [-100, 100] | 0 | 低饱和区优先增强 |
| `hue` | float | [-180, 180] | 0 | 全局色相旋转（度） |
| `split_shadow_hue` | float | [0, 360] | 0 | 分离色调：阴影色相 |
| `split_shadow_amount` | float | [0, 100] | 0 | 阴影着色强度 |
| `split_highlight_hue` | float | [0, 360] | 0 | 高光色相 |
| `split_highlight_amount` | float | [0, 100] | 0 | 高光着色强度 |
| `split_balance` | float | [-100, 100] | 0 | 分离色调平衡 |

**源码摘录（字段注册与不可变模型）：**

```python
# baker/params.py（节选）
PARAM_KEYS = (
    "exposure_ev", "contrast", "temperature", "tint",
    "highlights", "shadows", "whites", "blacks",
    "saturation", "vibrance", "hue",
    "split_shadow_hue", "split_shadow_amount",
    "split_highlight_hue", "split_highlight_amount", "split_balance",
)

@dataclass(frozen=True)
class ColorParams:
    exposure_ev: float = 0.0
    contrast: float = 0.0
    # … 共 16 个字段，默认均为 0.0 …
    split_balance: float = 0.0

    def with_updates(self, **updates: float) -> "ColorParams":
        # 合并 → normalize_params → dataclass replace
```

校验入口：`validate_params_document()` / `parse_params_text()`；禁止 NaN、重复 JSON 键、布尔伪装数字。

### 2.2 3D LUT、内存顺序与 `.cube`

**网格顺序（R 最快，B 最慢）：**

```python
# baker/color_transform.py — lut_grid()
# samples 形状 (N^3, 3)，.cube 行序：R 变化最快，B 最慢
b, g, r = np.meshgrid(values, values, values, indexing="ij")
samples = np.stack([r.ravel(), g.ravel(), b.ravel()], axis=1)
```

`baker/cube_reader.py` 中 `CubeLut.samples` 注释：`shape (N^3, 3), R fastest`。C++ `main.cpp` 自检构造 LUT 使用相同三重循环 `(b, g, r)` 与索引 `(b*n*n + g*n + r)*3`。

**尺寸：**

- 预览路径：固定 **33³**（`pipeline._params_preview_lut`）。
- 导出 `.cube`：先试 33³，若 `verify_exported_effect` 最大 8-bit 差 > 2 则升到 **65³**（`pipeline.export_lut`）。
- 合法范围：**[2, 65]**（`cube_writer.write_cube`）。

**.cube 文本格式（写入）：**

1. `TITLE "…"`
2. `LUT_3D_SIZE N`
3. `DOMAIN_MIN` / `DOMAIN_MAX`（默认 [0,0,0]–[1,1,1]）
4. `N³` 行，每行三个 float（9 位有效数字）

**强度（Strength）：** GPU 在着色器中 `mix(src, mapped, uStrength)`；预览/导出请求把 `strength` 传给 worker。导出用户 LUT 时对网格顶点做 `apply_strength` 烘焙。

### 2.3 预设文件结构（`presets/*.json`）

统一文档：

```json
{
  "schema_version": "2.0",
  "algorithm_version": "sdr-srgb-v2",
  "params": { /* 16 个数值，见上表 */ }
}
```

`list_presets()` 固定顺序：`identity, warm, cool, soft, cinematic, mono`（UI 离线预设按钮与 `OfflineProvider` 共用）。

### 2.4 应用状态（`app/state.py`）

```python
@dataclass
class AppState:
    document_id: str = ""
    revision: int = 0
    source: SourceImage | None = None
    preview_image: Image.Image | None = None
    params: ColorParams = field(default_factory=ColorParams.identity)
    strength: float = 1.0
    mode: Mode = "params"  # Literal["params", "external_lut"]
    external_lut: CubeLut | None = None
    saved_params: ColorParams = field(default_factory=ColorParams.identity)
    split_t: float = 1.0
    show_split: bool = False
    hold_original: bool = False
    zoom: float = 0.0  # 0 = fit
    pan_x: float = 0.0
    pan_y: float = 0.0
    last_completed_revision: int = -1
    busy_revision: int | None = None
    preview_is_scaled: bool = False
    source_label: str = "手动"
    last_error: str = ""
    dirty: bool = False
    video: VideoInfo | None = None
    video_time: float = 0.0
```

**历史记录 / Undo / Redo：** **未实现**。`README.md` 明确列为 P1；代码中无 undo 栈。参数变更通过 `bump_color()` 递增 `revision`，用于渲染与导出归属，**不是**可回退历史。

**增量 Delta：** AI 与手动均产出**完整** `ColorParams` 替换（`set_params` / `_apply_proposal`），无参数字段级 delta 协议。

---

## 3. 核心业务数据流与调用链

### 3.1 自然语言 AI 调色链路

```
用户输入 (ui.ai_text)
  → ColorApp.submit_ai()
      → build_provider(AIConfig)  # ai/provider.py
      → LatestJobRunner("ai").submit(..., provider.generate, coalesce_key="ai")
  → DeepSeekProvider.generate() 或 OfflineProvider.generate()
      → build_user_message(intent, current_params)  # ai/prompts.py
      → HTTP POST（在线）或关键词→load_preset（离线）
      → parse_params_text(content)  # baker/params.py
      → Proposal(params, summary, source, provider, model)
  → ColorApp._poll() → _handle_ai(JobOutcome)
      → _apply_proposal: state.params=…, bump_color(), _sync_sliders_from_state()
      → _start_preview(immediate=True)
```

**要点：**

- 在线失败可弹窗走 `OfflineProvider`（`messagebox.askyesno`）。
- 若返回时 `revision`/`document_id` 已变，提案进入 `_pending_proposal`，需用户点「应用结果」。
- AI 与预览一样走 `LatestJobRunner`，主线程 40ms `_poll` 轮询。

### 3.2 LUT 烘焙与实时预览链路

```
滑块/强度/模式变更
  → state.set_params / set_strength / … → bump_color()
  → _schedule_preview()  # ui.py, PREVIEW_DEBOUNCE_MS = 60
  → _start_preview()
      → RenderSnapshot.from_state(state)
      → runner.submit("preview", pipeline.render_preview, coalesce=True)
```

**`RenderPipeline.render_preview`：**

1. `preview_rgba_path(source)` — 缓存 `runtime/cache/preview/{fingerprint}-1280.rgba`
2. `_params_preview_lut(params)` — `bake_lut(33)` → `write_cube` 到 `runtime/cache/lut/{sha256}.cube`
3. `EngineClient.render(...)` — 子进程 GPU
4. 返回 `PreviewResult` → `_handle_preview` → `_processed_preview`、直方图失效、`_redraw()`

**防抖/节流：**

| 机制 | 位置 | 行为 |
| --- | --- | --- |
| 预览 debounce 60ms | `ui._schedule_preview` | `after_cancel` + 单次 `after(60, _start_preview)` |
| 预览 job coalesce | `jobs.LatestJobRunner` | 同 `coalesce_key="preview"` 只保留最新，取消在飞 |
| 滑块松手立即预览 | `Scale <ButtonRelease-1>` | `_start_preview(immediate=True)` |
| LUT 磁盘缓存 | `lut_cache_key` + LRU | 相同 canonical 参数复用 .cube |
| 导出 FIFO 不合并 | `coalesce=False` | 导出任务顺序执行 |

**直方图：** 在 `_redraw()` / `_refresh_histogram()` 中，对 `_composite_preview()` 像素调用 `compute_histogram` + `render_histogram`（主线程 numpy，非 GPU）。

### 3.3 A/B 分屏与视口交互

**内存：**

- `_original_preview`：当前帧原图（PIL RGBA）
- `_processed_preview`：最近一次成功 GPU 输出
- 显示合成：`_composite_preview()`  
  - `hold_original` → 原图  
  - `show_split` → `split_t` 左侧原图、右侧效果图（PIL paste）  
  - 否则效果图

**状态字段：** `AppState.split_t` [0,1]、`show_split`、`hold_original`、`zoom`、`pan_x/y`。

**绘制：** `tk.Canvas` 上 `create_image`；几何 `_display_geometry()`：fit 或 `zoom`、中心 + pan。鼠标：左键拖 A/B 竖线（`split_t`）、中键/逻辑 pan、滚轮缩放（`_on_wheel`）。

**与引擎：** 分割在 **Python PIL 合成**，非 shader；GPU 只产出整幅效果图。

### 3.4 视频与批量任务

#### 单素材视频（预览）

**不是**实时解码播放管线，而是 **按时间点 ffmpeg 抽帧 → 当作静图调色**：

```
打开视频 → video_io.probe
  → extract_frame → load_source_image → pipeline.prepare_preview
  → state.video / video_time
```

**“播放”：** `_toggle_video_playback` → `after(~1000/fps)` 递增 `video_time` → `_seek_video_now` → 后台线程 `_video_seek_worker` → `_start_preview`。即 **逐帧离线抽帧 + 每帧完整 LUT 渲染**，受取帧与 GPU 耗时限制，非流畅实时播放器。

**视频导出：** `export_video` → `pipeline.export_lut` 写临时 `.cube` → `video_io.export_graded`（ffmpeg `lut3d` 滤镜全片编码）。

#### 批量（`batch.py` + `batch_export.py` + `batch_ui.py`）

```
BatchWindow 收集条目与 OutputPlan
  → plan_batch / BatchScheduler（单消费者 FIFO）
  → BatchExportWorker(snapshot): pipeline.export_image 或 bake cube + export_graded
  → BatchUpdate 回 UI 线程刷新 Treeview
```

与单素材互锁：批处理运行期 `ColorApp._batch_active` 阻止单素材导出/预览队列（见 `ui._schedule_preview`）。

---

## 4. Python 与 C++ OpenGL 渲染引擎通信协议

### 4.1 进程模型

| 项目 | 实现 |
| --- | --- |
| 进程形态 | **每次渲染拉起新子进程**，非常驻 daemon |
| 可执行文件 | `render_worker.exe`（`paths.worker_path()`：`AI_COLOR_WORKER` → `build-arm64/Debug` 等） |
| 命令行 | `render_worker --request <abs.json> --response <abs.json> --shaders <dir>` |
| 自检 | `--selftest`（不经过 request 文件） |

### 4.2 控制协议（`protocol_version` **1.0**）

**请求（Python 写入 `job_dir/request.json`）：**

```json
{
  "protocol_version": "1.0",
  "job_id": "job-<uuid>",
  "document_id": "<doc-id>",
  "revision": <int>,
  "operation": "render",
  "input_rgba": "<absolute path>",
  "lut_path": "<absolute path>",
  "strength": <0..1>,
  "output_rgba": "<absolute path under same job_dir>"
}
```

**响应（`response.json`）：**

- 成功：`status: "ok"`, `output_rgba`, `metrics.render_readback_ms`
- 失败：`status: "error"`, `error: {code, message, stage}`

Python `EngineClient` 校验 `job_id` / `document_id` / `revision` 一致后读取输出 RGBA。

### 4.3 像素传递（非共享内存）

| 环节 | 格式 |
| --- | --- |
| Python → 磁盘 | `image_io.write_rgba_bridge`：magic `ACRGBA01` + 4×uint32 头 + RGBA8 行优先 |
| Worker 读入 | `loadRgbaFile`（`rgba_bridge.cpp`） |
| Worker 写出 | `writeRgbaFileAtomic` → Python `read_rgba_bridge` |

**瓶颈（典型）：** 每帧 **子进程启动 + GLFW/GL 初始化 + 纹理上传 + 3D LUT 上传 + 全图 draw + glReadPixels**；`metrics.render_readback_ms` 回传 UI（状态栏可见）。快速拖动滑块时 coalesce 取消在飞任务，但 worker 仍可能排队。

**安全约束（C++）：** 输出路径与 `response.json` 必须与 `request.json` **同一 job 目录**（防路径逃逸）。

### 4.4 着色器与 Uniform

**`shaders/fullscreen.vert`（核心）：** `gl_VertexID` 全屏三角，`vUv = 0.5 * (p + 1)`。

**`shaders/grade.frag`（核心 + Uniform）：**

```glsl
uniform sampler2D uImage;      // 绑定 GL_TEXTURE0
uniform sampler3D uLut;      // 绑定 GL_TEXTURE1
uniform vec3 uDomainMin;
uniform vec3 uDomainMax;
uniform float uLutSize;
uniform float uStrength;
```

逻辑：编码 sRGB 输入 → 域归一化 → 体素中心校正 → `texture(uLut, tc)` → `mix(src, mapped, uStrength)`，**alpha 原样保留**。

`GlRenderer::render` 另设：`GL_FRAMEBUFFER_SRGB` **关闭**（ADR-004 编码域一致）。

---

## 5. 当前前端 UI 实现现状与痛点诊断（`app/ui.py`）

### 5.1 技术栈与布局

| 项 | 现状 |
| --- | --- |
| GUI | **Python 标准库 Tkinter + ttk**（非 PySide/Qt/Gradio） |
| 主题 | `app/theme.py`：`clam` 自绘 + `Palette` 令牌 + Win DWM 深色标题栏 |
| 入口类 | `ColorApp`（约 2700+ 行，单文件承载绝大多数交互） |

**组件树（grid 概览）：**

```
root (tk.Tk)
├── row0 toolbar (ttk.Frame): 打开/批处理/导入LUT | 导出图/视频/LUT | 重置/直方图 | 素材标签/引擎状态
├── row1 body (ttk.Frame)
│   ├── col0 预览区: Canvas + 直方图条 + 视频条(可隐藏) + A/B 对比行
│   └── col2 侧栏: Canvas+Scrollbar 内嵌 Frame（素材/AI/离线预设/参数 Notebook/强度/摘要）
└── row2 status: 对比控件 | busy | 四 StatusChip | message
```

批处理：`batch_ui.BatchWindow`（`Toplevel`），逻辑与 `batch.py` 分离。

### 5.2 样式实现方式

- 集中：`theme.apply(root)` 配置 `TButton`、`TScale`、`Treeview`、`Notebook` 等。
- 画布/直方图：原生 `tk.Canvas` / `tk.Label` + 硬编码色（`histogram.py` 与 `Palette.canvas`）。
- 预览图：`ImageTk.PhotoImage` 贴到 Canvas（**位图刷新**，非纹理管线）。

### 5.3 工程视角：质感与结构性限制

**为何偏「轻 / Air」：**

- Tk/ttk 原生控件纹理与圆角能力有限，即使 `clam` 仍偏「工具对话框」而非专业 NLE/调色台密度。
- 预览为 **CPU 侧 PIL 合成 + PhotoImage 全量刷新**，无 GPU 预览链路与色彩管理显示链路。
- 字体依赖 `tk scaling` 与系统字体，高 DPI 下靠 `Theme.px()` 补偿，但与 Web/CSS 或 Qt 密度系统仍有差距。

**高 DPI：** 已实现 `winfo_fpixels` 缩放、`minsize` 按 scale 放大；极限场景需人工验收（见 `docs/test-runs/2026-11-11-ui-manual-acceptance.md`）。

**异步与等待反馈：** `LatestJobRunner` + 40ms poll + debounce 可用，但长时间操作（视频导出、批处理）仍主要靠状态文案与 `busy_var`；无统一进度模型（视频导出除外有 `_video_progress` 轮询）。

**视频实时播放：** **结构性不支持**真正实时解码+GPU 调色回放；当前为定时取帧 + 每帧完整渲染，帧率受 I/O 与 worker 启动约束，无法「边播边调」达到播放器体验。

**动态调色预览：** 参数变更 → 烘焙 33³ LUT（磁盘）→ 启 worker → 读回整图；延迟毫秒～秒级，不适合 60fps 交互式预览。

---

## 6. 前后端分离与 HTML + WebGL2 升级接口评估

**前提（用户目标）：** 保持 `ai/`、`baker/`、C++ `engine/` 核心不变；前端改为 **HTML/CSS/TS + WebGL2**（暗房 UI、波形 loading、视频边播边调、动态 A/B）。

### 6.1 可直接包装为 REST / WebSocket 的能力

| 层 | 函数/模块 | 建议 API 形态 |
| --- | --- | --- |
| 参数 | `parse_params_text`, `ColorParams`, `canonical_params` | `POST /api/params/validate` |
| AI | `build_provider().generate` | `POST /api/ai/propose`（异步 job id + WS 推送） |
| 预设 | `load_preset`, `list_presets` | `GET /api/presets` |
| LUT 烘焙 | `bake_lut`, `export_params_lut` | `POST /api/lut/bake` → 返回 `.cube` 或 float32 blob |
| 渲染 | `RenderPipeline.render_preview` / `export_*` | `POST /api/render/preview`（返回 PNG/WebP 或 RGBA 二进制） |
| 媒体 | `image_io.load_source_image`, `video_io.probe`, `extract_frame` | `POST /api/media/open` multipart |
| 批次 | `batch.plan_batch`, scheduler API | `POST /api/batch/sessions` + WS 进度 |
| 直方图 | `compute_histogram` | `GET /api/histogram?document=…` 或随预览 JSON 返回 bins |

### 6.2 与旧 UI 强耦合、需剥离的部分

| 耦合点 | 说明 | 剥离建议 |
| --- | --- | --- |
| `ColorApp` 单体 | 状态、.runner、pipeline、Tk 变量、`PhotoImage` 生命周期混在一起 | 抽出 `DocumentSession` 服务类（纯 Python，无 tk） |
| `RenderSnapshot.from_state(AppState)` | 依赖 UI 填充的 `preview_image` | 改为 `RenderSnapshot.from_document(DocumentSession)` |
| 文件对话框/消息框 | `filedialog`, `messagebox` 散落 `ui.py` | API 层接收路径/JSON，浏览器侧选文件 |
| `_poll` 40ms 合并 | UI 专用 | Web：WS 推送或 SSE；仍可用同一 `LatestJobRunner` 在服务端 |
| 导出互锁 / `_export_tickets` | 产品规则内嵌 UI | 移到 `DocumentSession` 或 `ExportGate` 模块（tests 已部分覆盖逻辑） |
| `theme` / `StatusChip` | 纯表现 | 留在废弃 Tk 路径或删除；Web 自有设计系统 |
| Worker 路径 | 服务端本地磁盘 job 目录 | API 返回 `job_id` + 签名 URL 或流式响应；**浏览器 WebGL2 预览可不经过 worker**（见下） |

**WebGL2 预览路径决策：**

- **方案 A（推荐初期）：** 浏览器用 **同一套 GLSL 逻辑**（`grade.frag` 移植）+ 3D LUT 纹理（由 API 返回 `lut` 二进制或 33³ RGB float）；视频用 **WebCodecs / MSE + 每帧 LUT**。不再每帧启动 `render_worker.exe`。
- **方案 B：** 保留 C++ worker 在服务端，API 返回渲染 PNG —— 简单但难以「边播边调」低延迟。

`baker/color_transform.py` 必须在服务端保留为 **LUT 真值**（ADR-003）；Web 侧 LUT 应由服务器烘焙，避免双实现漂移。

### 6.3 建议的后端适配器拆分（保持 204 测试通过）

```
ai_color_app/
├── core/                    # 可选重命名：从 app 抽出无 Tk 部分
│   ├── state.py             # AppState → DocumentState（可保留别名）
│   ├── pipeline.py
│   ├── jobs.py
│   ├── batch.py
│   ├── batch_export.py
│   ├── image_io.py
│   ├── video_io.py
│   ├── engine_client.py
│   └── session.py           # 新：导出互锁、revision、提案队列（从 ui 迁出）
├── api/                     # 新：FastAPI
│   ├── main.py
│   ├── routes_media.py
│   ├── routes_render.py
│   ├── routes_ai.py
│   └── routes_batch.py
├── desktop/                 # 原 app/ui.py + theme + batch_ui + main.py
│   └── ...
├── baker/ ai/ engine/       # 不动
└── tests/                   # 保持 import 路径：可保留 app 包为 facade re-export
```

**测试隔离策略：**

1. **204 项 unittest 不依赖 Tk 主循环** 的模块占多数；`test_matrix.py` 部分用 mock `ColorApp` —— 迁移时把被测逻辑挪到 `session.py` 后测试跟移。
2. 新增 `api/` 测试用 `TestClient`，**不替代**现有 204 项，作为附加层。
3. `desktop` 变薄：仅调用 `session` + `pipeline`，保证 `runtime/*_check.py` 仍可通过 `python -m app.main` 启动（或 `python -m desktop.main`  shim）。
4. **禁止**为 Web 修改 `baker/params.py` 契约与 `engine` 协议，除非 ADR 修订。

---

## 7. 风险、证据链与迁移验收清单

### 7.1 架构风险摘要

| 风险 | 级别 | 依据 |
| --- | --- | --- |
| 单文件 UI 回归成本高 | 高 | `ui.py` 体量与业务交织 |
| 每帧子进程渲染延迟 | 高 | `EngineClient` 设计；阻碍 Web「实时」体验 |
| 视频预览非真播放 | 中 | `ui` 取帧 + 全量渲染路径 |
| Mesa worker 退出 `glfwTerminate` 异常 | 低（已缓解） | `ExitProcess` 绕过 |
| AI 与手动参数双轨无 undo | 中 | 产品 P1 缺口 |
| 双端色彩：编码 sRGB 非显示 ICC | 中 | ADR-004/005 明确 |

### 7.2 证据与复核命令

```powershell
# 单元测试
.\.venv\Scripts\python.exe -m unittest discover -s tests -q

# Worker 自检
build-arm64\Debug\render_worker.exe --selftest

# UI/批次门控（示例）
.\.venv\Scripts\python.exe runtime\ui_export_queue_check.py
.\.venv\Scripts\python.exe runtime\batch_mixed_check.py
```

### 7.3 HTML/WebGL2 迁移阶段性验收

1. **阶段 0：** `session` 抽离 + 204 tests 仍全绿。  
2. **阶段 1：** FastAPI 暴露 `validate` / `propose` / `bake_lut` / `preview`（返回图像字节）。  
3. **阶段 2：** 前端 WebGL2 使用服务端 LUT，A/B 在 fragment shader 完成（摆脱 PIL paste）。  
4. **阶段 3：** 视频 WebCodecs + 共享 LUT；批处理改 WS 进度。  
5. **阶段 4：** 可选保留 Tk 桌面为瘦客户端或弃用。

---

**文档维护：** 当 `PARAM_KEYS`、协议 `1.0`、`render_worker` CLI 或测试数量变化时，应更新本章并复跑 `unittest discover` 记录新计数。