import { GlViewport } from "../core/gl_viewport";
import { LutCubeView } from "../core/lut_cube_view";
import type { ColorParams, ParamKey } from "../core/params";
import { StateStore } from "../core/state_store";
import { HistogramView } from "../components/histogram_view";
import { ParamPanel } from "../components/param_panel";
import { RgbWaveLoader } from "../components/rgb_wave_loader";
import { buildTopToolbar } from "../components/top_toolbar";
import { PresetGrid } from "../components/preset_grid";
import { MediaStageOverlay } from "../components/media_stage";
import { ViewportHud } from "../components/viewport_hud";
import { ColorProbe, gradeColor, type LutSnapshot } from "../components/color_probe";
import { createSampleSceneFile } from "../components/sample_scene";
import type { Vec3 } from "../core/lut_cube_view";
import { formatValue } from "../components/param_panel";
import { PARAM_KEYS, PARAM_LABELS } from "../core/params";
import {
  api,
  decodeLutBase64,
  mediaContentUrl,
  type PresetItem,
} from "../services/api_client";
import { triggerJobDownload, watchJob } from "../services/job_watch";
import { debounce } from "../utils/debounce";

/** 已验证的四字调色预设：点击后写入带结构的中文意图描述 */
const AI_INTENT_PRESETS: { label: string; prompt: string }[] = [
  {
    label: "清透日系",
    prompt:
      "清透日系：曝光 +0.20 EV 提亮整体，高光 -12 压住天空，阴影 +15 打开暗部细节；色温 +6、色调 +2 保持中性微暖；饱和 -8、自然饱和 +6 降低浓郁度，追求干净通透的轻盈空气感。",
  },
  {
    label: "胶片暖调",
    prompt:
      "胶片暖调：色温 +22、色调 +4 推向暖金，曝光 +0.10 EV；高光 -15 保留天空层次，阴影 +12 提亮暗部；饱和 -6、自然饱和 +12 避免肤色溢色；分离色调阴影偏暖橘、高光偏奶白，呈复古胶片质感。",
  },
  {
    label: "冷调电影",
    prompt:
      "冷调电影：色温 -18、色调 -4 压向冷青，曝光 -0.10 EV；对比 +18、高光 -20 强化轮廓；饱和 -12、自然饱和 +8 保持克制；阴影偏青蓝、高光偏暖橘形成青橙分离，呈电影级层次。",
  },
  {
    label: "奶油柔光",
    prompt:
      "奶油柔光：曝光 +0.25 EV、对比 -16 压低反差；高光 -20、阴影 +22 让亮暗两端都柔和过渡；色温 +10、色调 +3 微暖；饱和 -10、自然饱和 +6，高光偏奶白，适合人像与静物的奶油质感。",
  },
  {
    label: "高反差黑白",
    prompt:
      "高反差黑白：饱和 -100 完全去色；对比 +26、白色 +12、黑色 -14 拉出硬朗阶调；高光 -8 保住白场细节，阴影 +6 保留暗部层次，呈清晰锐利的纪实黑白观感。",
  },
  {
    label: "暮光黄昏",
    prompt:
      "暮光黄昏：色温 +30、色调 +8 营造金橙夕照；曝光 +0.15 EV、高光 -18 压住天光；阴影 +10 提亮暗部；饱和 +6、自然饱和 +10，分离色调高光偏金、阴影偏紫棕，温暖而低反差。",
  },
];

export function mountWorkbench(host: HTMLElement): void {
  const store = new StateStore();
  let presets: PresetItem[] = [];
  let bakeGen = 0;
  // lastBakeKey 只记录已成功上传到 GPU 的参数；失败后保持旧值，下次变更会重新烘焙
  let lastBakeKey = "";
  let inflightBakeKey = "";

  host.innerHTML = "";
  const shell = document.createElement("div");
  shell.className = "app-shell";

  const toolbar = buildTopToolbar();
  const workbench = document.createElement("div");
  workbench.className = "workbench";

  /* ---------------- 左侧观察区 ---------------- */
  const left = document.createElement("aside");
  left.className = "sidebar-panel sidebar-left";

  const histCard = document.createElement("div");
  histCard.className = "glass-card";
  histCard.innerHTML = '<div class="card-title">RGB · 亮度直方图</div>';
  const histHost = document.createElement("div");
  histCard.appendChild(histHost);
  const histogram = new HistogramView(histHost);

  const presetCard = document.createElement("div");
  presetCard.className = "glass-card";
  presetCard.innerHTML = '<div class="card-title">风格预设 · 一键应用</div>';
  const presetHost = document.createElement("div");
  presetCard.appendChild(presetHost);

  left.append(histCard, presetCard);

  /* ---------------- 底部状态栏 ---------------- */
  const statusBar = document.createElement("footer");
  statusBar.className = "status-bar";
  statusBar.innerHTML = `
    <span class="status-item" id="media-meta">未导入素材</span>
    <span class="status-spacer"></span>
    <span class="status-item">WebGL2 · Grade → Bloom → Composite</span>
    <span class="status-sep"></span>
    <span class="status-item">sdr-srgb-v2</span>
    <span class="status-sep"></span>
    <span class="status-item status-lut" id="status-lut">3D LUT · 33³</span>`;
  const statusLut = statusBar.querySelector("#status-lut") as HTMLSpanElement;

  /* ---------------- 中央光学视口 ---------------- */
  const center = document.createElement("main");
  center.className = "viewport-stage";
  const canvas = document.createElement("canvas");
  canvas.className = "viewport-canvas";
  center.appendChild(canvas);
  const cubeCanvas = document.createElement("canvas");
  cubeCanvas.className = "viewport-canvas viewport-cube-canvas";
  cubeCanvas.style.display = "none";
  center.appendChild(cubeCanvas);

  const emptyState = document.createElement("div");
  emptyState.className = "empty-state";
  emptyState.innerHTML = `
    <div class="empty-card">
      <svg class="empty-icon" width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="2"/><path d="M21 16l-5-5-9 9"/></svg>
      <div class="empty-title">拖入图片或视频，开始调色</div>
      <div class="empty-sub">支持 JPG / PNG / MP4 / MOV，也可以直接拖入 .cube LUT</div>
      <div class="empty-actions">
        <button type="button" class="btn" data-act="image">导入图片</button>
        <button type="button" class="btn" data-act="video">导入视频</button>
        <button type="button" class="btn btn-primary" data-act="sample">使用示例图</button>
      </div>
    </div>`;
  center.appendChild(emptyState);

  /* ---------------- 右侧控制台 ---------------- */
  const right = document.createElement("aside");
  right.className = "sidebar-panel sidebar-right scroll-y";

  const aiCard = document.createElement("div");
  aiCard.className = "glass-card";
  aiCard.innerHTML = '<div class="card-title">AI 自然语言调色</div>';

  const composer = document.createElement("div");
  composer.className = "ai-composer";
  const aiInput = document.createElement("textarea");
  aiInput.rows = 3;
  aiInput.placeholder = "描述色彩意图，如：通透日系、胶片暖调、压低高光…";
  const footer = document.createElement("div");
  footer.className = "ai-composer-footer";
  const footerHint = document.createElement("span");
  footerHint.className = "ai-footer-hint";
  footerHint.textContent = "自然语言 · 支持中文";
  const aiBtn = document.createElement("button");
  aiBtn.type = "button";
  aiBtn.className = "btn-ai";
  aiBtn.textContent = "✦ AI 生成";
  footer.append(footerHint, aiBtn);
  composer.append(aiInput, footer);

  const presetBlock = document.createElement("div");
  presetBlock.className = "ai-suggest";
  const presetLabel = document.createElement("span");
  presetLabel.className = "ai-suggest-label";
  presetLabel.textContent = "试试这样说：";
  const presetGridEl = document.createElement("span");
  presetGridEl.className = "ai-suggest-list";
  const presetButtons: HTMLButtonElement[] = [];
  for (const item of AI_INTENT_PRESETS) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "ai-suggest-link";
    b.textContent = item.label;
    b.title = item.prompt;
    b.dataset.prompt = item.prompt;
    b.addEventListener("click", () => {
      aiInput.value = item.prompt;
      for (const other of presetButtons) other.classList.toggle("active", other === b);
      autosizeInput();
      aiInput.focus();
      aiInput.setSelectionRange(item.prompt.length, item.prompt.length);
    });
    presetButtons.push(b);
    presetGridEl.appendChild(b);
  }
  aiInput.addEventListener("input", () => {
    autosizeInput();
    const matched = presetButtons.some((b) => b.dataset.prompt === aiInput.value);
    if (matched) return;
    for (const b of presetButtons) b.classList.remove("active");
  });

  function autosizeInput(): void {
    aiInput.style.height = "auto";
    aiInput.style.height = `${Math.min(120, Math.max(64, aiInput.scrollHeight))}px`;
  }
  presetBlock.append(presetLabel, presetGridEl);

  const aiMeta = document.createElement("div");
  aiMeta.style.marginTop = "8px";
  aiMeta.style.lineHeight = "1.55";
  aiMeta.innerHTML =
    '<span class="chip" id="ai-chip">参数调色</span> <span id="ai-summary" class="ai-summary"></span>';
  const aiDiff = document.createElement("div");
  aiDiff.className = "ai-diff";
  aiDiff.hidden = true;
  aiCard.append(composer, presetBlock, aiMeta, aiDiff);

  const paramScroll = document.createElement("div");
  paramScroll.className = "glass-card";
  paramScroll.innerHTML = '<div class="card-title">16 维精密参数</div>';
  const paramHost = document.createElement("div");
  paramScroll.appendChild(paramHost);

  right.append(aiCard, paramScroll);

  workbench.append(left, center, right);
  shell.append(toolbar.bar, workbench, statusBar);
  host.appendChild(shell);

  const loader = new RgbWaveLoader(center);
  const gl = new GlViewport(canvas);
  const lutCube = new LutCubeView(cubeCanvas);
  if (import.meta.env.DEV) {
    (window as unknown as Record<string, unknown>).__glv = gl;
  }
  const mediaStage = new MediaStageOverlay(center);
  gl.onHistogram((bins) => histogram.draw(bins));
  gl.startLoop();

  /* ---------------- HUD ---------------- */
  let zoom = 1;
  let panX = 0;
  let panY = 0;

  const hud = new ViewportHud(center, {
    onZoomIn: () => applyZoom(zoom * 1.25),
    onZoomOut: () => applyZoom(zoom / 1.25),
    onFit: () => fitView(),
    onStrength: (value, commit) => store.setStrength(value, commit),
    onBloom: (value) => store.setBloom(value),
    onReset: resetAll,
  });

  function applyZoom(next: number): void {
    zoom = Math.min(8, Math.max(0.25, next));
    gl.setViewTransform(zoom, panX, panY);
    hud.setZoom(zoom * 100);
  }

  function fitView(): void {
    zoom = 1;
    panX = 0;
    panY = 0;
    gl.fitToCanvas();
    gl.setViewTransform(zoom, panX, panY);
    hud.setZoom(100);
  }

  mediaStage.bindRatioChange((ratio) => {
    store.splitRatio = ratio;
    gl.setCompare(1, ratio);
  });

  const presetGrid = new PresetGrid(presetHost, (p) => {
    presetGrid.setActiveKey(p.key);
    clearAiDiff();
    store.setParams({ ...p.params });
    store.aiSummary = `已应用预设：${p.label}`;
    store.aiSource = "离线预设";
    store.emit();
  });

  const probe = new ColorProbe(center);
  let lutSnapshot: LutSnapshot | null = null;
  let pinnedSrc: Vec3 | null = null;

  function setLutInfo(
    samples: Float32Array,
    size: number,
    domainMin: Vec3,
    domainMax: Vec3,
    external: boolean,
  ): void {
    lutSnapshot = { samples, size, domainMin, domainMax };
    const tag = `sRGB · ${size}³`;
    histogram.setLutTag(tag);
    statusLut.textContent = external ? `外部 .cube · ${size}³` : `3D LUT · ${size}³`;
    refreshPin();
  }

  /** 钉住的取样点随 LUT / 强度变化重新计算 */
  function refreshPin(): void {
    if (!pinnedSrc || !lutSnapshot) {
      probe.setPinned(null);
      lutCube.setProbe(null);
      return;
    }
    const { mapped, graded } = gradeColor(pinnedSrc, lutSnapshot, store.strength);
    probe.setPinned({ src: pinnedSrc, graded });
    lutCube.setProbe(pinnedSrc, mapped);
  }

  function unpin(): void {
    pinnedSrc = null;
    refreshPin();
  }
  probe.onUnpin = unpin;

  const mediaSink = document.createElement("div");
  // 不用 display:none —— 不可见的视频在部分 GPU/浏览器下不会产出可上传帧
  mediaSink.style.cssText =
    "position:fixed;left:-10000px;top:0;width:320px;height:180px;opacity:0.01;pointer-events:none;overflow:hidden;";
  document.body.appendChild(mediaSink);
  let mediaEl: HTMLImageElement | HTMLVideoElement | null = null;
  let resumeVideoPlayback: (() => void) | null = null;

  // HUD 上的按钮/滑杆（含播放暂停键）在舞台内部，点击会冒泡到 center。
  // 必须把它们排除掉，否则「点暂停」会被下面的恢复播放逻辑立刻翻回播放。
  const isHudControl = (target: EventTarget | null): boolean => {
    const el = target as Element | null;
    if (!el || typeof el.closest !== "function") return false;
    return el.closest("button, input, a, .hud-bottom, .hud-top") !== null;
  };

  // 自动播放被拦截时，用户点一下画面即可恢复播放（只注册一次）
  const tryResumeVideo = (event: MouseEvent) => {
    if (!resumeVideoPlayback) return;
    if (isHudControl(event.target)) return;
    if (mediaEl instanceof HTMLVideoElement && !mediaEl.paused) return;
    resumeVideoPlayback();
  };
  canvas.addEventListener("click", tryResumeVideo);
  center.addEventListener("click", tryResumeVideo);

  const paramPanel = new ParamPanel(paramHost, (key: ParamKey, value, commit) => {
    store.setParam(key, value, commit);
    // 手动改参数即代表已离开当前预设；clearActive 幂等，重复调用无额外开销
    presetGrid.clearActive();
  });

  const scheduleBake = debounce(() => void rebakeLut(), 220);

  store.subscribe(() => {
    syncUi();
    const key = paramsKey(store.params);
    if (!store.externalLut && key !== lastBakeKey && key !== inflightBakeKey) {
      scheduleBake();
    }
  });

  void init();

  /* ---------------- 初始化 ---------------- */
  async function init(): Promise<void> {
    try {
      presets = await api.getPresets();
      presetGrid.render(presets);
      await rebakeLut();
    } catch (e) {
      console.error(e);
      toolbar.setStatus("无法连接后端 API，请确认 8765 已启动");
    }
  }

  function paramsKey(p: ColorParams): string {
    return Object.values(p).join(",");
  }

  async function rebakeLut(): Promise<void> {
    const gen = ++bakeGen;
    const key = paramsKey(store.params);
    inflightBakeKey = key;
    try {
      const data = await api.bakeLut(store.params, store.lutSize);
      if (gen !== bakeGen) return;
      const samples = decodeLutBase64(data.data_b64);
      gl.uploadLut(samples, data.size, data.domain_min, data.domain_max);
      lutCube.setLut(samples, data.size, data.domain_min, data.domain_max);
      setLutInfo(samples, data.size, data.domain_min, data.domain_max, false);
      lastBakeKey = key;
      toolbar.setError("");
    } catch (e) {
      console.error(e);
      if (gen === bakeGen) toolbar.setError(`LUT 烘焙失败：${errorText(e)}`);
    } finally {
      if (gen === bakeGen) inflightBakeKey = "";
    }
  }

  function errorText(e: unknown): string {
    return e instanceof Error && e.message ? e.message : "未知错误";
  }

  function syncUi(): void {
    paramPanel.sync(store.params);
    gl.setStrength(store.strength);
    gl.setBloom(store.bloom);
    const cubeMode = store.compareMode === "lut3d";
    gl.setRenderPaused(cubeMode);
    canvas.style.visibility = cubeMode ? "hidden" : "visible";
    cubeCanvas.style.display = cubeMode ? "block" : "none";
    lutCube.setActive(cubeMode);
    if (cubeMode) lutCube.resize();
    hud.set2dControlsVisible(!cubeMode);
    center.classList.toggle("is-cube-mode", cubeMode);
    const mode =
      !cubeMode && store.holdOriginal
        ? 2
        : store.compareMode === "split"
          ? 1
          : 0;
    gl.setCompare(mode, store.splitRatio);
    toolbar.updateHistory(store.canUndo(), store.canRedo());
    hud.setStrength(store.strength);
    hud.setBloom(store.bloom);
    mediaStage.setVisible(store.compareMode === "split");
    if (store.compareMode === "split") mediaStage.setRatio(store.splitRatio);
    const chip = document.getElementById("ai-chip");
    const summary = document.getElementById("ai-summary");
    if (chip) chip.textContent = store.aiSource || "参数调色";
    if (summary) summary.textContent = store.aiSummary;
    updateMediaMeta();
    if (pinnedSrc) refreshPin();
  }

  function updateMediaMeta(): void {
    const m = store.media;
    emptyState.hidden = !!m;
    center.classList.toggle("is-empty", !m);
    histCard.hidden = !m;
    const el = document.getElementById("media-meta");
    if (!el) return;
    if (!m) {
      el.textContent = "未导入素材";
      return;
    }
    const rows = [`${m.width}×${m.height} · ${m.kind === "video" ? "视频" : "图像"}`];
    if (m.fps) rows.push(`${m.fps.toFixed(1)} FPS`);
    if (m.duration_s !== undefined) rows.push(`${m.duration_s.toFixed(1)}s`);
    el.textContent = rows.join(" · ");
  }

  function resetAll(): void {
    store.resetParams();
    clearAiDiff();
    presetGrid.setActiveKey("identity");
    fitView();
    void rebakeLut();
  }

  /* ---------------- 媒体导入 ---------------- */
  async function loadMedia(file: File): Promise<void> {
    let up: Awaited<ReturnType<typeof api.uploadMedia>>;
    try {
      up = await api.uploadMedia(file);
    } catch (e) {
      console.error(e);
      toolbar.setError(`媒体导入失败：${errorText(e)}`);
      return;
    }
    const onDecodeError = () => {
      console.error("media decode failed", up.media_id);
      toolbar.setError("媒体解码失败：浏览器无法读取该文件");
    };
    store.media = {
      media_id: up.media_id,
      kind: up.kind,
      width: up.width,
      height: up.height,
      duration_s: up.duration_s,
      fps: up.fps,
      content_url: mediaContentUrl(up.media_id),
    };
    if (mediaEl) {
      mediaEl.remove();
      mediaEl = null;
    }
    hud.setMedia({ width: up.width, height: up.height });
    const url = store.media.content_url;
    if (up.kind === "video") {
      const video = document.createElement("video");
      video.crossOrigin = "anonymous";
      video.loop = true;
      video.muted = true;
      video.playsInline = true;
      video.preload = "auto";
      video.setAttribute("playsinline", "");
      // 给一个真实尺寸：display:none 的视频在部分环境下不会产出可上传的帧
      video.width = 640;
      video.height = 360;
      video.src = url;
      mediaEl = video;
      hud.attachVideo(video, up.fps);
      const startPlayback = () => {
        const p = video.play();
        if (p && typeof p.catch === "function") {
          p.catch(() => {
            // 浏览器拦截自动播放时保持首帧可用，并在画面上提示点击
            toolbar.setStatus("已载入视频 · 点击画面开始播放");
            if (video.currentTime === 0) {
              try {
                video.currentTime = 0.001;
              } catch {
                /* ignore */
              }
            }
          });
        }
      };
      const onReady = () => {
        gl.setSource(video);
        gl.notifySourceReady();
        toolbar.setError("");
        startPlayback();
      };
      video.addEventListener("loadeddata", onReady);
      video.addEventListener("error", onDecodeError);
      video.addEventListener("canplay", () => {
        if (!gl.hasSource) onReady();
      });
      resumeVideoPlayback = startPlayback;
    } else {
      resumeVideoPlayback = null;
      const img = new Image();
      img.crossOrigin = "anonymous";
      const onReady = () => {
        gl.setSource(img);
        gl.notifySourceReady();
        toolbar.setError("");
      };
      img.addEventListener("load", onReady);
      img.addEventListener("error", onDecodeError);
      img.src = url;
      mediaEl = img;
      hud.attachVideo(null);
      if (img.complete && img.naturalWidth > 0) onReady();
    }
    mediaSink.appendChild(mediaEl);
    fitView();
    store.emit();
  }

  /* ---------------- AI ---------------- */
  async function runAi(): Promise<void> {
    const intent = aiInput.value.trim();
    if (!intent) return;
    loader.show();
    try {
      const before = { ...store.params };
      const proposal = await api.aiPropose(intent, store.params, true);
      const validated = await api.validateParams(proposal.params);
      store.setParams(validated.params);
      showAiDiff(before, store.params);
      // AI 给出的参数不再等于任何离线预设，清掉左侧高亮避免状态误导
      presetGrid.clearActive();
      store.aiSummary = proposal.summary;
      store.aiSource =
        proposal.provider === "offline" ? "离线预设" : proposal.provider;
      // setParams 已先 emit 过一次，此时 aiSummary/aiSource 才赋值，
      // 必须再 emit 一次，否则 chip 与摘要要等到下次用户操作才更新。
      store.emit();
      await rebakeLut();
    } catch (e) {
      console.error(e);
      toolbar.setStatus(e instanceof Error ? e.message : "AI 调色失败");
    } finally {
      await loader.hide();
    }
  }

  function signed(key: ParamKey, v: number): string {
    const s = formatValue(key, v);
    return v > 0 && !key.endsWith("_hue") ? `+${s}` : s;
  }

  /** 对比 AI 调色前后的 16 维参数，高亮变化项并列出变化量 */
  function showAiDiff(before: ColorParams, after: ColorParams): void {
    const changed = PARAM_KEYS.filter((key) => {
      const eps = key === "exposure_ev" ? 0.005 : 0.5;
      return Math.abs(after[key] - before[key]) > eps;
    });
    paramPanel.highlightChanged(changed);
    if (changed.length === 0) {
      aiDiff.innerHTML = '<div class="ai-diff-head">AI 未改动任何参数</div>';
      aiDiff.hidden = false;
      return;
    }
    const rows = changed
      .map((key) => {
        const delta = after[key] - before[key];
        const deltaText = `${delta > 0 ? "+" : ""}${formatValue(key, delta)}`;
        return `<span class="ai-diff-name">${PARAM_LABELS[key]}</span>
          <span class="ai-diff-range">${signed(key, before[key])} → ${signed(key, after[key])}</span>
          <span class="ai-diff-delta ${delta > 0 ? "up" : "down"}">${deltaText}</span>`;
      })
      .join("");
    aiDiff.innerHTML = `<div class="ai-diff-head">AI 调整了 ${changed.length} 项参数</div><div class="ai-diff-list">${rows}</div>`;
    aiDiff.hidden = false;
  }

  function clearAiDiff(): void {
    aiDiff.hidden = true;
    aiDiff.replaceChildren();
    paramPanel.clearHighlight();
  }

  /* ---------------- .cube 导入 ---------------- */
  async function importCube(file: File): Promise<void> {
    loader.show("正在解析 .cube 并上传 3D LUT…");
    try {
      const lut = await api.uploadCube(file);
      const samples = decodeLutBase64(lut.data_b64);
      gl.uploadLut(samples, lut.size, lut.domain_min, lut.domain_max);
      lutCube.setLut(samples, lut.size, lut.domain_min, lut.domain_max);
      setLutInfo(samples, lut.size, lut.domain_min, lut.domain_max, true);
      store.externalLut = true;
      store.strength = 1;
      // 外部 .cube 完全替换了参数效果，任何预设高亮都已失效
      presetGrid.clearActive();
      gl.notifySourceReady();
      store.emit();
      toolbar.setError("");
    } catch (e) {
      console.error(e);
      toolbar.setError(`.cube 导入失败：${errorText(e)}`);
    } finally {
      await loader.hide();
    }
  }

  /* ---------------- 导出 ---------------- */
  let isExporting = false;
  let exportToken = 0;
  let exportClearTimer: number | undefined;

  async function runExport(kind: "image" | "video" | "lut"): Promise<void> {
    if (isExporting) return;
    if (kind !== "lut" && !store.media) {
      toolbar.setStatus("请先导入图片或视频");
      return;
    }
    isExporting = true;
    const token = ++exportToken;
    window.clearTimeout(exportClearTimer);
    toolbar.setExporting(true);
    toolbar.setProgress(0, "提交导出任务…");
    try {
      let jobId: string;
      if (kind === "image" && store.media) {
        const r = await api.exportImage(
          store.media.media_id,
          store.params,
          store.strength,
        );
        jobId = r.job_id;
      } else if (kind === "video" && store.media) {
        const r = await api.exportVideo(
          store.media.media_id,
          store.params,
          store.strength,
        );
        jobId = r.job_id;
      } else {
        const r = await api.exportLut(store.params, store.strength);
        jobId = r.job_id;
      }
      const final = await watchJob(jobId, (st) => {
        toolbar.setProgress(st.progress, st.message || st.status);
      });
      if (final.status === "done") {
        triggerJobDownload(jobId);
        toolbar.setProgress(1, "导出完成");
      } else {
        toolbar.setStatus(final.error || "导出失败");
      }
    } catch (e) {
      toolbar.setStatus(e instanceof Error ? e.message : "导出错误");
    } finally {
      isExporting = false;
      toolbar.setExporting(false);
      // 只清除本次任务留下的状态；若期间已开始新任务，旧定时器不再生效
      exportClearTimer = window.setTimeout(() => {
        if (token === exportToken) toolbar.setProgress(-1, "");
      }, 2000);
    }
  }

  /* ---------------- 视口交互 ---------------- */
  let panning = false;
  let spaceDown = false;
  let lastX = 0;
  let lastY = 0;

  canvas.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    // zoom 是显示放大倍数：滚轮向上（deltaY < 0）放大画面，向下缩小
    applyZoom(ev.deltaY > 0 ? zoom / 1.08 : zoom * 1.08);
  });

  canvas.addEventListener("mousedown", (ev) => {
    if (store.compareMode === "lut3d") return;
    // Shift+左键留给取样点钉住，不触发按住原图 / 分屏拖动
    if (ev.shiftKey && ev.button === 0) return;
    if (store.compareMode === "hold" && ev.button === 0) {
      store.holdOriginal = true;
      store.emit();
    }
    if (ev.button === 1 || (spaceDown && ev.button === 0)) {
      panning = true;
      lastX = ev.clientX;
      lastY = ev.clientY;
      ev.preventDefault();
    }
    if (store.compareMode === "split" && ev.button === 0) {
      mediaStage.setRatioFromClientX(ev.clientX);
      store.splitRatio = mediaStage.getRatio();
      store.emit();
    }
  });

  window.addEventListener("mouseup", () => {
    panning = false;
    if (store.holdOriginal) {
      store.holdOriginal = false;
      store.emit();
    }
  });

  window.addEventListener("mousemove", (ev) => {
    if (!panning) return;
    // 平移以屏幕归一化单位累计：向右拖 → 图像右移；屏幕 y 向下而 uPan.y 向上为正，故取反
    const rect = canvas.getBoundingClientRect();
    panX += (ev.clientX - lastX) / rect.width;
    panY -= (ev.clientY - lastY) / rect.height;
    lastX = ev.clientX;
    lastY = ev.clientY;
    gl.setViewTransform(zoom, panX, panY);
  });

  canvas.addEventListener("dblclick", fitView);

  /* ---------------- 取色 ---------------- */
  let probeEvent: MouseEvent | null = null;
  let probeRaf = 0;

  function sampleAt(ev: MouseEvent): { src: Vec3; graded: Vec3 } | null {
    if (!mediaEl || !lutSnapshot || !gl.hasSource) return null;
    const uv = gl.clientToImageUv(ev.clientX, ev.clientY);
    if (!uv) return null;
    const src = probe.readPixel(mediaEl, uv.u, uv.v);
    if (!src) return null;
    return { src, graded: gradeColor(src, lutSnapshot, store.strength).graded };
  }

  function runProbe(): void {
    probeRaf = 0;
    const ev = probeEvent;
    if (!ev || panning || store.compareMode === "lut3d") {
      probe.hide();
      return;
    }
    const hit = sampleAt(ev);
    if (!hit) {
      probe.hide();
      return;
    }
    probe.showAt(ev.clientX, ev.clientY, hit.src, hit.graded);
  }

  canvas.addEventListener("mousemove", (ev) => {
    probeEvent = ev;
    if (!probeRaf) probeRaf = requestAnimationFrame(runProbe);
  });
  canvas.addEventListener("mouseleave", () => {
    probeEvent = null;
    probe.hide();
  });
  canvas.addEventListener("click", (ev) => {
    if (!ev.shiftKey) return;
    if (pinnedSrc) {
      unpin();
      return;
    }
    const hit = sampleAt(ev);
    if (!hit) return;
    pinnedSrc = hit.src;
    refreshPin();
  });

  /* ---------------- 空状态与拖放导入 ---------------- */
  async function loadSample(): Promise<void> {
    try {
      await loadMedia(await createSampleSceneFile());
    } catch (e) {
      console.error(e);
      toolbar.setError(`示例图生成失败：${errorText(e)}`);
    }
  }

  emptyState.addEventListener("click", (ev) => {
    const act = (ev.target as Element).closest<HTMLElement>("[data-act]")?.dataset.act;
    if (act === "image") toolbar.pickImage();
    else if (act === "video") toolbar.pickVideo();
    else if (act === "sample") void loadSample();
  });

  function importDropped(file: File): void {
    const name = file.name.toLowerCase();
    if (name.endsWith(".cube")) void importCube(file);
    else if (
      file.type.startsWith("image/") ||
      file.type.startsWith("video/") ||
      /\.(jpe?g|png|webp|bmp|tiff?|mp4|mov|webm|mkv|avi)$/.test(name)
    ) {
      void loadMedia(file);
    }
    else toolbar.setError(`不支持的文件类型：${file.name}`);
  }

  let dragDepth = 0;
  const hasFiles = (ev: DragEvent) => ev.dataTransfer?.types.includes("Files") ?? false;
  center.addEventListener("dragenter", (ev) => {
    if (!hasFiles(ev)) return;
    ev.preventDefault();
    dragDepth += 1;
    center.classList.add("is-dragover");
  });
  center.addEventListener("dragover", (ev) => {
    if (!hasFiles(ev)) return;
    ev.preventDefault();
    if (ev.dataTransfer) ev.dataTransfer.dropEffect = "copy";
  });
  center.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0) center.classList.remove("is-dragover");
  });
  center.addEventListener("drop", (ev) => {
    ev.preventDefault();
    dragDepth = 0;
    center.classList.remove("is-dragover");
    const file = ev.dataTransfer?.files?.[0];
    if (file) importDropped(file);
  });

  window.addEventListener("keydown", (ev) => {
    const editing =
      ev.target instanceof HTMLTextAreaElement ||
      ev.target instanceof HTMLInputElement;
    if (ev.key === "Escape" && pinnedSrc) unpin();
    if (ev.key === " " && !editing) {
      spaceDown = true;
      ev.preventDefault();
    }
    if (ev.ctrlKey && ev.key.toLowerCase() === "z") {
      ev.preventDefault();
      if (store.undo()) void rebakeLut();
    }
    if (ev.ctrlKey && ev.key.toLowerCase() === "y") {
      ev.preventDefault();
      if (store.redo()) void rebakeLut();
    }
  });
  window.addEventListener("keyup", (ev) => {
    if (ev.key === " ") spaceDown = false;
  });

  aiBtn.addEventListener("click", () => void runAi());

  toolbar.onImportImage = (f) => void loadMedia(f);
  toolbar.onImportVideo = (f) => void loadMedia(f);
  toolbar.onImportCube = (f) => void importCube(f);
  toolbar.onCompareChange = (mode) => {
    store.compareMode = mode;
    store.emit();
  };
  toolbar.onUndo = () => {
    if (store.undo()) void rebakeLut();
  };
  toolbar.onRedo = () => {
    if (store.redo()) void rebakeLut();
  };
  toolbar.onExport = (k) => void runExport(k);

  syncUi();
}
