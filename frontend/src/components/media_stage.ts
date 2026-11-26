/** A/B 分屏对比线：1.5px 纯白分割线 + 黑金磨砂圆形拉手 + BEFORE / AFTER 徽章 */

export class MediaStageOverlay {
  readonly root: HTMLDivElement;
  private line: HTMLDivElement;
  private knob: HTMLButtonElement;
  private badgeBefore: HTMLSpanElement;
  private badgeAfter: HTMLSpanElement;
  private dragging = false;
  private ratio = 0.5;
  private onRatioChange?: (ratio: number) => void;

  constructor(stage: HTMLElement) {
    this.root = document.createElement("div");
    this.root.className = "media-stage-split";
    this.root.style.display = "none";

    this.badgeBefore = document.createElement("span");
    this.badgeBefore.className = "split-badge split-badge-left";
    this.badgeBefore.textContent = "原图 BEFORE";

    this.badgeAfter = document.createElement("span");
    this.badgeAfter.className = "split-badge split-badge-right";
    this.badgeAfter.textContent = "效果图 AFTER";

    this.line = document.createElement("div");
    this.line.className = "split-line";

    this.knob = document.createElement("button");
    this.knob.type = "button";
    this.knob.className = "split-knob";
    this.knob.setAttribute("aria-label", "拖动对比线");
    this.knob.innerHTML =
      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 8l-4 4 4 4"/><path d="M16 8l4 4-4 4"/><path d="M12 4v16"/></svg>';

    this.knob.addEventListener("mousedown", (ev) => {
      ev.preventDefault();
      ev.stopPropagation();
      this.dragging = true;
    });
    window.addEventListener("mouseup", () => {
      this.dragging = false;
    });
    window.addEventListener("mousemove", (ev) => {
      if (!this.dragging) return;
      this.setRatioFromClientX(ev.clientX);
    });

    this.line.appendChild(this.knob);
    this.root.append(this.badgeBefore, this.badgeAfter, this.line);
    stage.appendChild(this.root);
    this.setRatio(0.5);
  }

  bindRatioChange(fn: (ratio: number) => void): void {
    this.onRatioChange = fn;
  }

  setVisible(visible: boolean): void {
    this.root.style.display = visible ? "block" : "none";
  }

  getRatio(): number {
    return this.ratio;
  }

  setRatio(ratio: number): void {
    this.ratio = Math.min(1, Math.max(0, ratio));
    const pct = `${this.ratio * 100}%`;
    this.line.style.left = pct;
    this.badgeAfter.style.left = `calc(${pct} + 12px)`;
  }

  setRatioFromClientX(clientX: number): void {
    const rect = this.root.getBoundingClientRect();
    this.setRatio((clientX - rect.left) / rect.width);
    this.onRatioChange?.(this.ratio);
  }

  destroy(): void {
    this.root.remove();
  }
}
