"""Bring the app window to the front and capture it."""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PIL import ImageGrab

OUT = Path(__file__).resolve().parent / "app-live.png"
TITLE_HINT = "AI 调色"

SW_RESTORE = 9


def find_window(pid: int) -> int | None:
    user32 = ctypes.windll.user32
    best = None
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
            best = int(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    return best


def main() -> int:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()

    pid = int(sys.argv[1])
    hwnd = find_window(pid)
    if hwnd is None:
        print("no window")
        return 1

    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    user32.BringWindowToTop(hwnd)
    time.sleep(1.2)

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    shot = ImageGrab.grab()
    crop = (
        max(0, rect.left),
        max(0, rect.top),
        min(shot.size[0], rect.right),
        min(shot.size[1], rect.bottom),
    )
    image = shot.crop(crop)
    image.save(OUT)
    print("rect", (rect.left, rect.top, rect.right, rect.bottom),
          "image", image.size, "saved", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
