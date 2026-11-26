"""Layout sanity checks for the redesigned sidebar and histogram strip."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app.ui import ColorApp  # noqa: E402


def main() -> int:
    root = tk.Tk()
    app = ColorApp(root)

    def check():
        root.update_idletasks()
        app.load_path(ROOT_DIR / "runtime" / "test-fixtures" / "scene.jpg")
        root.update_idletasks()
        root.update()
        app.load_path(ROOT_DIR / "runtime" / "test-fixtures" / "scene.jpg")
        for _ in range(40):
            root.update()
            if app._hist_current is not None:
                break

        print("window", root.winfo_width(), root.winfo_height())
        print("hist_label", app.hist_label.winfo_width(), app.hist_label.winfo_height())
        print("canvas", app.canvas.winfo_width(), app.canvas.winfo_height())
        print("sidebar_canvas", app.sidebar_canvas.winfo_width(),
              app.sidebar_canvas.winfo_height())
        bbox = app.sidebar_canvas.bbox("all")
        print("sidebar_inner_bbox", bbox)
        print("tabs", app.param_notebook.tabs())
        page = app.param_notebook.nametowidget(app.param_notebook.tabs()[0])
        print("page0 size", page.winfo_width(), page.winfo_height())
        overflow = []
        for child in page.winfo_children():
            bottom = child.winfo_y() + child.winfo_height()
            if bottom > page.winfo_height() + 1:
                overflow.append((str(child), child.winfo_y(), child.winfo_height()))
        print("page0_overflow", overflow[:5], "count", len(overflow))
        print("strength y", app.strength_scale.winfo_rooty() - root.winfo_rooty())
        print("summary y", app.summary_var is not None)
        print("hist_size", app._hist_size, "holder",
              app.hist_holder.winfo_width(), app.hist_holder.winfo_height())
        print("hist_photo", app._hist_photo is not None,
              getattr(app._hist_photo, "width", lambda: 0)(),
              getattr(app._hist_photo, "height", lambda: 0)())
        print("canvas_bottom", app.canvas.winfo_rooty() - root.winfo_rooty()
              + app.canvas.winfo_height(),
              "hist_top", app.hist_holder.winfo_rooty() - root.winfo_rooty(),
              "hist_bottom", app.hist_holder.winfo_rooty() - root.winfo_rooty()
              + app.hist_holder.winfo_height(),
              "bottom_top", app.compare_group.winfo_rooty() - root.winfo_rooty())
        root.destroy()

    root.after(200, check)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
