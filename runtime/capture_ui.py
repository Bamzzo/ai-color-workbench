"""Capture the real on-screen appearance of the main and batch windows.

``ui_theme_check.py`` captures with PrintWindow, which cannot see the DWM
caption. This script raises each window for a moment and grabs the screen
rectangle, so the delivered screenshots include the dark title bar exactly as
the user sees it.

Usage: python runtime/capture_ui.py [--tag live]
"""

from __future__ import annotations

import argparse
import ctypes
import sys
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from PIL import ImageGrab  # noqa: E402

from app.ui import ColorApp  # noqa: E402

FIXTURES = ROOT_DIR / "runtime" / "test-fixtures"
SHOTS = ROOT_DIR / "runtime" / "screenshots"


def grab_window(window: tk.Misc, path: Path) -> tuple[int, int]:
    window.update_idletasks()
    window.update()
    user32 = ctypes.windll.user32
    hwnd = user32.GetAncestor(window.winfo_id(), 2)
    try:
        window.attributes("-topmost", True)
    except tk.TclError:
        pass
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    window.update()
    time.sleep(0.9)
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    shot = ImageGrab.grab(all_screens=True)
    image = shot.crop((rect.left, rect.top, rect.right, rect.bottom))
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    try:
        window.attributes("-topmost", False)
    except tk.TclError:
        pass
    return image.size


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="live")
    args = parser.parse_args()

    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()

    root = tk.Tk()
    app = ColorApp(root)
    result = {"code": 0}

    def run() -> None:
        try:
            app.load_path(FIXTURES / "scene.jpg")
            for _ in range(120):
                root.update()
                if app._last_render_ms is not None:
                    break
            main_path = SHOTS / f"main-{args.tag}.png"
            print("main", grab_window(root, main_path), main_path)

            app.open_batch_window()
            window = app._batch_window
            if window is None:
                result["code"] = 1
                return
            window.add_paths(
                [FIXTURES / "scene.jpg", FIXTURES / "pattern.png"]
            )
            window.set_output_dir(ROOT_DIR / "runtime" / "cache" / "capture-out")
            for _ in range(60):
                window.update()
                if len(window._meta) >= 2:
                    break
            batch_path = SHOTS / f"batch-{args.tag}.png"
            print("batch", grab_window(window, batch_path), batch_path)
            window.close()
        finally:
            app.close()

    root.after(400, run)
    root.mainloop()
    return result["code"]


if __name__ == "__main__":
    raise SystemExit(main())
