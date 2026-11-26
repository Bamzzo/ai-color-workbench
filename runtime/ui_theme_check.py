"""Theme, contrast and responsive-layout checks for the dark workbench UI.

Run at the default scale, then with ``--scale 1.25`` / ``--scale 1.5`` to
simulate 125% / 150% Windows display scaling. Tk expresses display scaling as
``tk scaling`` (pixels per point), so the check sets that before building the
app and shadows ``winfo_fpixels("1i")`` to report the simulated dpi. That makes
the app compute the same geometry, padding and column widths it would use on a
real 125%/150% display.

Each run prints measurements, asserts the layout invariants, and saves a PNG of
the main window and the batch window under ``runtime/screenshots``.

Usage:
    python runtime/ui_theme_check.py [--scale 1.25] [--no-shots]
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from tkinter import ttk

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app import theme as theme_mod  # noqa: E402
from app.ui import ColorApp  # noqa: E402

FIXTURES = ROOT_DIR / "runtime" / "test-fixtures"
SHOTS = ROOT_DIR / "runtime" / "screenshots"


# ----------------------------------------------------------------------
# screenshot (PrintWindow, works even when the window is not focused)
# ----------------------------------------------------------------------


class _BitmapInfoHeader(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class _BitmapInfo(ctypes.Structure):
    _fields_ = [("bmiHeader", _BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 3)]


def capture(window: tk.Misc, path: Path) -> tuple[int, int] | None:
    from PIL import Image

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hwnd = user32.GetAncestor(window.winfo_id(), 2)  # GA_ROOT
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None
    hdc = user32.GetWindowDC(hwnd)
    mem_dc = gdi32.CreateCompatibleDC(hdc)
    bitmap = gdi32.CreateCompatibleBitmap(hdc, width, height)
    gdi32.SelectObject(mem_dc, bitmap)
    user32.PrintWindow(hwnd, mem_dc, 2)
    info = _BitmapInfo()
    info.bmiHeader.biSize = ctypes.sizeof(_BitmapInfoHeader)
    info.bmiHeader.biWidth = width
    info.bmiHeader.biHeight = -height  # top-down
    info.bmiHeader.biPlanes = 1
    info.bmiHeader.biBitCount = 32
    info.bmiHeader.biCompression = 0
    buffer = ctypes.create_string_buffer(width * height * 4)
    gdi32.GetDIBits(mem_dc, bitmap, 0, height, buffer, ctypes.byref(info), 0)
    image = Image.frombuffer("RGB", (width, height), buffer, "raw", "BGRX", 0, 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem_dc)
    user32.ReleaseDC(hwnd, hdc)
    return width, height


# ----------------------------------------------------------------------
# checks
# ----------------------------------------------------------------------


def check_contrast(failures: list[str]) -> None:
    p = theme_mod.PALETTE
    pairs = [
        ("正文/面板", p.text, p.surface, 7.0),
        ("正文/输入框", p.text, p.input, 7.0),
        ("次要文字/面板", p.text_muted, p.surface, 4.5),
        ("次要文字/预览底", p.text_muted, p.canvas, 4.5),
        ("强调/面板", p.accent, p.surface, 3.0),
        ("成功/面板", p.ok, p.surface, 4.5),
        ("警告/面板", p.warn, p.surface, 4.5),
        ("错误/面板", p.error, p.surface, 4.5),
    ]
    print("-- contrast --")
    for label, fg, bg, minimum in pairs:
        ratio = theme_mod.contrast_ratio(fg, bg)
        print(f"{label}: {fg} on {bg} = {ratio:.2f} (min {minimum})")
        if ratio < minimum:
            failures.append(f"contrast {label} {ratio:.2f} < {minimum}")


def toolbar_overlap(toolbar: tk.Misc) -> tuple[str, str] | None:
    children = [c for c in toolbar.winfo_children() if c.winfo_width() > 1]
    for index, first in enumerate(children):
        fx, fw = first.winfo_x(), first.winfo_width()
        for second in children[index + 1:]:
            sx, sw = second.winfo_x(), second.winfo_width()
            if fx < sx + sw and sx < fx + fw:
                return (
                    f"{first.winfo_class()}:{first.cget('text') if first.winfo_class() != 'TSeparator' else ''}",
                    f"{second.winfo_class()}:{second.cget('text') if second.winfo_class() != 'TSeparator' else ''}",
                )
    return None


def check_keyboard(app: ColorApp, failures: list[str]) -> None:
    """Focus visibility and a usable Tab order, without simulating typing."""
    style = ttk.Style(app.root)
    for name in ("TButton", "TEntry", "TCombobox"):
        states = [state for state, _value in style.map(name, "bordercolor")]
        if "focus" not in states:
            failures.append(f"{name} has no visible focus colour")
    disabled = [state for state, _value in style.map("TButton", "foreground")]
    if "disabled" not in disabled:
        failures.append("TButton does not visually distinguish disabled state")

    order: list[str] = []
    widget = app.open_btn
    widget.focus_set()
    app.root.update()
    for _ in range(10):
        current = app.root.focus_get()
        if current is None:
            break
        order.append(str(current))
        nxt = app.root.tk.call("tk_focusNext", str(current))
        if not nxt or str(nxt) == str(current) or str(nxt) in order:
            break
        app.root.nametowidget(nxt).focus_set()
        app.root.update()
    print("tab order (first 10)", order)
    if len(order) < 4:
        failures.append(f"tab order stalls after {len(order)} stops")


def check_main(app: ColorApp, failures: list[str]) -> None:
    root = app.root
    root.update_idletasks()
    root.update()
    print("-- main window --")
    print("scale", app._dpi_scale(), "window", root.winfo_width(), root.winfo_height())
    print("toolbar children",
          [(str(c.winfo_class()), c.winfo_width()) for c in app.open_btn.master.winfo_children()])

    toolbar = app.open_btn.master
    right_edge = max(
        (c.winfo_x() + c.winfo_width() for c in toolbar.winfo_children()),
        default=0,
    )
    print("toolbar content edge", right_edge, "of", toolbar.winfo_width())
    if right_edge > toolbar.winfo_width():
        failures.append(
            f"toolbar content {right_edge} exceeds width {toolbar.winfo_width()}"
        )
    intersection = toolbar_overlap(toolbar)
    if intersection is not None:
        failures.append(f"toolbar widgets overlap: {intersection}")
    if app.batch_btn.winfo_width() <= 1 or app.export_lut_btn.winfo_width() <= 1:
        failures.append("toolbar buttons collapsed")
    if app.material_label.winfo_width() <= 1 or app.worker_badge.winfo_width() <= 1:
        failures.append("material label or engine badge collapsed")

    canvas_h = app.canvas.winfo_height()
    print("canvas", app.canvas.winfo_width(), canvas_h,
          "hist", app.hist_holder.winfo_width(), app.hist_holder.winfo_height())
    if canvas_h < 200:
        failures.append(f"preview canvas too short: {canvas_h}")

    hist_bottom = app.hist_holder.winfo_rooty() + app.hist_holder.winfo_height()
    compare_top = app.compare_group.winfo_rooty()
    print("hist_bottom", hist_bottom, "compare_top", compare_top)
    if hist_bottom > compare_top:
        failures.append("histogram overlaps the compare bar")

    bbox = app.sidebar_canvas.bbox("all")
    print("sidebar canvas", app.sidebar_canvas.winfo_width(),
          app.sidebar_canvas.winfo_height(), "content", bbox)
    if bbox is None or bbox[3] <= app.sidebar_canvas.winfo_height():
        failures.append("sidebar is not scrollable at this size")
    if bbox is not None and bbox[2] > app.sidebar_canvas.winfo_width() + 1:
        failures.append("sidebar content is wider than its canvas")

    chips = [app.preview_chip, app.ai_chip, app.export_chip, app.batch_chip]
    for chip in chips:
        if chip.winfo_width() <= 1 or chip.winfo_height() <= 1:
            failures.append(f"status chip hidden: {chip.cget('text')}")
    print("chips", [(c.cget("text"), c.winfo_width()) for c in chips])
    print("message", app.message_label.cget("style"),
          "busy", app.busy_label.cget("style"))

    page = app.param_notebook.nametowidget(app.param_notebook.tabs()[0])
    overflow = []
    for child in page.winfo_children():
        bottom = child.winfo_y() + child.winfo_height()
        if bottom > page.winfo_height() + 1:
            overflow.append((str(child), child.winfo_y(), child.winfo_height()))
    print("param page overflow", len(overflow))
    if overflow:
        failures.append(f"parameter rows overflow the page: {overflow[:3]}")

    # A changed parameter brightens its readout; returning to the default dims
    # it again. The mapping must survive regardless of which tab is visible.
    app._on_param_slider("exposure_ev", 0.5)
    changed_style = app._param_value_labels["exposure_ev"].cget("style")
    app._on_param_slider("exposure_ev", 0.0)
    default_style = app._param_value_labels["exposure_ev"].cget("style")
    print("value style changed/default", changed_style, default_style)
    if changed_style != "Value.TLabel" or default_style != "ValueZero.TLabel":
        failures.append(
            f"parameter value styles did not track edits: {changed_style}/{default_style}"
        )

    app.sidebar_canvas.yview_moveto(1.0)
    root.update_idletasks()
    bottom_y = app.summary_var is not None and app.strength_scale.winfo_rooty()
    print("sidebar scrolled to bottom, strength screen y", bottom_y)
    app.sidebar_canvas.yview_moveto(0.0)
    root.update_idletasks()

    # -- long Chinese name: elided label, full path still reachable ----
    long_dir = ROOT_DIR / "runtime" / "cache" / "ui-theme-long"
    long_dir.mkdir(parents=True, exist_ok=True)
    long_name = (
        "这是一个很长很长的中文素材文件名用于验证工具栏截断与完整路径提示_2026.png"
    )
    long_path = long_dir / long_name
    if not long_path.is_file():
        long_path.write_bytes((FIXTURES / "scene.jpg").read_bytes())
    app.load_path(long_path)
    for _ in range(120):
        root.update()
        if app._last_render_ms is not None:
            break
    label_text = app.material_label.cget("text")
    print("material label", label_text, len(label_text))
    if len(label_text) > 40:
        failures.append(f"material label not elided: {len(label_text)} chars")
    if app.material_tip.text != str(long_path):
        failures.append("material tooltip does not hold the full path")
    if toolbar_overlap(toolbar) is not None:
        failures.append("long material name broke the toolbar layout")
    if long_name not in app.root.title():
        failures.append("window title lost the full file name")

    # -- minimum window size ------------------------------------------
    normal_size = (root.winfo_width(), root.winfo_height())
    min_w, min_h = root.minsize()
    root.geometry(f"{int(min_w)}x{int(min_h)}")
    for _ in range(6):
        root.update_idletasks()
        root.update()
    print("min size window", root.winfo_width(), root.winfo_height())
    if toolbar_overlap(toolbar) is not None:
        failures.append("toolbar overlaps at the minimum window size")
    if app.hist_holder.winfo_rooty() + app.hist_holder.winfo_height() > (
        root.winfo_rooty() + root.winfo_height() + 1
    ):
        failures.append("histogram clipped at the minimum window size")
    for chip in (app.preview_chip, app.ai_chip, app.export_chip, app.batch_chip):
        if not chip.winfo_ismapped() or chip.winfo_width() <= 1:
            failures.append(f"status chip hidden at minimum size: {chip.cget('text')}")
    if app.canvas.winfo_height() < 180:
        failures.append("preview canvas collapsed at the minimum window size")

    check_keyboard(app, failures)

    # Leave the window back at its normal size for the screenshot.
    root.geometry(f"{normal_size[0]}x{normal_size[1]}")
    for _ in range(8):
        root.update_idletasks()
        root.update()


def check_batch(app: ColorApp, failures: list[str]) -> tk.Toplevel | None:
    app.open_batch_window()
    window = app._batch_window
    if window is None:
        failures.append("batch window did not open")
        return None
    window.geometry(
        f"{int(round(860 * window._ui_scale))}x{int(round(520 * window._ui_scale))}"
    )
    window.add_paths([FIXTURES / "scene.jpg", FIXTURES / "pattern.png"])
    window.set_output_dir(ROOT_DIR / "runtime" / "cache" / "theme-check-out")
    for _ in range(40):
        window.update()
        if all(k in window._meta for k in window._rows):
            break
    window.update_idletasks()
    window.update()

    print("-- batch window (min size) --")
    print("window", window.winfo_width(), window.winfo_height(),
          "tree", window.tree.winfo_width(), window.tree.winfo_height())
    if window.tree.winfo_height() < 100:
        failures.append("batch tree too short at 860x520")

    for button in (
        window.start_btn, window.cancel_current_btn, window.cancel_pending_btn,
        window.cancel_all_btn, window.add_btn, window.retry_btn,
    ):
        bottom = button.winfo_rooty() + button.winfo_height()
        right = button.winfo_rootx() + button.winfo_width()
        window_bottom = window.winfo_rooty() + window.winfo_height()
        window_right = window.winfo_rootx() + window.winfo_width()
        if bottom > window_bottom or right > window_right:
            failures.append(
                f"batch button clipped: {button.cget('text')} "
                f"({right},{bottom}) vs ({window_right},{window_bottom})"
            )

    if window._row_height < window._thumb_side:
        failures.append("tree row height is smaller than the thumbnail")

    columns = sum(
        int(window.tree.column(column, "width"))
        for column in ("#0", "name", "kind", "params", "info", "status", "progress", "note")
    )
    print("columns total", columns, "tree width", window.tree.winfo_width())
    if window.tree.winfo_width() < 200:
        failures.append("batch tree collapsed")

    statuses = [window.tree.set(iid, "status") for iid in window.tree.get_children()]
    print("rows", len(statuses), "statuses", statuses)
    if not all(statuses):
        failures.append("batch rows are missing status text")
    names = [window.tree.set(iid, "name") for iid in window.tree.get_children()]
    if not all(names):
        failures.append("batch rows are missing material names")
    return window


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--no-shots", action="store_true")
    args = parser.parse_args()

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()

    failures: list[str] = []
    root = tk.Tk()
    # Simulate the requested display scale before any widget is built.
    root.tk.call("tk", "scaling", 96.0 * args.scale / 72.0)
    original_fpixels = root.winfo_fpixels
    root.winfo_fpixels = lambda value: (
        96.0 * args.scale if value == "1i" else original_fpixels(value)
    )

    app = ColorApp(root)

    def run() -> None:
        window = None
        try:
            root.update_idletasks()
            root.update()
            app.load_path(FIXTURES / "scene.jpg")
            for _ in range(80):
                root.update()
                if app._last_render_ms is not None:
                    break
            root.update_idletasks()
            root.update()

            check_contrast(failures)
            check_main(app, failures)
            app.load_path(FIXTURES / "scene.jpg")
            for _ in range(120):
                root.update()
                if app._last_render_ms is not None:
                    break
            window = check_batch(app, failures)

            if not args.no_shots:
                suffix = f"{int(round(args.scale * 100))}"
                main_shot = SHOTS / f"main-{suffix}.png"
                print("shot", capture(root, main_shot), main_shot)
                if window is not None:
                    batch_shot = SHOTS / f"batch-{suffix}.png"
                    print("shot", capture(window, batch_shot), batch_shot)
        except Exception as exc:  # never leave a modal-less app running
            import traceback

            traceback.print_exc()
            failures.append(f"check crashed: {type(exc).__name__}: {exc}")
        finally:
            try:
                if window is not None:
                    window.close()
            except Exception:
                pass
            try:
                root.destroy()
            except tk.TclError:
                pass

    root.after(300, run)
    root.mainloop()

    if failures:
        print("\nFAILED")
        for item in failures:
            print(" -", item)
        return 1
    print("\nOK: contrast, layout, sidebar scroll and batch rows verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
