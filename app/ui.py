"""Tkinter desktop UI for the AI colour grading project."""

from __future__ import annotations

import logging
import queue
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
from PIL import Image, ImageTk

from ai.offline import OfflineProvider
from ai.prompts import STYLE_PRESETS, preset_text
from ai.provider import (
    AIError,
    AIConfig,
    Proposal,
    build_provider,
    load_config,
    summary_from_params,
)
from baker.cube_reader import CubeError, load_cube
from baker.params import (
    ColorParams,
    HUE_PARAMS,
    PARAM_GROUPS,
    PARAM_KEYS,
    PARAM_LABELS,
    PARAM_RANGES,
)

from . import histogram as histogram_mod, image_io, paths, theme as theme_mod, video_io
from .histogram import compute_histogram, render_histogram
from .image_io import ImageError
from .jobs import JobOutcome, LatestJobRunner
from .pipeline import (
    PREVIEW_LONG_SIDE,
    ExportResult,
    PreviewResult,
    RenderPipeline,
    RenderSnapshot,
)
from .session import DocumentSession, ExportTicket
from .state import AppState
from .widgets import StatusChip, Tooltip, shorten_middle, shorten_path

LOGGER = logging.getLogger("ai_color.ui")

_PALETTE = theme_mod.PALETTE
BG = _PALETTE.canvas
CANVAS_TEXT = _PALETTE.text
HIST_HEIGHT = 72
HIST_BG = _PALETTE.canvas_edge
HIST_SIDE_MARGIN = 24
PREVIEW_DEBOUNCE_MS = 60
SIDEBAR_WIDTH = 400
# How long an export result stays on the status line before previews may
# overwrite it. Long enough to read a path, short enough to feel live.
EXPORT_NOTICE_SECONDS = 6.0


def _describe_error(exc: BaseException) -> str:
    code = getattr(exc, "code", "")
    message = getattr(exc, "message", str(exc))
    if code:
        return f"{code}：{message}"
    return message


def _format_param(key: str, value: float) -> str:
    if key == "exposure_ev":
        return f"{value:+.2f}"
    if key in HUE_PARAMS:
        return f"{value:.0f}°"
    return f"{value:+.0f}"


def _hue_color(hue: float) -> str:
    """Opaque hex colour for a hue angle, used by the split-tone swatches."""
    from baker.color_transform import hue_to_rgb

    r, g, b = (int(round(v * 255)) for v in hue_to_rgb(hue))
    return f"#{r:02x}{g:02x}{b:02x}"


_ExportTicket = ExportTicket


class ColorApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.session = DocumentSession()
        self.state = self.session.state
        self._closing = False
        self._original_preview: Image.Image | None = None
        self._processed_preview: Image.Image | None = None
        self._display_photo: ImageTk.PhotoImage | None = None
        self._checker_cache: dict[tuple[int, int], Image.Image] = {}
        self._debounce_id: str | None = None
        self._syncing_sliders = False
        self._param_vars: dict[str, tk.DoubleVar] = {}
        self._param_value_labels: dict[str, ttk.Label] = {}
        self._drag_mode: str | None = None
        self._drag_start = (0.0, 0.0)
        self._drag_pan = (0.0, 0.0)
        self._last_render_ms: float | None = None
        self._ai_request_seq = 0
        self._ai_busy = False
        self._worker_ok = False
        self._worker_detail = ""
        self._display_geom: tuple[float, float, float, float, float] | None = None
        self._hist_current: histogram_mod.Histogram | None = None
        self._hist_original: histogram_mod.Histogram | None = None
        self._hist_photo: ImageTk.PhotoImage | None = None
        self._hist_size: tuple[int, int] = (-1, -1)
        self._sidebar_window: int | None = None
        self._ai_placeholder = "在此处描述你想要实现的处理和效果"
        self._ai_placeholder_active = False
        self._export_notice_until = 0.0
        self._export_summary: tuple[str, str] | None = None
        self._preview_error: str | None = None
        self._video_frame_token = 0
        self._video_progress: float | None = None
        self._video_poll_id: str | None = None
        self._video_seek_id: str | None = None
        self._video_play_id: str | None = None
        self._video_playing = False
        self._video_digests: dict[tuple[Path, int], str] = {}
        self._video_results: queue.Queue = queue.Queue()

        self._configure_root()
        self._init_services()
        self._build_ui()
        self._refresh_ai_status()
        self._update_summary()
        self._set_controls_enabled(False)
        self._redraw()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(40, self._poll)

    @property
    def _pending_proposal(self) -> Proposal | None:
        return self._ensure_session().pending_proposal

    @_pending_proposal.setter
    def _pending_proposal(self, value: Proposal | None) -> None:
        self._ensure_session().pending_proposal = value

    @property
    def _export_tickets(self) -> list[ExportTicket]:
        return self._ensure_session().export_tickets

    @_export_tickets.setter
    def _export_tickets(self, value: list[ExportTicket]) -> None:
        self._ensure_session().export_tickets = value

    @property
    def _batch_active(self) -> bool:
        return self._ensure_session().batch_active

    @_batch_active.setter
    def _batch_active(self, value: bool) -> None:
        self._ensure_session().batch_active = bool(value)

    @property
    def _export_seq(self) -> int:
        return self._ensure_session().export_seq

    @_export_seq.setter
    def _export_seq(self, value: int) -> None:
        self._ensure_session().export_seq = int(value)

    def _ensure_session(self) -> DocumentSession:
        session = getattr(self, "session", None)
        if session is not None:
            return session
        session = DocumentSession()
        if hasattr(self, "state"):
            session.state = self.state
        self.session = session
        return session

    # ------------------------------------------------------------------
    # setup
    # ------------------------------------------------------------------
    def _configure_root(self) -> None:
        self.root.title("AI 调色 · 3D LUT")
        # Request a comfortable size in 96-dpi units, scaled to whatever DPI the
        # window manager reports, and never exceed the usable screen. Without
        # this the window either overflows a 1280x800 display or comes out at
        # half size on a 200% scaled one.
        scale = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        margin_w = int(round(32 * scale))
        margin_h = int(round(64 * scale))
        width = max(
            int(round(1180 * scale)),
            min(int(round(1440 * scale)), screen_w - margin_w),
        )
        height = max(
            int(round(720 * scale)),
            min(int(round(900 * scale)), screen_h - margin_h),
        )
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(
            int(round(1120 * scale)), int(round(700 * scale))
        )
        try:
            self.root.tk.call(
                "tk", "scaling", self.root.winfo_fpixels("1i") / 72.0
            )
        except tk.TclError:
            pass
        # One theme object owns every colour, size and font used below.
        self.theme: theme_mod.Theme = theme_mod.apply(self.root)
        self._tip = lambda widget, text="": Tooltip(widget, text)
        theme_mod.bind_dark_titlebar(self.root)

    def _init_services(self) -> None:
        try:
            paths.ensure_runtime()
            paths.cleanup_old_jobs(24.0)
            removed, freed = paths.prune_cache()
            if removed:
                LOGGER.info(
                    "cache pruned at startup: %s files, %.1f MB", removed, freed / 1e6
                )
        except Exception as exc:  # surfaced in the status area
            LOGGER.exception("runtime directory failure")
            self.state.last_error = str(exc)
        try:
            self.config: AIConfig = load_config()
            self._config_error = ""
        except AIError as exc:
            self.config = AIConfig(offline_only=True)
            self._config_error = _describe_error(exc)
        ok, detail = paths.check_worker()
        self._worker_ok = ok
        self._worker_detail = detail
        try:
            self.pipeline = RenderPipeline()
        except Exception:
            self.pipeline = None  # type: ignore[assignment]
            self._worker_ok = False

        self.runner = LatestJobRunner("render")
        self.ai_runner = LatestJobRunner("ai")
        self._batch_window = None

    def _build_ui(self) -> None:
        self.root.rowconfigure(1, weight=1)
        self.root.columnconfigure(0, weight=1)
        t = self.theme

        # -- toolbar ---------------------------------------------------
        # Grouped so the eye can find file / export / view actions without
        # reading every label: [open|batch|LUT] | [image|video|LUT export] |
        # [reset|histogram] ................ [material] [engine].
        toolbar = ttk.Frame(
            self.root, style="Toolbar.TFrame",
            padding=(t.px(12), t.px(8), t.px(12), t.px(6)),
        )
        toolbar.grid(row=0, column=0, sticky="ew")

        self.open_btn = ttk.Button(
            toolbar, text="打开素材", style="Accent.TButton", command=self.open_image
        )
        self.open_btn.pack(side="left", padx=(0, 4))
        self.batch_btn = ttk.Button(
            toolbar, text="批处理…", command=self.open_batch_window
        )
        self.batch_btn.pack(side="left", padx=(0, 4))
        self.import_btn = ttk.Button(
            toolbar, text="导入 LUT", command=self.import_lut
        )
        self.import_btn.pack(side="left", padx=4)
        self._toolbar_separator(toolbar)

        self.export_img_btn = ttk.Button(
            toolbar, text="导出图片", command=self.export_image
        )
        self.export_img_btn.pack(side="left", padx=4)
        self.export_video_btn = ttk.Button(
            toolbar, text="导出视频", command=self.export_video
        )
        self.export_video_btn.pack(side="left", padx=4)
        self.export_lut_btn = ttk.Button(
            toolbar, text="导出 LUT", command=self.export_lut
        )
        self.export_lut_btn.pack(side="left", padx=4)
        self._toolbar_separator(toolbar)

        self.reset_btn = ttk.Button(toolbar, text="重置", command=self.reset_all)
        self.reset_btn.pack(side="left", padx=4)
        self._tip(self.reset_btn, "把参数、强度和视图恢复默认（不影响导出队列）")

        self.hist_var = tk.BooleanVar(value=True)
        self.hist_btn = ttk.Checkbutton(
            toolbar,
            text="直方图",
            variable=self.hist_var,
            command=self._toggle_histogram,
        )
        self.hist_btn.pack(side="left", padx=(4, 0))

        self.worker_badge = ttk.Label(toolbar, text="", style="Hint.TLabel")
        self.worker_badge.pack(side="right", padx=(t.px(10), 0))
        self.material_label = ttk.Label(
            toolbar, text="未打开素材", style="ToolbarMaterial.TLabel"
        )
        self.material_label.pack(side="right")
        self.material_tip = self._tip(self.material_label, "尚未打开素材")

        body = ttk.Frame(self.root)
        body.grid(row=1, column=0, sticky="nsew", padx=t.px(12), pady=(0, t.px(2)))
        body.rowconfigure(0, weight=1)
        body.rowconfigure(1, weight=0)
        body.columnconfigure(0, weight=1)

        # The preview sits inside a one-pixel frame so it reads as an image
        # canvas rather than a hole in the window, including at 150% dpi.
        canvas_holder = ttk.Frame(body, style="Canvas.TFrame")
        canvas_holder.grid(row=0, column=0, sticky="nsew")
        canvas_holder.rowconfigure(0, weight=1)
        canvas_holder.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            canvas_holder,
            bg=BG,
            highlightthickness=0,
            bd=0,
            cursor="crosshair",
        )
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<MouseWheel>", self._on_wheel)

        # The histogram is its own band between the photo and the compare bar:
        # centred, deliberately narrower than the canvas, so the three zones
        # read as image / meter / controls instead of one merged toolbar.
        self.hist_holder = ttk.Frame(body, style="Canvas.TFrame")
        self.hist_holder.grid(row=1, column=0, sticky="ew", pady=(t.px(10), t.px(2)))
        self.hist_holder.grid_propagate(False)
        self.hist_holder.bind(
            "<Configure>", lambda _e: self._refresh_histogram()
        )

        self.hist_label = tk.Label(
            self.hist_holder,
            bg=HIST_BG,
            bd=0,
            highlightthickness=0,
        )
        self.hist_label.place(relx=0.5, rely=0.5, anchor="center")

        # Video strip: only mapped for clips, tucked between the meter and the
        # compare bar so the still-image layout is unchanged.
        self.video_bar = ttk.Frame(body, style="Panel.TFrame")
        self.video_bar.grid(row=2, column=0, sticky="ew", pady=(t.px(8), 0))
        self.video_bar.columnconfigure(1, weight=1)
        nav = ttk.Frame(self.video_bar)
        nav.grid(row=0, column=0, sticky="w")
        self.video_play_btn = ttk.Button(
            nav, text="播放", width=6, command=self._toggle_video_playback,
            state="disabled",
        )
        self.video_play_btn.pack(side="left", padx=(0, 2))
        self.video_back_btn = ttk.Button(
            nav, text="◀ 1s", width=6, command=lambda: self._nudge_video(-1.0)
        )
        self.video_back_btn.pack(side="left", padx=(0, 2))
        self.video_fwd_btn = ttk.Button(
            nav, text="1s ▶", width=6, command=lambda: self._nudge_video(1.0)
        )
        self.video_fwd_btn.pack(side="left")
        self._tip(self.video_back_btn, "向前退 1 秒取帧")
        self._tip(self.video_fwd_btn, "向后进 1 秒取帧")
        self._tip(self.video_play_btn, "播放/暂停视频预览")
        self.video_scale = ttk.Scale(
            self.video_bar, from_=0.0, to=1000.0, command=self._on_video_scale
        )
        self.video_scale.grid(row=0, column=1, sticky="ew", padx=8)
        self.video_scale.bind("<ButtonRelease-1>", self._on_video_release)
        self.video_time_label = ttk.Label(
            self.video_bar, text="00:00.00 / 00:00.00", style="Hint.TLabel"
        )
        self.video_time_label.grid(row=0, column=2, sticky="e", padx=(0, 6))
        self.video_hint = ttk.Label(
            self.video_bar,
            text="拖动取帧调色，导出视频会按当前 LUT 重新编码",
            style="Hint.TLabel",
        )
        self.video_hint.grid(row=1, column=0, columnspan=3, sticky="w", pady=(2, 0))
        self.video_bar.grid_remove()

        ttk.Separator(body, orient="vertical").grid(
            row=0, column=1, rowspan=2, sticky="ns", padx=(t.px(12), t.px(6))
        )

        sidebar_holder = ttk.Frame(body, style="Panel.TFrame")
        sidebar_holder.grid(row=0, column=2, rowspan=2, sticky="ns")
        sidebar_holder.rowconfigure(0, weight=1)
        sidebar_holder.columnconfigure(0, weight=1)
        self.sidebar_canvas = tk.Canvas(
            sidebar_holder,
            width=int(round(SIDEBAR_WIDTH * self._dpi_scale())),
            bg=t.palette.surface,
            bd=0,
            highlightthickness=0,
            yscrollincrement=18,
        )
        self.sidebar_canvas.grid(row=0, column=0, sticky="ns")
        sidebar_bar = ttk.Scrollbar(
            sidebar_holder, orient="vertical", command=self.sidebar_canvas.yview
        )
        sidebar_bar.grid(row=0, column=1, sticky="ns")
        self.sidebar_canvas.configure(yscrollcommand=sidebar_bar.set)

        sidebar = ttk.Frame(self.sidebar_canvas, padding=(2, 4, 10, 8))
        self._sidebar_window = self.sidebar_canvas.create_window(
            (0, 0), window=sidebar, anchor="nw"
        )
        sidebar.bind(
            "<Configure>",
            lambda _e: self.sidebar_canvas.configure(
                scrollregion=self.sidebar_canvas.bbox("all")
            ),
        )
        self.sidebar_canvas.bind(
            "<Configure>",
            lambda e: self.sidebar_canvas.itemconfigure(
                self._sidebar_window, width=e.width
            ),
        )
        self.sidebar_canvas.bind_all("<MouseWheel>", self._scroll_sidebar, add="+")
        self.sidebar_canvas.bind_all("<Button-4>", self._scroll_sidebar, add="+")
        self.sidebar_canvas.bind_all("<Button-5>", self._scroll_sidebar, add="+")
        self._build_sidebar(sidebar)

        # Status area: controls, then one line per concurrent activity (preview /
        # AI / export / batch), then the last result. They used to share a single
        # line, so a finishing preview could erase an export notice.
        bottom = ttk.Frame(
            self.root, style="Status.TFrame",
            padding=(t.px(12), t.px(8), t.px(12), t.px(8)),
        )
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(1, weight=1)

        self.compare_group = ttk.Frame(bottom)
        self.compare_group.grid(row=0, column=0, sticky="w")
        self.ab_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            self.compare_group,
            text="A/B 对比",
            variable=self.ab_var,
            command=self._toggle_ab,
        ).pack(side="left")
        self.split_var = tk.DoubleVar(value=1.0)
        self.split_scale = ttk.Scale(
            self.compare_group,
            from_=0.0,
            to=1.0,
            variable=self.split_var,
            command=self._on_split_scale,
            length=132,
        )
        self.split_scale.pack(side="left", padx=(10, 0))
        self.hold_btn = ttk.Button(
            self.compare_group, text="按住查看原图"
        )
        self.hold_btn.pack(side="left", padx=(14, 0))
        self.hold_btn.bind("<ButtonPress-1>", lambda _e: self._set_hold(True))
        self.hold_btn.bind("<ButtonRelease-1>", lambda _e: self._set_hold(False))

        self.view_group = ttk.Frame(bottom)
        self.view_group.grid(row=0, column=2, sticky="e")
        self.zoom_fit_btn = ttk.Button(
            self.view_group, text="适配", command=self._zoom_fit, width=6
        )
        self.zoom_fit_btn.pack(side="left", padx=(0, 4))
        self.zoom_one_btn = ttk.Button(
            self.view_group, text="1:1", command=self._zoom_one, width=6
        )
        self.zoom_one_btn.pack(side="left")
        self._tip(self.zoom_fit_btn, "整幅适配窗口（Ctrl+0）")
        self._tip(self.zoom_one_btn, "按 100% 显示原像素")
        self.zoom_label = ttk.Label(
            self.view_group, text="适配", style="Hint.TLabel"
        )
        self.zoom_label.pack(side="left", padx=(10, 0))

        self.busy_var = tk.StringVar(value="")
        self.busy_label = ttk.Label(
            bottom, textvariable=self.busy_var, style="StatusRunning.TLabel"
        )
        self.busy_label.grid(row=0, column=1, sticky="e", padx=(16, 12))

        ttk.Separator(bottom, orient="horizontal").grid(
            row=1, column=0, columnspan=3, sticky="ew", pady=(t.px(6), t.px(4))
        )

        chips = ttk.Frame(bottom)
        chips.grid(row=2, column=0, columnspan=3, sticky="ew")
        self.preview_chip = StatusChip(chips, "预览")
        self.preview_chip.pack(side="left")
        self.ai_chip = StatusChip(chips, "AI")
        self.ai_chip.pack(side="left", padx=(t.px(14), 0))
        self.export_chip = StatusChip(chips, "导出")
        self.export_chip.pack(side="left", padx=(t.px(14), 0))
        self.batch_chip = StatusChip(chips, "批次")
        self.batch_chip.pack(side="left", padx=(t.px(14), 0))

        self.message_var = tk.StringVar(value="")
        self.message_label = ttk.Label(
            bottom, textvariable=self.message_var, anchor="w",
            style="Status.TLabel",
        )
        self.message_label.grid(
            row=3, column=0, columnspan=3, sticky="ew", pady=(t.px(4), 0)
        )

        self.root.bind("<Control-o>", lambda _e: self.open_image())
        self.root.bind("<Control-b>", lambda _e: self.open_batch_window())
        self.root.bind("<Control-e>", lambda _e: self.export_image())
        self.root.bind("<Control-Shift-E>", lambda _e: self.export_lut())
        self.root.bind("<KeyPress-space>", self._space_down)
        self.root.bind("<KeyRelease-space>", self._space_up)

        if self._worker_ok:
            self.worker_badge.configure(text="● 引擎就绪", style="StatusOk.TLabel")
        else:
            self.worker_badge.configure(
                text="● 引擎不可用", style="StatusError.TLabel"
            )
            self._set_message(
                "渲染引擎不可用：" + self._worker_detail + "。图片预览与导出不可用，可先检查 worker 路径或改用其它素材。",
                error=True,
            )
        self._refresh_status_chips()

    def _toolbar_separator(self, parent: tk.Misc) -> None:
        ttk.Separator(parent, orient="vertical").pack(
            side="left", fill="y", padx=self.theme.px(8), pady=self.theme.px(2)
        )

    def _sidebar_section(
        self,
        parent: ttk.Frame,
        row: int,
        title: str,
        hint: tk.StringVar | None = None,
    ) -> int:
        """Draw a rule plus a section heading with a small accent bar.

        The bar is the only saturated mark in the sidebar; it gives the eye a
        consistent anchor for "a new group starts here" without turning every
        heading into a coloured block.
        """
        t = self.theme
        ttk.Separator(parent, orient="horizontal").grid(
            row=row, column=0, sticky="ew", pady=(t.px(8), t.px(2))
        )
        header = ttk.Frame(parent)
        header.grid(row=row + 1, column=0, sticky="ew", pady=(t.px(4), t.px(5)))
        ttk.Label(header, text=title, style="Section.TLabel").pack(side="left")
        if hint is not None:
            ttk.Label(
                header, textvariable=hint, style="Hint.TLabel"
            ).pack(side="right")
        return row + 2

    def _build_sidebar(self, parent: ttk.Frame) -> None:
        t = self.theme
        parent.columnconfigure(0, weight=1)
        row = 0
        ttk.Label(parent, text="AI 调色", style="Title.TLabel").grid(
            row=row, column=0, sticky="w"
        )
        row += 1

        # -- material --------------------------------------------------
        row = self._sidebar_section(parent, row, "素材")
        self.source_info_var = tk.StringVar(
            value="未打开素材。打开图片或视频后可在此查看尺寸、色彩与耗时。"
        )
        ttk.Label(
            parent,
            textvariable=self.source_info_var,
            style="Hint.TLabel",
            wraplength=t.px(330),
            justify="left",
        ).grid(row=row, column=0, sticky="w")
        row += 1

        # -- AI --------------------------------------------------------
        row = self._sidebar_section(parent, row, "AI 辅助")
        style_frame = ttk.Frame(parent)
        style_frame.grid(row=row, column=0, sticky="ew", pady=(0, t.px(6)))
        for column in range(3):
            style_frame.columnconfigure(column, weight=1)
        for index, preset in enumerate(STYLE_PRESETS):
            grid_row, grid_col = divmod(index, 3)
            ttk.Button(
                style_frame,
                text=preset.label,
                width=8,
                command=lambda key=preset.key: self._apply_style_preset(key),
            ).grid(
                row=grid_row,
                column=grid_col,
                sticky="ew",
                padx=(0, 4),
                pady=(0, 4),
            )
        row += 1

        self.ai_text = tk.Text(
            parent,
            height=4,
            wrap="word",
            font=t.font(),
            relief="flat",
            bd=0,
            padx=t.px(6),
            pady=t.px(4),
            bg=t.palette.input,
            fg=t.palette.text,
            insertbackground=t.palette.text,
            selectbackground=t.palette.accent_dim,
            selectforeground=t.palette.text,
            highlightthickness=1,
            highlightbackground=t.palette.border,
            highlightcolor=t.palette.accent,
        )
        self.ai_text.grid(row=row, column=0, sticky="ew")
        self.ai_text.bind("<KeyRelease>", self._on_ai_text_key)
        self.ai_text.bind("<FocusIn>", self._clear_ai_placeholder)
        self.ai_text.bind("<FocusOut>", self._restore_ai_placeholder)
        row += 1
        intent_row = ttk.Frame(parent)
        intent_row.grid(row=row, column=0, sticky="ew", pady=(2, 6))
        self.intent_count = ttk.Label(
            intent_row, text="0/2000", style="Hint.TLabel"
        )
        self.intent_count.pack(side="right")
        self._restore_ai_placeholder()
        row += 1

        ai_buttons = ttk.Frame(parent)
        ai_buttons.grid(row=row, column=0, sticky="ew", pady=(0, t.px(6)))
        self.ai_submit_btn = ttk.Button(
            ai_buttons, text="提交描述", style="Accent.TButton",
            command=self.submit_ai,
        )
        self.ai_submit_btn.pack(side="left")
        self.ai_cancel_btn = ttk.Button(
            ai_buttons, text="取消请求", command=self.cancel_ai
        )
        self.ai_cancel_btn.pack(side="left", padx=t.px(6))
        self.apply_proposal_btn = ttk.Button(
            ai_buttons,
            text="应用 AI 提案",
            command=self.apply_pending_proposal,
        )
        self._sync_pending_proposal_button()
        row += 1

        self.ai_status_var = tk.StringVar(value="")
        ttk.Label(
            parent,
            textvariable=self.ai_status_var,
            style="Hint.TLabel",
            wraplength=t.px(330),
        ).grid(row=row, column=0, sticky="w")
        row += 1

        row = self._sidebar_section(parent, row, "离线预设")

        presets = ttk.Frame(parent)
        presets.grid(row=row, column=0, sticky="ew")
        for column in range(3):
            presets.columnconfigure(column, weight=1)
        from baker.params import list_presets

        for index, (key, label, _params) in enumerate(list_presets()):
            grid_row, grid_col = divmod(index, 3)
            ttk.Button(
                presets,
                text=label,
                width=8,
                command=lambda k=key: self.apply_preset(k),
            ).grid(
                row=grid_row,
                column=grid_col,
                sticky="ew",
                padx=(0, 4),
                pady=(0, 4),
            )
        row += 1

        self.mode_var = tk.StringVar(value="参数模式")
        row = self._sidebar_section(parent, row, "参数", hint=self.mode_var)

        param_actions = ttk.Frame(parent)
        param_actions.grid(row=row, column=0, sticky="ew", pady=(0, t.px(4)))
        self.reset_params_btn = ttk.Button(
            param_actions, text="重置参数", command=self.reset_all
        )
        self.reset_params_btn.pack(side="left")
        self._tip(
            self.reset_params_btn,
            "只把调色参数、强度和视图恢复默认；不影响素材、导出队列与批处理",
        )
        self.back_to_params_btn = ttk.Button(
            param_actions, text="退出外部 LUT", command=self.return_to_params
        )
        self.back_to_params_btn.pack(side="left", padx=(t.px(6), 0))
        self.back_to_params_btn.pack_forget()
        row += 1

        params_frame = ttk.Frame(parent)
        params_frame.grid(row=row, column=0, sticky="ew")
        params_frame.columnconfigure(0, weight=1)
        self._build_param_pages(params_frame)
        row += 1

        strength_row = ttk.Frame(parent)
        strength_row.grid(row=row, column=0, sticky="ew", pady=(8, 0))
        strength_row.columnconfigure(1, weight=1)
        row += 1
        ttk.Label(strength_row, text="强度", width=9).grid(
            row=0, column=0, sticky="w"
        )
        self.strength_var = tk.DoubleVar(value=1.0)
        self.strength_scale = ttk.Scale(
            strength_row,
            from_=0.0,
            to=1.0,
            variable=self.strength_var,
            command=self._on_strength_slider,
        )
        self.strength_scale.grid(row=0, column=1, sticky="ew", padx=4)
        self.strength_label = ttk.Label(
            strength_row, text="100%", width=6, anchor="e"
        )
        self.strength_label.grid(row=0, column=2, sticky="e")
        self.strength_scale.bind(
            "<ButtonRelease-1>",
            lambda _e: self._start_preview(immediate=True),
        )

        ttk.Separator(parent, orient="horizontal").grid(
            row=row, column=0, sticky="ew", pady=(t.px(10), t.px(6))
        )
        row += 1
        self.summary_var = tk.StringVar(value="")
        ttk.Label(
            parent,
            textvariable=self.summary_var,
            wraplength=t.px(330),
            justify="left",
            style="Hint.TLabel",
        ).grid(row=row, column=0, sticky="w")

    def _build_param_pages(self, parent: ttk.Frame) -> None:
        """Two-page parameter panel: basic tone/colour, then split toning.

        Sixteen sliders in one column would push the strength slider and summary
        off a 900 px window, so the rarely changed split-tone controls live on a
        second tab. The tab that is not visible still needs its values synced,
        which `_sync_sliders_from_state` already does by key.
        """
        self.param_notebook = ttk.Notebook(parent)
        self.param_notebook.grid(row=0, column=0, sticky="ew")
        self.param_scales: list[ttk.Scale] = []
        self._hue_swatches: dict[str, tk.Label] = {}

        for name, keys in PARAM_GROUPS:
            page = ttk.Frame(self.param_notebook, padding=(2, 6, 2, 4))
            page.columnconfigure(1, weight=1)
            for index, key in enumerate(keys):
                self._build_param_row(page, key, index)
            self.param_notebook.add(page, text=name)

    def _build_param_row(self, parent: ttk.Frame, key: str, index: int) -> None:
        low, high = PARAM_RANGES[key]
        ttk.Label(parent, text=PARAM_LABELS[key], width=9).grid(
            row=index, column=0, sticky="w", pady=2
        )
        variable = tk.DoubleVar(value=0.0)
        scale = ttk.Scale(
            parent,
            from_=low,
            to=high,
            variable=variable,
            command=lambda v, k=key: self._on_param_slider(k, v),
        )
        scale.grid(row=index, column=1, sticky="ew", padx=6, pady=2)
        value_label = ttk.Label(
            parent, text="+0", width=6, anchor="e", style="ValueZero.TLabel"
        )
        value_label.grid(row=index, column=2, sticky="e")
        scale.bind(
            "<ButtonRelease-1>",
            lambda _e: self._start_preview(immediate=True),
        )
        if key in HUE_PARAMS:
            swatch = tk.Label(
                parent,
                text="",
                width=2,
                bg=_hue_color(0.0),
                bd=0,
                relief="flat",
            )
            swatch.grid(row=index, column=3, padx=(4, 0), pady=2)
            self._hue_swatches[key] = swatch
        self._param_vars[key] = variable
        self._param_value_labels[key] = value_label
        self.param_scales.append(scale)

    def _scroll_sidebar(self, event: tk.Event) -> str:
        if self._closing:
            return "break"
        widget = getattr(event, "widget", None)
        if widget is None:
            return "break"
        try:
            if not (widget.winfo_rootx() <= event.x_root < widget.winfo_rootx() + widget.winfo_width()
                    and widget.winfo_rooty() <= event.y_root < widget.winfo_rooty() + widget.winfo_height()):
                return None
            if widget is self.canvas or str(widget).startswith(str(self.canvas)):
                return None
            if not (
                str(widget).startswith(str(self.sidebar_canvas))
                or str(widget).startswith(str(self.sidebar_canvas.master))
            ):
                return None
        except tk.TclError:
            return None
        delta = getattr(event, "delta", 0)
        if getattr(event, "num", None) == 4:
            units = -2
        elif getattr(event, "num", None) == 5:
            units = 2
        else:
            units = -int(delta / 120) * 2 if delta else 0
            if units == 0 and delta:
                units = -1 if delta > 0 else 1
        if units:
            self.sidebar_canvas.yview_scroll(units, "units")
        return "break"

    def _clear_ai_placeholder(self, _event=None) -> None:
        if self._ai_placeholder_active:
            self.ai_text.delete("1.0", "end")
            self.ai_text.configure(fg=self.theme.palette.text)
            self._ai_placeholder_active = False
            self._update_intent_count()

    def _restore_ai_placeholder(self, _event=None) -> None:
        if not self.ai_text.get("1.0", "end-1c").strip():
            self.ai_text.delete("1.0", "end")
            self.ai_text.insert("1.0", self._ai_placeholder)
            self.ai_text.configure(fg=self.theme.palette.text_muted)
            self._ai_placeholder_active = True
            self.intent_count.configure(text="0/2000")

    def _on_ai_text_key(self, event=None) -> None:
        if self._ai_placeholder_active:
            self._clear_ai_placeholder()
        self._update_intent_count()

    def _apply_style_preset(self, key: str) -> None:
        try:
            text = preset_text(key)
        except KeyError:
            return
        self._clear_ai_placeholder()
        current = self.ai_text.get("1.0", "end-1c").strip()
        merged = f"{current}；{text}" if current else text
        merged = merged[:2000]
        self.ai_text.delete("1.0", "end")
        self.ai_text.insert("1.0", merged)
        self._update_intent_count()
        self.ai_text.focus_set()
        self.ai_text.see("end")

    # ------------------------------------------------------------------
    # batch workspace
    # ------------------------------------------------------------------
    def open_batch_window(self) -> None:
        if self._closing:
            return
        if self.pipeline is None:
            self._set_message("渲染引擎不可用，无法执行批处理", error=True)
            messagebox.showwarning("批处理", "渲染引擎不可用")
            return
        window = getattr(self, "_batch_window", None)
        if window is not None:
            try:
                if window.winfo_exists():
                    window.deiconify()
                    window.lift()
                    window.focus_force()
                    return
            except tk.TclError:
                pass
            self._batch_window = None
        from .batch_ui import BatchWindow

        self._batch_window = BatchWindow(self.root, self)

    def set_batch_active(self, active: bool) -> None:
        """Freeze single-asset work while a batch owns the engine."""
        self._batch_active = bool(active)
        if active:
            try:
                self.runner.cancel("preview")
            except Exception:
                pass
        self._set_controls_enabled(
            (not active) and self.state.source is not None and self._worker_ok
        )
        state = "disabled" if active else "normal"
        for button in (self.open_btn, self.import_btn):
            button.configure(state=state)
        self.batch_btn.configure(state="disabled" if active else "normal")
        self._refresh_busy()

    # ------------------------------------------------------------------
    # status helpers
    # ------------------------------------------------------------------
    def _set_message(
        self, text: str, error: bool = False, role: str | None = None
    ) -> None:
        self.message_var.set(text)
        if role is None:
            role = "error" if error else "neutral"
        style = self._status_style(role)
        self.message_label.configure(style=style)
        if error:
            LOGGER.warning("%s", text)
        self._refresh_status_chips()

    def _status_style(self, role: str) -> str:
        """Map a semantic role to a theme style, tolerant of stub themes."""
        mapping = {
            "neutral": "Status.TLabel",
            "running": "StatusRunning.TLabel",
            "ok": "StatusOk.TLabel",
            "warn": "StatusWarn.TLabel",
            "error": "StatusError.TLabel",
        }
        if hasattr(self, "theme"):
            return self.theme.status_style(role)
        return mapping.get(role, "Status.TLabel")

    def _set_busy(self, text: str) -> None:
        self.busy_var.set(text)

    def _preview_message(self, text: str) -> None:
        """Write a preview status, unless a fresh export notice owns the line.

        The export result carries the output path and the revision it rendered;
        a preview finishing a moment later must not erase it before the user
        reads it. The notice decays on its own, so previews resume reporting.
        """
        if time.monotonic() < self._export_notice_until:
            return
        self._set_message(text)

    def _export_started(self, kind: str, revision: int, material: str = "") -> int:
        """Register an accepted export and return its identity token.

        The ticket is the source of truth for "this material still has an export
        in flight", so it is created before ``submit`` and removed exactly when
        the outcome is handled. ``material`` is the source name shown to the
        user, not a path.
        """
        token = self._ensure_session().export_started(kind, revision, material)
        self._refresh_busy()
        return token

    def _export_take(self, token: int | None, kind: str) -> ExportTicket | None:
        """Remove and return the ticket for this outcome, or None if unknown."""
        return self._ensure_session().export_take(token, kind)

    def _outstanding_exports(self) -> int:
        try:
            queued = self.runner.queued_count()
        except Exception:  # a stub runner in tests may not expose it
            queued = 0
        return self._ensure_session().outstanding_exports(queued)

    def _export_block_reason(self) -> str | None:
        try:
            queued = self.runner.queued_count()
        except Exception:
            queued = 0
        return self._ensure_session().export_block_reason(queued)

    def _refresh_busy(self) -> None:
        """Compose the one busy line from every concurrent activity.

        The line used to be written by whoever finished last, so a preview
        completing mid-export blanked the export notice, and an AI request hid a
        running export. Now each source contributes a part.
        """
        parts: list[str] = []
        if getattr(self, "_batch_active", False):
            parts.append("批处理进行中…")
        if self._export_tickets:
            first = self._export_tickets[0]
            kind, revision = first.kind, first.revision
            queued = self.runner.queued_count()
            # Exports run in FIFO order on the single worker thread, so the
            # tickets minus the still-queued ones is 0 (none started) or 1.
            running = len(self._export_tickets) - queued
            subject = f"（{first.material}）" if first.material else ""
            if running <= 0:
                text = f"正在导出{kind}{subject} rev {revision}…（等待当前渲染完成）"
                if len(self._export_tickets) > 1:
                    text += f"，共 {len(self._export_tickets)} 个导出排队"
            else:
                text = f"正在导出{kind}{subject} rev {revision}…"
                if queued:
                    text += f"（另有 {queued} 个导出排队）"
            parts.append(text)
        elif self.state.busy_revision is not None:
            parts.append(f"正在渲染 rev {self.state.busy_revision}…")
        if self._ai_busy:
            parts.append("AI 请求中…")
        progress = getattr(self, "_video_progress", None)
        if progress is not None:
            parts.append(f"视频编码 {progress * 100:.0f}%")
        self.busy_var.set(" · ".join(parts))
        self._refresh_status_chips()

    def _refresh_status_chips(self) -> None:
        """Fill the four persistent status fields.

        Each activity keeps its own field so they cannot overwrite each other:
        preview revision, AI request, this material's exports, and the batch.
        Colour follows the role (running / ok / warn / error) and is always
        accompanied by a text prefix and a worded state.
        """
        if not hasattr(self, "preview_chip"):
            return
        state = getattr(self, "state", None)

        # -- preview ---------------------------------------------------
        if state is None or getattr(state, "source", None) is None:
            self.preview_chip.set_value("无素材", "neutral")
        elif getattr(state, "busy_revision", None) is not None:
            self.preview_chip.set_value(
                f"渲染 rev {state.busy_revision}…", "running"
            )
        elif getattr(self, "_preview_error", None):
            self.preview_chip.set_value("渲染失败", "error")
        elif getattr(state, "last_completed_revision", None) == getattr(
            state, "revision", None
        ):
            ms = getattr(self, "_last_render_ms", None)
            suffix = f" · {ms:.0f} ms" if ms else ""
            self.preview_chip.set_value(f"rev {state.revision} 已更新{suffix}", "ok")
        else:
            self.preview_chip.set_value(f"rev {state.revision} 待更新", "warn")

        # -- AI --------------------------------------------------------
        if getattr(self, "_ai_busy", False):
            self.ai_chip.set_value("请求中…", "running")
        elif getattr(self, "_pending_proposal", None) is not None:
            self.ai_chip.set_value("提案待确认", "warn")
        elif getattr(getattr(self, "config", None), "offline_only", False):
            self.ai_chip.set_value("离线模式", "neutral")
        else:
            self.ai_chip.set_value("就绪", "neutral")

        # -- export ----------------------------------------------------
        tickets = getattr(self, "_export_tickets", [])
        if tickets:
            first = tickets[0]
            text = f"{first.kind} rev {first.revision}"
            if len(tickets) > 1:
                text += f" · 共 {len(tickets)} 项"
            self.export_chip.set_value(text, "running")
        elif getattr(self, "_export_summary", None) is not None:
            role, text = self._export_summary
            self.export_chip.set_value(text, role)
        else:
            self.export_chip.set_value("空闲", "neutral")

        # -- batch -----------------------------------------------------
        window = getattr(self, "_batch_window", None)
        if getattr(self, "_batch_active", False):
            text = "运行中"
            if window is not None and hasattr(window, "progress_text"):
                text = window.progress_text()
            self.batch_chip.set_value(text, "running")
        elif window is not None and hasattr(window, "last_summary"):
            summary = window.last_summary()
            if summary:
                role, text = summary
                self.batch_chip.set_value(text, role)
            else:
                self.batch_chip.set_value("空闲", "neutral")
        else:
            self.batch_chip.set_value("空闲", "neutral")

    def _refresh_ai_status(self) -> None:
        if self._config_error:
            self.ai_status_var.set("在线配置错误：" + self._config_error)
            return
        self.ai_status_var.set(self.config.status)

    def _set_controls_enabled(self, enabled: bool) -> None:
        if getattr(self, "_batch_active", False):
            # A running batch owns the engine; single-asset exports must not
            # compete with it even if some caller asks to enable them.
            enabled = False
        for button in (self.export_img_btn, self.export_lut_btn):
            button.configure(state="normal" if enabled else "disabled")
        self.export_video_btn.configure(
            state="normal" if enabled and self.state.video is not None else "disabled"
        )

    def _update_intent_count(self, _event=None) -> None:
        if getattr(self, "_ai_placeholder_active", False):
            self.intent_count.configure(text="0/2000")
            return
        text = self.ai_text.get("1.0", "end-1c")
        self.intent_count.configure(text=f"{min(len(text), 2000)}/2000")

    def _update_summary(self) -> None:
        text = summary_from_params(self.state.params)
        if self.state.strength < 0.999:
            text += f"；强度 {self.state.strength * 100:.0f}%"
        if self.state.mode == "external_lut" and self.state.external_lut:
            text += f"；外部 LUT {self.state.external_lut.size}³"
        self.summary_var.set(text[:300])

    def _value_style(self, value: float) -> str:
        """Dim unmodified values, brighten changed ones.

        The number itself stays readable; the colour only answers "did I touch
        this?" so a glance down the stack shows what is still at default.
        """
        return "Value.TLabel" if abs(value) > 1e-6 else "ValueZero.TLabel"

    def _update_hue_swatch(self, key: str, value: float) -> None:
        swatch = self._hue_swatches.get(key)
        if swatch is None:
            return
        try:
            swatch.configure(bg=_hue_color(value))
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # histogram
    # ------------------------------------------------------------------
    def _toggle_histogram(self) -> None:
        if self.hist_var.get():
            self.hist_holder.grid()
            self._hist_size = (-1, -1)
            self._refresh_histogram()
        else:
            self.hist_holder.grid_remove()

    def _invalidate_histogram(self, original: bool = False) -> None:
        if original:
            self._hist_original = None
        self._hist_current = None
        self._hist_size = (-1, -1)

    def _dpi_scale(self) -> float:
        """Pixels per logical unit, used to keep custom-drawn art crisp."""
        try:
            return max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            return 1.0

    def _histogram_geometry(self) -> tuple[int, int]:
        """Use most of the canvas width while retaining a quiet side margin."""
        scale = self._dpi_scale()
        canvas_w = self.canvas.winfo_width()
        if canvas_w <= 1:
            canvas_w = 640
        margin = int(round(HIST_SIDE_MARGIN * scale))
        width = max(1, canvas_w - 2 * margin)
        height = int(round(HIST_HEIGHT * scale))
        return width, height

    def _refresh_histogram(self, force: bool = False) -> None:
        """Recompute the histogram only when the pixels or the strip size change."""
        if not getattr(self, "hist_var", None) or not self.hist_var.get():
            return
        width, height = self._histogram_geometry()
        scale = self._dpi_scale()
        self.hist_holder.configure(height=height + int(round(14 * scale)))

        if self._original_preview is None:
            if not force and self._hist_size == (width, height):
                return
            image = render_histogram(None, None, width, height)
            self._hist_photo = ImageTk.PhotoImage(image)
            self.hist_label.configure(image=self._hist_photo)
            self._hist_size = (width, height)
            return

        if self._hist_original is None:
            self._hist_original = compute_histogram(self._original_preview)
        if self._hist_current is None:
            current_image = self._processed_preview or self._original_preview
            self._hist_current = compute_histogram(current_image)

        if (
            not force
            and self._hist_size == (width, height)
            and self._hist_photo is not None
        ):
            return
        image = render_histogram(
            self._hist_current, self._hist_original, width, height
        )
        self._hist_photo = ImageTk.PhotoImage(image)
        self.hist_label.configure(image=self._hist_photo)
        self._hist_size = (width, height)

    def _sync_sliders_from_state(self) -> None:
        self._syncing_sliders = True
        try:
            for key in PARAM_KEYS:
                value = float(getattr(self.state.params, key))
                self._param_vars[key].set(value)
                self._param_value_labels[key].configure(
                    text=_format_param(key, value),
                    style=self._value_style(value),
                )
                self._update_hue_swatch(key, value)
            self.strength_var.set(self.state.strength)
            self.strength_label.configure(
                text=f"{self.state.strength * 100:.0f}%"
            )
            self.split_var.set(self.state.split_t)
            enabled = self.state.mode == "params"
            for scale in self.param_scales:
                scale.state(["!disabled"] if enabled else ["disabled"])
            self.back_to_params_btn.configure(
                state="normal"
            )
            if self.state.mode == "external_lut":
                self.back_to_params_btn.pack(side="left", padx=(self.theme.px(6), 0))
            else:
                self.back_to_params_btn.pack_forget()
            if self.state.mode == "external_lut" and self.state.external_lut:
                self.mode_var.set(f"外部 LUT · {self.state.external_lut.summary()}")
            else:
                self.mode_var.set("参数模式")
        finally:
            self._syncing_sliders = False
        self._update_summary()

    # ------------------------------------------------------------------
    # image loading
    # ------------------------------------------------------------------
    def open_image(self) -> None:
        path = filedialog.askopenfilename(
            title="打开图片或视频",
            filetypes=[
                (
                    "图片与视频",
                    "*.jpg *.jpeg *.jpe *.png *.webp *.bmp *.tif *.tiff "
                    "*.gif *.heic *.heif *.avif "
                    "*.mp4 *.mov *.m4v *.mkv *.webm *.avi *.wmv *.mts *.m2ts",
                ),
                (
                    "图片",
                    "*.jpg *.jpeg *.jpe *.png *.webp *.bmp *.tif *.tiff "
                    "*.gif *.heic *.heif *.avif",
                ),
                (
                    "视频",
                    "*.mp4 *.mov *.m4v *.mkv *.webm *.avi *.wmv *.mts *.m2ts",
                ),
                ("所有文件", "*.*"),
            ],
        )
        if not path:
            return
        self.load_path(Path(path))

    def load_path(self, path: Path) -> None:
        if self._closing:
            return
        if getattr(self, "_batch_active", False):
            self._set_message("批处理进行中，暂时无法切换素材", error=True)
            return
        if self.pipeline is None:
            self._set_message(
                "渲染引擎不可用：" + self._worker_detail, error=True
            )
            return
        # Gated before any decoding and before the document is replaced: the
        # check has to happen while the current document is still intact, and a
        # rejected switch must not cost a decode of the new file either.
        blocked = self._export_block_reason() if self.state.source is not None else None
        if blocked is not None:
            self._set_message(blocked, error=True)
            messagebox.showwarning("暂不能切换素材", blocked)
            return
        if path.suffix.lower() in video_io.VIDEO_SUFFIXES:
            self._load_video(path)
            return
        self._set_busy("正在载入图像…")
        self.root.update_idletasks()
        started = time.monotonic()
        try:
            source = image_io.load_source_image(path)
            preview, scaled, _ = self.pipeline.prepare_preview(source)
        except (ImageError, OSError, ValueError) as exc:
            self._refresh_busy()
            detail = _describe_error(exc)
            hint = "。请确认文件未损坏、格式受支持，并且没有被其他程序占用。"
            self._set_message("无法打开图像：" + detail + hint, error=True)
            messagebox.showerror("无法打开图像", detail + hint)
            return
        self._commit_source(source, preview, scaled, started=started)

    def _commit_source(
        self,
        source: image_io.SourceImage,
        preview: Image.Image,
        scaled: bool,
        *,
        started: float,
        title_name: str | None = None,
    ) -> None:
        """Install a freshly loaded still (or extracted video frame)."""
        self._stop_video_playback()
        if self._debounce_id is not None:
            self.root.after_cancel(self._debounce_id)
            self._debounce_id = None

        self.state.new_document(source)
        self.session.reset_color_history()
        self.state.preview_image = preview
        self.state.preview_is_scaled = scaled
        if self.state.video is None:
            self.video_bar.grid_remove()
        self._original_preview = preview
        self._processed_preview = preview.copy()
        self._invalidate_histogram(original=True)
        self._last_render_ms = None
        self._preview_error = None
        self._pending_proposal = None
        self._sync_pending_proposal_button()
        self.ab_var.set(False)
        self._sync_sliders_from_state()
        self._set_controls_enabled(True)
        name = title_name or source.path.name
        self.root.title(f"AI 调色 · {name}")
        self._update_material_chip()
        self._update_source_info()
        notes = "；".join(source.notes)
        info = (
            f"已载入 {source.width}×{source.height}"
            f"{' · 缩放预览 ' + str(preview.width) + '×' + str(preview.height) if scaled else ''}"
            f" · {source.icc_action}"
            f" · {(time.monotonic() - started) * 1000:.0f} ms"
        )
        if notes:
            info += " · " + notes
        self._set_message(info)
        self._refresh_busy()
        self._redraw()
        self._start_preview(immediate=True)

    # ------------------------------------------------------------------
    # video
    # ------------------------------------------------------------------
    def _load_video(self, path: Path) -> None:
        available, detail = video_io.availability()
        if not available:
            self._set_message(detail, error=True)
            messagebox.showerror("视频功能不可用", detail)
            return
        self._set_busy("正在读取视频信息…")
        self.root.update_idletasks()
        try:
            info = video_io.probe(path)
        except video_io.VideoError as exc:
            self._refresh_busy()
            detail = _describe_error(exc)
            hint = "。请确认视频未损坏，且随附的 ffmpeg 可用（设置里可检查工具路径）。"
            self._set_message("无法打开视频：" + detail + hint, error=True)
            messagebox.showerror("无法打开视频", detail + hint)
            return
        # The first frame of a clip is often black, so start slightly in.
        start = min(2.0, info.duration_s * 0.05)
        try:
            self._install_video_frame(info, start, initial=True)
        except (video_io.VideoError, ImageError, OSError, ValueError) as exc:
            self._refresh_busy()
            detail = _describe_error(exc)
            hint = "。可尝试拖动时间轴换一帧，或确认视频编码受支持。"
            self._set_message("无法打开视频：" + detail + hint, error=True)
            messagebox.showerror("无法打开视频", detail + hint)

    def _video_digest(self, path: Path) -> str:
        try:
            key = (path, path.stat().st_mtime_ns)
        except OSError:
            key = (path, 0)
        digest = self._video_digests.get(key)
        if digest is None:
            digest = video_io.quick_fingerprint(path)
            self._video_digests[key] = digest
        return digest

    def _extract_video_frame(self, info: video_io.VideoInfo, time_s: float) -> Path:
        target = paths.VIDEO_CACHE / video_io.frame_cache_path(
            self._video_digest(info.path), time_s, video_io.MAX_FRAME_SIDE
        )
        if target.is_file() and target.stat().st_size > 0:
            return target
        return video_io.extract_frame(info.path, time_s, target, info=info)

    def _install_video_frame(
        self, info: video_io.VideoInfo, time_s: float, *, initial: bool
    ) -> None:
        """Show one decoded frame; keep the grade when only the time changes."""
        started = time.monotonic()
        frame_path = self._extract_video_frame(info, time_s)
        source = image_io.load_source_image(frame_path)
        source.notes.append(
            f"视频 {info.path.name} 的 {info.timecode(time_s)} 帧"
        )
        preview, scaled, _ = self.pipeline.prepare_preview(source)

        same_clip = self.state.video is not None and self.state.video.path == info.path
        if initial or not same_clip:
            self._commit_source(
                source,
                preview,
                scaled,
                started=started,
                title_name=f"{info.path.name} · {info.timecode(time_s)}",
            )
            self.state.video = info
            self.state.video_time = time_s
            self.video_bar.grid()
            self.video_play_btn.configure(state="normal", text="播放")
            self.video_scale.configure(to=max(1.0, info.duration_s * 1000.0))
            self.video_scale.set(time_s * 1000.0)
            self.export_video_btn.configure(state="normal")
            self.video_hint.configure(
                text=(
                    f"拖动取帧调色 · {info.display_width}×{info.display_height} · "
                    f"{info.fps:.2f} fps · {info.codec}"
                    + (" · 含音频" if info.has_audio else " · 无音频")
                )
            )
        else:
            self.state.source = source
            self.state.preview_image = preview
            self.state.preview_is_scaled = scaled
            self.state.video = info
            self.state.video_time = time_s
            self.state.bump_color()
            self._original_preview = preview
            self._processed_preview = preview.copy()
            self._invalidate_histogram(original=True)
            self.root.title(f"AI 调色 · {info.path.name} · {info.timecode(time_s)}")
            self._update_material_chip()
            self._update_source_info()
            self._preview_message(
                f"视频帧 {info.timecode(time_s)} · {source.width}×{source.height}"
                f" · {(time.monotonic() - started) * 1000:.0f} ms"
            )
            self._redraw()
            self._start_preview(immediate=True)
        self._update_video_time_label()

    def _update_video_time_label(self) -> None:
        info = self.state.video
        if info is None:
            return
        current = min(max(self.video_scale.get() / 1000.0, 0.0), info.duration_s)
        self.video_time_label.configure(
            text=f"{info.timecode(current)} / {info.timecode(info.duration_s)}"
        )

    def _on_video_scale(self, _value=None) -> None:
        self._update_video_time_label()
        if self._video_playing:
            return
        if self._video_seek_id is not None:
            self.root.after_cancel(self._video_seek_id)
        self._video_seek_id = self.root.after(220, self._seek_video_now)

    def _on_video_release(self, _event=None) -> None:
        self._stop_video_playback()
        if self._video_seek_id is not None:
            self.root.after_cancel(self._video_seek_id)
            self._video_seek_id = None
        self._seek_video_now()

    def _nudge_video(self, delta: float) -> None:
        self._stop_video_playback()
        info = self.state.video
        if info is None:
            return
        target = min(max(self.state.video_time + delta, 0.0), info.duration_s)
        self.video_scale.set(target * 1000.0)
        self._on_video_release()

    def _seek_video_now(self) -> None:
        self._video_seek_id = None
        info = self.state.video
        if info is None or self.pipeline is None:
            return
        target = min(
            max(self.video_scale.get() / 1000.0, 0.0), info.duration_s
        )
        if not self._video_playing and abs(target - self.state.video_time) < 0.04:
            return
        self._video_frame_token += 1
        token = self._video_frame_token
        self._set_message(f"正在取帧 {info.timecode(target)}…")
        threading.Thread(
            target=self._video_seek_worker,
            args=(token, info, target),
            name="video-seek",
            daemon=True,
        ).start()

    def _video_seek_worker(
        self, token: int, info: video_io.VideoInfo, time_s: float
    ) -> None:
        frame: Path | None = None
        error: BaseException | None = None
        try:
            frame = self._extract_video_frame(info, time_s)
        except BaseException as exc:  # reported on the UI thread
            error = exc
        # Tk objects are main-thread only (``after`` from a worker thread is
        # rejected), so hand the result to the poller instead.
        self._video_results.put((token, info, time_s, frame, error))

    def _drain_video_results(self) -> None:
        while True:
            try:
                item = self._video_results.get_nowait()
            except queue.Empty:
                return
            self._video_frame_ready(*item)

    def _video_frame_ready(
        self,
        token: int,
        info: video_io.VideoInfo,
        time_s: float,
        frame: Path | None,
        error: BaseException | None,
    ) -> None:
        if self._closing or token != self._video_frame_token:
            return
        if error is not None or frame is None:
            self._stop_video_playback()
            self._set_message("取帧失败：" + _describe_error(error), error=True)
            return
        if self.state.video is None or self.state.video.path != info.path:
            return
        try:
            source = image_io.load_source_image(frame)
            preview, scaled, _ = self.pipeline.prepare_preview(source)
        except (ImageError, OSError, ValueError) as exc:
            self._set_message("无法读取视频帧：" + _describe_error(exc), error=True)
            return
        source.notes.append(f"视频 {info.path.name} 的 {info.timecode(time_s)} 帧")
        self.state.source = source
        self.state.preview_image = preview
        self.state.preview_is_scaled = scaled
        self.state.video_time = time_s
        self.state.bump_color()
        self._original_preview = preview
        self._processed_preview = preview.copy()
        self._invalidate_histogram(original=True)
        self.root.title(f"AI 调色 · {info.path.name} · {info.timecode(time_s)}")
        self._update_material_chip()
        self._update_source_info()
        self._preview_message(
            f"视频帧 {info.timecode(time_s)} · {source.width}×{source.height}"
        )
        self._update_video_time_label()
        self._redraw()
        self._start_preview(immediate=True)

        if self._video_playing:
            self._schedule_video_playback()

    def _toggle_video_playback(self) -> None:
        """Toggle lightweight, frame-by-frame video preview playback."""
        if self.state.video is None:
            return
        self._set_video_playing(not self._video_playing)

    def _set_video_playing(self, playing: bool) -> None:
        if playing and self.state.video is None:
            playing = False
        if not playing:
            self._video_playing = False
            if self._video_play_id is not None:
                try:
                    self.root.after_cancel(self._video_play_id)
                except tk.TclError:
                    pass
                self._video_play_id = None
            if hasattr(self, "video_play_btn"):
                self.video_play_btn.configure(text="播放")
            return
        self._video_playing = True
        self.video_play_btn.configure(text="暂停")
        self._schedule_video_playback(delay_ms=0)

    def _stop_video_playback(self) -> None:
        self._set_video_playing(False)

    def _schedule_video_playback(self, *, delay_ms: int | None = None) -> None:
        if not self._video_playing or self.state.video is None or self._closing:
            return
        if self._video_play_id is not None:
            try:
                self.root.after_cancel(self._video_play_id)
            except tk.TclError:
                pass
        if delay_ms is None:
            fps = max(float(self.state.video.fps or 1.0), 1.0)
            delay_ms = max(30, int(round(1000.0 / fps)))
        self._video_play_id = self.root.after(delay_ms, self._advance_video_playback)

    def _advance_video_playback(self) -> None:
        self._video_play_id = None
        if not self._video_playing or self.state.video is None:
            return
        info = self.state.video
        step = 1.0 / max(float(info.fps or 1.0), 1.0)
        current = min(max(float(self.state.video_time), 0.0), info.duration_s)
        target = min(current + step, info.duration_s)
        if target <= current + 0.001:
            self._set_video_playing(False)
            self._set_message("播放结束")
            return
        self.video_scale.set(target * 1000.0)
        self._seek_video_now()

    # ------------------------------------------------------------------
    # preview
    # ------------------------------------------------------------------
    def _schedule_preview(self) -> None:
        if self.state.source is None:
            self._update_summary()
            return
        if getattr(self, "_batch_active", False):
            # A batch owns the engine; queuing previews now would either starve
            # the batch or run two heavy renders at once on a single GPU.
            self.busy_var.set("批处理进行中…")
            return
        if self._debounce_id is not None:
            self.root.after_cancel(self._debounce_id)
        self._debounce_id = self.root.after(
            PREVIEW_DEBOUNCE_MS, self._start_preview
        )

    def _start_preview(self, immediate: bool = False) -> None:
        if self._closing or self.state.source is None or self.state.preview_image is None:
            return
        if self._debounce_id is not None:
            self.root.after_cancel(self._debounce_id)
            self._debounce_id = None
        if not self._worker_ok or self.pipeline is None:
            self._set_message(
                "渲染引擎不可用：" + self._worker_detail, error=True
            )
            return
        try:
            snapshot = RenderSnapshot.from_state(self.state)
        except ValueError as exc:
            self._set_message(str(exc), error=True)
            return
        revision = snapshot.revision
        self.state.busy_revision = revision
        self._refresh_busy()
        self._redraw()
        self.runner.submit(
            "preview",
            lambda cancel: self.pipeline.render_preview(snapshot, cancel),
            coalesce_key="preview",
            revision=revision,
            coalesce=True,
        )

    def _handle_preview(self, outcome: JobOutcome) -> None:
        if outcome.cancelled:
            return
        revision = outcome.revision
        if outcome.error is not None:
            if revision == self.state.revision:
                self.state.busy_revision = None
                self._preview_error = _describe_error(outcome.error)
                self._refresh_busy()
                self._set_message(
                    f"渲染失败（rev {revision}）：{self._preview_error}"
                    "。画面仍是上一次成功结果；可撤销本次修改或重试。",
                    error=True,
                )
                self._redraw()
            return
        result: PreviewResult = outcome.value
        if (
            result.document_id != self.state.document_id
            or result.revision != self.state.revision
        ):
            return  # stale: a newer edit owns the display
        self._processed_preview = result.image
        self._preview_error = None
        self._invalidate_histogram()
        self.state.last_completed_revision = result.revision
        self.state.busy_revision = None
        self._last_render_ms = result.elapsed_ms
        self._refresh_busy()
        engine_ms = result.metrics.get("render_readback_ms")
        detail = f"预览已更新 rev {result.revision} · {result.elapsed_ms:.0f} ms"
        if isinstance(engine_ms, (int, float)):
            detail += f"（GPU 读写回 {engine_ms:.1f} ms）"
        self._preview_message(detail)
        self._redraw()

    # ------------------------------------------------------------------
    # sliders and presets
    # ------------------------------------------------------------------
    def _on_param_slider(self, key: str, raw: str) -> None:
        if self._syncing_sliders:
            return
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return
        value = round(value, 2) if key == "exposure_ev" else float(round(value))
        value = max(PARAM_RANGES[key][0], min(PARAM_RANGES[key][1], value))
        self._param_value_labels[key].configure(
            text=_format_param(key, value),
            style=self._value_style(value),
        )
        self._update_hue_swatch(key, value)
        new_params = self.state.params.with_updates(**{key: value})
        if new_params == self.state.params:
            return
        self.session.record_color_history()
        self.state.params = new_params
        self.state.mode = "params"
        self.state.external_lut = None
        self.state.source_label = "手动"
        self.state.dirty = True
        self.state.bump_color()
        self._update_summary()
        self._redraw()
        self._schedule_preview()

    def _on_strength_slider(self, raw: str) -> None:
        if self._syncing_sliders:
            return
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return
        value = max(0.0, min(1.0, round(value, 2)))
        self.strength_label.configure(text=f"{value * 100:.0f}%")
        if abs(value - self.state.strength) < 1e-9:
            return
        self.session.record_color_history()
        self.state.strength = value
        self.state.dirty = True
        self.state.bump_color()
        self._update_summary()
        self._schedule_preview()

    def apply_preset(self, name: str) -> None:
        from baker.params import load_preset

        try:
            params, _ = load_preset(name)
        except Exception as exc:
            self._set_message("预设读取失败：" + _describe_error(exc), error=True)
            return
        self.session.record_color_history()
        self.state.params = params
        self.state.mode = "params"
        self.state.external_lut = None
        self.state.source_label = f"预设 · {name}"
        self.state.dirty = True
        self.state.bump_color()
        self.session.record_color_history()
        self._sync_sliders_from_state()
        if self.state.source is None:
            self._set_message("已选择预设；打开图片后生效")
            return
        self._schedule_preview()

    # ------------------------------------------------------------------
    # AI
    # ------------------------------------------------------------------
    def submit_ai(self) -> None:
        intent = (
            ""
            if self._ai_placeholder_active
            else self.ai_text.get("1.0", "end-1c").strip()
        )
        if not intent:
            self._set_message("请先输入调色描述", error=True)
            return
        if len(intent) > 2000:
            intent = intent[:2000]
            self._set_message("描述已截断为 2000 字符")
        self._ai_busy = True
        self._refresh_busy()
        self._ai_request_seq += 1
        request_seq = self._ai_request_seq
        revision = self.state.revision
        document = self.state.document_id
        current = self.state.params

        try:
            provider = build_provider(self.config)
        except AIError as exc:
            self._ai_busy = False
            self._refresh_busy()
            self._offer_offline(intent, current, revision, document, exc)
            return

        self.ai_runner.submit(
            "ai",
            lambda cancel: provider.generate(intent, current, cancel),
            coalesce_key="ai",
            revision=revision,
            token=request_seq,
        )
        self._ai_document = document
        self._ai_seq = request_seq
        self._ai_intent = intent
        self._ai_current = current

    def cancel_ai(self) -> None:
        self.ai_runner.cancel("ai")
        self._set_message("已请求取消 AI 任务")
        self._refresh_busy()
    def _handle_ai(self, outcome: JobOutcome) -> None:
        if outcome.token is not None and outcome.token != self._ai_request_seq:
            # A newer request replaced this one; it owns the busy line and will
            # report its own result. Showing "cancelled" here would be noise.
            return
        if outcome.cancelled:
            self._ai_busy = False
            self._refresh_busy()
            self._set_message("AI 请求已取消")
            return
        self._ai_busy = False
        self._refresh_busy()
        if outcome.error is not None:
            exc = outcome.error
            if isinstance(exc, AIError):
                self._set_message("AI 失败：" + _describe_error(exc), error=True)
                self._offer_offline(
                    getattr(self, "_ai_intent", ""),
                    getattr(self, "_ai_current", self.state.params),
                    outcome.revision or self.state.revision,
                    getattr(self, "_ai_document", self.state.document_id),
                    exc,
                )
            else:
                self._set_message(
                    "AI 失败：" + _describe_error(exc), error=True
                )
            return
        proposal: Proposal = outcome.value
        if (
            outcome.revision == self.state.revision
            and getattr(self, "_ai_document", self.state.document_id)
            == self.state.document_id
        ):
            self._apply_proposal(proposal)
        else:
            self._pending_proposal = proposal
            self._sync_pending_proposal_button()
            self._set_message(
                "AI 结果返回较晚，参数已改动；结果作为提案保留，未自动覆盖"
            )

    def _offer_offline(
        self,
        intent: str,
        current: ColorParams,
        revision: int,
        document: str,
        exc: BaseException,
    ) -> None:
        if not intent:
            return
        answer = messagebox.askyesno(
            "在线请求失败",
            _describe_error(exc) + "\n\n是否改用离线模板？（来源会标记为离线）",
        )
        if not answer:
            return
        try:
            proposal = OfflineProvider().generate(intent, current)
        except Exception as offline_exc:
            self._set_message(
                "离线模板失败：" + _describe_error(offline_exc), error=True
            )
            return
        self._apply_proposal(proposal)

    def _apply_proposal(self, proposal: Proposal) -> None:
        if proposal.source == "ai":
            label = f"AI · {proposal.provider}/{proposal.model}"
        else:
            label = "离线模板"
        self.session.apply_proposal_to_state(proposal)
        self._sync_pending_proposal_button()
        self._sync_sliders_from_state()
        self._set_message(f"{label} · {proposal.summary}")
        if self.state.source is not None:
            self._start_preview(immediate=True)
        else:
            self._set_message(
                "已生成参数；打开图片后会按规格重置为 identity，请重新应用"
            )

    def apply_pending_proposal(self) -> None:
        if self._pending_proposal is None:
            return
        self._apply_proposal(self._pending_proposal)

    def _sync_pending_proposal_button(self) -> None:
        if not hasattr(self, "apply_proposal_btn"):
            return
        if self._pending_proposal is not None:
            if not self.apply_proposal_btn.winfo_manager():
                self.apply_proposal_btn.pack(side="left")
        else:
            self.apply_proposal_btn.pack_forget()

    # ------------------------------------------------------------------
    # LUT import and modes
    # ------------------------------------------------------------------
    def import_lut(self) -> None:
        path = filedialog.askopenfilename(
            title="导入 3D LUT",
            filetypes=[("Cube LUT", "*.cube"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self._set_busy("正在读取 LUT…")
        self.root.update_idletasks()
        try:
            lut = load_cube(Path(path))
            lut = self.pipeline.copy_external_lut(lut)
        except (CubeError, OSError) as exc:
            self._refresh_busy()
            self._set_message("LUT 导入失败：" + _describe_error(exc), error=True)
            messagebox.showerror("LUT 导入失败", _describe_error(exc))
            return
        self._refresh_busy()
        answer = messagebox.askyesno(
            "确认 LUT 颜色空间",
            "本应用会按 sRGB 解释该 LUT 的输入与输出。\n"
            "Log/相机 Log LUT 不会被自动识别。\n\n继续导入？",
        )
        if not answer:
            return
        self.state.import_external_lut(lut)
        self._sync_sliders_from_state()
        self._set_message(
            f"已导入外部 LUT：{lut.summary()}（按 sRGB 解释）"
        )
        if self.state.source is not None:
            self._schedule_preview()

    def return_to_params(self) -> None:
        self.state.return_to_params()
        self._sync_sliders_from_state()
        self._set_message("已回到参数调色")
        if self.state.source is not None:
            self._schedule_preview()

    # ------------------------------------------------------------------
    # export
    # ------------------------------------------------------------------
    def _material_name(self) -> str:
        """Human-facing source name for export notices (never a full path)."""
        video = self.state.video
        if video is not None:
            return video.path.name
        source = self.state.source
        return source.path.name if source is not None else ""

    def _update_material_chip(self) -> None:
        """Show the current material in the toolbar without letting it grow.

        The full path lives in a tooltip; the visible label is middle-elided so
        a long Chinese file name cannot push the export buttons off the toolbar.
        """
        if not hasattr(self, "material_label"):
            return
        path = None
        if self.state.video is not None:
            path = self.state.video.path
        elif self.state.source is not None:
            path = self.state.source.path
        if path is None:
            self.material_label.configure(text="未打开素材")
            tip = getattr(self, "material_tip", None)
            if tip is not None:
                tip.set_text("尚未打开素材")
            return
        self.material_label.configure(
            text="素材 · " + shorten_middle(path.name, 34)
        )
        tip = getattr(self, "material_tip", None)
        if tip is not None:
            tip.set_text(str(path))

    def _update_source_info(self) -> None:
        """One-line material readout in the sidebar (name, size, colour state)."""
        if not hasattr(self, "source_info_var"):
            return
        source = self.state.source
        if source is None:
            self.source_info_var.set(
                "未打开素材。打开图片或视频后可在此查看尺寸、色彩与耗时。"
            )
            return
        parts = [
            shorten_middle(source.path.name, 40),
            f"{source.width}×{source.height}",
            source.icc_action,
        ]
        if self.state.preview_is_scaled:
            parts.append(f"预览长边 {PREVIEW_LONG_SIDE}")
        video = self.state.video
        if video is not None:
            parts.append(f"时长 {video.duration_s:.1f}s")
        self.source_info_var.set(" · ".join(p for p in parts if p))

    def _submit_export(self, token: int, tag: str, fn, revision: int) -> None:
        """Submit a must-run export, dropping its ticket if submission fails.

        A leaked ticket would make ``_export_block_reason`` refuse material
        switches forever, which is worse than the submission error itself.
        """
        try:
            self.runner.submit(
                tag,
                fn,
                coalesce_key=tag,
                revision=revision,
                coalesce=False,
                token=token,
            )
        except Exception as exc:
            self._ensure_session().export_drop_token(token)
            self._refresh_busy()
            LOGGER.exception("export submit failed")
            self._set_message("导出任务提交失败：" + _describe_error(exc), error=True)

    def export_image(self) -> None:
        if getattr(self, "_batch_active", False):
            self._set_message("批处理进行中，已暂停单素材导出", error=True)
            return
        if self.state.source is None or self.state.preview_image is None:
            self._set_message("请先打开图片", error=True)
            return
        if not self._worker_ok:
            self._set_message("渲染引擎不可用，无法导出", error=True)
            return
        video = self.state.video
        if video is not None:
            base_dir = video.path.parent
            stamp = (
                video.timecode(self.state.video_time)
                .replace(":", "-")
                .replace(".", "_")
            )
            default_name = f"{video.path.stem}_{stamp}.png"
        else:
            base_dir = self.state.source.path.parent
            default_name = image_io.default_export_path(
                self.state.source.path, ".png"
            ).name
        path = filedialog.asksaveasfilename(
            title="导出图片",
            defaultextension=".png",
            initialdir=str(base_dir),
            initialfile=default_name,
            filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg *.jpeg")],
        )
        if not path:
            return
        target = Path(path)
        suffix = target.suffix.lower()
        fmt = "PNG" if suffix == ".png" else "JPEG"
        if suffix not in (".png", ".jpg", ".jpeg"):
            fmt = "PNG"
            target = target.with_suffix(".png")
        if image_io.is_same_file(target, self.state.source.path) or (
            video is not None and image_io.is_same_file(target, video.path)
        ):
            self._set_message("拒绝覆盖源文件", error=True)
            return
        if fmt == "JPEG" and self.state.source.had_alpha:
            if not messagebox.askyesno(
                "JPEG 不支持透明",
                "源图带透明通道。导出 JPEG 时会按编码 sRGB 白底合成，"
                "并移除 alpha。\n\n继续导出？",
            ):
                return
        try:
            snapshot = RenderSnapshot.from_state(self.state)
        except ValueError as exc:
            self._set_message(str(exc), error=True)
            return
        token = self._export_started("图片", snapshot.revision, self._material_name())
        self._submit_export(
            token,
            "export-image",
            lambda cancel: self.pipeline.export_image(
                snapshot, target, fmt, 95, cancel
            ),
            snapshot.revision,
        )

    def export_video(self) -> None:
        if getattr(self, "_batch_active", False):
            self._set_message("批处理进行中，已暂停单素材导出", error=True)
            return
        info = self.state.video
        if info is None or self.state.source is None:
            self._set_message("请先打开视频", error=True)
            return
        if not self._worker_ok or self.pipeline is None:
            self._set_message("渲染引擎不可用，无法导出视频", error=True)
            return
        available, detail = video_io.availability()
        if not available:
            self._set_message(detail, error=True)
            messagebox.showerror("视频功能不可用", detail)
            return
        default = f"{info.path.stem}_graded.mp4"
        path = filedialog.asksaveasfilename(
            title="导出调色视频",
            defaultextension=".mp4",
            initialdir=str(info.path.parent),
            initialfile=default,
            filetypes=[("MP4", "*.mp4"), ("QuickTime", "*.mov")],
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() not in (".mp4", ".mov", ".mkv", ".webm"):
            target = target.with_suffix(".mp4")
        if image_io.is_same_file(target, info.path):
            self._set_message("拒绝覆盖源视频", error=True)
            return
        try:
            snapshot = RenderSnapshot.from_state(self.state)
        except ValueError as exc:
            self._set_message(str(exc), error=True)
            return

        token = self._export_started("视频", snapshot.revision, info.path.name)
        self._video_progress = 0.0
        self._start_video_progress_poll()
        LOGGER.info("video export start: %s -> %s", info.path, target)
        self._submit_export(
            token,
            "export-video",
            lambda cancel: self._run_video_export(snapshot, info, target, cancel),
            snapshot.revision,
        )

    def _run_video_export(
        self,
        snapshot: RenderSnapshot,
        info: video_io.VideoInfo,
        target: Path,
        cancel: threading.Event,
    ) -> ExportResult:
        """Bake the current look to a .cube, then encode the clip through it."""
        cube = paths.VIDEO_CACHE / f"export-{snapshot.revision}-{time.monotonic_ns()}.cube"
        try:
            self.pipeline.export_lut(snapshot, cube, cancel)
            out = video_io.export_graded(
                info.path,
                cube,
                target,
                info=info,
                on_progress=self._set_video_progress,
                cancel_event=cancel,
            )
            size_mb = out.stat().st_size / (1024 * 1024)
            return ExportResult(
                path=out,
                width=info.display_width,
                height=info.display_height,
                revision=snapshot.revision,
                detail=(
                    f"{info.duration_s:.2f} s · {info.fps:.2f} fps · "
                    f"{size_mb:.1f} MB · H.264"
                ),
            )
        finally:
            cube.unlink(missing_ok=True)
            self._video_progress = None

    def _set_video_progress(self, value: float) -> None:
        # Called from the worker thread: plain assignment is enough, the UI
        # polls it instead of touching Tk cross-thread.
        self._video_progress = max(0.0, min(1.0, float(value)))

    def _start_video_progress_poll(self) -> None:
        if self._video_poll_id is None:
            self._video_poll_id = self.root.after(250, self._poll_video_progress)

    def _poll_video_progress(self) -> None:
        self._video_poll_id = None
        if self._closing:
            return
        self._refresh_busy()
        if self._video_progress is not None:
            self._start_video_progress_poll()

    def export_lut(self) -> None:
        if getattr(self, "_batch_active", False):
            self._set_message("批处理进行中，已暂停单素材导出", error=True)
            return
        if self.state.source is None or self.state.preview_image is None:
            self._set_message("请先打开图片", error=True)
            return
        default = image_io.default_export_path(self.state.source.path, ".cube")
        path = filedialog.asksaveasfilename(
            title="导出 3D LUT",
            defaultextension=".cube",
            initialdir=str(self.state.source.path.parent),
            initialfile=default.name,
            filetypes=[("Cube LUT", "*.cube")],
        )
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() != ".cube":
            target = target.with_suffix(".cube")
        try:
            snapshot = RenderSnapshot.from_state(self.state)
        except ValueError as exc:
            self._set_message(str(exc), error=True)
            return
        token = self._export_started("LUT", snapshot.revision, self._material_name())
        self._submit_export(
            token,
            "export-lut",
            lambda cancel: self.pipeline.export_lut(snapshot, target, cancel),
            snapshot.revision,
        )

    # ------------------------------------------------------------------
    # display interaction
    # ------------------------------------------------------------------
    def _fit_scale(self) -> float:
        if self._original_preview is None:
            return 1.0
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        iw, ih = self._original_preview.size
        scale = min((width - 24) / iw, (height - 24) / ih)
        return max(0.01, min(scale, 1.0))

    def _display_geometry(self) -> tuple[float, float, float, float, float] | None:
        if self._original_preview is None:
            return None
        scale = self._fit_scale() if self.state.zoom <= 0.0 else self.state.zoom
        iw, ih = self._original_preview.size
        disp_w = max(1.0, iw * scale)
        disp_h = max(1.0, ih * scale)
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        cx = cw / 2.0 + self.state.pan_x
        cy = ch / 2.0 + self.state.pan_y
        return disp_w, disp_h, cx, cy, scale

    def _composite_preview(self) -> Image.Image | None:
        if self._original_preview is None:
            return None
        if self.state.hold_original or self._processed_preview is None:
            return self._original_preview
        if not self.state.show_split:
            return self._processed_preview
        width, height = self._original_preview.size
        split = int(round(self.state.split_t * width))
        split = max(0, min(width, split))
        if split >= width:
            return self._processed_preview
        base = self._processed_preview.copy()
        base.paste(self._original_preview.crop((split, 0, width, height)), (split, 0))
        return base

    def _checker(self, width: int, height: int) -> Image.Image:
        key = (width, height)
        cached = self._checker_cache.get(key)
        if cached is not None:
            return cached
        yy, xx = np.indices((height, width))
        tile = ((xx // 12) + (yy // 12)) % 2
        arr = np.empty((height, width, 3), dtype=np.uint8)
        arr[tile == 0] = (58, 58, 62)
        arr[tile == 1] = (82, 82, 88)
        image = Image.fromarray(arr, "RGB")
        if len(self._checker_cache) > 8:
            self._checker_cache.clear()
        self._checker_cache[key] = image
        return image

    def _redraw(self) -> None:
        self.canvas.delete("all")
        self._refresh_histogram()
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        t = getattr(self, "theme", None)
        family = t.font_family if t is not None else "Microsoft YaHei UI"
        if self._original_preview is None:
            # Two weights instead of one block of text: a headline the eye can
            # find, and a quiet hint underneath.
            self.canvas.create_text(
                width / 2,
                height / 2 - (t.px(16) if t else 16),
                text="打开素材开始调色",
                fill=CANVAS_TEXT,
                font=(family, 15, "bold"),
                justify="center",
            )
            self.canvas.create_text(
                width / 2,
                height / 2 + (t.px(14) if t else 14),
                text="支持单帧 JPEG / PNG 与常见视频\n预览是视觉中心，界面颜色只用于状态提示",
                fill=_PALETTE.text_muted,
                font=(family, 9),
                justify="center",
            )
            self._display_geom = None
            return

        geometry = self._display_geometry()
        if geometry is None:
            return
        disp_w, disp_h, cx, cy, scale = geometry
        self._display_geom = geometry
        base = self._composite_preview()
        if base is None:
            return
        resample = Image.Resampling.LANCZOS if scale < 1.0 else Image.Resampling.BICUBIC
        resized = base.resize(
            (max(1, int(round(disp_w))), max(1, int(round(disp_h)))), resample
        )
        arr = np.asarray(resized, dtype=np.float32)
        if self.state.source is not None and self.state.source.had_alpha:
            alpha = arr[..., 3:4] / 255.0
            background = np.asarray(
                self._checker(resized.width, resized.height), dtype=np.float32
            )
            rgb = background * (1.0 - alpha) + arr[..., :3] * alpha
            display = Image.fromarray(
                np.clip(np.rint(rgb), 0, 255).astype(np.uint8), "RGB"
            )
        else:
            display = resized.convert("RGB")

        self._display_photo = ImageTk.PhotoImage(display)
        x0 = int(round(cx - disp_w / 2.0))
        y0 = int(round(cy - disp_h / 2.0))
        self.canvas.create_image(x0, y0, image=self._display_photo, anchor="nw")

        if self.state.show_split:
            split_x = x0 + disp_w * self.state.split_t
            self.canvas.create_line(
                split_x, y0, split_x, y0 + disp_h, fill=_PALETTE.warn, width=2
            )
            self.canvas.create_rectangle(
                split_x - 3, cy - 12, split_x + 3, cy + 12,
                fill=_PALETTE.warn, outline="",
            )

        status = (
            f"{self._original_preview.width}×{self._original_preview.height}"
            f" · {scale * 100:.0f}%"
        )
        if self.state.preview_is_scaled:
            status += f" · 缩放预览 {PREVIEW_LONG_SIDE} 长边"
        if self.state.last_completed_revision != self.state.revision:
            status += " · 尚未更新"
        if self.state.hold_original:
            status += " · 原图"
        elif self.state.show_split:
            status += f" · A/B {self.state.split_t * 100:.0f}%"
        if self._last_render_ms is not None:
            status += f" · {self._last_render_ms:.0f} ms"
        # A dithered plaque keeps the overlay readable over both a night sky and
        # a snow field without covering the picture with a solid bar.
        overlay = self.canvas.create_text(
            12,
            10,
            text=status,
            fill=CANVAS_TEXT,
            anchor="nw",
            font=(family, 9),
        )
        box = self.canvas.bbox(overlay)
        if box:
            plaque = self.canvas.create_rectangle(
                box[0] - 6, box[1] - 3, box[2] + 6, box[3] + 3,
                fill=_PALETTE.canvas_edge, outline="", stipple="gray50",
            )
            self.canvas.tag_lower(plaque, overlay)
        if self._preview_error:
            # Failures are reported next to the picture, not only in the status
            # bar at the far bottom of the window.
            banner = self.canvas.create_text(
                width / 2,
                height - (t.px(18) if t else 18),
                text="预览失败 · " + shorten_middle(self._preview_error, 70),
                fill=_PALETTE.error,
                anchor="s",
                font=(family, 9),
            )
            banner_box = self.canvas.bbox(banner)
            if banner_box:
                backing = self.canvas.create_rectangle(
                    banner_box[0] - 10, banner_box[1] - 6,
                    banner_box[2] + 10, banner_box[3] + 6,
                    fill=_PALETTE.canvas_edge, outline=_PALETTE.error,
                )
                self.canvas.tag_lower(backing, banner)
        self.zoom_label.configure(text=f"{scale * 100:.0f}%")

    # ------------------------------------------------------------------
    # canvas events
    # ------------------------------------------------------------------
    def _on_press(self, event: tk.Event) -> None:
        if self._display_geom is None:
            return
        disp_w, disp_h, cx, cy, _scale = self._display_geom
        x0 = cx - disp_w / 2.0
        if self.state.show_split and abs(event.x - (x0 + disp_w * self.state.split_t)) <= 8:
            self._drag_mode = "split"
            return
        inside = (
            x0 <= event.x <= x0 + disp_w
            and cy - disp_h / 2.0 <= event.y <= cy + disp_h / 2.0
        )
        if inside:
            self._drag_mode = "pan"
            self._drag_start = (event.x, event.y)
            self._drag_pan = (self.state.pan_x, self.state.pan_y)
            self.canvas.configure(cursor="fleur")

    def _on_drag(self, event: tk.Event) -> None:
        if self._display_geom is None:
            return
        disp_w, disp_h, cx, cy, _scale = self._display_geom
        x0 = cx - disp_w / 2.0
        if self._drag_mode == "split":
            self.state.split_t = max(0.0, min(1.0, (event.x - x0) / disp_w))
            self.split_var.set(self.state.split_t)
            self._redraw()
        elif self._drag_mode == "pan":
            dx = event.x - self._drag_start[0]
            dy = event.y - self._drag_start[1]
            self.state.pan_x = self._drag_pan[0] + dx
            self.state.pan_y = self._drag_pan[1] + dy
            self._clamp_pan()
            self._redraw()

    def _on_release(self, _event: tk.Event) -> None:
        self._drag_mode = None
        self.canvas.configure(cursor="crosshair")

    def _clamp_pan(self) -> None:
        if self._display_geom is None:
            return
        disp_w, disp_h, _cx, _cy, _scale = self._display_geom
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        limit_x = max(0.0, disp_w / 2.0 + cw / 2.0 - 40.0)
        limit_y = max(0.0, disp_h / 2.0 + ch / 2.0 - 40.0)
        self.state.pan_x = max(-limit_x, min(limit_x, self.state.pan_x))
        self.state.pan_y = max(-limit_y, min(limit_y, self.state.pan_y))

    def _on_wheel(self, event: tk.Event) -> None:
        if self._display_geom is None:
            return
        delta = 1.0 if event.delta > 0 else -1.0
        disp_w, disp_h, cx, cy, old_scale = self._display_geom
        fit = self._fit_scale()
        new_scale = old_scale * (1.12 ** delta)
        new_scale = max(fit * 0.5, min(new_scale, 8.0))
        image_x = (event.x - cx) / max(old_scale, 1e-6)
        image_y = (event.y - cy) / max(old_scale, 1e-6)
        self.state.zoom = 0.0 if abs(new_scale - fit) < 0.005 else new_scale
        if self.state.zoom == 0.0:
            self.state.pan_x = 0.0
            self.state.pan_y = 0.0
        else:
            cw = max(1, self.canvas.winfo_width())
            ch = max(1, self.canvas.winfo_height())
            self.state.pan_x = event.x - cw / 2.0 - image_x * new_scale
            self.state.pan_y = event.y - ch / 2.0 - image_y * new_scale
            self._clamp_pan()
        self._redraw()

    def _zoom_fit(self) -> None:
        self.state.zoom = 0.0
        self.state.pan_x = 0.0
        self.state.pan_y = 0.0
        self._redraw()

    def _zoom_one(self) -> None:
        if self._original_preview is None:
            return
        self.state.zoom = 1.0
        self.state.pan_x = 0.0
        self.state.pan_y = 0.0
        self._redraw()

    def _toggle_ab(self) -> None:
        self.state.show_split = bool(self.ab_var.get())
        if self.state.show_split and self.state.split_t >= 0.999:
            self.state.split_t = 0.5
            self.split_var.set(0.5)
        self._redraw()

    def _on_split_scale(self, raw: str) -> None:
        if self._syncing_sliders:
            return
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return
        self.state.split_t = max(0.0, min(1.0, value))
        if not self.state.show_split:
            self.state.show_split = True
            self.ab_var.set(True)
        self._redraw()

    def _set_hold(self, held: bool) -> None:
        if self.state.hold_original == held:
            return
        self.state.hold_original = held
        self._redraw()

    def _space_down(self, event: tk.Event) -> None:
        if isinstance(self.root.focus_get(), tk.Text):
            return
        self._set_hold(True)

    def _space_up(self, event: tk.Event) -> None:
        if isinstance(self.root.focus_get(), tk.Text):
            return
        self._set_hold(False)

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def reset_all(self) -> None:
        if self.state.source is None:
            self.state.params = ColorParams.identity()
            self.state.strength = 1.0
            self.state.mode = "params"
            self.state.external_lut = None
            self.state.bump_color()
            self._sync_sliders_from_state()
            self._update_summary()
            self._set_message("已重置参数")
            return
        self.state.params = ColorParams.identity()
        self.state.saved_params = ColorParams.identity()
        self.state.strength = 1.0
        self.state.mode = "params"
        self.state.external_lut = None
        self.state.source_label = "重置"
        self.state.show_split = False
        self.ab_var.set(False)
        self.state.split_t = 1.0
        self.split_var.set(1.0)
        self.state.hold_original = False
        self.state.zoom = 0.0
        self.state.pan_x = 0.0
        self.state.pan_y = 0.0
        self.state.bump_color()
        self._sync_sliders_from_state()
        self._set_message("已重置参数与视图")
        self._redraw()
        self._start_preview(immediate=True)

    def _dispatch_outcome(self, outcome: JobOutcome) -> None:
        if outcome.tag == "preview":
            self._handle_preview(outcome)
        elif outcome.tag == "export-image":
            self._handle_export(outcome, "图片")
        elif outcome.tag == "export-lut":
            self._handle_export(outcome, "LUT")
        elif outcome.tag == "export-video":
            self._handle_export(outcome, "视频")

    def _poll(self) -> None:
        if self._closing:
            return
        self._drain_video_results()
        # One outcome at a time: a handler raising must not swallow the other
        # outcomes in the same drain. They have already been taken off the
        # runner's queue, so dropping one loses its export ticket for good and
        # would leave material switching blocked forever.
        for outcome in self.runner.poll():
            try:
                self._dispatch_outcome(outcome)
            except Exception:
                LOGGER.exception("job poll failed for %s", outcome.tag)
                self._set_message("后台任务处理异常，详见日志", error=True)
        for outcome in self.ai_runner.poll():
            try:
                self._handle_ai(outcome)
            except Exception:
                LOGGER.exception("ai poll failed")
                self._set_message("AI 结果处理异常，详见日志", error=True)
        self.root.after(40, self._poll)

    def _handle_export(self, outcome: JobOutcome, kind: str) -> None:
        # Consume the ticket before anything else: even if formatting the
        # message fails, the material-switch gate must be released.
        ticket = self._export_take(outcome.token, kind)
        material = ticket.material if ticket is not None else ""
        owner = f"（{material}）" if material else ""
        self._video_progress = None
        try:
            if outcome.cancelled:
                self._export_summary = ("warn", f"{kind}已取消")
                self._set_message(f"{kind}导出已取消{owner}", role="warn")
                return
            if outcome.error is not None:
                if getattr(outcome.error, "code", "") == "CANCELLED":
                    self._export_summary = ("warn", f"{kind}已取消")
                    self._set_message(f"{kind}导出已取消{owner}", role="warn")
                    return
                self._export_summary = ("error", f"{kind}失败")
                detail = _describe_error(outcome.error)
                hint = "。可检查输出目录是否可写、磁盘空间是否充足，然后重试。"
                self._set_message(
                    f"{kind}导出失败{owner}：{detail}{hint}",
                    error=True,
                )
                if kind == "图片":
                    messagebox.showerror("导出图片失败", detail + hint)
                elif kind == "视频":
                    messagebox.showerror("导出视频失败", detail + hint)
                return
            result: ExportResult = outcome.value
            # The notice names the material, the revision and the file, so a
            # result that belongs to an earlier document can never be mistaken
            # for the one currently on screen.
            owner_rev = (
                f"{material}，rev {result.revision}"
                if material
                else f"rev {result.revision}"
            )
            text = (
                f"{kind}导出完成（{owner_rev}）：{result.path}"
                + (f" · {result.detail}" if result.detail else "")
            )
            self._export_summary = (
                ("warn", f"{kind}完成（有提示）")
                if result.warning
                else ("ok", f"{kind}完成")
            )
            self._set_message(
                text,
                error=bool(result.warning),
                role="warn" if result.warning else "ok",
            )
            self._export_notice_until = time.monotonic() + EXPORT_NOTICE_SECONDS
            if result.warning:
                messagebox.showwarning("LUT 一致性提示", result.warning)
        finally:
            self._refresh_busy()

    def close(self) -> None:
        if self._closing:
            return
        window = getattr(self, "_batch_window", None)
        if window is not None:
            try:
                if window.winfo_exists():
                    window.close()
            except tk.TclError:
                pass
            self._batch_window = None
        self._closing = True
        self._video_progress = None
        for timer in (
            self._debounce_id,
            self._video_seek_id,
            self._video_poll_id,
            self._video_play_id,
        ):
            if timer is None:
                continue
            try:
                self.root.after_cancel(timer)
            except tk.TclError:
                pass
        self._debounce_id = None
        self._video_seek_id = None
        self._video_poll_id = None
        self._video_play_id = None
        self._video_playing = False
        try:
            self.runner.shutdown()
            self.ai_runner.shutdown()
        except Exception:
            LOGGER.exception("runner shutdown failed")
        try:
            self.root.destroy()
        except tk.TclError:
            pass


__all__ = ["ColorApp"]
