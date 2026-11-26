export type ColorParams = Record<ParamKey, number>;

export const PARAM_KEYS = [
  "exposure_ev",
  "contrast",
  "temperature",
  "tint",
  "highlights",
  "shadows",
  "whites",
  "blacks",
  "saturation",
  "vibrance",
  "hue",
  "split_shadow_hue",
  "split_shadow_amount",
  "split_highlight_hue",
  "split_highlight_amount",
  "split_balance",
] as const;

export type ParamKey = (typeof PARAM_KEYS)[number];

export const PARAM_RANGES: Record<ParamKey, [number, number]> = {
  exposure_ev: [-2, 2],
  contrast: [-100, 100],
  temperature: [-100, 100],
  tint: [-100, 100],
  highlights: [-100, 100],
  shadows: [-100, 100],
  whites: [-100, 100],
  blacks: [-100, 100],
  saturation: [-100, 100],
  vibrance: [-100, 100],
  hue: [-180, 180],
  split_shadow_hue: [0, 360],
  split_shadow_amount: [0, 100],
  split_highlight_hue: [0, 360],
  split_highlight_amount: [0, 100],
  split_balance: [-100, 100],
};

export const PARAM_LABELS: Record<ParamKey, string> = {
  exposure_ev: "曝光 (EV)",
  contrast: "对比度",
  temperature: "色温",
  tint: "色调",
  highlights: "高光",
  shadows: "阴影",
  whites: "白色",
  blacks: "黑色",
  saturation: "饱和度",
  vibrance: "自然饱和",
  hue: "色相旋转",
  split_shadow_hue: "阴影色相",
  split_shadow_amount: "阴影着色",
  split_highlight_hue: "高光色相",
  split_highlight_amount: "高光着色",
  split_balance: "分离平衡",
};

export const BIPOLAR_KEYS = new Set<ParamKey>([
  "exposure_ev",
  "contrast",
  "temperature",
  "tint",
  "highlights",
  "shadows",
  "whites",
  "blacks",
  "saturation",
  "vibrance",
  "hue",
  "split_balance",
]);

export const PARAM_GROUPS: { title: string; keys: ParamKey[] }[] = [
  {
    title: "基础光影",
    keys: ["exposure_ev", "contrast", "highlights", "shadows", "whites", "blacks"],
  },
  {
    title: "白平衡与色彩",
    keys: ["temperature", "tint", "saturation", "vibrance", "hue"],
  },
  {
    title: "分离色调",
    keys: [
      "split_shadow_hue",
      "split_shadow_amount",
      "split_highlight_hue",
      "split_highlight_amount",
      "split_balance",
    ],
  },
];

export function identityParams(): ColorParams {
  const out = {} as ColorParams;
  for (const key of PARAM_KEYS) {
    out[key] = 0;
  }
  return out;
}

export function clampParam(key: ParamKey, value: number): number {
  const [lo, hi] = PARAM_RANGES[key];
  return Math.min(hi, Math.max(lo, value));
}