"""End-to-end check: an export must survive a slider drag that queues a preview.

Before the FIFO fix the preview submission replaced the pending export and the
file was never written, with no error shown. This drives the real UI wiring:
export is requested, then a debounced preview fires while the export is still
waiting for the worker.
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
OTHER = ROOT_DIR / "runtime" / "test-fixtures" / "pattern.png"
TARGET = ROOT_DIR / "runtime" / "export-queue-check.png"


def main() -> int:
    root = tk.Tk()
    app = ColorApp(root)
    failures: list[str] = []

    def pump(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)

    def step() -> None:
        app.load_path(IMAGE)
        for _ in range(400):
            root.update()
            if app._processed_preview is not None:
                break
            time.sleep(0.01)

        # 1. Queue an export, then let the debounced preview fire behind it.
        with mock.patch.object(
            ui.filedialog, "asksaveasfilename", return_value=str(TARGET)
        ):
            app.export_image()
        app._on_param_slider("exposure_ev", "0.4")
        print("after submit:", app.busy_var.get())

        # 1b. A switch request while the export is outstanding must be refused,
        # and it must not disturb the document that owns the export.
        document_before = app.state.document_id
        source_before = app.state.source.path
        with mock.patch.object(ui.messagebox, "showwarning") as warn:
            app.load_path(OTHER)
        print("blocked switch:", app.message_var.get())
        if app.state.document_id != document_before:
            failures.append("document changed while an export was outstanding")
        if app.state.source.path != source_before:
            failures.append("source changed while an export was outstanding")
        if not warn.called:
            failures.append("blocked switch did not warn the user")
        if "暂时无法切换" not in app.message_var.get():
            failures.append("blocked switch did not explain itself")

        # 2. A second slider move while both are queued must not displace it.
        pump(0.30)
        app._on_param_slider("contrast", "30")
        print("mid-flight:", app.busy_var.get())

        deadline = time.monotonic() + 90.0
        while time.monotonic() < deadline:
            pump(0.1)
            if TARGET.exists() and not app.runner.is_busy():
                break

        print("busy at end:", repr(app.busy_var.get()))
        print("message:", app.message_var.get())
        if not TARGET.exists():
            failures.append("export file was never written")
        else:
            size = TARGET.stat().st_size
            print(f"export size: {size / 1e6:.1f} MB")
            if size < 1000:
                failures.append("export file is suspiciously small")
            TARGET.unlink(missing_ok=True)
        if app.runner.is_busy():
            failures.append("runner still busy after export")

        # 3. Once the export reported back, the same switch must be allowed.
        app.load_path(OTHER)
        print("switch after export:", app.state.source.path.name)
        if app.state.source.path != OTHER:
            failures.append("switch stayed blocked after the export finished")
        root.destroy()

    root.after(200, step)
    root.mainloop()
    if failures:
        for item in failures:
            print("FAIL:", item)
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
