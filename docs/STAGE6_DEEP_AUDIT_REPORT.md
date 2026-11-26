# 全系统深度扫描审计与修复报告（阶段六）

> 审计时间：2026-11-20  
> 工程根目录：`<project-root>`  
> 审计范围：前端 WebGL2、FBO 后处理、3D 色彩立方体、状态机、API、离线/在线 AI、样式布局

---

## 0. 执行摘要

| 项目 | 结果 |
| --- | --- |
| **直方图回归** | **已修复**：`sampleHistogram()` 从默认帧缓冲误读 → 重绑 `histFbo` 后 `readPixels` |
| **离线「微暖」误命中** | **已修复**：结构化数值意图走 `_parse_numeric_assignments`；`_WARM` 去掉裸词「暖」；「微暖」上下文豁免 |
| 单元测试 | **214 tests OK**（新增 `test_offline_structured_chip_not_warm_template`） |
| 前端构建 | `npm run build` **通过** |
| 像素级验收 | `tools/acceptance_stage6_histogram.py`：**直方图彩色像素 1632 / 1736（>500）**，`gl.getError() === 0`，Console 无 error |

---

## 第一阶段：已暴露问题根因与修复

### 1.1 RGB · 亮度直方图空白

**根因（阶段五 3-Pass 引入）**  
`sampleHistogram()` 调用 `renderPipeline(this.histFbo, 64, 64)` 已将合成结果写入 `histFbo`，但 `renderPipeline()` 末尾无条件执行 `gl.bindFramebuffer(null)`。随后的 `readPixels()` 实际从**主画布默认帧缓冲**取样，而非 `histFbo`；再经 Alpha 过滤与对数归一化后，回调侧得到的 bin 几乎全零，`HistogramView` 因 `hasData` 为真但曲线高度为 0，呈现「空白框」。

**修复**（`frontend/src/core/gl_viewport.ts`）

1. `renderPipeline()` 仅当 `targetFbo === null` 时才解绑帧缓冲。  
2. `readPixels()` 前显式 `bindFramebuffer(histFbo)`。  
3. 读回后 `viewport` 恢复为主画布尺寸。

**验证**：Playwright 断言 `.histogram-wrap canvas` 非网格彩色像素 **> 500**；拖动晕光后仍 **> 500**。

### 1.2 AI 离线「微暖」误判重暖模板

**根因**  
「清透日系」等 chip 文案同时命中：裸词 **「暖」**（`_WARM`）、**「清透/日系」**（`_SOFT`），在存在部分参数词但未形成有效 `directives` 时走 `(style && !directives) → _from_preset(warm|soft)`。

**修复**（`ai/offline.py`）

1. 新增 `_parse_numeric_assignments()`：识别 `色温 +6`、`曝光 +0.20 EV`、`高光 -12` 等 **≥2 项**时，按结构化数值直接写 `ColorParams`（钳制至 `PARAM_RANGES`），**禁止套模板**。  
2. `_WARM` / `_COOL` 去掉单字「暖/冷」；风格匹配前剔除「微暖/微冷」干扰子串。  
3. 有数值色操作时不以风格模板作 rule 引擎基底。

**验证**：`warm_leak = false`；摘要为「按结构化数值解析：temperature +6 …」。

---

## 第二阶段：七大模块审计清单

| # | 子系统 | 结论 |
| --- | --- | --- |
| 1 | **WebGL2 / FBO** | **发现缺陷并已修复**：直方图 FBO 解绑；其余：静图 Mipmap、`bloom=0` 占位 1×1、Resize 时 `disposeFbos` 重建、Pass3 分屏/按住原图——**正常** |
| 2 | **3D 色彩立方体** | **正常**：`lut3d` 时主画布隐藏、分屏 UI 仅 `split` 显示；LUT 烘焙同步 `lutCube.setLut`；旋转/缩放/双击复位无额外泄漏（`lut_cube_view.ts` 使用 window 级 mouseup） |
| 3 | **左侧栏** | **正常**：直方图修复后实时更新；预设高亮/清除；`resetAll` 经 `store.resetParams()` 同步 **strength + bloom** |
| 4 | **顶栏 / HUD** | **正常**：四段模式、导入、撤销栈；强度/晕光并排（`layout.css` 底部宽度 640px）；视频 dock 逻辑未改 |
| 5 | **右侧 AI / 16 维** | **发现缺陷并已修复**：离线结构化 chip；在线仍经 `build_provider` + API，无 Key 降级离线——**正常** |
| 6 | **导出 / API** | **正常**（只读审计）：WS+轮询、`watchJob` 防重复导出依赖 UI `toolbar.setProgress`——未见阶段五回归 |
| 7 | **样式布局** | **正常**（静态审计）：`--sidebar-w: 344px`、HUD 宽度放宽；窄屏下 seg 四字按钮 `white-space: nowrap` |

---

## 第三阶段：自动化验收记录

命令：

```powershell
cd .
.\.venv\Scripts\python.exe tools\acceptance_stage6_histogram.py
```

产物：`runtime/benchmark_results/stage6_acceptance.json`

| 检查项 | 结果 |
| --- | --- |
| 直方图像素数 | 1632（阈值 > 500） |
| 晕光 70% 后直方图 | 1736 |
| WebGL `getError` | 0 |
| Console errors | `[]` |
| 清透日系非暖模板 | `warm_leak: false` |

---

## 变更文件一览

| 文件 | 变更性质 |
| --- | --- |
| `frontend/src/core/gl_viewport.ts` | 直方图 FBO 读回修复 |
| `ai/offline.py` | 结构化数值解析 + 暖色误命中修复 |
| `tests/test_ai.py` | 新增回归用例 |
| `tools/acceptance_stage6_histogram.py` | 阶段六像素级验收脚本 |

---

## 建议后续（未阻塞发版）

1. 直方图采样使用**独立 64² FBO 池**，避免 `ensureFbos(64,64)` 与主画布 FBO 尺寸交替重建。  
2. `lut3d` 模式下可选继续更新直方图（当前 `setRenderPaused` 暂停主循环采样）。  
3. 部署后端后需**重启 uvicorn** 以加载 `offline.py`（验收中已复现旧进程缓存问题）。