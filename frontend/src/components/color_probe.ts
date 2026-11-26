import { sampleLutTrilinear, type Vec3 } from "../core/lut_cube_view";

export interface LutSnapshot {
  samples: Float32Array;
  size: number;
  domainMin: Vec3;
  domainMax: Vec3;
}

type MediaSource = HTMLImageElement | HTMLVideoElement;

/** 与 FS_GRADE 相同：LUT 查表后按强度与原色线性混合，再夹紧到 [0,1] */
export function gradeColor(src: Vec3, lut: LutSnapshot, strength: number): { mapped: Vec3; graded: Vec3 } {
  const raw = sampleLutTrilinear(
    lut.samples,
    lut.size,
    lut.domainMin,
    lut.domainMax,
    src[0],
    src[1],
    src[2],
  );
  const mapped = raw.map((c) => Math.min(1, Math.max(0, c))) as Vec3;
  const graded = src.map((c, i) => Math.min(1, Math.max(0, c + (mapped[i] - c) * strength))) as Vec3;
  return { mapped, graded };
}

function mediaSize(el: MediaSource): [number, number] {
  return el instanceof HTMLVideoElement
    ? [el.videoWidth, el.videoHeight]
    : [el.naturalWidth, el.naturalHeight];
}

function rgbCss(c: Vec3): string {
  return `rgb(${c.map((v) => Math.round(v * 255)).join(",")})`;
}

function rgbText(c: Vec3): string {
  return c.map((v) => String(Math.round(v * 255)).padStart(3, " ")).join(" ");
}

/** 悬停取色浮窗 + 钉住取样点提示条 */
export class ColorProbe {
  private stage: HTMLElement;
  private tip: HTMLDivElement;
  private pinBar: HTMLDivElement;
  private pixelCanvas: HTMLCanvasElement;
  private pixelCtx: CanvasRenderingContext2D | null;
  onUnpin: (() => void) | null = null;

  constructor(stage: HTMLElement) {
    this.stage = stage;
    this.tip = document.createElement("div");
    this.tip.className = "color-probe";
    this.tip.hidden = true;
    this.pinBar = document.createElement("div");
    this.pinBar.className = "probe-pin-bar";
    this.pinBar.hidden = true;
    this.pixelCanvas = document.createElement("canvas");
    this.pixelCanvas.width = 1;
    this.pixelCanvas.height = 1;
    this.pixelCtx = this.pixelCanvas.getContext("2d", { willReadFrequently: true });
    stage.append(this.tip, this.pinBar);
  }

  /** 读取源媒体在 (u, v) 处的原始像素，v=1 为图像顶部 */
  readPixel(el: MediaSource, u: number, v: number): Vec3 | null {
    const [w, h] = mediaSize(el);
    const ctx = this.pixelCtx;
    if (!ctx || w <= 0 || h <= 0) return null;
    const px = Math.min(w - 1, Math.floor(u * w));
    const py = Math.min(h - 1, Math.floor((1 - v) * h));
    try {
      ctx.clearRect(0, 0, 1, 1);
      ctx.drawImage(el, px, py, 1, 1, 0, 0, 1, 1);
      const d = ctx.getImageData(0, 0, 1, 1).data;
      return [d[0] / 255, d[1] / 255, d[2] / 255];
    } catch {
      return null;
    }
  }

  showAt(clientX: number, clientY: number, src: Vec3, graded: Vec3): void {
    this.tip.innerHTML = `
      <div class="probe-row"><span class="probe-swatch" style="background:${rgbCss(src)}"></span><span class="probe-k">原图</span><span class="probe-v">${rgbText(src)}</span></div>
      <div class="probe-row"><span class="probe-swatch" style="background:${rgbCss(graded)}"></span><span class="probe-k">调色后</span><span class="probe-v">${rgbText(graded)}</span></div>
      <div class="probe-foot">Shift+点击 钉住取样点 · 不含晕光</div>`;
    this.tip.hidden = false;
    const rect = this.stage.getBoundingClientRect();
    const tw = this.tip.offsetWidth;
    const th = this.tip.offsetHeight;
    let x = clientX - rect.left + 16;
    let y = clientY - rect.top + 16;
    if (x + tw > rect.width - 8) x = clientX - rect.left - tw - 16;
    if (y + th > rect.height - 8) y = clientY - rect.top - th - 16;
    this.tip.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
  }

  hide(): void {
    this.tip.hidden = true;
  }

  setPinned(info: { src: Vec3; graded: Vec3 } | null): void {
    if (!info) {
      this.pinBar.hidden = true;
      return;
    }
    this.pinBar.innerHTML = `
      <span class="probe-pin-label">已钉住取样点</span>
      <span class="probe-swatch" style="background:${rgbCss(info.src)}"></span>
      <span class="probe-v">${rgbText(info.src)}</span>
      <span class="probe-arrow">→</span>
      <span class="probe-swatch" style="background:${rgbCss(info.graded)}"></span>
      <span class="probe-v">${rgbText(info.graded)}</span>
      <span class="probe-pin-hint">在「3D 色彩立方体」中标注位置 · Esc 取消</span>
      <button type="button" class="probe-pin-close" title="取消钉住" aria-label="取消钉住">×</button>`;
    this.pinBar.querySelector(".probe-pin-close")?.addEventListener("click", () => this.onUnpin?.());
    this.pinBar.hidden = false;
  }
}
