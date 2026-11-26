"""Capture the running app window (DPI-aware) for visual verification."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab

OUT = Path(__file__).resolve().parent / "app-live.png"
TITLE_HINT = "AI 调色"


def window_rect(pid: int) -> tuple[int, int, int, int] | None:
    user32 = ctypes.windll.user32
    best: tuple[int, int, int, int] | None = None
    best_area = 0

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _lparam):
        nonlocal best, best_area
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid or not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        if TITLE_HINT not in buffer.value:
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        area = (rect.right - rect.left) * (rect.bottom - rect.top)
        if area > best_area:
            best_area = area
            best = (rect.left, rect.top, rect.right, rect.bottom)
        return True

    user32.EnumWindows(callback, 0)
    return best


def main() -> int:
    # Make this process DPI-aware first, so GetWindowRect returns physical
    # pixels that line up with what ImageGrab captures.
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()

    pid = int(sys.argv[1])
    box = window_rect(pid)
    if box is None:
        print("no window")
        return 1

    shot = ImageGrab.grab()
    left, top, right, bottom = box
    crop = (
        max(0, left),
        max(0, top),
        min(shot.size[0], right),
        min(shot.size[1], bottom),
    )
    image = shot.crop(crop)
    image.save(OUT)
    print("rect", box, "crop", crop, "image", image.size, "png", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
