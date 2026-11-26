"""Design tokens and ttk theme for the dark colour-grading workbench.

The app previously used the native ``vista`` theme, which paints light chrome
that cannot be recoloured, sitting next to a dark preview canvas. That mismatch
is what this module fixes: one neutral grey ramp, one accent, one type scale.

Rules the palette follows:

* No pure black and no pure white over large areas. The canvas is the darkest
  surface but still ``#15171a``; panels are a mid grey.
* The preview is the visual centre, so UI surfaces stay desaturated. The only
  saturated colours are the accent (selection/focus), and the semantic
  success/warning/error colours, all used in small areas and always paired with
  text or an icon-ish prefix — never colour alone.
* Every size is expressed in 96-dpi logical pixels and multiplied by the
  display scale, so 125%/150% does not produce clipped or overlapping chrome.

``clam`` is used as the ttk base theme because it is drawn by Tk itself and
therefore accepts explicit colours. The native ``vista`` engine ignores most
background settings, which is exactly why a dark theme needs a different base.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

# ----------------------------------------------------------------------
# palette
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Palette:
    """Neutral workbench ramp plus four semantic accents."""

    # Surfaces, darkest to lightest.
    canvas: str = "#15171a"        # preview backdrop
    canvas_edge: str = "#0f1113"   # thin inner frame around the preview
    window: str = "#1f2226"        # window background behind panels
    surface: str = "#272b30"       # toolbar, sidebar, status bar
    surface_alt: str = "#2e3338"   # inputs above panels, hovered rows
    surface_high: str = "#353b41"  # hovered buttons, selected list rows
    input: str = "#1b1e22"         # editable fields (recessed)

    border: str = "#3a4046"
    border_strong: str = "#4a5158"

    text: str = "#e4e6e8"
    text_muted: str = "#9aa1a8"
    text_disabled: str = "#6b7177"

    accent: str = "#4c8dff"        # focus, selected tab, split highlight
    accent_dim: str = "#2b4b78"    # selection fill in lists/notebooks

    ok: str = "#5bb98c"
    warn: str = "#d8a657"
    error: str = "#e0716f"


PALETTE = Palette()

# Semantic status styles, keyed by the role a message plays. ``neutral`` is the
# muted running/default state, so a status line can be recoloured by swapping
# the style instead of the text.
STATUS_STYLES = {
    "neutral": "Status.TLabel",
    "running": "StatusRunning.TLabel",
    "ok": "StatusOk.TLabel",
    "warn": "StatusWarn.TLabel",
    "error": "StatusError.TLabel",
}


@dataclass(frozen=True)
class Theme:
    palette: Palette
    scale: float
    font_family: str
    font_size: int

    # -- sizing --------------------------------------------------------

    def px(self, value: float) -> int:
        """Logical px -> device px."""
        return int(round(value * self.scale))

    def padding(self, horizontal: float, vertical: float) -> tuple[int, int]:
        return self.px(horizontal), self.px(vertical)

    def font(self, size: int | None = None, *, weight: str = "normal") -> tuple:
        return (
            self.font_family,
            size if size is not None else self.font_size,
            weight,
        )

    # -- helpers -------------------------------------------------------

    def status_style(self, role: str) -> str:
        return STATUS_STYLES.get(role, STATUS_STYLES["neutral"])


def _colorref(hex_colour: str) -> int:
    """``#rrggbb`` -> Win32 COLORREF (0x00BBGGRR)."""
    value = hex_colour.lstrip("#")
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return r | (g << 8) | (b << 16)


def apply_dark_titlebar(window: tk.Misc) -> None:
    """Ask DWM to draw the caption dark, matching the workbench.

    Without this the window keeps a light system title bar above a dark body,
    which is the single brightest element on screen. Every call is optional:
    older Windows builds simply ignore the attributes.
    """
    import sys

    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.user32.GetAncestor(window.winfo_id(), 2)
        if not hwnd:
            return
        dwm = ctypes.windll.dwmapi
        enabled = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE
            if dwm.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(enabled), ctypes.sizeof(enabled)
            ) == 0:
                break
        # Windows 11 22H2+: exact caption / border / text colours.
        for attribute, colour in (
            (35, PALETTE.surface),
            (34, PALETTE.border),
            (36, PALETTE.text),
        ):
            value = ctypes.c_int(_colorref(colour))
            dwm.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass


def bind_dark_titlebar(window: tk.Misc) -> None:
    """Apply the dark caption and keep it after the window is mapped.

    Tk creates the real top-level wrapper HWND when the window is first mapped,
    so attributes set during construction land on a temporary handle and are
    lost. Re-applying on ``<Map>`` (plus one delayed retry) covers that.
    """
    def refresh(event=None) -> None:
        if event is not None and getattr(event, "widget", None) is not window:
            return
        apply_dark_titlebar(window)

    apply_dark_titlebar(window)
    window.bind("<Map>", refresh, add="+")
    try:
        window.after(250, refresh)
    except tk.TclError:
        pass


def ui_scale(root: tk.Misc) -> float:
    """Display scale relative to 96 dpi (1.0, 1.25, 1.5, ...)."""
    try:
        return max(1.0, root.winfo_fpixels("1i") / 96.0)
    except tk.TclError:
        return 1.0


def _font_family(root: tk.Misc) -> str:
    """Prefer a CJK-capable UI face, fall back cleanly on other systems."""
    import tkinter.font as tkfont

    available = set(tkfont.families(root))
    for candidate in (
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "PingFang SC",
        "Noto Sans CJK SC",
        "Segoe UI",
        "Helvetica",
    ):
        if candidate in available:
            return candidate
    return "TkDefaultFont"


# ----------------------------------------------------------------------
# theme application
# ----------------------------------------------------------------------


def apply(root: tk.Misc) -> Theme:
    """Install the workbench theme and return its tokens.

    Safe to call more than once; every style is configured, not appended.
    """
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:  # platform without clam: keep the default engine
        pass

    scale = ui_scale(root)
    family = _font_family(root)
    theme = Theme(PALETTE, scale, family, 9)
    p = PALETTE

    root.configure(bg=p.window)

    base_font = theme.font()
    # "." sets defaults for every ttk widget, so individual styles only need to
    # override what differs.
    style.configure(
        ".",
        background=p.surface,
        foreground=p.text,
        fieldbackground=p.input,
        bordercolor=p.border,
        darkcolor=p.surface,
        lightcolor=p.surface,
        troughcolor=p.input,
        selectbackground=p.accent_dim,
        selectforeground=p.text,
        focuscolor=p.accent,
        insertcolor=p.text,
        font=base_font,
    )
    style.map(
        ".",
        foreground=[("disabled", p.text_disabled)],
        background=[("disabled", p.surface)],
        fieldbackground=[("disabled", p.window)],
    )

    # -- containers ----------------------------------------------------

    style.configure("TFrame", background=p.surface)
    style.configure("Toolbar.TFrame", background=p.surface)
    style.configure("Panel.TFrame", background=p.surface)
    style.configure("Status.TFrame", background=p.surface)
    style.configure("Canvas.TFrame", background=p.canvas)
    style.configure("TSeparator", background=p.border)

    # -- text ----------------------------------------------------------

    style.configure("TLabel", background=p.surface, foreground=p.text,
                    font=base_font)
    style.configure("Title.TLabel", background=p.surface, foreground=p.text,
                    font=theme.font(13, weight="bold"))
    style.configure("Section.TLabel", background=p.surface,
                    foreground=p.text_muted,
                    font=theme.font(9, weight="bold"))
    style.configure("Hint.TLabel", background=p.surface,
                    foreground=p.text_muted)
    # Parameter readouts: bright when the value differs from the default, muted
    # when it is still neutral. The digits themselves never change size.
    style.configure("Value.TLabel", background=p.surface, foreground=p.text)
    style.configure("ValueZero.TLabel", background=p.surface,
                    foreground=p.text_muted)
    style.configure("ToolbarMaterial.TLabel", background=p.surface,
                    foreground=p.text_muted)
    style.configure("Mono.TLabel", background=p.surface,
                    foreground=p.text_muted, font=("Consolas", theme.font_size))
    style.configure("Error.TLabel", background=p.surface, foreground=p.error)
    style.configure("Ok.TLabel", background=p.surface, foreground=p.ok)

    # Status chips: a prefix glyph plus text, so state never relies on colour.
    for role, colour in (
        ("neutral", p.text_muted),
        ("running", p.accent),
        ("ok", p.ok),
        ("warn", p.warn),
        ("error", p.error),
    ):
        style.configure(
            STATUS_STYLES[role],
            background=p.surface,
            foreground=colour,
        )

    # -- buttons -------------------------------------------------------

    style.configure(
        "TButton",
        background=p.surface_alt,
        foreground=p.text,
        bordercolor=p.border,
        lightcolor=p.surface_alt,
        darkcolor=p.surface_alt,
        focuscolor=p.accent,
        padding=(theme.px(10), theme.px(4)),
        relief="flat",
    )
    style.map(
        "TButton",
        background=[
            ("pressed", p.window),
            ("active", p.surface_high),
            ("disabled", p.surface),
        ],
        foreground=[("disabled", p.text_disabled)],
        bordercolor=[("focus", p.accent)],
    )
    style.configure(
        "Accent.TButton",
        background=p.accent,
        foreground="#0c1015",
        bordercolor=p.accent,
        lightcolor=p.accent,
        darkcolor=p.accent,
    )
    style.map(
        "Accent.TButton",
        background=[
            ("pressed", "#3b74d1"),
            ("active", "#5c99ff"),
            ("disabled", p.surface_alt),
        ],
        foreground=[
            ("disabled", p.text_disabled),
            ("!disabled", "#0c1015"),
        ],
    )
    style.configure(
        "Ghost.TButton",
        background=p.surface,
        bordercolor=p.surface,
        padding=(theme.px(8), theme.px(3)),
    )
    style.map(
        "Ghost.TButton",
        background=[("active", p.surface_alt), ("pressed", p.window)],
        bordercolor=[("focus", p.accent)],
    )

    # -- fields --------------------------------------------------------

    field_options = dict(
        fieldbackground=p.input,
        background=p.input,
        foreground=p.text,
        bordercolor=p.border,
        lightcolor=p.input,
        darkcolor=p.input,
        insertcolor=p.text,
        padding=(theme.px(6), theme.px(3)),
    )
    for name in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(name, **field_options)
    style.map(
        "TEntry",
        bordercolor=[("focus", p.accent)],
        lightcolor=[("focus", p.accent)],
    )
    style.map(
        "TSpinbox",
        bordercolor=[("focus", p.accent)],
        foreground=[("disabled", p.text_disabled)],
    )
    style.map(
        "TCombobox",
        fieldbackground=[
            ("readonly", p.input),
            ("disabled", p.window),
        ],
        background=[("active", p.surface_high)],
        foreground=[("disabled", p.text_disabled)],
        bordercolor=[("focus", p.accent)],
        arrowcolor=[("disabled", p.text_disabled), ("!disabled", p.text_muted)],
    )
    # The drop-down list is a Tk listbox, not a ttk widget: colour it through
    # the option database so it does not flash a white panel.
    root.option_add("*TCombobox*Listbox.background", p.input)
    root.option_add("*TCombobox*Listbox.foreground", p.text)
    root.option_add("*TCombobox*Listbox.selectBackground", p.accent_dim)
    root.option_add("*TCombobox*Listbox.selectForeground", p.text)

    # -- toggles -------------------------------------------------------

    for name in ("TCheckbutton", "TRadiobutton"):
        style.configure(
            name,
            background=p.surface,
            foreground=p.text,
            indicatorbackground=p.input,
            indicatorforeground=p.accent,
            upperbordercolor=p.border_strong,
            lowerbordercolor=p.input,
            focuscolor=p.accent,
            padding=(theme.px(2), theme.px(2)),
        )
        style.map(
            name,
            background=[("active", p.surface)],
            foreground=[("disabled", p.text_disabled)],
            indicatorbackground=[
                ("selected", p.accent),
                ("disabled", p.surface_alt),
            ],
            indicatorforeground=[("selected", "#0c1015")],
        )

    # -- sliders -------------------------------------------------------

    style.configure(
        "TScale",
        background=p.text_muted,
        troughcolor=p.input,
        bordercolor=p.border,
        lightcolor=p.text_muted,
        darkcolor=p.text_muted,
        gripcount=0,
    )
    style.map(
        "TScale",
        background=[
            ("disabled", p.text_disabled),
            ("active", p.accent),
            ("!disabled", p.text_muted),
        ],
        troughcolor=[("disabled", p.window)],
    )

    # -- scrollbars ----------------------------------------------------

    style.configure(
        "TScrollbar",
        background=p.surface_high,
        troughcolor=p.window,
        bordercolor=p.window,
        arrowcolor=p.text_muted,
        lightcolor=p.surface_high,
        darkcolor=p.surface_high,
    )
    style.map(
        "TScrollbar",
        background=[("active", p.border_strong), ("pressed", p.accent)],
        arrowcolor=[("disabled", p.text_disabled)],
    )

    # -- notebook ------------------------------------------------------

    style.configure("TNotebook", background=p.surface, borderwidth=0,
                    tabmargins=(0, theme.px(2), 0, 0))
    style.configure(
        "TNotebook.Tab",
        background=p.surface,
        foreground=p.text_muted,
        padding=(theme.px(16), theme.px(4)),
        bordercolor=p.border,
        lightcolor=p.surface,
        darkcolor=p.surface,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", p.surface_alt), ("active", p.surface_alt)],
        foreground=[("selected", p.text), ("!selected", p.text_muted)],
        expand=[("selected", (0, 0, 0, 0)), ("!selected", (0, 0, 0, 0))],
    )

    # -- lists ---------------------------------------------------------

    style.configure(
        "Treeview",
        background=p.surface_alt,
        fieldbackground=p.surface_alt,
        foreground=p.text,
        bordercolor=p.border,
        lightcolor=p.surface_alt,
        darkcolor=p.surface_alt,
        rowheight=theme.px(24),
    )
    style.map(
        "Treeview",
        background=[("selected", p.accent_dim)],
        foreground=[("selected", p.text)],
    )
    style.configure(
        "Treeview.Heading",
        background=p.surface,
        foreground=p.text_muted,
        bordercolor=p.border,
        lightcolor=p.surface,
        darkcolor=p.surface,
        padding=(theme.px(6), theme.px(4)),
        font=theme.font(9, weight="bold"),
        relief="flat",
    )
    style.map(
        "Treeview.Heading",
        background=[("active", p.surface_high)],
        foreground=[("active", p.text)],
    )

    root.option_add("*TCombobox*Listbox.font", base_font)
    return theme


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio between two ``#rrggbb`` colours.

    Used by the theme check to prove that body text and status colours stay
    readable on every surface, instead of trusting the eye.
    """

    def luminance(colour: str) -> float:
        colour = colour.lstrip("#")
        channels = [int(colour[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]

        def linear(value: float) -> float:
            return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

        r, g, b = (linear(c) for c in channels)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    light, dark = sorted(
        (luminance(foreground), luminance(background)), reverse=True
    )
    return (light + 0.05) / (dark + 0.05)
