// ============================================================================
// 【文件总体作用】
//   调色结果的三维点云视图。把 LUT 在 RGB 立方体里的映射画成可旋转的点，
//   用来在答辩和调试时直观看到“这个颜色被送到了哪里”。
//
// 【输入与输出】
//   输入：画布、LUT 采样、边长、Domain。交互为拖拽旋转、滚轮推拉、双击复位。
//   输出：带线框和 RGB 坐标轴的 17³ 点云。点的位置是查表后的颜色，点的颜色也是该颜色。
//
// 【核心图形学技术点】
//   17³ = 4913 个采样点、4×4 齐次矩阵拼出的 MVP、深度测试、
//   gl_PointCoord 圆形裁剪（方点片元里丢掉圆外的像素）。
// ============================================================================

const GRID = 17;  // 点云固定 17×17×17。LUT 本身可以更密，这里只取样展示，避免一次画上万个点

// 【着色器】线框与坐标轴。每个顶点带位置和颜色，乘上 MVP 后写入裁剪空间。
const VS_LINES = `#version 300 es
layout(location = 0) in vec3 aPos;    // 物体空间位置，立方体中心在原点，边长为 1，范围 [-0.5, 0.5]
layout(location = 1) in vec3 aColor;  // 顶点颜色，线框是暗灰，三条轴分别偏红、偏绿、偏蓝
uniform mat4 uMvp;                    // 模型-视图-投影矩阵，列主序，与 gl.uniformMatrix4fv 一致
out vec3 vColor;                      // 传给片元，线段上的颜色由两端顶点插值
void main() {
  vColor = aColor;
  // vec4(aPos, 1.0)：w=1 表示这是一个点，不是方向。平移列会对它生效
  gl_Position = uMvp * vec4(aPos, 1.0);
}
`;

// 【着色器】线框片元。没有光照，颜色直接写出。
const FS_LINES = `#version 300 es
precision highp float;
in vec3 vColor;
out vec4 fragColor;
void main() {
  fragColor = vec4(vColor, 1.0);  // 不透明。深度测试负责让近处的线挡住远处的线
}
`;

// 【着色器】点云顶点。除了变换位置，还按视距改点的像素大小。
const VS_POINTS = `#version 300 es
layout(location = 0) in vec3 aPos;    // 查表后的颜色，已减去 0.5，使立方体中心落在原点
layout(location = 1) in vec3 aColor;  // 与位置对应的 RGB，用来给点上色
uniform mat4 uMvp;
out vec3 vColor;
void main() {
  vColor = aColor;
  vec4 clip = uMvp * vec4(aPos, 1.0);           // 裁剪空间坐标，透视除法前
  gl_Position = clip;
  // 透视除法后的深度大约是 clip.z / clip.w。这里用 -clip.z 当“离相机有多近”的代理：
  // 视图矩阵把相机放在 -Z，物体在相机前方时 clip.z 为负，取负后变正。
  // max(0.05, ...) 防止除以过小的数把点放得无限大。
  float ndcScale = 1.0 / max(0.05, -clip.z);
  // 近处的点更大。夹在 2 到 18 像素之间，避免远点消失、近点糊成一块
  gl_PointSize = clamp(2.5 + ndcScale * 10.0, 2.0, 18.0);
}
`;

// 【着色器】把方点裁成圆。gl_PointCoord 是点精灵内部坐标，左下 (0,0)，右上 (1,1)。
const FS_POINTS = `#version 300 es
precision highp float;
in vec3 vColor;
out vec4 fragColor;
void main() {
  vec2 d = gl_PointCoord - vec2(0.5);  // 移到点精灵中心
  // 到中心的距离平方 > 0.5² 就在圆外。discard 丢掉这个片元，既不写颜色也不写深度
  if (dot(d, d) > 0.25) discard;
  fragColor = vec4(vColor, 1.0);
}
`;

// 【着色器】取样点标记。固定像素大小，琥珀色外环 + 深色内描边 + 中心填充该点颜色。
const VS_MARKER = `#version 300 es
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aColor;
uniform mat4 uMvp;
uniform float uSize;   // 点精灵边长（设备像素）
out vec3 vColor;
void main() {
  vColor = aColor;
  gl_Position = uMvp * vec4(aPos, 1.0);
  gl_PointSize = uSize;
}
`;

const FS_MARKER = `#version 300 es
precision highp float;
in vec3 vColor;
out vec4 fragColor;
void main() {
  float d = length(gl_PointCoord - vec2(0.5));
  if (d > 0.5) discard;
  vec3 ring = vec3(1.0, 0.71, 0.32);
  vec3 c = d > 0.38 ? ring : (d > 0.31 ? vec3(0.04) : vColor);
  fragColor = vec4(c, 1.0);
}
`;

export type Vec3 = [number, number, number];

function clamp01(v: number): number {
  return Math.min(1, Math.max(0, v));
}

// 【模块功能】在 CPU 上直接按格点下标做三线性插值，用来把任意 LUT 重采样到 17³ 点云。
// 结果与 GPU 半体素映射后的硬件插值等价：两者都让 q=0/1 精确命中首尾格点。
export function sampleLutTrilinear(
  samples: Float32Array,
  size: number,
  domainMin: Vec3,
  domainMax: Vec3,
  r: number,
  g: number,
  b: number,
): Vec3 {
  const q: Vec3 = [
    // 各通道按 Domain 归一化。分母为 0 时用 1，避免 Domain 端点重合时出现 NaN
    clamp01((r - domainMin[0]) / (domainMax[0] - domainMin[0] || 1)),
    clamp01((g - domainMin[1]) / (domainMax[1] - domainMin[1] || 1)),
    clamp01((b - domainMin[2]) / (domainMax[2] - domainMin[2] || 1)),
  ];
  // CPU 直接在格点上插值：q 乘 (N-1) 就是连续网格下标，q=0 落在第 0 格，q=1 落在第 N-1 格。
  // 半体素偏移只属于 GPU 纹理坐标；这里若再套一次，角点会向内收缩。
  const x = q[0] * (size - 1);
  const y = q[1] * (size - 1);
  const z = q[2] * (size - 1);
  const x0 = Math.min(size - 1, Math.floor(x));
  const y0 = Math.min(size - 1, Math.floor(y));
  const z0 = Math.min(size - 1, Math.floor(z));
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

// 【模块功能】生成 17³ = 4913 个点。位置是查表后的 RGB 减 0.5（立方体中心对齐原点），颜色就是该 RGB。
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

// 【模块功能】单位立方体的 12 条棱，外加从原点指出的 RGB 三轴。
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

// 下面这组矩阵都是列主序：下标 0,4,8,12 是第一列。与 WebGL 的 uniformMatrix4fv 约定一致。
// 齐次坐标 (x, y, z, w)，点的 w=1，方向的 w=0。

function mat4Identity(): Mat4 {
  const m = new Float32Array(16);
  m[0] = m[5] = m[10] = m[15] = 1;
  return m;
}

// 【模块功能】4×4 矩阵相乘，o = a * b。按列遍历，使结果仍是列主序。
// 变换顺序是先乘 b 再乘 a：点先被 b 作用，再被 a 作用。
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

// 【模块功能】对称透视投影。fovY 是竖直张角（弧度），aspect = 宽/高，near/far 是近远裁剪面。
// 看 -Z 方向。矩阵把视锥压进裁剪空间的 [-w, w] 盒子，透视除法后再落到 NDC [-1,1]。
function mat4Perspective(fovY: number, aspect: number, near: number, far: number): Mat4 {
  const f = 1 / Math.tan(fovY / 2);  // 焦距。张角越小，f 越大，画面越“望远”
  const m = new Float32Array(16);
  m[0] = f / aspect;                         // X 缩放，除以宽高比，避免窗口变宽时物体被拉扁
  m[5] = f;                                  // Y 缩放
  m[10] = (far + near) / (near - far);       // Z 映射到裁剪空间，近远平面不再保持线性距离
  m[11] = -1;                                // 这一项把 z 写进 w，透视除法时用 -z 做除数，产生近大远小
  m[14] = (2 * far * near) / (near - far);   // 平移项，保证 near 投到 NDC z=-1、far 投到 NDC z=+1
  return m;
}

// 绕 X 轴旋转。Y/Z 组成的 2×2 是 [cos, -sin; sin, cos] 在列主序里的摆法：
// m[5]=cos，m[6]=sin，m[9]=-sin，m[10]=cos。X 分量不动。
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

// 绕 Y 轴旋转。X/Z 平面转动，Y 分量保持。右手系里正角度把 +Z 转向 +X。
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

// 平移。列主序的第 4 列（下标 12、13、14）就是齐次矩阵里的平移 (x, y, z)。
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
  private progMarker: WebGLProgram;
  private locMarkerMvp: WebGLUniformLocation | null;
  private locMarkerSize: WebGLUniformLocation | null;
  private probeLineVao: WebGLVertexArrayObject;
  private probeLinePos: WebGLBuffer;
  private probeLineCol: WebGLBuffer;
  private probePointVao: WebGLVertexArrayObject;
  private probePointPos: WebGLBuffer;
  private probePointCol: WebGLBuffer;
  private probeActive = false;
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
    this.progMarker = this.createProgram(VS_MARKER, FS_MARKER);
    this.locMarkerMvp = gl.getUniformLocation(this.progMarker, "uMvp");
    this.locMarkerSize = gl.getUniformLocation(this.progMarker, "uSize");
    this.probeLineVao = gl.createVertexArray()!;
    this.probeLinePos = gl.createBuffer()!;
    this.probeLineCol = gl.createBuffer()!;
    this.probePointVao = gl.createVertexArray()!;
    this.probePointPos = gl.createBuffer()!;
    this.probePointCol = gl.createBuffer()!;
    this.initWireframe();
    this.initPointVao();
    this.initProbeVao(this.probeLineVao, this.probeLinePos, this.probeLineCol);
    this.initProbeVao(this.probePointVao, this.probePointPos, this.probePointCol);
    this.uploadPoints(new Float32Array(3), new Float32Array(3));
    // 点与线有前后关系，必须开深度测试，否则后画的点会无条件盖住前面的线。
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

  private initProbeVao(vao: WebGLVertexArrayObject, pos: WebGLBuffer, col: WebGLBuffer): void {
    const gl = this.gl;
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, pos);
    gl.bufferData(gl.ARRAY_BUFFER, 24, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ARRAY_BUFFER, col);
    gl.bufferData(gl.ARRAY_BUFFER, 24, gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 3, gl.FLOAT, false, 0, 0);
    gl.bindVertexArray(null);
  }

  /**
   * 标注一个取样点：src 为原色（立方体中的输入位置），mapped 为 LUT 输出位置。
   * 传 null 清除标注。
   */
  setProbe(src: Vec3 | null, mapped?: Vec3): void {
    if (!src || !mapped) {
      this.probeActive = false;
      return;
    }
    const gl = this.gl;
    const pos = new Float32Array([
      src[0] - 0.5, src[1] - 0.5, src[2] - 0.5,
      mapped[0] - 0.5, mapped[1] - 0.5, mapped[2] - 0.5,
    ]);
    const lineCol = new Float32Array([0.55, 0.4, 0.2, 1.0, 0.71, 0.32]);
    const pointCol = new Float32Array([...src, ...mapped]);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.probeLinePos);
    gl.bufferData(gl.ARRAY_BUFFER, pos, gl.DYNAMIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.probeLineCol);
    gl.bufferData(gl.ARRAY_BUFFER, lineCol, gl.DYNAMIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.probePointPos);
    gl.bufferData(gl.ARRAY_BUFFER, pos, gl.DYNAMIC_DRAW);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.probePointCol);
    gl.bufferData(gl.ARRAY_BUFFER, pointCol, gl.DYNAMIC_DRAW);
    this.probeActive = true;
  }

  private drawProbe(mvp: Mat4): void {
    if (!this.probeActive) return;
    const gl = this.gl;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    // 标注始终画在最上层，不被点云遮挡
    gl.disable(gl.DEPTH_TEST);
    gl.useProgram(this.progLines);
    gl.uniformMatrix4fv(this.locLineMvp, false, mvp);
    gl.bindVertexArray(this.probeLineVao);
    gl.drawArrays(gl.LINES, 0, 2);
    gl.useProgram(this.progMarker);
    gl.uniformMatrix4fv(this.locMarkerMvp, false, mvp);
    gl.bindVertexArray(this.probePointVao);
    gl.uniform1f(this.locMarkerSize, 12 * dpr);
    gl.drawArrays(gl.POINTS, 0, 1);
    gl.uniform1f(this.locMarkerSize, 20 * dpr);
    gl.drawArrays(gl.POINTS, 1, 1);
    gl.bindVertexArray(null);
    gl.enable(gl.DEPTH_TEST);
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

  // 【模块功能】拼 MVP。点先绕 X（俯仰）再绕 Y（偏航），再沿 -Z 拉开相机，最后做透视。
  // 矩阵乘法从右往左作用于点：MVP * p = proj * view * rot * p。
  private mvpMatrix(): Mat4 {
    const aspect = this.canvas.width / this.canvas.height;
    const proj = mat4Perspective((50 * Math.PI) / 180, aspect, 0.05, 20);  // 竖直 50°，近 0.05，远 20
    const view = mat4Translate(0, 0, -this.distance);                       // 把物体推到相机前方 distance 处
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
    // 颜色和深度一起清。不清深度的话，上一帧的远近关系会残留，本帧的点会被错误挡住。
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    const mvp = this.mvpMatrix();

    gl.useProgram(this.progLines);
    // transpose=false：传入的 Float32Array 已经是列主序，不要再转置
    gl.uniformMatrix4fv(this.locLineMvp, false, mvp);
    gl.bindVertexArray(this.lineVao);
    gl.drawArrays(gl.LINES, 0, this.lineCount);  // 每两个顶点一条线段

    gl.useProgram(this.progPoints);
    gl.uniformMatrix4fv(this.locPointMvp, false, mvp);
    gl.bindVertexArray(this.pointVao);
    gl.drawArrays(gl.POINTS, 0, this.pointCount);  // 每个顶点一个点精灵，片元里再裁成圆
    gl.bindVertexArray(null);
    this.drawProbe(mvp);
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