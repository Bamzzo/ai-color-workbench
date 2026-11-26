import type { ColorParams, ParamKey } from "./params";
import { PARAM_KEYS, clampParam, identityParams } from "./params";

const MAX_HISTORY = 64;

export type CompareMode = "preview" | "split" | "hold" | "lut3d";

export interface ColorSnapshot {
  params: ColorParams;
  strength: number;
}

export type MediaInfo = {
  media_id: string;
  kind: "image" | "video";
  width: number;
  height: number;
  duration_s?: number;
  fps?: number;
  content_url: string;
};

export type Listener = () => void;

export class StateStore {
  params: ColorParams = identityParams();
  strength = 1;
  /** 光学晕光后处理强度，独立于 16 维 ColorParams */
  bloom = 0;
  media: MediaInfo | null = null;
  compareMode: CompareMode = "preview";
  splitRatio = 0.5;
  holdOriginal = false;
  aiSummary = "";
  aiSource = "";
  lutSize = 33;
  externalLut = false;

  private history: ColorSnapshot[] = [{ params: identityParams(), strength: 1 }];
  private historyIndex = 0;

  private listeners = new Set<Listener>();

  subscribe(fn: Listener): () => void {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  emit(): void {
    for (const fn of this.listeners) {
      fn();
    }
  }

  snapshot(): ColorSnapshot {
    return {
      params: { ...this.params },
      strength: this.strength,
    };
  }

  private pushHistory(): void {
    const snap = this.snapshot();
    const cur = this.history[this.historyIndex];
    if (
      PARAM_KEYS.every((k) => cur.params[k] === snap.params[k]) &&
      cur.strength === snap.strength
    ) {
      return;
    }
    if (this.historyIndex < this.history.length - 1) {
      this.history = this.history.slice(0, this.historyIndex + 1);
    }
    this.history.push(snap);
    this.historyIndex = this.history.length - 1;
    if (this.history.length > MAX_HISTORY) {
      const drop = this.history.length - MAX_HISTORY;
      this.history = this.history.slice(drop);
      this.historyIndex -= drop;
    }
  }

  canUndo(): boolean {
    return this.historyIndex > 0;
  }

  canRedo(): boolean {
    return this.historyIndex < this.history.length - 1;
  }

  undo(): boolean {
    if (!this.canUndo()) return false;
    this.historyIndex -= 1;
    this.applySnapshot(this.history[this.historyIndex]);
    return true;
  }

  redo(): boolean {
    if (!this.canRedo()) return false;
    this.historyIndex += 1;
    this.applySnapshot(this.history[this.historyIndex]);
    return true;
  }

  private applySnapshot(snap: ColorSnapshot): void {
    this.params = { ...snap.params };
    this.strength = snap.strength;
    this.emit();
  }

  setParam(key: ParamKey, value: number, commit = true): void {
    this.params = { ...this.params, [key]: clampParam(key, value) };
    this.externalLut = false;
    // 拖动滑杆时 input 连续触发：只刷新预览，松手（change）才落一个快照，
    // 否则一次拖动会往撤销栈里塞进几十条中间态。
    if (commit) this.pushHistory();
    this.emit();
  }

  setParams(params: ColorParams): void {
    this.params = { ...params };
    this.externalLut = false;
    this.pushHistory();
    this.emit();
  }

  setStrength(value: number, commit = true): void {
    this.strength = Math.min(1, Math.max(0, value));
    if (commit) this.pushHistory();
    this.emit();
  }

  setBloom(value: number): void {
    this.bloom = Math.min(1, Math.max(0, value));
    this.emit();
  }

  resetParams(): void {
    this.params = identityParams();
    this.strength = 1;
    this.bloom = 0;
    this.pushHistory();
    this.emit();
  }
}