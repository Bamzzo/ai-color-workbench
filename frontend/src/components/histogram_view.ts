import type { HistogramBins } from "../core/gl_viewport";

const CHANNELS: { key: "r" | "g" | "b"; color: string; glow: string }[] = [
  { key: "r", color: "#FF5A5F", glow: "rgba(255, 90, 95, 0.22)" },
  { key: "g", color: "#2EC4B6", glow: "rgba(46, 196, 182, 0.2)" },
  { key: "b", color: "#3A86FF", glow: "rgba(58, 134, 255, 0.2)" },
];

const EASE_MS = 120;

type ChannelKey = "r" | "g" | "b" | "luma";

function emptyBins(): Record<ChannelKey, Float32Array> {
  return {
    r: new Float32Array(256),
    g: new Float32Array(256),
    b: new Float32Array(256),
    luma: new Float32Array(256),
  };
}

/** 实时 RGB / Luma 直方图：screen 混合 + 120ms 缓动插值 */
export class HistogramView {
  private wrap: HTMLDivElement;
  private canvas: HTMLCanvasElement;
  private tag: HTMLSpanElement;
  private prev = emptyBins();
  private target = emptyBins();
  private buf = emptyBins();
  private animRaf = 0;
  private animStart = 0;
  private hasData = false;

  constructor(container: HTMLElement) {
    this.wrap = document.createElement("div");
    this.wrap.className = "histogram-wrap";
    this.tag = document.createElement("span");
    this.tag.className = "histogram-tag";
    this.tag.textContent = "sRGB · 33³";
    this.canvas = document.createElement("canvas");
    this.canvas.width = 288;
    this.canvas.height = 110;
    this.wrap.append(this.tag, this.canvas);
    container.appendChild(this.wrap);
    this.paint(0);
  }

  setLutTag(text: string): void {
    this.tag.textContent = text;
  }

  draw(bins: HistogramBins | null): void {
    if (!bins) return;
    for (const key of ["r", "g", "b", "luma"] as ChannelKey[]) {
      this.prev[key].set(this.buf[key]);
      this.target[key].set(bins[key]);
    }
    this.hasData = true;
    this.animStart = performance.now();
    if (!this.animRaf) this.animRaf = requestAnimationFrame(this.tick);
  }

  private tick = (): void => {
    const t = Math.min(1, (performance.now() - this.animStart) / EASE_MS);
    const eased = 1 - Math.pow(1 - t, 3);
    for (const key of ["r", "g", "b", "luma"] as ChannelKey[]) {
      const from = this.prev[key];
      const to = this.target[key];
      const out = this.buf[key];
      for (let i = 0; i < 256; i++) {
        out[i] = from[i] + (to[i] - from[i]) * eased;
      }
    }
    this.paint(eased);
    if (t < 1) {
      this.animRaf = requestAnimationFrame(this.tick);
    } else {
      this.animRaf = 0;
      for (const key of ["r", "g", "b", "luma"] as ChannelKey[]) {
        this.prev[key].set(this.target[key]);
        this.buf[key].set(this.target[key]);
      }
    }
  };

  private paint(_eased: number): void {
    const ctx = this.canvas.getContext("2d");
    if (!ctx) return;
    const w = this.canvas.width;
    const h = this.canvas.height;

    ctx.globalCompositeOperation = "source-over";
    ctx.globalAlpha = 1;
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = "rgba(9, 9, 11, 0.55)";
    ctx.fillRect(0, 0, w, h);

    // 4×3 暗灰细刻度网格
    ctx.strokeStyle = "rgba(255, 255, 255, 0.055)";
    ctx.lineWidth = 1;
    for (let c = 0; c <= 4; c++) {
      const x = Math.round((w * c) / 4) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let r = 0; r <= 3; r++) {
      const y = Math.round((h * r) / 3) + 0.5;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    if (!this.hasData) return;

    ctx.globalCompositeOperation = "screen";

    const yOf = (arr: Float32Array, i: number) =>
      h - 3 - arr[i] * (h - 8);

    for (const ch of CHANNELS) {
      const bins = this.buf[ch.key];

      const grad = ctx.createLinearGradient(0, h, 0, 0);
      grad.addColorStop(0, "rgba(0,0,0,0)");
      grad.addColorStop(1, ch.glow);
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.moveTo(0, h);
      for (let i = 0; i < 256; i++) {
        ctx.lineTo((i / 255) * w, yOf(bins, i));
      }
      ctx.lineTo(w, h);
      ctx.closePath();
      ctx.fill();

      ctx.strokeStyle = ch.color;
      ctx.lineWidth = 1.5;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.beginPath();
      for (let i = 0; i < 256; i++) {
        const x = (i / 255) * w;
        const y = yOf(bins, i);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }

    // Luma 作为柔和高光曲线
    ctx.strokeStyle = "rgba(244, 244, 246, 0.5)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i < 256; i++) {
      const x = (i / 255) * w;
      const y = yOf(this.buf.luma, i);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    ctx.globalCompositeOperation = "source-over";
  }
}
