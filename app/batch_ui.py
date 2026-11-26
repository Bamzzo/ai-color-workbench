"""Batch workspace window.

The window owns a ``BatchState`` and a ``BatchRunner``; the main window owns the
single-document editor. While a batch runs the main window stops submitting
previews and exports, so only one heavy task is ever competing for the engine.

Tk rules followed here: every widget and every ``PhotoImage`` is created and
touched on the main thread. Background threads only decode thumbnails and push
plain data into a queue.
"""

from __future__ import annotations

import queue
import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from . import paths, theme as theme_mod, video_io
from .widgets import Tooltip, shorten_middle, shorten_path
from .batch import (
    BatchItem,
    BatchPlanError,
    BatchRunner,
    BatchState,
    ConflictPolicy,
    ItemStatus,
    MediaKind,
    OutputPlan,
    Strategy,
    plan_batch,
)
from .batch_export import BatchExportWorker

IMAGE_SUFFIXES = {
    ".jpg", ".jpeg", ".jpe", ".png", ".webp", ".bmp",
    ".tif", ".tiff", ".gif", ".heic", ".heif", ".avif",
}

STATUS_TEXT = {
    ItemStatus.PENDING: "待处理",
    ItemStatus.PREPARING: "准备中",
    ItemStatus.RUNNING: "处理中",
    ItemStatus.DONE: "已完成",
    ItemStatus.FAILED: "失败",
    ItemStatus.CANCELLED: "已取消",
    ItemStatus.SKIPPED: "已跳过",
}

CONFLICT_LABELS = {
    "跳过（推荐）": ConflictPolicy.SKIP,
    "改名保留两份": ConflictPolicy.RENAME,
    "覆盖已有文件": ConflictPolicy.OVERWRITE,
}

PRESET_LABELS = {
    "极快（体积大）": "ultrafast",
    "快": "fast",
    "均衡": "medium",
    "慢（体积小）": "slow",
}

IMAGE_FORMAT_LABELS = {
    "PNG（无损）": ".png",
    "JPEG（有损）": ".jpg",
}

THUMB_SIDE = 64


class BatchWindow(tk.Toplevel):
    def __init__(self, master: tk.Misc, app) -> None:
        super().__init__(master)
        self.app = app
        self.title("批处理")
        # Layout follows the display scale so 125%/150% does not clip rows.
        try:
            self._ui_scale = max(1.0, self.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            self._ui_scale = 1.0
        self._scale_theme = getattr(app, "theme", None) or theme_mod.apply(self)
        self.configure(bg=self._scale_theme.palette.window)
        self._thumb_side = max(48, int(round(THUMB_SIDE * self._ui_scale)))
        self._row_height = max(
            self._thumb_side + int(round(4 * self._ui_scale)),
            int(round(30 * self._ui_scale)),
        )
        self.geometry(
            f"{int(round(1040 * self._ui_scale))}x"
            f"{int(round(720 * self._ui_scale))}"
        )
        self.minsize(
            int(round(860 * self._ui_scale)),
            int(round(520 * self._ui_scale)),
        )
        self.protocol("WM_DELETE_WINDOW", self.close)

        self.state: BatchState | None = None
        self.runner: BatchRunner | None = None
        self._worker = BatchExportWorker(app.pipeline)

        self._rows: dict[str, str] = {}
        self._photos: dict[str, ImageTk.PhotoImage] = {}
        self._meta: dict[str, str] = {}
        self._thumb_jobs: queue.Queue = queue.Queue()
        self._thumb_results: queue.Queue = queue.Queue()
        self._thumb_thread: threading.Thread | None = None
        self._poll_id: str | None = None
        self._running = False
        self._closing = False
        self._last_summary: tuple[str, str] | None = None

        self._build()
        self._poll_id = self.after(120, self._poll)
        theme_mod.bind_dark_titlebar(self)

    # -- layout --------------------------------------------------------

    def _px(self, value: int) -> int:
        """Scale a design-time pixel value by the display scale."""
        return int(round(value * self._ui_scale))

    def _build(self) -> None:
        t = self._scale_theme
        pad = self._px(14)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        header = ttk.Frame(self, padding=(pad, self._px(10), pad, self._px(4)))
        header.grid(row=0, column=0, sticky="ew")
        ttk.Label(header, text="批处理", style="Title.TLabel").pack(side="left")
        ttk.Label(
            header,
            text="串行队列 · 一次只跑一个 · 参数取自当前素材",
            style="Hint.TLabel",
        ).pack(side="left", padx=(self._px(10), 0))
        self.header_status_var = tk.StringVar(value="批次 · 空闲")
        self.header_status = ttk.Label(
            header, textvariable=self.header_status_var, style="Status.TLabel"
        )
        self.header_status.pack(side="right")

        strategy_wrap = ttk.Frame(self, padding=(pad, 0, pad, self._px(2)))
        strategy_wrap.grid(row=1, column=0, sticky="ew")
        strategy_row = ttk.Frame(strategy_wrap)
        strategy_row.grid(row=0, column=0, sticky="ew")
        self.strategy_var = tk.StringVar(value=Strategy.UNIFORM.value)
        ttk.Label(strategy_row, text="起始策略", style="Section.TLabel").pack(
            side="left", padx=(0, self._px(8))
        )
        ttk.Radiobutton(
            strategy_row,
            text="统一参数",
            value=Strategy.UNIFORM.value,
            variable=self.strategy_var,
            command=self._on_strategy_change,
        ).pack(side="left", padx=(0, self._px(10)))
        ttk.Radiobutton(
            strategy_row,
            text="逐项微调",
            value=Strategy.PER_ITEM.value,
            variable=self.strategy_var,
            command=self._on_strategy_change,
        ).pack(side="left", padx=(0, self._px(10)))
        self.reference_radio = ttk.Radiobutton(
            strategy_row,
            text="参考素材协调（未启用）",
            value=Strategy.REFERENCE.value,
            variable=self.strategy_var,
            state="disabled",
        )
        self.reference_radio.pack(side="left")
        Tooltip(
            self.reference_radio,
            "参考素材协调尚未实现：不会读取参考图，也不会改动你的参数。",
        )

        self.strategy_hint_var = tk.StringVar(value="")
        ttk.Label(
            strategy_wrap,
            textvariable=self.strategy_hint_var,
            style="Hint.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(self._px(2), 0))
        strategy_wrap.columnconfigure(0, weight=1)

        options = ttk.Frame(self, padding=(pad, self._px(4), pad, self._px(6)))
        options.grid(row=2, column=0, sticky="ew")
        options.columnconfigure(0, weight=1)

        out_row = ttk.Frame(options)
        out_row.grid(row=0, column=0, sticky="ew")
        out_row.columnconfigure(1, weight=1)
        ttk.Label(out_row, text="输出目录", style="Hint.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.output_var = tk.StringVar(value="")
        ttk.Entry(out_row, textvariable=self.output_var).grid(
            row=0, column=1, sticky="ew", padx=(self._px(6), self._px(6))
        )
        self.output_btn = ttk.Button(
            out_row, text="选择…", command=self.choose_output
        )
        self.output_btn.grid(row=0, column=2, sticky="e")

        cfg_row = ttk.Frame(options)
        cfg_row.grid(row=1, column=0, sticky="w", pady=(self._px(6), 0))
        ttk.Label(cfg_row, text="图片格式", style="Hint.TLabel").pack(side="left")
        self.image_format_var = tk.StringVar(value="PNG（无损）")
        self.image_format_box = ttk.Combobox(
            cfg_row,
            textvariable=self.image_format_var,
            values=list(IMAGE_FORMAT_LABELS),
            state="readonly",
            width=11,
        )
        self.image_format_box.pack(side="left", padx=(self._px(6), self._px(12)))
        ttk.Label(cfg_row, text="质量", style="Hint.TLabel").pack(side="left")
        self.quality_var = tk.IntVar(value=95)
        self.quality_spin = ttk.Spinbox(
            cfg_row, from_=1, to=100, textvariable=self.quality_var, width=4
        )
        self.quality_spin.pack(side="left", padx=(self._px(6), self._px(12)))
        ttk.Label(cfg_row, text="视频预设", style="Hint.TLabel").pack(side="left")
        self.preset_var = tk.StringVar(value="均衡")
        self.preset_box = ttk.Combobox(
            cfg_row,
            textvariable=self.preset_var,
            values=list(PRESET_LABELS),
            state="readonly",
            width=9,
        )
        self.preset_box.pack(side="left", padx=(self._px(6), self._px(12)))
        ttk.Label(cfg_row, text="命名后缀", style="Hint.TLabel").pack(side="left")
        self.suffix_var = tk.StringVar(value="_graded")
        ttk.Entry(cfg_row, textvariable=self.suffix_var, width=10).pack(
            side="left", padx=(self._px(6), self._px(12))
        )
        ttk.Label(cfg_row, text="同名冲突", style="Hint.TLabel").pack(side="left")
        self.conflict_var = tk.StringVar(value="跳过（推荐）")
        self.conflict_box = ttk.Combobox(
            cfg_row,
            textvariable=self.conflict_var,
            values=list(CONFLICT_LABELS),
            state="readonly",
            width=12,
        )
        self.conflict_box.pack(side="left", padx=(self._px(6), 0))

        actions = ttk.Frame(self, padding=(pad, self._px(4), pad, self._px(4)))
        actions.grid(row=3, column=0, sticky="new")
        row_files = ttk.Frame(actions)
        row_files.grid(row=0, column=0, sticky="w")
        row_run = ttk.Frame(actions)
        row_run.grid(row=1, column=0, sticky="w", pady=(self._px(4), 0))
        row_params = ttk.Frame(actions)
        row_params.grid(row=2, column=0, sticky="w", pady=(self._px(4), 0))

        self.add_btn = ttk.Button(
            row_files, text="添加素材…", command=self.choose_files
        )
        self.add_btn.pack(side="left", padx=(0, 4))
        self.remove_btn = ttk.Button(
            row_files, text="移除所选", command=self.remove_selected
        )
        self.remove_btn.pack(side="left", padx=4)
        self.retry_btn = ttk.Button(
            row_files, text="重试所选", command=self.retry_selected
        )
        self.retry_btn.pack(side="left", padx=4)
        Tooltip(self.remove_btn, "只移除尚未开始的选中项；已完成的结果保留在输出目录")
        Tooltip(self.retry_btn, "把失败、取消或跳过的选中项重新排队")

        self.start_btn = ttk.Button(
            row_run, text="开始导出", style="Accent.TButton", command=self.start
        )
        self.start_btn.pack(side="left", padx=(0, 4))
        self.cancel_current_btn = ttk.Button(
            row_run, text="取消当前项", command=self.cancel_current
        )
        self.cancel_current_btn.pack(side="left", padx=4)
        self.cancel_pending_btn = ttk.Button(
            row_run, text="取消后续", command=self.cancel_pending
        )
        self.cancel_pending_btn.pack(side="left", padx=4)
        self.cancel_all_btn = ttk.Button(
            row_run, text="全部取消", command=self.cancel_all
        )
        self.cancel_all_btn.pack(side="left", padx=4)
        Tooltip(self.cancel_current_btn, "中断正在处理的项；队列继续执行下一项")
        Tooltip(self.cancel_pending_btn, "取消仍在排队的项；正在处理的项会跑完")
        Tooltip(self.cancel_all_btn, "中断当前项并取消所有排队项")

        ttk.Label(
            row_params, text="参数", style="Section.TLabel"
        ).pack(side="left", padx=(0, self._px(8)))
        self.apply_params_btn = ttk.Button(
            row_params,
            text="用当前参数填充所选",
            command=self.apply_current_params,
        )
        self.apply_params_btn.pack(side="left", padx=(0, 4))
        self.clear_params_btn = ttk.Button(
            row_params, text="恢复统一参数", command=self.clear_overrides
        )
        self.clear_params_btn.pack(side="left", padx=4)
        self.params_hint_var = tk.StringVar(
            value="填充只影响所选且尚未开始的项，运行中的结果按启动时快照"
        )
        ttk.Label(
            row_params, textvariable=self.params_hint_var, style="Hint.TLabel"
        ).pack(side="left", padx=(self._px(8), 0))

        tree_frame = ttk.Frame(self, padding=(14, 0, 14, 0))
        tree_frame.grid(row=4, column=0, sticky="nsew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        # Row height must be set on the base style: a derived style name without
        # an item layout drops the item text on this Tk/theme build (the image
        # then renders alone). The app has no other Treeview.
        style = ttk.Style(self)
        style.configure("Treeview", rowheight=self._row_height)
        style.configure("Treeview.Heading", rowheight=max(self._row_height, self._px(28)))

        self.tree = ttk.Treeview(
            tree_frame,
            columns=("name", "kind", "params", "info", "status", "progress", "note"),
            show="tree headings",
            selectmode="extended",
        )
        # The tree column only carries the thumbnail: on this Tk build a tree
        # item that owns an image stops rendering its own text, so the file
        # name lives in a normal value column instead.
        self.tree.heading("#0", text="预览")
        self.tree.column("#0", width=self._px(72), stretch=False,
                         minwidth=self._px(72), anchor="center")
        self.tree.heading("name", text="素材")
        self.tree.column("name", width=self._px(230), stretch=True,
                         minwidth=self._px(150))
        self.tree.heading("kind", text="类型")
        self.tree.column("kind", width=self._px(54), stretch=False,
                         minwidth=self._px(54))
        self.tree.heading("params", text="参数")
        self.tree.column("params", width=self._px(56), stretch=False,
                         minwidth=self._px(56))
        self.tree.heading("info", text="尺寸 / 时长")
        self.tree.column("info", width=self._px(132), stretch=False,
                         minwidth=self._px(132))
        self.tree.heading("status", text="状态")
        self.tree.column("status", width=self._px(84), stretch=False,
                         minwidth=self._px(84))
        self.tree.heading("progress", text="进度")
        self.tree.column("progress", width=self._px(62), stretch=False,
                         minwidth=self._px(62))
        self.tree.heading("note", text="说明 / 输出")
        self.tree.column("note", width=self._px(290), stretch=True,
                         minwidth=self._px(160))
        self.tree.tag_configure("failed", foreground=theme_mod.PALETTE.error)
        self.tree.tag_configure("done", foreground=theme_mod.PALETTE.ok)
        self.tree.tag_configure("running", foreground=theme_mod.PALETTE.accent)
        self.tree.tag_configure("cancelled", foreground=theme_mod.PALETTE.text_muted)
        self.tree.tag_configure("skipped", foreground=theme_mod.PALETTE.text_muted)
        self.tree.grid(row=0, column=0, sticky="nsew")

        scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        hscroll = ttk.Scrollbar(
            tree_frame, orient="horizontal", command=self.tree.xview
        )
        hscroll.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=hscroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_selection_detail())
        # Full path for the row under the pointer: the visible cell stays short,
        # but a long Chinese file name can always be read in full.
        self._tree_tip = Tooltip(self.tree, "")
        self.tree.bind("<Motion>", self._on_tree_motion, add="+")

        footer = ttk.Frame(
            self, padding=(pad, self._px(6), pad, self._px(10))
        )
        footer.grid(row=5, column=0, sticky="ew")
        footer.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="尚未添加素材")
        self.status_label = ttk.Label(
            footer, textvariable=self.status_var, anchor="w", style="Status.TLabel"
        )
        self.status_label.grid(row=1, column=0, sticky="ew")
        self.detail_var = tk.StringVar(value="")
        self.detail_label = ttk.Label(
            footer,
            textvariable=self.detail_var,
            anchor="w",
            style="Hint.TLabel",
            wraplength=self._px(760),
            justify="left",
        )
        self.detail_label.grid(row=2, column=0, sticky="ew", pady=(self._px(2), 0))
        self.selection_var = tk.StringVar(value="")
        self.selection_label = ttk.Label(
            footer,
            textvariable=self.selection_var,
            anchor="w",
            style="Hint.TLabel",
            wraplength=self._px(720),
            justify="left",
        )
        self.selection_label.grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(self._px(2), 0)
        )
        ttk.Separator(footer, orient="horizontal").grid(
            row=0, column=0, columnspan=2, sticky="ew", pady=(0, self._px(4))
        )
        self.close_btn = ttk.Button(footer, text="关闭", command=self.close)
        self.close_btn.grid(row=1, column=1, rowspan=2, sticky="e", padx=(self._px(10), 0))

        self._refresh_buttons()
        self._on_strategy_change()

    # -- import --------------------------------------------------------

    def choose_files(self) -> None:
        picked = filedialog.askopenfilenames(
            parent=self,
            title="选择图片或视频（可多选）",
            filetypes=[
                (
                    "图片与视频",
                    "*.jpg *.jpeg *.jpe *.png *.webp *.bmp *.tif *.tiff "
                    "*.gif *.heic *.heif *.avif "
                    "*.mp4 *.mov *.m4v *.mkv *.webm *.avi *.wmv *.mts *.m2ts",
                ),
                ("所有文件", "*.*"),
            ],
        )
        if picked:
            self.add_paths([Path(p) for p in picked])

    def add_paths(self, paths_in: list[Path]) -> None:
        if self._running:
            self._status("批次运行中，暂时不能添加素材")
            return
        if self.state is None:
            self.state = BatchState.create(
                self._strategy(),
                self.app.state.params,
                self._output_plan(),
            )
        for path in paths_in:
            self._add_one(Path(path))
        self._refresh_rows()
        self._refresh_status()

    def _add_one(self, path: Path) -> None:
        assert self.state is not None
        suffix = path.suffix.lower()
        if suffix in video_io.VIDEO_SUFFIXES:
            kind = MediaKind.VIDEO
        elif suffix in IMAGE_SUFFIXES:
            kind = MediaKind.IMAGE
        else:
            kind = MediaKind.IMAGE

        override = self.app.state.params if self._strategy() is Strategy.PER_ITEM else None
        try:
            item = BatchItem.create(path, kind, override=override)
            record = self.state.add_item(item)
        except ValueError as exc:
            self._status(str(exc))
            return

        if suffix not in IMAGE_SUFFIXES and suffix not in video_io.VIDEO_SUFFIXES:
            record.status = ItemStatus.FAILED
            record.error_code = "IMPORT_UNSUPPORTED"
            record.error_message = f"不支持的格式：{suffix or '无扩展名'}"
            record.finished_at = time.time()
            return
        if not path.is_file():
            record.status = ItemStatus.FAILED
            record.error_code = "IMPORT_MISSING"
            record.error_message = "文件不存在或不可读"
            record.finished_at = time.time()
            return
        self._queue_thumbnail(item.item_id, path, kind)

    # -- output config -------------------------------------------------

    def choose_output(self) -> None:
        picked = filedialog.askdirectory(
            parent=self, title="选择输出目录", mustexist=True
        )
        if picked:
            self.output_var.set(picked)

    def set_output_dir(self, path: Path | str) -> None:
        self.output_var.set(str(path))

    def _output_plan(self) -> OutputPlan:
        directory = Path(self.output_var.get().strip() or ".")
        conflict = CONFLICT_LABELS.get(
            self.conflict_var.get(), ConflictPolicy.SKIP
        )
        try:
            quality = int(self.quality_var.get())
        except (tk.TclError, ValueError):
            quality = 95
        return OutputPlan(
            directory=directory,
            image_suffix=IMAGE_FORMAT_LABELS.get(
                self.image_format_var.get(), ".png"
            ),
            image_quality=max(1, min(100, quality)),
            video_preset=PRESET_LABELS.get(self.preset_var.get(), "medium"),
            suffix_label=self.suffix_var.get().strip() or "_graded",
            conflict=conflict,
        )

    def _strategy(self) -> Strategy:
        try:
            return Strategy(self.strategy_var.get())
        except ValueError:
            return Strategy.UNIFORM

    def _on_strategy_change(self) -> None:
        strategy = self._strategy()
        if strategy is Strategy.PER_ITEM:
            text = "逐项微调：每项保留独立参数，之后可用“填充/恢复”单独调整"
        elif strategy is Strategy.REFERENCE:
            text = "参考素材协调尚未启用，不会改动任何参数"
        else:
            text = "统一参数：所有未单独覆盖的素材共用当前参数，个别项可再覆盖"
        if hasattr(self, "strategy_hint_var"):
            self.strategy_hint_var.set(text)
        self.detail_var.set(text)

    # -- run control ---------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        if self.state is None or not self.state.items:
            messagebox.showinfo("批处理", "请先添加素材", parent=self)
            return

        if self.app.pipeline is None:
            messagebox.showwarning(
                "批处理", "渲染引擎不可用，无法执行批处理", parent=self
            )
            return

        directory_text = self.output_var.get().strip()
        if not directory_text:
            messagebox.showwarning(
                "批处理", "请先选择输出目录", parent=self
            )
            return
        directory = Path(directory_text).expanduser()
        if not directory.is_dir():
            messagebox.showwarning(
                "批处理", f"输出目录不存在：\n{directory}", parent=self
            )
            return
        if not os.access(directory, os.W_OK):
            messagebox.showwarning(
                "批处理", f"输出目录不可写：\n{directory}", parent=self
            )
            return

        if self.app._outstanding_exports() > 0:
            messagebox.showwarning(
                "批处理",
                "当前素材仍有导出任务正在进行，请等待导出完成后再开始批处理。",
                parent=self,
            )
            return

        try:
            output = self._output_plan()
            self.state.output = output
            self.state.strategy = self._strategy()
            self.state.baseline = self.app.state.params
            plan = plan_batch(self.state)
        except BatchPlanError as exc:
            messagebox.showerror("无法开始批处理", exc.message, parent=self)
            return
        except ValueError as exc:
            messagebox.showerror("无法开始批处理", str(exc), parent=self)
            return

        self.state.apply_plan(plan)
        self._refresh_rows()

        if not plan.snapshots:
            messagebox.showinfo(
                "批处理",
                "没有可执行的素材。请检查失败原因或全部重试。",
                parent=self,
            )
            return

        if self.runner is not None:
            self.runner.shutdown(0.2)
        self.runner = BatchRunner(self._worker)
        self._running = True
        self.app.set_batch_active(True)
        self.runner.submit(plan.snapshots)
        self._status(
            f"已开始：{len(plan.snapshots)} 项"
            + (f" · 跳过 {len(plan.skipped)}" if plan.skipped else "")
            + (f" · 失败 {len(plan.errors)}" if plan.errors else "")
        )
        self._refresh_buttons()

    def cancel_current(self) -> None:
        if self.runner is None:
            return
        current = self.runner.current_item_id()
        if current is None:
            self._status("没有正在运行的项")
            return
        if self.runner.cancel_item(current):
            self._status("已请求取消当前项")
        else:
            self._status("当前项已经结束，无法取消")

    def cancel_pending(self) -> None:
        if self.runner is None:
            return
        count = self.runner.cancel_pending()
        self._status(f"已取消 {count} 个后续项" if count else "没有排队项")

    def cancel_all(self) -> None:
        if self.runner is None:
            return
        count = self.runner.cancel_all()
        self._status(f"已取消 {count} 项")

    def remove_selected(self) -> None:
        if self.state is None:
            return
        removed = 0
        for item_id in self._selected_item_ids():
            if self.state.remove_item(item_id):
                removed += 1
        self._refresh_rows()
        self._refresh_status()
        if removed:
            self._status(f"已移除 {removed} 项")

    def retry_selected(self) -> None:
        if self.state is None:
            return
        retried = 0
        for item_id in self._selected_item_ids():
            if self.state.retry(item_id):
                retried += 1
        self._refresh_rows()
        self._refresh_status()
        if retried:
            self._status(f"已重新排队 {retried} 项，点“开始导出”继续")

    def _pending_selection(self) -> list[str]:
        """Selected item IDs that may still be edited (not started)."""
        return [
            item_id
            for item_id in self._selected_item_ids()
            if self.state is not None
            and (record := self.state.records.get(item_id)) is not None
            and record.status is ItemStatus.PENDING
        ]

    def apply_current_params(self) -> None:
        """Copy the editor's current parameters onto the selected pending items."""
        if self.state is None:
            return
        selected = self._selected_item_ids()
        if not selected:
            self._status("请先选择要应用参数的项")
            return
        targets = self._pending_selection()
        if not targets:
            self._status("所选项目前不可修改（仅待处理项可调整）")
            return
        params = self.app.state.params
        changed = 0
        for item_id in targets:
            if self.state.item(item_id).override != params:
                self.state.set_override(item_id, params)
                changed += 1
        self._refresh_rows()
        self._refresh_status()
        self._status(
            f"已用当前参数填充 {changed} 项"
            if changed
            else "所选项目前已是当前参数"
        )

    def clear_overrides(self) -> None:
        """Drop per-item parameters so the shared baseline applies again."""
        if self.state is None:
            return
        targets = [i for i in self._pending_selection()
                   if self.state.item(i).override is not None]
        for item_id in targets:
            self.state.set_override(item_id, None)
        self._refresh_rows()
        self._refresh_status()
        self._status(
            f"已恢复统一参数：{len(targets)} 项"
            if targets
            else "所选项目前都使用统一参数"
        )

    # -- polling -------------------------------------------------------

    def _poll(self) -> None:
        if self._closing:
            return
        self._drain_thumbnails()
        if self.runner is not None:
            for update in self.runner.poll():
                if self.state is not None:
                    self.state.apply_update(update)
                self._refresh_row(update.item_id)
            if self._running and self.runner.is_idle():
                self._running = False
                self.app.set_batch_active(False)
                self._refresh_rows()
                self._refresh_buttons()
                text = self._summary()
                failed = bool(
                    self.state
                    and any(
                        r.status is ItemStatus.FAILED
                        for r in self.state.records.values()
                    )
                )
                self._last_summary = (
                    "warn" if failed else "ok",
                    text.replace("批次结束：", "结束 · "),
                )
                self._status(text)
        self._refresh_status()
        self._refresh_buttons()
        self._poll_id = self.after(150, self._poll)

    # -- thumbnails ----------------------------------------------------

    def _queue_thumbnail(self, item_id: str, path: Path, kind: MediaKind) -> None:
        self._thumb_jobs.put((item_id, path, kind))
        if self._thumb_thread is None or not self._thumb_thread.is_alive():
            self._thumb_thread = threading.Thread(
                target=self._thumbnail_loop, name="batch-thumbs", daemon=True
            )
            self._thumb_thread.start()

    def _thumbnail_loop(self) -> None:
        while True:
            job = self._thumb_jobs.get()
            if job is None:
                return
            item_id, path, kind = job
            try:
                if kind is MediaKind.VIDEO:
                    info = video_io.probe(path)
                    frame = paths.VIDEO_CACHE / f"batch-thumb-{item_id}.png"
                    if not frame.is_file():
                        video_io.extract_frame(path, 0.0, frame, info=info)
                    image = Image.open(frame)
                    image.load()
                    meta = (
                        f"{info.display_width}×{info.display_height} · "
                        f"{info.duration_s:.2f}s"
                    )
                else:
                    image = Image.open(path)
                    width, height = image.size
                    image.draft("RGB", (self._thumb_side * 2, self._thumb_side * 2))
                    image = image.convert("RGB")
                    meta = f"{width}×{height}"
            except Exception as exc:  # thumbnail failure is not item failure
                self._thumb_results.put((item_id, None, f"预览不可用：{exc}"))
                continue
            try:
                image.thumbnail((self._thumb_side, self._thumb_side))
                self._thumb_results.put((item_id, image.copy(), meta))
            finally:
                image.close()

    def _drain_thumbnails(self) -> None:
        while True:
            try:
                item_id, image, meta = self._thumb_results.get_nowait()
            except queue.Empty:
                return
            self._meta[item_id] = meta
            iid = self._rows.get(item_id)
            if iid is None or not self.tree.exists(iid):
                continue
            if image is not None:
                photo = ImageTk.PhotoImage(image)
                self._photos[item_id] = photo
                self.tree.item(iid, image=photo)
            self.tree.set(iid, "info", meta)

    # -- rendering -----------------------------------------------------

    def _refresh_rows(self) -> None:
        if self.state is None:
            return
        for item in self.state.items:
            iid = self._rows.get(item.item_id)
            if iid is None or not self.tree.exists(iid):
                iid = self.tree.insert(
                    "",
                    "end",
                    values=(item.source.name, "", "", "…", "", "", ""),
                )
                self._rows[item.item_id] = iid
            self.tree.set(
                iid,
                "kind",
                "视频" if item.kind is MediaKind.VIDEO else "图片",
            )
            self.tree.set(
                iid, "params", "单独" if item.override is not None else "统一"
            )
            self.tree.set(iid, "info", self._meta.get(item.item_id, "…"))
            self._refresh_row(item.item_id)
        for item_id, iid in list(self._rows.items()):
            if self.state.records.get(item_id) is None:
                if self.tree.exists(iid):
                    self.tree.delete(iid)
                self._rows.pop(item_id, None)
                self._photos.pop(item_id, None)

    def _refresh_row(self, item_id: str) -> None:
        if self.state is None:
            return
        iid = self._rows.get(item_id)
        record = self.state.records.get(item_id)
        if iid is None or record is None or not self.tree.exists(iid):
            return
        self.tree.set(iid, "status", STATUS_TEXT.get(record.status, record.status.value))
        progress = record.progress if record.status is ItemStatus.RUNNING else (
            1.0 if record.status is ItemStatus.DONE else 0.0
        )
        self.tree.set(iid, "progress", f"{progress * 100:.0f}%" if progress else "")
        note = (
            record.error_message
            or record.skip_reason
            or (record.output.name if record.output is not None else "")
        )
        self.tree.set(iid, "note", note)
        tags = ()
        if record.status is ItemStatus.FAILED:
            tags = ("failed",)
        elif record.status is ItemStatus.DONE:
            tags = ("done",)
        elif record.status is ItemStatus.RUNNING:
            tags = ("running",)
        elif record.status is ItemStatus.CANCELLED:
            tags = ("cancelled",)
        elif record.status is ItemStatus.SKIPPED:
            tags = ("skipped",)
        self.tree.item(iid, tags=tags)

    def _refresh_status(self) -> None:
        if self.state is None:
            self.status_var.set("尚未添加素材")
            self._set_status_style("neutral")
            self._set_header("空闲", "neutral")
            return
        records = list(self.state.records.values())
        count = len(records)
        done = sum(1 for r in records if r.status is ItemStatus.DONE)
        failed = sum(1 for r in records if r.status is ItemStatus.FAILED)
        cancelled = sum(1 for r in records if r.status is ItemStatus.CANCELLED)
        skipped = sum(1 for r in records if r.status is ItemStatus.SKIPPED)
        pending = sum(1 for r in records if r.status is ItemStatus.PENDING)
        running = sum(1 for r in records if r.status is ItemStatus.RUNNING)
        queued = self.runner.queued_count() if self.runner is not None else 0
        parts = [f"共 {count} 项"]
        current_id = (
            self.runner.current_item_id() if self.runner is not None else None
        )
        if current_id:
            try:
                current_name = self.state.item(current_id).source.name
            except KeyError:
                current_name = ""
            if current_name:
                parts.insert(0, "当前 " + shorten_middle(current_name, 28))
        if running:
            parts.append(f"处理中 {running}")
        parts.append(f"待处理 {pending}")
        if queued:
            parts.append(f"排队 {queued}")
        parts.append(f"完成 {done}")
        if failed:
            parts.append(f"失败 {failed}")
        if cancelled:
            parts.append(f"取消 {cancelled}")
        if skipped:
            parts.append(f"跳过 {skipped}")
        remaining = count - done - failed - cancelled - skipped
        if remaining > 0:
            parts.append(f"剩余 {remaining}")
        self.status_var.set(" · ".join(parts))
        if running or queued or self._running:
            self._set_status_style("running")
        elif failed:
            self._set_status_style("error")
        elif done:
            self._set_status_style("ok")
        else:
            self._set_status_style("neutral")
        if self._running:
            self._set_header(self.progress_text(), "running")
        elif self._last_summary is not None and not (running or queued):
            self._set_header(*self._last_summary)
        else:
            self._set_header("就绪", "neutral")

    def _set_status_style(self, role: str) -> None:
        mapping = {
            "neutral": "Status.TLabel",
            "running": "StatusRunning.TLabel",
            "ok": "StatusOk.TLabel",
            "warn": "StatusWarn.TLabel",
            "error": "StatusError.TLabel",
        }
        if hasattr(self, "status_label"):
            self.status_label.configure(style=mapping.get(role, "Status.TLabel"))

    def _set_header(self, text: str, role: str = "neutral") -> None:
        mapping = {
            "neutral": "Status.TLabel",
            "running": "StatusRunning.TLabel",
            "ok": "StatusOk.TLabel",
            "warn": "StatusWarn.TLabel",
            "error": "StatusError.TLabel",
        }
        if hasattr(self, "header_status"):
            self.header_status_var.set(f"批次 · {text}")
            self.header_status.configure(style=mapping.get(role, "Status.TLabel"))

    def progress_text(self) -> str:
        """Short "done/total" text for the main window's batch chip."""
        if self.state is None:
            return "运行中"
        records = list(self.state.records.values())
        total = len(records)
        done = sum(1 for r in records if r.status is ItemStatus.DONE)
        failed = sum(1 for r in records if r.status is ItemStatus.FAILED)
        cancelled = sum(1 for r in records if r.status is ItemStatus.CANCELLED)
        skipped = sum(1 for r in records if r.status is ItemStatus.SKIPPED)
        text = f"运行中 {done}/{total} 完成"
        remaining = total - done - failed - cancelled - skipped
        if remaining:
            text += f" · 剩余 {remaining}"
        if failed:
            text += f" · {failed} 失败"
        return text

    def last_summary(self) -> tuple[str, str] | None:
        """Role and text of the last finished batch, for the main status bar."""
        return self._last_summary

    def _summary(self) -> str:
        if self.state is None:
            return "批次结束"
        records = list(self.state.records.values())
        done = sum(1 for r in records if r.status is ItemStatus.DONE)
        failed = sum(1 for r in records if r.status is ItemStatus.FAILED)
        cancelled = sum(1 for r in records if r.status is ItemStatus.CANCELLED)
        skipped = sum(1 for r in records if r.status is ItemStatus.SKIPPED)
        text = f"批次结束：完成 {done}"
        if failed:
            text += f"，失败 {failed}"
        if cancelled:
            text += f"，取消 {cancelled}"
        if skipped:
            text += f"，跳过 {skipped}"
        return text

    def _refresh_buttons(self) -> None:
        running = self._running
        self.add_btn.configure(state="disabled" if running else "normal")
        self.remove_btn.configure(state="disabled" if running else "normal")
        self.retry_btn.configure(state="disabled" if running else "normal")
        self.start_btn.configure(
            state="disabled" if running else "normal",
            text="运行中" if running else "开始导出",
        )
        has_runner = self.runner is not None
        self.apply_params_btn.configure(state="disabled" if running else "normal")
        self.clear_params_btn.configure(state="disabled" if running else "normal")
        current = has_runner and self.runner.is_running()
        queued = has_runner and self.runner.queued_count() > 0
        self.cancel_current_btn.configure(
            state="normal" if current else "disabled"
        )
        self.cancel_pending_btn.configure(
            state="normal" if queued else "disabled"
        )
        self.cancel_all_btn.configure(
            state="normal" if (current or queued) else "disabled"
        )

    # -- misc ----------------------------------------------------------

    def _selected_item_ids(self) -> list[str]:
        by_iid = {iid: item_id for item_id, iid in self._rows.items()}
        return [
            by_iid[iid] for iid in self.tree.selection() if iid in by_iid
        ]

    def _show_selection_detail(self) -> None:
        if self.state is None:
            return
        selected = self._selected_item_ids()
        if not selected:
            self.detail_var.set("")
            if hasattr(self, "selection_var"):
                self.selection_var.set("")
            return
        record = self.state.records.get(selected[0])
        if record is None:
            return
        if record.status is ItemStatus.FAILED:
            self.detail_var.set(
                f"{record.error_code or '错误'}：{record.error_message}"
                "　可点“重试所选”重新排队，或检查源文件与输出目录。"
            )
        elif record.status is ItemStatus.SKIPPED:
            self.detail_var.set(f"已跳过：{record.skip_reason}")
        elif record.output is not None:
            self.detail_var.set(f"输出：{record.output}")
        else:
            self.detail_var.set(STATUS_TEXT.get(record.status, ""))
        if hasattr(self, "selection_var"):
            try:
                item = self.state.item(selected[0])
                text = f"源：{item.source}"
            except KeyError:
                text = ""
            if record.output is not None:
                text += f"  →  输出：{record.output}"
            self.selection_var.set(text)

    def _on_tree_motion(self, event: tk.Event) -> None:
        """Hover text with the full source path of the row under the pointer."""
        tip = getattr(self, "_tree_tip", None)
        if tip is None or self.state is None:
            return
        iid = self.tree.identify_row(event.y)
        item_id = None
        for key, value in self._rows.items():
            if value == iid:
                item_id = key
                break
        if item_id is None:
            tip.update_text("")
            return
        try:
            item = self.state.item(item_id)
        except KeyError:
            tip.update_text("")
            return
        text = str(item.source)
        record = self.state.records.get(item_id)
        if record is not None:
            text += "\n" + STATUS_TEXT.get(record.status, record.status.value)
            if record.error_message:
                text += f"：{record.error_message}"
            if record.output is not None:
                text += f"\n输出：{record.output}"
        tip.update_text(text)

    def _status(self, text: str) -> None:
        self.detail_var.set(text)

    def close(self) -> None:
        if self._closing:
            return
        if self._running and self.runner is not None:
            remaining = self.runner.queued_count() + (1 if self.runner.is_running() else 0)
            if not messagebox.askyesno(
                "批处理仍在运行",
                f"仍有 {remaining} 项未完成。\n关闭窗口将取消所有任务，确定继续？",
                parent=self,
            ):
                return
            self.runner.cancel_all()
            clean = self.runner.shutdown(3.0)
            if not clean:
                messagebox.showwarning(
                    "仍在清理",
                    "有渲染/编码进程尚未退出，请稍后确认输出目录后再关闭应用。",
                    parent=self,
                )
        self._closing = True
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        self._thumb_jobs.put(None)
        self.app.set_batch_active(False)
        if getattr(self.app, "_batch_window", None) is self:
            self.app._batch_window = None
        self.destroy()
