// ============================================================================
// 【文件总体作用】
//   浏览器里的 WebGL2 实时视口。用户拖动调色参数时，这里用 3D LUT 立刻重画预览，
//   不等待 C++ 离屏工人。画面分三遍：调色、晕光、合成到屏幕。
//
// 【输入与输出】
//   输入：画布、<img> 或 <video>、Float32 的 LUT 采样、强度、晕光、分屏模式、缩放平移。
//   输出：画布上的预览像素，以及一块 64×64 离屏图读回后统计出的 RGB / 亮度直方图。
//
// 【核心图形学技术点】
//   内嵌 6 段 GLSL、静态图 generateMipmap 抗锯齿、视频流不做 mipmap、
//   3-Pass Ping-Pong FBO 光学晕光、A/B 分屏、64×64 直方图 FBO 与 readPixels。
// ============================================================================

// 【着色器】全幅采样用的顶点程序。Pass 1（调色）、Pass 2（抽高光 / 模糊）和直方图都用它。
// aPos 是单位正方形 [0,1]² 上的六个顶点（两个三角形）。
const VS_FULL = `#version 300 es
in vec2 aPos;          // 顶点属性：单位正方形坐标，来自 VBO，范围 [0,1]
out vec2 vUv;          // 传给片元着色器的纹理坐标，光栅器会在三角形内做重心插值
out vec2 vScreenUv;    // 合成着色器需要的屏幕坐标。全幅绘制时与 vUv 相同
void main() {
  vUv = aPos;          // 这套顶点把纹理坐标直接设成 aPos，片元拿到的就是图像上的位置
  vScreenUv = aPos;
  // 把 [0,1] 映射到裁剪空间 [-1,1]：左下 (0,0) → (-1,-1)，右上 (1,1) → (1,1)
  // z=0 无深度意义（主视口关了深度测试），w=1 表示不再做透视缩放
  gl_Position = vec4(aPos * 2.0 - 1.0, 0.0, 1.0);
}
`;

// 【着色器】只在第 3 遍（合成到屏幕）使用。
// 顶点仍铺满画布，片元按“屏幕 → 图像”的逆映射去取样。
// 正向关系（屏幕归一化坐标 s，图像坐标 u）：
//   s = 0.5 + uPan + (u - 0.5) * uAspect * uZoom
// 逆映射：
//   u = (s - 0.5 - uPan) / (uAspect * uZoom) + 0.5
// 所有量都是 [0,1] 归一化屏幕单位，与 devicePixelRatio 无关。
const VS_VIEW = `#version 300 es
in vec2 aPos;            // 画布上的单位正方形顶点，也就是屏幕归一化坐标 s
out vec2 vUv;            // 逆映射得到的图像坐标，落在 [0,1] 之外的部分是留白
out vec2 vScreenUv;      // 未经缩放 / 平移 / 信箱变换的屏幕坐标，A/B 分屏按它切
uniform vec2 uPan;       // 图像中心相对屏幕中心的平移（屏幕归一化单位）。x 正向右，y 正向上
uniform float uZoom;     // 图像显示放大倍数：1 为适配窗口，大于 1 画面变大，小于 1 画面变小
uniform vec2 uAspect;    // 适配窗口时图像占屏幕的比例 (ax, ay)。较长边为 1，另一边小于 1，形成信箱留白
void main() {
  vScreenUv = aPos;
  // 先去掉平移，再除以图像在屏幕上的尺寸（适配比例 × 放大倍数），回到以图像中心为原点的坐标
  vUv = (aPos - 0.5 - uPan) / (uAspect * uZoom) + 0.5;
  // 三角形本身始终铺满画布；变的是“这块屏幕去图像的哪里取样”
  gl_Position = vec4(aPos * 2.0 - 1.0, 0.0, 1.0);
}
`;

// 【着色器】第 1 遍：2D 原图采样 + 3D LUT 查表。算法与 shaders/grade.frag 相同，
// 差别只在 WebGL2 要写精度，以及信箱黑边（uv 出界）直接输出透明。
const FS_GRADE = `#version 300 es
precision highp float;       // 片元里的 float 用高精度，避免 Domain 除法和 LUT 坐标被吃掉小数
precision highp sampler3D;   // 3D 采样器同样高精度，三线性插值的权重才稳定
in vec2 vUv;
out vec4 fragColor;          // 写入调色 FBO 的颜色
uniform sampler2D uImage;    // 原图，纹理单元 0
uniform sampler3D uLut;      // 三维查找表，纹理单元 1，过滤为 LINEAR
uniform vec3 uDomainMin;     // .cube 的 DOMAIN_MIN，归一化前的下端
uniform vec3 uDomainMax;     // .cube 的 DOMAIN_MAX，归一化前的上端
uniform float uLutSize;      // 格子边长 N
uniform float uStrength;     // 混合强度 [0,1]
void main() {
  // 信箱或过度平移会让 uv 跑出图像。出界处不采样，写成全透明，合成阶段可据此当黑边
  if (vUv.x < 0.0 || vUv.x > 1.0 || vUv.y < 0.0 || vUv.y > 1.0) {
    fragColor = vec4(0.0);
    return;
  }
  vec4 src = texture(uImage, vUv);   // 编码域 sRGB。静态图若开了 mipmap，这里按层级过滤
  // Domain 归一化到 [0,1]，再夹紧，避免采样坐标掉进立方体外
  vec3 q = clamp((src.rgb - uDomainMin) / (uDomainMax - uDomainMin), 0.0, 1.0);
  // 半体素中心映射：把 [0,1] 输入区间映射到首尾体素中心 [0.5/N, 1-0.5/N]，
  // 避免边界处插值偏移半个体素（配合 CLAMP_TO_EDGE）
  vec3 tc = q * ((uLutSize - 1.0) / uLutSize) + vec3(0.5 / uLutSize);
  // sampler3D + LINEAR = 硬件 8 邻域三线性插值
  vec3 mapped = clamp(texture(uLut, tc).rgb, 0.0, 1.0);
  // mix(a,b,t) = a*(1-t)+b*t。t=0 原图，t=1 完全用 LUT
  vec3 graded = clamp(mix(src.rgb, mapped, uStrength), 0.0, 1.0);
  fragColor = vec4(graded, src.a);   // Alpha 原样保留
}
`;

// 【着色器】晕光第 1 步：从调色结果里抽出高光。
// 亮度用 BT.709 权重。smoothstep 做软拐点，避免亮部边缘变成硬切的光斑。
const FS_EXTRACT = `#version 300 es
precision highp float;
in vec2 vUv;
out vec4 fragColor;
uniform sampler2D uTex;      // 上一遍的调色结果
void main() {
  vec3 c = texture(uTex, vUv).rgb;
  // 编码域亮度代理：人眼对绿最敏感，所以 G 权重大约是 R 的 3 倍、B 的 10 倍
  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  // smoothstep(edge0, edge1, x)：x≤0.55 得 0，x≥0.82 得 1，中间是平滑的 S 形。
  // 门槛比 0.64 更早抬起，树叶边缘和次高光也能进入光晕，而不是只剩最亮的几个点。
  float t = smoothstep(0.55, 0.82, l);
  // rgb 乘上 t：暗的地方变成 0；alpha 槽里另存一份权重，便于看抽取掩码
  fragColor = vec4(c * t, t);
}
`;

// 【着色器】可分离高斯模糊的一遍。Ping-Pong 时先沿 X 再沿 Y，各做两次。
// 权重是 9 点高斯的一维切片，中心最高，向两侧衰减。
const FS_BLUR = `#version 300 es
precision highp float;
in vec2 vUv;
out vec4 fragColor;
uniform sampler2D uTex;    // 当前要模糊的那张半分辨率纹理
uniform vec2 uTexel;       // 一个纹素的宽高，即 (1/宽, 1/高)，用来把“第 i 个像素”换成纹理坐标
uniform vec2 uAxis;        // 模糊方向。(1,0) 水平，(0,1) 垂直
void main() {
  vec3 acc = vec3(0.0);    // 加权颜色累加
  float wsum = 0.0;        // 权重累加，最后相除，避免权重总和不精确时变亮或变暗
  // 下标 0 是中心权重，1..4 是离开中心 1 到 4 个像素的权重。左右共用同一权重。
  const float w[5] = float[5](0.227027, 0.1945948, 0.1216216, 0.054054, 0.016216);
  for (int i = -4; i <= 4; i++) {
    int j = abs(i);                        // 高斯左右对称，-i 与 +i 用同一个权重
    float wgt = w[j];
    vec2 off = uAxis * uTexel * float(i);  // 沿指定轴偏移 i 个纹素
    acc += texture(uTex, vUv + off).rgb * wgt;
    wsum += wgt;
  }
  fragColor = vec4(acc / wsum, 1.0);       // 归一化后的模糊颜色，alpha 固定为不透明
}
`;

// 【着色器】第 3 遍：把原图、调色结果、晕光合到一起，并实现 A/B 对比。
// 屏幕合成用 VS_VIEW（带缩放）；直方图用 VS_FULL（铺满整幅图像，不受平移影响）。
const FS_COMPOSITE = `#version 300 es
precision highp float;
in vec2 vUv;
in vec2 vScreenUv;            // 屏幕舞台坐标 [0,1]，与 DOM 分割线使用同一套坐标
out vec4 fragColor;
uniform sampler2D uImage;     // 原图，单元 0
uniform sampler2D uGraded;    // 调色 FBO，单元 1
uniform sampler2D uBloom;     // 模糊后的高光，单元 2
uniform float uBloomAmt;      // 晕光强度，0 表示不加
uniform float uSplitRatio;    // 分屏位置（屏幕舞台宽度的比例），0.5 表示从正中切开
uniform int uCompareMode;     // 0 只看效果，1 左右分屏，2 只看原图
void main() {
  // 信箱区域 uv 出界，输出透明，画布清屏色透出来成为黑边
  if (vUv.x < 0.0 || vUv.x > 1.0 || vUv.y < 0.0 || vUv.y > 1.0) {
    fragColor = vec4(0.0);
    return;
  }
  vec4 src = texture(uImage, vUv);
  vec3 graded = texture(uGraded, vUv).rgb;
  vec3 bloom = texture(uBloom, vUv).rgb;
  // 略偏暖的染色：R 抬一点、B 压一点，让高光更像光学光晕而不是纯白雾
  vec3 warm = bloom * vec3(1.05, 0.98, 0.92);
  // 0.85 是晕光混入调色结果的固定比例，再乘用户拉杆 uBloomAmt
  vec3 effect = graded + warm * uBloomAmt * 0.85;
  vec3 rgb = effect;
  if (uCompareMode == 2) {
    rgb = src.rgb;                                             // 只看调色前
  } else if (uCompareMode == 1) {
    // 按屏幕坐标切分，不受缩放、平移和信箱影响：左侧纯原图（无 LUT、无晕光），右侧 LUT + 晕光
    rgb = vScreenUv.x < uSplitRatio ? src.rgb : effect;
  }
  fragColor = vec4(rgb, 1.0);                                  // 预览本身不透，黑边已在上面处理
}
`;

export type CompareModeGl = 0 | 1 | 2;  // 0 效果，1 左右分屏，2 原图

export interface HistogramBins {
  r: Float32Array;
  g: Float32Array;
  b: Float32Array;
  luma: Float32Array;
  samples: number;
}

export type HistogramCallback = (bins: HistogramBins) => void;

const HIST_SIZE = 64;             // 直方图离屏目标边长。64×64 共 4096 个采样，足够看分布又很轻
const HIST_INTERVAL_MS = 100;     // 两次 readPixels 至少间隔 100 ms，避免回读拖住预览帧率
const MAX_UPLOAD_WIDTH = 1920;    // 视频上传前若宽于 1920，先在 2D canvas 上缩小
const MAX_GRADED_EDGE = 2560;     // 调色 / 晕光 FBO 的长边上限，避免 4K 源每帧全分辨率跑三遍
type FboPair = {
  fbo: WebGLFramebuffer;
  tex: WebGLTexture;
  w: number;
  h: number;
};

// 【模块功能】生成边长为 size 的恒等 LUT：格子颜色等于格子自身坐标。
// 顺序与 .cube 相同：B 最慢、R 最快，每个点连续写入 R、G、B 三个 float。
function buildIdentityLut(size: number): Float32Array {
  const out = new Float32Array(size ** 3 * 3);
  let i = 0;
  const denom = Math.max(1, size - 1);
  for (let b = 0; b < size; b++) {
    for (let g = 0; g < size; g++) {
      for (let r = 0; r < size; r++) {
        out[i++] = r / denom;
        out[i++] = g / denom;
        out[i++] = b / denom;
      }
    }
  }
  return out;
}

function isSourceReady(el: HTMLImageElement | HTMLVideoElement): boolean {
  if ("readyState" in el) {
    return el.readyState >= 2 && el.videoWidth > 0;
  }
  return el.complete && el.naturalWidth > 0;
}

// 【模块功能】视口类。构造时创建上下文、6 段着色器链成的 5 个程序、几何、纹理和直方图 FBO。
export class GlViewport {
  private canvas: HTMLCanvasElement;
  private gl: WebGL2RenderingContext;
  private vao: WebGLVertexArrayObject;
  private imageTex: WebGLTexture;
  private lutTex: WebGLTexture;
  private progGrade: WebGLProgram;
  private progExtract: WebGLProgram;
  private progBlur: WebGLProgram;
  private progComposite: WebGLProgram;
  private progCompositeFull: WebGLProgram;
  private locGrade = {} as Record<string, WebGLUniformLocation | null>;
  private locExtract = {} as Record<string, WebGLUniformLocation | null>;
  private locBlur = {} as Record<string, WebGLUniformLocation | null>;
  private locComposite = {} as Record<string, WebGLUniformLocation | null>;
  private locCompositeFull = {} as Record<string, WebGLUniformLocation | null>;
  private raf = 0;
  private source: HTMLImageElement | HTMLVideoElement | null = null;
  private frameReady = false;
  private scratchCanvas: HTMLCanvasElement | null = null;
  private scratchCtx: CanvasRenderingContext2D | null = null;
  private loopErrorLogged = false;
  private lastUploadedTime = -1;
  frames = 0;
  uploads = 0;
  private lutSize = 2;
  private domainMin: [number, number, number] = [0, 0, 0];
  private domainMax: [number, number, number] = [1, 1, 1];
  private strength = 1;
  private bloom = 0;
  private compareMode: CompareModeGl = 0;
  private splitRatio = 0.5;
  private zoom = 1;
  private panX = 0;
  private panY = 0;
  private imgAspect = 1;
  private imageMipmap = false;

  private graded: FboPair | null = null;
  private ping: FboPair | null = null;
  private pong: FboPair | null = null;
  // 晕光关闭时合成阶段采样这张常驻 1×1 黑纹理。不能拿 ping.tex 去改尺寸，
  // 否则半分辨率附件会被永久塌成 1×1，再打开晕光也只剩一个黑点。
  private blackTex: WebGLTexture;
  private fboW = 0;
  private fboH = 0;

  private histFbo: WebGLFramebuffer;
  private histTex: WebGLTexture;
  private histPixels = new Uint8Array(HIST_SIZE * HIST_SIZE * 4);
  private histCallback: HistogramCallback | null = null;
  private histDirty = true;
  private histLastAt = 0;
  private renderPaused = false;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    // alpha：画布可以透明，信箱黑边由着色器写成 0。
    // antialias：关。像素级预览不需要 MSAA，直方图回读也不希望被抗锯齿掺色。
    // premultipliedAlpha：关，与直通 RGBA 的上传约定一致，避免浏览器再乘一次 Alpha。
    // preserveDrawingBuffer：开，方便截图和外部工具在下一帧前读到刚画完的画布。
    const gl = canvas.getContext("webgl2", {
      alpha: true,
      antialias: false,
      premultipliedAlpha: false,
      preserveDrawingBuffer: true,
    });
    if (!gl) throw new Error("WebGL2 不可用");
    this.gl = gl;
    // 浮点纹理的线性过滤不是 WebGL2 核心必选能力。3D LUT 要用 GL_LINEAR，
    // 先尝试打开 OES_texture_float_linear；失败时 uploadLut 会退回 RGB32F 再试。
    gl.getExtension("OES_texture_float_linear");
    this.progGrade = this.createProgram(VS_FULL, FS_GRADE);
    this.progExtract = this.createProgram(VS_FULL, FS_EXTRACT);
    this.progBlur = this.createProgram(VS_FULL, FS_BLUR);
    this.progComposite = this.createProgram(VS_VIEW, FS_COMPOSITE);
    this.progCompositeFull = this.createProgram(VS_FULL, FS_COMPOSITE);
    this.vao = gl.createVertexArray()!;
    this.imageTex = gl.createTexture()!;
    this.lutTex = gl.createTexture()!;
    this.blackTex = gl.createTexture()!;
    this.histFbo = gl.createFramebuffer()!;
    this.histTex = gl.createTexture()!;
    this.initGeometry();
    this.initTextures();
    this.initHistogramTarget();
    this.bindAllLocations();
    this.uploadPlaceholderImage();
    this.uploadLut(buildIdentityLut(2), 2, [0, 0, 0], [1, 1, 1]);
    // 预览画布需要混合：信箱区域 alpha=0 时透出清屏色。调色数学本身在着色器里完成，不靠混合。
    gl.enable(gl.BLEND);
    // SRC_ALPHA / ONE_MINUS_SRC_ALPHA：标准直通 Alpha 混合，结果 = src.rgb*src.a + dst.rgb*(1-src.a)
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.disable(gl.DEPTH_TEST);  // 全屏四边形没有前后关系，深度测试只会干扰
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

  // 【模块功能】编译并链接一对顶点 / 片元着色器。失败时抛出驱动日志。
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

  // 【模块功能】上传一块盖住单位正方形的四边形（两个三角形、6 个顶点）。
  // 【渲染管线阶段】顶点拉取。所有全屏 Pass 共用这一个 VAO。
  private initGeometry(): void {
    const gl = this.gl;
    // 两个三角形：(0,0)-(1,0)-(0,1) 与 (0,1)-(1,0)-(1,1)，正好铺满 [0,1]²
    const quad = new Float32Array([0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 1]);
    const vbo = gl.createBuffer();
    gl.bindVertexArray(this.vao);                         // 之后的顶点属性状态记在这个 VAO 上
    gl.bindBuffer(gl.ARRAY_BUFFER, vbo);
    // STATIC_DRAW：顶点只上传一次，GPU 可以把它放在适合反复绘制的内存里
    gl.bufferData(gl.ARRAY_BUFFER, quad, gl.STATIC_DRAW);
    for (const prog of [
      this.progGrade,
      this.progExtract,
      this.progBlur,
      this.progComposite,
      this.progCompositeFull,
    ]) {
      gl.useProgram(prog);
      const loc = gl.getAttribLocation(prog, "aPos");
      gl.enableVertexAttribArray(loc);
      // size=2：每个顶点 2 个 float；normalized=false：坐标已经是数值，不要再从整数归一化
      // stride=0、offset=0：紧密排列，从缓冲开头读
      gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    }
    gl.bindVertexArray(null);
  }

  // 【模块功能】设定原图与 LUT 的过滤和包裹。真正的像素在随后的上传函数里写入。
  private initTextures(): void {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.imageTex);
    // 预览允许双线性。缩小时若后面打开 mipmap，MIN_FILTER 会改成 LINEAR_MIPMAP_LINEAR。
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    // 钳到边缘：信箱外的采样不会绕到图像对侧
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.bindTexture(gl.TEXTURE_3D, this.lutTex);
    // 3D + LINEAR：采样一个坐标时取周围 8 个格子做三线性插值，LUT 在格子之间才连续
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE);

    // 常驻 1×1 纯黑。尺寸只在这里写一次，渲染循环里不再改它，更不能拿它替换 ping。
    gl.bindTexture(gl.TEXTURE_2D, this.blackTex);
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
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  }

  // 【模块功能】按“这是不是静态大图”切换缩小过滤。
  // 静态图用 mipmap 金字塔消除缩小后的摩尔纹；视频每帧都在变，不建金字塔。
  private applyImageFilterMode(): void {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.imageTex);
    if (this.imageMipmap) {
      // LINEAR_MIPMAP_LINEAR：先在相邻两层 mip 上各做一次双线性，再在两层之间插值。
      // 缩小时取样来自分辨率接近屏幕的那一层，高频条纹不会折返成摩尔纹。
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
      // 放大没有更细的层可用，MAG 只能在第 0 层上双线性
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    } else {
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    }
  }

  // 【模块功能】准备 64×64 的直方图离屏目标。
  // 合成着色器用“铺满整图”的顶点程序画进这块 FBO，再用 readPixels 把 8 位颜色读回 CPU 统计。
  private initHistogramTarget(): void {
    const gl = this.gl;
    gl.bindTexture(gl.TEXTURE_2D, this.histTex);
    // 分配 64×64 的 RGBA8，data=null 表示只分配、不上传初始像素
    gl.texImage2D(
      gl.TEXTURE_2D,
      0,
      gl.RGBA8,
      HIST_SIZE,
      HIST_SIZE,
      0,
      gl.RGBA,
      gl.UNSIGNED_BYTE,
      null,
    );
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.histFbo);
    // 把 histTex 挂到颜色附件 0。之后画到这个 FBO 的结果就留在这张小纹理里
    gl.framebufferTexture2D(
      gl.FRAMEBUFFER,
      gl.COLOR_ATTACHMENT0,
      gl.TEXTURE_2D,
      this.histTex,
      0,
    );
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);  // 解绑，避免后续清屏误写到直方图
  }

  private bindProgramLocs(
    program: WebGLProgram,
    names: string[],
    bucket: Record<string, WebGLUniformLocation | null>,
  ): void {
    const gl = this.gl;
    gl.useProgram(program);
    for (const n of names) {
      bucket[n] = gl.getUniformLocation(program, n);
    }
  }

  private bindAllLocations(): void {
    this.bindProgramLocs(
      this.progGrade,
      ["uImage", "uLut", "uDomainMin", "uDomainMax", "uLutSize", "uStrength"],
      this.locGrade,
    );
    this.bindProgramLocs(this.progExtract, ["uTex"], this.locExtract);
    this.bindProgramLocs(this.progBlur, ["uTex", "uTexel", "uAxis"], this.locBlur);
    const viewShared = ["uPan", "uZoom", "uAspect"];
    this.bindProgramLocs(
      this.progComposite,
      [
        ...viewShared,
        "uImage",
        "uGraded",
        "uBloom",
        "uBloomAmt",
        "uSplitRatio",
        "uCompareMode",
      ],
      this.locComposite,
    );
    this.bindProgramLocs(
      this.progCompositeFull,
      ["uImage", "uGraded", "uBloom", "uBloomAmt", "uSplitRatio", "uCompareMode"],
      this.locCompositeFull,
    );
    const gl = this.gl;
    gl.useProgram(this.progGrade);
    gl.uniform1i(this.locGrade.uImage, 0);
    gl.uniform1i(this.locGrade.uLut, 1);
    gl.useProgram(this.progExtract);
    gl.uniform1i(this.locExtract.uTex, 0);
    gl.useProgram(this.progBlur);
    gl.uniform1i(this.locBlur.uTex, 0);
    gl.useProgram(this.progComposite);
    gl.uniform1i(this.locComposite.uImage, 0);
    gl.uniform1i(this.locComposite.uGraded, 1);
    gl.uniform1i(this.locComposite.uBloom, 2);
    gl.useProgram(this.progCompositeFull);
    gl.uniform1i(this.locCompositeFull.uImage, 0);
    gl.uniform1i(this.locCompositeFull.uGraded, 1);
    gl.uniform1i(this.locCompositeFull.uBloom, 2);
  }

  /** Exposed for acceptance tooling (B1 mipmap probe). */
  imageUsesMipmap(): boolean {
    return this.imageMipmap;
  }

  get sourceAspect(): number {
    return this.imgAspect;
  }

  private gradedPixelSize(): { w: number; h: number } {
    const src = this.source;
    if (!src) return { w: 1, h: 1 };
    const sw =
      "videoWidth" in src ? src.videoWidth : (src as HTMLImageElement).naturalWidth;
    const sh =
      "videoHeight" in src ? src.videoHeight : (src as HTMLImageElement).naturalHeight;
    if (sw <= 0 || sh <= 0) return { w: 1, h: 1 };
    const scale = Math.min(1, MAX_GRADED_EDGE / Math.max(sw, sh));
    return {
      w: Math.max(1, Math.floor(sw * scale)),
      h: Math.max(1, Math.floor(sh * scale)),
    };
  }

  private uploadPlaceholderImage(): void {
    const gl = this.gl;
    const pixel = new Uint8Array([128, 128, 128, 255]);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.imageTex);
    gl.texImage2D(
      gl.TEXTURE_2D,
      0,
      gl.RGBA,
      1,
      1,
      0,
      gl.RGBA,
      gl.UNSIGNED_BYTE,
      pixel,
    );
    this.imageMipmap = false;
    this.applyImageFilterMode();
  }

  onHistogram(cb: HistogramCallback | null): void {
    this.histCallback = cb;
    this.histDirty = true;
  }

  setSource(el: HTMLImageElement | HTMLVideoElement | null): void {
    this.source = el;
    this.frameReady = false;
    this.lastUploadedTime = -1;
    this.histDirty = true;
    this.imageMipmap = false;
    if (el) {
      const w = "videoWidth" in el ? el.videoWidth : el.naturalWidth;
      const h = "videoHeight" in el ? el.videoHeight : el.naturalHeight;
      if (w > 0 && h > 0) this.imgAspect = w / h;
    }
  }

  notifySourceReady(): void {
    this.frameReady = false;
    this.lastUploadedTime = -1;
    this.histDirty = true;
    this.histLastAt = 0;
    this.drawFrame();
  }

  private get sourceIsVideo(): boolean {
    return this.source !== null && "videoWidth" in this.source;
  }

  get hasSource(): boolean {
    return this.source !== null;
  }

  // 【模块功能】把烘焙好的 LUT 上传成三维浮点纹理。
  // 【关键参数】samples 长度必须是 size³×3，顺序 R 最快、B 最慢。
  // 【渲染管线阶段】纹理上传。优先 RGB16F（省带宽），驱动不接受时退回 RGB32F。
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
    // 清掉更早留下的错误标志，否则紧接着的 RGB16F 失败会被误判成“上一回的错”。
    let stale = gl.getError();
    while (stale !== gl.NO_ERROR) stale = gl.getError();
    // texImage3D：level=0，internalFormat 先试半精度浮点 RGB16F。
    // 源数据是 RGB float。WebGL 要求源类型 FLOAT 搭配浮点内部格式。
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
      // 半精度不被接受时改用 32 位浮点，数值与 CPU 烘焙完全同宽。
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
    // 上传会重置部分采样状态，这里重新钉死三线性插值和三轴钳边。
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_WRAP_R, gl.CLAMP_TO_EDGE);
    this.histDirty = true;
    this.histLastAt = 0;
  }

  setStrength(v: number): void {
    this.strength = v;
    this.histDirty = true;
  }

  setBloom(v: number): void {
    this.bloom = Math.min(1, Math.max(0, v));
    this.histDirty = true;
  }

  /** 切到 3D 色彩立方体时暂停主视口绘制以节省 GPU */
  setRenderPaused(paused: boolean): void {
    this.renderPaused = paused;
  }

  setCompare(mode: CompareModeGl, split = 0.5): void {
    this.compareMode = mode;
    this.splitRatio = split;
    this.histDirty = true;
  }

  setViewTransform(zoom: number, panX: number, panY: number): void {
    this.zoom = zoom;
    this.panX = panX;
    this.panY = panY;
  }

  fitToCanvas(): void {
    this.zoom = 1;
    this.panX = 0;
    this.panY = 0;
  }

  /**
   * 把鼠标位置换算成图像纹理坐标 (u, v)，v=1 为图像顶部；落在留白处返回 null。
   * 与 VS_VIEW 的逆映射保持同一公式：u = (s - 0.5 - uPan) / (uAspect * uZoom) + 0.5。
   */
  clientToImageUv(clientX: number, clientY: number): { u: number; v: number } | null {
    const rect = this.canvas.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return null;
    const sx = (clientX - rect.left) / rect.width;
    const sy = 1 - (clientY - rect.top) / rect.height;
    const { ax, ay } = this.computeAspect(this.canvas.width, this.canvas.height);
    const u = (sx - 0.5 - this.panX) / (ax * this.zoom) + 0.5;
    const v = (sy - 0.5 - this.panY) / (ay * this.zoom) + 0.5;
    if (u < 0 || u > 1 || v < 0 || v > 1) return null;
    return { u, v };
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

  // 【模块功能】按当前图像尺寸准备三张离屏缓冲。
  // graded 与图像同分辨率（长边不超过 2560）；ping / pong 是半分辨率，供晕光来回画。
  private ensureFbos(): void {
    const { w, h } = this.gradedPixelSize();
    if (this.graded && this.fboW === w && this.fboH === h) return;
    this.disposeFbos();
    this.fboW = w;
    this.fboH = h;
    this.graded = this.createColorFbo(w, h);
    // 晕光在半分辨率上做。模糊核对高频不敏感，分辨率减半后像素数变为 1/4。
    const hw = Math.max(1, Math.floor(w / 2));
    const hh = Math.max(1, Math.floor(h / 2));
    this.ping = this.createColorFbo(hw, hh);
    this.pong = this.createColorFbo(hw, hh);
  }

  // 【模块功能】创建一张 RGBA8 颜色纹理，并把它挂到新建 FBO 的颜色附件 0。
  private createColorFbo(w: number, h: number): FboPair {
    const gl = this.gl;
    const tex = gl.createTexture()!;
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    const fbo = gl.createFramebuffer()!;
    gl.bindFramebuffer(gl.FRAMEBUFFER, fbo);
    gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    return { fbo, tex, w, h };
  }

  private disposeFbos(): void {
    const gl = this.gl;
    for (const pair of [this.graded, this.ping, this.pong]) {
      if (!pair) continue;
      gl.deleteFramebuffer(pair.fbo);
      gl.deleteTexture(pair.tex);
    }
    this.graded = this.ping = this.pong = null;
    this.fboW = this.fboH = 0;
  }

  // 【模块功能】把当前图像或视频帧上传到 2D 纹理。
  // 静态图随后 generateMipmap，生成 1/2、1/4… 的金字塔，缩小时用它消除摩尔纹。
  // 视频每帧都变，建金字塔的开销大于收益，因此只保留第 0 层，并用双线性过滤。
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
    // WebGL 的纹理原点在左下，图片和视频的第 0 行在顶部。打开翻转后上传结果才是正的。
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
        // 从第 0 层逐级盒式下采样，直到 1×1。之后 MIN_FILTER 必须改成带 MIPMAP 的模式，纹理才完整。
        gl.generateMipmap(gl.TEXTURE_2D);
        this.imageMipmap = true;
      } else {
        // 视频流隔离：不调用 generateMipmap，避免每帧重建金字塔，也避免用过期层级采样。
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

  private computeAspect(viewW: number, viewH: number): { aspect: number; ax: number; ay: number } {
    const aspect = viewW / viewH;
    let ax = 1;
    let ay = 1;
    if (this.imgAspect > aspect) {
      ay = aspect / this.imgAspect;
    } else {
      ax = this.imgAspect / aspect;
    }
    return { aspect, ax, ay };
  }

  private setQuadUniforms(
    program: WebGLProgram,
    locs: Record<string, WebGLUniformLocation | null>,
    viewW: number,
    viewH: number,
  ): { ax: number; ay: number; aspect: number } {
    const { aspect, ax, ay } = this.computeAspect(viewW, viewH);
    const gl = this.gl;
    gl.useProgram(program);
    if (locs.uAspect) gl.uniform2f(locs.uAspect, ax, ay);
    if (locs.uPan) gl.uniform2f(locs.uPan, this.panX, this.panY);
    if (locs.uZoom) gl.uniform1f(locs.uZoom, this.zoom);
    return { ax, ay, aspect };
  }

  private drawQuad(): void {
    const gl = this.gl;
    gl.bindVertexArray(this.vao);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
    gl.bindVertexArray(null);
  }

  // 【渲染管线阶段】第 1 遍。绑定调色 FBO，原图在单元 0，LUT 在单元 1，画满目标分辨率。
  // 离屏写入关掉混合：片元颜色直接覆盖附件，避免全局 SRC_ALPHA 把结果再乘一次 alpha。
  private passGrade(target: FboPair): void {
    const gl = this.gl;
    gl.disable(gl.BLEND);
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

  // 【渲染管线阶段】第 2 遍。先把高光抽到 ping（半分辨率），再水平 / 垂直各模糊两轮。
  // ping 与 pong 交替当读写目标，这就是 Ping-Pong：同一张纹理不能同时读和写。
  // 抽取着色器写出 vec4(c*t, t)。若此时仍开着混合，RGB 会再乘一次 t，高光被削掉一层。
  private passBloomChain(): void {
    const gl = this.gl;
    if (!this.graded || !this.ping || !this.pong) return;
    gl.disable(gl.BLEND);

    gl.bindFramebuffer(gl.FRAMEBUFFER, this.ping.fbo);
    gl.viewport(0, 0, this.ping.w, this.ping.h);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(this.progExtract);
    gl.uniform1i(this.locExtract.uTex, 0);
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, this.graded.tex);
    this.drawQuad();

    const blurPass = (
      src: FboPair,
      dst: FboPair,
      axisX: number,
      axisY: number,
      texelScale: number,
    ): void => {
      gl.bindFramebuffer(gl.FRAMEBUFFER, dst.fbo);
      gl.viewport(0, 0, dst.w, dst.h);
      gl.useProgram(this.progBlur);
      gl.uniform1i(this.locBlur.uTex, 0);
      // texelScale=1 时偏移 1 个纹素；第 2 轮传 2，等价于着色器里的 2.0 * uTexel，光晕扩散更开。
      gl.uniform2f(this.locBlur.uTexel, texelScale / src.w, texelScale / src.h);
      gl.uniform2f(this.locBlur.uAxis, axisX, axisY);
      gl.activeTexture(gl.TEXTURE0);
      gl.bindTexture(gl.TEXTURE_2D, src.tex);
      this.drawQuad();
    };

    for (let round = 0; round < 2; round++) {
      const texelScale = round === 0 ? 1 : 2;
      blurPass(this.ping, this.pong, 1, 0, texelScale);  // 水平：轴 (1, 0)
      blurPass(this.pong, this.ping, 0, 1, texelScale);  // 垂直：轴 (0, 1)，结果回到 ping
    }
  }

  // 【渲染管线阶段】第 3 遍，画到屏幕（targetFbo 为 null 即默认帧缓冲）或指定 FBO。
  // 三个纹理单元：0 原图、1 调色、2 晕光。分屏与对比模式由 uniform 决定。
  private passComposite(
    targetFbo: WebGLFramebuffer | null,
    viewW: number,
    viewH: number,
    bloomTex: WebGLTexture,
  ): void {
    const gl = this.gl;
    // 只有上屏这一遍恢复混合，信箱区域 alpha=0 才能透出清屏色。离屏两遍在各自入口关掉混合。
    gl.enable(gl.BLEND);
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

  /** Histogram / analytics: full-image UV, preview mode only. */
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

  private renderOffscreenBloomTex(): WebGLTexture | null {
    this.ensureFbos();
    if (!this.graded || !this.ping) return null;

    this.passGrade(this.graded);

    if (this.bloom > 0.001) {
      this.passBloomChain();
      return this.ping.tex;
    }
    // 强度为 0 时不改 ping 的尺寸，合成直接采样常驻黑纹理，画面立刻回到锐利原图。
    return this.blackTex;
  }

  private renderPipeline(
    targetFbo: WebGLFramebuffer | null,
    viewW: number,
    viewH: number,
  ): void {
    const bloomTex = this.renderOffscreenBloomTex();
    if (!bloomTex) return;
    this.passComposite(targetFbo, viewW, viewH, bloomTex);
    if (targetFbo === null) {
      this.gl.bindFramebuffer(this.gl.FRAMEBUFFER, null);
    }
  }

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

  // 【模块功能】把当前效果画进 64×64 直方图 FBO，再 readPixels 回 CPU 做 256 档统计。
  private sampleHistogram(): HistogramBins | null {
    const gl = this.gl;
    const bloomTex = this.renderOffscreenBloomTex();
    if (!bloomTex) return null;
    this.passCompositeFull(this.histFbo, HIST_SIZE, HIST_SIZE, bloomTex);
    gl.bindFramebuffer(gl.FRAMEBUFFER, this.histFbo);
    // 从直方图 FBO 左下角读 64×64 个 RGBA8 像素到 histPixels。这是同步回读，会等 GPU 画完。
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
      // BT.709 亮度权重，与抽高光着色器里的系数相同，保证直方图亮度和光晕判据一致。
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

  startLoop(): void {
    if (this.raf) return;
    const tick = () => {
      this.raf = requestAnimationFrame(tick);
      try {
        this.drawFrame();
      } catch (err) {
        if (!this.loopErrorLogged) {
          this.loopErrorLogged = true;
          console.error("[gl] render loop error", err);
        }
      }
    };
    this.raf = requestAnimationFrame(tick);
  }

  stopLoop(): void {
    if (this.raf) {
      cancelAnimationFrame(this.raf);
      this.raf = 0;
    }
  }

  destroy(): void {
    this.stopLoop();
    this.disposeFbos();
  }
}
