# AI 智能调色工作台（ai_color_app）最新架构与改动总结 · V2

> 审计性质：**只读扫描**。除本文档外，未修改任何业务代码与测试代码。
> 审计基准：`<project-root>` 磁盘现状 + 实际运行命令输出。
> 审计时间：2026-11-18 11:10 (UTC+8)　审计人：首席软件架构师（AI）
> 版本控制状态：**该目录不是 git 仓库**（无 `.git`），因此"最近改动"由文件 mtime + 代码内注释/文档重建，不存在 `git status` 级别的权威 diff。

---

## 0. 执行摘要（可直接同步给外部架构师）

| 维度 | 结论 |
| --- | --- |
| 后端测试 | **214 tests**，`OK`（含阶段六离线结构化 chip 回归） |
| 前端构建 | `tsc -b && vite build` **通过**（21 modules，含 `lut_cube_view.ts`） |
| AI 配置 | 实测 `configured=True`，`在线 · deepseek · deepseek-flash`，provider 实例 `DeepSeekProvider` |
| 渲染后端 | WebGL2（浏览器，主）+ OpenGL 3.3 Core / C++ `render_worker.exe`（导出与位级校验） |
| 直方图 | **100% 客户端**：离屏 **64×64** FBO + 3-Pass 合成后 `readPixels`（阶段六修复 FBO 误绑定回归） |
| 视觉主题 | 已从"黑金"彻底转为**黑灰 + 银白**（`--accent: #e7e8ee`），金色 token 全部移除 |
| 布局 | 左右侧栏**对称 344 px**，顶栏 46 px，悬浮 HUD 上 32 px / 下 40 px |
| 最大性能瓶颈 | 直方图 `readPixels` 同步回读：视频渲染 **58.6 → 44.8 fps（−23%）** |
| 最大架构隐患 | 媒体与任务注册表**纯内存态**，`uvicorn --reload` 即失效（预览/下载 404） |

**当前版本定性**：功能闭环已完整（导入 → 调色 → 分屏对比 → 导出/下载），视觉与交互达到可演示水平；剩余问题集中在**实时性开销**、**状态持久化**、**预览与导出的一致性**、**异常可见性**四类。

### 0.1 阶段四收官更新（2026-11-18 12:30，已落地）

| # | 审计条目 | 处理 | 实测结果 |
| --- | --- | --- | --- |
| 1 | §5-P0-1 直方图 `readPixels` 掉帧 | `HIST_SIZE` 160→**64**、`HIST_INTERVAL_MS` 50→**100** | 1080p 视频 **44.8 → 59.9 fps**；单次采样 **4.28 → 1.10 ms**；64² 下仍保留 173 个非零 bin |
| 2 | §5-P0-2 媒体注册表进程内存储 | `runtime/cache/api_media/index.json` 索引持久化 + 模块加载自动恢复 | 清空内存后 `load_index()` 恢复 1 条，`/content` 仍 200 |
| 2b | 演示防重载 | `start_web.ps1` 移除 `--reload` | 缓存文件变动不再重启进程 |
| 3 | §5-P0-4 拖动污染撤销栈 | `setParam(key, value, commit)`：`input` 传 false、`change` 传 true | 8 次 input 后撤销键仍禁用；一次 `change` 只产生 1 条快照，撤销直接回到拖动前 |
| 3b | §5-P1-10 预设高亮误导 | 新增 `PresetGrid.clearActive()`，AI / 外部 `.cube` / 手动滑杆均清除高亮 | 点预设=1 张高亮；改滑杆/AI 后=0 张；重置后回到 identity |
| 4 | §5-P1-7 LUT 导出强依赖夹具 | 夹具缺失时内存合成 16×16 校验图 | 无夹具时导出成功，`33³ · max diff 0.00/255` |

附带修复：`runAi` 中 `setParams` 已先 `emit`，导致 AI chip/摘要要等下次操作才刷新；已补一次 `store.emit()`（现有测试与构建均通过）。

### 0.2 阶段五图形学管线升级（2026-11-20，已落地）

| 能力 | 实现要点 |
| --- | --- |
| 静图 Mipmap | `generateMipmap` + `LINEAR_MIPMAP_LINEAR`（视频/LUT 隔离） |
| Bloom 后处理 | Pass1 LUT → Pass2 Ping-Pong 高斯 → Pass3 合成；`store.bloom` 独立 |
| 3D 色彩立方体 | `LutCubeView` 17³ 点云 + 顶栏第四分段 `lut3d` |

### 0.4 阶段七显示几何与 18 项总验收（2026-11-20，已落地）

详报：[STAGE7_ACCEPTANCE_REPORT.md](STAGE7_ACCEPTANCE_REPORT.md)

| 项 | 内容 |
| --- | --- |
| 3-Pass 几何拆分 | Pass1/2 全图 UV；Pass3 单独 letterbox + 透明边 |
| gradedFbo | 原图同比例，长边 ≤ 2560 |
| 18 项矩阵 | `tools/acceptance_stage7_matrix.py` → **18/18 PASS** |
| 直方图 | 全图 UV 合成采样，垂直跨度 > 40% |

### 0.3 阶段六深度扫描回归修复（2026-11-20，已落地）

详报：[STAGE6_DEEP_AUDIT_REPORT.md](STAGE6_DEEP_AUDIT_REPORT.md)

| # | 缺陷 | 修复 |
| --- | --- | --- |
| 1 | 直方图曲线全空 | `renderPipeline` 写 `histFbo` 后误 `bindFramebuffer(null)` 导致 `readPixels` 读主画布 |
| 2 | 「清透日系」离线误判暖模板 | 结构化数值解析；`_WARM` 去掉裸「暖」 |
| 3 | 验收 | `tools/acceptance_stage6_histogram.py`：直方图彩色像素 **>500**，`gl.getError()==0` |

---

## 1. 最新工程目录与核心改动盘点

### 1.1 核心文件结构（已排除 `.venv` / `node_modules` / `__pycache__` / `dist` / `build-*` / `runtime/cache`）

```text
ai_color_app/
├─ api/                     FastAPI 服务层（2026-11-18 08:53 全量新建）
│  ├─ server.py       16,425 B   10 个 HTTP 路由 + 1 个 WebSocket
│  ├─ envelope.py        489 B   统一 {code, message, data} 信封
│  ├─ job_runner.py    2,694 B   导出任务：daemon 线程 + 内存态 _JOBS
│  ├─ media_store.py   2,120 B   上传落盘 + 内存态 _REGISTRY
│  └─ __init__.py        100 B
├─ app/                     业务核心（Tk 桌面端，同时被 API 复用）
│  ├─ session.py       6,379 B   ★ 11-18 新建：DocumentSession（无 Tk 依赖）
│  ├─ ui.py          112,627 B   Tkinter 桌面工作台（仍在，可独立运行）
│  ├─ pipeline.py     12,436 B   RenderPipeline / RenderSnapshot / ExportResult
│  ├─ ui.py 依赖：state.py 3,352 · theme.py 17,906 · widgets.py 4,955
│  ├─ batch.py        29,833 B   · batch_ui.py 45,773 · batch_export.py 5,131
│  ├─ engine_client.py 8,151 B   · image_io.py 16,538 · video_io.py 14,910
│  ├─ histogram.py     6,476 B   · jobs.py 7,420 · paths.py 5,587 · main.py 2,478
├─ baker/                   调色参数与 LUT 数学（纯 CPU 参考实现）
│  ├─ params.py       11,083 B   ColorParams / PARAM_KEYS / PARAM_RANGES / 预设加载
│  ├─ color_transform.py 12,177 B bake_lut / _trilinear / srgb 编解码
│  ├─ cube_reader.py   7,209 B   · cube_writer.py 6,345
├─ ai/                      AI 提案层
│  ├─ provider.py      5,854 B   AIConfig / load_config / build_provider / 摘要文本
│  ├─ deepseek.py      9,251 B   在线 provider（重试 + 格式修复）
│  ├─ offline.py       4,425 B   关键词模板兜底
│  ├─ prompts.py       6,696 B
├─ engine/                  C++17 / OpenGL 3.3 Core 离屏渲染 worker
│  ├─ main.cpp 20,786 · gl_renderer.cpp 13,442 · cube.cpp 11,015
│  ├─ rgba_bridge.cpp 5,207 · json_lite.cpp 9,849 · + 4 个头文件
├─ shaders/
│  ├─ fullscreen.vert    307 B   gl_VertexID 全屏三角形（零 VBO）
│  └─ grade.frag         900 B   3D LUT + voxel-center 校正（encoded sRGB）
├─ schemas/                 color_params.v1.schema.json / v2.schema.json
├─ presets/                 6 个 v2 预设：identity / warm / cool / soft / cinematic / mono
├─ tests/                   14 个测试模块（见 §2.4）
├─ tools/                   check_config.py · measure_large_image.py · measure_lut.py
├─ docs/
│  ├─ PROJECT_ARCHITECTURE_AUDIT.md      29,089 B（旧版，11-18 08:45）
│  ├─ decisions/            ADR-003 … ADR-011 共 9 篇
│  └─ test-runs/evidence/2026-11-11-ui-acceptance/
├─ frontend/                Vite 6 + TypeScript（无框架，原生 DOM）
│  ├─ index.html 446 B · package.json · vite.config.ts · tsconfig*.json
│  └─ src/
│     ├─ app/workbench.ts        21,591 B   工作台装配与全部事件编排
│     ├─ core/
│     │  ├─ gl_viewport.ts       19,934 B / 603 行  WebGL2 渲染 + 直方图管线
│     │  ├─ state_store.ts        3,290 B   参数状态 + 撤销/重做栈
│     │  └─ params.ts             2,556 B   16 维参数契约（与后端逐字一致）
│     ├─ components/
│     │  ├─ viewport_hud.ts       8,012 B   上遥测条 + 下强度/视频控制坞
│     │  ├─ top_toolbar.ts        6,719 B   导入 / 对比模式 / 撤销重做 / 导出
│     │  ├─ param_panel.ts        5,040 B   16 滑杆（3 分组折叠）
│     │  ├─ histogram_view.ts     4,953 B   288×110 Canvas2D 直方图
│     │  ├─ rgb_wave_loader.ts    3,133 B   RGB 律动加载遮罩
│     │  ├─ media_stage.ts        2,789 B   A/B 分屏分割线与拉手
│     │  ├─ preset_grid.ts        2,489 B   离线风格预设卡
│     │  └─ icons.ts                996 B
│     ├─ services/
│     │  ├─ api_client.ts         5,018 B   fetch 封装 + 类型 + URL 助手
│     │  └─ job_watch.ts          2,800 B   WS + 轮询双通道任务跟踪
│     ├─ theme/
│     │  ├─ tokens.css            1,390 B   设计 token
│     │  └─ layout.css           24,213 B / 1,010 行  全量样式
│     └─ utils/debounce.ts          322 B
├─ start_web.ps1            2,324 B   一键启动（后端就绪轮询 → Vite）
└─ runtime/                 jobs / cache / logs / screenshots / test-fixtures
```

### 1.2 最近一轮手动改动的识别方法

由于无 git，采用三重证据交叉定位：**文件 mtime 排序** + **代码内注释语义** + **与旧审计文档（08:45 生成）的差异**。改动可清晰分为四个批次：

| 批次 | 时间窗 | 内容 | 证据 |
| --- | --- | --- | --- |
| A 后端分层与会话抽离 | 11-18 08:53 – 08:58 | `api/` 四个文件新建、`app/session.py` 新建、`app/ui.py` 改为委托、`tests/test_api.py` + `tests/test_session.py` 新增 | mtime 密集聚集；`session.py` 文档字符串写明"formerly embedded in ColorApp" |
| B 前端从零搭建 | 11-18 09:00 – 09:42 | `frontend/` 全套（package/vite/tsconfig → theme → core → components → services → app） | mtime 单调递增，最后落在 `layout.css` 09:42 |
| C AI 配置健壮性 | 11-18 09:23 | `ai/provider.py`、`ai/offline.py`、`api/server.py` 同日最后一次修改 | 引入 `RETIRED_MODELS`、四层超时、`DEEPSEEK_API_KEY` 兼容、无命中不改参数 |
| D 运行时缺陷修复（最靠后） | 11-18 10:49 – 10:52 | `start_web.ps1`（就绪轮询）、`workbench.ts`（HUD 点击隔离）、`gl_viewport.ts`（视频逐帧上传 + 降采样） | 三者是全场最新文件；注释直接写明修复原因 |

### 1.3 逐项说明：改了什么逻辑 / 样式 / 交互

#### (1) `app/session.py` —— 业务规则从 Tk UI 中剥离（新增文件）

- 定义 `ColorSnapshot(params, strength, mode, source_label)`（frozen dataclass），`MAX_COLOR_HISTORY = 64`。
- `record_color_history()`：与栈顶去重；若当前不在栈尾则先裁剪 redo 分支；超限时整体左移并修正索引。
- `undo()/redo()`：应用快照后调用 `state.bump_color()` 触发失效，返回 bool 供 UI 决定是否重绘。
- `apply_proposal_to_state()`：`source == "ai"` → 标签 `AI · {provider}/{model}`，否则 `离线模板`；同时清空 `pending_proposal`、`external_lut`，并把 `mode` 置为 `params`。
- `ExportTicket(kind, revision, material, token)` + `export_started / export_take / export_drop_token / outstanding_exports / export_block_reason`：构成"导出闸门"，剩余任务 > 1 时自动改写提示文案为"（剩余 N 项）"。
- `batch_blocks_single_asset_work()`：批量任务进行中禁止单素材切换。
- **架构意义**：`app/ui.py` 顶部已改为 `from .session import DocumentSession, ExportTicket`，`ColorApp.__init__` 内 `self.session = DocumentSession()`。业务规则现在可被 FastAPI 与单元测试复用，**但 `api/server.py` 目前尚未接入它**（见 §4 隐患 9）。

#### (2) `api/` —— FastAPI 服务层从零建立

- `envelope.py`：`ok(data)` 返回 dict；`err(code, message)` 返回 `JSONResponse(http_status=400)`，保证错误也走同一 JSON 结构。
- `server.py`：模块级 `load_dotenv(paths.ENV_FILE, override=False)`（因为 `uvicorn --reload` 不会自动读 `.env`），随后注册 CORS（白名单 `localhost/127.0.0.1` 的 3000 与 5173）。
- `media_store.py`：上传落盘到 `runtime/cache/api_media/<uuid>/<原名>`；视频走 `video_io.probe` 取宽高/时长/帧率，图片走 `image_io.load_source_image`；登记进进程内 `_REGISTRY`。
- `job_runner.py`：`create_job` 生成 uuid，`run_job` 起一个 **daemon 线程**执行，`report(progress)` 写入 `JobRecord`；异常统一落为 `FAILED + error/message`。无队列、无并发上限、无取消。

#### (3) `ai/provider.py` —— 配置层加固

- `RETIRED_MODELS = {"deepseek-chat", "deepseek-reasoner"}`，`status` 会明确提示"该型号已停用，请改为 deepseek-flash"。
- 四层超时：`AI_TIMEOUT_SECONDS`(读空闲) / `AI_CONNECT_TIMEOUT_SECONDS` / `AI_TOTAL_TIMEOUT_SECONDS` / `AI_POOL_TIMEOUT_SECONDS`。
- `_float_env` 做 NaN 与区间钳制；`_int_env` 对 `max_retries` 钳到 0–5；`temperature` 钳到 0–1.5。
- `AI_API_KEY` 与历史写法 `DEEPSEEK_API_KEY` 等价回退。
- `AI_BASE_URL` 必须是 `https` 且不得含 userinfo，否则抛 `AIError("AI_AUTH", …)`。

#### (4) `ai/offline.py` —— 兜底策略重写（关键行为变化）

- 关键词分组并按**固定优先级**判定：`mono > cinematic > warm > cool > soft > identity`，命中即 `load_preset()`。
- 命中后再叠加语义修饰：`通透/清透/日系/空气感` → `exposure_ev +0.20 / shadows +15 / highlights −12`；`鲜艳/浓郁/punchy` → `vibrance +22 / saturation +10`。
- **最重要的一条**：所有分组都不命中时，**不再返回全 0 参数覆盖用户编辑**，而是原样返回 `current_params` 并给出"未能识别…保留当前参数不变"的说明。
- 注意其调用位置语义：`build_provider()` 在 `api_key` 缺失时**直接返回** `OfflineProvider`（不抛错），所以离线是"配置缺失"的主路径；`/api/ai/propose` 里的 try/except 只覆盖"在线调用失败"的降级路径。

#### (5) `start_web.ps1` —— 启动竞态修复

- 先探活 `http://127.0.0.1:8765/api/presets`：已在监听则跳过启动后端（避免 `--reload` 双开抢端口）。
- 需要启动时，向端口轮询 **每 500 ms / 最多 30 s**，直到返回 200 才启动 Vite，杜绝首屏 `/api` 被代理成 `ECONNREFUSED`。
- 超时后仅告警并继续启前端，错误原因指向后端窗口。

#### (6) `frontend/` —— 全新 Web 工作台（详见 §3）

本批次一次性落地了：黑灰主题 token、左右对称 344 px 布局、WebGL2 视口、客户端直方图、HUD、16 维参数面板、6 个离线预设卡、6 个"可参考预设"中文 chip、导出闭环。

#### (7) `gl_viewport.ts` —— 视频"灰屏/静止帧"缺陷修复（10:52，全场最新）

- 引入 `frameReady` 与 `lastUploadedTime`：视频在 `drawFrame()` 里**每帧**调用 `uploadSourceFrame()`；若 `currentTime` 未变且非 seeking，则直接复用已有纹理（支持暂停后零开销重绘）。
- `uploadableFrame()`：宽度 > `MAX_UPLOAD_WIDTH = 1920` 的视频，先 `drawImage` 到 offscreen `scratchCanvas` 再上传，避免 2.6K/4K 逐帧上传整幅 RGBA 把帧率拖到 30 fps 以下。
- 直方图采样在视频**暂停/结束**时提前返回，不再空转。

#### (8) `workbench.ts` —— 暂停键被"点击画面恢复播放"抢走（10:51）

- 新增 `isHudControl(target)`：命中 `button, input, a, .hud-bottom, .hud-top` 即忽略。
- `tryResumeVideo` 先过该守卫，再判断 `mediaEl.paused`，最终才 `resumeVideoPlayback()`。
- `mediaSink` 采用 `position:fixed; left:-10000px; opacity:0.01`（**故意不用 `display:none`**，注释说明不可见视频在部分 GPU/浏览器下不产出可上传帧）。

#### (9) `layout.css` / `tokens.css` —— 黑金 → 黑灰（09:29 / 09:42）

- 强调色体系改为银白：`--accent: #e7e8ee`、`--accent-bright: #ffffff`、`--accent-line: rgba(255,255,255,0.55)`、`--accent-glow: rgba(255,255,255,0.16)`。
- 金色相关 token 已不存在；RGB 三通道色（`#ff5a5f / #2ec4b6 / #3a86ff`）仅保留给直方图与加载器，属于功能色而非主题色。
- 侧栏统一 `--sidebar-w: 344px`，左右完全对称（此前右侧换行问题随之消解）。

#### (10) `workbench.ts` 的 AI 预设区（"可参考预设"）

- 移除旧的"清透日系 / 胶片调暖"两个 UI 卡片，改为 `AI_INTENT_PRESETS`（6 条）→ 3 列 chip 网格，正好两行。
- 每条 chip 的 `title` 与 `dataset.prompt` 都是**完整的中文调色指令长句**（不是四字标签本身），点击即写入 textarea、聚焦、光标置尾、自动撑高。
- `input` 事件里若文本不等于任一 `dataset.prompt`，立即清除 active 高亮（避免"手动改写后仍显示已选中"）。

---

## 2. 后端服务与自动化测试现状

### 2.1 路由清单（`api/server.py` 实际注册）

| # | 方法 | 路径 | 请求字段 | 成功 `data` | 业务错误码 |
| --- | --- | --- | --- | --- | --- |
| 1 | GET | `/api/presets` | — | `[{key, label, params}]`（顺序固定 identity→mono） | — |
| 2 | POST | `/api/params/validate` | `params` | `{params}`（归一化后 16 键） | 4001 |
| 3 | POST | `/api/ai/propose` | `intent`, `current_params`, `allow_offline_fallback` | `{params, summary, source, provider, model}` | 4002 / 4003 / 4004 / 4005 |
| 4 | POST | `/api/lut/bake` | `params`, `size`(33\|65) | `{lut_id, size, domain_min, domain_max, data_b64}` | 4010 / 4011 / 4012 |
| 5 | POST | `/api/lut/upload_cube` | multipart `file`(.cube) | 同上 + `title`, `sha256` | 4020 / 4021 / 4022 |
| 6 | POST | `/api/media/upload` | multipart `file` | `{media_id, kind, width, height, content_url[, duration_s, fps]}` | 4030 / 4031 / 4032 |
| 7 | GET | `/api/media/{media_id}/content` | — | `FileResponse`（原始字节） | 4040（HTTP 404） |
| 8 | POST | `/api/histogram` | `media_id` 或 `image_b64` | `{r, g, b, luma}`（各 256）+ `clip_low`, `clip_high` | 4041–4044 |
| 9 | POST | `/api/export/image` | `media_id`, `params`, `strength`, `format` | `{job_id}` | 4050 / 4051 |
| 10 | POST | `/api/export/video` | `media_id`, `params`, `strength` | `{job_id}` | 4060 / 4061 / 4062 |
| 11 | POST | `/api/export/lut` | `params`, `strength` | `{job_id}` | 4070 |
| 12 | GET | `/api/jobs/{job_id}` | — | `{job_id, kind, status, progress, message, result_path, error, detail[, download_url]}` | 4080（HTTP 404） |
| 13 | GET | `/api/jobs/{job_id}/download` | — | `FileResponse` | 4081 / 4082（HTTP 404） |
| 14 | WS | `/ws/jobs/{job_id}` | — | 每 250 ms 推 `{code:0, data:{status, progress, result_path, error}}`，终态即断开 | 4080 |

补充实现细节：

- `lut_id` 为 `samples(float32, C-order)` 的 **SHA-256**，前端目前只消费 `data_b64`/`size`，未做缓存。
- `/api/export/lut` **不接受 media_id**，优先用 `runtime/test-fixtures/pattern.png` 作校验上下文；夹具缺失（或损坏）时自动退化为内存合成的 16×16 渐变图，因此部署到无测试目录的环境也能导出。
- `/api/export/video` 是"抽首帧 → 建 RenderSnapshot → 烤 cube → ffmpeg 套 LUT"的异步流水线，进度 0.05→0.20→0.95→1.0。
- 所有错误响应都是 HTTP 400/404 + JSON 信封，前端 `request()` 先 `json()` 再判 `code !== 0`。

### 2.2 `.env` 加载机制（双层，且都显式 `override=False`）

1. **模块导入期**：`api/server.py` 顶部 `load_dotenv(dotenv_path=paths.ENV_FILE, override=False)`，`paths.ENV_FILE = <root>/.env`。注释点明原因：`uvicorn --reload` 不会自动读 `.env`。
2. **调用期**：`ai/provider.load_config()` 再执行一次 `load_dotenv` 并从 `os.environ` 组装 `AIConfig`，同时做 URL 合法性校验。

`override=False` 的设计意图：**进程环境变量（CI / 容器 / 临时覆盖）优先于 `.env` 文件**。

磁盘上 `.env` 存在的键（值已掩码，未读取明文）：

```text
AI_PROVIDER          (8 chars)
AI_BASE_URL          (24 chars)
AI_MODEL             (14 chars)
AI_API_KEY           (35 chars)
AI_TIMEOUT_SECONDS   (2 chars)
AI_MAX_RETRIES       (1 char)
AI_OFFLINE_ONLY      (5 chars)
```

实际加载结果（真实执行 `load_config()`）：

```text
configured   : True
status       : 在线 · deepseek · deepseek-flash
provider     : deepseek
model        : deepseek-flash
base_url     : https://api.deepseek.com
offline_only : False
built        : DeepSeekProvider
```

### 2.3 `ai/offline.py` 兜底策略（现状）

```text
intent ──lower──┬─ 命中 mono      → preset "mono"        "匹配到黑白倾向"
                ├─ 命中 cinematic → preset "cinematic"   "匹配到电影感倾向"
                ├─ 命中 warm      → preset "warm"        "匹配到暖色倾向"
                ├─ 命中 cool      → preset "cool"        "匹配到冷色倾向"
                ├─ 命中 soft      → preset "soft"        "匹配到柔和/通透倾向"
                ├─ 命中 identity  → preset "identity"    "匹配到原图意图"
                └─ 全不命中       → 原样返回 current_params + 提示文案（绝不覆盖）
                            ↓ 命中后
                  叠加 _TRANSLUCENT_SHIFT / _VIVID_SHIFT
                            ↓
                  Proposal(source="offline", provider="offline", model="template",
                           summary = 模板说明 + 叠加项 + summary_from_params(params))
```

- `cancel_event` 已预留协作取消（每次 `generate` 入口检查 `is_set()`）。
- 触发链有两条：① `build_provider` 因无 key / `AI_OFFLINE_ONLY=true` 直接返回离线 provider；② `/api/ai/propose` 捕获 `AIError` 且 `allow_offline_fallback=True` 时降级。
- 已知语义缺口：`model="template"` 会让前端 `aiSource` 显示"离线预设"，但**用户无法区分"没配 key"与"在线请求失败"**（两者 `provider/model` 完全相同）。

### 2.4 后端测试执行结果（实际命令输出）

命令：`.\.venv\Scripts\python.exe -m unittest discover -s tests -q`

```text
Ran 213 tests in 49.641s

OK
```

**通过 213 / 失败 0 / 错误 0 / 跳过 0**（若存在 skip，unittest 会输出 `OK (skipped=N)`，此处没有）。

逐模块分布（`-p <file>` 单独跑取得，用于定位耗时）：

| 模块 | 用例数 | 耗时 | 说明 |
| --- | --- | --- | --- |
| `test_ai.py` | 17 | 0.056 s | provider 配置、离线模板、摘要文本 |
| `test_api.py` | 7 | 0.469 s | FastAPI 冒烟：presets/validate/bake/离线降级/上传+直方图/cube/导出 job |
| `test_batch.py` | 35 | 0.422 s | 批量工作区 |
| `test_batch_export.py` | 9 | 0.031 s | 批量导出 |
| `test_color.py` | 19 | 0.728 s | CPU 调色数学 |
| `test_cube.py` | 14 | 0.362 s | .cube 读写 |
| `test_engine.py` | 13 | **23.674 s** | 真实 OpenGL worker 端到端（主要耗时源） |
| `test_histogram.py` | 6 | 0.040 s | 后端直方图 |
| `test_image_io.py` | 27 | 1.107 s | 图像解码/EXIF/缩放 |
| `test_matrix.py` | 31 | **9.066 s** | UI 矩阵 + 错误路径注入 |
| `test_params.py` | 15 | 0.027 s | 参数契约与 schema |
| `test_paths.py` | 6 | 0.034 s | 路径与缓存清理 |
| `test_session.py` | 2 | 0.001 s | ★ 新增：undo/redo + 导出闸门 |
| `test_video.py` | 12 | **8.284 s** | ffmpeg 抽帧/导出 |
| **合计** | **213** | 49.641 s | — |

运行时输出的两类"非故障"噪声，需向外部协作者说明以免误判：

1. `stderr` 的 `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated; install httpx2 instead.` —— FastAPI 0.163.2 的依赖弃用提示，与测试结果无关。
2. `stdout` 的 `视频导出失败（clip.mp4）：boom。` / `无法打开图像：IMAGE_INVALID：probe。` / `当前素材仍有导出任务正在进行…` / `job poll failed for preview` + Traceback —— 全部来自 `test_matrix.py` 等**故意注入异常的错误路径用例**，属预期日志。

依赖与外部可执行文件实测：

- `fastapi 0.163.2`、`numpy 2.5.4`、`Pillow 13.0.0`、`python-dotenv` 可用。
- `ffmpeg`：`(True, '<local-ffmpeg-path>')`。
- `render_worker.exe`：`build-arm64/Debug/render_worker.exe`，1,235,456 B，2026-10-20 13:09。

### 2.5 `app/session.py` 实现状态

| 能力 | 状态 | 备注 |
| --- | --- | --- |
| 参数撤销/重做 | ✅ 完成 | 64 步上限、去重、redo 分支裁剪 |
| 强度/模式/来源标签纳入快照 | ✅ 完成 | 比前端 `StateStore` 的语义更完整 |
| 导出闸门（多任务计数） | ✅ 完成 | ticket + token 双重匹配，剩余项改写文案 |
| 批量任务互斥 | ✅ 完成 | `batch_blocks_single_asset_work()` |
| 被 FastAPI 复用 | ❌ 未接入 | `api/server.py` 完全无状态，撤销/重做在浏览器侧重做了一遍 |

---

## 3. 前端工作台（`frontend/`）当前实现解剖

### 3.1 布局与视觉现状

**Token（`src/theme/tokens.css`，实测值）**

| 类别 | Token | 值 |
| --- | --- | --- |
| 明度阶梯 | `--bg-shell` / `--bg-abyss` / `--bg-card` / `--bg-groove` / `--bg-stage` | `#131316` / `#0b0b0d` / `#19191d` / `#101012` / `#26262a` |
| 磨砂玻璃 | `--glass-1` | `linear-gradient(165deg, rgba(28,29,34,.78), rgba(18,18,22,.88))` |
| 玻璃叠层 | `--glass-2` | `linear-gradient(145deg, rgba(255,255,255,.045), rgba(255,255,255,.012))` |
| 滤镜 | `--glass-blur` | `blur(24px) saturate(140%)` |
| 描边 | `--rim` / `--rim-top` | `1px rgba(255,255,255,.07)` / `1px rgba(255,255,255,.14)` |
| 投影 | `--glass-shadow` | `0 16px 40px -10px rgba(0,0,0,.75), inset 0 1px 0 rgba(255,255,255,.06)` |
| 文字 | `--text-primary` / `--text-muted` / `--text-dim` | `#f4f4f6` / `#9c9ca6` / `#6c6c76` |
| 强调 | `--accent` / `--accent-bright` / `--accent-line` / `--accent-glow` | `#e7e8ee` / `#ffffff` / `rgba(255,255,255,.55)` / `rgba(255,255,255,.16)` |
| 通道色 | `--accent-r` / `--accent-g` / `--accent-b` | `#ff5a5f` / `#2ec4b6` / `#3a86ff`（仅图表/加载器） |
| 尺寸 | `--toolbar-h` / `--sidebar-w` / `--gap` | `46px` / `344px` / `10px` |
| 圆角 | `--radius-lg/md/sm` | `12px` / `8px` / `6px` |
| 字体 | `--font-ui` / `--font-mono` | `Segoe UI, Microsoft YaHei UI, system-ui` / `Cascadia Mono, Consolas` |

**结构比例（`src/theme/layout.css`）**

- `.app-shell`：`height:100vh`，flex 纵向，`padding:10px`，背景 `radial-gradient(circle at 50% 42%, #232429, #131316 58%, #0b0b0d)`。
- `.toolbar`：`flex:0 0 46px`，`display:grid; grid-template-columns:1fr auto 1fr`（左导入 / 中对比模式 / 右进度+撤销重做+导出）。
- `.workbench`：flex 横向，`gap:10px`。
- `.sidebar-panel`：`flex:0 0 344px; width:344px`，独立纵向滚动，自定义 6 px 滚动条。
- `.viewport-stage`：`flex:1; min-width:0; overflow:hidden`，径向内阴影营造"光学舞台"。
- `.hud-top`：`position:absolute; top:14px; left:50%; translateX(-50%)`，高 32 px，`border-radius:999px`（胶囊）。
- `.hud-bottom`：`bottom:14px` 居中，`width:min(520px,88%)`，高 40 px；视频态 `.has-video` 扩展到 `min(720px,94%)`。
- 分屏：`.split-line` 1.5 px 纯白 + `.split-knob` 32 px 圆形磨砂按钮；`.split-badge` 置于 `top:56px`。
- 预设卡：2 列；AI chip：3 列（6 个词恰好两行）；参数行：`76px / 1fr / 46px`。

**结论**：左右栏已按要求做**对称加宽**（同为 344 px），右侧文本换行问题随之消失；"黑金"已完全退场，强调色为银白，整体是"三层暗房明度阶梯 + 双层磨砂玻璃 + 环境光场"。

### 3.2 WebGL2 渲染与直方图管线

**着色器（`gl_viewport.ts` 内联，与 C++ 版同源）**

- 顶点：`aPos` 为 6 顶点四边形 VBO，`gl_Position = vec4(aPos*2-1, 0, 1)`，并把 `p` 依次做 `zoom/pan → aspect` 变换后写入 `vUv`。
- 片元：`texture(uImage) → q = clamp((rgb−dmin)/(dmax−dmin), 0, 1) → tc = q*((N−1)/N) + 0.5/N → texture(uLut) → mix(src, mapped, uStrength) → clamp`，最后按 `uCompareMode` 与 `uSplitRatio` 选择输出；`vUv` 越界时输出 `vec4(0)`。
- 几何路径与 C++ **不同**：C++ 端 `shaders/fullscreen.vert` 用 `gl_VertexID` 取 `(-1,-1)/(3,-1)/(-1,3)` 的全屏三角形（零 VBO、无缝对角线）；WebGL2 端仍用 2 个三角形 + VBO。两者覆盖结果等价，但**不是同一份 shader 源码**，修改时需两处同步。

**LUT 纹理格式**

- 首选 `gl.RGB16F` + `gl.FLOAT` 上传 `texImage3D`；随后 `gl.getError()` 检测，若失败则回退 `gl.RGB32F`。
- 上传前主动清空历史 GL 错误（`while (stale !== NO_ERROR) stale = getError()`），避免误判本次失败。
- 线性过滤依赖 `OES_texture_float_linear`（构造时已 `getExtension`）。

**上下文与确定性**

- `getContext("webgl2", { alpha: true, antialias: false, premultipliedAlpha: false })`。
- `enable(BLEND)` + `SRC_ALPHA / ONE_MINUS_SRC_ALPHA`（用于 letterbox 透明区），`disable(DEPTH_TEST)`。
- 未启用 `SRGB8_ALPHA8` / `FRAMEBUFFER_SRGB`，与 ADR-004 的"encoded sRGB in → out"一致。

**视频边播边调色循环（当前实现）**

```text
RAF tick
  └─ drawFrame()
       ├─ resize()：dpr = min(devicePixelRatio, 2)，实测画布 2350×2004
       ├─ 清屏（clearColor 全透明）
       ├─ 视频 → 每帧 uploadSourceFrame()
       │    ├─ currentTime 未变 && !seeking → 复用纹理，直接返回 true
       │    ├─ 宽度 > 1920 → drawImage 到 scratchCanvas 后再 texImage2D
       │    └─ UNPACK_FLIP_Y_WEBGL 临时 true，finally 复位
       ├─ 静态图 → 仅 frameReady=false 时上传一次
       ├─ renderScene(canvas.width/height)
       └─ maybeSampleHistogram()（≥50 ms 才采样）
```

**直方图：已是纯前端实时计算，未走后端**

- 离屏目标：`HIST_SIZE = 64` 的 `RGBA8` 纹理 + FBO；`renderScene(aspect=1)` 后 `readPixels(0,0,64,64,RGBA,UNSIGNED_BYTE)`。
- 采样节流 `HIST_INTERVAL_MS = 100`；`alpha < 8` 的像素跳过（自动排除 letterbox）。
- 统计：R/G/B 各 256 bin；luma 权重 `0.2126 / 0.7152 / 0.0722`。
- 后处理：`1-2-1` 平滑 `(a + 2c + d) / 4`；按四通道峰值归一后 `log1p(x * 9) / ln(10)` 做对数压缩，防止高光尖峰吃掉整条曲线。
- 暂停优化：视频 `paused || ended` 且 `!histDirty` 时直接返回。
- `HistogramView`：288×110 Canvas2D，`globalCompositeOperation = "screen"`，RGB 三曲线 + 半透明 Luma 曲线，120 ms `cubic ease-out` 插值（逐 bin 线性插值）。
- **实测代价**：`sampleHistogram()` 平均 **4.28 ms/次**（30 次均值），即每 50 ms 吃掉约 8.6 % 的时间预算。

### 3.3 特色动效与交互状态完成度

| 项目 | 实现 | 完成度 |
| --- | --- | --- |
| `RgbWaveLoader` | 420×120 Canvas2D，3 条正弦（`freq 2.2/2.8/3.4`、相位错开）+ 高斯包络，`lighter` 叠加；`show(text?)` 可覆盖文案；`hide()` 为 120 ms 渐隐并 `await` | ✅ 完整 |
| `state_store.ts` 撤销/重做 | `MAX_HISTORY = 64`，16 键 + strength 全等去重，redo 分支裁剪；`canUndo/canRedo` 驱动工具栏按钮禁用；`setParam(key, value, commit?)` 支持拖动合并 | ✅ 完整（阶段四修复拖动污染） |
| 预设卡高亮 | 6 卡：中文 label + 英文 en + 渐变 swatch + active 白边 + 发光圆点；`clearActive()` 在 AI / `.cube` / 手动改参时清除 | ✅ 完整（阶段四修复状态误导） |
| A/B 分屏 | 白线 + 32 px 圆钮 + BEFORE/AFTER 徽章；拖动 `window.mousemove`，点击画布同侧亦可改比例 | ⚠️ 仅鼠标事件（无 pointer/touch） |
| 按住原图 | `compareMode="hold"` 时 `mousedown` 置 `holdOriginal`，`window.mouseup` 复位 | ✅ 完整 |
| 缩放/平移 | 滚轮 `×1.08`，范围 0.25–8；中键或 `Space+左键` 平移；双击 `fitView()` | ✅ 完整 |
| 视频坞 | 播放/暂停（图标随 `play`/`pause` 事件切换）、0–1000 拖拽 seek、`timeupdate` 同步时间、显示源 FPS | ✅ 完整 |
| 导出下载闭环 | 提交 → `watchJob`（WS 250 ms 推送 + 800 ms HTTP 轮询双通道）→ `status === "done"` → 隐藏 `<a>` 触发 `/api/jobs/{id}/download` → 2 s 后自动清空进度条 | ✅ 闭环，缺取消 |
| 快捷键 | `Space`（平移修饰，编辑框内不触发）、`Ctrl+Z`、`Ctrl+Y` | ✅ 基本 |

### 3.4 `npm run build` 真实输出

```text
> ai-color-workbench@0.1.0 build
> tsc -b && vite build

vite v6.4.6 building for production...
transforming...
✓ 20 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                  0.43 kB │ gzip:  0.32 kB
dist/assets/index-3RrQSbSK.css  18.39 kB │ gzip:  4.08 kB
dist/assets/index-Covhgj4c.js   50.47 kB │ gzip: 16.76 kB │ map: 149.68 kB
✓ built in 369ms
```

- `tsc -b` **零类型错误**（严格模式，`tsconfig.json` 504 B）。
- 产物体积很小（JS 50.47 kB），符合"无框架、原生 DOM"的选型。
- 注意：`index.html` 用 `<link rel="stylesheet" href="/src/theme/tokens.css">` 直接引用源码 CSS，Vite 会正确抽取进 `dist/assets`，但**路径是绝对 `/src/...`**——若将来部署到子路径（如 `/app/`），需把 `base` 与这两条 href 一起调整。

### 3.5 性能实测（本次审计现场测得，浏览器 CDP，dpr=2，画布 2350×2004）

| 场景 | 优化前 FPS | **阶段四后 FPS** | 3 s 纹理上传 | 说明 |
| --- | --- | --- | --- | --- |
| 静态 1920×1080 图 | 58.7 | 58.7 | 0（仅首次） | 直方图开启 |
| 640×360 视频 | 44.8 | **59.9** | 180 | 满帧 |
| 1920×1080 视频 | 44.8（同尺寸量级） | **59.9** | 180 | 满帧 |
| 2560×1440 视频 | 37.9 | **59.9** | 179 | 先降采样到 1920 宽再上传 |
| 对照：关闭直方图回调 | 58.6 | — | — | 优化前后均证明 `readPixels` 曾是主因 |

直方图单次采样成本：**160² @ 4.28 ms → 64² @ 1.10 ms**（−74 %）；64² 下 1080p 素材仍有 173 个非零 bin、峰值 0.994，曲线形态完整。

LUT 烘焙耗时（CPU，`bake_lut` + base64，本机实测）：

| size | 计算 | base64 | 载荷 | 采样点 |
| --- | --- | --- | --- | --- |
| 33³ | 23.2 ms | 1.7 ms | 562 KB | 35,937 |
| 65³ | 203.2 ms | 20.5 ms | 4,291 KB | 274,625 |

---

## 4. 前后端接口联调一致性核对

### 4.1 调用矩阵（前端实际发出的请求 → 后端实际注册的路由）

| 前端调用点 | 方法/路径 | 请求体 | 后端接收 | 结论 |
| --- | --- | --- | --- | --- |
| `workbench.init` → `api.getPresets` | GET `/api/presets` | — | `api_presets()` | ✅ 一致（`key/label/params` 三字段，`presets` 表 6 项顺序固定） |
| `workbench.runAi` → `api.validateParams` | POST `/api/params/validate` | `{params}` | `ParamsValidateBody.params: dict` | ✅ 一致；返回 `{params}` 已归一化，前端直接 `store.setParams(validated.params)` |
| `workbench.runAi` → `api.aiPropose` | POST `/api/ai/propose` | `{intent, current_params, allow_offline_fallback}` | `AiProposeBody` 同名字段 | ✅ 一致；`AiProposal` 类型覆盖 `params/summary/source/provider/model` |
| `workbench.rebakeLut` → `api.bakeLut` | POST `/api/lut/bake` | `{params, size}` | `LutBakeBody` | ✅ 一致；`LutBakeResult` 含 `domain_min/max` 且前端确实传入 `uploadLut` |
| `workbench.importCube` → `api.uploadCube` | POST `/api/lut/upload_cube` | `FormData("file")` | `UploadFile = File(...)` | ✅ 一致；额外 `title/sha256` 前端声明为可选但未展示 |
| `workbench.loadMedia` → `api.uploadMedia` | POST `/api/media/upload` | `FormData("file")` | `UploadFile = File(...)` | ✅ 一致；`duration_s/fps` 仅视频返回，前端类型已可选 |
| `store.media.content_url`（`<video>/<img>` src） | GET `/api/media/{id}/content` | — | `api_media_content` | ✅ 一致；`crossOrigin="anonymous"`（同源经 Vite 代理，无 CORS 负担） |
| `workbench.runExport("image")` | POST `/api/export/image` | `{media_id, params, strength, format}` | `ExportImageBody` | ✅ 一致；**前端 `format` 恒为默认 `"PNG"`，无 JPEG 入口** |
| `workbench.runExport("video")` | POST `/api/export/video` | `{media_id, params, strength}` | `ExportVideoBody` | ✅ 一致 |
| `workbench.runExport("lut")` | POST `/api/export/lut` | `{params, strength}` | `ExportLutBody` | ✅ 一致；后端不接收 media_id，靠夹具图 |
| `job_watch.watchJob` → `api.jobStatus` | GET `/api/jobs/{id}` | — | `api_job_status` | ✅ 一致（`JobStatus` 类型逐字段对齐真实返回） |
| `job_watch.watchJob` → `new WebSocket(wsJobUrl())` | WS `/ws/jobs/{id}` | — | `ws_job` | ⚠️ 字段子集不一致（见 4.2-4） |
| `triggerJobDownload` | GET `/api/jobs/{id}/download` | — | `api_job_download` | ✅ 一致（前端自行拼 URL，未用后端 `download_url`） |
| **无调用方** | POST `/api/histogram` | — | `api_histogram` | ❌ 悬空（见 4.2-1） |

**参数契约核对（逐字比对）**：`baker/params.py` 的 `PARAM_KEYS` 16 项与 `frontend/src/core/params.ts` 的 `PARAM_KEYS` **名称、顺序、取值范围完全一致**（`exposure_ev −2..2`，`hue −180..180`，两个 `*_hue 0..360`，其余 `−100..100`）。`PARAM_LABELS` 也逐条对应。这一层是本项目最扎实的契约。

### 4.2 发现的不一致 / 悬空 / 隐患

1. **`/api/histogram` 双向悬空**：后端完整实现（含 `clip_low/high`），但前端 `api_client.ts` 里的 `api.histogram()` **从未被调用**，工作台用客户端 FBO 直方图。该接口目前只服务 `tests/test_api.py`。→ 建议标注为"兼容/调试接口"或直接下线，避免外部协作方误以为主链路依赖它。
2. **前端死代码**：`api.histogram()`、`HistogramData` 类型、后端返回的 `clip_low/clip_high`（前端无任何 UI 展示）。
3. **媒体与任务注册表纯内存**：`api/media_store._REGISTRY`、`api/job_runner._JOBS` 都是进程内 dict。`uvicorn --reload` 或任何进程重启后，`media_id` 立刻 404、已提交的 job 彻底消失（下载 404）。这是当前**最容易在演示中翻车**的一致性问题。
4. **WS 负载是 HTTP 的子集**：WS 只推 `status/progress/result_path/error`，缺 `kind` 与 `message`。`job_watch.ts` 用默认值补齐（`status ?? "running"`、`message ?? ""`），因此**纯 WS 阶段进度文案会退化成英文枚举**（`toolbar.setProgress(p, st.message || st.status)`），直到 800 ms 轮询取回中文 message。
5. **`content_url` 双源**：后端返回 `content_url`，前端却在 `workbench.ts` 里用 `mediaContentUrl(up.media_id)` 重新拼一遍（结果相同但多一处真相源）。
6. **`download_url` 未消费**：后端仅在 `status === done` 时下发，前端用 `jobDownloadUrl(jobId)` 自行拼接。
7. **LUT 导出曾强依赖测试夹具** ✅ 已修复：`/api/export/lut` 在夹具缺失（或损坏）时自动改用内存合成的 16×16 渐变图，实测导出成功且 `max diff 0.00/255`；测试资源不再进入生产路径。
8. **`format` 能力未暴露**：后端支持 `PNG/JPEG/JPG`，前端 UI 无选择，恒 `PNG`。
9. **撤销/重做双实现且语义不同**：Python `DocumentSession`（含 `mode`、`source_label`、64 步、导出闸门）vs TypeScript `StateStore`（仅 `params` + `strength`、64 步、无 mode/source）。FastAPI 层未接入 `DocumentSession`，同一业务规则在两端各写一遍，**后续极易漂移**。
10. **`strength` 后端不校验**：`ExportImageBody/ExportVideoBody/ExportLutBody` 的 `strength: float` 直接进入 `RenderSnapshot`，仅前端 `setStrength` 做了 `0..1` 钳制。直接调 API 可传入越界值。
11. **`api/server.py` 存在未使用导入**：`import uuid`（全文仅第 6 行出现）。
12. **错误语义在前端被压缩成字符串**：`ApiError` 携带 `code`，但 `workbench.ts` 的各类 catch 多数只 `console.error(e)`（`importCube`、`rebakeLut`）或把 `e.message` 塞进 toolbar 一行文字，**用户无法区分"网络断开 / 后端 500 / 业务码 40xx"**。

### 4.3 联调结论

- **字段名层面：零处拼写不一致**（全部 snake_case 对齐），参数契约 16 键完全对齐。
- **语义层面：3 处真实缺口**（WS 字段子集、`strength` 未校验、LUT 导出夹具耦合）。
- **架构层面：2 处结构性重复**（撤销/重做双实现；`content_url`/`download_url` 双源）。
- **悬空接口：1 个**（`/api/histogram`）。

---

## 5. 当前已知局限与遗留待办清单（按优先级）

### P0 —— 影响演示稳定性或明显掉性能，建议下一步优先处理

| # | 问题 | 证据 | 建议 |
| --- | --- | --- | --- |
| 1 | **直方图 `readPixels` 同步回读阻塞渲染管线** ✅ 已修复 | 关闭直方图回调后 44.8 → **58.6 fps**（+31 %）；单次采样 **4.28 ms** | 已改 64² + 100 ms：1080p 达 **59.9 fps**，采样 1.10 ms；进一步可改 PBO 异步回读 |
| 2 | **媒体/任务注册表进程内存储** ✅ 媒体侧已修复 | `_REGISTRY` / `_JOBS` 均为 dict；重启即清空 | 媒体已落盘 `api_media/index.json` 并自动恢复；`_JOBS` 仍为内存态，进程重启会丢失进行中的导出任务 |
| 3 | **预览与导出分辨率不一致（所见非所得）** | 预览把 >1920 宽视频降采样；导出走全分辨率 ffmpeg | HUD 上明确标注"预览已降采样"，或把预览上限提到 2560，并在导出前给出分辨率提示 |
| 4 | **参数拖动污染撤销栈** ✅ 已修复 | `state_store.setParam` 每次 `input` 都 `pushHistory()` | 已改 `commit` 分档：一次拖动只落 1 条快照（实测 8 次 input 后撤销键仍禁用，撤销直接回到拖动前） |
| 5 | **每次参数变化都要回后端重烤 LUT** | 33³ = 23 ms + 562 KB base64；65³ = 203 ms + 4.3 MB | 已有 `paramsKey` 去重 + 220 ms debounce，但连续拖动仍会触发；建议改 Worker/GPU 本地烘焙，或仅在 `change` 时烘焙 |

### P1 —— 体验与健壮性打磨

| # | 问题 | 说明 / 建议 |
| --- | --- | --- |
| 6 | A/B 把手仅鼠标事件 | 只有 `mousedown` + `window.mousemove`，触屏/触控板手势不可用；无键盘可达（`aria-label` 有，但无方向键处理）。建议改 `pointerdown/move/up` + `setPointerCapture` |
| 7 | 导出无取消、无并发上限 | 每 job 一个 daemon 线程；连点导出会并发跑多份 ffmpeg 抢 CPU。建议引入队列 + 取消令牌（`ai/offline.py` 已预留 `cancel_event` 的同类模式） |
| 8 | 异常对用户不可见 | `importCube` 与 `rebakeLut` 只 `console.error`；后端 40xx 业务码被压缩成一行文字。建议统一 toast + 错误码文案表 |
| 9 | 外部 `.cube` 语义会被静默丢弃 | `setParam/setParams` 都会把 `externalLut` 置 false，但 UI 无提示，用户以为仍在用导入的 cube |
| 10 | AI 应用参数后预设卡高亮不重置 ✅ 已修复 | 新增 `PresetGrid.clearActive()`；AI 生成、导入外部 `.cube`、手动拖滑杆都会清除高亮，仅点预设或重置才点亮 |
| 11 | WebGL 上下文丢失无恢复 | 全文无 `webglcontextlost` / `webglcontextrestored` 监听，掉上下文只能刷新页面 |
| 12 | 无响应式断点 | 两侧固定 344 px；窗口 < ~1000 px 时中央视口被压到不可用，无 `min-width` 保护、无折叠策略 |
| 13 | 无 `ResizeObserver` | 依赖每帧 `resize()` 被动生效（当前每帧调用，代价可接受），但布局突变时无即时正确性保证 |

### P2 —— 长期/工程化

| # | 问题 | 说明 |
| --- | --- | --- |
| 14 | 无持久化、无会话恢复 | 刷新后参数、媒体、撤销栈全部丢失；无多文档/标签页 |
| 15 | 可访问性不足 | 16 个 `input[type=range]` 无 `aria-label`（无障碍树中 name 退化为数值）；无 `prefers-reduced-motion`；键盘仅 `Space / Ctrl+Z / Ctrl+Y` |
| 16 | 直方图信息未用尽 | 后端能算 `clip_low/clip_high`，前端不显示裁切告警；采样基于屏幕 CSS 区域，非源图统计 |
| 17 | 加载遮罩文案写死 | 默认文案为"AI 正在解析…烘焙 33³ 3D LUT…"；导入 65³ cube 且未传 `show(text)` 时文案与实际不符 |
| 18 | 外部依赖未自检 | 依赖 `.venv` 手工安装 + 系统 `ffmpeg`；`tools/check_config.py` 未接入启动流程，也没有 `/health` 路由 |
| 19 | LUT 无客户端缓存 | `lut_id` 是 SHA-256，但前端不复用；相同参数重复烘焙、重复上传 |
| 20 | 无 CI / 无版本控制 | 目录无 `.git`；213 个用例与 `tsc -b` 全靠手工执行，缺少流水线门禁 |

---

## 附录 A：本次审计的验证命令清单

```powershell
# 结构与改动时间
Get-ChildItem -Recurse -File | Where-Object { 排除 .venv/node_modules/__pycache__/dist/build-* } |
  Sort-Object LastWriteTime -Descending

# 后端测试（全套）
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
# 逐模块统计
foreach ($f in (Get-ChildItem tests -Filter 'test_*.py')) {
  .\.venv\Scripts\python.exe -m unittest discover -s tests -p $f.Name
}

# 前端构建
cd frontend; npm run build

# AI 配置实况（不打印密钥）
.\.venv\Scripts\python.exe -c "from ai.provider import load_config, build_provider; c=load_config(); print(c.status, c.configured, build_provider(c).__class__.__name__)"

# ffmpeg / worker 可用性
.\.venv\Scripts\python.exe -c "from app import video_io; print(video_io.availability())"
Get-ChildItem build-arm64\Debug\render_worker.exe

# LUT 烘焙耗时
.\.venv\Scripts\python.exe -c "import time; from baker.params import ColorParams; from baker.color_transform import bake_lut; ..."
```

浏览器侧性能采样（CDP `Runtime.evaluate`，仅内存态，未改动任何源码）：

- 静态 1920×1080 图：`glv.frames` 2 s 增量 / 时长 → 58.7 fps；`sampleHistogram()` ×30 均值 → 4.28 ms。
- 640×360 / 2560×1440 视频：3 s 内 `frames` 与 `uploads` 增量 → 44.8 fps / 134 次，37.9 fps / 113 次。
- 对照实验：`glv.onHistogram(null)` 后同一视频 → 58.6 fps。
- 实验结束后页面已刷新复原，临时测试视频与临时静态服务脚本已删除（`runtime/cache/_perf_*`）。

## 附录 B：关键设计约束（来自 ADR，仍需遵守）

| ADR | 约束 | 代码落点 |
| --- | --- | --- |
| ADR-003 | 参数数学由 Python 拥有，前端不重复实现 | `baker/color_transform.py` 烤 LUT，前端只采样 |
| ADR-004 | encoded sRGB 进、encoded sRGB 出；禁用自动 sRGB 转换与抖动 | `grade.frag` 注释 + WebGL2 未启用 `SRGB8_ALPHA8` |
| ADR-005 | 只用本地图像，不外传素材（AI 只传参数意图） | `/api/ai/propose` 只收 `intent` + `current_params` |
| ADR-007 | 参数 v2 共 16 维，schema 2.0 | `schemas/color_params.v2.schema.json` + 双端 `PARAM_KEYS` |
| ADR-008 | 媒体类型与视频处理约定 | `video_io.py` / `/api/export/video` |
| ADR-011 | 暗房黑金 UI 规范（现已按用户要求改为黑灰） | `tokens.css` / `layout.css` |

> 注：ADR-011 原文描述的是"黑金"，而当前实现已按用户指令改为"黑灰 + 银白"。建议补一篇 ADR-012 记录这次主题变更，以免后续协作方按旧 ADR 回退配色。
