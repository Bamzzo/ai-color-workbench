import type { PresetItem } from "../services/api_client";

const PRESET_VISUAL: Record<
  string,
  { en: string; gradient: string }
> = {
  identity: {
    en: "IDENTITY",
    gradient: "linear-gradient(90deg,#33333a,#8f8f97,#e3e3e8)",
  },
  warm: {
    en: "WARM FILM",
    gradient: "linear-gradient(90deg,#332c26,#7d6c58,#c7b79f)",
  },
  cool: {
    en: "COOL TONE",
    gradient: "linear-gradient(90deg,#232a33,#54626e,#a7b2bc)",
  },
  soft: {
    en: "SOFT AIR",
    gradient: "linear-gradient(90deg,#44444a,#9d9ba3,#e4e2e7)",
  },
  cinematic: {
    en: "CINEMATIC",
    gradient: "linear-gradient(90deg,#141418,#3a3833,#6d675c)",
  },
  mono: {
    en: "MONOCHROME",
    gradient: "linear-gradient(90deg,#0a0a0c,#6e6e72,#f0f0f2)",
  },
};

export type PresetPickHandler = (preset: PresetItem) => void;

export class PresetGrid {
  private grid: HTMLElement;
  private activeKey = "identity";
  private onPick: PresetPickHandler;

  constructor(container: HTMLElement, onPick: PresetPickHandler) {
    this.onPick = onPick;
    this.grid = document.createElement("div");
    this.grid.className = "preset-grid";
    container.appendChild(this.grid);
  }

  render(presets: PresetItem[]): void {
    this.grid.replaceChildren();
    for (const p of presets) {
      const vis = PRESET_VISUAL[p.key] ?? {
        en: p.key.toUpperCase(),
        gradient: "linear-gradient(90deg,#333,#aaa)",
      };
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "preset-card";
      btn.dataset.key = p.key;
      btn.innerHTML = `
        <span class="preset-swatch" style="background:${vis.gradient}"></span>
        <span class="preset-text">
          <span class="preset-title">${p.label}</span>
          <span class="preset-en">${vis.en}</span>
        </span>
        <span class="preset-dot" aria-hidden="true"></span>
      `;
      btn.addEventListener("click", () => {
        this.activeKey = p.key;
        this.syncActive();
        this.onPick(p);
      });
      this.grid.appendChild(btn);
    }
    this.syncActive();
  }

  setActiveKey(key: string): void {
    this.activeKey = key;
    this.syncActive();
  }

  /** 参数已偏离任何预设（AI 调色 / 导入 .cube / 手动改滑杆）时取消高亮 */
  clearActive(): void {
    if (this.activeKey === "") return;
    this.activeKey = "";
    this.syncActive();
  }

  private syncActive(): void {
    for (const el of this.grid.querySelectorAll(".preset-card")) {
      const card = el as HTMLElement;
      card.classList.toggle("active", card.dataset.key === this.activeKey);
    }
  }
}