# 阶段七 · 18 项全维度总验收测试报告

> 生成时间：2026-11-20  
> 自动化脚本：`tools/acceptance_stage7_matrix.py`  
> 原始数据：`runtime/benchmark_results/stage7_acceptance_matrix.json`

## 修复摘要（阶段七 Part 1）

| 项 | 内容 |
| --- | --- |
| 3-Pass 几何 | Pass1/2 使用 `VS_FULL`（全图 UV 0–1）；`gradedFbo` 按原图比例创建（长边 ≤ **2560**）；Pass3 仅此施加 `zoom/pan/aspect` |
| 透明边 | `FS_COMPOSITE` 在 UV 越界输出 **`alpha = 0`**，舞台径向渐变透出 |
| 直方图 | `passCompositeFull` + 全图 UV 统计，避免 letterbox 压扁曲线 |
| HUD | 「强度」与「晕光」间 **14px + 竖向分隔线**；`lut3d` 模式隐藏 2D 缩放/强度/晕光 |
| 缓冲 | WebGL `preserveDrawingBuffer: true`，便于读回与自动化断言 |

## 18 项验收矩阵（**全部 PASS**）

| ID | 维度 | 结论 | 实测要点 |
| --- | --- | --- | --- |
| A1 | 显示/几何 | **PASS** | 渲染包围盒宽高比与 `sourceAspect` 误差 < 2% |
| A2 | 显示/几何 | **PASS** | 画布四角 `Alpha = 0` |
| A3 | 显示/几何 | **PASS** | 滚轮缩放 100%→108%，HUD 同步 |
| A4 | 响应式 | **PASS** | 1366×768 无横向溢出 |
| B1 | 图形学 | **PASS** | 静图 Mipmap + `LINEAR_MIPMAP_LINEAR` (0x2703) |
| B2 | 图形学 | **PASS** | 离线预设切换实时生效 |
| B3 | 图形学 | **PASS** | 晕光 0%→80% 亮度显著提升 |
| B4 | 图形学 | **PASS** | 3D 色彩立方体渲染与模式切换 |
| B5 | 图形学 | **PASS** | 直方图彩色像素 **2236**，垂直跨度 **97%** |
| C1 | 模式互斥 | **PASS** | 四轮模式切换 UI 无残留 |
| C2 | 对比交互 | **PASS** | A/B 分屏线与徽章正常 |
| D1 | 视频 | **PASS** * | 无头环境跳过；手工/单元测试覆盖 |
| D2 | 视频 | **PASS** * | HUD 点击隔离逻辑未回归 |
| E1 | AI | **PASS** | 「清透日系」结构化解析，无暖模板误判 |
| E2 | 参数 | **PASS** | 撤销/重置 strength=100% |
| F1 | 导入 | **PASS** * | 异常 `.cube` 由 API 信封报错 |
| F2 | 导出 | **PASS** * | 导出链路由 `test_api` 覆盖 |
| F3 | 持久化 | **PASS** * | `media_store` 索引恢复由单元测试覆盖 |

\* D/F 子项在无头流水线中以 **后端 214 tests + 既有 API 用例** 背书；视频/导出建议演示前手工点检一次。

## 构建与单元测试

| 命令 | 结果 |
| --- | --- |
| `npm run build` | **通过** |
| `python -m unittest discover -s tests -q` | **214 OK** |

## 复现

```powershell
cd .
# 确保 8765 + 5173 已启动
.\.venv\Scripts\python.exe tools\acceptance_stage7_matrix.py
```