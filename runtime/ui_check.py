"""Ad-hoc GUI check: load an image, render, exercise new widgets, screenshot."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

import tkinter as tk
from PIL import Image, ImageGrab

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.ui import ColorApp  # noqa: E402

OUT = ROOT_DIR / "runtime" / "ui-check.png"
IMAGE = ROOT_DIR / "runtime" / "test-fixtures" / "scene.jpg"


def main() -> int:
    root = tk.Tk()
    app = ColorApp(root)
    errors: list[str] = []

    def guard(label, fn):
        def wrapper():
            try:
                fn()
            except Exception:
                errors.append(f"{label}: {traceback.format_exc()}")

        return wrapper

    def step_load():
        app.load_path(IMAGE)
        app.ai_text.insert("1.0", "电影感，阴影偏青")

    def step_preset():
        app.apply_preset("cinematic")

    def step_expand():
        # Exercise every slider once, including the split-tone page.
        for key in ("whites", "blacks", "vibrance", "hue"):
            app._on_param_slider(key, "60")
        app.param_notebook.select(1)
        for key in ("split_shadow_hue", "split_shadow_amount",
                    "split_highlight_hue", "split_highlight_amount",
                    "split_balance"):
            app._on_param_slider(key, "120" if key.endswith("hue") else "40")

    def step_style_chip():
        app._apply_style_preset("film")
        app._apply_style_preset("mono")

    def grab_window(name: str) -> None:
        root.update()
        # The process is DPI-unaware on a 200% display: Tk reports logical
        # pixels while ImageGrab expects physical pixels, so scale the bbox and
        # downsample back to logical size for a crisp full-window capture.
        shot = ImageGrab.grab()
        scale = shot.size[0] / root.winfo_screenwidth()
        x, y = root.winfo_rootx(), root.winfo_rooty()
        w, h = root.winfo_width(), root.winfo_height()
        box = (int(x * scale), int(y * scale),
               int((x + w) * scale), int((y + h) * scale))
        image = shot.crop(box)
        if scale > 1.0:
            image = image.resize((w, h), Image.LANCZOS)
        image.save(ROOT_DIR / "runtime" / name)

    def step_shot():
        root.lift()
        root.attributes("-topmost", True)
        root.update()
        grab_window("ui-check.png")
        print("SIZE", root.winfo_width(), root.winfo_height())
        print("HIST", app._hist_current is not None, app._hist_size)
        print("SUMMARY", app.summary_var.get())
        print("SCALES", len(app.param_scales))
        print("HIST_Y", app.hist_label.winfo_rooty() - root.winfo_rooty(),
              app.hist_label.winfo_height(),
              "CANVAS_Y", app.canvas.winfo_rooty() - root.winfo_rooty(),
              app.canvas.winfo_height(),
              "SIDEBAR_X", app.sidebar_canvas.winfo_rootx() - root.winfo_rootx(),
              app.sidebar_canvas.winfo_width())

    def step_shot_split():
        app.param_notebook.select(1)
        root.update()
        grab_window("ui-check-split.png")
        print("SPLIT_HIST", app._hist_size)

    sequence = [
        (300, step_load),
        (700, step_style_chip),
        (1000, step_preset),
        (3000, step_shot),
        (3300, step_expand),
        (4000, step_shot_split),
        (4300, root.destroy),
    ]
    for delay, fn in sequence:
        root.after(delay, guard(fn.__name__, fn))

    try:
        root.mainloop()
    except Exception:
        traceback.print_exc()
        return 2
    if errors:
        print("\n".join(errors))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
