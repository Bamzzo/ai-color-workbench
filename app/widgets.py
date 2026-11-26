"""Small reusable widgets: tooltips and text truncation helpers.

Both exist to satisfy one product rule: a long file name or output path must
never break the layout, but the full value must still be reachable. Truncation
keeps the layout stable; the tooltip and detail lines keep the value visible.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk


def shorten_middle(text: str, limit: int, *, keep_tail: int | None = None) -> str:
    """Shorten ``text`` in the middle so both ends stay recognisable."""
    if limit <= 3 or len(text) <= limit:
        return text
    tail = keep_tail if keep_tail is not None else max(4, limit // 3)
    head = max(2, limit - tail - 1)
    return text[:head] + "…" + text[-tail:]


def shorten_path(path: Path | str, limit: int) -> str:
    """Keep the file name intact and elide leading directories when needed."""
    path = Path(path)
    name = path.name
    parent = str(path.parent)
    budget = limit - len(name) - 1
    if budget <= 1:
        return shorten_middle(name, limit)
    return shorten_middle(parent, budget) + "/" + name


class Tooltip:
    """Hover text for a widget, used for truncated names and icon-only buttons."""

    def __init__(
        self,
        widget: tk.Misc,
        text: str = "",
        *,
        delay_ms: int = 450,
        wrap: int = 640,
    ) -> None:
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms
        self.wrap = wrap
        self._after_id: str | None = None
        self._window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def set_text(self, text: str) -> None:
        self.text = text
        if self._window is not None:
            self._hide()

    def update_text(self, text: str) -> None:
        """Change the text while hovering (e.g. the row under the pointer)."""
        if text == self.text:
            return
        self.text = text
        if not text:
            self._hide()
            return
        if self._window is not None:
            self._hide()
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _schedule(self, _event=None) -> None:
        if not self.text:
            return
        self._cancel()
        self._after_id = self.widget.after(self.delay_ms, self._show)

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None

    def _show(self) -> None:
        self._after_id = None
        if self._window is not None or not self.text:
            return
        try:
            if not self.widget.winfo_viewable():
                return
            x = self.widget.winfo_rootx() + 12
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        except tk.TclError:
            return
        window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.wm_geometry(f"+{x}+{y}")
        window.configure(bg="#4a5158")
        label = tk.Label(
            window,
            text=self.text,
            justify="left",
            background="#2e3338",
            foreground="#e4e6e8",
            padx=8,
            pady=4,
            wraplength=self.wrap,
            borderwidth=0,
        )
        label.pack(padx=1, pady=1)
        self._window = window

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._window is not None:
            try:
                self._window.destroy()
            except tk.TclError:
                pass
            self._window = None


class StatusChip(ttk.Label):
    """A small labelled status field: ``前缀 · 值`` with a semantic style.

    The prefix is literal text ("预览", "AI", "导出", "批次"), so the state is
    readable without relying on colour alone.
    """

    def __init__(self, master: tk.Misc, label: str, **kwargs) -> None:
        super().__init__(master, text=f"{label} · —", **kwargs)
        self._label = label
        self.set_value("—", "neutral")

    def set_value(self, value: str, role: str = "neutral") -> None:
        theme_style = {
            "neutral": "Status.TLabel",
            "running": "StatusRunning.TLabel",
            "ok": "StatusOk.TLabel",
            "warn": "StatusWarn.TLabel",
            "error": "StatusError.TLabel",
        }.get(role, "Status.TLabel")
        self.configure(text=f"{self._label} · {value}", style=theme_style)
