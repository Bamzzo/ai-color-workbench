import type { ColorParams, ParamKey } from "../core/params";
import {
  BIPOLAR_KEYS,
  PARAM_GROUPS,
  PARAM_LABELS,
  PARAM_RANGES,
} from "../core/params";

export type ParamChangeHandler = (
  key: ParamKey,
  value: number,
  commit?: boolean,
) => void;

const HUE_WHEEL =
  "linear-gradient(90deg,#ff3b3b,#ffd23b 17%,#4cff3b 33%,#3bfff1 50%,#3b5bff 67%,#e23bff 83%,#ff3b3b)";
const SAT_RAMP = "linear-gradient(90deg,#6e6e74,#8d8a86 50%,#e8743c 75%,#f2c230 88%,#3cc8f0)";

/** 带颜色语义的参数使用渐变轨道，其余参数沿用中性轨道 + 琥珀填充 */
const SEMANTIC_TRACK: Partial<Record<ParamKey, string>> = {
  exposure_ev: "linear-gradient(90deg,#141416,#7c7c84 50%,#f4f4f6)",
  temperature: "linear-gradient(90deg,#3d7bff,#8e97a6 50%,#f2a93b)",
  tint: "linear-gradient(90deg,#39b85a,#959ba1 50%,#d64fcf)",
  saturation: SAT_RAMP,
  vibrance: SAT_RAMP,
  hue: "linear-gradient(90deg,#3bfff1,#3b5bff 17%,#e23bff 33%,#ff3b3b 50%,#ffd23b 67%,#4cff3b 83%,#3bfff1)",
  split_shadow_hue: HUE_WHEEL,
  split_highlight_hue: HUE_WHEEL,
};

export class ParamPanel {
  private root: HTMLElement;
  private onChange: ParamChangeHandler;
  private fills = new Map<ParamKey, HTMLDivElement>();
  private rows = new Map<ParamKey, HTMLElement>();

  constructor(container: HTMLElement, onChange: ParamChangeHandler) {
    this.onChange = onChange;
    this.root = document.createElement("div");
    this.root.className = "param-panel";
    container.appendChild(this.root);
    for (const group of PARAM_GROUPS) {
      const details = document.createElement("details");
      details.className = "param-group";
      details.open =
        group.title === "基础光影" || group.title === "白平衡与色彩";
      const summary = document.createElement("summary");
      summary.textContent = group.title;
      details.appendChild(summary);
      for (const key of group.keys) {
        details.appendChild(this.row(key));
      }
      this.root.appendChild(details);
    }
  }

  private row(key: ParamKey): HTMLElement {
    const wrap = document.createElement("div");
    wrap.className = "param-row";
    wrap.dataset.key = key;
    this.rows.set(key, wrap);

    const label = document.createElement("label");
    label.title = "双击归零";
    const dot = document.createElement("span");
    dot.className = "param-dot";
    dot.setAttribute("aria-hidden", "true");
    label.append(dot, PARAM_LABELS[key]);

    const track = document.createElement("div");
    track.className = "param-track";
    const gradient = SEMANTIC_TRACK[key];
    if (gradient) {
      wrap.classList.add("semantic");
      track.style.setProperty("--track-bg", gradient);
    }
    if (BIPOLAR_KEYS.has(key)) {
      const zero = document.createElement("span");
      zero.className = "param-zero";
      track.appendChild(zero);
    }
    const fill = document.createElement("div");
    fill.className = "param-fill";
    if (BIPOLAR_KEYS.has(key)) fill.classList.add("bipolar");
    this.fills.set(key, fill);
    track.appendChild(fill);

    const input = document.createElement("input");
    input.type = "range";
    input.className = "param-range";
    input.title = "双击归零";
    const [lo, hi] = PARAM_RANGES[key];
    input.min = String(lo);
    input.max = String(hi);
    input.step = key === "exposure_ev" ? "0.01" : "1";
    input.addEventListener("input", () => {
      const v = Number(input.value);
      // commit=false：只在预览上实时生效，不进撤销栈
      this.onChange(key, v, false);
      this.render(key, v);
      wrap.classList.remove("ai-changed");
    });
    // 鼠标松手 / 键盘调整结束时浏览器才派发 change，此处落一条撤销快照
    input.addEventListener("change", () => {
      this.onChange(key, Number(input.value), true);
    });
    track.appendChild(input);

    const valueEl = document.createElement("div");
    valueEl.className = "param-value";
    valueEl.title = "双击输入精确数值";
    valueEl.addEventListener("dblclick", () => {
      const raw = prompt(PARAM_LABELS[key], valueEl.textContent ?? "0");
      if (raw === null) return;
      const v = Number(raw);
      if (Number.isFinite(v)) {
        this.onChange(key, v, true);
        this.render(key, clamp(key, v));
        wrap.classList.remove("ai-changed");
      }
    });

    const resetToZero = () => {
      this.onChange(key, 0, true);
      this.render(key, 0);
      wrap.classList.remove("ai-changed");
    };
    label.addEventListener("dblclick", resetToZero);
    input.addEventListener("dblclick", resetToZero);

    wrap.append(label, track, valueEl);
    return wrap;
  }

  sync(params: ColorParams): void {
    for (const key of this.rows.keys()) {
      this.render(key, params[key]);
    }
  }

  /** 高亮一组被 AI 改动的参数，并展开所在分组 */
  highlightChanged(keys: ParamKey[]): void {
    this.clearHighlight();
    for (const key of keys) {
      const row = this.rows.get(key);
      if (!row) continue;
      row.classList.add("ai-changed");
      const group = row.closest("details");
      if (group) group.open = true;
    }
  }

  clearHighlight(): void {
    for (const row of this.rows.values()) row.classList.remove("ai-changed");
  }

  private render(key: ParamKey, value: number): void {
    const row = this.rows.get(key);
    if (!row) return;
    const input = row.querySelector("input") as HTMLInputElement;
    const valueEl = row.querySelector(".param-value") as HTMLDivElement;
    input.value = String(value);
    valueEl.textContent = formatValue(key, value);
    this.updateFill(key, value);
    const touched = Math.abs(value) > (key === "exposure_ev" ? 0.001 : 0.5);
    row.classList.toggle("touched", touched);
  }

  private updateFill(key: ParamKey, value: number): void {
    const fill = this.fills.get(key);
    if (!fill) return;
    const [lo, hi] = PARAM_RANGES[key];
    if (BIPOLAR_KEYS.has(key)) {
      const mid = (lo + hi) / 2;
      const pct = ((value - mid) / (hi - lo)) * 100;
      if (pct >= 0) {
        fill.style.left = "50%";
        fill.style.width = `${Math.abs(pct)}%`;
      } else {
        fill.style.left = `${50 + pct}%`;
        fill.style.width = `${Math.abs(pct)}%`;
      }
    } else {
      const t = (value - lo) / (hi - lo);
      fill.style.left = "0";
      fill.style.width = `${t * 100}%`;
    }
  }
}

function clamp(key: ParamKey, v: number): number {
  const [lo, hi] = PARAM_RANGES[key];
  return Math.min(hi, Math.max(lo, v));
}

export function formatValue(key: ParamKey, v: number): string {
  if (key === "exposure_ev") return v.toFixed(2);
  return v.toFixed(0);
}
