# AI 智能调色工作台：结课论文技术规格总归档

审计日期：2026-11-21（Asia/Shanghai）。源码根目录：`<project-root>`。本文件依据当前磁盘源码与既存实验输出归档，不将开发规划、注释愿景或旧交付结论自动视为已实现。

执行边界：原仓库业务代码、测试、配置和原始 Benchmark 零修改；唯一交付为本文。为防止 unittest 的 fixture/cache 和 npm 的 dist/tsbuildinfo 写回仓库，验证在临时项目副本执行，使用原项目 `.venv` Python 和复制的当前前端依赖，未安装或升级依赖。未重新运行五维 Benchmark、在线付费请求和阶段七浏览器验收。历史完整 Benchmark 记录时间为 2026-11-18，阶段七矩阵为 2026-11-20。

下文源码代码块为直接摘录；`文件:行号` 对应本次扫描位置。精确表格由 JSON 生成，不补充原文件未保存的小数。结论限于指定机器、参数和样本；“通过”不等于所有功能都有端到端自动化覆盖。

## 1. 工程全貌与代码规模统计

### 1.1 实际工程组成

工程同时保留 Tkinter/ttk 桌面前端（`app/main.py → ColorApp`）与 TypeScript DOM/Canvas2D/WebGL2 前端（`frontend/src/main.ts → mountWorkbench`）。Web 前端没有 React/Vue；其交互预览在浏览器完成，FastAPI 负责 AI、LUT 烘焙、媒体和导出。C++ worker 用于后端 LUT 应用，浏览器不会为每个视频帧调用它。

`CMakeLists.txt` 指定 C++17，编译五个 `engine/*.cpp` 与 `glad.c`；根目录历史 `main.cpp` 明确不参加构建。当前没有 `baker/presets.py` / `baker/cube_io.py` / `CommandHistory` 类，实际对应 `baker/params.py`、`cube_reader.py` / `cube_writer.py`、`DocumentSession` / `StateStore`。

### 1.2 完整过滤目录树

排除 `.venv`、`node_modules`、`__pycache__`、`dist`、`build`、`build-*`、`.git` 与整个 `runtime`，保留点文件名称但不读取 `.env` 内容。Benchmark 原始目录在第六章单独核对；本归档文件不计入核心源码。

```text
ai_color_app/
  ai/
    __init__.py
    deepseek.py
    offline.py
    prompts.py
    provider.py
  api/
    __init__.py
    envelope.py
    job_runner.py
    media_store.py
    server.py
  app/
    __init__.py
    batch.py
    batch_export.py
    batch_ui.py
    engine_client.py
    histogram.py
    image_io.py
    jobs.py
    main.py
    paths.py
    pipeline.py
    session.py
    state.py
    theme.py
    ui.py
    video_io.py
    widgets.py
  baker/
    __init__.py
    color_transform.py
    cube_reader.py
    cube_writer.py
    params.py
  docs/
    decisions/
      ADR-003-python-owns-parameter-math.md
      ADR-004-encoded-srgb-pipeline.md
      ADR-005-local-images-only.md
      ADR-006-contrast-direction.md
      ADR-007-params-v2.md
      ADR-008-media-types-and-video.md
      ADR-009-local-log-paths.md
      ADR-010-batch-workspace.md
      ADR-011-dark-workbench-ui.md
    test-runs/
      evidence/
        2026-11-11-ui-acceptance/
          01-main-long-name.png
          02-main-video-ab.png
          03-batch-long-names.png
          05-batch-window-fixed.png
      2026-10-20-baseline.md
      2026-10-20-v2-enhancements.md
      2026-10-21-hardening.md
      2026-10-21-media-and-video.md
      2026-11-11-phase-a-export-gate.md
      2026-11-11-phase-b-logic.md
      2026-11-11-phase-b-ui.md
      2026-11-11-ui-manual-acceptance.md
    PROJECT_ARCHITECTURE_AUDIT.md
    PROJECT_ARCHITECTURE_AUDIT_V2.md
    STAGE6_DEEP_AUDIT_REPORT.md
    STAGE7_ACCEPTANCE_REPORT.md
    THIRD-PARTY.md
    UI优化与打磨_开发Agent提示词.md
    优化空间扫描与开发评估清单.md
    后续开发指导文档.md
  engine/
    cube.cpp
    cube.h
    gl_renderer.cpp
    gl_renderer.h
    json_lite.cpp
    json_lite.h
    main.cpp
    rgba_bridge.cpp
    rgba_bridge.h
  frontend/
    src/
      app/
        workbench.ts
      components/
        histogram_view.ts
        icons.ts
        media_stage.ts
        param_panel.ts
        preset_grid.ts
        rgb_wave_loader.ts
        top_toolbar.ts
        viewport_hud.ts
      core/
        gl_viewport.ts
        lut_cube_view.ts
        params.ts
        state_store.ts
      services/
        api_client.ts
        job_watch.ts
      theme/
        layout.css
        tokens.css
      utils/
        debounce.ts
      main.ts
      vite-env.d.ts
    index.html
    package-lock.json
    package.json
    tsconfig.json
    tsconfig.node.json
    tsconfig.tsbuildinfo
    vite.config.ts
  presets/
    cinematic.json
    cool.json
    identity.json
    mono.json
    soft.json
    warm.json
  schemas/
    color_params.v1.schema.json
    color_params.v2.schema.json
  shaders/
    fullscreen.vert
    grade.frag
  tests/
    __init__.py
    helpers.py
    test_ai.py
    test_api.py
    test_batch.py
    test_batch_export.py
    test_color.py
    test_cube.py
    test_engine.py
    test_histogram.py
    test_image_io.py
    test_matrix.py
    test_params.py
    test_paths.py
    test_session.py
    test_video.py
  tools/
    benchmark/
      __init__.py
      common.py
      dataset.py
      dim1_speedup.py
      dim2_lut.py
      dim3_interp.py
      dim4_quality.py
      dim5_ai.py
      interpolation.py
      metrics.py
      offline_baseline.json
      report.py
      visualization.py
    __init__.py
    acceptance_stage6_histogram.py
    acceptance_stage7_matrix.py
    check_config.py
    measure_large_image.py
    measure_lut.py
    run_benchmark.py
  .env
  .env.example
  .gitignore
  ai_color_output.ppm
  CMakeLists.txt
  glad.c
  identity17.cube
  main.cpp
  README.md
  requirements-lock.txt
  requirements.txt
  run.ps1
  start_web.ps1
  docs/FINAL_PROJECT_SPEC_FOR_PAPER.md  ← 本次唯一新增归档
```

### 1.3 规模统计与可复算口径

物理 LOC=`splitlines()` 行数。有效 SLOC=删除注释与空行后仍含源码的物理行数：Python 用 tokenize 去注释、AST 去模块/类/函数首个 docstring；赋值的提示词/着色器多行字符串仍算代码。C++/TS/GLSL 保护字符串后去除 `//` 与 `/*…*/`；括号独占行、预处理指令算代码。TS 内嵌 GLSL 仅计入 TS，不重复累计。该口径不是逻辑语句数。

下表模块互斥，包含空 `__init__.py` 的文件数量；核心合计不含第三方生成 `glad.c`、根历史 `main.cpp`、CSS、JSON、docs、依赖和构建产物。辅助源码另列，避免第三方自动生成代码放大项目规模。

| 模块 | 文件数 | 物理 LOC | 有效 SLOC |
| --- | --- | --- | --- |
| C++ 引擎（含头文件） | 9 | 1812 | 1593 |
| 独立 GLSL 着色器 | 2 | 39 | 24 |
| Python app 控制/媒体/桌面层 | 17 | 7954 | 6582 |
| Python FastAPI 层 | 5 | 865 | 709 |
| Python AI 层 | 5 | 1116 | 915 |
| Python LUT 烘焙层 | 5 | 1119 | 871 |
| TypeScript 前端 src（含 .d.ts） | 18 | 3836 | 3442 |
| 自动化测试（含 fixtures helpers） | 16 | 3862 | 3189 |
| Benchmark 实验脚本 | 13 | 3434 | 2802 |
| 其他测量/配置/验收工具 | 6 | 749 | 619 |
| 核心合计 | 96 | 24786 | 20746 |

| 补充（不计核心） | 物理 LOC | 有效 SLOC |
| --- | --- | --- |
| frontend/src/theme/layout.css | 1172 | 1012 |
| frontend/src/theme/tokens.css | 42 | 32 |
| frontend/vite.config.ts | 27 | 25 |
| glad.c | 1140 | 1069 |
| main.cpp | 79 | 62 |

统计函数原文（输入为相对路径和UTF-8文本；核心目录/后缀分组见上表）：

```python
import ast, io, tokenize, re
def sloc(rel,txt):
 if rel.endswith('.py'):
  lines=txt.splitlines(keepends=True);off=[0]
  for l in lines:off.append(off[-1]+len(l))
  chars=list(txt)
  def blank(a,b):
   for i in range(a,b):
    if chars[i] not in '\r\n':chars[i]=' '
  for t in tokenize.generate_tokens(io.StringIO(txt).readline):
   if t.type==tokenize.COMMENT:blank(off[t.start[0]-1]+t.start[1],off[t.end[0]-1]+t.end[1])
  for node in ast.walk(ast.parse(txt)):
   if isinstance(node,(ast.Module,ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and node.body:
    s=node.body[0]
    if isinstance(s,ast.Expr) and isinstance(s.value,ast.Constant) and isinstance(s.value.value,str):blank(off[s.lineno-1]+s.col_offset,off[s.end_lineno-1]+s.end_col_offset)
  stripped=''.join(chars)
 else:
  pat=r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|(/\*[\s\S]*?\*/|//[^\n]*)'''
  stripped=re.sub(pat,lambda m:m.group(1) if m.group(1) else re.sub(r'[^\r\n]',' ',m.group(2)),txt)
 return sum(bool(x.strip()) for x in stripped.splitlines())
```

### 1.4 每个核心文件的职责与真实符号索引

**`ai/__init__.py`** — Python包入口/标识。 LOC=0，SLOC=0。

入口/类型：无顶层公开定义。依赖：无导入。

**`ai/deepseek.py`** — DeepSeekProvider HTTP Chat Completions、重试、一次Schema修复、本地严格解析。 LOC=241，SLOC=211。

入口/类型：`_Retryable@27`；`DeepSeekProvider@42`。依赖：`__future__`, `json`, `logging`, `random`, `threading`, `time`, `uuid`, `httpx`, `baker.params`, `.prompts`, `.provider`。

**`ai/offline.py`** — OfflineProvider数值赋值/风格模板/局部极性/增量/极值规则。 LOC=516，SLOC=416。

入口/类型：`_ParamSpec@175`；`OfflineProvider@407`。依赖：`__future__`, `re`, `threading`, `dataclasses`, `baker.params`, `.provider`。

**`ai/prompts.py`** — 系统提示词、三条示例、六条StylePreset意图和当前参数消息。 LOC=173，SLOC=142。

入口/类型：`StylePreset@100`；`build_user_message(intent: str, current_params: ColorParams | dict[str, Any])@140`；`preset_text(key: str)@158`。依赖：`__future__`, `json`, `dataclasses`, `typing`, `baker.params`。

**`ai/provider.py`** — AIConfig、Proposal、AIError、环境配置与provider工厂。 LOC=186，SLOC=146。

入口/类型：`AIError@13`；`Proposal@21`；`AIConfig@30`；`load_config(env_file: str | Path | None=None)@98`；`summary_from_params(params: ColorParams)@142`；`build_provider(config: AIConfig)@163`。依赖：`__future__`, `os`, `dataclasses`, `pathlib`, `urllib.parse`, `baker.params`。

**`api/__init__.py`** — Python包入口/标识。 LOC=5，SLOC=2。

入口/类型：无顶层公开定义。依赖：`.server`。

**`api/envelope.py`** — code/message/data统一信封与HTTP错误JSONResponse。 LOC=21，SLOC=15。

入口/类型：`ok(data: Any=None, message: str='ok')@8`；`err(code: int, message: str, data: Any=None, http_status: int=400)@12`。依赖：`__future__`, `typing`, `fastapi.responses`。

**`api/job_runner.py`** — 进程内JobRecord注册表，每项daemon thread，无持久任务队列。 LOC=102，SLOC=83。

入口/类型：`JobStatus@11`；`JobRecord@20`；`create_job(kind: str)@35`；`get_job(job_id: str)@42`；`update_job(job_id: str, **kwargs: Any)@47`；`run_job(job_id: str, fn: Callable[[Callable[[float], None]], Any])@56`；`clear_jobs_for_tests()@100`。依赖：`__future__`, `threading`, `time`, `uuid`, `dataclasses`, `enum`, `typing`。

**`api/media_store.py`** — 上传落盘、MediaRecord、index.json原子持久化/恢复。 LOC=190，SLOC=150。

入口/类型：`MediaRecord@21`；`load_index()@108`；`register(record: MediaRecord)@127`；`get(media_id: str)@133`；`save_upload(filename: str, data: bytes)@138`；`content_url(media_id: str, *, base: str='')@175`；`clear_registry_for_tests()@181`。依赖：`__future__`, `json`, `shutil`, `threading`, `uuid`, `dataclasses`, `pathlib`, `typing`, `app`。

**`api/server.py`** — FastAPI路由和Pydantic请求，适配AI/LUT/媒体/导出。 LOC=547，SLOC=459。

入口/类型：`get_pipeline()@58`；`ParamsValidateBody@66`；`AiProposeBody@70`；`LutBakeBody@76`；`HistogramBody@81`；`ExportImageBody@86`；`ExportVideoBody@93`；`ExportLutBody@99`；`api_presets()@127`；`api_validate(body: ParamsValidateBody)@136`；`api_ai_propose(body: AiProposeBody)@150`；`api_lut_bake(body: LutBakeBody)@174`；`api_lut_upload_cube(file: UploadFile=File(...))@190`；`api_media_upload(file: UploadFile=File(...))@220`；`api_media_content(media_id: str)@245`；`api_histogram(body: HistogramBody)@253`；`api_export_image(body: ExportImageBody)@318`；`api_export_video(body: ExportVideoBody)@348`；`api_export_lut(body: ExportLutBody)@446`；`api_job_status(job_id: str)@486`；`api_job_download(job_id: str)@506`；`ws_job(websocket: WebSocket, job_id: str)@517`。依赖：`__future__`, `base64`, `hashlib`, `tempfile`, `uuid`, `pathlib`, `typing`, `numpy`, `fastapi`, `fastapi.middleware.cors`, `fastapi.responses`, `pydantic`, `ai.offline`, `ai.provider`, `baker.params`, `baker.color_transform`, `baker.cube_reader`, `app`, `app.pipeline`, `.`, `.job_runner`, `.media_store`。

**`app/__init__.py`** — Python包入口/标识。 LOC=0，SLOC=0。

入口/类型：无顶层公开定义。依赖：无导入。

**`app/batch.py`** — 批次模型、输出冲突规划、冻结任务快照、单消费者FIFO与取消/重试；BatchState→BatchPlan→BatchUpdate。 LOC=828，SLOC=616。

入口/类型：`MediaKind@44`；`ItemStatus@49`；`can_transition(current: ItemStatus, target: ItemStatus)@86`；`Strategy@92`；`ConflictPolicy@100`；`BatchPlanError@106`；`OutputPlan@116`；`BatchItem@148`；`BatchTaskSnapshot@192`；`BatchRecord@212`；`BatchPlan@228`；`same_path(left: Path, right: Path)@245`；`BatchState@250`；`plan_target(item: BatchItem, output: OutputPlan, *, taken: Iterable[str]=())@419`；`plan_batch(batch: BatchState)@451`；`BatchCancelled@526`；`UpdateKind@530`；`BatchUpdate@552`；`BatchRunner@588`；`detect_kind(path: Path | str)@820`。依赖：`__future__`, `itertools`, `os`, `threading`, `time`, `uuid`, `collections`, `dataclasses`, `enum`, `pathlib`, `queue`, `typing`, `baker.params`。

**`app/batch_export.py`** — BatchExportWorker将BatchTaskSnapshot送入pipeline图片导出或ffmpeg视频导出；返回Path，每项释放像素/临时cube。 LOC=146，SLOC=113。

入口/类型：`BatchExportWorker@28`。依赖：`__future__`, `logging`, `time`, `pathlib`, `baker.cube_reader`, `.`, `.batch`, `.pipeline`。

**`app/batch_ui.py`** — Tk BatchWindow，列表导入、策略、统一/逐项参数、输出设置与队列操作。 LOC=1118，SLOC=999。

入口/类型：`BatchWindow@76`。依赖：`__future__`, `queue`, `os`, `threading`, `time`, `tkinter`, `pathlib`, `PIL`, `.`, `.widgets`, `.batch`, `.batch_export`。

**`app/engine_client.py`** — EngineClient启动一次性worker、JSON文件协议/取消/超时/身份验证，返回RenderOutcome。 LOC=218，SLOC=189。

入口/类型：`EngineError@19`；`RenderOutcome@28`；`EngineClient@37`。依赖：`__future__`, `json`, `shutil`, `subprocess`, `threading`, `time`, `dataclasses`, `pathlib`, `typing`, `PIL`, `.`。

**`app/histogram.py`** — NumPy/Pillow直方图：Image→Histogram→RGB曲线图。 LOC=191，SLOC=146。

入口/类型：`Histogram@32`；`compute_histogram(image: Image.Image)@59`；`render_histogram(current: Histogram | None, original: Histogram | None, width: int, height: int, *, supersample: int=2)@123`。依赖：`__future__`, `dataclasses`, `numpy`, `PIL`。

**`app/image_io.py`** — EXIF/ICC图像规范化、预乘alpha缩放、RGBA桥与原子PNG/JPEG写出。 LOC=439，SLOC=346。

入口/类型：`ImageError@65`；`SourceImage@73`；`srgb_profile_bytes()@86`；`file_fingerprint(path: str | Path)@94`；`load_source_image(path: str | Path)@216`；`make_preview(rgba: Image.Image, long_side: int=PREVIEW_LONG_SIDE)@304`；`write_rgba_bridge(path: str | Path, rgba: Image.Image)@316`；`read_rgba_bridge(path: str | Path)@336`；`save_png_atomic(rgba: Image.Image, target: str | Path)@370`；`save_jpeg_atomic(rgba: Image.Image, target: str | Path, quality: int=95)@393`；`default_export_path(source: Path, extension: str)@419`；`is_same_file(a: str | Path, b: str | Path)@423`；`estimate_rgba_bytes(width: int, height: int)@430`；`clamp_preview_size(width: int, height: int, long_side: int)@434`。依赖：`__future__`, `hashlib`, `io`, `math`, `os`, `struct`, `uuid`, `dataclasses`, `pathlib`, `numpy`, `PIL`。

**`app/jobs.py`** — LatestJobRunner：latest-wins预览与不丢弃FIFO导出，fn(cancel)→JobOutcome。 LOC=212，SLOC=163。

入口/类型：`JobSpec@30`；`JobOutcome@41`；`LatestJobRunner@52`。依赖：`__future__`, `queue`, `threading`, `time`, `collections`, `dataclasses`, `typing`。

**`app/main.py`** — 桌面入口、DPI awareness、日志、Tk mainloop。 LOC=86，SLOC=65。

入口/类型：`main(argv: list[str] | None=None)@47`。依赖：`__future__`, `ctypes`, `logging`, `sys`, `tkinter`, `pathlib`, `app`, `app.ui`。

**`app/paths.py`** — 运行路径、worker发现、任务目录、缓存老化/LRU回收。 LOC=183，SLOC=140。

入口/类型：`PathError@23`；`ensure_runtime()@27`；`worker_path()@41`；`check_worker()@61`；`new_job_dir(prefix: str='job')@72`；`cleanup_old_jobs(max_age_hours: float=24.0)@80`；`cache_usage(root: Path | None=None)@129`；`prune_cache(max_bytes: int=CACHE_LIMIT_BYTES, min_age_seconds: float=CACHE_MIN_AGE_SECONDS, root: Path | None=None)@140`；`preview_cache_path(fingerprint: str, long_side: int)@178`；`lut_cache_path(key: str)@182`。依赖：`__future__`, `os`, `shutil`, `time`, `pathlib`。

**`app/pipeline.py`** — RenderSnapshot与RenderPipeline：33³预览、全尺寸图像导出、33/65³ LUT误差验证、视频cube。 LOC=338，SLOC=294。

入口/类型：`RenderSnapshot@34`；`PreviewResult@61`；`ExportResult@70`；`RenderPipeline@79`。依赖：`__future__`, `json`, `threading`, `dataclasses`, `pathlib`, `typing`, `PIL`, `baker.color_transform`, `baker.cube_reader`, `baker.cube_writer`, `baker.params`, `.`, `.engine_client`, `.image_io`, `.state`。

**`app/session.py`** — 无Tk业务层DocumentSession：64快照历史、AI提案、导出ticket与门控。 LOC=187，SLOC=141。

入口/类型：`ExportTicket@23`；`ColorSnapshot@33`；`DocumentSession@59`。依赖：`__future__`, `dataclasses`, `typing`, `ai.provider`, `baker.params`, `.state`。

**`app/state.py`** — AppState：文档ID/revision/参数/模式/视口/视频状态。 LOC=109，SLOC=91。

入口/类型：`AppState@22`。依赖：`__future__`, `uuid`, `dataclasses`, `pathlib`, `typing`, `PIL`, `baker.cube_reader`, `baker.params`, `.image_io`, `.video_io`。

**`app/theme.py`** — Tk Palette/Theme、ttk样式、DPI单位与Windows暗标题栏。 LOC=528，SLOC=384。

入口/类型：`Palette@35`；`Theme@77`；`apply_dark_titlebar(window: tk.Misc)@112`；`bind_dark_titlebar(window: tk.Misc)@150`；`ui_scale(root: tk.Misc)@170`；`apply(root: tk.Misc)@201`；`contrast_ratio(foreground: str, background: str)@508`。依赖：`__future__`, `tkinter`, `dataclasses`。

**`app/ui.py`** — ColorApp桌面编排：异步预览/AI/导出、视频抽帧播放、分屏/拖动和批次入口。 LOC=2755，SLOC=2396。

入口/类型：`ColorApp@94`。依赖：`__future__`, `logging`, `queue`, `threading`, `time`, `tkinter`, `dataclasses`, `pathlib`, `numpy`, `PIL`, `ai.offline`, `ai.prompts`, `ai.provider`, `baker.cube_reader`, `baker.params`, `.`, `.histogram`, `.image_io`, `.jobs`, `.pipeline`, `.session`, `.state`, `.widgets`。

**`app/video_io.py`** — ffprobe探测→VideoInfo；ffmpeg抽帧/整片lut3d重编码→Path/进度。 LOC=468，SLOC=385。

入口/类型：`VideoError@46`；`VideoInfo@54`；`ffmpeg_bin()@79`；`ffprobe_bin()@88`；`availability()@97`；`probe(path: str | Path)@139`；`frame_cache_path(fingerprint: str, time_s: float, long_side: int)@216`；`extract_frame(path: str | Path, time_s: float, target: str | Path, *, info: VideoInfo | None=None, long_side: int=MAX_FRAME_SIDE)@222`；`export_graded(path: str | Path, cube_path: str | Path, target: str | Path, *, info: VideoInfo | None=None, quality: int=18, preset: str='medium', on_progress: Callable[[float], None] | None=None, cancel_event: threading.Event | None=None)@290`；`content_fingerprint(path: Path)@447`；`quick_fingerprint(path: Path)@456`。依赖：`__future__`, `hashlib`, `json`, `logging`, `os`, `re`, `shutil`, `subprocess`, `threading`, `dataclasses`, `pathlib`, `typing`。

**`app/widgets.py`** — 路径省略、Tooltip与StatusChip。 LOC=148，SLOC=114。

入口/类型：`shorten_middle(text: str, limit: int, *, keep_tail: int | None=None)@15`；`shorten_path(path: Path | str, limit: int)@24`；`Tooltip@35`；`StatusChip@128`。依赖：`__future__`, `tkinter`, `pathlib`。

**`baker/__init__.py`** — Python包入口/标识。 LOC=0，SLOC=0。

入口/类型：无顶层公开定义。依赖：无导入。

**`baker/color_transform.py`** — sdr-srgb-v2数学真值、LUT烘焙、三线性/强度/重采样。 LOC=349，SLOC=237。

入口/类型：`hue_to_rgb(hue_degrees: float)@28`；`srgb_decode(encoded: np.ndarray)@70`；`srgb_encode(linear: np.ndarray)@76`；`transform_rgb(rgb: np.ndarray, params: ColorParams)@86`；`lut_grid(n: int)@185`；`bake_lut(params: ColorParams, n: int=33)@199`；`apply_strength(samples: np.ndarray, n: int, strength: float)@206`；`bake_lut_with_strength(params: ColorParams, n: int=33, strength: float=1.0)@219`；`sample_lut(samples: np.ndarray, n: int, rgb: np.ndarray, domain_min: tuple[float, float, float]=(0.0, 0.0, 0.0), domain_max: tuple[float, float, float]=(1.0, 1.0, 1.0))@263`；`apply_effect_to_rgb(rgb: np.ndarray, samples: np.ndarray, n: int, strength: float=1.0, domain_min: tuple[float, float, float]=(0.0, 0.0, 0.0), domain_max: tuple[float, float, float]=(1.0, 1.0, 1.0))@278`；`apply_effect_to_rgba(rgba: np.ndarray, samples: np.ndarray, n: int, strength: float=1.0, domain_min: tuple[float, float, float]=(0.0, 0.0, 0.0), domain_max: tuple[float, float, float]=(1.0, 1.0, 1.0))@293`；`resample_effect(samples: np.ndarray, n_in: int, n_out: int, strength: float, domain_min: tuple[float, float, float]=(0.0, 0.0, 0.0), domain_max: tuple[float, float, float]=(1.0, 1.0, 1.0))@311`；`algorithm_version()@331`。依赖：`__future__`, `math`, `numpy`, `.params`。

**`baker/cube_reader.py`** — 严格.cube子集解析→CubeLut(float32/domain/hash)。 LOC=218，SLOC=186。

入口/类型：`CubeError@32`；`CubeLut@40`；`load_cube(path: str | Path)@89`。依赖：`__future__`, `hashlib`, `math`, `dataclasses`, `pathlib`, `numpy`。

**`baker/cube_writer.py`** — 原子.cube写/回读、strength合入与效果误差校验。 LOC=194，SLOC=161。

入口/类型：`CubeWriteError@16`；`write_cube(path: str | Path, size: int, samples: np.ndarray, *, title: str='ai_color_app', domain_min: tuple[float, float, float]=(0.0, 0.0, 0.0), domain_max: tuple[float, float, float]=(1.0, 1.0, 1.0), verify: bool=True)@31`；`export_params_lut(params: ColorParams, strength: float, path: str | Path, size: int=33, title: str='ai_color_app params')@103`；`verify_exported_effect(exported: CubeLut, *, params: ColorParams | None=None, source_samples: np.ndarray | None=None, source_size: int | None=None, source_domain_min: tuple[float, float, float]=(0.0, 0.0, 0.0), source_domain_max: tuple[float, float, float]=(1.0, 1.0, 1.0), strength: float=1.0)@148`。依赖：`__future__`, `math`, `os`, `pathlib`, `numpy`, `.color_transform`, `.cube_reader`, `.params`。

**`baker/params.py`** — 16参数唯一Python契约、v1/v2校验、canonical/cache key及六套预设。 LOC=358，SLOC=287。

入口/类型：`ParamError@111`；`_DuplicateKey@132`；`strict_json_loads(text: str)@149`；`validate_params_document(document: Any)@194`；`normalize_params(params: Mapping[str, Any])@225`；`parse_params_text(text: str)@236`；`load_params_file(path: str | Path)@240`；`ColorParams@250`；`canonical_params(params: ColorParams | Mapping[str, Any])@300`；`lut_cache_key(params: ColorParams | Mapping[str, Any], n: int, domain_min: tuple[float, float, float], domain_max: tuple[float, float, float], strength: float)@319`；`load_preset(name: str)@339`；`list_presets()@345`。依赖：`__future__`, `json`, `math`, `dataclasses`, `pathlib`, `typing`, `jsonschema`。

**`engine/cube.cpp`** — C++ LUT子集读取；诊断写出函数不在正常导出链路使用。 LOC=312，SLOC=280。

**`engine/cube.h`** — 对应C++实现的公开结构/函数/类声明，第二章摘录。 LOC=30，SLOC=18。

**`engine/gl_renderer.cpp`** — 隐藏GLFW上下文、GLSL编译、纹理/FBO/像素回读。 LOC=380，SLOC=338。

**`engine/gl_renderer.h`** — 对应C++实现的公开结构/函数/类声明，第二章摘录。 LOC=41，SLOC=28。

**`engine/json_lite.cpp`** — 浅JSON扫描器，无外部JSON依赖。 LOC=285，SLOC=265。

**`engine/json_lite.h`** — 对应C++实现的公开结构/函数/类声明，第二章摘录。 LOC=35，SLOC=19。

**`engine/main.cpp`** — wmain请求校验、路径包含约束、调用渲染/响应提交、ExitProcess。 LOC=556，SLOC=503。

**`engine/rgba_bridge.cpp`** — ACRGBA01头验证、原子像素文件写出。 LOC=143，SLOC=125。

**`engine/rgba_bridge.h`** — 对应C++实现的公开结构/函数/类声明，第二章摘录。 LOC=30，SLOC=17。

**`frontend/src/app/workbench.ts`** — 三栏DOM、AI/LUT/媒体网络编排、导出/快捷键/模式交互。 LOC=632，SLOC=555。

**`frontend/src/components/histogram_view.ts`** — 288×110 Canvas2D直方图，screen混合、120ms缓动。 LOC=167，SLOC=144。

**`frontend/src/components/icons.ts`** — 内联SVG图标。 LOC=22，SLOC=21。

**`frontend/src/components/media_stage.ts`** — A/B拉手/标签，输出舞台屏幕ratio。 LOC=83，SLOC=68。

**`frontend/src/components/param_panel.ts`** — 三组details滑杆，input更新/change入历史，双击精确值。 LOC=160，SLOC=144。

**`frontend/src/components/preset_grid.ts`** — 离线预设按钮及高亮，回调PresetItem。 LOC=94，SLOC=85。

**`frontend/src/components/rgb_wave_loader.ts`** — Canvas2D三相RGB波形与120ms淡出。 LOC=97，SLOC=89。

**`frontend/src/components/top_toolbar.ts`** — 单文件导入/四模式/撤销重做/导出菜单与进度。 LOC=228，SLOC=210。

**`frontend/src/components/viewport_hud.ts`** — HUD缩放/强度/晕光/视频播放暂停/seek；FPS文本为素材帧率。 LOC=259，SLOC=229。

**`frontend/src/core/gl_viewport.ts`** — GlViewport媒体纹理、三阶段Bloom/合成、实时直方图和RAF。 LOC=1010，SLOC=929。

**`frontend/src/core/lut_cube_view.ts`** — LutCubeView 17³映射点云/MVP/深度与轨道交互。 LOC=511，SLOC=469。

**`frontend/src/core/params.ts`** — 前端16维键/范围/中文名/三组分类/clamp。 LOC=109，SLOC=101。

**`frontend/src/core/state_store.ts`** — StateStore订阅、params/strength历史、media/模式/bloom。 LOC=145，SLOC=120。

**`frontend/src/main.ts`** — 引入CSS并挂载工作台。 LOC=7，SLOC=6。

**`frontend/src/services/api_client.ts`** — fetch信封、FormData、base64→Float32Array和URL构造。 LOC=191，SLOC=166。

**`frontend/src/services/job_watch.ts`** — WS+800ms轮询，幂等终态结算和下载。 LOC=101，SLOC=89。

**`frontend/src/theme/layout.css`** — 三栏布局、舞台/HUD/卡片/响应式样式。 LOC=1172，SLOC=1012。

**`frontend/src/theme/tokens.css`** — 暗房灰阶/银白强调色/三色/玻璃/字体/尺寸tokens。 LOC=42，SLOC=32。

**`frontend/src/utils/debounce.ts`** — timeout尾沿防抖，LUT请求220ms。 LOC=10，SLOC=10。

**`frontend/src/vite-env.d.ts`** — Vite客户端类型声明。 LOC=10，SLOC=7。

**`frontend/vite.config.ts`** — Vite5173，HTTP/WS代理8765，生产dist与sourcemap。 LOC=27，SLOC=25。

**`glad.c`** — 第三方自动生成GL loader，CMake编入，但不计自有核心规模。 LOC=1140，SLOC=1069。

**`main.cpp`** — 历史单文件原型，不参与当前CMake。 LOC=79，SLOC=62。

**`shaders/fullscreen.vert`** — gl_VertexID全屏三角形与UV。 LOC=10，SLOC=7。

**`shaders/grade.frag`** — domain/体素中心/LUT采样/strength混合，保留alpha。 LOC=29，SLOC=17。

**`tests/__init__.py`** — Python包入口/标识。 LOC=0，SLOC=0。

入口/类型：无顶层公开定义。依赖：无导入。

**`tests/helpers.py`** — unittest自动化测试/夹具；逐用例清单见第六章。 LOC=101，SLOC=79。

入口/类型：`ensure_fixtures()@15`；`make_snapshot_image(width: int=32, height: int=24)@75`；`write_params_document(path: Path, **overrides: float)@85`；`load_rgba_array(image: Image.Image)@100`。依赖：`__future__`, `pathlib`, `numpy`, `PIL`, `app`。

**`tests/test_ai.py`** — unittest自动化测试/夹具；逐用例清单见第六章。 LOC=330，SLOC=280。

入口/类型：`FakeTransport@35`；`DeepSeekTests@55`；`ConfigAndOfflineTests@228`。依赖：`__future__`, `json`, `os`, `tempfile`, `threading`, `unittest`, `pathlib`, `httpx`, `ai.deepseek`, `ai.offline`, `ai.provider`, `baker.params`。

**`tests/test_api.py`** — unittest自动化测试/夹具；逐用例清单见第六章。 LOC=168，SLOC=144。

入口/类型：`ApiTests@24`。依赖：`__future__`, `base64`, `time`, `unittest`, `pathlib`, `numpy`, `fastapi.testclient`, `api.media_store`, `api.job_runner`, `api.server`, `baker.params`。

**`tests/test_batch.py`** — unittest自动化测试/夹具；逐用例清单见第六章。 LOC=586，SLOC=484。

入口/类型：`_StubWorker@72`；`_BatchFixture@122`；`BatchModelTests@155`；`BatchPlanTests@255`；`BatchRunnerTests@401`。依赖：`__future__`, `shutil`, `tempfile`, `threading`, `time`, `unittest`, `dataclasses`, `pathlib`, `app`, `app.batch`, `baker.params`。

**`tests/test_batch_export.py`** — unittest自动化测试/夹具；逐用例清单见第六章。 LOC=247，SLOC=204。

入口/类型：`_Recorder@30`；`_Pipeline@40`；`BatchExportWorkerTests@84`；`RunnerCancellationMappingTests@216`。依赖：`__future__`, `shutil`, `tempfile`, `threading`, `time`, `unittest`, `pathlib`, `types`, `PIL`, `app`, `app.batch`, `app.batch_export`, `app.engine_client`, `app.image_io`, `app.pipeline`, `baker.params`。

**`tests/test_color.py`** — unittest自动化测试/夹具；逐用例清单见第六章。 LOC=165，SLOC=136。

入口/类型：`ColorTransformTests@11`。依赖：`__future__`, `unittest`, `numpy`, `baker`, `baker.params`。

**`tests/test_cube.py`** — unittest自动化测试/夹具；逐用例清单见第六章。 LOC=128，SLOC=102。

入口/类型：`CubeReaderTests@22`；`CubeWriterTests@102`。依赖：`__future__`, `tempfile`, `unittest`, `pathlib`, `numpy`, `baker.cube_reader`, `baker.cube_writer`。

**`tests/test_engine.py`** — unittest自动化测试/夹具；逐用例清单见第六章。 LOC=395，SLOC=345。

入口/类型：`setUpModule()@25`；`WorkerTestCase@35`；`SamplingTests@89`；`ProtocolErrorTests@206`。依赖：`__future__`, `struct`, `tempfile`, `threading`, `unittest`, `pathlib`, `numpy`, `PIL`, `app`, `app.engine_client`, `baker.color_transform`, `baker.cube_writer`, `baker.params`。

**`tests/test_histogram.py`** — unittest自动化测试/夹具；逐用例清单见第六章。 LOC=71，SLOC=53。

入口/类型：`HistogramTests@19`。依赖：`__future__`, `unittest`, `numpy`, `PIL`, `app.histogram`。

**`tests/test_image_io.py`** — unittest自动化测试/夹具；逐用例清单见第六章。 LOC=365，SLOC=300。

入口/类型：`ImageLoadTests@50`；`ImageExportTests@258`。依赖：`__future__`, `struct`, `tempfile`, `unittest`, `zlib`, `pathlib`, `numpy`, `PIL`, `app`, `app.image_io`。

**`tests/test_matrix.py`** — unittest自动化测试/夹具；逐用例清单见第六章。 LOC=850，SLOC=692。

入口/类型：`setUpModule()@33`；`PipelineTests@38`；`JobRunnerTests@224`；`BusyStatusTests@370`；`PollIsolationTests@554`；`MaterialSwitchGateTests@632`；`AiGenerationTests@741`；`StateTests@796`。依赖：`__future__`, `queue`, `shutil`, `tempfile`, `threading`, `time`, `unittest`, `pathlib`, `numpy`, `PIL`, `app`, `app.engine_client`, `app.image_io`, `app.jobs`, `app.pipeline`, `app.state`, `baker.color_transform`, `baker.cube_reader`, `baker.cube_writer`, `baker.params`, `tests`。

**`tests/test_params.py`** — unittest自动化测试/夹具；逐用例清单见第六章。 LOC=126，SLOC=104。

入口/类型：`ParamsTests@9`。依赖：`__future__`, `json`, `unittest`, `baker`。

**`tests/test_paths.py`** — unittest自动化测试/夹具；逐用例清单见第六章。 LOC=83，SLOC=65。

入口/类型：`CachePruneTests@14`。依赖：`__future__`, `os`, `tempfile`, `time`, `unittest`, `pathlib`, `app`。

**`tests/test_session.py`** — unittest自动化测试/夹具；逐用例清单见第六章。 LOC=41，SLOC=32。

入口/类型：`SessionTests@11`。依赖：`__future__`, `unittest`, `app.session`, `baker.params`。

**`tests/test_video.py`** — unittest自动化测试/夹具；逐用例清单见第六章。 LOC=206，SLOC=169。

入口/类型：`VideoPipelineTests@59`；`VideoAvailabilityTests@175`。依赖：`__future__`, `shutil`, `subprocess`, `tempfile`, `threading`, `unittest`, `pathlib`, `numpy`, `app`, `baker.cube_writer`, `baker.params`。

**`tools/__init__.py`** — Python包入口/标识。 LOC=1，SLOC=0。

入口/类型：无顶层公开定义。依赖：无导入。

**`tools/acceptance_stage6_histogram.py`** — Stage-6 acceptance: histogram canvas must contain visible curve pixels. LOC=118，SLOC=96。

入口/类型：`main()@15`。依赖：`__future__`, `json`, `sys`, `time`, `pathlib`。

**`tools/acceptance_stage7_matrix.py`** — Stage-7: 18-item acceptance matrix (Playwright + in-page probes). LOC=316，SLOC=282。

入口/类型：`pass_item(item_id: str, ok: bool, **data: object)@15`；`main()@20`。依赖：`__future__`, `json`, `sys`, `time`, `pathlib`。

**`tools/benchmark/__init__.py`** — Python包入口/标识。 LOC=33，SLOC=12。

入口/类型：无顶层公开定义。依赖：无导入。

**`tools/benchmark/common.py`** — Shared plumbing: paths, timing statistics, environment capture, LUT caching. LOC=230，SLOC=184。

入口/类型：`Timing@23`；`summarise(samples_ms: Sequence[float])@44`；`time_call(func: Callable[[], Any], *, warmup: int=1, trials: int=5)@60`；`to_float01(rgb_uint8: np.ndarray)@72`；`to_uint8(rgb01: np.ndarray)@76`；`bake_timed(params: Any, size: int, *, repeats: int=3)@82`；`cube_cache_path(tag: str, size: int)@96`；`ensure_cube(params: Any, size: int, tag: str)@100`；`environment_info()@131`；`reset_work_dir()@192`；`dump_json(path: Path, payload: Any)@197`。依赖：`__future__`, `json`, `platform`, `shutil`, `subprocess`, `sys`, `time`, `dataclasses`, `pathlib`, `typing`, `numpy`。

**`tools/benchmark/dataset.py`** — Deterministic benchmark image set. LOC=226，SLOC=171。

入口/类型：`BenchImage@24`；`build_dataset(fixtures_dir: Path, out_dir: Path, minimum: int=5)@191`。依赖：`__future__`, `dataclasses`, `pathlib`, `numpy`, `PIL`。

**`tools/benchmark/dim1_speedup.py`** — Dimension 1 - CPU per-pixel maths vs the C++ OpenGL 3.3 Core render worker. LOC=165，SLOC=118。

入口/类型：`Resolution@36`；`make_test_image(width: int, height: int)@54`；`run(results_dir: Path)@114`。依赖：`__future__`, `shutil`, `dataclasses`, `pathlib`, `typing`, `numpy`, `PIL`, `.`。

**`tools/benchmark/dim2_lut.py`** — Dimension 2 - how much accuracy a 17^3 / 33^3 / 65^3 LUT costs. LOC=119，SLOC=80。

入口/类型：`build_probe()@29`；`payload_kb(samples: np.ndarray)@40`；`run(results_dir: Path | None=None)@46`；`metrics_transform(rgb01: np.ndarray, params: Any)@105`。依赖：`__future__`, `base64`, `pathlib`, `typing`, `numpy`, `.`, `.interpolation`。

**`tools/benchmark/dim3_interp.py`** — Dimension 3 - trilinear vs tetrahedral 3D LUT interpolation. LOC=192，SLOC=146。

入口/类型：`run(results_dir: Path | None=None)@134`。依赖：`__future__`, `pathlib`, `typing`, `numpy`, `.`, `.dim2_lut`, `.interpolation`。

**`tools/benchmark/dim4_quality.py`** — Dimension 4 - objective quality of the five built-in grading presets. LOC=165，SLOC=124。

入口/类型：`run(results_dir: Path)@69`。依赖：`__future__`, `pathlib`, `typing`, `numpy`, `PIL`, `.`。

**`tools/benchmark/dim5_ai.py`** — Dimension 5 - AI intent parsing accuracy and robustness. LOC=413，SLOC=348。

入口/类型：`Check@44`；`Case@60`；`run(online: bool=False, results_dir: Any=None)@358`。依赖：`__future__`, `json`, `time`, `dataclasses`, `pathlib`, `typing`, `.`。

**`tools/benchmark/interpolation.py`** — 3D LUT sampling: GPU-equivalent trilinear vs 6-simplex tetrahedral. LOC=114，SLOC=78。

入口/类型：`tetrahedral_sample(lut: np.ndarray, n: int, rgb: np.ndarray, domain_min: Domain=(0.0, 0.0, 0.0), domain_max: Domain=(1.0, 1.0, 1.0))@35`；`trilinear_sample(lut: np.ndarray, n: int, rgb: np.ndarray, domain_min: Domain=(0.0, 0.0, 0.0), domain_max: Domain=(1.0, 1.0, 1.0))@101`。依赖：`__future__`, `numpy`。

**`tools/benchmark/metrics.py`** — Colour-science and image-quality metrics, implemented with numpy only. LOC=295，SLOC=207。

入口/类型：`srgb_to_linear(encoded: np.ndarray)@39`；`linear_to_xyz(linear_rgb: np.ndarray)@45`；`xyz_to_lab(xyz: np.ndarray)@53`；`srgb_to_lab(rgb: np.ndarray)@61`；`srgb8_to_lab(rgb: np.ndarray)@67`；`luma(rgb: np.ndarray)@71`；`chroma(lab: np.ndarray)@76`；`delta_e76(lab1: np.ndarray, lab2: np.ndarray)@82`；`delta_e00(lab1: np.ndarray, lab2: np.ndarray)@88`；`DeltaEStats@155`；`delta_e_stats(lab1: np.ndarray, lab2: np.ndarray, *, ciede2000: bool)@161`；`psnr_uint8(reference: np.ndarray, test: np.ndarray)@173`；`psnr_unit(reference: np.ndarray, test: np.ndarray)@183`；`mae_uint8(reference: np.ndarray, test: np.ndarray)@193`；`ssim(reference: np.ndarray, test: np.ndarray, window: int=8)@211`；`entropy_bits(rgb_uint8: np.ndarray)@237`；`mean_luma(rgb_uint8: np.ndarray)@249`；`contrast_std(rgb_uint8: np.ndarray)@254`；`colorfulness(rgb_uint8: np.ndarray)@259`；`identity_psnr()@270`。依赖：`__future__`, `math`, `dataclasses`, `numpy`。

**`tools/benchmark/report.py`** — Markdown report assembly for the five-dimension benchmark. LOC=776，SLOC=733。

入口/类型：`build(raw: dict[str, Any], results_dir: Path)@238`。依赖：`__future__`, `pathlib`, `typing`。

**`tools/benchmark/visualization.py`** — 300 DPI publication figures for the benchmark report. LOC=502，SLOC=443。

入口/类型：`configure_style()@42`；`figure_speedup(data: dict[str, Any], path: Path)@123`；`figure_lut(data: dict[str, Any], path: Path)@188`；`figure_interp(data: dict[str, Any], path: Path)@303`；`figure_quality(data: dict[str, Any], path: Path)@431`；`build_all(raw: dict[str, Any], results_dir: Path)@483`。依赖：`__future__`, `pathlib`, `typing`, `matplotlib`, `matplotlib.pyplot`, `numpy`。

**`tools/check_config.py`** — Fail-safe .env inspection: never prints secret values. LOC=54，SLOC=42。

入口/类型：`mask(key: str, value: str)@15`；`main()@23`。依赖：`__future__`, `sys`, `pathlib`, `ai.provider`。

**`tools/measure_large_image.py`** — Measure load/preview/export cost and peak memory on a large image (T15). LOC=202，SLOC=159。

入口/类型：`_ProcessMemoryCounters@40`；`main()@105`。依赖：`__future__`, `argparse`, `ctypes`, `json`, `sys`, `time`, `dataclasses`, `pathlib`, `numpy`, `PIL`, `app`, `app.pipeline`, `app.state`, `baker.params`。

**`tools/measure_lut.py`** — Measure 3D LUT approximation error against the CPU reference (T08). LOC=58，SLOC=40。

入口/类型：`measure(params: ColorParams, size: int, points: np.ndarray)@22`；`main()@35`。依赖：`__future__`, `json`, `sys`, `pathlib`, `numpy`, `baker.color_transform`, `baker.params`。

**`tools/run_benchmark.py`** — Five-dimension performance & image-quality benchmark for ai_color_app. LOC=204，SLOC=158。

入口/类型：`main(argv: list[str] | None=None)@93`。依赖：`__future__`, `argparse`, `shutil`, `sys`, `time`, `traceback`, `pathlib`, `tools.benchmark`。

### 1.5 配置/Schema/数据职责

`requirements.txt` / `requirements-lock.txt` 为Python依赖；`frontend/package.json` 构建 `tsc -b && vite build`，实际依赖见lock。`run.ps1` 桌面启动；`start_web.ps1` 检查8765就绪后启动Vite，不启用uvicorn热重载。`schemas/` 是v1/v2参数约束，`presets/` 是六套数据，`docs/decisions/` 是设计缘由，根 `identity17.cube` / `ai_color_output.ppm` 为历史数据。生成的tsbuildinfo不计源码。

| 契约/预设文件 | 读取方/职责 |
| --- | --- |
| presets/cinematic.json | baker.params读取的JSON 参数预设 |
| presets/cool.json | baker.params读取的JSON 参数预设 |
| presets/identity.json | baker.params读取的JSON 参数预设 |
| presets/mono.json | baker.params读取的JSON 参数预设 |
| presets/soft.json | baker.params读取的JSON 参数预设 |
| presets/warm.json | baker.params读取的JSON 参数预设 |
| schemas/color_params.v1.schema.json | baker.params读取的JSON Schema约束 |
| schemas/color_params.v2.schema.json | baker.params读取的JSON Schema约束 |

## 2. C++17 + OpenGL 离屏渲染引擎（engine/ 与 shaders/）

### 2.1 上下文、FBO 与资源生命周期

真实调用链：`EngineClient.render → subprocess.Popen(render_worker.exe --request … --response … --shaders …) → wmain → parseRequest → loadRgbaFile → loadCubeFile → GlRenderer::init → GlRenderer::render → writeRgbaFileAtomic → jsonResponse → writeTextAtomic → ExitProcess`。是每个任务拉起一次进程，没有常驻worker或共享内存。stdout/stderr管道只承载日志；图像与控制数据均走文件。

初始化顺序：`glfwSetErrorCallback → glfwInit → glfwWindowHint(CONTEXT_VERSION_MAJOR,3)/MINOR,3 → VISIBLE,FALSE → DOUBLEBUFFER,FALSE → glfwCreateWindow(64,64,…) → glfwMakeContextCurrent → glfwSwapInterval(0) → gladLoadGLLoader(glfwGetProcAddress)`。**真实隐藏窗口为64×64，不是1×1；未设置 GLFW_OPENGL_PROFILE 或 CORE_PROFILE hint。** 代码查询 GL_VERSION/RENDERER/VENDOR 与 major/minor，最低接受3.3，不能仅凭请求参数宣称实际context一定是3.3 Core。

`loadProgram` 读取两份磁盘GLSL、compile/link、删除shader；生成并绑定一个空VAO。禁用depth/blend/dither/scissor/cull和`GL_FRAMEBUFFER_SRGB`，PACK/UNPACK_ALIGNMENT=1。因此编码sRGB样本不经OpenGL自动解码/再编码；只有Python曝光/白平衡步骤显式转线性光。

每次render创建输入2D纹理、3D LUT纹理、输出颜色纹理、FBO：附件为COLOR_ATTACHMENT0的RGBA8纹理，无深度附件，`glCheckFramebufferStatus`验证完整，再`glDrawBuffer/glReadBuffer(COLOR_ATTACHMENT0)`。viewport等于输入宽高；设置纹理单元0/1和六个uniform，`glDrawArrays(GL_TRIANGLES,0,3) → glFinish → glReadPixels(RGBA,UNSIGNED_BYTE)`。输出缓冲为宽×高×4字节。

render结束解绑FBO/VAO/program并删除本次四个GL对象，恢复PACK/UNPACK_ALIGNMENT=1。类析构的shutdown会删除program/VAO、destroyWindow和glfwTerminate；但**正式worker在main中故意new且不delete renderer，提交response后用Windows ExitProcess跳过CRT/静态析构**，注释说明是避开本机Mesa glfwTerminate异常。不能将这条实际退出路径描写成每次完整执行正常析构。

| 资源 | 内部/外部格式 | MIN / MAG | wrap / 其他 |
| --- | --- | --- | --- |
| 输入原图2D | GL_RGBA8 / GL_RGBA / GL_UNSIGNED_BYTE | GL_NEAREST / GL_NEAREST | S,T CLAMP_TO_EDGE，无mipmap |
| 3D LUT | GL_RGB32F / GL_RGB / GL_FLOAT | GL_LINEAR / GL_LINEAR | S,T,R CLAMP_TO_EDGE；BASE_LEVEL=MAX_LEVEL=0 |
| 输出颜色附件2D | GL_RGBA8 / GL_RGBA / GL_UNSIGNED_BYTE | GL_NEAREST / GL_NEAREST | 单层FBO颜色纹理；wrap未显式设置 |

**准确术语：** 3D纹理的 GL_LINEAR 是8个邻接体素的硬件三线性空间插值；静图mipmap的LINEAR_MIPMAP_LINEAR则是二维层内双线性+层间混合，两者不可混称。C++原图使用NEAREST，不是LINEAR。

### 2.2 两份独立 GLSL 原文与数学

源码：`shaders/fullscreen.vert:1`。

```glsl
#version 330 core

// Fullscreen triangle without vertex buffers. A VAO must still be bound.
out vec2 vUv;

void main() {
    const vec2 p[3] = vec2[3](vec2(-1.0, -1.0), vec2(3.0, -1.0), vec2(-1.0, 3.0));
    gl_Position = vec4(p[gl_VertexID], 0.0, 1.0);
    vUv = 0.5 * (p[gl_VertexID] + 1.0);
}
```

源码：`shaders/grade.frag:1`。

```glsl
#version 330 core

// Encoded-sRGB in, encoded-sRGB out. No automatic sRGB conversion is enabled
// anywhere in the pipeline (see ADR-004).
in vec2 vUv;
out vec4 fragColor;

uniform sampler2D uImage;
uniform sampler3D uLut;
uniform vec3 uDomainMin;
uniform vec3 uDomainMax;
uniform float uLutSize;
uniform float uStrength;

void main() {
    vec4 src = texture(uImage, vUv);

    // CPU validates max > min per channel.
    vec3 q = clamp((src.rgb - uDomainMin) / (uDomainMax - uDomainMin), 0.0, 1.0);

    // Voxel-center correction: a 3D texture with N texels per axis has its
    // first center at 0.5/N and last center at 1 - 0.5/N.
    vec3 tc = q * ((uLutSize - 1.0) / uLutSize) + vec3(0.5 / uLutSize);

    vec3 mapped = clamp(texture(uLut, tc).rgb, 0.0, 1.0);
    vec3 rgb = clamp(mix(src.rgb, mapped, uStrength), 0.0, 1.0);

    fragColor = vec4(rgb, src.a);
}
```

全屏三角形顶点为(-1,-1)、(3,-1)、(-1,3)，超出裁剪框部分由光栅管线裁切；只需VAO，不需要VBO/EBO。纹理坐标由 `vUv=(p+1)/2` 插值获得。

对逐通道输入 (c)、domain下/上界 (d_0,d_1)、LUT边长 (N)、强度 (s)：

\[
q=\operatorname{clamp}((c-d_0)/(d_1-d_0),0,1),\quad
 t=q\frac{N-1}{N}+\frac{1}{2N},\quad
m=\operatorname{clamp}(\operatorname{texture}(uLut,t),0,1),\quad
c_o=\operatorname{clamp}((1-s)c+sm,0,1).
\]

这里 (t=0.5/N) 和 (1-0.5/N) 正好落在端点体素中心，避免将[0,1]端点错误映到纹理边界。Alpha直接取src.a，非预乘。Uniform：`uImage` sampler2D→单元0，`uLut` sampler3D→单元1；`uDomainMin`/`uDomainMax` vec3；`uLutSize` float；`uStrength` float。C++头注释规定RGBA文件首行是图像顶部；上下传输与回读采用一致约定，不增加独立CPU翻转。

### 2.3 ACRGBA01 像素桥与安全校验

| 字节offset | 类型 | 含义 |
| --- | --- | --- |
| 0 | char[8] | ASCII ACRGBA01 |
| 8 | uint32 LE | width |
| 12 | uint32 LE | height |
| 16 | uint32 LE | row_stride，必须width×4 |
| 20 | uint32 LE | format=1（straight RGBA8） |
| 24 | byte[width×height×4] | 连续行，无padding；row0=top |

`rgba_bridge.cpp` 检查magic、24字节头完整、format=1、单边1..16384、像素数≤40,000,000、stride以及文件总长度必须恰好24+4WH，短读也失败。写出使用`.tmp`、flush、关闭后remove/rename；Python桥使用`struct.Struct('<8sIIII')`。

worker JSON请求上限65536字节；`json_lite`仅支持浅对象的string/number/bool/null，最多24键，不支持嵌套数组/对象，拒绝重复键、尾随内容、非有限/越界数值、不合法转义与孤立UTF-16代理项。`parseRequest`额外要求protocol_version='1.0'、operation='render'、revision是0..2^53的整数、strength在[0,1]、所有路径绝对；job/document字符串最长128，路径最长4096，禁控制字符。

输出与response的父目录经weakly_canonical比较，必须与request所在任务目录相同。**输入RGBA和LUT允许来自任务目录外的缓存**，因此错误消息“all files must be inside…”比真实限制更宽泛。Python再次resolve response输出路径，确认位于job_dir；检查协议版本/job/document/revision，防止串任务。

### 2.4 控制协议、进程预算和错误

```json
{
  "protocol_version": "1.0",
  "job_id": "<job-id>",
  "document_id": "<document-id>",
  "revision": 1,
  "operation": "render",
  "input_rgba": "<absolute input.rgba>",
  "lut_path": "<absolute lut.cube>",
  "strength": 1.0,
  "output_rgba": "<absolute job/output.rgba>"
}
```

```json
{
  "protocol_version": "1.0",
  "job_id": "<same>",
  "document_id": "<same>",
  "revision": 1,
  "status": "ok",
  "error": null,
  "output_rgba": "<absolute output.rgba>",
  "metrics": {
    "render_readback_ms": null
  }
}
```

```json
{
  "protocol_version": "1.0",
  "job_id": "<same>",
  "document_id": "<same>",
  "revision": 1,
  "status": "error",
  "error": {
    "code": "GPU_RENDER_FAILED",
    "message": "<detail>",
    "stage": "gpu"
  },
  "output_rgba": null,
  "metrics": {
    "render_readback_ms": null
  }
}
```

以上尖括号是ID/路径取值说明，字段名与响应形状来自真实源码。`render_readback_ms`在计时>0时为JSON number；示例使用null表示未填入测量值，不伪造新实测数值。

`Popen(shell=False, stdout=PIPE, stderr=PIPE, CREATE_NO_WINDOW)`；每80ms communicate一次检查cancel或deadline；默认30s，全尺寸export传120s。超时/取消kill进程并尝试5s回收。成功默认删除job_dir，取消也删除；崩溃/失败保留诊断文件。响应有5×20ms存在检查。退出码：0成功；3 LUT_UNSUPPORTED；4 GPU_INIT_FAILED/GPU_RENDER_FAILED/GPU_LIMIT；5 EXPORT_IO；其他2。

**计时边界：** C++计时包围整个`renderer.render`，包含纹理/FBO创建、上传、glFinish、uniform/draw、glReadPixels和临时GL对象清理；不含GLFW/GLAD初始化、读输入/cube、写输出文件和response。它不是GPU timer query，也不是纯fragment执行时间。dim1端到端另包含进程/文件开销，详见6.3。

### 2.5 可查验的真实类型与生命周期实现

源码：`engine/gl_renderer.h:1`。

```cpp
#pragma once

#include <string>

#include "cube.h"
#include "rgba_bridge.h"

// Hidden-window OpenGL 3.3 renderer. All GL calls, including init and
// teardown, happen on the calling (main) thread.
class GlRenderer {
public:
    GlRenderer() = default;
    ~GlRenderer();

    GlRenderer(const GlRenderer&) = delete;
    GlRenderer& operator=(const GlRenderer&) = delete;

    // Creates the hidden context and compiles the shader program.
    bool init(const std::string& shaderDir, std::string& error);
    void shutdown();

    // Encoded-sRGB in / encoded-sRGB out. Alpha is copied byte-for-byte.
    bool render(const RgbaImage& input, const CubeLut& lut, float strength,
                RgbaImage& output, std::string& error);

    std::string glInfo() const { return glInfo_; }

private:
    bool initGlfw(std::string& error);
    bool loadProgram(const std::string& shaderDir, std::string& error);
    void releaseGl();

    bool initialized_ = false;
    bool glfwReady_ = false;
    void* window_ = nullptr;  // GLFWwindow*
    unsigned int program_ = 0;
    unsigned int vao_ = 0;
    int maxTextureSize_ = 0;
    int max3dTextureSize_ = 0;
    std::string glInfo_;
};
```

源码：`engine/cube.h:1`。

```cpp
#pragma once

#include <string>
#include <vector>

// P0 subset of the Iridas .cube format. This is deliberately strict: an
// unsupported or ambiguous file must fail instead of being misread.
struct CubeLut {
    int size = 0;
    float domain_min[3] = {0.0f, 0.0f, 0.0f};
    float domain_max[3] = {1.0f, 1.0f, 1.0f};
    std::string title;
    // R fastest, B slowest: index = 3 * (r + N * (g + N * b)).
    std::vector<float> samples;
};

enum class CubeErrorKind { Parse, Unsupported, Io };

struct CubeError {
    CubeErrorKind kind = CubeErrorKind::Parse;
    std::string message;
};

// Returns true on success. `error` is filled otherwise.
bool loadCubeFile(const std::string& path, CubeLut& out, CubeError& error);

// Writes a .cube atomically (tmp file + rename). Used only by tests/self-check;
// the production exporter lives in Python.
bool writeCubeFile(const std::string& path, const CubeLut& lut,
                   std::string& error);
```

源码：`engine/rgba_bridge.h:1`。

```cpp
#pragma once

#include <cstdint>
#include <string>
#include <vector>

// Internal straight (non-premultiplied) RGBA8 bridge between Python and the
// render worker. File layout:
//   8 bytes  magic "ACRGBA01"
//   4 x little-endian uint32: width, height, row_stride, format
//   width * height * 4 bytes, row 0 = top of the image
// format 1 = straight RGBA8. row_stride must equal width * 4.
struct RgbaImage {
    std::uint32_t width = 0;
    std::uint32_t height = 0;
    std::vector<std::uint8_t> pixels;
};

enum class RgbaErrorKind { Invalid, Io };

struct RgbaError {
    RgbaErrorKind kind = RgbaErrorKind::Invalid;
    std::string message;
};

bool loadRgbaFile(const std::string& path, RgbaImage& out, RgbaError& error);

// Writes to `path + ".tmp"`, flushes and closes, then renames over `path`.
bool writeRgbaFileAtomic(const std::string& path, const RgbaImage& image,
                         std::string& error);
```

源码：`engine/json_lite.h:1`。

```cpp
#pragma once

#include <string>

namespace jsonlite {

// Strict, minimal JSON support for the worker request. The request is a flat
// object of strings / numbers / booleans / null. Duplicate keys, trailing
// tokens, NaN/Infinity and malformed escapes are rejected. This keeps the
// engine free of an external JSON dependency while still failing loudly.
struct Value {
    enum class Type { Null, Bool, Number, String };
    Type type = Type::Null;
    bool boolean = false;
    double number = 0.0;
    std::string text;
};

struct Object {
    std::string keys[24];
    Value values[24];
    int count = 0;

    const Value* find(const std::string& key) const;
};

// Parses exactly one object and rejects anything after it.
// Returns false and fills `error` on failure. Object must be shallow (no
// nested arrays/objects) because the protocol does not use them.
bool parseObject(const std::string& text, Object& out, std::string& error);

// Escapes a UTF-8 string for inclusion in a JSON document.
std::string escape(const std::string& s);

}  // namespace jsonlite
```

源码：`engine/gl_renderer.cpp:1`。

```cpp
#define NOMINMAX
#define GLFW_INCLUDE_NONE
#include "gl_renderer.h"

#include <glad/glad.h>
#include <GLFW/glfw3.h>

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <vector>

namespace {

std::string readTextFile(const std::filesystem::path& path) {
    std::ifstream f(path, std::ios::binary);
    if (!f) return std::string();
    std::ostringstream ss;
    ss << f.rdbuf();
    return ss.str();
}

std::string glErrorName(GLenum e) {
    switch (e) {
        case GL_NO_ERROR: return "GL_NO_ERROR";
        case GL_INVALID_ENUM: return "GL_INVALID_ENUM";
        case GL_INVALID_VALUE: return "GL_INVALID_VALUE";
        case GL_INVALID_OPERATION: return "GL_INVALID_OPERATION";
        case GL_INVALID_FRAMEBUFFER_OPERATION:
            return "GL_INVALID_FRAMEBUFFER_OPERATION";
        case GL_OUT_OF_MEMORY: return "GL_OUT_OF_MEMORY";
        default: return "GL_ERROR_" + std::to_string(e);
    }
}

bool checkGl(const char* where, std::string& error) {
    GLenum e = glGetError();
    if (e == GL_NO_ERROR) return true;
    error = std::string("OpenGL error at ") + where + ": " + glErrorName(e);
    return false;
}

GLuint compileShader(GLenum type, const std::string& source,
                     const std::string& label, std::string& error) {
    GLuint shader = glCreateShader(type);
    if (shader == 0) {
        error = "glCreateShader failed for " + label;
        return 0;
    }
    const char* src = source.c_str();
    glShaderSource(shader, 1, &src, nullptr);
    glCompileShader(shader);
    GLint ok = GL_FALSE;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (ok != GL_TRUE) {
        char log[4096] = {0};
        glGetShaderInfoLog(shader, sizeof(log) - 1, nullptr, log);
        error = "shader compile failed (" + label + "): " + log;
        glDeleteShader(shader);
        return 0;
    }
    return shader;
}

struct GlObjects {
    GLuint inputTexture = 0;
    GLuint lutTexture = 0;
    GLuint colorTexture = 0;
    GLuint fbo = 0;
};

}  // namespace

GlRenderer::~GlRenderer() { shutdown(); }

bool GlRenderer::init(const std::string& shaderDir, std::string& error) {
    if (initialized_) return true;
    if (!initGlfw(error)) {
        shutdown();
        return false;
    }
    if (!loadProgram(shaderDir, error)) {
        shutdown();
        return false;
    }
    glGenVertexArrays(1, &vao_);
    glBindVertexArray(vao_);
    if (!checkGl("glGenVertexArrays", error)) {
        shutdown();
        return false;
    }

    glDisable(GL_DEPTH_TEST);
    glDisable(GL_BLEND);
    glDisable(GL_DITHER);
    glDisable(GL_SCISSOR_TEST);
    glDisable(GL_CULL_FACE);
    glDisable(GL_FRAMEBUFFER_SRGB);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);
    if (!checkGl("initial state", error)) {
        shutdown();
        return false;
    }

    initialized_ = true;
    return true;
}

bool GlRenderer::initGlfw(std::string& error) {
    glfwSetErrorCallback([](int code, const char* description) {
        // The caller reports the failure; avoid writing to stdout from here.
        (void)code;
        (void)description;
    });

    if (!glfwInit()) {
        error = "GLFW init failed";
        return false;
    }
    glfwReady_ = true;

    // No core-profile hint: the known-good local Mesa/D3D12 path returns 4.1
    // core either way, and the hint made visible-window paths less stable.
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
    glfwWindowHint(GLFW_VISIBLE, GLFW_FALSE);
    glfwWindowHint(GLFW_DOUBLEBUFFER, GLFW_FALSE);

    GLFWwindow* window = glfwCreateWindow(64, 64, "render_worker", nullptr, nullptr);
    if (window == nullptr) {
        error = "GLFW window creation failed";
        return false;
    }
    window_ = window;
    glfwMakeContextCurrent(window);
    glfwSwapInterval(0);

    if (!gladLoadGLLoader(reinterpret_cast<GLADloadproc>(glfwGetProcAddress))) {
        error = "GLAD loader failed";
        return false;
    }

    const char* version = reinterpret_cast<const char*>(glGetString(GL_VERSION));
    const char* renderer = reinterpret_cast<const char*>(glGetString(GL_RENDERER));
    const char* vendor = reinterpret_cast<const char*>(glGetString(GL_VENDOR));
    glInfo_ = std::string(version ? version : "?") + " | " +
              (renderer ? renderer : "?") + " | " + (vendor ? vendor : "?");

    GLint major = 0, minor = 0;
    glGetIntegerv(GL_MAJOR_VERSION, &major);
    glGetIntegerv(GL_MINOR_VERSION, &minor);
    if (major < 3 || (major == 3 && minor < 3)) {
        error = "OpenGL 3.3 required, got " + std::to_string(major) + "." +
                std::to_string(minor);
        return false;
    }

    glGetIntegerv(GL_MAX_TEXTURE_SIZE, &maxTextureSize_);
    glGetIntegerv(GL_MAX_3D_TEXTURE_SIZE, &max3dTextureSize_);
    if (maxTextureSize_ < 64 || max3dTextureSize_ < 2) {
        error = "GL texture limits are too small";
        return false;
    }
    if (!checkGl("limits query", error)) return false;
    return true;
}

bool GlRenderer::loadProgram(const std::string& shaderDir, std::string& error) {
    std::filesystem::path dir(shaderDir);
    const std::filesystem::path vertPath = dir / "fullscreen.vert";
    const std::filesystem::path fragPath = dir / "grade.frag";
    const std::string vertSrc = readTextFile(vertPath);
    const std::string fragSrc = readTextFile(fragPath);
    if (vertSrc.empty()) {
        error = "cannot read shader: " + vertPath.string();
        return false;
    }
    if (fragSrc.empty()) {
        error = "cannot read shader: " + fragPath.string();
        return false;
    }

    GLuint vert = compileShader(GL_VERTEX_SHADER, vertSrc, vertPath.string(), error);
    if (vert == 0) return false;
    GLuint frag = compileShader(GL_FRAGMENT_SHADER, fragSrc, fragPath.string(), error);
    if (frag == 0) {
        glDeleteShader(vert);
        return false;
    }

    program_ = glCreateProgram();
    glAttachShader(program_, vert);
    glAttachShader(program_, frag);
    glLinkProgram(program_);
    glDeleteShader(vert);
    glDeleteShader(frag);

    GLint ok = GL_FALSE;
    glGetProgramiv(program_, GL_LINK_STATUS, &ok);
    if (ok != GL_TRUE) {
        char log[4096] = {0};
        glGetProgramInfoLog(program_, sizeof(log) - 1, nullptr, log);
        error = std::string("shader link failed: ") + log;
        return false;
    }
    return checkGl("link program", error);
}

bool GlRenderer::render(const RgbaImage& input, const CubeLut& lut,
                        float strength, RgbaImage& output, std::string& error) {
    if (!initialized_) {
        error = "renderer not initialized";
        return false;
    }
    if (input.width == 0 || input.height == 0 || input.pixels.empty()) {
        error = "empty input image";
        return false;
    }
    if (lut.size < 2 || lut.size > 65) {
        error = "invalid LUT size";
        return false;
    }
    if (static_cast<int>(input.width) > maxTextureSize_ ||
        static_cast<int>(input.height) > maxTextureSize_) {
        error = "image exceeds GL_MAX_TEXTURE_SIZE";
        return false;
    }
    if (lut.size > max3dTextureSize_) {
        error = "LUT exceeds GL_MAX_3D_TEXTURE_SIZE";
        return false;
    }
    if (!(strength >= 0.0f && strength <= 1.0f)) {
        error = "strength must be in [0,1]";
        return false;
    }

    const std::size_t expectedLut =
        static_cast<std::size_t>(lut.size) * lut.size * lut.size * 3u;
    if (lut.samples.size() != expectedLut) {
        error = "LUT sample count mismatch";
        return false;
    }

    GlObjects obj;
    bool ok = true;

    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);

    glGenTextures(1, &obj.inputTexture);
    glBindTexture(GL_TEXTURE_2D, obj.inputTexture);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, static_cast<GLsizei>(input.width),
                 static_cast<GLsizei>(input.height), 0, GL_RGBA,
                 GL_UNSIGNED_BYTE, input.pixels.data());
    ok = ok && checkGl("upload input texture", error);

    if (ok) {
        glGenTextures(1, &obj.lutTexture);
        glBindTexture(GL_TEXTURE_3D, obj.lutTexture);
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_BASE_LEVEL, 0);
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MAX_LEVEL, 0);
        glTexImage3D(GL_TEXTURE_3D, 0, GL_RGB32F, lut.size, lut.size, lut.size,
                     0, GL_RGB, GL_FLOAT, lut.samples.data());
        glFinish();
        ok = ok && checkGl("upload 3D LUT", error);
    }

    if (ok) {
        glGenTextures(1, &obj.colorTexture);
        glBindTexture(GL_TEXTURE_2D, obj.colorTexture);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, static_cast<GLsizei>(input.width),
                     static_cast<GLsizei>(input.height), 0, GL_RGBA,
                     GL_UNSIGNED_BYTE, nullptr);
        ok = ok && checkGl("allocate output texture", error);
    }

    if (ok) {
        glGenFramebuffers(1, &obj.fbo);
        glBindFramebuffer(GL_FRAMEBUFFER, obj.fbo);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_2D, obj.colorTexture, 0);
        GLenum status = glCheckFramebufferStatus(GL_FRAMEBUFFER);
        if (status != GL_FRAMEBUFFER_COMPLETE) {
            error = "framebuffer incomplete: " + std::to_string(status);
            ok = false;
        }
        glDrawBuffer(GL_COLOR_ATTACHMENT0);
        glReadBuffer(GL_COLOR_ATTACHMENT0);
    }

    if (ok) {
        glViewport(0, 0, static_cast<GLsizei>(input.width),
                   static_cast<GLsizei>(input.height));
        glUseProgram(program_);
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, obj.inputTexture);
        glUniform1i(glGetUniformLocation(program_, "uImage"), 0);
        glActiveTexture(GL_TEXTURE1);
        glBindTexture(GL_TEXTURE_3D, obj.lutTexture);
        glUniform1i(glGetUniformLocation(program_, "uLut"), 1);
        glUniform3f(glGetUniformLocation(program_, "uDomainMin"),
                    lut.domain_min[0], lut.domain_min[1], lut.domain_min[2]);
        glUniform3f(glGetUniformLocation(program_, "uDomainMax"),
                    lut.domain_max[0], lut.domain_max[1], lut.domain_max[2]);
        glUniform1f(glGetUniformLocation(program_, "uLutSize"),
                    static_cast<float>(lut.size));
        glUniform1f(glGetUniformLocation(program_, "uStrength"), strength);
        glBindVertexArray(vao_);
        glDrawArrays(GL_TRIANGLES, 0, 3);
        glFinish();
        ok = ok && checkGl("draw", error);
    }

    if (ok) {
        output.width = input.width;
        output.height = input.height;
        output.pixels.resize(static_cast<std::size_t>(input.width) * input.height * 4u);
        glPixelStorei(GL_PACK_ALIGNMENT, 1);
        glReadPixels(0, 0, static_cast<GLsizei>(input.width),
                     static_cast<GLsizei>(input.height), GL_RGBA,
                     GL_UNSIGNED_BYTE, output.pixels.data());
        ok = ok && checkGl("glReadPixels", error);
    }

    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    glBindVertexArray(0);
    glUseProgram(0);
    if (obj.fbo) glDeleteFramebuffers(1, &obj.fbo);
    if (obj.colorTexture) glDeleteTextures(1, &obj.colorTexture);
    if (obj.lutTexture) glDeleteTextures(1, &obj.lutTexture);
    if (obj.inputTexture) glDeleteTextures(1, &obj.inputTexture);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glPixelStorei(GL_PACK_ALIGNMENT, 1);

    if (!ok) output = RgbaImage{};
    return ok;
}

void GlRenderer::shutdown() {
    if (initialized_ || program_ != 0) {
        if (program_ != 0) {
            glDeleteProgram(program_);
            program_ = 0;
        }
        if (vao_ != 0) {
            glDeleteVertexArrays(1, &vao_);
            vao_ = 0;
        }
        glUseProgram(0);
        glBindVertexArray(0);
    }
    initialized_ = false;
    releaseGl();
}

void GlRenderer::releaseGl() {
    if (window_ != nullptr) {
        glfwDestroyWindow(static_cast<GLFWwindow*>(window_));
        window_ = nullptr;
    }
    if (glfwReady_) {
        glfwTerminate();
        glfwReady_ = false;
    }
}
```

### 2.6 C++ cube/json辅助文件的实现边界

`loadCubeFile`与Python reader均支持TITLE/LUT_3D_SIZE/DOMAIN_MIN/MAX及#注释、UTF-8 BOM；N=2..65、32MiB、有限样本、绝对值≤65504、禁止数据后header/重复header/1D或range扩展。读取样本按照文件顺序填vector，索引在头文件明示。注意C++诊断`writeCubeFile`当前逐float各写一行，而读取器要求一行三个值；它不是Python正式导出器，不能用该函数证明往返规范。`json_lite.cpp`为有限浅对象扫描，不是通用JSON库；Response嵌套结构由main字符串构造。

## 3. TypeScript + WebGL2 实时渲染与交互管线（frontend/src/）

### 3.1 组件树、状态和媒体输入

`mountWorkbench`构造：顶栏Toolbar；左栏HistogramView、PresetGrid、媒体摘要、状态和重置；中央viewport-stage中主canvas、色彩立方体canvas、RgbWaveLoader、MediaStageOverlay和ViewportHud；右栏AI输入/六个意图chip、摘要与三组16维ParamPanel。CSS由tokens/layout集中实现：toolbar46px，sidebar344px，gap10px，灰阶玻璃与银白accent。当前tokens强调色是#e7e8ee，并不是金色；“黑金”是部分组件注释/历史方向。

参数input→`StateStore.setParam(commit=false)`→emit→syncUi与220ms尾沿防抖→`rebakeLut`→POST `/api/lut/bake`→float32 base64→`GlViewport.uploadLut`和`LutCubeView.setLut`。change时commit=true只落一条历史。`bakeGen`丢弃后返回的旧请求结果，不取消网络计算；`lastBakeKey`仅包含Object.values(params)，在请求开始前写入，失败时同参数自动重试受限。strength/bloom直接更新GPU uniform，不重新烘焙。

媒体上传→API返回media_id/content_url→`HTMLImageElement`或`HTMLVideoElement`读原始content。隐藏媒体容器使用屏幕外但非display:none，防浏览器不产出视频帧。视频loop/muted/playsInline/preload，loadeddata后setSource+play；用户点舞台可重试被拦截的play，HUD控制点击被过滤。浏览器解码能否硬件加速/支持编码不由本项目保证。

### 3.2 Mipmap、纹理精度与上载隔离

主canvas请求WebGL2：alpha=true、antialias=false、premultipliedAlpha=false、preserveDrawingBuffer=true；请求`OES_texture_float_linear`扩展。顶点是VBO中6个vec2构成的两个三角形，和C++零VBO三角形不同。

输入2D纹理CLAMP_TO_EDGE，初始MIN/MAG LINEAR。`uploadSourceFrame`以`UNPACK_FLIP_Y_WEBGL=true`上载DOM像素，finally恢复false。静图首次/重新ready才上载，之后 `generateMipmap(TEXTURE_2D)`，MIN=LINEAR_MIPMAP_LINEAR，MAG=LINEAR；视频每个currentTime变化上载，MIN/MAG维持LINEAR，不生成mipmap。视频宽>1920时先Canvas2D等比缩到宽1920；静图无同等上传像素预算。3D LUT先以RGB16F接受FLOAT上载，出错尝试RGB32F；MIN/MAG LINEAR、S/T/R CLAMP。**Web实际默认半精度LUT，后端RGB32F与CPU float32误差不能未经测量宣称逐位相同。**

浏览器canvas DPR=min(devicePixelRatio,2)。`gradedPixelSize`按原始媒体比例将最长边限2560，ping/pong为其一半（floor、至少1）。媒体显示纹理下采样尺寸和FBO尺寸是两个独立限制。

源码：`frontend/src/core/gl_viewport.ts:294`。

```typescript
  private initTextures(): void {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.imageTex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.bindTexture(gl.TEXTURE_3D, this.lutTex);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE);
  }
```

源码：`frontend/src/core/gl_viewport.ts:309`。

```typescript
  private applyImageFilterMode(): void {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.imageTex);
    if (this.imageMipmap) {
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    } else {
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    }
  }
```

源码：`frontend/src/core/gl_viewport.ts:485`。

```typescript
  uploadLut(
    samples: Float32Array,
    size: number,
    domainMin: [number, number, number] = [0, 0, 0],
    domainMax: [number, number, number] = [1, 1, 1],
  ): void {
    const gl = this.gl;
    const expected = size ** 3 * 3;
    if (samples.length !== expected) {
      throw new Error(`LUT length ${samples.length} != ${expected}`);
    }
    this.lutSize = size;
    this.domainMin = domainMin;
    this.domainMax = domainMax;
    gl.bindTexture(gl.TEXTURE_3D, this.lutTex);
    let stale = gl.getError();
    while (stale !== gl.NO_ERROR) stale = gl.getError();
    gl.texImage3D(
      gl.TEXTURE_3D,
      0,
      gl.RGB16F,
      size,
      size,
      size,
      0,
      gl.RGB,
      gl.FLOAT,
      samples,
    );
    if (gl.getError() !== gl.NO_ERROR) {
      gl.texImage3D(
        gl.TEXTURE_3D,
        0,
        gl.RGB32F,
        size,
        size,
        size,
        0,
        gl.RGB,
        gl.FLOAT,
        samples,
      );
    }
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE);
    this.histDirty = true;
    this.histLastAt = 0;
  }
```

源码：`frontend/src/core/gl_viewport.ts:621`。

```typescript
  private uploadSourceFrame(): boolean {
    const gl = this.gl;
    const src = this.source;
    if (!src || !isSourceReady(src)) return false;

    if ("videoWidth" in src) {
      const v = src;
      if (
        this.frameReady &&
        !v.seeking &&
        v.currentTime === this.lastUploadedTime
      ) {
        return true;
      }
    }

    const isVideo = "videoWidth" in src;
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.imageTex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    try {
      gl.texImage2D(
        gl.TEXTURE_2D,
        0,
        gl.RGBA,
        gl.RGBA,
        gl.UNSIGNED_BYTE,
        this.uploadableFrame(src),
      );
      if (!isVideo) {
        gl.generateMipmap(gl.TEXTURE_2D);
        this.imageMipmap = true;
      } else {
        this.imageMipmap = false;
      }
      this.applyImageFilterMode();
      this.frameReady = true;
      this.uploads += 1;
      if (isVideo) this.lastUploadedTime = src.currentTime;
      const w = isVideo ? src.videoWidth : src.naturalWidth;
      const h = isVideo ? src.videoHeight : src.naturalHeight;
      if (w > 0 && h > 0) {
        this.imgAspect = w / h;
        this.disposeFbos();
      }
    } catch (err) {
      console.warn("texImage2D failed", err);
      return false;
    } finally {
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    }
    return true;
  }
```

源码：`frontend/src/core/gl_viewport.ts:675`。

```typescript
  private uploadableFrame(
    src: HTMLImageElement | HTMLVideoElement,
  ): TexImageSource {
    if (!("videoWidth" in src)) return src;
    const vw = src.videoWidth;
    const vh = src.videoHeight;
    if (vw <= MAX_UPLOAD_WIDTH || vw <= 0 || vh <= 0) return src;
    const scale = MAX_UPLOAD_WIDTH / vw;
    const cw = MAX_UPLOAD_WIDTH;
    const ch = Math.max(1, Math.round(vh * scale));
    if (!this.scratchCanvas) {
      this.scratchCanvas = document.createElement("canvas");
      this.scratchCtx = this.scratchCanvas.getContext("2d", { alpha: false });
    }
    const canvas = this.scratchCanvas;
    const ctx = this.scratchCtx;
    if (!canvas || !ctx) return src;
    if (canvas.width !== cw || canvas.height !== ch) {
      canvas.width = cw;
      canvas.height = ch;
    }
    ctx.drawImage(src, 0, 0, cw, ch);
    return canvas;
  }
```

### 3.3 三阶段 Bloom（实际多次 draw）及完整内嵌 GLSL

逻辑“三Pass”并不是总共三次draw。开启Bloom时主图一帧：grade一次 + extract一次 + blur四次（两轮H/V）+ composite一次，共7次全屏draw；直方图采样会再次执行offscreen grade/Bloom和full composite，每100ms最多再增加一套7次draw。关闭Bloom跳过extract/blur，主图2次draw。

源码：`frontend/src/core/gl_viewport.ts:1`。

```typescript
/** WebGL2 3D LUT viewport — 3-pass FBO (grade · bloom · composite). */

/** Full-frame image UV — used in Pass 1/2 and histogram. */
const VS_FULL = `#version 300 es
in vec2 aPos;
out vec2 vUv;
void main() {
  vUv = aPos;
  gl_Position = vec4(aPos * 2.0 - 1.0, 0.0, 1.0);
}
`;

/** Viewport letterbox + zoom/pan — Pass 3 to screen only. */
const VS_VIEW = `#version 300 es
in vec2 aPos;
out vec2 vUv;
uniform vec2 uPan;
uniform float uZoom;
uniform vec2 uAspect;
void main() {
  vec2 p = aPos;
  p = (p - 0.5) * uZoom + 0.5 + uPan;
  p = (p - vec2(0.5)) / uAspect + vec2(0.5);
  vUv = p;
  gl_Position = vec4(aPos * 2.0 - 1.0, 0.0, 1.0);
}
`;

const FS_GRADE = `#version 300 es
precision highp float;
precision highp sampler3D;
in vec2 vUv;
out vec4 fragColor;
uniform sampler2D uImage;
uniform sampler3D uLut;
uniform vec3 uDomainMin;
uniform vec3 uDomainMax;
uniform float uLutSize;
uniform float uStrength;
void main() {
  if (vUv.x < 0.0 || vUv.x > 1.0 || vUv.y < 0.0 || vUv.y > 1.0) {
    fragColor = vec4(0.0);
    return;
  }
  vec4 src = texture(uImage, vUv);
  vec3 q = clamp((src.rgb - uDomainMin) / (uDomainMax - uDomainMin), 0.0, 1.0);
  vec3 tc = q * ((uLutSize - 1.0) / uLutSize) + vec3(0.5 / uLutSize);
  vec3 mapped = clamp(texture(uLut, tc).rgb, 0.0, 1.0);
  vec3 graded = clamp(mix(src.rgb, mapped, uStrength), 0.0, 1.0);
  fragColor = vec4(graded, src.a);
}
`;

const FS_EXTRACT = `#version 300 es
precision highp float;
in vec2 vUv;
out vec4 fragColor;
uniform sampler2D uTex;
void main() {
  vec3 c = texture(uTex, vUv).rgb;
  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  float t = smoothstep(0.64, 0.84, l); // soft knee @ ~0.72
  fragColor = vec4(c * t, t);
}
`;

const FS_BLUR = `#version 300 es
precision highp float;
in vec2 vUv;
out vec4 fragColor;
uniform sampler2D uTex;
uniform vec2 uTexel;
uniform vec2 uAxis;
void main() {
  vec3 acc = vec3(0.0);
  float wsum = 0.0;
  const float w[5] = float[5](0.227027, 0.1945948, 0.1216216, 0.054054, 0.016216);
  for (int i = -4; i <= 4; i++) {
    int j = abs(i);
    float wgt = w[j];
    vec2 off = uAxis * uTexel * float(i);
    acc += texture(uTex, vUv + off).rgb * wgt;
    wsum += wgt;
  }
  fragColor = vec4(acc / wsum, 1.0);
}
`;

const FS_COMPOSITE = `#version 300 es
precision highp float;
in vec2 vUv;
out vec4 fragColor;
uniform sampler2D uImage;
uniform sampler2D uGraded;
uniform sampler2D uBloom;
uniform float uBloomAmt;
uniform float uSplitRatio;
uniform int uCompareMode;
void main() {
  if (vUv.x < 0.0 || vUv.x > 1.0 || vUv.y < 0.0 || vUv.y > 1.0) {
    fragColor = vec4(0.0);
    return;
  }
  vec4 src = texture(uImage, vUv);
  vec3 graded = texture(uGraded, vUv).rgb;
  vec3 bloom = texture(uBloom, vUv).rgb;
  vec3 warm = bloom * vec3(1.05, 0.98, 0.92);
  vec3 effect = graded + warm * uBloomAmt * 0.85;
  vec3 rgb = effect;
  if (uCompareMode == 2) {
    rgb = src.rgb;
  } else if (uCompareMode == 1) {
    rgb = vUv.x < uSplitRatio ? src.rgb : effect;
  }
  fragColor = vec4(rgb, 1.0);
}
`;

```

**Pass 1** `VS_FULL`始终全图UV，FS_GRADE执行与C++同形的domain/体素中心/strength公式，写RGBA8 gradedFbo。这里不能施加屏幕aspect/zoom/pan，否则Bloom和直方图会二次letterbox。

**Pass 2** 对graded亮度代理 (L=0.2126R+0.7152G+0.0722B)，(t=\mathrm{smoothstep}(0.64,0.84,L))，输出 `(c*t,t)` 到半分辨率pingFbo。模糊核是中心到距离4的五个权重 `[0.227027,0.1945948,0.1216216,0.054054,0.016216]`，展开为9-tap，每tap除以wsum。每轮先ping→pong沿X，再pong→ping沿Y，总共2轮4次卷积。取样偏移为 `uAxis*uTexel*i`，uTexel=(1/src.w,1/src.h)。这不是物理光能守恒或HDR散射模拟，是编码域艺术性柔光近似。

**Pass 3** 合成 (e=g+0.85\,b_a\,(1.05,0.98,0.92)\odot B)。warm RGB系数直接乘，未显式tone-map；目标RGBA8会饱和裁切。屏幕使用`VS_VIEW`，仅该阶段处理视口：

\[
u'=\frac{(aPos-0.5)\,uZoom+uPan}{uAspect}+0.5.
\]

aspect若图像更宽则(ax,ay)=(1,canvasAspect/imageAspect)，否则(imageAspect/canvasAspect,1)。UV越界输出vec4(0)让舞台透出。compareMode=0效果、=1在`vUv.x<splitRatio`侧原图、=2全原图；Bloom仅并入效果侧，原图侧不带Bloom。域内alpha强制1，而非传src.a，因此Web合成和C++保alpha的结果有差异。

**实现细节必须保留：** 全局BLEND开启，`SRC_ALPHA,ONE_MINUS_SRC_ALPHA`也作用于extract写入，所以`vec4(c*t,t)`在清零目标上写出的RGB会额外乘一次t；不能把源码理想输出与实际混合后附件内容混为一谈。`renderOffscreenBloomTex`在bloom≤0.001时把ping纹理改成1×1黑纹理，却没有更新pair.w/h；由0再开Bloom是否重建附件不能仅由18项矩阵证明。`uploadSourceFrame`每次成功的视频上传都会disposeFbos，导致播放中每帧重建graded/ping/pong，和“只在resize重建”的概略描述不符。

源码：`frontend/src/core/gl_viewport.ts:581`。

```typescript
  private ensureFbos(): void {
    const { w, h } = this.gradedPixelSize();
    if (this.graded && this.fboW === w && this.fboH === h) return;
    this.disposeFbos();
    this.fboW = w;
    this.fboH = h;
    this.graded = this.createColorFbo(w, h);
    const hw = Math.max(1, Math.floor(w / 2));
    const hh = Math.max(1, Math.floor(h / 2));
    this.ping = this.createColorFbo(hw, hh);
    this.pong = this.createColorFbo(hw, hh);
  }
```

源码：`frontend/src/core/gl_viewport.ts:734`。

```typescript
  private passGrade(target: FboPair): void {
    const gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, target.fbo);
    gl.viewport(0, 0, target.w, target.h);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(this.progGrade);
    gl.uniform1f(this.locGrade.uLutSize, this.lutSize);
    gl.uniform3f(this.locGrade.uDomainMin, ...this.domainMin);
    gl.uniform3f(this.locGrade.uDomainMax, ...this.domainMax);
    gl.uniform1f(this.locGrade.uStrength, this.strength);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_3D, this.lutTex);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.imageTex);
    this.drawQuad();
  }
```

源码：`frontend/src/core/gl_viewport.ts:752`。

```typescript
  private passBloomChain(): void {
    const gl = this.gl;
    if (!this.graded || !this.ping || !this.pong) return;

    gl.bindFramebuffer(gl.FRAMEBUFFER, this.ping.fbo);
    gl.viewport(0, 0, this.ping.w, this.ping.h);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(this.progExtract);
    gl.uniform1i(this.locExtract.uTex, 0);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.graded.tex);
    this.drawQuad();

    const blurPass = (src: FboPair, dst: FboPair, axisX: number, axisY: number): void => {
      gl.bindFramebuffer(gl.FRAMEBUFFER, dst.fbo);
      gl.viewport(0, 0, dst.w, dst.h);
      gl.useProgram(this.progBlur);
      gl.uniform1i(this.locBlur.uTex, 0);
      gl.uniform2f(this.locBlur.uTexel, 1.0 / src.w, 1.0 / src.h);
      gl.uniform2f(this.locBlur.uAxis, axisX, axisY);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, src.tex);
      this.drawQuad();
    };

    for (let round = 0; round < 2; round++) {
      blurPass(this.ping, this.pong, 1, 0);
      blurPass(this.pong, this.ping, 0, 1);
    }
  }
```

源码：`frontend/src/core/gl_viewport.ts:784`。

```typescript
  private passComposite(
    targetFbo: WebGLFramebuffer | null,
    viewW: number,
    viewH: number,
    bloomTex: WebGLTexture,
  ): void {
    const gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, targetFbo);
    gl.viewport(0, 0, viewW, viewH);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    this.setQuadUniforms(this.progComposite, this.locComposite, viewW, viewH);
    gl.uniform1f(this.locComposite.uBloomAmt, this.bloom);
    gl.uniform1f(this.locComposite.uSplitRatio, this.splitRatio);
    gl.uniform1i(this.locComposite.uCompareMode, this.compareMode);
    gl.activeTexture(gl.TEXTURE2);
    gl.bindTexture(gl.TEXTURE_2D, bloomTex);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.graded!.tex);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.imageTex);
    this.drawQuad();
  }
```

源码：`frontend/src/core/gl_viewport.ts:809`。

```typescript
  private passCompositeFull(
    targetFbo: WebGLFramebuffer,
    viewW: number,
    viewH: number,
    bloomTex: WebGLTexture,
  ): void {
    const gl = this.gl;
    gl.bindFramebuffer(gl.FRAMEBUFFER, targetFbo);
    gl.viewport(0, 0, viewW, viewH);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(this.progCompositeFull);
    gl.uniform1f(this.locCompositeFull.uBloomAmt, this.bloom);
    gl.uniform1f(this.locCompositeFull.uSplitRatio, 0.5);
    gl.uniform1i(this.locCompositeFull.uCompareMode, 0);
    gl.activeTexture(gl.TEXTURE2);
    gl.bindTexture(gl.TEXTURE_2D, bloomTex);
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, this.graded!.tex);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.imageTex);
    this.drawQuad();
  }
```

源码：`frontend/src/core/gl_viewport.ts:833`。

```typescript
  private renderOffscreenBloomTex(): WebGLTexture | null {
    const gl = this.gl;
    this.ensureFbos();
    if (!this.graded || !this.ping) return null;

    this.passGrade(this.graded);

    let bloomTex = this.ping.tex;
    if (this.bloom > 0.001) {
      this.passBloomChain();
      bloomTex = this.ping.tex;
    } else {
      gl.bindTexture(gl.TEXTURE_2D, this.ping.tex);
      gl.texImage2D(
        gl.TEXTURE_2D,
        0,
        gl.RGBA8,
        1,
        1,
        0,
        gl.RGBA,
        gl.UNSIGNED_BYTE,
        new Uint8Array([0, 0, 0, 255]),
      );
    }
    return bloomTex;
  }
```

源码：`frontend/src/core/gl_viewport.ts:874`。

```typescript
  drawFrame(): void {
    if (this.renderPaused) return;
    this.resize();
    const canvas = this.canvas;

    if (!this.source) return;
    if (this.sourceIsVideo) {
      this.uploadSourceFrame();
    } else if (!this.frameReady) {
      this.uploadSourceFrame();
    }
    if (!this.frameReady) return;

    this.frames += 1;
    this.renderPipeline(null, canvas.width, canvas.height);
    this.maybeSampleHistogram();
  }
```

### 3.4 64×64 直方图FBO与统计触发

`HIST_SIZE=64`，RGBA8附件16384字节；`HIST_INTERVAL_MS=100`，最多10次/秒。静图仅histDirty时重算；播放视频持续采样，暂停/ended且无dirty时跳过。参数LUT/strength/bloom/compare/source变更设置dirty；纯zoom/pan不触发，统计对象是整幅效果图。

`sampleHistogram → renderOffscreenBloomTex → passCompositeFull(histFbo,64,64,…) → bindFramebuffer(histFbo) → readPixels → bindFramebuffer(null) → viewport恢复主canvas`。full合成强制compare=0，绕过屏幕几何，因此A/B拖动不改变统计内容。像素A<8跳过，其余最多4096样本；R/G/B按字节索引加1，亮度 `round(.2126R+.7152G+.0722B)` 入256-bin。

平滑 (h'_i=(h_{i-1}+2h_i+h_{i+1})/4)，边缘重复；以四通道共用最大peak归一化 (v_i=\log(1+9h'_i/peak)/\log10)。HistogramView随后用120ms三次ease-out做过渡，RGB screen混合+Luma白线。它是经过双线性空间下采样的分析近似，不是原图全部像素的精确全分辨率统计。

**没有读回耗时仪表/JSON原始ms数值。** 64×64是规模，100ms是触发周期，两者不能推导“gl.readPixels耗时100ms”或自行补“<1ms”。现有stage6/stage7只记录曲线非背景像素数、跨度和glError，不包含readback时间。

源码：`frontend/src/core/gl_viewport.ts:892`。

```typescript
  private maybeSampleHistogram(): void {
    if (!this.histCallback || !this.source) return;
    const now = performance.now();
    if (now - this.histLastAt < HIST_INTERVAL_MS) return;
    const isVideo = "videoWidth" in (this.source as HTMLVideoElement);
    if (isVideo) {
      const video = this.source as HTMLVideoElement;
      if (!this.histDirty && (video.paused || video.ended)) return;
    }
    if (!this.histDirty && !isVideo) return;
    this.histLastAt = now;
    this.histDirty = false;
    const bins = this.sampleHistogram();
    if (bins) this.histCallback(bins);
  }
```

源码：`frontend/src/core/gl_viewport.ts:908`。

```typescript
  private sampleHistogram(): HistogramBins | null {
    const gl = this.gl;
    const bloomTex = this.renderOffscreenBloomTex();
    if (!bloomTex) return null;
    this.passCompositeFull(this.histFbo, HIST_SIZE, HIST_SIZE, bloomTex);
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.histFbo);
    gl.readPixels(
      0,
      0,
      HIST_SIZE,
      HIST_SIZE,
      gl.RGBA,
      gl.UNSIGNED_BYTE,
      this.histPixels,
    );
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, this.canvas.width, this.canvas.height);

    const r = new Float32Array(256);
    const g = new Float32Array(256);
    const b = new Float32Array(256);
    const luma = new Float32Array(256);
    let samples = 0;
    const px = this.histPixels;
    for (let i = 0; i < px.length; i += 4) {
      if (px[i + 3] < 8) continue;
      const cr = px[i];
      const cg = px[i + 1];
      const cb = px[i + 2];
      r[cr] += 1;
      g[cg] += 1;
      b[cb] += 1;
      const y = Math.min(255, Math.round(0.2126 * cr + 0.7152 * cg + 0.0722 * cb));
      luma[y] += 1;
      samples += 1;
    }
    if (samples === 0) return null;

    const smooth = (src: Float32Array) => {
      const out = new Float32Array(256);
      for (let i = 0; i < 256; i++) {
        const a = src[Math.max(0, i - 1)];
        const c = src[i];
        const d = src[Math.min(255, i + 1)];
        out[i] = (a + 2 * c + d) / 4;
      }
      return out;
    };

    const sr = smooth(r);
    const sg = smooth(g);
    const sb = smooth(b);
    const sy = smooth(luma);

    let peak = 0;
    for (let i = 0; i < 256; i++) {
      peak = Math.max(peak, sr[i], sg[i], sb[i], sy[i]);
    }
    const norm = (src: Float32Array) => {
      const out = new Float32Array(256);
      for (let i = 0; i < 256; i++) {
        out[i] = Math.log1p((src[i] / peak) * 9) / Math.log(10);
      }
      return out;
    };

    return {
      r: norm(sr),
      g: norm(sg),
      b: norm(sb),
      luma: norm(sy),
      samples,
    };
  }
```

### 3.5 17³ 色彩立方体、MVP与轨道交互

LutCubeView使用独立WebGL2 context（antialias=true）和独立RAF，GRID=17，(17^3=4913)点。输入格点为(r/16,g/16,b/16)，经TS CPU三线性采样得到mapped；位置mapped−(0.5,0.5,0.5)，颜色=mapped。立方体12条边+RGB三根轴，共15线段30顶点。开启DEPTH_TEST与BLEND，先画LINES再画POINTS；点fragment用gl_PointCoord圆形discard。

源码`sampleLutTrilinear`先计算半体素修正tc，再计算`x=tc.x*(size-1)`等CPU索引；标准硬件等效索引应为`tc*N-0.5=q*(N-1)`。当前点云索引多引入一次压缩，**不能宣称点云CPU采样与GPU LUT严格一致**；本归档如实记录，不修改实现。

矩阵为列主序Float32Array，上传`uniformMatrix4fv(location,false,mvp)`：

\[
MVP=P(50^\circ,aspect,0.05,20)\,T(0,0,-d)\,R_y(yaw)\,R_x(pitch).
\]

\[
P=\begin{bmatrix}f/a&0&0&0\0&f&0&0\0&0&(F+n)/(n-F)&2Fn/(n-F)\0&0&-1&0\end{bmatrix},\quad f=1/\tan(25^\circ),\ n=.05,F=20.
\]

\[
R_x=\begin{bmatrix}1&0&0&0\0&c_x&-s_x&0\0&s_x&c_x&0\0&0&0&1\end{bmatrix},\quad
R_y=\begin{bmatrix}c_y&0&s_y&0\0&1&0&0\-s_y&0&c_y&0\0&0&0&1\end{bmatrix}.
\]

初始yaw=.785、pitch=−.62、distance=2.35。左键拖动yaw+=dx*.008、pitch+=dy*.008并限[-1.2,1.2]；滚轮distance+=deltaY*.004限[1.2,6]；双击resetView。points size=clamp(2.5+10/max(.05,−clip.z),2,18)，这里使用clip.z，不是clip.w，不能替换为标准透视点大小公式。lut3d模式暂停主GlViewport绘制/直方图，只运行点云RAF。

源码：`frontend/src/core/lut_cube_view.ts:1`。

```typescript
/** Interactive 3D LUT mapping cloud — 17³ samples in RGB space. */

const GRID = 17;

const VS_LINES = `#version 300 es
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aColor;
uniform mat4 uMvp;
out vec3 vColor;
void main() {
  vColor = aColor;
  gl_Position = uMvp * vec4(aPos, 1.0);
}
`;

const FS_LINES = `#version 300 es
precision highp float;
in vec3 vColor;
out vec4 fragColor;
void main() {
  fragColor = vec4(vColor, 1.0);
}
`;

const VS_POINTS = `#version 300 es
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aColor;
uniform mat4 uMvp;
out vec3 vColor;
void main() {
  vColor = aColor;
  vec4 clip = uMvp * vec4(aPos, 1.0);
  gl_Position = clip;
  float ndcScale = 1.0 / max(0.05, -clip.z);
  gl_PointSize = clamp(2.5 + ndcScale * 10.0, 2.0, 18.0);
}
`;

const FS_POINTS = `#version 300 es
precision highp float;
in vec3 vColor;
out vec4 fragColor;
void main() {
  vec2 d = gl_PointCoord - vec2(0.5);
  if (dot(d, d) > 0.25) discard;
  fragColor = vec4(vColor, 1.0);
}
`;

type Vec3 = [number, number, number];

function clamp01(v: number): number {
  return Math.min(1, Math.max(0, v));
}

function sampleLutTrilinear(
  samples: Float32Array,
  size: number,
  domainMin: Vec3,
  domainMax: Vec3,
  r: number,
  g: number,
  b: number,
): Vec3 {
  const q: Vec3 = [
    clamp01((r - domainMin[0]) / (domainMax[0] - domainMin[0] || 1)),
    clamp01((g - domainMin[1]) / (domainMax[1] - domainMin[1] || 1)),
    clamp01((b - domainMin[2]) / (domainMax[2] - domainMin[2] || 1)),
  ];
  const scale = (size - 1) / size;
  const tc: Vec3 = [
    q[0] * scale + 0.5 / size,
    q[1] * scale + 0.5 / size,
    q[2] * scale + 0.5 / size,
  ];
  const x = tc[0] * (size - 1);
  const y = tc[1] * (size - 1);
  const z = tc[2] * (size - 1);
  const x0 = Math.floor(x);
  const y0 = Math.floor(y);
  const z0 = Math.floor(z);
  const x1 = Math.min(size - 1, x0 + 1);
  const y1 = Math.min(size - 1, y0 + 1);
  const z1 = Math.min(size - 1, z0 + 1);
  const fx = x - x0;
  const fy = y - y0;
  const fz = z - z0;

  const read = (ri: number, gi: number, bi: number): Vec3 => {
    const idx = (bi * size * size + gi * size + ri) * 3;
    return [samples[idx], samples[idx + 1], samples[idx + 2]];
  };

  const c000 = read(x0, y0, z0);
  const c100 = read(x1, y0, z0);
  const c010 = read(x0, y1, z0);
  const c110 = read(x1, y1, z0);
  const c001 = read(x0, y0, z1);
  const c101 = read(x1, y0, z1);
  const c011 = read(x0, y1, z1);
  const c111 = read(x1, y1, z1);

  const lerp3 = (a: Vec3, b: Vec3, t: number): Vec3 => [
    a[0] + (b[0] - a[0]) * t,
    a[1] + (b[1] - a[1]) * t,
    a[2] + (b[2] - a[2]) * t,
  ];

  const c00 = lerp3(c000, c100, fx);
  const c10 = lerp3(c010, c110, fx);
  const c01 = lerp3(c001, c101, fx);
  const c11 = lerp3(c011, c111, fx);
  const c0 = lerp3(c00, c10, fy);
  const c1 = lerp3(c01, c11, fy);
  return lerp3(c0, c1, fz);
}

function buildPointCloud(
  samples: Float32Array,
  size: number,
  domainMin: Vec3,
  domainMax: Vec3,
): { positions: Float32Array; colors: Float32Array } {
  const n = GRID ** 3;
  const positions = new Float32Array(n * 3);
  const colors = new Float32Array(n * 3);
  let o = 0;
  const denom = GRID - 1;
  for (let bi = 0; bi < GRID; bi++) {
    for (let gi = 0; gi < GRID; gi++) {
      for (let ri = 0; ri < GRID; ri++) {
        const ir = ri / denom;
        const ig = gi / denom;
        const ib = bi / denom;
        const mapped = sampleLutTrilinear(samples, size, domainMin, domainMax, ir, ig, ib);
        positions[o] = mapped[0] - 0.5;
        positions[o + 1] = mapped[1] - 0.5;
        positions[o + 2] = mapped[2] - 0.5;
        colors[o] = mapped[0];
        colors[o + 1] = mapped[1];
        colors[o + 2] = mapped[2];
        o += 3;
      }
    }
  }
  return { positions, colors };
}

function buildWireframe(): { positions: Float32Array; colors: Float32Array } {
  const lo = -0.5;
  const hi = 0.5;
  const corners: Vec3[] = [
    [lo, lo, lo],
    [hi, lo, lo],
    [hi, hi, lo],
    [lo, hi, lo],
    [lo, lo, hi],
    [hi, lo, hi],
    [hi, hi, hi],
    [lo, hi, hi],
  ];
  const edges = [
    [0, 1],
    [1, 2],
    [2, 3],
    [3, 0],
    [4, 5],
    [5, 6],
    [6, 7],
    [7, 4],
    [0, 4],
    [1, 5],
    [2, 6],
    [3, 7],
  ];
  const alpha = 0.18;
  const gcol: Vec3 = [alpha, alpha, alpha];
  const origin: Vec3 = [lo, lo, lo];
  const axes: [Vec3, Vec3][] = [
    [[1, 0.15, 0.15], [hi, lo, lo]],
    [[0.15, 1, 0.15], [lo, hi, lo]],
    [[0.15, 0.25, 1], [lo, lo, hi]],
  ];

  const segments = edges.length + axes.length;
  const positions = new Float32Array(segments * 2 * 3);
  const colors = new Float32Array(segments * 2 * 3);
  let o = 0;
  for (const [a, b] of edges) {
    for (const idx of [a, b]) {
      const p = corners[idx];
      positions[o++] = p[0];
      positions[o++] = p[1];
      positions[o++] = p[2];
      colors[o - 3] = gcol[0];
      colors[o - 2] = gcol[1];
      colors[o - 1] = gcol[2];
    }
  }
  for (const [col, end] of axes) {
  positions[o++] = origin[0];
  positions[o++] = origin[1];
  positions[o++] = origin[2];
    colors[o - 3] = col[0];
    colors[o - 2] = col[1];
    colors[o - 1] = col[2];
    positions[o++] = end[0];
    positions[o++] = end[1];
    positions[o++] = end[2];
    colors[o - 3] = col[0];
    colors[o - 2] = col[1];
    colors[o - 1] = col[2];
  }
  return { positions, colors };
}

type Mat4 = Float32Array;

function mat4Identity(): Mat4 {
  const m = new Float32Array(16);
  m[0] = m[5] = m[10] = m[15] = 1;
  return m;
}

function mat4Multiply(a: Mat4, b: Mat4): Mat4 {
  const o = new Float32Array(16);
  for (let col = 0; col < 4; col++) {
    for (let row = 0; row < 4; row++) {
      o[col * 4 + row] =
        a[row] * b[col * 4 + 0] +
        a[4 + row] * b[col * 4 + 1] +
        a[8 + row] * b[col * 4 + 2] +
        a[12 + row] * b[col * 4 + 3];
    }
  }
  return o;
}

function mat4Perspective(fovY: number, aspect: number, near: number, far: number): Mat4 {
  const f = 1 / Math.tan(fovY / 2);
  const m = new Float32Array(16);
  m[0] = f / aspect;
  m[5] = f;
  m[10] = (far + near) / (near - far);
  m[11] = -1;
  m[14] = (2 * far * near) / (near - far);
  return m;
}

function mat4RotX(a: number): Mat4 {
  const c = Math.cos(a);
  const s = Math.sin(a);
  const m = mat4Identity();
  m[5] = c;
  m[6] = s;
  m[9] = -s;
  m[10] = c;
  return m;
}

function mat4RotY(a: number): Mat4 {
  const c = Math.cos(a);
  const s = Math.sin(a);
  const m = mat4Identity();
  m[0] = c;
  m[2] = -s;
  m[8] = s;
  m[10] = c;
  return m;
}

function mat4Translate(x: number, y: number, z: number): Mat4 {
  const m = mat4Identity();
  m[12] = x;
  m[13] = y;
  m[14] = z;
  return m;
}

export class LutCubeView {
  private canvas: HTMLCanvasElement;
  private gl: WebGL2RenderingContext;
  private progLines: WebGLProgram;
  private progPoints: WebGLProgram;
  private lineVao: WebGLVertexArrayObject;
  private pointVao: WebGLVertexArrayObject;
  private pointPosBuf: WebGLBuffer;
  private pointColBuf: WebGLBuffer;
  private lineCount = 0;
  private pointCount = 0;
  private locLineMvp: WebGLUniformLocation | null;
  private locPointMvp: WebGLUniformLocation | null;
  private yaw = 0.785;
  private pitch = -0.62;
  private distance = 2.35;
  private dragging = false;
  private lastX = 0;
  private lastY = 0;
  private raf = 0;
  private active = false;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    const gl = canvas.getContext("webgl2", {
      alpha: true,
      antialias: true,
      premultipliedAlpha: false,
    });
    if (!gl) throw new Error("WebGL2 不可用（色彩立方体）");
    this.gl = gl;
    this.progLines = this.createProgram(VS_LINES, FS_LINES);
    this.progPoints = this.createProgram(VS_POINTS, FS_POINTS);
    this.locLineMvp = gl.getUniformLocation(this.progLines, "uMvp");
    this.locPointMvp = gl.getUniformLocation(this.progPoints, "uMvp");
    this.lineVao = gl.createVertexArray()!;
    this.pointVao = gl.createVertexArray()!;
    this.pointPosBuf = gl.createBuffer()!;
    this.pointColBuf = gl.createBuffer()!;
    this.initWireframe();
    this.initPointVao();
    this.uploadPoints(new Float32Array(3), new Float32Array(3));
    gl.enable(gl.DEPTH_TEST);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    this.bindInteraction();
  }

  private createShader(type: number, source: string): WebGLShader {
    const gl = this.gl;
    const shader = gl.createShader(type)!;
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      throw new Error(gl.getShaderInfoLog(shader) || "shader compile failed");
    }
    return shader;
  }

  private createProgram(vs: string, fs: string): WebGLProgram {
    const gl = this.gl;
    const program = gl.createProgram()!;
    gl.attachShader(program, this.createShader(gl.VERTEX_SHADER, vs));
    gl.attachShader(program, this.createShader(gl.FRAGMENT_SHADER, fs));
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      throw new Error(gl.getProgramInfoLog(program) || "link failed");
    }
    return program;
  }

  private initWireframe(): void {
    const { positions, colors } = buildWireframe();
    this.lineCount = positions.length / 3;
    const gl = this.gl;
    gl.bindVertexArray(this.lineVao);
    const pbo = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, pbo);
    gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
    const cbo = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, cbo);
    gl.bufferData(gl.ARRAY_BUFFER, colors, gl.STATIC_DRAW);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 3, gl.FLOAT, false, 0, 0);
    gl.bindVertexArray(null);
  }

  private initPointVao(): void {
    const gl = this.gl;
    gl.bindVertexArray(this.pointVao);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.pointPosBuf);
    gl.bufferData(gl.ARRAY_BUFFER, 12, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.pointColBuf);
    gl.bufferData(gl.ARRAY_BUFFER, 12, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 3, gl.FLOAT, false, 0, 0);
    gl.bindVertexArray(null);
  }

  private uploadPoints(positions: Float32Array, colors: Float32Array): void {
    this.pointCount = positions.length / 3;
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.pointPosBuf);
    gl.bufferData(gl.ARRAY_BUFFER, positions, gl.DYNAMIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.pointColBuf);
    gl.bufferData(gl.ARRAY_BUFFER, colors, gl.DYNAMIC_DRAW);
  }

  setLut(
    samples: Float32Array,
    size: number,
    domainMin: [number, number, number],
    domainMax: [number, number, number],
  ): void {
    const cloud = buildPointCloud(samples, size, domainMin, domainMax);
    this.uploadPoints(cloud.positions, cloud.colors);
  }

  resize(): void {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = this.canvas.getBoundingClientRect();
    const w = Math.max(1, Math.floor(rect.width * dpr));
    const h = Math.max(1, Math.floor(rect.height * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
  }

  resetView(): void {
    this.yaw = 0.785;
    this.pitch = -0.62;
    this.distance = 2.35;
  }

  private mvpMatrix(): Mat4 {
    const aspect = this.canvas.width / this.canvas.height;
    const proj = mat4Perspective((50 * Math.PI) / 180, aspect, 0.05, 20);
    const view = mat4Translate(0, 0, -this.distance);
    const rot = mat4Multiply(mat4RotY(this.yaw), mat4RotX(this.pitch));
    return mat4Multiply(proj, mat4Multiply(view, rot));
  }

  drawFrame(): void {
    if (!this.active) return;
    this.resize();
    const gl = this.gl;
    const w = this.canvas.width;
    const h = this.canvas.height;
    gl.viewport(0, 0, w, h);
    gl.clearColor(0.09, 0.09, 0.1, 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    const mvp = this.mvpMatrix();

    gl.useProgram(this.progLines);
    gl.uniformMatrix4fv(this.locLineMvp, false, mvp);
    gl.bindVertexArray(this.lineVao);
    gl.drawArrays(gl.LINES, 0, this.lineCount);

    gl.useProgram(this.progPoints);
    gl.uniformMatrix4fv(this.locPointMvp, false, mvp);
    gl.bindVertexArray(this.pointVao);
    gl.drawArrays(gl.POINTS, 0, this.pointCount);
    gl.bindVertexArray(null);
  }

  setActive(on: boolean): void {
    this.active = on;
    if (on) {
      this.startLoop();
      this.drawFrame();
    } else {
      this.stopLoop();
    }
  }

  startLoop(): void {
    if (this.raf) return;
    const tick = () => {
      this.raf = requestAnimationFrame(tick);
      if (this.active) this.drawFrame();
    };
    this.raf = requestAnimationFrame(tick);
  }

  stopLoop(): void {
    if (this.raf) {
      cancelAnimationFrame(this.raf);
      this.raf = 0;
    }
  }

  private bindInteraction(): void {
    const canvas = this.canvas;
    canvas.addEventListener("mousedown", (ev) => {
      if (ev.button !== 0) return;
      this.dragging = true;
      this.lastX = ev.clientX;
      this.lastY = ev.clientY;
      ev.preventDefault();
    });
    window.addEventListener("mouseup", () => {
      this.dragging = false;
    });
    window.addEventListener("mousemove", (ev) => {
      if (!this.dragging) return;
      const dx = ev.clientX - this.lastX;
      const dy = ev.clientY - this.lastY;
      this.lastX = ev.clientX;
      this.lastY = ev.clientY;
      this.yaw += dx * 0.008;
      this.pitch = Math.min(1.2, Math.max(-1.2, this.pitch + dy * 0.008));
    });
    canvas.addEventListener(
      "wheel",
      (ev) => {
        ev.preventDefault();
        this.distance = Math.min(6, Math.max(1.2, this.distance + ev.deltaY * 0.004));
      },
      { passive: false },
    );
    canvas.addEventListener("dblclick", () => this.resetView());
  }

  destroy(): void {
    this.stopLoop();
  }
}
```

### 3.6 A/B与2D视口的坐标关系及状态边界

中键或空格+左键平移，鼠标位移除canvas CSS宽高，panY反号；wheel按1.08倍率，按钮1.25，zoom限0.25..8，双击fit。hold模式按住左键看原图，松手恢复。DOM分割线ratio按舞台屏幕x归一化，而shader判断的是经过zoom/pan/aspect后的图像vUv.x；非默认视口时二者未做完整坐标互转，阶段七只验证分屏组件可见，不能证明任意缩放平移下线与图像切分完全重合。VS_VIEW把zoom乘到UV，所以不能仅凭HUD“108%”断言图像几何真的放大8%。

StateStore只存params+strength快照，MAX_HISTORY=64，最多64个快照而非64次undo加初始态；bloom/media/external LUT/视图都不进快照，切换媒体也没有清空前端历史。没有持久化编辑工程文件。`destroy()`只停止RAF/部分删除FBO，源码未全面删除program/texture/buffer/window监听或处理webglcontextlost；长会话资源行为没有被当前测试证明。

源码：`frontend/src/core/state_store.ts:1`。

```typescript
import type { ColorParams, ParamKey } from "./params";
import { PARAM_KEYS, clampParam, identityParams } from "./params";

const MAX_HISTORY = 64;

export type CompareMode = "preview" | "split" | "hold" | "lut3d";

export interface ColorSnapshot {
  params: ColorParams;
  strength: number;
}

export type MediaInfo = {
  media_id: string;
  kind: "image" | "video";
  width: number;
  height: number;
  duration_s?: number;
  fps?: number;
  content_url: string;
};

export type Listener = () => void;

export class StateStore {
  params: ColorParams = identityParams();
  strength = 1;
  /** 光学晕光后处理强度，独立于 16 维 ColorParams */
  bloom = 0;
  media: MediaInfo | null = null;
  compareMode: CompareMode = "preview";
  splitRatio = 0.5;
  holdOriginal = false;
  aiSummary = "";
  aiSource = "";
  lutSize = 33;
  externalLut = false;

  private history: ColorSnapshot[] = [{ params: identityParams(), strength: 1 }];
  private historyIndex = 0;

  private listeners = new Set<Listener>();

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  emit(): void {
    for (const fn of this.listeners) {
      fn();
    }
  }

  snapshot(): ColorSnapshot {
    return {
      params: { ...this.params },
      strength: this.strength,
    };
  }

  private pushHistory(): void {
    const snap = this.snapshot();
    const cur = this.history[this.historyIndex];
    if (
      PARAM_KEYS.every((k) => cur.params[k] === snap.params[k]) &&
      cur.strength === snap.strength
    ) {
      return;
    }
    if (this.historyIndex < this.history.length - 1) {
      this.history = this.history.slice(0, this.historyIndex + 1);
    }
    this.history.push(snap);
    this.historyIndex = this.history.length - 1;
    if (this.history.length > MAX_HISTORY) {
      const drop = this.history.length - MAX_HISTORY;
      this.history = this.history.slice(drop);
      this.historyIndex -= drop;
    }
  }

  canUndo(): boolean {
    return this.historyIndex > 0;
  }

  canRedo(): boolean {
    return this.historyIndex < this.history.length - 1;
  }

  undo(): boolean {
    if (!this.canUndo()) return false;
    this.historyIndex -= 1;
    this.applySnapshot(this.history[this.historyIndex]);
    return true;
  }

  redo(): boolean {
    if (!this.canRedo()) return false;
    this.historyIndex += 1;
    this.applySnapshot(this.history[this.historyIndex]);
    return true;
  }

  private applySnapshot(snap: ColorSnapshot): void {
    this.params = { ...snap.params };
    this.strength = snap.strength;
    this.emit();
  }

  setParam(key: ParamKey, value: number, commit = true): void {
    this.params = { ...this.params, [key]: clampParam(key, value) };
    this.externalLut = false;
    // 拖动滑杆时 input 连续触发：只刷新预览，松手（change）才落一个快照，
    // 否则一次拖动会往撤销栈里塞进几十条中间态。
    if (commit) this.pushHistory();
    this.emit();
  }

  setParams(params: ColorParams): void {
    this.params = { ...params };
    this.externalLut = false;
    this.pushHistory();
    this.emit();
  }

  setStrength(value: number, commit = true): void {
    this.strength = Math.min(1, Math.max(0, value));
    if (commit) this.pushHistory();
    this.emit();
  }

  setBloom(value: number): void {
    this.bloom = Math.min(1, Math.max(0, value));
    this.emit();
  }

  resetParams(): void {
    this.params = identityParams();
    this.strength = 1;
    this.bloom = 0;
    this.pushHistory();
    this.emit();
  }
}
```

## 4. 色彩科学建模与3D LUT烘焙器（baker/）

### 4.1 完整16维契约及真实默认值

Python ColorParams为frozen dataclass；JSON字段为number（不是只允许整数），前端number。默认全部0，strength=1和bloom=0不属于这16维。版本为schema_version=2.0、algorithm_version=sdr-srgb-v2。前端三组为基础光影6维+白平衡与色彩5维+分离色调5维；Tk仍采用基础11维+分离5维。

| 英文键 | 中文名 | 类型 | 范围（闭区间） | 默认 | 实现意义 |
| --- | --- | --- | --- | --- | --- |
| exposure_ev | 曝光 (EV) | float / JSON number | (-2.0, 2.0) | 0 | 线性光乘2^EV，±2为1/4..4倍；随后裁剪。 |
| contrast | 对比度 | float / JSON number | (-100.0, 100.0) | 0 | 编码域中点0.5的符号幂曲线，正值增强中灰反差。 |
| temperature | 色温 | float / JSON number | (-100.0, 100.0) | 0 | 相对通道指数增益，正暖负冷；不是Kelvin或色适应矩阵。 |
| tint | 色调 | float / JSON number | (-100.0, 100.0) | 0 | 相对G与R/B增益，正品红负绿色。 |
| highlights | 高光 | float / JSON number | (-100.0, 100.0) | 0 | 按编码亮度平方y²加/减0.20倍权重。 |
| shadows | 阴影 | float / JSON number | (-100.0, 100.0) | 0 | 按(1−y)²加/减0.20倍权重。 |
| whites | 白色 | float / JSON number | (-100.0, 100.0) | 0 | 仅上半亮度，[(y−.5)/.5]²遮罩，幅度0.25。 |
| blacks | 黑色 | float / JSON number | (-100.0, 100.0) | 0 | 仅下半亮度，[(.5−y)/.5]²遮罩；正值抬黑。 |
| saturation | 饱和度 | float / JSON number | (-100.0, 100.0) | 0 | 围绕加权亮度的色差放缩，factor=1+s/100；不是HSL转换。 |
| vibrance | 自然饱和 | float / JSON number | (-100.0, 100.0) | 0 | 以1−(maxRGB−minRGB)抑制高色度像素增幅，没有显式肤色识别。 |
| hue | 色相旋转 | float / JSON number | (-180.0, 180.0) | 0 | 编码RGB亮度近似保持的3×3旋转矩阵角度。 |
| split_shadow_hue | 阴影色相 | float / JSON number | (0.0, 360.0) | 0 | HSV全饱和value1色相目标，经hue_to_rgb获得。 |
| split_shadow_amount | 阴影着色 | float / JSON number | (0.0, 100.0) | 0 | 阴影mix最大系数amount/100×.30×(1−y)²。 |
| split_highlight_hue | 高光色相 | float / JSON number | (0.0, 360.0) | 0 | 高光目标纯色相角。 |
| split_highlight_amount | 高光着色 | float / JSON number | (0.0, 100.0) | 0 | 高光mix系数amount/100×.30×y²。 |
| split_balance | 分离平衡 | float / JSON number | (-100.0, 100.0) | 0 | 给分离遮罩亮度加balance/100×.25；正值偏高光。 |

源码：`baker/params.py:249`。

```python
@dataclass(frozen=True)
class ColorParams:
    exposure_ev: float = 0.0
    contrast: float = 0.0
    temperature: float = 0.0
    tint: float = 0.0
    highlights: float = 0.0
    shadows: float = 0.0
    whites: float = 0.0
    blacks: float = 0.0
    saturation: float = 0.0
    vibrance: float = 0.0
    hue: float = 0.0
    split_shadow_hue: float = 0.0
    split_shadow_amount: float = 0.0
    split_highlight_hue: float = 0.0
    split_highlight_amount: float = 0.0
    split_balance: float = 0.0

    @classmethod
    def identity(cls) -> "ColorParams":
        return cls()

    @classmethod
    def from_dict(cls, params: Mapping[str, Any]) -> "ColorParams":
        normalized = normalize_params(params)
        return cls(**normalized)

    def as_dict(self) -> dict[str, float]:
        return {key: float(getattr(self, key)) for key in PARAM_KEYS}

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "algorithm_version": ALGORITHM_VERSION,
            "params": self.as_dict(),
        }

    def with_updates(self, **updates: float) -> "ColorParams":
        merged = self.as_dict()
        for key, value in updates.items():
            if key not in PARAM_RANGES:
                raise ParamError("SCHEMA_INVALID", f"未知参数: {key}")
            merged[key] = value
        normalized = normalize_params(merged)
        return replace(self, **normalized)

    def is_identity(self) -> bool:
        return all(abs(value) < 1e-12 for value in self.as_dict().values())
```

Schema验证拒绝未知额外属性、缺必填字段、布尔值、NaN/Infinity、重复JSON键与越界；归一化到6位小数、负零转0。严格解析并不自动clip越界AI数值。`ColorParams.from_dict → normalize_params`会为缺键补0、忽略未迭代的未知键；因此与完整文档的strict Schema入口不同。v1旧7维合法文档补其余9维为0，v1/v2约束原文如下。

源码：`schemas/color_params.v2.schema.json:1`。

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.local/ai_color_app/color_params.v2.schema.json",
  "title": "ColorParams v2",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "algorithm_version", "params"],
  "properties": {
    "schema_version": {
      "const": "2.0"
    },
    "algorithm_version": {
      "const": "sdr-srgb-v2"
    },
    "params": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "exposure_ev",
        "contrast",
        "temperature",
        "tint",
        "highlights",
        "shadows",
        "whites",
        "blacks",
        "saturation",
        "vibrance",
        "hue",
        "split_shadow_hue",
        "split_shadow_amount",
        "split_highlight_hue",
        "split_highlight_amount",
        "split_balance"
      ],
      "properties": {
        "exposure_ev": {
          "type": "number",
          "minimum": -2,
          "maximum": 2
        },
        "contrast": {
          "type": "number",
          "minimum": -100,
          "maximum": 100
        },
        "temperature": {
          "type": "number",
          "minimum": -100,
          "maximum": 100
        },
        "tint": {
          "type": "number",
          "minimum": -100,
          "maximum": 100
        },
        "highlights": {
          "type": "number",
          "minimum": -100,
          "maximum": 100
        },
        "shadows": {
          "type": "number",
          "minimum": -100,
          "maximum": 100
        },
        "whites": {
          "type": "number",
          "minimum": -100,
          "maximum": 100
        },
        "blacks": {
          "type": "number",
          "minimum": -100,
          "maximum": 100
        },
        "saturation": {
          "type": "number",
          "minimum": -100,
          "maximum": 100
        },
        "vibrance": {
          "type": "number",
          "minimum": -100,
          "maximum": 100
        },
        "hue": {
          "type": "number",
          "minimum": -180,
          "maximum": 180
        },
        "split_shadow_hue": {
          "type": "number",
          "minimum": 0,
          "maximum": 360
        },
        "split_shadow_amount": {
          "type": "number",
          "minimum": 0,
          "maximum": 100
        },
        "split_highlight_hue": {
          "type": "number",
          "minimum": 0,
          "maximum": 360
        },
        "split_highlight_amount": {
          "type": "number",
          "minimum": 0,
          "maximum": 100
        },
        "split_balance": {
          "type": "number",
          "minimum": -100,
          "maximum": 100
        }
      }
    }
  }
}
```

源码：`schemas/color_params.v1.schema.json:1`。

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://example.local/ai_color_app/color_params.v1.schema.json",
  "title": "ColorParams v1",
  "type": "object",
  "additionalProperties": false,
  "required": ["schema_version", "algorithm_version", "params"],
  "properties": {
    "schema_version": {
      "const": "1.0"
    },
    "algorithm_version": {
      "enum": ["sdr-srgb-v1", "sdr-srgb-v1.1"]
    },
    "params": {
      "type": "object",
      "additionalProperties": false,
      "required": [
        "exposure_ev",
        "contrast",
        "temperature",
        "tint",
        "highlights",
        "shadows",
        "saturation"
      ],
      "properties": {
        "exposure_ev": {
          "type": "number",
          "minimum": -2,
          "maximum": 2
        },
        "contrast": {
          "type": "number",
          "minimum": -100,
          "maximum": 100
        },
        "temperature": {
          "type": "number",
          "minimum": -100,
          "maximum": 100
        },
        "tint": {
          "type": "number",
          "minimum": -100,
          "maximum": 100
        },
        "highlights": {
          "type": "number",
          "minimum": -100,
          "maximum": 100
        },
        "shadows": {
          "type": "number",
          "minimum": -100,
          "maximum": 100
        },
        "saturation": {
          "type": "number",
          "minimum": -100,
          "maximum": 100
        }
      }
    }
  }
}
```

### 4.2 按真实顺序的非线性变换流水线

本实现主要是编码sRGB逐像素映射，只有曝光/白平衡在线性域完成。不是ACES、RAW显影、HDR tone mapping或完整色适应系统。记 (\ell(c)=.2126c_r+.7152c_g+.0722c_b)，(C(x)=clip(x,0,1))。

1. sRGB解码：(D(c)=c/12.92)（c≤.04045），否则(((c+.055)/1.055)^{2.4})。曝光：(l=D(c)2^{EV})。
2. (t=temperature/100,m=tint/100)，增益 (g=(2^{.25t+.10m},2^{-.20m},2^{-.25t+.10m}))。(l\leftarrow l\odot g)，裁剪后编码：(E(l)=12.92l)（l≤.0031308），否则(1.055l^{1/2.4}-.055)。
3. (p=2^{-contrast/100},z=2c-1)，(c=.5+.5sign(z)|z|^p)。枢轴是编码值.5，不是线性18%中灰；源码负指数修正了早期符号方向。
4. (y=\ell(c))，(\delta=.20[(shadows/100)(1-y)^2+(highlights/100)y^2])，(c=C(c+\delta))。
5. whites时 (w=C((\ell(c)-.5)/.5)^2)，(c=C(c+.25(whites/100)w))。然后blacks时重新算亮度，(w=C((.5-\ell(c))/.5)^2)，(c=C(c+.25(blacks/100)w))。**这些是平方遮罩，没有Smoothstep；白/黑作用范围是上/下半，不是提示词写的“约10%”。**
6. hue非0时 (c=C(cM^T))，矩阵完整系数见下列`_hue_matrix`源码。系数.213/.715/.072是近似权重，不能夸大为严格物理亮度守恒。
7. saturation：(f=1+s/100,y=\ell(c),c=C(y+f(c-y)))。没有RGB↔HSL转换。
8. vibrance：(chroma=C(\max c-\min c),f_v=1+(v/100)(1-chroma))，重算y后同形 (c=C(y+f_v(c-y)))。没有肤色、人脸或区域掩膜。
9. 分离色调仅在amount非0时进入：(y=C(\ell(c)+.25balance/100))。阴影 (k_s=.30amount_s/100(1-y)^2)，(c\leftarrow(1-k_s)c+k_s\,hueRGB_s)；高光 (k_h=.30amount_h/100\,y^2)，在已染阴影的c上再mix。两个遮罩共用进入分离步骤时的y，之后不会重新求y。
10. 输出C(c)。**分离着色没有额外的亮度重建/保持项**，能改变亮度；“含亮度保护”最多是较弱加权染色的直观描述，不是代码里的约束。

源码：`baker/color_transform.py:44`。

```python
def _hue_matrix(degrees: float) -> np.ndarray:
    """Rotation matrix that preserves the encoded-domain luma weights."""
    angle = math.radians(float(degrees))
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    return np.array(
        [
            [
                0.213 + cos_a * 0.787 - sin_a * 0.213,
                0.715 - cos_a * 0.715 - sin_a * 0.715,
                0.072 - cos_a * 0.072 + sin_a * 0.928,
            ],
            [
                0.213 - cos_a * 0.213 + sin_a * 0.143,
                0.715 + cos_a * 0.285 + sin_a * 0.140,
                0.072 - cos_a * 0.072 - sin_a * 0.283,
            ],
            [
                0.213 - cos_a * 0.213 - sin_a * 0.787,
                0.715 - cos_a * 0.715 + sin_a * 0.715,
                0.072 + cos_a * 0.928 + sin_a * 0.072,
            ],
        ],
        dtype=np.float64,
    )
```

源码：`baker/color_transform.py:28`。

```python
def hue_to_rgb(hue_degrees: float) -> np.ndarray:
    """Fully saturated hue at value 1, as an encoded-sRGB triple."""
    h = (float(hue_degrees) % 360.0) / 60.0
    x = 1.0 - abs(h % 2.0 - 1.0)
    sector = int(h) % 6
    table = (
        (1.0, x, 0.0),
        (x, 1.0, 0.0),
        (0.0, 1.0, x),
        (0.0, x, 1.0),
        (x, 0.0, 1.0),
        (1.0, 0.0, x),
    )
    return np.array(table[sector], dtype=np.float64)
```

源码：`baker/color_transform.py:70`。

```python
def srgb_decode(encoded: np.ndarray) -> np.ndarray:
    """sRGB electro-optical transfer function (W3C CSS Color 4)."""
    c = np.asarray(encoded, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
```

源码：`baker/color_transform.py:76`。

```python
def srgb_encode(linear: np.ndarray) -> np.ndarray:
    """Inverse sRGB transfer function (W3C CSS Color 4)."""
    c = np.asarray(linear, dtype=np.float64)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * (c ** (1.0 / 2.4)) - 0.055)
```

源码：`baker/color_transform.py:86`。

```python
def transform_rgb(rgb: np.ndarray, params: ColorParams) -> np.ndarray:
    """Apply the sdr-srgb-v2 pipeline to encoded-sRGB values.

    Input and output shape is (..., 3), values in [0, 1]. The operation is
    per-pixel and per-channel; no spatial information is used, so it can be
    baked into a 3D LUT exactly as documented in ADR-003.
    """
    c = np.asarray(rgb, dtype=np.float64)
    if c.shape[-1] != 3:
        raise ValueError("rgb must have a trailing dimension of 3")

    # 1-2. Decode to linear light, apply exposure.
    linear = srgb_decode(c) * (2.0 ** params.exposure_ev)

    # 3. Relative temperature/tint gains (not a chromatic adaptation matrix).
    t = params.temperature / 100.0
    m = params.tint / 100.0
    gain = np.array(
        [
            2.0 ** (0.25 * t + 0.10 * m),
            2.0 ** (-0.20 * m),
            2.0 ** (-0.25 * t + 0.10 * m),
        ],
        dtype=np.float64,
    )
    linear = linear * gain

    # 4. Clip in linear light, re-encode.
    c = srgb_encode(_clip01(linear))

    # 5. Contrast around 0.5, keeping 0 and 1 fixed.
    #
    # Deviation from the spec's literal p = 2**(contrast/100): that exponent
    # *lowers* midtone contrast for positive values (|2c-1| < 1 shrinks when
    # p > 1), which inverts the documented sign convention. v1.1 uses the
    # reciprocal exponent so positive contrast expands tones away from 0.5.
    # See docs/decisions/ADR-006-contrast-direction.md.
    p = 2.0 ** (-params.contrast / 100.0)
    signed = 2.0 * c - 1.0
    c = 0.5 + 0.5 * np.sign(signed) * np.abs(signed) ** p

    # 6. Shadows/highlights. Y here is an encoded-domain tone proxy.
    y = _luma(c)
    w_s = (1.0 - y) ** 2
    w_h = y**2
    delta = 0.20 * (
        (params.shadows / 100.0) * w_s + (params.highlights / 100.0) * w_h
    )
    c = _clip01(c + delta[..., None])

    # 6b. Whites/blacks. Windowed to the top/bottom half only, so midtones are
    # untouched and the pair stays clearly distinct from highlights/shadows.
    if params.whites:
        w = np.clip((_luma(c) - 0.5) / 0.5, 0.0, 1.0) ** 2
        c = _clip01(c + (params.whites / 100.0) * 0.25 * w[..., None])
    if params.blacks:
        w = np.clip((0.5 - _luma(c)) / 0.5, 0.0, 1.0) ** 2
        c = _clip01(c + (params.blacks / 100.0) * 0.25 * w[..., None])

    # 7. Global hue rotation (luma-weight preserving, encoded sRGB).
    if params.hue:
        c = _clip01(c @ _hue_matrix(params.hue).T)

    # 8. Saturation around the same luminance proxy.
    factor = 1.0 + params.saturation / 100.0
    y = _luma(c)
    c = _clip01(y[..., None] + factor * (c - y[..., None]))

    # 9. Vibrance: the same mix, but weighted toward low-chroma pixels so
    # already saturated colours (and skin) are protected.
    if params.vibrance:
        chroma = np.clip(c.max(axis=-1) - c.min(axis=-1), 0.0, 1.0)
        weight = np.asarray(1.0 - chroma, dtype=np.float64)
        v_factor = 1.0 + (params.vibrance / 100.0) * weight
        y = _luma(c)
        c = _clip01(y[..., None] + v_factor[..., None] * (c - y[..., None]))

    # 10. Split toning: tint shadows and highlights separately.
    if params.split_shadow_amount or params.split_highlight_amount:
        y = np.clip(
            _luma(c) + (params.split_balance / 100.0) * 0.25, 0.0, 1.0
        )
        if params.split_shadow_amount:
            tint = hue_to_rgb(params.split_shadow_hue)
            k = np.asarray(
                (params.split_shadow_amount / 100.0) * 0.30 * (1.0 - y) ** 2
            )
            c = c * (1.0 - k[..., None]) + tint * k[..., None]
        if params.split_highlight_amount:
            tint = hue_to_rgb(params.split_highlight_hue)
            k = np.asarray(
                (params.split_highlight_amount / 100.0) * 0.30 * y**2
            )
            c = c * (1.0 - k[..., None]) + tint * k[..., None]

    # 11. Encoded sRGB output.
    return _clip01(c)
```

源码：`baker/color_transform.py:185`。

```python
def lut_grid(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Return (values, samples) for an N^3 grid.

    values has shape (N, 3); samples is the flattened encoded-RGB grid in
    .cube order (R fastest, B slowest) with shape (N^3, 3).
    """
    if n < 2 or n > 65:
        raise ValueError("LUT size must be in [2, 65]")
    values = np.linspace(0.0, 1.0, n, dtype=np.float64)
    b, g, r = np.meshgrid(values, values, values, indexing="ij")
    samples = np.stack([r.ravel(), g.ravel(), b.ravel()], axis=1)
    return values, samples
```

源码：`baker/color_transform.py:199`。

```python
def bake_lut(params: ColorParams, n: int = 33) -> np.ndarray:
    """Bake the base LUT (strength not applied) as float32 samples."""
    _, grid = lut_grid(n)
    baked = transform_rgb(grid, params)
    return np.ascontiguousarray(baked.astype(np.float32))
```

源码：`baker/color_transform.py:263`。

```python
def sample_lut(
    samples: np.ndarray,
    n: int,
    rgb: np.ndarray,
    domain_min: tuple[float, float, float] = (0.0, 0.0, 0.0),
    domain_max: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> np.ndarray:
    """GPU-equivalent LUT lookup (clamped domain) without strength."""
    dmin = np.asarray(domain_min, dtype=np.float64)
    dmax = np.asarray(domain_max, dtype=np.float64)
    c = np.asarray(rgb, dtype=np.float64)
    q = np.clip((c - dmin) / (dmax - dmin), 0.0, 1.0)
    return _trilinear(samples, n, q)
```

源码：`baker/color_transform.py:278`。

```python
def apply_effect_to_rgb(
    rgb: np.ndarray,
    samples: np.ndarray,
    n: int,
    strength: float = 1.0,
    domain_min: tuple[float, float, float] = (0.0, 0.0, 0.0),
    domain_max: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> np.ndarray:
    """CPU reference for the GPU shader: lookup, mix by strength, clamp."""
    c = np.asarray(rgb, dtype=np.float64)
    mapped = sample_lut(samples, n, c, domain_min, domain_max)
    mixed = (1.0 - float(strength)) * c + float(strength) * mapped
    return np.clip(mixed, 0.0, 1.0)
```

### 4.3 LUT内存、.cube规范与导出一致性

`lut_grid(N)`使用`b,g,r=np.meshgrid(values,values,values,indexing='ij')`，stack(r.ravel,g.ravel,b.ravel)，`bake_lut`输出C-contiguous float32 `(N³,3)`。R最内层最快、B最外层最慢；标量索引 (i=3[r+N(g+Nb)]+channel)。33³=35,937顶点=431,244原始字节；65³=274,625顶点=3,295,500字节；17³=4,913顶点=58,956字节。API base64体积另乘4/3（这些字节数都可整除3）。

读取器允许N=2..65（不是只允许17/33/65），API烘焙仅33/65，预览默认33。支持UTF-8 BOM、空行、#注释、TITLE、LUT_3D_SIZE、DOMAIN_MIN/MAX；不支持1D或混合LUT、*_INPUT_RANGE和未知扩展；重复header/数据后header失败，domain每通道max>min，必须恰有N³行、每行三个有限样本。输入样本允许0..1以外但绝对值≤65504，shader再clip；文件≤32MiB。

写出头结构：

```text
TITLE "ai_color_app"
LUT_3D_SIZE 33
DOMAIN_MIN 0 0 0
DOMAIN_MAX 1 1 1
<R> <G> <B>
… N³ 行
```

Python writer以float32九位有效数字`.9g`、LF、UTF-8写`.tmp`，flush+fsync+os.replace，再load_cube校验回读最大误差≤1e−6。正式export strength已经烘入样本 `(1−s)grid+s*base`，用户导入普通cube不需专属强度元数据。

`RenderPipeline.export_lut`先33，再在验证diff>2/255时尝试65；校验13色卡点+4096固定种子20261020随机点，对比解析式或源LUT效果；若65仍>2则附`.strength.json`警告。因此“最终导出固定65³”不是当前实现。`export_image`仍使用参数33³预览LUT，最终原图分辨率导出并不自动升65；`bake_video_cube`默认33。

源码：`baker/cube_reader.py:39`。

```python
@dataclass(frozen=True)
class CubeLut:
    path: Path
    size: int
    domain_min: tuple[float, float, float]
    domain_max: tuple[float, float, float]
    title: str
    samples: np.ndarray  # float32, shape (N^3, 3), R fastest
    sha256: str

    @property
    def sample_count(self) -> int:
        return self.size * self.size * self.size

    def summary(self) -> str:
        return (
            f"{self.size}³，domain "
            f"[{self.domain_min[0]:g},{self.domain_min[1]:g},{self.domain_min[2]:g}] → "
            f"[{self.domain_max[0]:g},{self.domain_max[1]:g},{self.domain_max[2]:g}]"
        )
```

源码：`baker/cube_writer.py:31`。

```python
def write_cube(
    path: str | Path,
    size: int,
    samples: np.ndarray,
    *,
    title: str = "ai_color_app",
    domain_min: tuple[float, float, float] = (0.0, 0.0, 0.0),
    domain_max: tuple[float, float, float] = (1.0, 1.0, 1.0),
    verify: bool = True,
) -> CubeLut:
    if not 2 <= int(size) <= 65:
        raise CubeWriteError("LUT_UNSUPPORTED", "LUT 尺寸必须在 [2, 65]")
    array = np.asarray(samples, dtype=np.float32)
    expected = int(size) ** 3
    if array.shape != (expected, 3):
        raise CubeWriteError(
            "LUT_PARSE_ERROR",
            f"样本形状 {array.shape} 与 {size}³ 不匹配",
        )
    if not np.all(np.isfinite(array)):
        raise CubeWriteError("LUT_PARSE_ERROR", "拒绝写入非有限样本")
    if np.max(np.abs(array)) > 65504.0:
        raise CubeWriteError("LUT_UNSUPPORTED", "样本超出安全上限 65504")
    for low, high in zip(domain_min, domain_max):
        if not (math.isfinite(low) and math.isfinite(high) and high > low):
            raise CubeWriteError("LUT_PARSE_ERROR", "无效 domain")

    clean_title = "".join(ch for ch in title if ch >= " ")[:256].replace('"', "'")
    lines = [
        f'TITLE "{clean_title}"',
        f"LUT_3D_SIZE {int(size)}",
        "DOMAIN_MIN "
        + " ".join(format(float(v), ".9g") for v in domain_min),
        "DOMAIN_MAX "
        + " ".join(format(float(v), ".9g") for v in domain_max),
    ]
    lines.extend(
        " ".join(_format_sample(v) for v in row) for row in array.tolist()
    )
    payload = "\n".join(lines) + "\n"

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise CubeWriteError("EXPORT_IO", f"写入 LUT 失败: {exc}") from exc

    if not verify:
        loaded = load_cube(target)
        return loaded

    loaded = load_cube(target)
    if loaded.size != int(size):
        raise CubeWriteError("LUT_PARSE_ERROR", "LUT 回读尺寸不一致")
    max_diff = float(np.max(np.abs(loaded.samples.astype(np.float64) - array)))
    if max_diff > 1e-6:
        raise CubeWriteError(
            "LUT_PARSE_ERROR", f"LUT 回读不一致，max diff={max_diff:g}"
        )
    return loaded
```

### 4.4 六套预设数据原文

预设都由`baker.params.load_preset/list_presets`加载，经v1/v2验证。与`ai.prompts.STYLE_PRESETS`六条意图chip不是同一数据集合。

源码：`presets/identity.json:1`。

```json
{
  "schema_version": "2.0",
  "algorithm_version": "sdr-srgb-v2",
  "params": {
    "exposure_ev": 0,
    "contrast": 0,
    "temperature": 0,
    "tint": 0,
    "highlights": 0,
    "shadows": 0,
    "whites": 0,
    "blacks": 0,
    "saturation": 0,
    "vibrance": 0,
    "hue": 0,
    "split_shadow_hue": 0,
    "split_shadow_amount": 0,
    "split_highlight_hue": 0,
    "split_highlight_amount": 0,
    "split_balance": 0
  }
}
```

源码：`presets/warm.json:1`。

```json
{
  "schema_version": "2.0",
  "algorithm_version": "sdr-srgb-v2",
  "params": {
    "exposure_ev": 0.15,
    "contrast": 8,
    "temperature": 32,
    "tint": 3,
    "highlights": -12,
    "shadows": 10,
    "whites": 4,
    "blacks": -6,
    "saturation": 8,
    "vibrance": 10,
    "hue": 0,
    "split_shadow_hue": 30,
    "split_shadow_amount": 12,
    "split_highlight_hue": 45,
    "split_highlight_amount": 14,
    "split_balance": 10
  }
}
```

源码：`presets/cool.json:1`。

```json
{
  "schema_version": "2.0",
  "algorithm_version": "sdr-srgb-v2",
  "params": {
    "exposure_ev": -0.05,
    "contrast": 12,
    "temperature": -34,
    "tint": -4,
    "highlights": -8,
    "shadows": 6,
    "whites": -4,
    "blacks": 4,
    "saturation": -4,
    "vibrance": 6,
    "hue": 0,
    "split_shadow_hue": 210,
    "split_shadow_amount": 14,
    "split_highlight_hue": 195,
    "split_highlight_amount": 8,
    "split_balance": -10
  }
}
```

源码：`presets/soft.json:1`。

```json
{
  "schema_version": "2.0",
  "algorithm_version": "sdr-srgb-v2",
  "params": {
    "exposure_ev": 0.2,
    "contrast": -14,
    "temperature": 6,
    "tint": 2,
    "highlights": -18,
    "shadows": 22,
    "whites": -10,
    "blacks": 14,
    "saturation": -8,
    "vibrance": 4,
    "hue": 0,
    "split_shadow_hue": 40,
    "split_shadow_amount": 6,
    "split_highlight_hue": 50,
    "split_highlight_amount": 8,
    "split_balance": 0
  }
}
```

源码：`presets/cinematic.json:1`。

```json
{
  "schema_version": "2.0",
  "algorithm_version": "sdr-srgb-v2",
  "params": {
    "exposure_ev": 0.05,
    "contrast": 18,
    "temperature": 6,
    "tint": -2,
    "highlights": -22,
    "shadows": 8,
    "whites": -6,
    "blacks": -8,
    "saturation": -6,
    "vibrance": 4,
    "hue": 0,
    "split_shadow_hue": 190,
    "split_shadow_amount": 26,
    "split_highlight_hue": 35,
    "split_highlight_amount": 22,
    "split_balance": 6
  }
}
```

源码：`presets/mono.json:1`。

```json
{
  "schema_version": "2.0",
  "algorithm_version": "sdr-srgb-v2",
  "params": {
    "exposure_ev": 0.05,
    "contrast": 22,
    "temperature": 0,
    "tint": 0,
    "highlights": -10,
    "shadows": 6,
    "whites": 6,
    "blacks": -10,
    "saturation": -100,
    "vibrance": 0,
    "hue": 0,
    "split_shadow_hue": 0,
    "split_shadow_amount": 0,
    "split_highlight_hue": 0,
    "split_highlight_amount": 0,
    "split_balance": 0
  }
}
```

## 5. 双模AI意图引擎、FastAPI编排与媒体任务（ai/、api/、app/）

### 5.1 在线结构化意图与错误恢复

`runAi → api.aiPropose(intent,current_params,true) → /api/ai/propose → ColorParams.from_dict(current) → build_provider(load_config) → generate → Proposal → /api/params/validate → StateStore.setParams → rebakeLut`。Web自动应用结果；Tk保留proposal确认逻辑并用document/revision/请求序号过滤过时结果。AI输入是自然语言和当前16参数，没有将图像或视频像素发给DeepSeek；因此不能写成视觉多模态内容理解。

`build_user_message`将当前参数JSON与截断2000字符的需求组合；SYSTEM_PROMPT要求完整v2 JSON、16范围/幅度引导和三个例子。HTTP POST `<base_url>/chat/completions`，`response_format={type:json_object}`、temperature默认.3、max_tokens1200、stream=false。**没有向服务端传完整JSON Schema的strict结构化输出模式**；格式/范围由返回后的本地Draft202012Validator保证。

默认AIConfig read30s/connect10s/pool5s/总预算65s，max_retries=2即最多3次尝试，配置可0..5重试；退避min(2^(attempt−1),2)+随机0..0.25s，受deadline约束。408/425/429/500/502/503/504及网络异常可重试；401/403鉴权错误不重试。Schema错误最多一次修复对话且消耗同一个尝试次数预算。响应累计≤64KiB，禁止redirect，取消检查在请求前/尝试间，不能声称可立即中断所有阻塞read。

无key或offline_only走OfflineProvider；不支持的provider/无效HTTPS配置会AIError。API捕获AIError且allow_offline_fallback=true时离线重试；这与“所有异常自动降级”不同。key只从环境/.env读取；本归档没有读取或输出密钥。源码有关模型停用日期的注释未经厂商核对，不作为论文外部事实。

源码：`ai/provider.py:20`。

```python
@dataclass(frozen=True)
class Proposal:
    params: ColorParams
    summary: str
    source: str  # "ai" | "offline"
    provider: str
    model: str
```

源码：`ai/provider.py:29`。

```python
@dataclass(frozen=True)
class AIConfig:
    provider: str = "deepseek"
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    api_key: str = ""
    timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 10.0
    total_timeout_seconds: float = 65.0
    pool_timeout_seconds: float = 5.0
    max_retries: int = 2
    temperature: float = 0.3
    offline_only: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.api_key) and not self.offline_only

    @property
    def status(self) -> str:
        if self.offline_only:
            return "离线模式（配置强制）"
        if not self.api_key:
            return "在线未配置（缺少 AI_API_KEY）"
        if self.model in RETIRED_MODELS:
            return (
                f"在线 · {self.provider} · {self.model}（该型号已停用，"
                "请改为 deepseek-flash）"
            )
        return f"在线 · {self.provider} · {self.model}"
```

源码：`ai/prompts.py:140`。

```python
def build_user_message(
    intent: str, current_params: ColorParams | dict[str, Any]
) -> str:
    """Compose the single user turn: current state plus the new intent."""
    params = (
        current_params.as_dict()
        if isinstance(current_params, ColorParams)
        else dict(current_params)
    )
    text = (intent or "").strip()[:MAX_INTENT_CHARS]
    return (
        "当前参数（作为起点，可调整）："
        + json.dumps(params, ensure_ascii=False, sort_keys=True)
        + "\n调色需求：\n"
        + text
    )
```

源码：`ai/deepseek.py:51`。

```python
    def generate(
        self,
        intent: str,
        current_params: ColorParams,
        cancel_event: threading.Event | None = None,
    ) -> Proposal:
        request_id = uuid.uuid4().hex[:10]
        intent = (intent or "").strip()[:MAX_INTENT_CHARS]
        if not intent:
            raise AIError("AI_SCHEMA", "调色描述为空")
        if cancel_event is not None and cancel_event.is_set():
            raise AIError("CANCELLED", "请求已取消")

        deadline = time.monotonic() + self.config.total_timeout_seconds
        base_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_user_message(intent, current_params),
            },
        ]
        messages = list(base_messages)
        max_attempts = 1 + self.config.max_retries
        attempt = 0
        repair_used = False

        while attempt < max_attempts:
            attempt += 1
            if cancel_event is not None and cancel_event.is_set():
                raise AIError("CANCELLED", "请求已取消")
            remaining = deadline - time.monotonic()
            if remaining <= 1.0:
                raise AIError("AI_NETWORK", "请求总时限已到")

            started = time.monotonic()
            try:
                content = self._post(messages, remaining, request_id)
            except _Retryable as exc:
                elapsed = (time.monotonic() - started) * 1000.0
                LOGGER.info(
                    "request_id=%s provider=%s model=%s attempt=%d elapsed_ms=%.1f code=%s",
                    request_id,
                    "deepseek",
                    self.model,
                    attempt,
                    elapsed,
                    exc.code,
                )
                if attempt >= max_attempts or time.monotonic() >= deadline:
                    raise AIError(exc.code, exc.message) from exc
                self._backoff(attempt, deadline)
                continue

            try:
                params = self._parse(content)
            except AIError as exc:
                if exc.code != "AI_SCHEMA":
                    raise
                LOGGER.info(
                    "request_id=%s provider=deepseek attempt=%d validation=%s",
                    request_id,
                    attempt,
                    exc.code,
                )
                if repair_used or attempt >= max_attempts:
                    raise AIError(
                        "AI_SCHEMA",
                        "模型输出未通过本地 Schema 校验；已保留当前参数",
                    ) from exc
                repair_used = True
                messages = list(base_messages) + [
                    {"role": "assistant", "content": content[:4000]},
                    {"role": "user", "content": _repair_prompt(str(exc))},
                ]
                continue

            LOGGER.info(
                "request_id=%s provider=deepseek attempt=%d elapsed_ms=%.1f code=OK",
                request_id,
                attempt,
                (time.monotonic() - started) * 1000.0,
            )
            return Proposal(
                params=params,
                summary=summary_from_params(params),
                source="ai",
                provider="deepseek",
                model=self.model,
            )

        raise AIError("AI_SCHEMA", "模型输出未通过校验")
```

### 5.2 离线混合意图引擎：当前比“两阶段”多一个数值优先入口

1. `_parse_numeric_assignments`识别带显式正负号的10类字段（色温/tint/EV/highlights/shadows/whites/blacks/saturation/vibrance/contrast），若≥2个不同字段命中，直接在current上做绝对目标赋值并clamp；不是delta，也不解析分离色调具体数值。仅1个数值命中不进入该捷径，不能写成任意自然语言数字都可精确赋值。
2. `_match_style`按mono→cinematic→warm→cool→soft→identity优先级做子串匹配，先剔除“微暖/微冷”干扰；纯风格走load_preset。通透修饰通过with_updates**替换**EV=.2/shadows15/highlights−12，鲜艳修饰替换vibrance22/saturation10；注释“叠加”不代表数值加法。模板路径Proposal.model实际为template，规则路径为template+rules。
3. 显式参数/程度/极值时解析directive；`_window_polarity`按每个参数名位置左右各6字符窗口判方向，down cues优先，不是分词/句法模型。出现其他参数名时禁止泛“亮/暗”污染曝光，温度冷/暖形容词有专属规则。当前规则spec仅8维（曝光/对比/色温/饱和/高光/阴影/白/黑）；不能宣称离线口语规则覆盖所有16维。
4. 再/更/一点/一些/稍微等为小步长：EV±.25，其余±15；普通指令EV±.40，其余±25；最/极限/全部去掉/完全/越等直接吸附范围端点。先手工_clamp再ColorParams.from_dict。通常相对current；有风格但无增量/极值/数值时可能以模板作base。
5. 无模板且无directive则原样返回current，四条噪声测试均不改参数；这是有限测试集结论，不是对任意噪声的数学零误触发保证。子串词典仍可能有歧义。该引擎是确定性规则，不是训练模型或LLM。

源码：`ai/offline.py:243`。

```python
def _window_polarity(text: str, noun: str, spec: _ParamSpec) -> int:
    """Decide +1/-1 for every occurrence of ``noun``; negative cues win."""
    start = 0
    while True:
        index = text.find(noun, start)
        if index < 0:
            return 0
        window = text[max(0, index - _WINDOW) : index + len(noun) + _WINDOW]
        if _hits(window, spec.down):
            return -1
        if _hits(window, spec.up):
            return 1
        start = index + len(noun)
```

源码：`ai/offline.py:325`。

```python
def _apply(
    base: ColorParams,
    directives: list[tuple[str, int]],
    *,
    extreme: bool,
    incremental: bool,
) -> tuple[ColorParams, list[str]]:
    """Apply deltas (or endpoint snaps) on ``base`` and describe the edit."""
    values = base.as_dict()
    notes: list[str] = []
    for key, direction in directives:
        low, high = PARAM_RANGES[key]
        if extreme:
            value = high if direction > 0 else low
            notes.append(f"{key} → {_fmt_value(key, value)}（推到量程端点）")
        else:
            if key == "exposure_ev":
                step = _STEP_SMALL_EV if incremental else _STEP_NORMAL_EV
            else:
                step = _STEP_SMALL if incremental else _STEP_NORMAL
            value = values[key] + direction * step
            notes.append(
                f"{key} {_fmt_value(key, values[key])} → {_fmt_value(key, value)}"
                f"（{'增量' if incremental else '标准'}步长 {_fmt_value(key, direction * step)}）"
            )
        values[key] = value
    return ColorParams.from_dict(_clamp(values)), notes
```

源码：`ai/offline.py:379`。

```python
def _parse_numeric_assignments(text: str) -> dict[str, float]:
    """Structured chips like「色温 +6」— value is the grading target, not a template."""
    updates: dict[str, float] = {}
    for pattern, key in _NUMERIC_ASSIGNMENTS:
        match = pattern.search(text)
        if not match:
            continue
        raw = match.group(1).replace(" ", "")
        updates[key] = float(raw)
    return updates
```

源码：`ai/offline.py:407`。

```python
class OfflineProvider:
    name = "offline"
    model = "template+rules"

    def generate(
        self,
        intent: str,
        current_params: ColorParams,
        cancel_event: threading.Event | None = None,
    ) -> Proposal:
        if cancel_event is not None and cancel_event.is_set():
            raise AIError("CANCELLED", "请求已取消")

        text = (intent or "").strip().lower()
        numeric = _parse_numeric_assignments(text)
        if len(numeric) >= 2:
            merged = current_params.as_dict()
            for key, value in numeric.items():
                low, high = PARAM_RANGES[key]
                merged[key] = min(max(float(value), low), high)
            params = ColorParams.from_dict(merged)
            bits = [f"{k} {numeric[k]:+g}" for k in numeric]
            return Proposal(
                params=params,
                summary=f"按结构化数值解析：{', '.join(bits)}。{summary_from_params(params)}",
                source="offline",
                provider="offline",
                model=self.model,
            )

        style = _match_style(text) if text else None
        incremental = _hits(text, _INCREMENTAL_MARKERS)
        extreme = _hits(text, _EXTREME_MARKERS)
        body = _strip_style_words(text)
        explicit = _has_explicit_param(body)
        directives = _parse_directives(text) if (explicit or incremental or extreme) else []

        # Pure look description, or a style word we cannot turn into a delta:
        # fall back to the shipped template (byte-identical to the preset file).
        pure_style = style is not None and not (incremental or extreme or explicit or numeric)
        if pure_style or (
            style is not None and not directives and not _has_numeric_color_ops(text)
        ):
            return self._from_preset(style, text)

        if not directives:
            # 关键：无法匹配时绝不返回全 0 参数覆盖用户当前编辑。
            return Proposal(
                params=current_params,
                summary=(
                    "离线模式未能识别该描述，已保留当前参数不变。"
                    "可尝试「暖色胶片」「清透日系」「黑白」或「高光压一点」「曝光拉到最亮」。"
                ),
                source="offline",
                provider="offline",
                model=self.model,
            )

        # Relative edits accumulate on the user's current state. A look word
        # without a degree modifier becomes the base of the edit; extreme
        # commands stay surgical and only snap the named parameter.
        if (
            style is not None
            and not incremental
            and not extreme
            and not _has_numeric_color_ops(text)
        ):
            base, _ = load_preset(style[0])
            prefix = f"{style[1]}，在其基础上"
        else:
            base = current_params
            prefix = "在原有参数基础上"

        params, notes = _apply(
            base, directives, extreme=extreme, incremental=incremental
        )
        detail = "，".join(notes)
        mode = "极值" if extreme else ("增量" if incremental else "标准")
        return Proposal(
            params=params,
            summary=f"{prefix}按{mode}规则调整：{detail}。{summary_from_params(params)}",
            source="offline",
            provider="offline",
            model=self.model,
        )

    def _from_preset(self, style: tuple[str, str], text: str) -> Proposal:
        chosen, note = style
        base, _ = load_preset(chosen)
        shifts: dict[str, float] = {}
        if _hits(text, _TONE_TRANSLUCENT):
            shifts.update(_TRANSLUCENT_SHIFT)
        if _hits(text, _TONE_VIVID):
            shifts.update(_VIVID_SHIFT)

        params = base.with_updates(**shifts) if shifts else base
        extras = ""
        if shifts:
            bits = [f"{k} {v:+g}" for k, v in shifts.items()]
            extras = "；叠加 " + "，".join(bits)
        return Proposal(
            params=params,
            summary=f"{note}{extras}。{summary_from_params(params)}",
            source="offline",
            provider="offline",
            model="template",
        )
```

### 5.3 全部HTTP/WS接口（源码路由）

| 方法 | 路径 | 真实handler | 源码行 |
| --- | --- | --- | --- |
| GET | /api/presets | api_presets | 127 |
| POST | /api/params/validate | api_validate | 136 |
| POST | /api/ai/propose | api_ai_propose | 150 |
| POST | /api/lut/bake | api_lut_bake | 174 |
| POST | /api/lut/upload_cube | api_lut_upload_cube | 190 |
| POST | /api/media/upload | api_media_upload | 220 |
| GET | /api/media/{media_id}/content | api_media_content | 245 |
| POST | /api/histogram | api_histogram | 253 |
| POST | /api/export/image | api_export_image | 318 |
| POST | /api/export/video | api_export_video | 348 |
| POST | /api/export/lut | api_export_lut | 446 |
| GET | /api/jobs/{job_id} | api_job_status | 486 |
| GET | /api/jobs/{job_id}/download | api_job_download | 506 |
| WEBSOCKET | /ws/jobs/{job_id} | ws_job | 517 |

额外`/openapi.json`、`/docs`、`/docs/oauth2-redirect`、`/redoc`是FastAPI默认文档路由，不是业务端点。CORS允许localhost/127.0.0.1的无端口、3000、5173来源，credentials=true；无登录/多租户会话设计。

请求模型直接摘录（字段/默认值以此为准）：

源码：`api/server.py:66`。

```python
class ParamsValidateBody(BaseModel):
    params: dict[str, Any]
```

源码：`api/server.py:70`。

```python
class AiProposeBody(BaseModel):
    intent: str
    current_params: dict[str, Any] = Field(default_factory=dict)
    allow_offline_fallback: bool = True
```

源码：`api/server.py:76`。

```python
class LutBakeBody(BaseModel):
    params: dict[str, Any]
    size: int = 33
```

源码：`api/server.py:81`。

```python
class HistogramBody(BaseModel):
    media_id: str | None = None
    image_b64: str | None = None
```

源码：`api/server.py:86`。

```python
class ExportImageBody(BaseModel):
    media_id: str
    params: dict[str, Any]
    strength: float = 1.0
    format: str = "PNG"
```

源码：`api/server.py:93`。

```python
class ExportVideoBody(BaseModel):
    media_id: str
    params: dict[str, Any]
    strength: float = 1.0
```

源码：`api/server.py:99`。

```python
class ExportLutBody(BaseModel):
    params: dict[str, Any]
    strength: float = 1.0
```

成功信封`{code:0,message:'ok',data:…}`；错误为带HTTP状态的JSONResponse、code非0。LUT payload字段为lut_id(SHA256原始样本)、size、domain_min/max、data_b64（连续float32本机字节序），浏览器atob→Uint8Array→Float32Array；在当前LE平台一致，没有显式跨大小端协商。

`POST /api/lut/bake`仅N=33/65。`upload_cube`读取真实domain但`_lut_payload`硬编码返回[0,0,0]/[1,1,1]，因此非默认domain外部LUT在Web预览不能保证正确。Web外部LUT导入仅存在浏览器纹理/布尔状态；export请求模型没有external_lut或bloom，仍只导出params+strength，**预览与下载不保证一致**。这不影响Tk的external_lut导出路径已实现。

`POST /api/histogram`是CPU原图或image_b64统计；Web实时直方图用本地FBO，不循环请求该接口。HTTP内容端点返回上传原文件，未以规范化RGBA替换，所以浏览器ICC/EXIF/视频色彩处理与Python SourceImage不构成已验证逐位一致。

导出image/lut/video返回job_id；GET状态返回kind/status/progress/message/result_path/error/detail，DONE加download_url；download以FileResponse发送文件。`api.job_runner.run_job`每任务一个daemon thread，记录在进程内dict+Lock；没有取消端点、并发队列上限或任务状态磁盘恢复。WS每250ms发code信封中的status/progress/result_path/error，终态关闭循环；前端同时800ms轮询，不是仅在WS失败才轮询。

源码：`api/server.py:104`。

```python
def _lut_payload(samples: np.ndarray, size: int) -> dict[str, Any]:
    raw = np.ascontiguousarray(samples, dtype=np.float32).tobytes()
    digest = hashlib.sha256(raw).hexdigest()
    return {
        "lut_id": digest,
        "size": int(size),
        "domain_min": [0.0, 0.0, 0.0],
        "domain_max": [1.0, 1.0, 1.0],
        "data_b64": base64.standard_b64encode(raw).decode("ascii"),
    }
```

源码：`api/job_runner.py:19`。

```python
@dataclass
class JobRecord:
    job_id: str
    kind: str
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    message: str = ""
    result_path: str | None = None
    error: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
```

### 5.4 状态模型、历史记录与持久化边界

Python `AppState`持有document_id/revision/SourceImage/preview/params/strength/模式/外部LUT/视口/视频；`DocumentSession`不依赖Tk，MAX_COLOR_HISTORY=64，其ColorSnapshot存params/strength/mode/source_label，未保存external_lut实体。当前FastAPI并没有为各客户端实例化DocumentSession；Web主要依赖前端StateStore，不能描述成后端提供会话化CommandHistory服务。

源码：`app/state.py:1`。

```python
"""Application state with explicit colour revisions."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image

from baker.cube_reader import CubeLut
from baker.params import ColorParams

from .image_io import SourceImage
from .video_io import VideoInfo

Mode = Literal["params", "external_lut"]


@dataclass
class AppState:
    document_id: str = ""
    revision: int = 0
    source: SourceImage | None = None
    preview_image: Image.Image | None = None
    params: ColorParams = field(default_factory=ColorParams.identity)
    strength: float = 1.0
    mode: Mode = "params"
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
    # Video mode: the graded source is one extracted frame of this clip.
    video: VideoInfo | None = None
    video_time: float = 0.0

    def new_document(self, source: SourceImage) -> None:
        self.document_id = f"doc-{uuid.uuid4().hex[:12]}"
        self.revision += 1
        self.source = source
        self.preview_image = None
        self.params = ColorParams.identity()
        self.saved_params = ColorParams.identity()
        self.strength = 1.0
        self.mode = "params"
        self.external_lut = None
        self.split_t = 1.0
        self.show_split = False
        self.hold_original = False
        self.zoom = 0.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.last_completed_revision = -1
        self.busy_revision = None
        self.source_label = "手动"
        self.last_error = ""
        self.dirty = False
        self.video = None
        self.video_time = 0.0

    def bump_color(self) -> int:
        self.revision += 1
        return self.revision

    def set_params(self, params: ColorParams, label: str = "手动") -> int:
        self.params = params
        self.source_label = label
        self.mode = "params"
        self.dirty = True
        return self.bump_color()

    def set_strength(self, strength: float) -> int:
        self.strength = max(0.0, min(1.0, float(strength)))
        self.dirty = True
        return self.bump_color()

    def import_external_lut(self, lut: CubeLut) -> int:
        self.saved_params = self.params
        self.external_lut = lut
        self.mode = "external_lut"
        self.source_label = "外部 LUT"
        self.dirty = True
        return self.bump_color()

    def return_to_params(self) -> int:
        self.mode = "params"
        self.external_lut = None
        self.source_label = "参数调色"
        self.dirty = True
        return self.bump_color()

    @property
    def has_image(self) -> bool:
        return self.source is not None

    @property
    def source_path(self) -> Path | None:
        return self.source.path if self.source else None
```

源码：`app/session.py:32`。

```python
@dataclass(frozen=True)
class ColorSnapshot:
    """Params + strength + mode fingerprint for undo/redo."""

    params: ColorParams
    strength: float
    mode: Mode
    source_label: str

    @classmethod
    def from_state(cls, state: AppState) -> ColorSnapshot:
        return cls(
            params=state.params,
            strength=float(state.strength),
            mode=state.mode,
            source_label=str(state.source_label),
        )

    def apply_to(self, state: AppState) -> None:
        state.params = self.params
        state.strength = self.strength
        state.mode = self.mode
        state.source_label = self.source_label
        state.dirty = True
```

源码：`app/session.py:58`。

```python
@dataclass
class DocumentSession:
    """Per-document business rules formerly embedded in ``ColorApp``."""

    state: AppState = field(default_factory=AppState)
    pending_proposal: Proposal | None = None
    export_tickets: list[ExportTicket] = field(default_factory=list)
    export_seq: int = 0
    batch_active: bool = False
    _color_history: list[ColorSnapshot] = field(default_factory=list)
    _color_history_index: int = 0

    # -- color history -------------------------------------------------
    def reset_color_history(self) -> None:
        self._color_history = [ColorSnapshot.from_state(self.state)]
        self._color_history_index = 0

    def clear_color_history(self) -> None:
        self._color_history = []
        self._color_history_index = 0

    def record_color_history(self) -> None:
        """Call before mutating params/strength/mode from user edits."""
        snap = ColorSnapshot.from_state(self.state)
        if not self._color_history:
            self._color_history = [snap]
            self._color_history_index = 0
            return
        if self._color_history[self._color_history_index] == snap:
            return
        if self._color_history_index < len(self._color_history) - 1:
            self._color_history = self._color_history[: self._color_history_index + 1]
        self._color_history.append(snap)
        self._color_history_index = len(self._color_history) - 1
        if len(self._color_history) > MAX_COLOR_HISTORY:
            overflow = len(self._color_history) - MAX_COLOR_HISTORY
            self._color_history = self._color_history[overflow:]
            self._color_history_index -= overflow

    def can_undo(self) -> bool:
        return self._color_history_index > 0

    def can_redo(self) -> bool:
        return self._color_history_index < len(self._color_history) - 1

    def undo(self) -> bool:
        if not self.can_undo():
            return False
        self._color_history_index -= 1
        self._color_history[self._color_history_index].apply_to(self.state)
        self.state.bump_color()
        return True

    def redo(self) -> bool:
        if not self.can_redo():
            return False
        self._color_history_index += 1
        self._color_history[self._color_history_index].apply_to(self.state)
        self.state.bump_color()
        return True

    # -- AI proposals --------------------------------------------------
    def set_pending_proposal(self, proposal: Proposal | None) -> None:
        self.pending_proposal = proposal

    def clear_pending_proposal(self) -> None:
        self.pending_proposal = None

    def apply_proposal_to_state(self, proposal: Proposal) -> int:
        self.pending_proposal = None
        self.record_color_history()
        if proposal.source == "ai":
            label = f"AI · {proposal.provider}/{proposal.model}"
        else:
            label = "离线模板"
        self.state.params = proposal.params
        self.state.mode = "params"
        self.state.external_lut = None
        self.state.source_label = label
        self.state.dirty = True
        rev = self.state.bump_color()
        self.record_color_history()
        return rev

    # -- export gate ---------------------------------------------------
    def export_started(self, kind: str, revision: int, material: str = "") -> int:
        self.export_seq += 1
        token = self.export_seq
        self.export_tickets.append(
            ExportTicket(kind, revision, material, token)
        )
        return token

    def export_take(self, token: int | None, kind: str) -> ExportTicket | None:
        if token is not None:
            for index, ticket in enumerate(self.export_tickets):
                if ticket.token == token:
                    return self.export_tickets.pop(index)
        for index, ticket in enumerate(self.export_tickets):
            if ticket.kind == kind:
                return self.export_tickets.pop(index)
        return None

    def export_drop_token(self, token: int) -> None:
        for index, ticket in enumerate(self.export_tickets):
            if ticket.token == token:
                del self.export_tickets[index]
                return

    def outstanding_exports(self, runner_queued: int = 0) -> int:
        return max(len(self.export_tickets), int(runner_queued))

    def export_block_reason(self, runner_queued: int = 0) -> str | None:
        outstanding = self.outstanding_exports(runner_queued)
        if outstanding <= 0:
            return None
        text = "当前素材仍有导出任务正在进行，暂时无法切换。请等待导出完成后再试。"
        if outstanding > 1:
            text = text[:-1] + f"（剩余 {outstanding} 项）。"
        return text

    def batch_blocks_single_asset_work(self) -> bool:
        return self.batch_active
```

MediaRecord包含media_id/kind/path/width/height/duration_s/fps。上传目录`runtime/cache/api_media/<uuid>/<safe basename>`；`index.json`格式`{version:1,records:[…]}`，同名`.tmp`→replace，锁内注册/写索引；模块import时load_index。恢复检查字段/正尺寸/文件存在，坏记录丢弃；version被写入但load_index未执行版本兼容验证，恢复路径也未额外限制到media根。索引写失败被吞掉，因此上传成功不保证持久化已提交。它不是工程参数/历史保存，job记录也不会恢复。

源码：`api/media_store.py:20`。

```python
@dataclass
class MediaRecord:
    media_id: str
    kind: MediaKind
    path: Path
    width: int
    height: int
    duration_s: float | None = None
    fps: float | None = None
```

源码：`api/media_store.py:87`。

```python
def _write_index() -> None:
    """Persist the registry so a backend restart does not orphan uploads.

    The index is a convenience cache layered on top of the files themselves: a
    failed write must never fail an upload that already succeeded on disk.
    """
    try:
        API_MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": INDEX_VERSION,
            "records": [_record_to_json(record) for record in _REGISTRY.values()],
        }
        tmp = INDEX_PATH.with_name(INDEX_PATH.name + ".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(INDEX_PATH)
    except (OSError, TypeError, ValueError):
        pass
```

源码：`api/media_store.py:108`。

```python
def load_index() -> int:
    """Restore records from disk; returns how many survived validation."""
    try:
        raw = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    records = raw.get("records") if isinstance(raw, dict) else None
    if not isinstance(records, list):
        return 0
    restored = 0
    with _LOCK:
        for item in records:
            record = _record_from_json(item)
            if record is not None:
                _REGISTRY[record.media_id] = record
                restored += 1
    return restored
```

### 5.5 视频解码、播放、最终重编码及批次

Web视频是浏览器HTMLVideoElement实时解码+requestAnimationFrame上载/渲染，支持边播边调、暂停/seek、动态A/B、loop静音；不是先离线生成每帧PNG。未采用requestVideoFrameCallback；通过currentTime比较避免同一帧重复上传。HUD的FPS由ffprobe返回素材fps格式化得到，不是实际渲染测速。主gl.frames计数是drawFrame次数，不能等同于不同解码帧数。

Tk视频仍是`probe → extract_frame → load_source_image → prepare_preview`的抽帧模型；220ms seek防抖、token拒过时结果；播放推进在取帧结果到达后安排下一次timer（min30ms），再经过一次性C++预览，因此不承诺素材FPS。两套前端的性能叙述必须分开。

ffprobe调用：`ffprobe -v error -print_format json -show_format -show_streams <path>`；读取首视频、音频存在、duration、avg_frame_rate/r_frame_rate、旋转信息。VideoInfo display_width/height按90°旋转互换。单帧`ffmpeg -v error -nostdin -y -ss <seconds> -i … -frames:v 1 -vf <scale/lanczos,matrix,format=rgb24> -pix_fmt rgb24 <png>`。long_side=8192；末尾回退max(1/max(fps,1),.05)，失败正时刻重试0秒。视频颜色矩阵未知按bt709；没有完整HDR转SDR或不同transfer特征管理。

API video导出在创建任务前先probe+抽0秒帧+SourceImage/preview/Snapshot；后台`pipeline.export_lut`把strength合入cube，然后ffmpeg整片`lut3d`滤镜，不是把每帧送C++。滤镜图：

```text
scale=in_color_matrix=<matrix>:out_color_matrix=bt709,
format=rgb24,lut3d='<escaped cube path>',format=yuv420p
```

命令核心：`-map 0:v:0 -map 0:a:0? -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p -colorspace bt709 -color_primaries bt709 -color_trc bt709 -c:a aac -b:a 192k -movflags +faststart -progress pipe:1 -nostats <stem.partial.ext>`。不显式指定lut3d interp，不应宣称视频导出已固定为与Web硬件三线性相同。编码成功os.replace提交，失败/取消删partial；progress读取out_time_ms/us并除1e6再除duration。cancel在stdout迭代中检查，wait(timeout=60)发生在stdout结束之后，不是完整进程的绝对超时保证；未处理阻塞stdout期间即时取消与stderr写满的所有情形。

`app.jobs.LatestJobRunner`单线程消费，预览coalesce/latest-wins取消旧任务、导出FIFO优先且不丢；`api.job_runner`则另一路每job线程，不能混为同一个调度器。桌面`BatchRunner`单消费者FIFO，BatchTaskSnapshot frozen，item状态pending/preparing/running/done/failed/cancelled/skipped，支持统一基线与逐项override、跳过/改名/显式覆盖策略、取消单项/待处理/全部及重试失败项。`Strategy.REFERENCE`源码明确是阶段C占位，没有参考素材色彩协调算法；Web也没有批量端点/UI。历史用户愿望不等于当前实现。

源码：`app/video_io.py:53`。

```python
@dataclass(frozen=True)
class VideoInfo:
    path: Path
    duration_s: float
    fps: float
    width: int
    height: int
    codec: str
    color_space: str
    has_audio: bool
    rotation: int = 0

    @property
    def display_width(self) -> int:
        return self.height if self.rotation % 180 == 90 else self.width

    @property
    def display_height(self) -> int:
        return self.width if self.rotation % 180 == 90 else self.height

    def timecode(self, seconds: float) -> str:
        seconds = max(0.0, float(seconds))
        minutes, rest = divmod(seconds, 60.0)
        return f"{int(minutes):02d}:{rest:05.2f}"
```

源码：`app/video_io.py:290`。

```python
def export_graded(
    path: str | Path,
    cube_path: str | Path,
    target: str | Path,
    *,
    info: VideoInfo | None = None,
    quality: int = 18,
    preset: str = "medium",
    on_progress: Callable[[float], None] | None = None,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Re-encode the whole clip through the exported 3D LUT.

    Progress is reported as 0..1 from ffmpeg's ``-progress`` stream; cancelling
    kills the encoder and leaves no partial file behind.
    """
    ffmpeg = ffmpeg_bin()
    if not ffmpeg:
        raise VideoError("VIDEO_UNAVAILABLE", availability()[1])
    source = Path(path)
    target_path = Path(target)
    meta = info or probe(source)
    if target_path.suffix.lower() not in (".mp4", ".mov", ".mkv", ".webm"):
        target_path = target_path.with_suffix(".mp4")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    # The suffix must stay last: ffmpeg picks the muxer from the extension.
    partial = target_path.with_name(
        f"{target_path.stem}.partial{target_path.suffix}"
    )
    partial.unlink(missing_ok=True)

    matrix = "bt709" if meta.color_space in ("bt709", "unknown", "") else meta.color_space
    filters = (
        f"scale=in_color_matrix={matrix}:out_color_matrix=bt709,"
        f"format=rgb24,lut3d='{_filter_path(Path(cube_path))}',"
        "format=yuv420p"
    )
    cmd = [
        ffmpeg,
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        filters,
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(int(quality)),
        "-pix_fmt",
        "yuv420p",
        "-colorspace",
        "bt709",
        "-color_primaries",
        "bt709",
        "-color_trc",
        "bt709",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(partial),
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except OSError as exc:
        raise VideoError("VIDEO_UNAVAILABLE", f"无法启动 ffmpeg：{exc}") from exc

    cancelled = False
    assert proc.stdout is not None
    time_re = re.compile(r"out_time_(?:ms|us)=(\d+)")
    timed_out = False
    stderr = ""
    try:
        for line in proc.stdout:
            if cancel_event is not None and cancel_event.is_set():
                cancelled = True
                proc.kill()
                break
            match = time_re.search(line)
            if match and on_progress is not None and meta.duration_s > 0:
                done = int(match.group(1))
                # ffmpeg emits out_time_ms but the value is microseconds.
                seconds = done / 1_000_000.0
                on_progress(max(0.0, min(1.0, seconds / meta.duration_s)))
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
    finally:
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:  # pragma: no cover - stuck child
                LOGGER.warning("ffmpeg did not exit after kill")
        # Drain and close both pipes; leaving them to GC leaks file handles and
        # trips ResourceWarning in the test suite.
        if proc.stderr is not None:
            try:
                stderr = proc.stderr.read() or ""
            except (OSError, ValueError):
                stderr = ""
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        proc.stdout = None
        proc.stderr = None

    if timed_out:
        partial.unlink(missing_ok=True)
        raise VideoError("VIDEO_TIMEOUT", "ffmpeg 未在预期时间内退出")

    if cancelled:
        partial.unlink(missing_ok=True)
        raise VideoError("CANCELLED", "视频导出已取消")

    if proc.returncode != 0 or not partial.is_file():
        partial.unlink(missing_ok=True)
        detail = stderr.strip().splitlines()
        raise VideoError(
            "VIDEO_ENCODE_FAILED",
            "视频编码失败：" + (detail[-1] if detail else f"exit={proc.returncode}"),
        )

    os.replace(partial, target_path)
    if on_progress is not None:
        on_progress(1.0)
    return target_path
```

### 5.6 Python后端/桌面预览保留链路

参数→AppState.bump_color→60ms `_schedule_preview`→RenderSnapshot→`LatestJobRunner.submit(coalesce_key="preview")`→`RenderPipeline.render_preview`→33³ cache LUT→`EngineClient.render`→主线程40ms poll→`_handle_preview`验证document/revision→替换_processed_preview/清直方图cache→redraw。original与processed是两份Pillow Image；A/B在Tk CPU合成，和Web最后一Pass分支不同。直方图由rendered preview统计且缓存，不参与烘焙数学。参数等价cache key含algorithm/canonical params/N/domain/strength，磁盘cache默认320MiB且仅淘汰老于600s文件。

源码：`app/pipeline.py:33`。

```python
@dataclass(frozen=True)
class RenderSnapshot:
    document_id: str
    revision: int
    source: SourceImage
    preview: Image.Image
    params: ColorParams
    strength: float
    mode: str
    external_lut: CubeLut | None

    @classmethod
    def from_state(cls, state: AppState) -> "RenderSnapshot":
        if state.source is None or state.preview_image is None:
            raise ValueError("没有已载入的图像")
        return cls(
            document_id=state.document_id,
            revision=state.revision,
            source=state.source,
            preview=state.preview_image,
            params=state.params,
            strength=state.strength,
            mode=state.mode,
            external_lut=state.external_lut,
        )
```

## 6. 自动化测试、五维Benchmark与阶段七验收证据

### 6.1 本次实际验证（2026-11-21）

为满足原仓库只读，复制项目到系统临时目录，排除原缓存/依赖环境并复制当前测试夹具、现有worker及其运行DLL/着色器和前端依赖。使用原`.venv/Scripts/python.exe -B`，不重新构建C++或安装依赖。实际测试/构建工作目录为临时副本；以下给出便于在原项目复现的等价命令，直接在原项目运行会产生runtime/dist等文件，**本次没有这样写回原仓库**。

```powershell
cd .
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
cd frontend
npm run build
```

| 检查 | 本次实际结果 |
| --- | --- |
| Python | Ran **214 tests in 36.740s**；**OK**，未报告skipped |
| TypeScript | `tsc -b`通过 |
| Vite | **v6.4.6**，21 modules transformed，生产打包通过，Vite阶段438ms |
| HTML | dist/index.html 0.43 kB，gzip 0.32 kB |
| CSS | dist/assets/index-CkhRb_qn.css 18.66 kB，gzip 4.17 kB |
| JS | dist/assets/index-4sG3phGs.js 68.92 kB，gzip 21.17 kB，sourcemap 203.90 kB |

214替代旧版本204项口径。stdout/stderr中的boom、视频失败、无效图像、导出门控与job poll failed是注入错误用例的预期日志，最终测试结果OK；还出现Starlette关于httpx TestClient的DeprecationWarning，它不等于失败。构建通过仅证明TS和bundle可生成，不证明WebGL浏览器行为全部通过。没有重新运行阶段七Playwright，不能将2026-11-20矩阵换成2026-11-21实测。

### 6.2 全部测试文件、覆盖域与用例名

**`tests/test_ai.py`** — 在线HTTP鉴权/限流/网络/Schema/修复/取消、配置与离线风格/相对规则/结构化chip。

| 测试类 | 方法数 | 真实test_*方法 |
| --- | --- | --- |
| DeepSeekTests | 11 | `test_t09_valid_output`（L78）<br>`test_t09_repair_after_one_bad_schema`（L102）<br>`test_t09_two_invalid_outputs_fail_without_touching_params`（L120）<br>`test_t09_duplicate_keys_and_empty_content`（L134）<br>`test_t09_auth_error_is_not_retried`（L150）<br>`test_t09_rate_limit_and_server_errors_retry_then_fail`（L158）<br>`test_t09_server_error_then_success`（L170）<br>`test_t09_timeout_is_retried`（L184）<br>`test_t09_oversized_response_rejected`（L197）<br>`test_t09_cancel_and_deadline`（L204）<br>`test_t09_empty_intent_rejected`（L220） |
| ConfigAndOfflineTests | 7 | `test_offline_provider_is_selected_without_key`（L229）<br>`test_offline_structured_chip_not_warm_template`（L234）<br>`test_offline_presets`（L250）<br>`test_load_config_rejects_insecure_base_url`（L274）<br>`test_load_config_env_overrides_and_offline_flag`（L287）<br>`test_retired_model_is_flagged`（L310）<br>`test_prompt_targets_v2_schema_and_carries_current_params`（L318） |

**`tests/test_api.py`** — REST基础信封、参数与LUT、上传媒体、导出任务/下载、索引恢复等。

| 测试类 | 方法数 | 真实test_*方法 |
| --- | --- | --- |
| ApiTests | 7 | `test_presets`（L34）<br>`test_params_validate`（L45）<br>`test_lut_bake_binary_layout`（L52）<br>`test_ai_offline_fallback`（L66）<br>`test_media_upload_and_histogram`（L86）<br>`test_lut_upload_cube`（L104）<br>`test_export_image_job_submit`（L118） |

**`tests/test_batch.py`** — 模型状态机、重复源/源变化、规划冲突与参数缺失、队列FIFO、取消/幂等/重试。

| 测试类 | 方法数 | 真实test_*方法 |
| --- | --- | --- |
| BatchModelTests | 9 | `test_uniform_baseline_is_used_when_item_has_no_override`（L156）<br>`test_override_wins_without_touching_other_items`（L162）<br>`test_updating_the_baseline_leaves_covered_items_alone`（L175）<br>`test_applying_the_baseline_to_all_items_is_explicit`（L185）<br>`test_duplicate_source_is_rejected`（L196）<br>`test_remove_only_removes_items_that_have_not_started`（L202）<br>`test_retry_resets_failed_items_only`（L212）<br>`test_progress_never_moves_backwards`（L225）<br>`test_a_finished_item_is_never_reported_as_cancelled`（L241） |
| BatchPlanTests | 14 | `test_target_keeps_the_stem_and_uses_the_kind_suffix`（L256）<br>`test_video_items_use_the_video_suffix`（L263）<br>`test_existing_target_is_skipped_by_default`（L270）<br>`test_rename_policy_picks_the_next_free_name`（L284）<br>`test_rename_avoids_collisions_inside_the_batch`（L292）<br>`test_overwrite_happens_only_when_selected`（L307）<br>`test_target_may_never_be_the_source`（L317）<br>`test_missing_source_is_reported_with_a_stable_code`（L325）<br>`test_missing_parameters_are_reported`（L333）<br>`test_source_change_after_import_is_reported`（L340）<br>`test_an_unchanged_source_still_plans`（L359）<br>`test_planning_aborts_when_the_output_directory_is_gone`（L365）<br>`test_snapshot_is_frozen_against_later_edits`（L372）<br>`test_only_pending_items_are_planned`（L384） |
| BatchRunnerTests | 12 | `test_items_run_in_submit_order`（L410）<br>`test_only_one_item_runs_at_a_time`（L424）<br>`test_a_failure_does_not_stop_the_queue`（L431）<br>`test_cancelling_a_queued_item_is_idempotent`（L447）<br>`test_cancelling_the_current_item_stops_it_cooperatively`（L467）<br>`test_cancel_pending_keeps_the_running_item`（L482）<br>`test_cancel_all_reports_the_current_item_too`（L501）<br>`test_cancelling_after_completion_is_a_no_op`（L518）<br>`test_a_worker_that_ignores_cancel_is_not_reported_as_done`（L534）<br>`test_progress_updates_are_forwarded_and_deduplicated`（L550）<br>`test_shutdown_cancels_running_and_pending`（L562）<br>`test_duplicate_submissions_are_ignored`（L575） |

**`tests/test_batch_export.py`** — 图片/视频worker适配、external LUT、质量/强度透传、临时cube清理、取消映射。

| 测试类 | 方法数 | 真实test_*方法 |
| --- | --- | --- |
| BatchExportWorkerTests | 7 | `test_image_item_exports_with_the_snapshot_settings`（L97）<br>`test_jpeg_suffix_selects_jpeg`（L122）<br>`test_external_lut_switches_the_render_mode`（L131）<br>`test_cancel_before_start_never_touches_the_pipeline`（L148）<br>`test_decode_failure_propagates_with_its_code`（L157）<br>`test_video_item_bakes_a_cube_and_removes_it`（L168）<br>`test_video_failure_still_removes_the_cube`（L198） |
| RunnerCancellationMappingTests | 2 | `test_engine_cancelled_error_is_reported_as_cancelled`（L229）<br>`test_other_engine_errors_are_failures`（L239） |

**`tests/test_color.py`** — identity/曝光/白平衡/对比方向、各维数学和CPU参考。

| 测试类 | 方法数 | 真实test_*方法 |
| --- | --- | --- |
| ColorTransformTests | 19 | `test_identity_lut_is_exact_grid`（L12）<br>`test_identity_is_exact_on_random_colours`（L21）<br>`test_exposure_direction`（L27）<br>`test_temperature_direction`（L34）<br>`test_tint_direction_is_magenta`（L41）<br>`test_contrast_keeps_endpoints`（L47）<br>`test_contrast_direction`（L52）<br>`test_shadows_and_highlights_direction`（L58）<br>`test_saturation_minus_100_is_gray`（L70）<br>`test_bake_is_byte_repeatable`（L76）<br>`test_strength_mix_is_linear`（L82）<br>`test_lut_approximation_33`（L92）<br>`test_lut_approximation_33_with_split_toning`（L103）<br>`test_whites_and_blacks_only_move_the_extremes`（L113）<br>`test_vibrance_protects_saturated_colours`（L124）<br>`test_shadows_highlight_tint_hues`（L134）<br>`test_hue_rotation_moves_red_towards_green`（L146）<br>`test_hue_rotation_preserves_gray`（L151）<br>`test_strength_zero_is_identity_on_gpu_formula`（L156） |

**`tests/test_cube.py`** — cube子集合法/异常、BOM/注释、domain、写回/strength/等价误差。

| 测试类 | 方法数 | 真实test_*方法 |
| --- | --- | --- |
| CubeReaderTests | 11 | `test_valid_and_title_with_hash`（L35）<br>`test_bom_and_crlf`（L42）<br>`test_missing_size`（L47）<br>`test_duplicate_size`（L53）<br>`test_header_after_data`（L58）<br>`test_extra_and_short_rows`（L63）<br>`test_extra_token`（L71）<br>`test_nan_inf_and_range`（L76）<br>`test_1d_and_unknown`（L83）<br>`test_invalid_domain`（L91）<br>`test_negative_and_above_one_samples_allowed`（L96） |
| CubeWriterTests | 3 | `test_roundtrip_is_exact`（L103）<br>`test_rejects_nonfinite`（L114）<br>`test_rejects_wrong_shape`（L121） |

**`tests/test_engine.py`** — 真实worker identity/非对称通道/alpha/domain/强度/尺寸与协议故障。

| 测试类 | 方法数 | 真实test_*方法 |
| --- | --- | --- |
| SamplingTests | 4 | `test_t01_identity_lut_sizes`（L90）<br>`test_t02_known_mappings`（L124）<br>`test_t03_domain_and_out_of_range`（L155）<br>`test_t03_strength_mixes_identity`（L195） |
| ProtocolErrorTests | 9 | `test_t04_lut_errors_are_typed`（L207）<br>`test_t04_strength_out_of_range_rejected`（L234）<br>`test_t05_bad_rgba_bridge_rejected_before_gl`（L244）<br>`test_t14_missing_worker_is_reported`（L272）<br>`test_t14_cancel_before_start`（L284）<br>`test_successful_render_cleans_its_job_directory`（L304）<br>`test_keep_job_dir_flag_leaves_diagnostics_on_disk`（L315）<br>`test_cancelled_render_leaves_no_job_directory`（L338）<br>`test_t14_foreign_binary_as_worker_is_reported`（L363） |

**`tests/test_histogram.py`** — 256-bin统计、透明像素/裁切、绘图与缩放。

| 测试类 | 方法数 | 真实test_*方法 |
| --- | --- | --- |
| HistogramTests | 6 | `test_gradient_spreads_across_all_bins`（L20）<br>`test_channel_separation`（L29）<br>`test_clipping_fractions`（L37）<br>`test_render_size_and_content`（L44）<br>`test_transparent_pixels_composite_on_white`（L55）<br>`test_render_empty_histogram`（L62） |

**`tests/test_image_io.py`** — 容器/位深/EXIF/ICC/安全尺寸、alpha预览和PNG/JPEG原子导出。

| 测试类 | 方法数 | 真实test_*方法 |
| --- | --- | --- |
| ImageLoadTests | 19 | `test_exif_orientations_1_to_8`（L58）<br>`test_orientation_6_moves_top_left_to_top_right`（L68）<br>`test_orientation_3_rotates_180`（L78）<br>`test_grayscale_and_palette`（L86）<br>`test_16bit_rejected`（L101）<br>`test_cmyk_rejected`（L110）<br>`test_mpo_phone_photo_uses_main_image`（L116）<br>`test_additional_still_containers_load`（L131）<br>`test_multiframe_gif_uses_first_frame_with_note`（L147）<br>`test_heif_without_plugin_explains_the_fix`（L155）<br>`test_unknown_container_names_supported_formats`（L165）<br>`test_animated_rejected`（L173）<br>`test_srgb_icc_accepted`（L180）<br>`test_invalid_icc_rejected`（L188）<br>`test_gamma_plus_icc_conflict_rejected`（L196）<br>`test_oversize_side_rejected`（L212）<br>`test_oversize_rejected_before_pixels_are_decoded`（L218）<br>`test_truncated_header_only_file_reports_decode_error`（L234）<br>`test_pixel_limit_boundary_is_inclusive`（L243） |
| ImageExportTests | 8 | `test_png_roundtrip_preserves_alpha_and_icc`（L266）<br>`test_jpeg_flattens_alpha_on_white`（L283）<br>`test_bridge_roundtrip`（L295）<br>`test_bridge_rejects_bad_header`（L303）<br>`test_preview_is_long_side_limited`（L309）<br>`test_preview_keeps_alpha_transparent_pixels`（L315）<br>`test_opaque_preview_matches_the_general_path`（L321）<br>`test_write_failures_leave_no_partial_or_temp_file`（L341） |

**`tests/test_matrix.py`** — pipeline端到端、队列、状态/导出归属/门控、过时AI与poll错误隔离。

| 测试类 | 方法数 | 真实test_*方法 |
| --- | --- | --- |
| PipelineTests | 6 | `test_t12_preview_png_and_jpeg_export`（L72）<br>`test_t12_lut_export_and_verification`（L115）<br>`test_t12_external_lut_mode`（L146）<br>`test_t13_unicode_path_and_source_protection`（L181）<br>`test_t13_failed_target_keeps_no_partial_file`（L197）<br>`test_t07_lut_cache_key_is_stable`（L210） |
| JobRunnerTests | 5 | `test_t10_latest_job_wins`（L225）<br>`test_t10_export_is_not_dropped_by_a_preview`（L259）<br>`test_queued_exports_keep_fifo_order`（L299）<br>`test_shutdown_cancels_queued_exports`（L335）<br>`test_t10_shutdown_cancels_work`（L354） |
| BusyStatusTests | 9 | `test_export_status_survives_a_finished_preview`（L422）<br>`test_queued_exports_are_counted_while_one_runs`（L440）<br>`test_two_exports_waiting_report_the_total`（L456）<br>`test_ai_and_export_share_the_line`（L464）<br>`test_finishing_an_unknown_export_keeps_the_other_ticket`（L475）<br>`test_tokens_keep_same_kind_same_revision_apart`（L484）<br>`test_notice_names_the_material_it_belongs_to`（L496）<br>`test_failed_export_is_attributed_and_releases_the_gate`（L522）<br>`test_export_notice_is_not_overwritten_by_a_preview`（L543） |
| PollIsolationTests | 2 | `test_one_failing_handler_does_not_drop_the_next_outcome`（L596）<br>`test_failed_export_handler_still_releases_its_ticket`（L615） |
| MaterialSwitchGateTests | 5 | `test_switch_is_refused_while_an_export_is_pending`（L680）<br>`test_block_message_counts_the_remaining_exports`（L697）<br>`test_switch_proceeds_once_the_ticket_is_released`（L704）<br>`test_previews_alone_never_block_a_switch`（L719）<br>`test_initial_load_is_allowed_even_with_a_queued_fifo`（L727） |
| AiGenerationTests | 2 | `test_stale_ai_outcome_is_ignored`（L775）<br>`test_current_ai_cancellation_is_reported`（L785） |
| StateTests | 2 | `test_t11_split_composite_boundaries`（L797）<br>`test_new_document_resets_edits`（L827） |

**`tests/test_params.py`** — v1/v2/重复键/非有限/布尔/范围、normalize/cache key和预设。

| 测试类 | 方法数 | 真实test_*方法 |
| --- | --- | --- |
| ParamsTests | 15 | `test_identity_document_is_valid`（L13）<br>`test_extra_field_rejected`（L17）<br>`test_missing_field_rejected`（L23）<br>`test_wrong_version_rejected`（L29）<br>`test_legacy_v1_document_is_upgraded_with_zero_defaults`（L35）<br>`test_hue_out_of_range_rejected`（L56）<br>`test_split_amounts_must_be_non_negative`（L62）<br>`test_bool_is_not_a_number`（L68）<br>`test_nan_rejected_by_parser`（L74）<br>`test_duplicate_key_rejected`（L81）<br>`test_out_of_range_rejected`（L90）<br>`test_normalization_rounds_and_removes_negative_zero`（L96）<br>`test_canonical_json_is_stable`（L104）<br>`test_cache_key_includes_strength_and_size`（L112）<br>`test_presets_are_valid`（L119） |

**`tests/test_paths.py`** — cache老化/LRU淘汰，近期使用文件保护。

| 测试类 | 方法数 | 真实test_*方法 |
| --- | --- | --- |
| CachePruneTests | 6 | `test_usage_counts_nested_files`（L32）<br>`test_prune_is_a_noop_under_the_limit`（L39）<br>`test_prune_evicts_oldest_first_until_under_the_cap`（L45）<br>`test_prune_never_touches_recent_files`（L56）<br>`test_prune_keeps_evicting_when_recent_files_alone_exceed_the_cap`（L68）<br>`test_missing_cache_directory_is_tolerated`（L76） |

**`tests/test_session.py`** — 无Tk会话业务、64历史、AI提案与导出ticket。

| 测试类 | 方法数 | 真实test_*方法 |
| --- | --- | --- |
| SessionTests | 2 | `test_undo_redo_params`（L12）<br>`test_export_gate`（L29） |

**`tests/test_video.py`** — ffprobe/ffmpeg抽帧/视频重编码、音频/取消/不可用工具。

| 测试类 | 方法数 | 真实test_*方法 |
| --- | --- | --- |
| VideoPipelineTests | 11 | `test_probe_reports_stream_metadata`（L76）<br>`test_probe_rejects_non_video`（L84）<br>`test_extract_frame_is_a_loadable_still`（L93）<br>`test_extract_frame_clamps_beyond_duration`（L101）<br>`test_timecode_format`（L105）<br>`test_export_applies_the_lut`（L110）<br>`test_export_reports_monotonic_progress`（L127）<br>`test_export_without_audio_keeps_the_video`（L138）<br>`test_cancel_leaves_no_partial_output`（L146）<br>`test_bad_input_reports_invalid`（L160）<br>`test_quick_fingerprint_changes_with_content`（L167） |
| VideoAvailabilityTests | 1 | `test_missing_ffmpeg_is_explained`（L176） |

静态AST合计 `214` 个test_*方法；与本次运行214项相互核对。`tests/helpers.py`负责生成夹具；`tests/__init__.py`为包标识。Python测试并不执行TS内嵌shader的像素级浏览器断言；Playwright工具另行运行。

### 6.3 实验来源、环境与报告交叉核对

| 证据文件 | 字节 | SHA256 |
| --- | --- | --- |
| runtime/benchmark_results/benchmark_report.md | 19556 | c1d476692c9d90dd35a9e4644e31c8fa5f96f32cbf68546ee74d25c19574eb32 |
| runtime/benchmark_results/benchmark_raw.json | 234112 | 3453b3f0f688ac2a97c45008e219140c9657f1671422a6e2e8e3588061ad7494 |
| runtime/benchmark_results/benchmark_raw_partial.json | 39028 | 05566d0a1e27395fbc867bc2fe195d4db552484e2a7e6d3348f74419fa06366b |
| runtime/benchmark_results/stage7_acceptance_matrix.json | 2039 | 271d2207898697640321e86128c60554cc4e2493c75af5469c73fd8957452830 |
| runtime/benchmark_results/stage6_acceptance.json | 700 | e5107ad78dfd285100befa07e617e0c83aa79db99fd75f91f791fed541a86262 |
| docs/STAGE7_ACCEPTANCE_REPORT.md | 2720 | 0f815c0ca1063761b4a49a9a9992c30ea3bab9e094a7c0e4cf569cb515f1d16d |
| docs/STAGE6_DEEP_AUDIT_REPORT.md | 5266 | f9c3cf7637ff680fe9a1f86bab49f158ca3b1aeaf656de3532d6e34006e5319a |
| tools/benchmark/offline_baseline.json | 5689 | 8115c4473c11152ef9e0fa6a2627abc36bc786e9f76519c658ed3ca116380a14 |

完整raw包含dim1..dim5；partial仅dim5，记录时间为2026-11-18 13:35:15，早于完整raw的2026-11-18 13:35:45。本归档使用完整raw，没有用partial覆盖其他维度。已在临时目录用当前`tools/benchmark/report.build`重新生成报告，**所有Markdown表块与既存benchmark_report.md完全一致**；另外核对dim1加速比、dim2顶点/字节/base64体积、dim5 24条准确率计数。该校验只验证数据自洽，不是重新测量性能。

```json
{
  "platform": "Windows-11-10.0.26200-SP0",
  "machine": "ARM64",
  "processor": "ARMv8 (64-bit) Family 8 Model D4B Revision   0, Qualcomm Technologies Inc",
  "cpu_model": "Snapdragon (TM) 8cx Gen 3 @ 3.0 GHz",
  "gpu_model": "Virtual Display Device",
  "python": "3.13.12",
  "numpy": "2.5.4",
  "matplotlib": "3.11.2",
  "pillow": "13.0.0",
  "algorithm_version": "sdr-srgb-v2",
  "worker_path": "build-arm64\\Debug\\render_worker.exe",
  "worker_bytes": 1235456,
  "worker_mtime": "2026-10-20 13:09:38",
  "results_dir": "runtime\\benchmark_results",
  "generated_at": "2026-11-18 13:35:45",
  "gl_context": "OpenGL 3.3 Core (offscreen FBO, Mesa software rasteriser)"
}
```

**环境解释：** raw的gl_context为`common.environment_info`写死的描述字符串，不是glGetString实时采样；gpu_model记录Virtual Display Device，不能据此写成已验证独立物理GPU加速。源码确实创建OpenGL渲染，但论文应称“OpenGL路径对CPU解析式参考的加速”，并注明原始环境记录为Mesa软件光栅路径。worker原始大小/时间戳见meta，现有测试使用现存binary，未重编译；源码与二进制逐项等价未由此次任务证明。

### 6.4 维度一：CPU vs OpenGL速度（原始保存精度）

cinematic参数、33³ LUT，1080p/2560×1440/4K；CPU计时包含float64完整16参数transform_rgb，输入转换在计时外；GL总时间是EngineClient.render，不含在计时外准备的cube/输入桥。每项预热1次后正式5次。gpu_shader_ms实际取收集值中位数，且readbacks列表包含预热调用，而cpu/gpu_total为5次均值；**不能称之为同样5次的shader均值**。这里“GPU”沿用原始字段名，不证明独显硬件。

| 分辨率 | CPU mean ms | CPU P95 ms | GL总 mean ms | GL总 P95 ms | render_readback中位ms | overhead ms | 总加速× | render阶段比× |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1080p (1920x1080) | 2797.2771 | 2804.4411 | 1383.4055 | 1510.8967 | 22.0395 | 1361.366 | 2.022 | 126.921 |
| 2K (2560x1440) | 4643.8304 | 4938.4466 | 1326.8792 | 1406.2539 | 34.651 | 1292.2282 | 3.5 | 134.017 |
| 4K (3840x2160) | 11112.1361 | 11198.0768 | 1393.1665 | 1420.3942 | 45.761 | 1347.4055 | 7.976 | 242.83 |

原始正式时间样本（ms），保留JSON中的精度：

| 分辨率 | CPU samples_ms | GL total samples_ms |
| --- | --- | --- |
| 1080p | [2777.2943, 2804.4978, 2798.2887, 2802.0904, 2804.2142] | [1532.6632, 1390.6352, 1278.0008, 1291.8974, 1423.8307] |
| 2k | [4944.2788, 4915.1176, 4394.282, 4391.9794, 4573.4942] | [1285.7109, 1426.1582, 1298.0811, 1326.6366, 1297.8092] |
| 4k | [11196.2377, 11153.612, 11165.7769, 10846.5174, 11198.5366] | [1366.931, 1399.2408, 1373.1281, 1401.3862, 1425.1462] |

1080p固定开销约98.4%，后端一次性worker并不适合视频逐帧实时调用；Web实时方案通过常驻浏览器context与媒体纹理避免该跨进程链路。render_readback含upload/draw/readback/清理，不能在论文图注标成“纯GPU kernel时间”；也不能把上述C++基准换算成开启Bloom的Web FPS。

### 6.5 维度二：LUT尺寸精度、烘焙与传输

cinematic，64³均匀RGB格点262,144样本排成512×512卡；真值float64 transform_rgb，LUT用CPU硬件等效三线性参考采样；双方先量化8-bit，再算PSNR/MAE/Lab色差。bake_ms为3次中最快一次，非平均。payload_bytes是float32原始字节，payload_kb是base64字符数/1024，实际单位KiB，报告显示KB。

| N | 顶点 | PSNR dB | MAE /255 | max字节误差 | ΔE76 mean | ΔE76 max | ΔE00 mean | ΔE00 P95 | ΔE00 max | bake ms | 原始bytes | base64 KiB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 17 | 4913 | 53.572 | 0.2 | 4 | 0.2595 | 2.6373 | 0.1269 | 0.5098 | 2.1493 | 5.08 | 58956 | 76.8 |
| 33 | 35937 | 60.069 | 0.0545 | 2 | 0.077 | 1.9497 | 0.0376 | 0.2971 | 1.5794 | 37.0 | 431244 | 561.5 |
| 65 | 274625 | 67.706 | 0.011 | 1 | 0.017 | 1.4492 | 0.0089 | 0.0 | 1.0816 | 341.34 | 3295500 | 4291.0 |

65³ P95=0来自8-bit量化，不表示解析式在连续域零误差；0.0089均值与1.0816最大值必须一起看。33³的60.069dB/0.0376平均ΔE00仅针对当前预设/探针，不应直接断言任意极值参数、Web RGB16F、视频色彩转换或Bloom输出视觉无损。

### 6.6 维度三：三线性 vs 四面体精度

cinematic和tetra_stress各测17³/33³；灰轴256级，全色域64³。正式C++/Web shader仍用硬件三线性，四面体仅Benchmark NumPy实现，不是产品已切换的算法。其六分支按fractional RGB排序，每单纯形4顶点；三线性8顶点。

| 预设 | N | 插值 | 灰C*mean | 灰C*max | 灰C*误差mean | 灰C*误差max | 灰ΔE00 mean | 灰ΔE00 max | 扫卡PSNR | 扫卡MAE | 扫卡ΔE00 mean | 扫卡ΔE00 max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cinematic | 17 | trilinear | 3.8267 | 6.4096 | 0.0918 | 0.6661 | 0.1785 | 1.0089 | 53.572 | 0.2 | 0.1269 | 2.1493 |
| cinematic | 17 | tetrahedral | 3.8251 | 6.4096 | 0.0996 | 0.6661 | 0.1897 | 1.0089 | 53.675 | 0.1975 | 0.1272 | 2.1493 |
| cinematic | 33 | trilinear | 3.8491 | 6.4096 | 0.0304 | 0.7135 | 0.0532 | 0.9149 | 60.069 | 0.0545 | 0.0376 | 1.5794 |
| cinematic | 33 | tetrahedral | 3.8508 | 6.4096 | 0.033 | 0.7135 | 0.0573 | 0.9149 | 60.135 | 0.0539 | 0.0376 | 1.5794 |
| tetra_stress | 17 | trilinear | 10.6816 | 30.8358 | 0.6168 | 9.1186 | 0.9022 | 10.849 | 37.528 | 1.3007 | 0.6392 | 17.6707 |
| tetra_stress | 17 | tetrahedral | 10.7656 | 30.9357 | 0.6723 | 9.3704 | 0.9345 | 10.7976 | 37.625 | 1.255 | 0.6299 | 17.3761 |
| tetra_stress | 33 | trilinear | 10.3037 | 30.5106 | 0.3011 | 11.1828 | 0.4686 | 10.8356 | 45.066 | 0.4571 | 0.2397 | 10.0495 |
| tetra_stress | 33 | tetrahedral | 10.3288 | 30.5106 | 0.3006 | 10.6931 | 0.458 | 10.6551 | 45.135 | 0.4448 | 0.2367 | 9.2332 |

| 预设 | N | 灰C*下降% | 灰ΔE00下降% | 扫卡PSNR增益dB | 扫卡ΔE00下降% |
| --- | --- | --- | --- | --- | --- |
| cinematic | 17 | 0.04 | -6.27 | 0.103 | -0.24 |
| cinematic | 33 | -0.04 | -7.71 | 0.066 | 0.0 |
| tetra_stress | 17 | -0.79 | -3.58 | 0.097 | 1.45 |
| tetra_stress | 33 | -0.24 | 2.26 | 0.069 | 1.25 |

灰轴输出C*本身含预设分离染色，不等于插值引入的色偏；应使用相对于float64真值的ΔE00或chroma_err。收益有正有负，不能删掉负值后宣称四面体全面优于三线性。

压力参数原样：

```json
{
  "contrast": 100.0,
  "saturation": 55.0,
  "temperature": 45.0,
  "vibrance": 25.0,
  "highlights": -35.0,
  "shadows": 20.0,
  "split_shadow_hue": 195.0,
  "split_shadow_amount": 40.0,
  "split_highlight_hue": 40.0,
  "split_highlight_amount": 40.0
}
```

源码：`tools/benchmark/interpolation.py:35`。

```python
def tetrahedral_sample(
    lut: np.ndarray,
    n: int,
    rgb: np.ndarray,
    domain_min: Domain = (0.0, 0.0, 0.0),
    domain_max: Domain = (1.0, 1.0, 1.0),
) -> np.ndarray:
    """Sample an N^3 LUT with tetrahedral (6-simplex) interpolation."""
    lut3 = np.asarray(lut, dtype=np.float64).reshape(n, n, n, 3)
    i0, i1, f = _grid_position(rgb, n, domain_min, domain_max)

    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    r1, g1, b1 = i1[..., 0], i1[..., 1], i1[..., 2]

    c000 = lut3[b0, g0, r0]
    c100 = lut3[b0, g0, r1]
    c010 = lut3[b0, g1, r0]
    c110 = lut3[b0, g1, r1]
    c001 = lut3[b1, g0, r0]
    c101 = lut3[b1, g0, r1]
    c011 = lut3[b1, g1, r0]
    c111 = lut3[b1, g1, r1]

    fr, fg, fb = f[..., 0:1], f[..., 1:2], f[..., 2:3]
    sr, sg, sb = f[..., 0], f[..., 1], f[..., 2]

    # The six orderings of (fr, fg, fb) select the simplex; each branch is a
    # chain of four vertices along the sorted axis order.
    branches = (
        (
            (sr > sg) & (sg > sb),
            c000 + fr * (c100 - c000) + fg * (c110 - c100) + fb * (c111 - c110),
        ),
        (
            (sr > sg) & ~(sg > sb) & (sr > sb),
            c000 + fr * (c100 - c000) + fb * (c101 - c100) + fg * (c111 - c101),
        ),
        (
            (sr > sg) & ~(sg > sb) & ~(sr > sb),
            c000 + fb * (c001 - c000) + fr * (c101 - c001) + fg * (c111 - c101),
        ),
        (
            ~(sr > sg) & (sb > sg),
            c000 + fb * (c001 - c000) + fg * (c011 - c001) + fr * (c111 - c011),
        ),
        (
            ~(sr > sg) & ~(sb > sg) & (sb > sr),
            c000 + fg * (c010 - c000) + fb * (c011 - c010) + fr * (c111 - c011),
        ),
        (
            ~(sr > sg) & ~(sb > sg) & ~(sb > sr),
            c000 + fg * (c010 - c000) + fr * (c110 - c010) + fb * (c111 - c110),
        ),
    )

    # A NaN coordinate matches no branch; seeding with the lower corner keeps
    # the output defined instead of uninitialised.
    out = np.array(c000, dtype=np.float64, copy=True)
    assigned = np.zeros(sr.shape, dtype=bool)
    for mask, value in branches:
        take = mask & ~assigned
        assigned |= take
        out[take] = value[take]
    return out
```

### 6.7 维度四：六图 ×（原图+五种预设）完整质量数据

6种方案为Original基线+warm/cool/soft/cinematic/mono，并不是六个有风格预设。当前数据为1张夹具scene+5张固定种子合成图，不能描述成6张真实摄影图片。hdr场景本身是8-bit SDR合成高反差图，不是HDR浮点编码输入。dataset实际无条件附加所有五张合成图，minimum参数没有限制生成数量；与“缺几张补几张”的docstring不同。最长边768，scene实际768×449，其余见下表。

| 图key | 来源 | 宽×高 | 原始路径 |
| --- | --- | --- | --- |
| scene | fixture | 768×449 | runtime\benchmark_results\assets\images\fixture_scene.png |
| underexposed | synthetic | 768×512 | runtime\benchmark_results\assets\images\synth_underexposed.png |
| lowcontrast | synthetic | 768×512 | runtime\benchmark_results\assets\images\synth_lowcontrast.png |
| saturated | synthetic | 768×512 | runtime\benchmark_results\assets\images\synth_saturated.png |
| skintone | synthetic | 768×512 | runtime\benchmark_results\assets\images\synth_skintone.png |
| hdr | synthetic | 768×512 | runtime\benchmark_results\assets\images\synth_hdr.png |

| 方案 | SSIM | 亮度mean | 对比σ | 熵bits | 丰富度 | low % | high % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Original | 1.0 | 117.059 | 50.693 | 5.6204 | 32.754 | 0.1037 | 0.8736 |
| warm | 0.9871 | 123.7028 | 50.9668 | 5.5771 | 41.1931 | 0.0 | 0.0 |
| cool | 0.9866 | 116.0518 | 48.0222 | 5.5319 | 33.4285 | 0.0 | 0.0 |
| soft | 0.9463 | 126.389 | 45.4308 | 5.4048 | 32.0881 | 0.0 | 0.0 |
| cinematic | 0.9797 | 119.0188 | 47.399 | 5.4862 | 37.8302 | 0.0 | 0.0 |
| mono | 0.9906 | 118.3942 | 53.552 | 5.6584 | 0.0 | 1.4117 | 0.8555 |

| 图key | 方案 | SSIM | 亮度mean | 对比σ | 熵bits | 丰富度 | low % | high % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| scene | Original | 1.0 | 142.113 | 102.078 | 4.6018 | 8.0389 | 0.0525 | 4.1461 |
| scene | warm | 0.98755 | 146.905 | 101.19 | 4.3673 | 14.0355 | 0.0 | 0.0 |
| scene | cool | 0.98889 | 138.697 | 95.489 | 4.5099 | 11.4209 | 0.0 | 0.0 |
| scene | soft | 0.9405 | 149.767 | 91.518 | 4.0402 | 9.1007 | 0.0 | 0.0 |
| scene | cinematic | 0.97977 | 138.614 | 92.942 | 4.4129 | 17.5245 | 0.0 | 0.0 |
| scene | mono | 0.99095 | 141.836 | 106.016 | 4.4684 | 0.0 | 0.4254 | 4.0423 |
| underexposed | Original | 1.0 | 44.975 | 33.089 | 6.2312 | 7.26 | 0.0 | 0.0 |
| underexposed | warm | 0.98121 | 50.496 | 33.091 | 6.205 | 12.6619 | 0.0 | 0.0 |
| underexposed | cool | 0.98197 | 47.404 | 29.604 | 5.9849 | 8.9678 | 0.0 | 0.0 |
| underexposed | soft | 0.88268 | 62.67 | 29.898 | 6.1005 | 7.6338 | 0.0 | 0.0 |
| underexposed | cinematic | 0.96785 | 50.165 | 30.024 | 5.9951 | 14.1773 | 0.0 | 0.0 |
| underexposed | mono | 0.98293 | 40.721 | 33.675 | 6.2104 | 0.0 | 0.0 | 0.0 |
| lowcontrast | Original | 1.0 | 142.098 | 7.457 | 4.8618 | 3.9777 | 0.0 | 0.0 |
| lowcontrast | warm | 0.99772 | 150.845 | 7.686 | 4.9139 | 4.3735 | 0.0 | 0.0 |
| lowcontrast | cool | 0.99951 | 140.741 | 7.847 | 4.9428 | 7.7779 | 0.0 | 0.0 |
| lowcontrast | soft | 0.99875 | 147.093 | 6.602 | 4.6617 | 2.7488 | 0.0 | 0.0 |
| lowcontrast | cinematic | 0.9991 | 146.319 | 7.603 | 4.8817 | 3.5003 | 0.0 | 0.0 |
| lowcontrast | mono | 0.99719 | 148.445 | 8.568 | 5.0776 | 0.0 | 0.0 | 0.0 |
| saturated | Original | 1.0 | 125.838 | 18.609 | 4.7128 | 124.4948 | 0.0 | 0.0 |
| saturated | warm | 0.99787 | 132.832 | 19.141 | 4.791 | 140.6429 | 0.0 | 0.0 |
| saturated | cool | 0.99881 | 124.324 | 18.997 | 4.7498 | 125.8415 | 0.0 | 0.0 |
| saturated | soft | 0.99726 | 133.388 | 16.9 | 4.6184 | 116.7652 | 0.0 | 0.0 |
| saturated | cinematic | 0.99904 | 128.533 | 18.795 | 4.7422 | 121.7576 | 0.0 | 0.0 |
| saturated | mono | 0.99674 | 128.694 | 20.746 | 4.9591 | 0.0 | 0.0 | 0.0 |
| skintone | Original | 1.0 | 138.12 | 46.315 | 6.7694 | 42.8774 | 0.0 | 0.0 |
| skintone | warm | 0.99788 | 145.75 | 47.929 | 6.7643 | 56.6686 | 0.0 | 0.0 |
| skintone | cool | 0.99926 | 135.965 | 45.76 | 6.7032 | 38.8667 | 0.0 | 0.0 |
| skintone | soft | 0.99238 | 145.299 | 40.708 | 6.6137 | 43.8684 | 0.0 | 0.0 |
| skintone | cinematic | 0.99894 | 139.758 | 46.085 | 6.6578 | 48.9354 | 0.0 | 0.0 |
| skintone | mono | 0.9965 | 141.255 | 51.56 | 6.8434 | 0.0 | 0.0 | 0.0 |
| hdr | Original | 1.0 | 109.209 | 96.609 | 6.5454 | 9.8753 | 0.5699 | 1.0953 |
| hdr | warm | 0.96007 | 115.389 | 96.764 | 6.421 | 18.7763 | 0.0 | 0.0 |
| hdr | cool | 0.95132 | 109.18 | 90.436 | 6.3009 | 7.6964 | 0.0 | 0.0 |
| hdr | soft | 0.86602 | 120.117 | 86.959 | 6.3943 | 12.412 | 0.0 | 0.0 |
| hdr | cinematic | 0.93341 | 110.724 | 88.945 | 6.2277 | 21.0862 | 0.0 | 0.0 |
| hdr | mono | 0.97917 | 109.414 | 100.747 | 6.3917 | 0.0 | 8.0447 | 1.0905 |

clip_low/high来自app.histogram：编码亮度量化≤2/255或≥253/255的像素比例×100，不是RGB任一通道越界率。SSIM是亮度8×8 uniform滑窗valid平均，非Gaussian标准库默认；C1=.01²,C2=.03²。熵为256-bin量化亮度Shannon熵；丰富度为Hasler&Suesstrunk代理。调色改变亮度/对比会降低SSIM，不自动表示主观画质差；SSIM高也不能证明没有光晕、局部伪影或通过美学评价。该实验不含空间Bloom，不能用于证明Bloom质量。

公式：

\[
SSIM=\operatorname{mean}\frac{(2\mu_x\mu_y+C_1)(2\sigma_{xy}+C_2)}{(\mu_x^2+\mu_y^2+C_1)(\sigma_x^2+\sigma_y^2+C_2)},\quad
H=-\sum_{p_i>0}p_i\log_2p_i.
\]

\[
CF=\sqrt{\operatorname{Var}(R-G)+\operatorname{Var}((R+G)/2-B)}+.3\sqrt{\operatorname{Mean}(R-G)^2+\operatorname{Mean}((R+G)/2-B)^2}.
\]

PSNR=10log10(255²/MSE)；代码对完全相同样本用100.0dB哨兵而非正无穷。

### 6.8 维度五：24条中文指令与消融

记录的在线模型为deepseek/deepseek-flash。基线来自`tools/benchmark/offline_baseline.json`，capture=2026-11-18 13:10:33；在线/离线分别各24条，按Provider.generate调用端到端计时，包含可能重试。这里“Schema一次通过率”原始字段first_pass_valid_rate实际上仅由最终Proposal存在且无异常计算，并未统计模型首次HTTP输出是否已经合法；应在论文中改称“最终结构化返回有效率”。clamping_rate是任一字段触及端点的样本比例（含amount=0），不是发生越界后被裁剪的比率。

| Provider | model | N | 有效率% | 端点触达% | 方向准确% | mean ms | P95 ms | max ms |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| offline-before | template | 24 | 100.0 | 54.17 | 45.83 | 0.3648 | 1.0285 | 1.5586 |
| offline | template+rules | 24 | 100.0 | 62.5 | 100.0 | 0.4738 | 1.2136 | 1.8161 |
| deepseek | deepseek-flash | 24 | 100.0 | 62.5 | 100.0 | 1885.6652 | 2784.9087 | 4103.2224 |

| 类别 | N | 优化前准确% | 离线优化后% | 在线% | 离线mean ms | 在线mean ms |
| --- | --- | --- | --- | --- | --- | --- |
| 单维微调 | 6 | 16.67 | 100.0 | 100.0 | 0.4703 | 1523.9319 |
| 复合氛围 | 6 | 100.0 | 100.0 | 100.0 | 1.1378 | 1599.5956 |
| 增量微调 | 4 | 0.0 | 100.0 | 100.0 | 0.2022 | 1866.6557 |
| 极端/边界 | 4 | 0.0 | 100.0 | 100.0 | 0.1451 | 2104.0624 |
| 无关噪声 | 4 | 100.0 | 100.0 | 100.0 | 0.0836 | 2657.9821 |

原始24条逐条结果与延迟：

| ID | 类别 | 指令原文 | 期望 | 优化前 | 离线优化后 | 在线 | 离线ms | 在线ms | 错误 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| S1 | single | 把画面整体调亮一点 | 曝光上升 | False | True | True | 1.2204 | 1976.85 |  |
| S2 | single | 画面太亮了，帮我压暗一些 | 曝光下降 | False | True | True | 0.2029 | 1683.7937 |  |
| S3 | single | 增加一点对比度 | 对比度上升 | False | True | True | 0.1663 | 1067.1433 |  |
| S4 | single | 把饱和度降下来一点 | 饱和度下降 | False | True | True | 0.159 | 1056.7356 |  |
| S5 | single | 整体调得偏暖一些 | 色温上升 | True | True | True | 0.8787 | 1601.2047 |  |
| S6 | single | 把高光压一压 | 高光下降 | False | True | True | 0.1947 | 1757.8639 |  |
| M1 | compound | 黄昏暖调，同时压住高光 | 色温上升 + 高光下降 | True | True | True | 1.8161 | 1942.7004 |  |
| M2 | compound | 清冷通透的日系氛围 | 色温下降 + 曝光上升 | True | True | True | 1.1754 | 1209.1809 |  |
| M3 | compound | 电影感的青橙色调 | 分离色调双侧着色 | True | True | True | 0.9841 | 1365.5568 |  |
| M4 | compound | 黑白纪实风格，加强对比 | 饱和度归零 + 对比度上升 | True | True | True | 0.9217 | 1999.4592 |  |
| M5 | compound | 柔和低对比的雾面感 | 对比度下降 | True | True | True | 0.9861 | 1219.5775 |  |
| M6 | compound | 鲜艳浓郁的风光大片 | 色彩浓度上升（饱和度或自然饱和度） | True | True | True | 0.9432 | 1861.0989 |  |
| I1 | incremental | 再暖一点 | 在当前暖色基础上色温继续上升 | False | True | True | 0.2065 | 2043.2004 |  |
| I2 | incremental | 高光再压一点 | 在当前基础上高光继续下降 | False | True | True | 0.2025 | 1590.7941 |  |
| I3 | incremental | 饱和度再高一些 | 在当前基础上饱和度继续上升 | False | True | True | 0.1973 | 1814.5887 |  |
| I4 | incremental | 对比再强一点 | 在当前基础上对比度继续上升 | False | True | True | 0.2023 | 2018.0395 |  |
| X1 | extreme | 曝光拉到最亮 | 曝光接近 +2 EV 上界 | False | True | True | 0.1617 | 1509.268 |  |
| X2 | extreme | 饱和度全部去掉，越灰越好 | 饱和度贴近 -100 下界 | False | True | True | 0.1523 | 1871.7708 |  |
| X3 | extreme | 色温调到最冷 | 色温贴近 -100 下界 | False | True | True | 0.1275 | 2366.6107 |  |
| X4 | extreme | 对比度拉到极限 | 对比度贴近 +100 上界 | False | True | True | 0.1389 | 2668.6001 |  |
| N1 | noise | 帮我写个冒泡排序 | 参数保持不变 | True | True | True | 0.085 | 2805.4338 |  |
| N2 | noise | 今天天气怎么样 | 参数保持不变 | True | True | True | 0.0834 | 1394.9064 |  |
| N3 | noise | 1+1 等于几 | 参数保持不变 | True | True | True | 0.0834 | 2328.366 |  |
| N4 | noise | 把这段文字翻译成英文 | 参数保持不变 | True | True | True | 0.0824 | 4103.2224 |  |

方向判断基于Check(gt/lt/ge/le/unchanged)和有限阈值，不是人类审美评分或开放中文语义能力评测。24条各测一次，100%=24/24，不能宣称自然语言任意输入100%正确。优化前11/24=45.83%，优化后24/24=100%，提升54.17个百分点。在线延迟是2026-11-18网络/模型条件下记录，不是服务时延承诺；没有在本次重新请求API。

逐条参数、valid、boundary、checks完整保留如下（从原始JSON投影，未四舍五入）：

<details>
<summary>展开48条AI原始结果与16维参数</summary>

```json
[
  {
    "provider": "offline",
    "model": "template+rules",
    "cases": [
      {
        "case": "S1",
        "category": "single",
        "intent": "把画面整体调亮一点",
        "expect": "曝光上升",
        "current": "identity",
        "latency_ms": 1.2204,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "gt(exposure_ev)=PASS"
        ],
        "params": {
          "exposure_ev": 0.25,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "S2",
        "category": "single",
        "intent": "画面太亮了，帮我压暗一些",
        "expect": "曝光下降",
        "current": "identity",
        "latency_ms": 0.2029,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "lt(exposure_ev)=PASS"
        ],
        "params": {
          "exposure_ev": -0.25,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "S3",
        "category": "single",
        "intent": "增加一点对比度",
        "expect": "对比度上升",
        "current": "identity",
        "latency_ms": 0.1663,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "gt(contrast)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 15.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "S4",
        "category": "single",
        "intent": "把饱和度降下来一点",
        "expect": "饱和度下降",
        "current": "identity",
        "latency_ms": 0.159,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "lt(saturation)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": -15.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "S5",
        "category": "single",
        "intent": "整体调得偏暖一些",
        "expect": "色温上升",
        "current": "identity",
        "latency_ms": 0.8787,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "gt(temperature)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": 15.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "S6",
        "category": "single",
        "intent": "把高光压一压",
        "expect": "高光下降",
        "current": "identity",
        "latency_ms": 0.1947,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "lt(highlights)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": -25.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "M1",
        "category": "compound",
        "intent": "黄昏暖调，同时压住高光",
        "expect": "色温上升 + 高光下降",
        "current": "identity",
        "latency_ms": 1.8161,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "gt(temperature)=PASS",
          "lt(highlights)=PASS"
        ],
        "params": {
          "exposure_ev": 0.15,
          "contrast": 8.0,
          "temperature": 57.0,
          "tint": 3.0,
          "highlights": -37.0,
          "shadows": 10.0,
          "whites": 4.0,
          "blacks": -6.0,
          "saturation": 8.0,
          "vibrance": 10.0,
          "hue": 0.0,
          "split_shadow_hue": 30.0,
          "split_shadow_amount": 12.0,
          "split_highlight_hue": 45.0,
          "split_highlight_amount": 14.0,
          "split_balance": 10.0
        },
        "error": ""
      },
      {
        "case": "M2",
        "category": "compound",
        "intent": "清冷通透的日系氛围",
        "expect": "色温下降 + 曝光上升",
        "current": "identity",
        "latency_ms": 1.1754,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "lt(temperature)=PASS",
          "gt(exposure_ev)=PASS"
        ],
        "params": {
          "exposure_ev": 0.2,
          "contrast": 12.0,
          "temperature": -34.0,
          "tint": -4.0,
          "highlights": -12.0,
          "shadows": 15.0,
          "whites": -4.0,
          "blacks": 4.0,
          "saturation": -4.0,
          "vibrance": 6.0,
          "hue": 0.0,
          "split_shadow_hue": 210.0,
          "split_shadow_amount": 14.0,
          "split_highlight_hue": 195.0,
          "split_highlight_amount": 8.0,
          "split_balance": -10.0
        },
        "error": ""
      },
      {
        "case": "M3",
        "category": "compound",
        "intent": "电影感的青橙色调",
        "expect": "分离色调双侧着色",
        "current": "identity",
        "latency_ms": 0.9841,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "gt(split_shadow_amount)=PASS",
          "gt(split_highlight_amount)=PASS"
        ],
        "params": {
          "exposure_ev": 0.05,
          "contrast": 18.0,
          "temperature": 6.0,
          "tint": -2.0,
          "highlights": -22.0,
          "shadows": 8.0,
          "whites": -6.0,
          "blacks": -8.0,
          "saturation": -6.0,
          "vibrance": 4.0,
          "hue": 0.0,
          "split_shadow_hue": 190.0,
          "split_shadow_amount": 26.0,
          "split_highlight_hue": 35.0,
          "split_highlight_amount": 22.0,
          "split_balance": 6.0
        },
        "error": ""
      },
      {
        "case": "M4",
        "category": "compound",
        "intent": "黑白纪实风格，加强对比",
        "expect": "饱和度归零 + 对比度上升",
        "current": "identity",
        "latency_ms": 0.9217,
        "valid": true,
        "boundary": [
          "saturation=-100",
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "le(saturation)=PASS",
          "gt(contrast)=PASS"
        ],
        "params": {
          "exposure_ev": 0.05,
          "contrast": 47.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": -10.0,
          "shadows": 6.0,
          "whites": 6.0,
          "blacks": -10.0,
          "saturation": -100.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "M5",
        "category": "compound",
        "intent": "柔和低对比的雾面感",
        "expect": "对比度下降",
        "current": "identity",
        "latency_ms": 0.9861,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "lt(contrast)=PASS"
        ],
        "params": {
          "exposure_ev": 0.2,
          "contrast": -14.0,
          "temperature": 6.0,
          "tint": 2.0,
          "highlights": -18.0,
          "shadows": 22.0,
          "whites": -10.0,
          "blacks": 14.0,
          "saturation": -8.0,
          "vibrance": 4.0,
          "hue": 0.0,
          "split_shadow_hue": 40.0,
          "split_shadow_amount": 6.0,
          "split_highlight_hue": 50.0,
          "split_highlight_amount": 8.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "M6",
        "category": "compound",
        "intent": "鲜艳浓郁的风光大片",
        "expect": "色彩浓度上升（饱和度或自然饱和度）",
        "current": "identity",
        "latency_ms": 0.9432,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "gt(saturation,vibrance)=PASS"
        ],
        "params": {
          "exposure_ev": 0.15,
          "contrast": 8.0,
          "temperature": 32.0,
          "tint": 3.0,
          "highlights": -12.0,
          "shadows": 10.0,
          "whites": 4.0,
          "blacks": -6.0,
          "saturation": 10.0,
          "vibrance": 22.0,
          "hue": 0.0,
          "split_shadow_hue": 30.0,
          "split_shadow_amount": 12.0,
          "split_highlight_hue": 45.0,
          "split_highlight_amount": 14.0,
          "split_balance": 10.0
        },
        "error": ""
      },
      {
        "case": "I1",
        "category": "incremental",
        "intent": "再暖一点",
        "expect": "在当前暖色基础上色温继续上升",
        "current": "warm",
        "latency_ms": 0.2065,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "gt(temperature)=PASS"
        ],
        "params": {
          "exposure_ev": 0.15,
          "contrast": 8.0,
          "temperature": 47.0,
          "tint": 3.0,
          "highlights": -12.0,
          "shadows": 10.0,
          "whites": 4.0,
          "blacks": -6.0,
          "saturation": 8.0,
          "vibrance": 10.0,
          "hue": 0.0,
          "split_shadow_hue": 30.0,
          "split_shadow_amount": 12.0,
          "split_highlight_hue": 45.0,
          "split_highlight_amount": 14.0,
          "split_balance": 10.0
        },
        "error": ""
      },
      {
        "case": "I2",
        "category": "incremental",
        "intent": "高光再压一点",
        "expect": "在当前基础上高光继续下降",
        "current": "warm",
        "latency_ms": 0.2025,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "lt(highlights)=PASS"
        ],
        "params": {
          "exposure_ev": 0.15,
          "contrast": 8.0,
          "temperature": 32.0,
          "tint": 3.0,
          "highlights": -27.0,
          "shadows": 10.0,
          "whites": 4.0,
          "blacks": -6.0,
          "saturation": 8.0,
          "vibrance": 10.0,
          "hue": 0.0,
          "split_shadow_hue": 30.0,
          "split_shadow_amount": 12.0,
          "split_highlight_hue": 45.0,
          "split_highlight_amount": 14.0,
          "split_balance": 10.0
        },
        "error": ""
      },
      {
        "case": "I3",
        "category": "incremental",
        "intent": "饱和度再高一些",
        "expect": "在当前基础上饱和度继续上升",
        "current": "warm",
        "latency_ms": 0.1973,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "gt(saturation)=PASS"
        ],
        "params": {
          "exposure_ev": 0.15,
          "contrast": 8.0,
          "temperature": 32.0,
          "tint": 3.0,
          "highlights": -12.0,
          "shadows": 10.0,
          "whites": 4.0,
          "blacks": -6.0,
          "saturation": 23.0,
          "vibrance": 10.0,
          "hue": 0.0,
          "split_shadow_hue": 30.0,
          "split_shadow_amount": 12.0,
          "split_highlight_hue": 45.0,
          "split_highlight_amount": 14.0,
          "split_balance": 10.0
        },
        "error": ""
      },
      {
        "case": "I4",
        "category": "incremental",
        "intent": "对比再强一点",
        "expect": "在当前基础上对比度继续上升",
        "current": "warm",
        "latency_ms": 0.2023,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "gt(contrast)=PASS"
        ],
        "params": {
          "exposure_ev": 0.15,
          "contrast": 23.0,
          "temperature": 32.0,
          "tint": 3.0,
          "highlights": -12.0,
          "shadows": 10.0,
          "whites": 4.0,
          "blacks": -6.0,
          "saturation": 8.0,
          "vibrance": 10.0,
          "hue": 0.0,
          "split_shadow_hue": 30.0,
          "split_shadow_amount": 12.0,
          "split_highlight_hue": 45.0,
          "split_highlight_amount": 14.0,
          "split_balance": 10.0
        },
        "error": ""
      },
      {
        "case": "X1",
        "category": "extreme",
        "intent": "曝光拉到最亮",
        "expect": "曝光接近 +2 EV 上界",
        "current": "identity",
        "latency_ms": 0.1617,
        "valid": true,
        "boundary": [
          "exposure_ev=2",
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "ge(exposure_ev)=PASS"
        ],
        "params": {
          "exposure_ev": 2.0,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "X2",
        "category": "extreme",
        "intent": "饱和度全部去掉，越灰越好",
        "expect": "饱和度贴近 -100 下界",
        "current": "identity",
        "latency_ms": 0.1523,
        "valid": true,
        "boundary": [
          "saturation=-100",
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "le(saturation)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": -100.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "X3",
        "category": "extreme",
        "intent": "色温调到最冷",
        "expect": "色温贴近 -100 下界",
        "current": "identity",
        "latency_ms": 0.1275,
        "valid": true,
        "boundary": [
          "temperature=-100",
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "le(temperature)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": -100.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "X4",
        "category": "extreme",
        "intent": "对比度拉到极限",
        "expect": "对比度贴近 +100 上界",
        "current": "identity",
        "latency_ms": 0.1389,
        "valid": true,
        "boundary": [
          "contrast=100",
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "ge(contrast)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 100.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "N1",
        "category": "noise",
        "intent": "帮我写个冒泡排序",
        "expect": "参数保持不变",
        "current": "identity",
        "latency_ms": 0.085,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "unchanged(exposure_ev,contrast,temperature,tint,highlights,shadows,whites,blacks,saturation,vibrance,hue,split_shadow_hue,split_shadow_amount,split_highlight_hue,split_highlight_amount,split_balance)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "N2",
        "category": "noise",
        "intent": "今天天气怎么样",
        "expect": "参数保持不变",
        "current": "identity",
        "latency_ms": 0.0834,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "unchanged(exposure_ev,contrast,temperature,tint,highlights,shadows,whites,blacks,saturation,vibrance,hue,split_shadow_hue,split_shadow_amount,split_highlight_hue,split_highlight_amount,split_balance)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "N3",
        "category": "noise",
        "intent": "1+1 等于几",
        "expect": "参数保持不变",
        "current": "identity",
        "latency_ms": 0.0834,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "unchanged(exposure_ev,contrast,temperature,tint,highlights,shadows,whites,blacks,saturation,vibrance,hue,split_shadow_hue,split_shadow_amount,split_highlight_hue,split_highlight_amount,split_balance)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "N4",
        "category": "noise",
        "intent": "把这段文字翻译成英文",
        "expect": "参数保持不变",
        "current": "identity",
        "latency_ms": 0.0824,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "unchanged(exposure_ev,contrast,temperature,tint,highlights,shadows,whites,blacks,saturation,vibrance,hue,split_shadow_hue,split_shadow_amount,split_highlight_hue,split_highlight_amount,split_balance)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      }
    ]
  },
  {
    "provider": "deepseek",
    "model": "deepseek-flash",
    "cases": [
      {
        "case": "S1",
        "category": "single",
        "intent": "把画面整体调亮一点",
        "expect": "曝光上升",
        "current": "identity",
        "latency_ms": 1976.85,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "gt(exposure_ev)=PASS"
        ],
        "params": {
          "exposure_ev": 0.35,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": -6.0,
          "shadows": 8.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "S2",
        "category": "single",
        "intent": "画面太亮了，帮我压暗一些",
        "expect": "曝光下降",
        "current": "identity",
        "latency_ms": 1683.7937,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "lt(exposure_ev)=PASS"
        ],
        "params": {
          "exposure_ev": -0.6,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": -12.0,
          "shadows": 0.0,
          "whites": -6.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "S3",
        "category": "single",
        "intent": "增加一点对比度",
        "expect": "对比度上升",
        "current": "identity",
        "latency_ms": 1067.1433,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "gt(contrast)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 8.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "S4",
        "category": "single",
        "intent": "把饱和度降下来一点",
        "expect": "饱和度下降",
        "current": "identity",
        "latency_ms": 1056.7356,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "lt(saturation)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": -14.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "S5",
        "category": "single",
        "intent": "整体调得偏暖一些",
        "expect": "色温上升",
        "current": "identity",
        "latency_ms": 1601.2047,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "gt(temperature)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": 22.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "S6",
        "category": "single",
        "intent": "把高光压一压",
        "expect": "高光下降",
        "current": "identity",
        "latency_ms": 1757.8639,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "lt(highlights)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": -30.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "M1",
        "category": "compound",
        "intent": "黄昏暖调，同时压住高光",
        "expect": "色温上升 + 高光下降",
        "current": "identity",
        "latency_ms": 1942.7004,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "gt(temperature)=PASS",
          "lt(highlights)=PASS"
        ],
        "params": {
          "exposure_ev": 0.1,
          "contrast": 12.0,
          "temperature": 28.0,
          "tint": 4.0,
          "highlights": -30.0,
          "shadows": 8.0,
          "whites": -12.0,
          "blacks": -4.0,
          "saturation": 10.0,
          "vibrance": 8.0,
          "hue": 0.0,
          "split_shadow_hue": 35.0,
          "split_shadow_amount": 10.0,
          "split_highlight_hue": 40.0,
          "split_highlight_amount": 14.0,
          "split_balance": 10.0
        },
        "error": ""
      },
      {
        "case": "M2",
        "category": "compound",
        "intent": "清冷通透的日系氛围",
        "expect": "色温下降 + 曝光上升",
        "current": "identity",
        "latency_ms": 1209.1809,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "lt(temperature)=PASS",
          "gt(exposure_ev)=PASS"
        ],
        "params": {
          "exposure_ev": 0.2,
          "contrast": -6.0,
          "temperature": -16.0,
          "tint": 2.0,
          "highlights": -10.0,
          "shadows": 16.0,
          "whites": -6.0,
          "blacks": 8.0,
          "saturation": -8.0,
          "vibrance": 10.0,
          "hue": 0.0,
          "split_shadow_hue": 205.0,
          "split_shadow_amount": 12.0,
          "split_highlight_hue": 190.0,
          "split_highlight_amount": 6.0,
          "split_balance": -4.0
        },
        "error": ""
      },
      {
        "case": "M3",
        "category": "compound",
        "intent": "电影感的青橙色调",
        "expect": "分离色调双侧着色",
        "current": "identity",
        "latency_ms": 1365.5568,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "gt(split_shadow_amount)=PASS",
          "gt(split_highlight_amount)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 20.0,
          "temperature": 5.0,
          "tint": 0.0,
          "highlights": -18.0,
          "shadows": 8.0,
          "whites": -4.0,
          "blacks": -8.0,
          "saturation": -4.0,
          "vibrance": 6.0,
          "hue": 0.0,
          "split_shadow_hue": 195.0,
          "split_shadow_amount": 26.0,
          "split_highlight_hue": 35.0,
          "split_highlight_amount": 22.0,
          "split_balance": 4.0
        },
        "error": ""
      },
      {
        "case": "M4",
        "category": "compound",
        "intent": "黑白纪实风格，加强对比",
        "expect": "饱和度归零 + 对比度上升",
        "current": "identity",
        "latency_ms": 1999.4592,
        "valid": true,
        "boundary": [
          "saturation=-100",
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "le(saturation)=PASS",
          "gt(contrast)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 32.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": -14.0,
          "shadows": -8.0,
          "whites": 10.0,
          "blacks": -16.0,
          "saturation": -100.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "M5",
        "category": "compound",
        "intent": "柔和低对比的雾面感",
        "expect": "对比度下降",
        "current": "identity",
        "latency_ms": 1219.5775,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "lt(contrast)=PASS"
        ],
        "params": {
          "exposure_ev": 0.1,
          "contrast": -22.0,
          "temperature": 3.0,
          "tint": 2.0,
          "highlights": -12.0,
          "shadows": 22.0,
          "whites": -8.0,
          "blacks": 14.0,
          "saturation": -10.0,
          "vibrance": 6.0,
          "hue": 0.0,
          "split_shadow_hue": 210.0,
          "split_shadow_amount": 10.0,
          "split_highlight_hue": 45.0,
          "split_highlight_amount": 8.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "M6",
        "category": "compound",
        "intent": "鲜艳浓郁的风光大片",
        "expect": "色彩浓度上升（饱和度或自然饱和度）",
        "current": "identity",
        "latency_ms": 1861.0989,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "gt(saturation,vibrance)=PASS"
        ],
        "params": {
          "exposure_ev": 0.1,
          "contrast": 24.0,
          "temperature": 10.0,
          "tint": -2.0,
          "highlights": -18.0,
          "shadows": 10.0,
          "whites": 8.0,
          "blacks": -10.0,
          "saturation": 20.0,
          "vibrance": 18.0,
          "hue": 0.0,
          "split_shadow_hue": 215.0,
          "split_shadow_amount": 16.0,
          "split_highlight_hue": 45.0,
          "split_highlight_amount": 14.0,
          "split_balance": 5.0
        },
        "error": ""
      },
      {
        "case": "I1",
        "category": "incremental",
        "intent": "再暖一点",
        "expect": "在当前暖色基础上色温继续上升",
        "current": "warm",
        "latency_ms": 2043.2004,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "gt(temperature)=PASS"
        ],
        "params": {
          "exposure_ev": 0.15,
          "contrast": 8.0,
          "temperature": 44.0,
          "tint": 4.0,
          "highlights": -12.0,
          "shadows": 10.0,
          "whites": 4.0,
          "blacks": -6.0,
          "saturation": 8.0,
          "vibrance": 10.0,
          "hue": 0.0,
          "split_shadow_hue": 30.0,
          "split_shadow_amount": 12.0,
          "split_highlight_hue": 45.0,
          "split_highlight_amount": 16.0,
          "split_balance": 10.0
        },
        "error": ""
      },
      {
        "case": "I2",
        "category": "incremental",
        "intent": "高光再压一点",
        "expect": "在当前基础上高光继续下降",
        "current": "warm",
        "latency_ms": 1590.7941,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "lt(highlights)=PASS"
        ],
        "params": {
          "exposure_ev": 0.15,
          "contrast": 8.0,
          "temperature": 32.0,
          "tint": 3.0,
          "highlights": -20.0,
          "shadows": 10.0,
          "whites": 2.0,
          "blacks": -6.0,
          "saturation": 8.0,
          "vibrance": 10.0,
          "hue": 0.0,
          "split_shadow_hue": 30.0,
          "split_shadow_amount": 12.0,
          "split_highlight_hue": 45.0,
          "split_highlight_amount": 12.0,
          "split_balance": 10.0
        },
        "error": ""
      },
      {
        "case": "I3",
        "category": "incremental",
        "intent": "饱和度再高一些",
        "expect": "在当前基础上饱和度继续上升",
        "current": "warm",
        "latency_ms": 1814.5887,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "gt(saturation)=PASS"
        ],
        "params": {
          "exposure_ev": 0.15,
          "contrast": 8.0,
          "temperature": 32.0,
          "tint": 3.0,
          "highlights": -12.0,
          "shadows": 10.0,
          "whites": 4.0,
          "blacks": -6.0,
          "saturation": 20.0,
          "vibrance": 14.0,
          "hue": 0.0,
          "split_shadow_hue": 30.0,
          "split_shadow_amount": 12.0,
          "split_highlight_hue": 45.0,
          "split_highlight_amount": 14.0,
          "split_balance": 10.0
        },
        "error": ""
      },
      {
        "case": "I4",
        "category": "incremental",
        "intent": "对比再强一点",
        "expect": "在当前基础上对比度继续上升",
        "current": "warm",
        "latency_ms": 2018.0395,
        "valid": true,
        "boundary": [],
        "direction_ok": true,
        "checks": [
          "gt(contrast)=PASS"
        ],
        "params": {
          "exposure_ev": 0.15,
          "contrast": 20.0,
          "temperature": 32.0,
          "tint": 3.0,
          "highlights": -12.0,
          "shadows": 10.0,
          "whites": 4.0,
          "blacks": -10.0,
          "saturation": 8.0,
          "vibrance": 10.0,
          "hue": 0.0,
          "split_shadow_hue": 30.0,
          "split_shadow_amount": 12.0,
          "split_highlight_hue": 45.0,
          "split_highlight_amount": 14.0,
          "split_balance": 10.0
        },
        "error": ""
      },
      {
        "case": "X1",
        "category": "extreme",
        "intent": "曝光拉到最亮",
        "expect": "曝光接近 +2 EV 上界",
        "current": "identity",
        "latency_ms": 1509.268,
        "valid": true,
        "boundary": [
          "exposure_ev=2",
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "ge(exposure_ev)=PASS"
        ],
        "params": {
          "exposure_ev": 2.0,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "X2",
        "category": "extreme",
        "intent": "饱和度全部去掉，越灰越好",
        "expect": "饱和度贴近 -100 下界",
        "current": "identity",
        "latency_ms": 1871.7708,
        "valid": true,
        "boundary": [
          "saturation=-100",
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "le(saturation)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": -8.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 4.0,
          "saturation": -100.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "X3",
        "category": "extreme",
        "intent": "色温调到最冷",
        "expect": "色温贴近 -100 下界",
        "current": "identity",
        "latency_ms": 2366.6107,
        "valid": true,
        "boundary": [
          "temperature=-100",
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "le(temperature)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": -100.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "X4",
        "category": "extreme",
        "intent": "对比度拉到极限",
        "expect": "对比度贴近 +100 上界",
        "current": "identity",
        "latency_ms": 2668.6001,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "ge(contrast)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 92.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": -12.0,
          "shadows": -10.0,
          "whites": 14.0,
          "blacks": -24.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "N1",
        "category": "noise",
        "intent": "帮我写个冒泡排序",
        "expect": "参数保持不变",
        "current": "identity",
        "latency_ms": 2805.4338,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "unchanged(exposure_ev,contrast,temperature,tint,highlights,shadows,whites,blacks,saturation,vibrance,hue,split_shadow_hue,split_shadow_amount,split_highlight_hue,split_highlight_amount,split_balance)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "N2",
        "category": "noise",
        "intent": "今天天气怎么样",
        "expect": "参数保持不变",
        "current": "identity",
        "latency_ms": 1394.9064,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "unchanged(exposure_ev,contrast,temperature,tint,highlights,shadows,whites,blacks,saturation,vibrance,hue,split_shadow_hue,split_shadow_amount,split_highlight_hue,split_highlight_amount,split_balance)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "N3",
        "category": "noise",
        "intent": "1+1 等于几",
        "expect": "参数保持不变",
        "current": "identity",
        "latency_ms": 2328.366,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "unchanged(exposure_ev,contrast,temperature,tint,highlights,shadows,whites,blacks,saturation,vibrance,hue,split_shadow_hue,split_shadow_amount,split_highlight_hue,split_highlight_amount,split_balance)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      },
      {
        "case": "N4",
        "category": "noise",
        "intent": "把这段文字翻译成英文",
        "expect": "参数保持不变",
        "current": "identity",
        "latency_ms": 4103.2224,
        "valid": true,
        "boundary": [
          "split_shadow_hue=0",
          "split_shadow_amount=0",
          "split_highlight_hue=0",
          "split_highlight_amount=0"
        ],
        "direction_ok": true,
        "checks": [
          "unchanged(exposure_ev,contrast,temperature,tint,highlights,shadows,whites,blacks,saturation,vibrance,hue,split_shadow_hue,split_shadow_amount,split_highlight_hue,split_highlight_amount,split_balance)=PASS"
        ],
        "params": {
          "exposure_ev": 0.0,
          "contrast": 0.0,
          "temperature": 0.0,
          "tint": 0.0,
          "highlights": 0.0,
          "shadows": 0.0,
          "whites": 0.0,
          "blacks": 0.0,
          "saturation": 0.0,
          "vibrance": 0.0,
          "hue": 0.0,
          "split_shadow_hue": 0.0,
          "split_shadow_amount": 0.0,
          "split_highlight_hue": 0.0,
          "split_highlight_amount": 0.0,
          "split_balance": 0.0
        },
        "error": ""
      }
    ]
  }
]
```
</details>

### 6.9 阶段七18项：数值原样与证据等级

原始矩阵时间=2026-11-20 19:57:42，passed=18 / total=18，all_pass=True。它**含5条直接硬编码True的占位/跳过项**，不是18次全部完成实机断言；F3虽然有单元测试支持，当前脚本本身未执行该项。报告“全部PASS”只能引用为既存脚本输出，并同时解释这些限制。

| ID | 检查对象 | 记录pass | 原始数值/备注 | 证据等级 |
| --- | --- | --- | --- | --- |
| A1 | 不透明像素包围盒比例 | True | {"aspect": 1.710791366906475, "expected": 1.7095158597662772, "opaque": 828240} | 真实浏览器断言（范围有限） |
| A2 | 画布角alpha | True | {"corners": [0, 0, 0, 0]} | 真实浏览器断言（范围有限） |
| A3 | HUD滚轮数值 | True | {"before": "100%", "after": "108%"} | 真实浏览器断言（范围有限） |
| A4 | 页面横向overflow | True | {"scrollOverflow": 0} | 真实浏览器断言（范围有限） |
| B1 | 2D静图mipmap状态 | True | {"minFilter": 9987, "glErr": 0, "mipmap": true} | 真实浏览器断言（范围有限） |
| B2 | warm预设应用 | True | {"note": "preset warm applied"} | 真实浏览器断言（范围有限） |
| B3 | Bloom亮度采样 | True | {"bright0": 124.21025735643559, "bright1": 224.791996958464} | 真实浏览器断言（范围有限） |
| B4 | 立方体canvas可见/有尺寸 | True | {} | 真实浏览器断言（范围有限） |
| B5 | 直方图像素/跨度 | True | {"histCount": 2236, "histSpan": 0.9727272727272728} | 真实浏览器断言（范围有限） |
| C1 | 模式UI切换 | True | {"states": "3-cycle"} | 真实浏览器断言（范围有限） |
| C2 | 分屏组件可见 | True | {} | 真实浏览器断言（范围有限） |
| D1 | 视频（脚本跳过） | True | {"note": "video skipped in headless quick path"} | 硬编码True/未在此脚本执行 |
| D2 | 视频控制（脚本跳过） | True | {"note": "video skipped"} | 硬编码True/未在此脚本执行 |
| E1 | 结构化chip不误进暖模板 | True | {"summary": "按结构化数值解析：temperature +6, tint +2, exposure_ev +0.2, highlights -12, shadows +15, saturation -8, vibrance +6。全局调色：曝光 (EV)"} | 真实浏览器断言（范围有限） |
| E2 | reset强度100%及弱undo检查 | True | {} | 部分断言；undo条件恒真 |
| F1 | cube错误UX（手工占位） | True | {"note": "cube error UX manual"} | 硬编码True/未在此脚本执行 |
| F2 | 导出smoke（手工占位） | True | {"note": "export job smoke manual"} | 硬编码True/未在此脚本执行 |
| F3 | 持久化（引用单元测试） | True | {"note": "media_store persistence unit-tested"} | 硬编码True/未在此脚本执行 |

A1 aspect=1.710791366906475、expected=1.7095158597662772、opaque=828240；A2四角alpha均0。B3亮度由124.21025735643559到224.791996958464；B5 histCount2236、span=.9727272727272728。C1记录states=3-cycle，代码实际循环一遍5标签，不能沿用旧报告“四轮切换”的措辞。E2的`count()>=0`恒成立，只能确认重置后强度文本100%，不是强撤销断言。B4只检canvas可见/width>0，不足以证明点云几何/采样数值正确。

#### Bloom开启FPS：缺少原始测量，不能填数

`stage7_acceptance_matrix.json`没有FPS或帧时数据，STAGE7_ACCEPTANCE_REPORT也没有；脚本没有测量稳定区间、frame count/time或GPU timer。`workbench.ts`状态卡“WebGL2实时·60 FPS”是固定文字；HUD FPS是素材fps。故本项目目前可证实“使用RAF实时绘制并有Bloom管线”，**无法从既存证据给出开启Bloom后的实测FPS**。本次严格只读归档不新增benchmark测量、更不把C++ readback倒数伪装为Web FPS。

阶段六辅助原始记录：

```json
{
  "base": "http://127.0.0.1:5173",
  "checks": [
    {
      "name": "histogram_pixels",
      "ok": true,
      "count": 1632,
      "glErr": 0,
      "w": 288,
      "h": 110
    },
    {
      "name": "qingtou_not_warm_template",
      "warm_leak": false,
      "summary": "按结构化数值解析：temperature +6, tint +2, exposure_ev +0.2, highlights -12, shadows +15, saturation -8, vibrance +6。全局调色：曝光 (EV) +0.20，色温 +6，色调 +2，高光 -12，阴影 +15，饱和度 -8，"
    },
    {
      "name": "console_errors",
      "errors": []
    },
    {
      "name": "histogram_after_bloom",
      "count": 1736,
      "ok": true
    }
  ]
}
```

### 6.10 原报告表格原样留档与计算公式源码

以下所有表块原样摘自benchmark_report.md，经当前report.build(raw)复算逐块一致。用于对照原展示精度；精确JSON值以上文表为准。原报告解释中的“最优”“视觉无损”“一次通过”“GPU纯着色”等强表述应使用本归档的限定口径。

原报告表块 1：

| 项目 | 值 |
|---|---:|
| 生成时间 | 2026-11-18 13:35:45 |
| 操作系统 | Windows-11-10.0.26200-SP0 |
| CPU | Snapdragon (TM) 8cx Gen 3 @ 3.0 GHz |
| GPU / 渲染后端 | Virtual Display Device · OpenGL 3.3 Core (offscreen FBO, Mesa software rasteriser) |
| Python | 3.13.12 |
| numpy / matplotlib / Pillow | 2.5.4 / 3.11.2 / 13.0.0 |
| 算法版本 | sdr-srgb-v2 |
| 渲染 worker | `build-arm64\Debug\render_worker.exe`（1,235,456 B，2026-10-20 13:09:38） |
| 采样策略 | 每种配置预热 1 次 + 连续测量 5 次，报告均值与 P95 |

原报告表块 2：

| 分辨率 | MP | CPU 均值 (ms) | CPU P95 (ms) | GPU 端到端 (ms) | GPU P95 (ms) | GPU 着色+回读 (ms) | 进程/IO 开销 (ms) | 端到端加速比 | 纯着色加速比 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1080p (1920x1080) | 2.07 | 2797.3 | 2804.4 | 1383.4 | 1510.9 | 22.0 | 1361.4 | **2.02×** | 126.9× |
| 2K (2560x1440) | 3.69 | 4643.8 | 4938.4 | 1326.9 | 1406.3 | 34.7 | 1292.2 | **3.50×** | 134.0× |
| 4K (3840x2160) | 8.29 | 11112.1 | 11198.1 | 1393.2 | 1420.4 | 45.8 | 1347.4 | **7.98×** | 242.8× |

原报告表块 3：

| 尺寸 | 顶点数 | PSNR (dB) | MAE (/255) | 最大绝对误差 | ΔE76 均值 / 最大 | ΔE00 均值 / P95 / 最大 | 烘焙 (ms) | Base64 (KB) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 17³ | 4,913 | 53.57 | 0.200 | 4 | 0.260 / 2.64 | 0.127 / 0.510 / 2.15 | 5.1 | 77 |
| 33³ | 35,937 | 60.07 | 0.054 | 2 | 0.077 / 1.95 | 0.038 / 0.297 / 1.58 | 37.0 | 562 |
| 65³ | 274,625 | 67.71 | 0.011 | 1 | 0.017 / 1.45 | 0.009 / 0.000 / 1.08 | 341.3 | 4,291 |

原报告表块 4：

| 预设 | 尺寸 | 插值 | 色偏均值 C*ab | 色偏最大 C*ab | ΔE00 均值 | ΔE00 最大 |
|---|---:|---:|---:|---:|---:|---:|
| cinematic | 17³ | 三线性 | 3.8267 | 6.4096 | 0.1785 | 1.009 |
| cinematic | 17³ | 四面体 | 3.8251 | 6.4096 | 0.1897 | 1.009 |
| cinematic | 33³ | 三线性 | 3.8491 | 6.4096 | 0.0532 | 0.915 |
| cinematic | 33³ | 四面体 | 3.8508 | 6.4096 | 0.0573 | 0.915 |
| tetra_stress | 17³ | 三线性 | 10.6816 | 30.8358 | 0.9022 | 10.849 |
| tetra_stress | 17³ | 四面体 | 10.7656 | 30.9357 | 0.9345 | 10.798 |
| tetra_stress | 33³ | 三线性 | 10.3037 | 30.5106 | 0.4686 | 10.836 |
| tetra_stress | 33³ | 四面体 | 10.3288 | 30.5106 | 0.4580 | 10.655 |

原报告表块 5：

| 预设 | 尺寸 | 插值 | PSNR (dB) | MAE (/255) | ΔE00 均值 | ΔE00 最大 |
|---|---:|---:|---:|---:|---:|---:|
| cinematic | 17³ | 三线性 | 53.572 | 0.2000 | 0.1269 | 2.149 |
| cinematic | 17³ | 四面体 | 53.675 | 0.1975 | 0.1272 | 2.149 |
| cinematic | 33³ | 三线性 | 60.069 | 0.0545 | 0.0376 | 1.579 |
| cinematic | 33³ | 四面体 | 60.135 | 0.0539 | 0.0376 | 1.579 |
| tetra_stress | 17³ | 三线性 | 37.528 | 1.3007 | 0.6392 | 17.671 |
| tetra_stress | 17³ | 四面体 | 37.625 | 1.2550 | 0.6299 | 17.376 |
| tetra_stress | 33³ | 三线性 | 45.066 | 0.4571 | 0.2397 | 10.050 |
| tetra_stress | 33³ | 四面体 | 45.135 | 0.4448 | 0.2367 | 9.233 |

原报告表块 6：

| 预设 | 尺寸 | 灰轴色偏下降 | 灰轴 ΔE00 下降 | 扫卡 PSNR 增益 | 扫卡 ΔE00 下降 |
|---|---:|---:|---:|---:|---:|
| cinematic | 17³ | +0.04% | -6.27% | +0.1030 dB | -0.24% |
| cinematic | 33³ | -0.04% | -7.71% | +0.0660 dB | +0.00% |
| tetra_stress | 17³ | -0.79% | -3.58% | +0.0970 dB | +1.45% |
| tetra_stress | 33³ | -0.24% | +2.26% | +0.0690 dB | +1.25% |

原报告表块 7：

| 方案 | SSIM | 亮度均值 | 对比度 σ | 信息熵 (bit) | 色彩丰富度 | clip_low (%) | clip_high (%) |
|---|---:|---:|---:|---:|---:|---:|---:|
| 原图 (Original) | 1.0000 | 117.06 | 50.69 | 5.620 | 32.75 | 0.10 | 0.87 |
| 暖色 (`warm`) | 0.9871 | 123.70 | 50.97 | 5.577 | 41.19 | 0.00 | 0.00 |
| 冷色 (`cool`) | 0.9866 | 116.05 | 48.02 | 5.532 | 33.43 | 0.00 | 0.00 |
| 柔和 (`soft`) | 0.9463 | 126.39 | 45.43 | 5.405 | 32.09 | 0.00 | 0.00 |
| 电影感 (`cinematic`) | 0.9797 | 119.02 | 47.40 | 5.486 | 37.83 | 0.00 | 0.00 |
| 黑白 (`mono`) | 0.9906 | 118.39 | 53.55 | 5.658 | 0.00 | 1.41 | 0.86 |

原报告表块 8：

| 基准图 | 预设 | SSIM | 亮度均值 | 信息熵 | 色彩丰富度 | clip_low (%) | clip_high (%) |
|---|---:|---:|---:|---:|---:|---:|---:|
| 夹具图 scene.jpg | 暖色 | 0.9876 | 146.91 | 4.367 | 14.04 | 0.00 | 0.00 |
| 欠曝暗调 | 暖色 | 0.9812 | 50.50 | 6.205 | 12.66 | 0.00 | 0.00 |
| 低对比灰雾 | 暖色 | 0.9977 | 150.84 | 4.914 | 4.37 | 0.00 | 0.00 |
| 高饱和风景 | 暖色 | 0.9979 | 132.83 | 4.791 | 140.64 | 0.00 | 0.00 |
| 肤色渐变 | 暖色 | 0.9979 | 145.75 | 6.764 | 56.67 | 0.00 | 0.00 |
| 高动态范围建筑 | 暖色 | 0.9601 | 115.39 | 6.421 | 18.78 | 0.00 | 0.00 |
| 夹具图 scene.jpg | 冷色 | 0.9889 | 138.70 | 4.510 | 11.42 | 0.00 | 0.00 |
| 欠曝暗调 | 冷色 | 0.9820 | 47.40 | 5.985 | 8.97 | 0.00 | 0.00 |
| 低对比灰雾 | 冷色 | 0.9995 | 140.74 | 4.943 | 7.78 | 0.00 | 0.00 |
| 高饱和风景 | 冷色 | 0.9988 | 124.32 | 4.750 | 125.84 | 0.00 | 0.00 |
| 肤色渐变 | 冷色 | 0.9993 | 135.97 | 6.703 | 38.87 | 0.00 | 0.00 |
| 高动态范围建筑 | 冷色 | 0.9513 | 109.18 | 6.301 | 7.70 | 0.00 | 0.00 |
| 夹具图 scene.jpg | 柔和 | 0.9405 | 149.77 | 4.040 | 9.10 | 0.00 | 0.00 |
| 欠曝暗调 | 柔和 | 0.8827 | 62.67 | 6.101 | 7.63 | 0.00 | 0.00 |
| 低对比灰雾 | 柔和 | 0.9988 | 147.09 | 4.662 | 2.75 | 0.00 | 0.00 |
| 高饱和风景 | 柔和 | 0.9973 | 133.39 | 4.618 | 116.77 | 0.00 | 0.00 |
| 肤色渐变 | 柔和 | 0.9924 | 145.30 | 6.614 | 43.87 | 0.00 | 0.00 |
| 高动态范围建筑 | 柔和 | 0.8660 | 120.12 | 6.394 | 12.41 | 0.00 | 0.00 |
| 夹具图 scene.jpg | 电影感 | 0.9798 | 138.61 | 4.413 | 17.52 | 0.00 | 0.00 |
| 欠曝暗调 | 电影感 | 0.9678 | 50.16 | 5.995 | 14.18 | 0.00 | 0.00 |
| 低对比灰雾 | 电影感 | 0.9991 | 146.32 | 4.882 | 3.50 | 0.00 | 0.00 |
| 高饱和风景 | 电影感 | 0.9990 | 128.53 | 4.742 | 121.76 | 0.00 | 0.00 |
| 肤色渐变 | 电影感 | 0.9989 | 139.76 | 6.658 | 48.94 | 0.00 | 0.00 |
| 高动态范围建筑 | 电影感 | 0.9334 | 110.72 | 6.228 | 21.09 | 0.00 | 0.00 |
| 夹具图 scene.jpg | 黑白 | 0.9909 | 141.84 | 4.468 | 0.00 | 0.43 | 4.04 |
| 欠曝暗调 | 黑白 | 0.9829 | 40.72 | 6.210 | 0.00 | 0.00 | 0.00 |
| 低对比灰雾 | 黑白 | 0.9972 | 148.44 | 5.078 | 0.00 | 0.00 | 0.00 |
| 高饱和风景 | 黑白 | 0.9967 | 128.69 | 4.959 | 0.00 | 0.00 | 0.00 |
| 肤色渐变 | 黑白 | 0.9965 | 141.25 | 6.843 | 0.00 | 0.00 | 0.00 |
| 高动态范围建筑 | 黑白 | 0.9792 | 109.41 | 6.392 | 0.00 | 8.04 | 1.09 |

原报告表块 9：

| Provider | 样本数 | Schema 一次通过 | 触达量程边界 | 方向一致性 | 平均延迟 (ms) | P95 延迟 (ms) |
|---|---:|---:|---:|---:|---:|---:|
| offline / template+rules | 24 | 100.00% | 62.50% | **100.00%** | 0.47 | 1.21 |
| deepseek / deepseek-flash | 24 | 100.00% | 62.50% | **100.00%** | 1885.67 | 2784.91 |

原报告表块 10：

| Provider | 指令族 | 条数 | 方向一致性 | 平均延迟 (ms) |
|---|---:|---:|---:|---:|
| offline | 单维微调 | 6 | 100.0% | 0.47 |
| offline | 复合氛围 | 6 | 100.0% | 1.14 |
| offline | 增量微调 | 4 | 100.0% | 0.20 |
| offline | 极端/边界 | 4 | 100.0% | 0.15 |
| offline | 无关噪声 | 4 | 100.0% | 0.08 |
| deepseek | 单维微调 | 6 | 100.0% | 1523.93 |
| deepseek | 复合氛围 | 6 | 100.0% | 1599.60 |
| deepseek | 增量微调 | 4 | 100.0% | 1866.66 |
| deepseek | 极端/边界 | 4 | 100.0% | 2104.06 |
| deepseek | 无关噪声 | 4 | 100.0% | 2657.98 |

原报告表块 11：

| 编号 | 指令 | 期望方向 | offline 结果 | deepseek 结果 | 错误 |
|---|---:|---:|---:|---:|---:|
| S1 | 把画面整体调亮一点 | 曝光上升 | PASS | PASS | - |
| S2 | 画面太亮了，帮我压暗一些 | 曝光下降 | PASS | PASS | - |
| S3 | 增加一点对比度 | 对比度上升 | PASS | PASS | - |
| S4 | 把饱和度降下来一点 | 饱和度下降 | PASS | PASS | - |
| S5 | 整体调得偏暖一些 | 色温上升 | PASS | PASS | - |
| S6 | 把高光压一压 | 高光下降 | PASS | PASS | - |
| M1 | 黄昏暖调，同时压住高光 | 色温上升 + 高光下降 | PASS | PASS | - |
| M2 | 清冷通透的日系氛围 | 色温下降 + 曝光上升 | PASS | PASS | - |
| M3 | 电影感的青橙色调 | 分离色调双侧着色 | PASS | PASS | - |
| M4 | 黑白纪实风格，加强对比 | 饱和度归零 + 对比度上升 | PASS | PASS | - |
| M5 | 柔和低对比的雾面感 | 对比度下降 | PASS | PASS | - |
| M6 | 鲜艳浓郁的风光大片 | 色彩浓度上升（饱和度或自然饱和度） | PASS | PASS | - |
| I1 | 再暖一点 | 在当前暖色基础上色温继续上升 | PASS | PASS | - |
| I2 | 高光再压一点 | 在当前基础上高光继续下降 | PASS | PASS | - |
| I3 | 饱和度再高一些 | 在当前基础上饱和度继续上升 | PASS | PASS | - |
| I4 | 对比再强一点 | 在当前基础上对比度继续上升 | PASS | PASS | - |
| X1 | 曝光拉到最亮 | 曝光接近 +2 EV 上界 | PASS | PASS | - |
| X2 | 饱和度全部去掉，越灰越好 | 饱和度贴近 -100 下界 | PASS | PASS | - |
| X3 | 色温调到最冷 | 色温贴近 -100 下界 | PASS | PASS | - |
| X4 | 对比度拉到极限 | 对比度贴近 +100 上界 | PASS | PASS | - |
| N1 | 帮我写个冒泡排序 | 参数保持不变 | PASS | PASS | - |
| N2 | 今天天气怎么样 | 参数保持不变 | PASS | PASS | - |
| N3 | 1+1 等于几 | 参数保持不变 | PASS | PASS | - |
| N4 | 把这段文字翻译成英文 | 参数保持不变 | PASS | PASS | - |

原报告表块 12：

| 指令族 | 条数 | 优化前（纯模板） | 优化后（模板 + 规则） | 提升 |
|---|---:|---:|---:|---:|
| 单维微调 | 6 | 16.7% | 100.0% | +83.3 pp |
| 复合氛围 | 6 | 100.0% | 100.0% | +0.0 pp |
| 增量微调 | 4 | 0.0% | 100.0% | +100.0 pp |
| 极端/边界 | 4 | 0.0% | 100.0% | +100.0 pp |
| 无关噪声 | 4 | 100.0% | 100.0% | +0.0 pp |
| **合计** | **24** | **45.83%** | **100.00%** | **+54.17 pp** |

指标计算的关键源码原文（D65矩阵、CIEDE2000、SSIM/熵/丰富度），避免论文使用与实验实现不同的标准库默认参数：

源码：`tools/benchmark/metrics.py:1`。

```python
"""Colour-science and image-quality metrics, implemented with numpy only.

Everything here is deterministic and dependency-light on purpose: the benchmark
must run inside the project venv without pulling in OpenCV or scikit-image.

Reference formulas
------------------
* sRGB -> linear -> XYZ (IEC 61966-2-1, D65)
* XYZ -> CIELAB (CIE 1976 L*a*b*)
* CIEDE2000 (CIE 2000 colour-difference formula, kL = kC = kH = 1)
* PSNR / MAE on 8-bit encoded sRGB
* SSIM (Wang et al. 2004), uniform 8x8 window, luma channel
* Shannon entropy over the 256-bin luma histogram
* Hasler & Suesstrunk (2003) colourfulness
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

# sRGB (linear) -> XYZ, D65.
_M_RGB_TO_XYZ = np.array(
    [
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ],
    dtype=np.float64,
)
_WHITE_D65 = np.array([0.95047, 1.00000, 1.08883], dtype=np.float64)
_EPSILON = 216.0 / 24389.0
_KAPPA = 24389.0 / 27.0
_LUMA_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float64)


def srgb_to_linear(encoded: np.ndarray) -> np.ndarray:
    """Decode encoded sRGB in [0, 1] to linear light."""
    c = np.asarray(encoded, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_xyz(linear_rgb: np.ndarray) -> np.ndarray:
    return np.asarray(linear_rgb, dtype=np.float64) @ _M_RGB_TO_XYZ.T


def _f(t: np.ndarray) -> np.ndarray:
    return np.where(t > _EPSILON, np.cbrt(t), (_KAPPA * t + 16.0) / 116.0)


def xyz_to_lab(xyz: np.ndarray) -> np.ndarray:
    scaled = np.asarray(xyz, dtype=np.float64) / _WHITE_D65
    fx, fy, fz = _f(scaled[..., 0]), _f(scaled[..., 1]), _f(scaled[..., 2])
    return np.stack(
        [116.0 * fy - 16.0, 500.0 * (fx - fy), 200.0 * (fy - fz)], axis=-1
    )


def srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    """Convert encoded sRGB in [0, 1] (..., 3) to CIELAB (D65)."""
    c = np.clip(np.asarray(rgb, dtype=np.float64), 0.0, 1.0)
    return xyz_to_lab(linear_to_xyz(srgb_to_linear(c)))


def srgb8_to_lab(rgb: np.ndarray) -> np.ndarray:
    return srgb_to_lab(np.asarray(rgb, dtype=np.float64) / 255.0)


def luma(rgb: np.ndarray) -> np.ndarray:
    """Encoded-domain luma proxy, identical to the engine's weighting."""
    return np.asarray(rgb, dtype=np.float64) @ _LUMA_WEIGHTS


def chroma(lab: np.ndarray) -> np.ndarray:
    """CIELAB chroma C*ab = sqrt(a*^2 + b*^2)."""
    arr = np.asarray(lab, dtype=np.float64)
    return np.hypot(arr[..., 1], arr[..., 2])


def delta_e76(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIE76 colour difference (Euclidean distance in CIELAB)."""
    diff = np.asarray(lab1, dtype=np.float64) - np.asarray(lab2, dtype=np.float64)
    return np.sqrt(np.sum(diff * diff, axis=-1))


def delta_e00(lab1: np.ndarray, lab2: np.ndarray) -> np.ndarray:
    """CIEDE2000 colour difference, vectorised over (..., 3) CIELAB arrays."""
    lab1 = np.asarray(lab1, dtype=np.float64)
    lab2 = np.asarray(lab2, dtype=np.float64)
    l1, a1, b1 = lab1[..., 0], lab1[..., 1], lab1[..., 2]
    l2, a2, b2 = lab2[..., 0], lab2[..., 1], lab2[..., 2]

    c1 = np.hypot(a1, b1)
    c2 = np.hypot(a2, b2)
    c_bar = 0.5 * (c1 + c2)
    c_bar7 = c_bar**7
    g = 0.5 * (1.0 - np.sqrt(c_bar7 / (c_bar7 + 25.0**7)))

    a1p = (1.0 + g) * a1
    a2p = (1.0 + g) * a2
    c1p = np.hypot(a1p, b1)
    c2p = np.hypot(a2p, b2)

    h1p = np.where(c1p > 0.0, np.degrees(np.arctan2(b1, a1p)) % 360.0, 0.0)
    h2p = np.where(c2p > 0.0, np.degrees(np.arctan2(b2, a2p)) % 360.0, 0.0)

    dlp = l2 - l1
    dcp = c2p - c1p
    zero_chroma = (c1p * c2p) == 0.0
    dh = h2p - h1p
    dh = np.where(dh > 180.0, dh - 360.0, np.where(dh < -180.0, dh + 360.0, dh))
    dhp = np.where(zero_chroma, 0.0, dh)
    dhp_big = 2.0 * np.sqrt(c1p * c2p) * np.sin(np.radians(dhp) / 2.0)

    l_bar_p = 0.5 * (l1 + l2)
    c_bar_p = 0.5 * (c1p + c2p)
    h_sum = h1p + h2p
    h_bar_p = np.where(
        zero_chroma,
        h_sum,
        np.where(
            np.abs(h1p - h2p) <= 180.0,
            0.5 * h_sum,
            np.where(h_sum < 360.0, 0.5 * (h_sum + 360.0), 0.5 * (h_sum - 360.0)),
        ),
    )

    t = (
        1.0
        - 0.17 * np.cos(np.radians(h_bar_p - 30.0))
        + 0.24 * np.cos(np.radians(2.0 * h_bar_p))
        + 0.32 * np.cos(np.radians(3.0 * h_bar_p + 6.0))
        - 0.20 * np.cos(np.radians(4.0 * h_bar_p - 63.0))
    )
    d_theta = 30.0 * np.exp(-(((h_bar_p - 275.0) / 25.0) ** 2))
    c_bar_p7 = c_bar_p**7
    r_c = 2.0 * np.sqrt(c_bar_p7 / (c_bar_p7 + 25.0**7))
    s_l = 1.0 + (0.015 * (l_bar_p - 50.0) ** 2) / np.sqrt(
        20.0 + (l_bar_p - 50.0) ** 2
    )
    s_c = 1.0 + 0.045 * c_bar_p
    s_h = 1.0 + 0.015 * c_bar_p * t
    r_t = -np.sin(np.radians(2.0 * d_theta)) * r_c

    term_l = dlp / s_l
    term_c = dcp / s_c
    term_h = dhp_big / s_h
    squared = term_l**2 + term_c**2 + term_h**2 + r_t * term_c * term_h
    return np.sqrt(np.maximum(squared, 0.0))


@dataclass(frozen=True)
class DeltaEStats:
    mean: float
    max: float
    p95: float


def delta_e_stats(lab1: np.ndarray, lab2: np.ndarray, *, ciede2000: bool) -> DeltaEStats:
    diff = delta_e00(lab1, lab2) if ciede2000 else delta_e76(lab1, lab2)
    flat = np.asarray(diff, dtype=np.float64).ravel()
    if flat.size == 0:
        return DeltaEStats(0.0, 0.0, 0.0)
    return DeltaEStats(
        mean=float(flat.mean()),
        max=float(flat.max()),
        p95=float(np.percentile(flat, 95.0)),
    )


def psnr_uint8(reference: np.ndarray, test: np.ndarray) -> float:
    """PSNR in dB for 8-bit images (identical inputs -> 100.0 sentinel)."""
    ref = np.asarray(reference, dtype=np.float64)
    cmp = np.asarray(test, dtype=np.float64)
    mse = float(np.mean((ref - cmp) ** 2))
    if mse <= 1e-12:
        return 100.0
    return float(10.0 * math.log10((255.0**2) / mse))


def psnr_unit(reference: np.ndarray, test: np.ndarray) -> float:
    """PSNR in dB for float images whose nominal peak is 1.0."""
    ref = np.asarray(reference, dtype=np.float64)
    cmp = np.asarray(test, dtype=np.float64)
    mse = float(np.mean((ref - cmp) ** 2))
    if mse <= 1e-15:
        return 100.0
    return float(10.0 * math.log10(1.0 / mse))


def mae_uint8(reference: np.ndarray, test: np.ndarray) -> float:
    ref = np.asarray(reference, dtype=np.float64)
    cmp = np.asarray(test, dtype=np.float64)
    return float(np.mean(np.abs(ref - cmp)))


def _box_mean(image: np.ndarray, window: int) -> np.ndarray:
    """Mean over a sliding window, 'valid' mode, via summed-area tables."""
    ii = np.pad(image, ((1, 0), (1, 0))).cumsum(axis=0).cumsum(axis=1)
    total = (
        ii[window:, window:]
        - ii[:-window, window:]
        - ii[window:, :-window]
        + ii[:-window, :-window]
    )
    return total / float(window * window)


def ssim(reference: np.ndarray, test: np.ndarray, window: int = 8) -> float:
    """Structural similarity on the luma channel, images in [0, 1] RGB."""
    x = np.clip(luma(np.asarray(reference, dtype=np.float64)), 0.0, 1.0)
    y = np.clip(luma(np.asarray(test, dtype=np.float64)), 0.0, 1.0)
    if x.ndim != 2:
        raise ValueError("ssim expects (H, W, 3) images")
    if min(x.shape) < window + 1:
        window = max(2, min(x.shape) - 1)

    mu_x = _box_mean(x, window)
    mu_y = _box_mean(y, window)
    mu_xx = mu_x * mu_x
    mu_yy = mu_y * mu_y
    mu_xy = mu_x * mu_y

    sigma_xx = _box_mean(x * x, window) - mu_xx
    sigma_yy = _box_mean(y * y, window) - mu_yy
    sigma_xy = _box_mean(x * y, window) - mu_xy

    c1 = 0.01**2
    c2 = 0.03**2
    numerator = (2.0 * mu_xy + c1) * (2.0 * sigma_xy + c2)
    denominator = (mu_xx + mu_yy + c1) * (sigma_xx + sigma_yy + c2)
    return float(np.mean(numerator / denominator))


def entropy_bits(rgb_uint8: np.ndarray) -> float:
    """Shannon entropy of the 256-bin luma histogram, in bits."""
    arr = np.asarray(rgb_uint8, dtype=np.float64) / 255.0
    luma_u8 = np.clip(np.rint(luma(arr) * 255.0), 0, 255).astype(np.uint8)
    counts = np.bincount(luma_u8.ravel(), minlength=256).astype(np.float64)
    total = counts.sum()
    if total <= 0.0:
        return 0.0
    p = counts[counts > 0.0] / total
    return float(-np.sum(p * np.log2(p)))


def mean_luma(rgb_uint8: np.ndarray) -> float:
    arr = np.asarray(rgb_uint8, dtype=np.float64) / 255.0
    return float(luma(arr).mean() * 255.0)


def contrast_std(rgb_uint8: np.ndarray) -> float:
    arr = np.asarray(rgb_uint8, dtype=np.float64) / 255.0
    return float(luma(arr).std(ddof=0) * 255.0)


def colorfulness(rgb_uint8: np.ndarray) -> float:
    """Hasler & Suesstrunk colourfulness metric (RGB in 0..255)."""
    arr = np.asarray(rgb_uint8, dtype=np.float64)
    red, green, blue = arr[..., 0], arr[..., 1], arr[..., 2]
    rg = red - green
    yb = 0.5 * (red + green) - blue
    std = math.sqrt(float(rg.var()) + float(yb.var()))
    mean = math.sqrt(float(rg.mean()) ** 2 + float(yb.mean()) ** 2)
    return float(std + 0.3 * mean)


def identity_psnr() -> float:
    return 100.0


__all__ = [
    "DeltaEStats",
    "chroma",
    "colorfulness",
    "contrast_std",
    "delta_e00",
    "delta_e76",
    "delta_e_stats",
    "entropy_bits",
    "identity_psnr",
    "linear_to_xyz",
    "luma",
    "mae_uint8",
    "mean_luma",
    "psnr_uint8",
    "psnr_unit",
    "srgb8_to_lab",
    "srgb_to_lab",
    "srgb_to_linear",
    "ssim",
    "xyz_to_lab",
]
```

### 6.11 论文/答辩可以主张与需要保留的限制

可以主张：实现了可复现16参数解析式与3D LUT离散化；后端OpenGL离屏应用与文件协议隔离；浏览器WebGL2三阶段空间Bloom、视频纹理实时调色、动态原图对照、离屏直方图和17³交互点云；在线结构化意图+确定性离线规则；在明确样本/机器下完成五维实验和214项Python测试。

需要明示：当前C++实际64×64隐藏窗口且未强制core profile；Python基础明暗是平方遮罩而非Smoothstep，饱和度不是HSL，split染色不严格保亮度；Bloom是额外空间后处理，不可编码进普通3D LUT，且当前导出没有应用它；Web外部cube导出与非默认domain有接口缺口；StateStore/DocumentSession快照不是完整工程历史；参考素材协调是占位；阶段七存在跳过/手工项且未保存Bloom FPS；gl_context元数据为固定标签，不能证明独立显卡加速。保留这些限制比将历史“全部完成”当作所有分支已验证更符合论文可查证要求。

如后续补实验，应单独记录浏览器/驱动/分辨率/DPR/静图或视频/媒体fps/LUT大小/Bloom强度、预热/采样时长、主绘制与直方图频率、mean/P95 frame time和帧数，区分RAF回调、已解码新帧与真实完成帧。此处只是复现实验规范建议，不是本次新增实测结果。

### 6.12 源码零修改核对与指纹索引

以本次扫描开始保存的SHA256逐文件比对，`engine/shaders/baker/ai/api/app/frontend/tools/tests/schemas/presets`共114个非依赖/非构建文件内容未变。临时副本验证未写回原始runtime。下面给出核心源码哈希，后续论文引用时可确认版本；本次不创建计划文件、测试文件或其他仓库产物。

| 核心源码 | SHA256 |
| --- | --- |
| ai/__init__.py | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| ai/deepseek.py | 5ea063e54ab8b928d6714cc722be987429dd4330bd9b2153eac5a23aed0e71d0 |
| ai/offline.py | 3c27e8e1fda0916866a97b5da01e7fdeec25d6a5a2cccc885024f6b0f03467fe |
| ai/prompts.py | eb20d9467f7649a713af3aee122c988844b038e4a885d332e9e52d41476a8325 |
| ai/provider.py | 54eccab9c7e58462bd7e0371a147f1f5b0e6fb4de4024773edc2a437d6783073 |
| api/__init__.py | 39e0e3eb787798bde98e454336924ad06acf9781d02dea25296f947e58d28146 |
| api/envelope.py | 177806d03fe33ac1f03903787a5bd3678c3eef1424244bb6565b8b60421ee1f3 |
| api/job_runner.py | 0c7599e1eb336927f541e8770e00bd2d3ec7b267b832b27ee881191d3e97faf0 |
| api/media_store.py | 237e5139998bc01cb8daa569b101d6401255d2653adebc0749e66a59577c934e |
| api/server.py | de3e1fe9de6b398f51fad3f72545bd93a3650c91c4206f2fdea0281b7e26a452 |
| app/__init__.py | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| app/batch.py | 943394c9f1d22236856835afee0b3b256650ddc1edd32e32533cf6b0a65af308 |
| app/batch_export.py | fc21905a9082f1b72c4765d14b858682eb0d26c7bc16156f33b8b6ea471d6307 |
| app/batch_ui.py | 359f75ce8dd916b1e198acbd2851258a71c1677534ea56d3fc64b87934ce55bd |
| app/engine_client.py | 6c08b9ee2953a30c838eacd136cb1a0c69dc1f8ea1f54334c3a2762f8a912a59 |
| app/histogram.py | 353c80d25ac1e5fe620e5fb505383261996025bc67826e4cdb5c9bbc7ba42013 |
| app/image_io.py | 7a1a4587198a8a5aa6fe3fb9b31041dfe378095a2b13af338475750f0f8b4d67 |
| app/jobs.py | 01335db6cdf948581d2e43c397ddd0d4d9e8dfd36e51d3b067eb1c13a2566934 |
| app/main.py | 8bf6d6dc4b921aad14f2c76b440266814d8e43e3c39b1bbbb03a8f3d85b1ea42 |
| app/paths.py | d8135661188629f68833af9673e55f0a930501d6206122336a6ed810509b2112 |
| app/pipeline.py | 8cd31a85fd829cd8699d1407d2b47e4ab692b5ad6863867e2fe0a9f72f904c58 |
| app/session.py | fcca2bf4098a73688d69081c5b8d09a89b77c38572402c854b2f530f7a4410d0 |
| app/state.py | c25eafc4b0c42d68a866814cd4422deb4baae088ac3ceb5841a40a3584909fb6 |
| app/theme.py | 45c514bd9679c92767923732a2d454c959e3ef60639ce553daa54ba32cd353d1 |
| app/ui.py | 816f38748f294f02b88565e6180938959d22ad76df23a55548fc8006f53c4621 |
| app/video_io.py | 97f80ac1c6975a51a4b9d10aa1e5d557b865e8c9d7814e90109352b99c3056b6 |
| app/widgets.py | b7a4ed669612844acfb15099cd0138993c1d22f91f51cb6dc0f3d2ffca31f4a7 |
| baker/__init__.py | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| baker/color_transform.py | 9548a2c055a5d111677f13447271b4ef99431716b458342894da887dfd6b7932 |
| baker/cube_reader.py | 61da73191bb191ed92231323ec8fb4b680f36b5a64f98984c48447cc968322c0 |
| baker/cube_writer.py | 23ad5a94c9c3d619bc611ca49f04089448ff7926dac92955f042c06b85acbdfc |
| baker/params.py | 43390bd531802e4a093d6fd344d68467b762f09e05df69ce3b1d5fc18d0617b5 |
| engine/cube.cpp | 2393810496f18670c8997ba691890c07b3866e091262e5f7472c94c3ba1b7928 |
| engine/cube.h | b3adc3d593f178b25770303ab6586170f625f071ba437d1b2007a69a35c34871 |
| engine/gl_renderer.cpp | 28e7700e9eddd91d00ef76c638665ac7503af6aa56841d0924c51275e4d8319f |
| engine/gl_renderer.h | 00e4aeea50216b11b41d2733af848afe61c3864fc2b1ced39133fbc9163ebb75 |
| engine/json_lite.cpp | 6f970c4c5bc9527255365397ad6f2c326ac6b7f9dc8f77ed41a010bf3007e8f5 |
| engine/json_lite.h | cefbf8643f49f62de80c52c8a3a566481e92b27548793e298cedcabcfb523dea |
| engine/main.cpp | 014de63056baedbbf60a4f40182583e3720669bd3c6960688ae906a3fbcb85cf |
| engine/rgba_bridge.cpp | e7386bc83eae3acc48bd9220163cb709f1769c41378ae7b1f13903c0df65c022 |
| engine/rgba_bridge.h | a60c753072fb4e88f7f83fc009c3ba383cc5dcacfae54984f7a0b2dc64fd987c |
| frontend/src/app/workbench.ts | 7a5f8d3de6d2d420105457b007aee074022d9f27a64ac03dbe59075f8b344456 |
| frontend/src/components/histogram_view.ts | 808cb7d240e3da34aa3ca9ef52c76898f56aab9964805ea686fd1d5f5b567cf3 |
| frontend/src/components/icons.ts | 8968872a8f10941ea610e1da1a1f32a12ca2002b4e0c0aebc624c28eae49a8bd |
| frontend/src/components/media_stage.ts | 7fa7923a1fb2c9388587b8221db1642e5f38958219329bd3bc8b28967bb57141 |
| frontend/src/components/param_panel.ts | 329ba4e0e25929eaca913060e3223f90a924bcfe4af47c00a3c7505629a1a65f |
| frontend/src/components/preset_grid.ts | f7ac8913c6f7d1dbc8da6e7a82ee4b46cb81f3af951a3aedce6c448128a96f2c |
| frontend/src/components/rgb_wave_loader.ts | 6121b9cb1fc2bdce1b799eaa385ab3f91df6bda9c14471f3a6fc3cca28d2bd73 |
| frontend/src/components/top_toolbar.ts | 7d138c471f64cdab9a76f0fc51802bd7106cf5b78482d9f00abeadf3b6c26ed1 |
| frontend/src/components/viewport_hud.ts | d4db20b64a1efff5ba02a9c2ee8ea9c8b43ad8df4058fd75411affee99b7d9f4 |
| frontend/src/core/gl_viewport.ts | 368e7587e907384d615b44a77e05eab5c1d83fd7da69da6a089efbaf248facac |
| frontend/src/core/lut_cube_view.ts | 7aa474fc4def0d97cf75f858869040c2560d0676c7004a800cee3c0050b35d8a |
| frontend/src/core/params.ts | 934184ee2af24ba7b67f1a5b93970ccff06333db4bf2df31925f850166a16397 |
| frontend/src/core/state_store.ts | 6f99392d7412bacf77dc857970e3b8efe5a856f435243e4894855ffe631030a3 |
| frontend/src/main.ts | c04df202b82daee266e94b85bc3108047d77087ef74ca93ddd7975bba71613b9 |
| frontend/src/services/api_client.ts | 3ea57fb2b589894a4f76bba63344013a9671ab6627671f239082dae2eadbed84 |
| frontend/src/services/job_watch.ts | 0854f09e70ec488d8e750e1d48280d748067d1f46d11a8ad679810c1f9bfb6b6 |
| frontend/src/utils/debounce.ts | c8dd519e5c170f63292d653ad0e24c76fac5c11e2058bde40d6efe9b2e07e561 |
| frontend/src/vite-env.d.ts | 31ca7cf3c2b0cc3b2c0d73483c3bccef9784d2a813629285eb28f007bd66ca9b |
| shaders/fullscreen.vert | ee2351c4adfc6865465bc6b4e9e5ba6c336d4896c69008807b9c10f22890caeb |
| shaders/grade.frag | 1e954968dc208d9a9a11b8175528fc05ce0503b54d617df56ebded5fb567d18e |
| tests/__init__.py | e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 |
| tests/helpers.py | 2c30f96bb8611ca862dfa643d2566dfb5f7865594af09ad9f17312fc44ba7928 |
| tests/test_ai.py | b110fbf7d3819a3d3a1b1724bc1afc82b8098626438ad44c7e04b093cc9e9220 |
| tests/test_api.py | cadc9ee846ab2e23690f6bb6e4085a303e5236dcd3e041725ad97be81e9731d5 |
| tests/test_batch.py | da6486b9735ecbc0b0d5c7f03c977ca4bf442c9d30976b9527ed86d53665c78e |
| tests/test_batch_export.py | a3c6d56fb58104d0a5b9ad02fc38abe1af9caa1ef7c25ae9a1aaa040149e1007 |
| tests/test_color.py | dd744da5e4956e5414ab9dade6104d73bb9f35fdcafd0ffdc10c032012f42d21 |
| tests/test_cube.py | 2884fa1ec5375f7323f5b5288f24bd6764076d79b5cd67800e4dd2f431bd2bda |
| tests/test_engine.py | 1edd9f9fd9480db53f955c5da18d0b1eaa57c1706fb917f9f06b12cb2db69b4a |
| tests/test_histogram.py | 2bcb4242c92738652c24eb6a4143fb35fc28c2431bf42d38428b52fad2827bdf |
| tests/test_image_io.py | f3d20b218182aae13e6a942cfeab670a70789d2c273e7d5860703ab26d62b7d2 |
| tests/test_matrix.py | 777acd6b58dbcc3eba0b8c98b6ebbe362447e2dc7709b63e4926f14b2a86bf7a |
| tests/test_params.py | c800418169e45fdeabd9a66b7f7eccf72a3fd8f412b05c77bc2bec660a77d1a7 |
| tests/test_paths.py | 8ac01fa6d6967448804f08422ba9eb4dd5fb964d2d6d42bd84b876483e9d4348 |
| tests/test_session.py | e8d546bda54cc9ad7c2c82f426fa56a4b611c4f7d0d44c344a03181cd65620da |
| tests/test_video.py | d420f7f4efab25f8be3b7185dbb79ba99651f740e8d69215886e3f5378b88156 |
| tools/__init__.py | 0a6a5fa5dcfb9e36db6294a728e1406cada987322714063fe45b72c6500ebfc9 |
| tools/acceptance_stage6_histogram.py | c5b342c49f1e9627cddf1b6965a7dc9ac6d4096fbbf2f9dfa1604aaa652b9879 |
| tools/acceptance_stage7_matrix.py | b7889b965e3e8f9093ada698d540ecac6bcb54aa06ab2fb4b4b5bad529723682 |
| tools/benchmark/__init__.py | 5f4a5235419efc4f1c06adc08804996c7e56e1e3173166766192380937198df0 |
| tools/benchmark/common.py | 76d41ff6e9f9cc0658ef7f7e7dc8a2a871051705ce88ff8a12b9bffe00df1ae1 |
| tools/benchmark/dataset.py | be96160de08630f01c418814a008ef5c946fda274c5eb64b431a4209a9f19ce1 |
| tools/benchmark/dim1_speedup.py | 6d0abe63fed3c365fc5f81daed6ff16112f421ef85050e11a0056b175c466374 |
| tools/benchmark/dim2_lut.py | 0690e551105b879f9ded227043d8ec5d74b4f39728b13a979af662f440293577 |
| tools/benchmark/dim3_interp.py | 9ca2390a9effb52fc92c77b285146e7dca35dcb06665881c8fcadbd0478c349f |
| tools/benchmark/dim4_quality.py | 4d17a9cd514d679fb86e568ae94ccbd86b02ac8989c7f2737fe67f304149a898 |
| tools/benchmark/dim5_ai.py | 8b7dff9182ca342204c74eec25e8be7dc6276369c139ba41a8d6b18d32757f87 |
| tools/benchmark/interpolation.py | 9082a1c5fc0b228eac839060ffbb8816bc26a964d1960d4863817bfc09ed4c47 |
| tools/benchmark/metrics.py | 5b02791f6bddafceb6d7843149de874143cbea872083384e837985309e2b3a0b |
| tools/benchmark/report.py | 34b320ee1aced7df800b9c26538c78cdb6aa182bf840040a74105dbb515f57b9 |
| tools/benchmark/visualization.py | 67700a46e47fbc466e6298684386a087d006e89282f531fbb5bca8279de2876c |
| tools/check_config.py | bb0de767344799f825bbe4e7ce9c98a58c806d4cbafc8e8a5aed2b79ac7a0378 |
| tools/measure_large_image.py | 0c88ca5e64cb5af1a6423fe5eed2fcd1c6c3a34112f934dce9b0058b2afac412 |
| tools/measure_lut.py | b277c7e91382ce9ab1d86369708e3998b2107e7815bdfbc00dbcbaa73dc66fd6 |
| tools/run_benchmark.py | 48824443add27e3a874e6815af185929a1edea9cd42964f3c7d223ce53305dd4 |
