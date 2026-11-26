/** RGB 三原色律动加载遮罩（Canvas2D，无框架依赖） */

export class RgbWaveLoader {
  private root: HTMLDivElement;
  private canvas: HTMLCanvasElement;
  private label: HTMLParagraphElement;
  private visible = false;
  private raf = 0;
  private t0 = 0;
  private phase = { r: 0, g: 2.1, b: 4.2 };

  constructor(parent: HTMLElement) {
    this.root = document.createElement("div");
    this.root.className = "wave-overlay";
    this.canvas = document.createElement("canvas");
    this.canvas.className = "wave-canvas";
    this.canvas.width = 420;
    this.canvas.height = 120;
    this.label = document.createElement("p");
    this.label.style.color = "var(--text-muted)";
    this.label.style.fontFamily = "var(--font-mono)";
    this.label.style.fontSize = "12px";
    this.label.textContent = "AI 正在解析色彩意图并烘焙 33³ 3D LUT...";
    this.root.append(this.canvas, this.label);
    parent.appendChild(this.root);
  }

  show(text?: string): void {
    if (text) this.label.textContent = text;
    this.visible = true;
    this.root.classList.add("visible");
    this.t0 = performance.now();
    if (!this.raf) this.raf = requestAnimationFrame(this.tick);
  }

  async hide(): Promise<void> {
    this.visible = false;
    const start = performance.now();
    while (performance.now() - start < 120) {
      this.draw(1 - (performance.now() - start) / 120);
      await new Promise((r) => requestAnimationFrame(r));
    }
    this.root.classList.remove("visible");
    if (this.raf) {
      cancelAnimationFrame(this.raf);
      this.raf = 0;
    }
  }

  private tick = (): void => {
    if (!this.visible) return;
    const t = (performance.now() - this.t0) / 1000;
    this.draw(1, t);
    this.raf = requestAnimationFrame(this.tick);
  };

  private draw(amplitude: number, t = 0): void {
    const ctx = this.canvas.getContext("2d");
    if (!ctx) return;
    const w = this.canvas.width;
    const h = this.canvas.height;
    ctx.clearRect(0, 0, w, h);
    const curves: { color: string; phase: number; freq: number }[] = [
      { color: "#FF4D4F", phase: this.phase.r, freq: 2.2 },
      { color: "#36CFC9", phase: this.phase.g, freq: 2.8 },
      { color: "#4096FF", phase: this.phase.b, freq: 3.4 },
    ];
    ctx.globalCompositeOperation = "lighter";
    for (const c of curves) {
      ctx.strokeStyle = c.color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      for (let x = 0; x < w; x++) {
        const u = x / w;
        const env =
          Math.exp(-Math.pow((u - 0.5) * 3.2, 2)) *
          (0.5 + 0.5 * Math.sin(t * 1.6 + c.phase));
        const y =
          h * 0.5 -
          Math.sin(u * Math.PI * 8 * c.freq + t * 3 + c.phase) *
            h *
            0.22 *
            env *
            amplitude;
        if (x === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    ctx.globalCompositeOperation = "source-over";
  }

  destroy(): void {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.root.remove();
  }
}