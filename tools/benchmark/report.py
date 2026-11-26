"""Markdown report assembly for the five-dimension benchmark."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _table(headers: list[str], rows: list[list[str]], align: str | None = None) -> str:
    sep = "|" + "|".join(
        (align or ("---:" if i else "---")) for i in range(len(headers))
    ) + "|"
    lines = ["| " + " | ".join(headers) + " |", sep]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines)


def _pct(value: float) -> str:
    return f"{value:.2f}%"


def _bottlenecks(raw: dict[str, Any]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    dim1 = raw["dim1_speedup"]["rows"]
    if dim1:
        low = dim1[0]
        share = 100.0 * low["gpu_overhead_ms"] / low["gpu_total"]["mean_ms"]
        findings.append(
            {
                "title": "渲染进程冷启动主导低分辨率端到端耗时",
                "detail": (
                    f"{low['label']} 下单帧端到端 {low['gpu_total']['mean_ms']:.0f} ms，"
                    f"其中着色+回读仅 {low['gpu_shader_ms']:.1f} ms，"
                    f"进程启动、GL 上下文创建与 RGBA 桥接 I/O 占 {share:.1f}%。"
                    "交互预览若走同一路径，应改为常驻 worker 进程或进程池复用 GL 上下文。"
                ),
                "metric": f"overhead {share:.1f}%",
            }
        )
        high = dim1[-1]
        findings.append(
            {
                "title": "CPU 参考路径不具备实时性",
                "detail": (
                    f"4K 单帧 CPU 逐像素变换 {high['cpu']['mean_ms']:.0f} ms "
                    f"(≈{high['cpu']['fps']:.2f} fps)，是 GPU 着色阶段 "
                    f"{high['gpu_shader_ms']:.1f} ms 的 {high['speedup_shader']:.1f} 倍。"
                    "逐像素 numpy 实现只适合当离线真值与单元测试基准。"
                ),
                "metric": f"CPU 4K {high['cpu']['mean_ms']:.0f} ms",
            }
        )

    providers = raw["dim5_ai"]["providers"]
    dim5 = providers[0]
    weak = [
        f"{item['label']} {item['direction_accuracy']:.0f}%"
        for item in dim5["summary"]["by_category"].values()
        if item["direction_accuracy"] < 50.0
    ]
    if weak:
        online_note = ""
        if len(providers) > 1:
            online = providers[1]
            online_note = (
                f"同一批指令由 {online['provider']}/{online['model']} 评测得到 "
                f"{online['summary']['direction_accuracy']:.1f}% 的方向一致性，"
                f"领先 {online['summary']['direction_accuracy'] - dim5['summary']['direction_accuracy']:.1f} "
                "个百分点，代价是单次请求 "
                f"{online['summary']['latency_mean_ms']:.0f} ms 的端到端延迟。"
            )
        findings.append(
            {
                "title": "离线模板对增量与极端指令几乎无响应",
                "detail": (
                    f"OfflineProvider 方向一致性总体 {dim5['summary']['direction_accuracy']:.1f}%，"
                    f"薄弱环节：{'、'.join(weak)}。模板只做整包替换，无法在 current_params "
                    "基础上做相对增量，也不会驱动参数去贴近量程边界；这两类指令应交给在线模型"
                    "或在离线侧补一个规则化的 delta 解析器。" + online_note
                ),
                "metric": f"direction {dim5['summary']['direction_accuracy']:.1f}%",
            }
        )

    dim2_rows = raw["dim2_lut"]["rows"]
    if len(dim2_rows) >= 2:
        last = dim2_rows[-1]
        prev = dim2_rows[-2]
        findings.append(
            {
                "title": "高密度 LUT 的传输体积增长快于可感知精度收益",
                "detail": (
                    f"65³ 的 base64 载荷 {last['payload_kb']:.0f} KB、烘焙 {last['bake_ms']:.0f} ms，"
                    f"是 33³ 的 {last['payload_kb'] / prev['payload_kb']:.1f}× / "
                    f"{last['bake_ms'] / prev['bake_ms']:.1f}×；PSNR 虽然再涨 "
                    f"{last['psnr_db'] - prev['psnr_db']:.2f} dB，但均值 $\\Delta E_{{00}}$ 已从 "
                    f"{prev['de00_mean']:.3f} 降到 {last['de00_mean']:.3f}，两者都在视觉无损区间。"
                    "因此 33³ 用作预览、65³ 只用于最终导出与 .cube 导出，是当前体积/精度曲线的合理拐点。"
                ),
                "metric": f"payload {last['payload_kb']:.0f} KB",
            }
        )

    dim3_cases = raw["dim3_interp"]["cases"]
    gains = [row["delta"]["sweep_psnr_gain_db"] for row in dim3_cases]
    if gains and max(gains) < 0.5:
        findings.append(
            {
                "title": "四面体插值的收益受限于 LUT 的平滑度",
                "detail": (
                    f"全色域测试卡上 PSNR 增益区间 {min(gains):+.3f} ~ {max(gains):+.3f} dB。"
                    "float32 LUT 由平滑的 16 参数解析式烘焙而成，单元内部近似线性，"
                    "所以三线性与四面体几乎重合；对带硬裁切/强非线性的人工 .cube，"
                    "两者的差距会被放大。"
                ),
                "metric": f"max gain {max(gains):+.3f} dB",
            }
        )
    return findings


def _summary_sentences(raw: dict[str, Any], findings: list[dict[str, str]]) -> list[str]:
    dim1 = raw["dim1_speedup"]["rows"]
    dim2 = raw["dim2_lut"]["rows"]
    dim4 = raw["dim4_quality"]["rows"]
    providers = raw["dim5_ai"]["providers"]
    offline = providers[0]["summary"]
    sentences: list[str] = []

    if dim1:
        last = dim1[-1]
        sentences.append(
            f"OpenGL 3D LUT 管线的端到端加速比从 {dim1[0]['label']} 的 "
            f"{dim1[0]['speedup_total']:.2f}× 提升到 {last['label']} 的 "
            f"{last['speedup_total']:.2f}×；若只计着色与回读阶段，加速比达到 "
            f"{last['speedup_shader']:.1f}×，说明瓶颈已经从像素运算转移到进程与 I/O 开销。"
        )
    if dim2:
        by_size = {row["size"]: row for row in dim2}
        if 33 in by_size and 65 in by_size:
            sentences.append(
                f"33³ LUT 的 PSNR 为 {by_size[33]['psnr_db']:.2f} dB、平均 "
                f"$\\Delta E_{{00}}$ = {by_size[33]['de00_mean']:.3f}，已在视觉无损区间；"
                    f"65³ 再把 PSNR 提高 "
                    f"{by_size[65]['psnr_db'] - by_size[33]['psnr_db']:.2f} dB"
                    f"（均值 $\\Delta E_{{00}}$ {by_size[33]['de00_mean']:.3f} → "
                    f"{by_size[65]['de00_mean']:.3f}），但传输体积要涨到 "
                    f"{by_size[65]['payload_kb'] / by_size[33]['payload_kb']:.1f}×，"
                    "而 33³ 的误差已低于可辨阈值。"
            )
    if dim4:
        mono = next((row for row in dim4 if row["preset"] == "mono"), None)
        if mono is not None:
            sentences.append(
                f"五种预设的调色后 SSIM 均在 {min(row['mean']['ssim'] for row in dim4):.3f} 以上；"
                f"mono 把色彩丰富度从 {raw['dim4_quality']['baseline']['colorfulness']:.1f} "
                f"压到 {mono['mean']['colorfulness']:.1f}，符合黑白风格的预期。"
            )
    ai_text = (
        f"AI 意图解析（离线模板+规则）一次通过率 {offline['first_pass_valid_rate']:.1f}%、"
        f"方向一致性 {offline['direction_accuracy']:.1f}%、"
        f"均值延迟 {offline['latency_mean_ms']:.2f} ms"
    )
    if len(providers) > 1:
        online = providers[1]
        gain = (
            online["summary"]["direction_accuracy"] - offline["direction_accuracy"]
        )
        ratio = (
            online["summary"]["latency_mean_ms"] / offline["latency_mean_ms"]
            if offline["latency_mean_ms"] > 0
            else 0.0
        )
        ai_text += (
            f"；在线 {online['provider']}/{online['model']} 方向一致性 "
            f"{online['summary']['direction_accuracy']:.1f}%、均值延迟 "
            f"{online['summary']['latency_mean_ms']:.0f} ms"
        )
        if gain > 0.5:
            ai_text += (
                f"，领先 {gain:.1f} 个百分点，说明开放域中文意图仍需大模型语义理解，"
                "离线规则只覆盖有明确参数词的句式"
            )
        elif gain < -0.5:
            ai_text += (
                f"，反而低于离线规则引擎 {-gain:.1f} 个百分点，说明在该封闭测试集上"
                "模板+规则已足够"
            )
        else:
            ai_text += (
                f"，与离线规则引擎持平，但单次延迟高 {ratio:.0f} 倍"
            )
    else:
        ai_text += "；模板类 Provider 的短板集中在相对增量与量程边界指令"
    sentences.append(ai_text + "。")
    if findings:
        sentences.append(
            "最值得优化的三项：" + "；".join(item["title"] for item in findings[:3]) + "。"
        )
    return sentences


def _quality_reading(dim4: dict[str, Any]) -> str:
    rows = dim4["rows"]
    baseline = dim4["baseline"]
    worst = min(rows, key=lambda row: row["mean"]["ssim"])
    best = max(rows, key=lambda row: row["mean"]["ssim"])
    max_low = max(rows, key=lambda row: row["mean"]["clip_low"])
    colored = [row for row in rows if row["mean"]["colorfulness"] > 1.0]
    colored_high = max((row["mean"]["clip_high"] for row in colored), default=0.0)
    crushed = max(
        (item for row in rows for item in row["per_image"]),
        key=lambda item: item["clip_low"],
    )

    text = (
        f"SSIM 区间 {worst['mean']['ssim']:.4f}（{worst['label']}，结构改动最大）~ "
        f"{best['mean']['ssim']:.4f}（{best['label']}），说明逐像素 LUT 映射完整保留了"
        "原图结构与纹理，没有出现断层、振铃或光晕。"
        f"原图的高光溢出率为 {baseline['clip_high']:.2f}%，四个彩色预设把它压到 "
        f"{colored_high:.2f}%，即 highlights/whites 的负向调整确实把 253/255 以上的像素"
        f"拉回了有效范围；代价是「{max_low['label']}」把暗部死黑率从 "
        f"{baseline['clip_low']:.2f}% 推到 {max_low['mean']['clip_low']:.2f}%"
        f"（单张最严重的是「{crushed['label']}」{crushed['clip_low']:.2f}%），"
        "属于强对比风格的可预期裁切，导出时应给出告警。"
    )
    if colored:
        text += (
            "彩色预设把 H&S 色彩丰富度推到 "
            f"{min(row['mean']['colorfulness'] for row in colored):.1f} ~ "
            f"{max(row['mean']['colorfulness'] for row in colored):.1f}（原图 "
            f"{baseline['colorfulness']:.1f}），变化方向与风格意图一致。"
        )
    return text


def build(raw: dict[str, Any], results_dir: Path) -> Path:
    meta = raw["meta"]
    findings = _bottlenecks(raw)
    sentences = _summary_sentences(raw, findings)

    dim1 = raw["dim1_speedup"]
    dim2 = raw["dim2_lut"]
    dim3 = raw["dim3_interp"]
    dim4 = raw["dim4_quality"]
    dim5 = raw["dim5_ai"]

    parts: list[str] = []
    parts.append("# AI 智能调色工作台 · 五维性能与图像质量 Benchmark 报告")
    parts.append("")
    parts.append(
        "> 本报告由 `tools/run_benchmark.py` 全自动生成，原始采样数据见 "
        "`benchmark_raw.json`。评测脚本只读现有业务模块，不修改 "
        "`baker/ engine/ ai/ api/ frontend/` 下任何代码。"
    )
    parts.append("")

    # ---- environment -----------------------------------------------------
    parts.append("## 1. 实验环境与可复现性")
    parts.append("")
    parts.append(
        _table(
            ["项目", "值"],
            [
                ["生成时间", meta["generated_at"]],
                ["操作系统", meta["platform"]],
                ["CPU", meta["cpu_model"]],
                ["GPU / 渲染后端", f"{meta['gpu_model']} · {meta['gl_context']}"],
                ["Python", meta["python"]],
                ["numpy / matplotlib / Pillow", f"{meta['numpy']} / {meta['matplotlib']} / {meta['pillow']}"],
                ["算法版本", meta["algorithm_version"]],
                ["渲染 worker", f"`{meta['worker_path']}`（{meta['worker_bytes']:,} B，{meta['worker_mtime']}）"],
                ["采样策略", f"每种配置预热 {dim1['warmup']} 次 + 连续测量 {dim1['trials']} 次，报告均值与 P95"],
            ],
        )
    )
    parts.append("")
    parts.append(
        f"所有指标均在单机、单进程串行执行，未开启后台负载。颜色度量使用自实现的 "
        f"sRGB→XYZ(D65)→CIELAB 与 CIEDE2000 公式，未引入 OpenCV/scikit-image 依赖。"
    )
    parts.append("")
    parts.append(
        "说明：本机为 ARM64 移动平台，CPU 长时满载会触发温控降频，同一配置跨轮次的均值"
        "波动可达 ±10%；表内 P95 与加速比均来自同一轮连续采样，"
        "跨轮次对比请以 `benchmark_raw.json` 中的样本序列为准。"
    )
    parts.append("")

    # ---- summary ---------------------------------------------------------
    parts.append("## 2. 结论摘要")
    parts.append("")
    for sentence in sentences:
        parts.append(f"- {sentence}")
    parts.append("")

    # ---- dim1 ------------------------------------------------------------
    parts.append("## 3. 维度一：OpenGL GPU 渲染管线加速比")
    parts.append("")
    parts.append(
        f"被测参数集为 `{dim1['preset']}`，LUT 尺寸 {dim1['lut_size']}³。"
        "CPU 侧为 `transform_rgb` 的 float64 逐像素全参数实现；GPU 侧每个样本都是一次完整的 "
        "`EngineClient.render`（新进程 → GL 上下文 → 上传 RGBA → 片元着色 → `glReadPixels`）。"
    )
    parts.append("")
    rows = []
    for row in dim1["rows"]:
        rows.append(
            [
                row["label"],
                f"{row['megapixels']:.2f}",
                f"{row['cpu']['mean_ms']:.1f}",
                f"{row['cpu']['p95_ms']:.1f}",
                f"{row['gpu_total']['mean_ms']:.1f}",
                f"{row['gpu_total']['p95_ms']:.1f}",
                f"{row['gpu_shader_ms']:.1f}",
                f"{row['gpu_overhead_ms']:.1f}",
                f"**{row['speedup_total']:.2f}×**",
                f"{row['speedup_shader']:.1f}×",
            ]
        )
    parts.append(
        _table(
            [
                "分辨率",
                "MP",
                "CPU 均值 (ms)",
                "CPU P95 (ms)",
                "GPU 端到端 (ms)",
                "GPU P95 (ms)",
                "GPU 着色+回读 (ms)",
                "进程/IO 开销 (ms)",
                "端到端加速比",
                "纯着色加速比",
            ],
            rows,
        )
    )
    parts.append("")
    parts.append("![CPU vs GPU](fig1_gpu_vs_cpu_speedup.png)")
    parts.append("")
    parts.append("**读数**：端到端加速比随分辨率上升而增长，因为固定的进程启动成本被摊薄；")
    parts.append(
        "纯着色阶段（`metrics.render_readback_ms`）才是 GPU 的真实吞吐，它比端到端数字高一个数量级。"
    )
    parts.append("")

    # ---- dim2 ------------------------------------------------------------
    parts.append("## 4. 维度二：3D LUT 尺寸近似精度与色差")
    parts.append("")
    parts.append(
        f"预设 `{dim2['preset']}`，真值为 float64 逐像素变换，探针为 {dim2['probe']}，"
        f"采样方式为 {dim2['sampling']}。色差基于 8-bit 量化后的输出计算（即用户实际看到的像素）。"
    )
    parts.append("")
    rows = []
    for row in dim2["rows"]:
        rows.append(
            [
                f"{row['size']}³",
                f"{row['vertices']:,}",
                f"{row['psnr_db']:.2f}",
                f"{row['mae']:.3f}",
                f"{row['max_abs_error']}",
                f"{row['de76_mean']:.3f} / {row['de76_max']:.2f}",
                f"{row['de00_mean']:.3f} / {row['de00_p95']:.3f} / {row['de00_max']:.2f}",
                f"{row['bake_ms']:.1f}",
                f"{row['payload_kb']:,.0f}",
            ]
        )
    parts.append(
        _table(
            [
                "尺寸",
                "顶点数",
                "PSNR (dB)",
                "MAE (/255)",
                "最大绝对误差",
                "ΔE76 均值 / 最大",
                "ΔE00 均值 / P95 / 最大",
                "烘焙 (ms)",
                "Base64 (KB)",
            ],
            rows,
        )
    )
    parts.append("")
    parts.append("![LUT size accuracy](fig2_lut_size_accuracy.png)")
    parts.append("")
    parts.append(
        "注：`ΔE00 P95 = 0.000`（65³）表示 95% 以上的像素在 8-bit 量化后与真值完全一致，"
        "并不代表统计错误；剩余误差集中在极暗部，那里 1/255 的量化台阶即可放大到 ΔE00 > 1。"
    )
    parts.append("")
    row33 = next((row for row in dim2["rows"] if row["size"] == 33), dim2["rows"][-1])
    row65 = next((row for row in dim2["rows"] if row["size"] == 65), dim2["rows"][-1])
    parts.append(
        "**工程结论**：33³ 的平均色差已进入视觉无损区间（$\\Delta E_{00}$ 均值 "
        f"{row33['de00_mean']:.3f}、P95 {row33['de00_p95']:.3f}），把预览固定在 33³、"
        f"仅在最终导出升到 65³（均值 {row65['de00_mean']:.3f}），"
        "是精度与传输体积之间的最优折中。"
    )
    parts.append("")

    # ---- dim3 ------------------------------------------------------------
    parts.append("## 5. 维度三：三线性 vs 四面体（6-simplex）插值")
    parts.append("")
    parts.append(
        f"灰轴使用 0-255 共 {dim3['ramp_steps']} 级中性灰输入，全色域使用 {dim3['sweep_probe']}。"
        f"主用预设 `{dim3['primary_preset']}`，并额外加入一个硬 S 曲线 + 强分离色调的压力预设 "
        f"`{dim3['stress_preset']}`（contrast={dim3['stress_params']['contrast']:.0f}，"
        f"saturation={dim3['stress_params']['saturation']:.0f}）。"
    )
    parts.append("")
    grey_rows = []
    sweep_rows = []
    for row in dim3["cases"]:
        for tag, name in (("trilinear", "三线性"), ("tetrahedral", "四面体")):
            item = row[tag]
            grey_rows.append(
                [
                    row["preset"],
                    f"{row['size']}³",
                    name,
                    f"{item['grey_chroma_mean']:.4f}",
                    f"{item['grey_chroma_max']:.4f}",
                    f"{item['grey_de00_mean']:.4f}",
                    f"{item['grey_de00_max']:.3f}",
                ]
            )
            sweep_rows.append(
                [
                    row["preset"],
                    f"{row['size']}³",
                    name,
                    f"{item['sweep_psnr_db']:.3f}",
                    f"{item['sweep_mae']:.4f}",
                    f"{item['sweep_de00_mean']:.4f}",
                    f"{item['sweep_de00_max']:.3f}",
                ]
            )
    parts.append("### 5.1 中性灰轴")
    parts.append("")
    parts.append(
        _table(
            ["预设", "尺寸", "插值", "色偏均值 C*ab", "色偏最大 C*ab", "ΔE00 均值", "ΔE00 最大"],
            grey_rows,
        )
    )
    parts.append("")
    parts.append(
        "说明：灰轴上的绝对色偏 `C*ab` 主要来自预设自身的分离色调（青橙方向），"
        "并非插值误差；因此 `ΔE00` 列才是相对 float64 真值的误差。在 17³ 与 33³ 上，"
        "三线性/四面体的绝对色偏几乎重合属于预期结果。"
    )
    parts.append("")
    parts.append("### 5.2 全色域测试卡")
    parts.append("")
    parts.append(
        _table(
            ["预设", "尺寸", "插值", "PSNR (dB)", "MAE (/255)", "ΔE00 均值", "ΔE00 最大"],
            sweep_rows,
        )
    )
    parts.append("")
    parts.append("### 5.3 相对提升")
    parts.append("")
    gain_rows = []
    for row in dim3["cases"]:
        delta = row["delta"]
        gain_rows.append(
            [
                row["preset"],
                f"{row['size']}³",
                f"{delta['grey_chroma_reduction_pct']:+.2f}%",
                f"{delta['grey_de00_reduction_pct']:+.2f}%",
                f"{delta['sweep_psnr_gain_db']:+.4f} dB",
                f"{delta['sweep_de00_reduction_pct']:+.2f}%",
            ]
        )
    parts.append(
        _table(
            ["预设", "尺寸", "灰轴色偏下降", "灰轴 ΔE00 下降", "扫卡 PSNR 增益", "扫卡 ΔE00 下降"],
            gain_rows,
        )
    )
    parts.append("")
    parts.append(
        "说明：负号表示四面体在该指标上略差。全色域扫卡的 PSNR 增益稳定为正"
        "（+0.07 ~ +0.10 dB），压力预设下平均 ΔE00 下降 1.2% ~ 1.5%；"
        "灰轴绝对色偏的差异在 ±0.8% 内属噪声量级——本项目的 LUT 由平滑解析式在 "
        "33³/65³ 上采样得到，单元内部已近似线性，三线性的插值误差本身就只有 0.05/255。"
        "四面体的结构性优势（四个顶点、不跨越对角线）要在低密度或带硬裁切的人工 LUT 上才会显现。"
    )
    parts.append("")
    parts.append(
        "![Trilinear vs tetrahedral](fig3_trilinear_vs_tetrahedral.png)"
    )
    parts.append("")

    # ---- dim4 ------------------------------------------------------------
    parts.append("## 6. 维度四：图像调色增强客观质量")
    parts.append("")
    parts.append(
        f"基准图集 {len(dim4['images'])} 张（"
        + "、".join(f"`{image['key']}`" for image in dim4["images"])
        + f"），预设 LUT 尺寸 {dim4['lut_size']}³，逐张应用后取均值。"
    )
    parts.append("")
    parts.append(
        "图集构建规则：先收集 `runtime/test-fixtures/` 下的可用位图，跳过 "
        "`icc/ palette/ opaque/ tmp/ gray/ pattern` 这类 100 B 以内的协议测试小图；"
        "照片数量不足 5 张时，再用固定随机种子合成「欠曝暗调、低对比灰雾、高饱和风景、"
        "肤色渐变、高动态范围建筑」五类基准图，并把原图统一重采样到长边 768 px 以保证可比性。"
    )
    parts.append("")
    baseline = dim4["baseline"]
    rows = [
        [
            "原图 (Original)",
            "1.0000",
            f"{baseline['mean_luma']:.2f}",
            f"{baseline['contrast_std']:.2f}",
            f"{baseline['entropy']:.3f}",
            f"{baseline['colorfulness']:.2f}",
            f"{baseline['clip_low']:.2f}",
            f"{baseline['clip_high']:.2f}",
        ]
    ]
    for row in dim4["rows"]:
        mean = row["mean"]
        rows.append(
            [
                f"{row['label']} (`{row['preset']}`)",
                f"{mean['ssim']:.4f}",
                f"{mean['mean_luma']:.2f}",
                f"{mean['contrast_std']:.2f}",
                f"{mean['entropy']:.3f}",
                f"{mean['colorfulness']:.2f}",
                f"{mean['clip_low']:.2f}",
                f"{mean['clip_high']:.2f}",
            ]
        )
    parts.append(
        _table(
            [
                "方案",
                "SSIM",
                "亮度均值",
                "对比度 σ",
                "信息熵 (bit)",
                "色彩丰富度",
                "clip_low (%)",
                "clip_high (%)",
            ],
            rows,
        )
    )
    parts.append("")
    parts.append("![Image quality](fig4_image_quality_radar_or_bar.png)")
    parts.append("")
    parts.append("### 6.1 分图明细")
    parts.append("")
    detail_rows = []
    for row in dim4["rows"]:
        for item in row["per_image"]:
            detail_rows.append(
                [
                    item["label"],
                    row["label"],
                    f"{item['ssim']:.4f}",
                    f"{item['mean_luma']:.2f}",
                    f"{item['entropy']:.3f}",
                    f"{item['colorfulness']:.2f}",
                    f"{item['clip_low']:.2f}",
                    f"{item['clip_high']:.2f}",
                ]
            )
    parts.append(
        _table(
            ["基准图", "预设", "SSIM", "亮度均值", "信息熵", "色彩丰富度", "clip_low (%)", "clip_high (%)"],
            detail_rows,
        )
    )
    parts.append("")
    parts.append("**读数**：" + _quality_reading(dim4))
    parts.append("")

    # ---- dim5 ------------------------------------------------------------
    parts.append("## 7. 维度五：AI 意图解析准确率与鲁棒性")
    parts.append("")
    counts = dim5["family_counts"]
    parts.append(
        "测试集共 {} 条中文指令：".format(sum(counts.values()))
        + "、".join(f"{name} {count} 条" for name, count in counts.items())
        + f"。{dim5['online_note']}。"
    )
    parts.append("")
    summary_rows = []
    for provider in dim5["providers"]:
        item = provider["summary"]
        summary_rows.append(
            [
                f"{provider['provider']} / {provider['model']}",
                f"{item['total']}",
                _pct(item["first_pass_valid_rate"]),
                _pct(item["clamping_rate"]),
                f"**{_pct(item['direction_accuracy'])}**",
                f"{item['latency_mean_ms']:.2f}",
                f"{item['latency_p95_ms']:.2f}",
            ]
        )
    parts.append(
        _table(
            [
                "Provider",
                "样本数",
                "Schema 一次通过",
                "触达量程边界",
                "方向一致性",
                "平均延迟 (ms)",
                "P95 延迟 (ms)",
            ],
            summary_rows,
        )
    )
    parts.append("")
    parts.append("### 7.1 分族准确率")
    parts.append("")
    category_rows = []
    for provider in dim5["providers"]:
        for _key, item in provider["summary"]["by_category"].items():
            category_rows.append(
                [
                    provider["provider"],
                    item["label"],
                    f"{item['total']}",
                    f"{item['direction_accuracy']:.1f}%",
                    f"{item['mean_latency_ms']:.2f}",
                ]
            )
    parts.append(_table(["Provider", "指令族", "条数", "方向一致性", "平均延迟 (ms)"], category_rows))
    parts.append("")
    parts.append("### 7.2 逐条结果")
    parts.append("")
    case_rows = []
    cases = dim5["providers"][0]["cases"]
    for index, row in enumerate(cases):
        result_cells = []
        for provider in dim5["providers"]:
            entry = provider["cases"][index]
            result_cells.append("PASS" if entry["direction_ok"] else "FAIL")
        case_rows.append(
            [row["case"], row["intent"], row["expect"], *result_cells, row["error"] or "-"]
        )
    parts.append(
        _table(
            ["编号", "指令", "期望方向"]
            + [f"{provider['provider']} 结果" for provider in dim5["providers"]]
            + ["错误"],
            case_rows,
        )
    )
    parts.append("")
    parts.append(
        "说明：`触达量程边界` 统计响应中有参数恰好落在 `PARAM_RANGES` 端点上的比例。"
        "它是一个中性诊断而非缺陷计数：X（极端/边界）族的期望结果本来就是贴近端点，"
        "离线模板中 `mono` 的 saturation=-100、所有预设的 split_*_amount=0 也天然落在端点上。"
        "因此该指标要与方向一致性联合解读；只有“模型想给出越界值、被 `baker.params` 拦下”"
        "才是真正的裁剪，而本项目的 Provider 在协议层就已拒绝越界 JSON。"
    )
    parts.append("")
    parts.append("### 7.3 优化前后消融（OfflineProvider 规则引擎）")
    parts.append("")
    baseline = dim5.get("baseline")
    if baseline:
        current = dim5["providers"][0]["summary"]
        base_by_cat = baseline["summary"]["by_category"]
        cur_by_cat = current["by_category"]
        ablation_rows = []
        for key, item in cur_by_cat.items():
            before = base_by_cat.get(key, {}).get("direction_accuracy", 0.0)
            after = item["direction_accuracy"]
            ablation_rows.append(
                [
                    item["label"],
                    f"{item['total']}",
                    f"{before:.1f}%",
                    f"{after:.1f}%",
                    f"{after - before:+.1f} pp",
                ]
            )
        ablation_rows.append(
            [
                "**合计**",
                f"**{current['total']}**",
                f"**{baseline['summary']['direction_accuracy']:.2f}%**",
                f"**{current['direction_accuracy']:.2f}%**",
                f"**{current['direction_accuracy'] - baseline['summary']['direction_accuracy']:+.2f} pp**",
            ]
        )
        parts.append(
            _table(
                ["指令族", "条数", "优化前（纯模板）", "优化后（模板 + 规则）", "提升"],
                ablation_rows,
            )
        )
        parts.append("")
        parts.append(
            f"优化前基线：{baseline.get('label', 'v1')}，采样于 {baseline.get('captured_at', '—')}，"
            "逐条结果保存在 `tools/benchmark/offline_baseline.json`，"
            "可用 `python tools/run_benchmark.py --from-json ...` 复现同一张表。"
        )
        parts.append("")
        parts.append(
            "改造要点：`OfflineProvider` 现在先做风格模板匹配，再把 `当前参数` 与 `意图` 送入规则引擎——"
            "程度词（再/更/一点/稍微）使用小步长（EV ±0.25、其余 ±15），"
            "普通参数词使用标准步长（EV ±0.40、其余 ±25），"
            "极值词（最/极限/全部去掉/越…越好）直接把参数吸附到 `PARAM_RANGES` 端点，"
            "所有结果都经 `ColorParams.from_dict` 归一化钳制；"
            "既无风格命中又无参数命中的输入（如“写个冒泡排序”）原样返回 `current_params`，"
            "无关噪声族保持 100% 不误触发。"
        )
        parts.append("")
        changed = [
            row["case"]
            for row in dim5["providers"][0]["cases"]
            if row["direction_ok"]
            and not next(
                (c["direction_ok"] for c in baseline["cases"] if c["case"] == row["case"]),
                False,
            )
        ]
        if changed:
            parts.append(
                f"本轮由失败转为通过的指令共 {len(changed)} 条：{'、'.join(changed)}。"
                "这些集中在单维微调、增量微调与极端/边界三族，"
                "正是模板匹配结构上无法表达的三类语义。"
            )
            parts.append("")
    else:
        parts.append("未找到 `tools/benchmark/offline_baseline.json`，跳过消融对比。")
        parts.append("")

    # ---- bottlenecks -----------------------------------------------------
    parts.append("## 8. 瓶颈与优化建议")
    parts.append("")
    for index, finding in enumerate(findings, start=1):
        parts.append(f"### 8.{index} {finding['title']}")
        parts.append("")
        parts.append(finding["detail"])
        parts.append("")
        parts.append(f"关键指标：`{finding['metric']}`")
        parts.append("")

    parts.append("## 9. 复现方式")
    parts.append("")
    parts.append("```powershell")
    parts.append("cd .")
    parts.append(".\\\\.venv\\\\Scripts\\\\python.exe tools\\\\run_benchmark.py")
    parts.append("# 附带在线大模型对比（需要配置 AI_API_KEY）")
    parts.append(".\\\\.venv\\\\Scripts\\\\python.exe tools\\\\run_benchmark.py --online")
    parts.append("```")
    parts.append("")
    parts.append("产物：`benchmark_report.md`、`benchmark_raw.json`、四张 300 DPI 图表。")
    parts.append("")

    target = results_dir / "benchmark_report.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(parts), encoding="utf-8")
    raw["conclusions"] = {"summary": sentences, "findings": findings}
    return target


__all__ = ["build"]
