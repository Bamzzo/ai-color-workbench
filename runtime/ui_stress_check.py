"""Stress the interaction paths that only show up with a real worker.

Phases:
  1. load, wait for the first preview
  2. request an export, then keep dragging sliders while it is queued/running
  3. queue an image export and a LUT export behind a running preview
  4. close the window while an export is still running

Assertions are printed as PASS/FAIL lines; the process exits non-zero on failure.
"""

from __future__ import annotations

import sys
import time
import tkinter as tk
from pathlib import Path
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app import ui  # noqa: E402
from app.ui import ColorApp  # noqa: E402

IMAGE = ROOT_DIR / "runtime" / "test-fixtures" / "scene.jpg"
OUT_DIR = ROOT_DIR / "runtime"
failures: list[str] = []


def check(condition: bool, label: str, detail: str = "") -> None:
    if condition:
        print(f"PASS {label}")
    else:
        failures.append(label)
        print(f"FAIL {label} {detail}".rstrip())


def main() -> int:
    root = tk.Tk()
    app = ColorApp(root)

    def pump(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)

    def wait_for(predicate, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            pump(0.05)
        return predicate()

    def export_image(target: Path) -> None:
        with mock.patch.object(
            ui.filedialog, "asksaveasfilename", return_value=str(target)
        ):
            app.export_image()

    def export_lut(target: Path) -> None:
        with mock.patch.object(
            ui.filedialog, "asksaveasfilename", return_value=str(target)
        ):
            app.export_lut()

    def phase_1() -> None:
        app.load_path(IMAGE)
        ok = wait_for(lambda: app._processed_preview is not None, 60.0)
        check(ok, "phase1 first preview arrives", app.message_var.get())
        check(
            app.state.source is not None and app.state.source.width > 0,
            "phase1 source loaded",
        )

    def phase_2() -> None:
        target = OUT_DIR / "stress-a.png"
        target.unlink(missing_ok=True)
        export_image(target)
        busy_after_submit = app.busy_var.get()
        check("正在导出图片" in busy_after_submit, "phase2 export reported", busy_after_submit)

        # Keep editing while the export waits for / runs on the worker.
        for index, value in enumerate(("0.5", "0.9", "-0.4", "0.2")):
            app._on_param_slider("exposure_ev", value)
            pump(0.06)
        deadline = wait_for(
            lambda: target.exists()
            and not app.runner.is_busy()
            and app.state.busy_revision is None,
            120.0,
        )
        check(deadline, "phase2 export completed", app.message_var.get())
        check(target.exists() and target.stat().st_size > 1000, "phase2 file written")
        check(
            "正在导出" not in app.busy_var.get(),
            "phase2 export notice retired",
            app.busy_var.get(),
        )
        check(
            app._export_tickets == [],
            "phase2 no stale export tickets",
            str(app._export_tickets),
        )
        target.unlink(missing_ok=True)

    def phase_3() -> None:
        img_a = OUT_DIR / "stress-b.png"
        img_b = OUT_DIR / "stress-c.png"
        lut = OUT_DIR / "stress-d.cube"
        for path in (img_a, img_b, lut):
            path.unlink(missing_ok=True)

        # Force a preview to be in flight, then queue two exports behind it.
        app._on_param_slider("contrast", "24")
        pump(0.02)
        export_image(img_a)
        export_lut(lut)
        export_image(img_b)
        check(
            len(app._export_tickets) == 3,
            "phase3 three exports tracked",
            str(app._export_tickets),
        )
        text = app.busy_var.get()
        check("正在导出" in text, "phase3 busy shows export", text)

        ok = wait_for(
            lambda: all(p.exists() for p in (img_a, img_b, lut))
            and not app.runner.is_busy(),
            180.0,
        )
        check(ok, "phase3 all three exports finished", app.message_var.get())
        for path in (img_a, img_b, lut):
            check(path.exists() and path.stat().st_size > 200, f"phase3 {path.name}")
        check("导出完成" in app.message_var.get(), "phase3 completion message",
              app.message_var.get())
        for path in (img_a, img_b, lut, Path(str(lut) + ".strength.json")):
            path.unlink(missing_ok=True)

    def phase_4() -> None:
        target = OUT_DIR / "stress-e.png"
        target.unlink(missing_ok=True)
        app._on_param_slider("saturation", "30")
        pump(0.02)
        export_image(target)
        pump(0.15)
        started = time.monotonic()
        app.close()
        elapsed = time.monotonic() - started
        check(elapsed < 12.0, "phase4 close is prompt", f"{elapsed:.1f}s")
        print(f"phase4 close took {elapsed:.2f}s; partial file: {target.exists()}")
        target.unlink(missing_ok=True)

    try:
        # Phases run sequentially; pump() drives the Tk event loop inside each.
        phase_1()
        phase_2()
        phase_3()
        phase_4()
        root.mainloop()
    except tk.TclError:
        pass

    if failures:
        print("FAILURES:", len(failures))
        for item in failures:
            print(" -", item)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
