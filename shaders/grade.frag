// ============================================================================
// 【文件总体作用】
//   离屏调色引擎的片元着色器。每个像素做一次 3D LUT 查表：
//   先按 Domain 把编码域 sRGB 归一化，再做半体素中心校正，
//   交给 sampler3D 的硬件三线性插值，最后按强度与原色混合。
//   整条管线不做自动 sRGB↔线性转换（ADR-004）：进来是编码域，出去仍是编码域。
//
// 【输入与输出】
//   输入：vUv（全屏三角形插值出的纹理坐标）、uImage（原图 RGBA8）、
//         uLut（RGB32F 三维查找表）、Domain 端点、LUT 边长、混合强度。
//   输出：fragColor，RGB 为调色结果，Alpha 原样拷贝，不参与查表。
//
// 【核心技术点】
//   Domain 归一化、半体素偏移 0.5/N、sampler3D 硬件三线性插值、mix 强度混合。
// ============================================================================
#version 330 core

// 顶点着色器写出、光栅器按像素插值后的纹理坐标，范围在视口内约为 [0,1]。
in vec2 vUv;

// 当前片元写入帧缓冲的颜色。布局由 FBO 的 GL_RGBA8 颜色附件决定，
// 写出时硬件会把 [0,1] 浮点量化成 8 位无符号字节。
out vec4 fragColor;

// 原图：2D 纹理，引擎侧过滤为 GL_NEAREST，一个片元对应一个纹素，避免额外模糊。
uniform sampler2D uImage;

// 三维查找表。过滤为 GL_LINEAR，采样时硬件在 R/G/B 三个轴上各取相邻两层，
// 共 8 个邻域体素做三线性插值。
uniform sampler3D uLut;

// .cube 文件里的 DOMAIN_MIN / DOMAIN_MAX。
// 输入颜色先映射进这个区间，再送进单位立方体 [0,1]^3。
uniform vec3 uDomainMin;
uniform vec3 uDomainMax;

// LUT 每条轴的格点数 N（常见 17、33、65）。用 float 是为了直接参与坐标运算。
uniform float uLutSize;

// 调色强度，范围 [0,1]。0 表示完全保留原图，1 表示完全采用 LUT 结果。
uniform float uStrength;

void main() {
    // 在 vUv 处读取原图像素。texture() 使用该 sampler 当前绑定的过滤与包裹模式。
    // src.rgb 是编码域 sRGB，数值约在 [0,1]；src.a 是直通 Alpha，后面原样写回。
    vec4 src = texture(uImage, vUv);

    // Domain 归一化：把 [domainMin, domainMax] 线性映射到 [0,1]。
    // CPU 已保证每个通道 max > min，这里不会除以 0。
    // clamp 把落在 Domain 外面的颜色按到立方体表面，避免采样坐标跑出纹理。
    vec3 q = clamp((src.rgb - uDomainMin) / (uDomainMax - uDomainMin), 0.0, 1.0);

    // 半体素中心映射。
    // 一条轴上有 N 个纹素时，第 i 个纹素的中心在纹理坐标 (i + 0.5) / N。
    // 这里把 [0, 1] 输入区间映射到纹理首尾体素中心 [0.5/N, 1 - 0.5/N]：
    //   tc = q * (N - 1) / N + 0.5 / N
    // q=0 恰好取第一格的值，q=1 恰好取最后一格的值，中间按相邻格点线性插值。
    // 若直接用 q 采样，边界处会偏移半个体素；配合 GL_CLAMP_TO_EDGE，坐标也不会越过首尾中心。
    vec3 tc = q * ((uLutSize - 1.0) / uLutSize) + vec3(0.5 / uLutSize);

    // texture(sampler3D, tc) 触发硬件三线性插值：xyz 三个方向各找左右两格，
    // 8 个角点按距离加权，得到连续的 RGB。再 clamp 回 [0,1]，防止 LUT 里的
    // 越界浮点在量化前溢出。
    vec3 mapped = clamp(texture(uLut, tc).rgb, 0.0, 1.0);

    // mix(a, b, t) = a * (1 - t) + b * t。
    // t = uStrength：0 取原图，1 取 LUT 颜色，中间是两者的线性混合。
    // 混合发生在编码域 sRGB，与 CPU 参考实现 apply_effect_to_rgb 一致。
    vec3 rgb = clamp(mix(src.rgb, mapped, uStrength), 0.0, 1.0);

    // Alpha 不进 LUT。直通拷贝，保证透明通道与输入逐字节一致（量化前的浮点 Alpha）。
    fragColor = vec4(rgb, src.a);
}
