"""Application entry point."""

from __future__ import annotations

import ctypes
import logging
import sys
import tkinter as tk
from pathlib import Path

if __package__ in (None, ""):
    # Allow `python app/main.py` from the project root as well as -m app.main.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import paths  # noqa: E402
from app.ui import ColorApp  # noqa: E402


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _configure_logging() -> None:
    try:
        paths.LOGS.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(
            paths.LOGS / "app.log", encoding="utf-8"
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)
    except Exception:
        logging.basicConfig(level=logging.INFO)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    smoke = "--smoke" in argv
    smoke_image = None
    if "--smoke-image" in argv:
        index = argv.index("--smoke-image")
        if index + 1 < len(argv):
            smoke_image = Path(argv[index + 1])
    startup_image = smoke_image
    if "--image" in argv:
        index = argv.index("--image")
        if index + 1 < len(argv):
            startup_image = Path(argv[index + 1])

    _enable_dpi_awareness()
    _configure_logging()

    root = tk.Tk()
    app = ColorApp(root)
    if startup_image is not None:
        root.after(100, lambda: app.load_path(startup_image))

    if smoke:
        # Exercises window creation, layout, canvas draw and teardown without
        # requiring manual interaction. P0 GUI acceptance still needs a human.
        def _finish_smoke() -> None:
            try:
                root.update_idletasks()
                root.update()
            finally:
                app.close()

        root.after(1200 if smoke_image is not None else 500, _finish_smoke)

    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
