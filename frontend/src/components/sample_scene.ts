/** 内置示例图：程序化生成的黄昏场景 + 24 色标准色卡 + 灰阶条，离线可用、无版权问题 */

const W = 1600;
const H = 1000;

// X-Rite ColorChecker Classic 24 色的 sRGB 近似值，按 4 行 × 6 列排列
const CHECKER = [
  "#735244", "#c29682", "#627a9d", "#576c43", "#8580b1", "#67bdaa",
  "#d67e2c", "#505ba6", "#c15a63", "#5e3c6c", "#9dbc40", "#e0a32e",
  "#383d96", "#469449", "#af363c", "#e7c71f", "#bb5695", "#0885a1",
  "#f3f3f2", "#c8c8c8", "#a0a0a0", "#7a7a79", "#555555", "#343434",
];

function ridge(
  ctx: CanvasRenderingContext2D,
  baseY: number,
  amp: number,
  freqs: number[],
  fill: string | CanvasGradient,
): void {
  ctx.beginPath();
  ctx.moveTo(0, H);
  for (let x = 0; x <= W; x += 8) {
    let y = baseY;
    freqs.forEach((f, i) => {
      y -= Math.sin(x * f + i * 1.7) * amp / (i + 1);
    });
    ctx.lineTo(x, y);
  }
  ctx.lineTo(W, H);
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number): void {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

export async function createSampleSceneFile(): Promise<File> {
  const canvas = document.createElement("canvas");
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("无法创建示例图画布");

  // 天空：深蓝 → 紫 → 橙 → 地平线淡黄
  const sky = ctx.createLinearGradient(0, 0, 0, 620);
  sky.addColorStop(0, "#1b2747");
  sky.addColorStop(0.42, "#5a4a78");
  sky.addColorStop(0.75, "#e2875a");
  sky.addColorStop(1, "#f7cf8a");
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, W, H);

  // 太阳与光晕：提供高光区，便于观察高光与晕光
  const sunX = 1120;
  const sunY = 540;
  const glow = ctx.createRadialGradient(sunX, sunY, 10, sunX, sunY, 420);
  glow.addColorStop(0, "rgba(255,240,200,0.95)");
  glow.addColorStop(0.18, "rgba(255,200,130,0.55)");
  glow.addColorStop(1, "rgba(255,160,90,0)");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, W, H);
  ctx.beginPath();
  ctx.arc(sunX, sunY, 62, 0, Math.PI * 2);
  ctx.fillStyle = "#fff6dc";
  ctx.fill();

  // 远山 / 近山剪影：提供中间调和暗部
  ridge(ctx, 560, 60, [0.004, 0.011, 0.023], "#6a5577");
  ridge(ctx, 610, 70, [0.003, 0.009, 0.019], "#3b3048");
  const ground = ctx.createLinearGradient(0, 600, 0, H);
  ground.addColorStop(0, "#2a2230");
  ground.addColorStop(1, "#141116");
  ridge(ctx, 670, 40, [0.002, 0.007], ground);

  // 24 色卡
  const patch = 62;
  const gap = 8;
  const bx = 64;
  const by = 640;
  const bw = 6 * patch + 7 * gap;
  const bh = 4 * patch + 5 * gap;
  ctx.fillStyle = "#101012";
  roundRect(ctx, bx, by, bw, bh, 10);
  ctx.fill();
  CHECKER.forEach((c, i) => {
    const col = i % 6;
    const row = Math.floor(i / 6);
    ctx.fillStyle = c;
    roundRect(ctx, bx + gap + col * (patch + gap), by + gap + row * (patch + gap), patch, patch, 4);
    ctx.fill();
  });

  // 11 级灰阶条
  const steps = 11;
  const gx = 560;
  const gy = 880;
  const gw = 980;
  const sw = gw / steps;
  for (let i = 0; i < steps; i++) {
    const v = Math.round((i / (steps - 1)) * 255);
    ctx.fillStyle = `rgb(${v},${v},${v})`;
    ctx.fillRect(gx + i * sw, gy, Math.ceil(sw), 64);
  }
  ctx.strokeStyle = "rgba(255,255,255,0.25)";
  ctx.strokeRect(gx + 0.5, gy + 0.5, gw, 64);

  ctx.fillStyle = "rgba(255,255,255,0.55)";
  ctx.font = "600 22px 'Segoe UI', sans-serif";
  ctx.fillText("AI COLOR · SAMPLE SCENE", gx, gy - 18);

  const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, "image/png"));
  if (!blob) throw new Error("示例图编码失败");
  return new File([blob], "sample_scene.png", { type: "image/png" });
}
