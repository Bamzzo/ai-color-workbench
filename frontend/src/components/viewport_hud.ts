/** 视口上下悬浮玻璃 HUD：光学遥测 + 缩放控制，以及强度 / 视频控制坞 */

export interface HudCallbacks {
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
  onStrength: (value: number, commit: boolean) => void;
  onBloom: (value: number) => void;
  onReset: () => void;
}

export class ViewportHud {
  readonly topBar: HTMLDivElement;
  readonly bottomDock: HTMLDivElement;
  private resEl: HTMLSpanElement;
  private zoomEl: HTMLSpanElement;
  private strengthInput: HTMLInputElement;
  private strengthValue: HTMLSpanElement;
  private strengthFill: HTMLDivElement;
  private bloomInput: HTMLInputElement;
  private bloomValue: HTMLSpanElement;
  private bloomFill: HTMLDivElement;
  private videoSlot: HTMLDivElement;
  private playBtn: HTMLButtonElement | null = null;
  private seek: HTMLInputElement | null = null;
  private timeEl: HTMLSpanElement | null = null;
  private fpsEl: HTMLSpanElement | null = null;
  private video: HTMLVideoElement | null = null;
  private stage: HTMLElement;

  constructor(stage: HTMLElement, cb: HudCallbacks) {
    this.stage = stage;

    this.topBar = document.createElement("div");
    this.topBar.className = "hud-top glass-hud";
    this.resEl = document.createElement("span");
    this.resEl.className = "hud-item hud-res";
    this.resEl.textContent = "未载入";
    const sep2 = document.createElement("span");
    sep2.className = "hud-sep";

    const zoomGroup = document.createElement("div");
    zoomGroup.className = "hud-zoom";
    const minus = hudBtn("−", "缩小", cb.onZoomOut);
    this.zoomEl = document.createElement("span");
    this.zoomEl.className = "hud-zoom-value";
    this.zoomEl.textContent = "100%";
    const plus = hudBtn("+", "放大", cb.onZoomIn);
    const fit = document.createElement("button");
    fit.type = "button";
    fit.className = "hud-btn hud-fit";
    fit.textContent = "适应";
    fit.addEventListener("click", cb.onFit);
    zoomGroup.append(minus, this.zoomEl, plus, fit);

    this.topBar.append(this.resEl, sep2, zoomGroup);

    this.bottomDock = document.createElement("div");
    this.bottomDock.className = "hud-bottom glass-hud";

    const strength = document.createElement("div");
    strength.className = "dock-strength";
    const label = document.createElement("span");
    label.className = "dock-label";
    label.textContent = "强度";
    const track = document.createElement("div");
    track.className = "dock-track";
    this.strengthFill = document.createElement("div");
    this.strengthFill.className = "dock-fill";
    this.strengthFill.style.width = "100%";
    this.strengthInput = document.createElement("input");
    this.strengthInput.type = "range";
    this.strengthInput.className = "dock-range";
    this.strengthInput.min = "0";
    this.strengthInput.max = "100";
    this.strengthInput.value = "100";
    this.strengthInput.addEventListener("input", () => {
      const v = Number(this.strengthInput.value);
      this.strengthFill.style.width = `${v}%`;
      this.strengthValue.textContent = `${v}%`;
      cb.onStrength(v / 100, false);
    });
    this.strengthInput.addEventListener("change", () => {
      cb.onStrength(Number(this.strengthInput.value) / 100, true);
    });
    track.append(this.strengthFill, this.strengthInput);
    this.strengthValue = document.createElement("span");
    this.strengthValue.className = "dock-value";
    this.strengthValue.textContent = "100%";
    strength.append(label, track, this.strengthValue);

    const dockSep = document.createElement("span");
    dockSep.className = "dock-sep";
    dockSep.setAttribute("aria-hidden", "true");

    const bloom = document.createElement("div");
    bloom.className = "dock-strength dock-bloom";
    const bloomLabel = document.createElement("span");
    bloomLabel.className = "dock-label";
    bloomLabel.textContent = "晕光";
    const bloomTrack = document.createElement("div");
    bloomTrack.className = "dock-track";
    this.bloomFill = document.createElement("div");
    this.bloomFill.className = "dock-fill";
    this.bloomFill.style.width = "0%";
    this.bloomInput = document.createElement("input");
    this.bloomInput.type = "range";
    this.bloomInput.className = "dock-range";
    this.bloomInput.min = "0";
    this.bloomInput.max = "100";
    this.bloomInput.value = "0";
    this.bloomInput.addEventListener("input", () => {
      const v = Number(this.bloomInput.value);
      this.bloomFill.style.width = `${v}%`;
      this.bloomValue.textContent = `${v}%`;
      cb.onBloom(v / 100);
    });
    bloomTrack.append(this.bloomFill, this.bloomInput);
    this.bloomValue = document.createElement("span");
    this.bloomValue.className = "dock-value";
    this.bloomValue.textContent = "0%";
    bloom.append(bloomLabel, bloomTrack, this.bloomValue);

    this.videoSlot = document.createElement("div");
    this.videoSlot.className = "dock-video";
    this.videoSlot.style.display = "none";

    const reset = document.createElement("button");
    reset.type = "button";
    reset.className = "dock-reset";
    reset.title = "重置全部参数";
    reset.setAttribute("aria-label", "重置全部参数");
    reset.innerHTML =
      '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/></svg>';
    reset.addEventListener("click", cb.onReset);

    this.bottomDock.append(strength, dockSep, bloom, this.videoSlot, reset);
    stage.append(this.topBar, this.bottomDock);
  }

  setMedia(info: { width: number; height: number } | null): void {
    this.resEl.textContent = info ? `${info.width}×${info.height}` : "未载入";
  }

  setZoom(pct: number): void {
    this.zoomEl.textContent = `${Math.round(pct)}%`;
  }

  setStrength(value: number): void {
    const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
    this.strengthInput.value = String(pct);
    this.strengthFill.style.width = `${pct}%`;
    this.strengthValue.textContent = `${pct}%`;
  }

  setBloom(value: number): void {
    const pct = Math.round(Math.min(1, Math.max(0, value)) * 100);
    this.bloomInput.value = String(pct);
    this.bloomFill.style.width = `${pct}%`;
    this.bloomValue.textContent = `${pct}%`;
  }

  /** 3D 色彩立方体模式：隐藏 2D 专属强度/晕光滑块，保留视频区与重置。 */
  set2dControlsVisible(visible: boolean): void {
    for (const el of this.bottomDock.querySelectorAll(".dock-strength, .dock-sep")) {
      (el as HTMLElement).style.display = visible ? "" : "none";
    }
    this.topBar.querySelector(".hud-zoom")?.classList.toggle("hidden", !visible);
  }

  attachVideo(video: HTMLVideoElement | null, fps?: number): void {
    this.video = video;
    this.videoSlot.replaceChildren();
    if (!video) {
      this.videoSlot.style.display = "none";
      this.bottomDock.classList.remove("has-video");
      this.stage.classList.remove("is-video");
      return;
    }
    this.videoSlot.style.display = "flex";
    this.bottomDock.classList.add("has-video");
    this.stage.classList.add("is-video");

    this.playBtn = document.createElement("button");
    this.playBtn.type = "button";
    this.playBtn.className = "dock-play";
    this.playBtn.innerHTML =
      '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5l12 7-12 7z"/></svg>';
    this.playBtn.addEventListener("click", () => {
      if (!this.video) return;
      if (this.video.paused) void this.video.play();
      else this.video.pause();
    });

    this.seek = document.createElement("input");
    const seek = this.seek;
    seek.type = "range";
    seek.className = "dock-range dock-seek";
    seek.min = "0";
    seek.max = "1000";
    seek.value = "0";
    seek.addEventListener("input", () => {
      if (!this.video) return;
      const d = this.video.duration || 1;
      this.video.currentTime = (Number(seek.value) / 1000) * d;
    });

    this.timeEl = document.createElement("span");
    this.timeEl.className = "dock-time";
    this.timeEl.textContent = "0:00 / 0:00";

    this.fpsEl = document.createElement("span");
    this.fpsEl.className = "dock-fps";
    this.fpsEl.textContent = fps ? `${fps.toFixed(0)} FPS` : "";

    video.addEventListener("play", () => {
      if (!this.playBtn) return;
      this.playBtn.innerHTML =
        '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M7 5h4v14H7zM13 5h4v14h-4z"/></svg>';
    });
    video.addEventListener("pause", () => {
      if (!this.playBtn) return;
      this.playBtn.innerHTML =
        '<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5l12 7-12 7z"/></svg>';
    });
    video.addEventListener("timeupdate", () => this.syncTime());

    this.videoSlot.append(this.playBtn, this.seek, this.timeEl, this.fpsEl);
  }

  private syncTime(): void {
    if (!this.video || !this.seek || !this.timeEl) return;
    const d = this.video.duration || 1;
    this.seek.value = String((this.video.currentTime / d) * 1000);
    this.timeEl.textContent = `${fmt(this.video.currentTime)} / ${fmt(d)}`;
  }
}

function hudBtn(label: string, title: string, onClick: () => void): HTMLButtonElement {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "hud-btn";
  b.textContent = label;
  b.title = title;
  b.addEventListener("click", onClick);
  return b;
}

function fmt(s: number): string {
  if (!Number.isFinite(s)) return "0:00";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}
