import type { CompareMode } from "../core/state_store";
import {
  iconCube,
  iconDownload,
  iconImage,
  iconRedo,
  iconUndo,
  iconVideo,
} from "./icons";

type ExportKind = "image" | "video" | "lut";

export interface TopToolbarHandlers {
  onImportImage?: (f: File) => void;
  onImportVideo?: (f: File) => void;
  onImportCube?: (f: File) => void;
  onCompareChange?: (mode: CompareMode) => void;
  onUndo?: () => void;
  onRedo?: () => void;
  onExport?: (kind: ExportKind) => void;
}

export interface TopToolbarController extends TopToolbarHandlers {
  bar: HTMLElement;
  setProgress: (p: number, msg: string) => void;
  setStatus: (msg: string) => void;
  /** 顶栏错误提示；传空串清除 */
  setError: (msg: string) => void;
  setExporting: (busy: boolean) => void;
  pickImage: () => void;
  pickVideo: () => void;
  updateHistory: (canUndo: boolean, canRedo: boolean) => void;
}

export function buildTopToolbar(): TopToolbarController {
  const handlers: TopToolbarHandlers = {};
  const bar = document.createElement("header");
  bar.className = "toolbar top-toolbar";

  const left = document.createElement("div");
  left.className = "toolbar-zone toolbar-left";
  const center = document.createElement("div");
  center.className = "toolbar-zone toolbar-center";
  const right = document.createElement("div");
  right.className = "toolbar-zone toolbar-right";

  const fileImg = hiddenFile("image/*");
  const fileVid = hiddenFile("video/*");
  const fileCube = hiddenFile(".cube", false);

  left.append(
    iconBtn("导入图片", iconImage, () => fileImg.click()),
    iconBtn("导入视频", iconVideo, () => fileVid.click()),
    iconBtn("导入 .cube", iconCube, () => fileCube.click()),
  );

  const seg = document.createElement("div");
  seg.className = "seg seg-premium";
  const modes: { id: CompareMode; label: string }[] = [
    { id: "preview", label: "调色预览" },
    { id: "split", label: "A/B 分屏" },
    { id: "hold", label: "按住原图" },
    { id: "lut3d", label: "3D 色彩立方体" },
  ];
  const segButtons: HTMLButtonElement[] = [];
  for (const m of modes) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = m.label;
    b.dataset.mode = m.id;
    b.addEventListener("click", () => {
      handlers.onCompareChange?.(m.id);
      for (const x of segButtons) {
        x.classList.toggle("active", x.dataset.mode === m.id);
      }
    });
    if (m.id === "preview") b.classList.add("active");
    segButtons.push(b);
    seg.appendChild(b);
  }
  center.appendChild(seg);

  const undoBtn = iconBtn("撤销", iconUndo, () => handlers.onUndo?.(), true);
  const redoBtn = iconBtn("重做", iconRedo, () => handlers.onRedo?.(), true);

  const exportWrap = document.createElement("div");
  exportWrap.className = "export-wrap";
  const exportBtn = document.createElement("button");
  exportBtn.type = "button";
  exportBtn.className = "btn btn-export";
  exportBtn.innerHTML = `${iconDownload}<span>导出</span><span class="caret">▾</span>`;
  const exportMenu = document.createElement("div");
  exportMenu.className = "export-menu";
  for (const [k, label] of [
    ["image", "导出无损图像"],
    ["video", "导出调色视频"],
    ["lut", "导出 .cube LUT"],
  ] as const) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "export-menu-item";
    item.textContent = label;
    item.addEventListener("click", () => {
      exportMenu.classList.remove("open");
      if (exportBtn.disabled) return;
      handlers.onExport?.(k);
    });
    exportMenu.appendChild(item);
  }
  const exportNote = document.createElement("div");
  exportNote.className = "export-menu-note";
  exportNote.textContent = "注：离线导出包含完整 3D LUT 调色，光学晕光仅作用于实时预览";
  exportMenu.appendChild(exportNote);
  exportBtn.addEventListener("click", () => {
    if (exportBtn.disabled) return;
    exportMenu.classList.toggle("open");
  });
  exportWrap.append(exportBtn, exportMenu);

  const errorText = document.createElement("div");
  errorText.className = "toolbar-error";
  errorText.hidden = true;
  const progress = document.createElement("div");
  progress.className = "toolbar-progress";
  right.append(errorText, progress, undoBtn, redoBtn, exportWrap);

  bar.append(left, center, right);

  fileImg.addEventListener("change", () => {
    const f = fileImg.files?.[0];
    if (f) handlers.onImportImage?.(f);
    fileImg.value = "";
  });
  fileVid.addEventListener("change", () => {
    const f = fileVid.files?.[0];
    if (f) handlers.onImportVideo?.(f);
    fileVid.value = "";
  });
  fileCube.addEventListener("change", () => {
    const f = fileCube.files?.[0];
    if (f) handlers.onImportCube?.(f);
    fileCube.value = "";
  });

  const controller: TopToolbarController = {
    bar,
    setProgress(p: number, msg: string) {
      if (p < 0) {
        progress.textContent = "";
        return;
      }
      progress.textContent = `${Math.round(p * 100)}% ${msg}`;
    },
    setStatus(msg: string) {
      progress.textContent = msg;
    },
    setError(msg: string) {
      errorText.textContent = msg;
      errorText.title = msg;
      errorText.hidden = msg === "";
    },
    pickImage() {
      fileImg.click();
    },
    pickVideo() {
      fileVid.click();
    },
    setExporting(busy: boolean) {
      exportBtn.disabled = busy;
      exportBtn.classList.toggle("disabled", busy);
      exportBtn.setAttribute("aria-busy", String(busy));
      if (busy) exportMenu.classList.remove("open");
    },
    updateHistory(canUndo: boolean, canRedo: boolean) {
      undoBtn.disabled = !canUndo;
      redoBtn.disabled = !canRedo;
      undoBtn.classList.toggle("disabled", !canUndo);
      redoBtn.classList.toggle("disabled", !canRedo);
    },
  };

  Object.defineProperties(controller, {
    onImportImage: {
      set(v: (f: File) => void) {
        handlers.onImportImage = v;
      },
      enumerable: true,
      configurable: true,
    },
    onImportVideo: {
      set(v: (f: File) => void) {
        handlers.onImportVideo = v;
      },
      enumerable: true,
      configurable: true,
    },
    onImportCube: {
      set(v: (f: File) => void) {
        handlers.onImportCube = v;
      },
      enumerable: true,
      configurable: true,
    },
    onCompareChange: {
      set(v: (m: CompareMode) => void) {
        handlers.onCompareChange = v;
      },
      enumerable: true,
      configurable: true,
    },
    onUndo: {
      set(v: () => void) {
        handlers.onUndo = v;
      },
      enumerable: true,
      configurable: true,
    },
    onRedo: {
      set(v: () => void) {
        handlers.onRedo = v;
      },
      enumerable: true,
      configurable: true,
    },
    onExport: {
      set(v: (k: ExportKind) => void) {
        handlers.onExport = v;
      },
      enumerable: true,
      configurable: true,
    },
  });

  return controller;
}

function iconBtn(
  label: string,
  icon: string,
  onClick: () => void,
  iconOnly = false,
): HTMLButtonElement {
  const b = document.createElement("button");
  b.type = "button";
  b.className = iconOnly ? "btn btn-icon" : "btn btn-icon-text";
  b.title = label;
  b.innerHTML = iconOnly ? icon : `${icon}<span>${label}</span>`;
  b.addEventListener("click", onClick);
  return b;
}

function hiddenFile(accept: string, withAccept = true): HTMLInputElement {
  const input = document.createElement("input");
  input.type = "file";
  if (withAccept) input.accept = accept;
  input.hidden = true;
  document.body.appendChild(input);
  return input;
}