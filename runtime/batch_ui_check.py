"""End-to-end check for the batch window (real Tk + real engine + ffmpeg).

Covers: multi-import with thumbnails, a mixed run, the main-window interlock,
duplicate rejection, cancel-pending and window close. Everything is written
under a system temp directory and removed afterwards.

Exits non-zero if any check fails.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from PIL import Image  # noqa: E402

from app.batch import ItemStatus  # noqa: E402
from app.ui import ColorApp  # noqa: E402

FIXTURES = ROOT_DIR / "runtime" / "test-fixtures"
FAILURES: list[str] = []


def check(condition: bool, label: str, detail: object = "") -> None:
    if not condition:
        FAILURES.append(label)
        print(f"FAIL: {label} {detail}")


def pump(root: tk.Tk, seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)


def pump_until(root: tk.Tk, predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return True
        time.sleep(0.01)
    root.update()
    return predicate()


def make_clip(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "testsrc2=size=480x270:rate=24:duration=1",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def main() -> int:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        print("SKIP: ffmpeg/ffprobe not on PATH")
        return 0
    for name in ("scene.jpg", "pattern.png"):
        if not (FIXTURES / name).is_file():
            print(f"SKIP: fixture missing: {name}")
            return 0

    work = Path(tempfile.mkdtemp(prefix="batch-ui-check-"))
    root = tk.Tk()
    app = ColorApp(root)
    try:
        outs = work / "out"
        outs.mkdir()
        shutil.copyfile(FIXTURES / "scene.jpg", work / "one.jpg")
        shutil.copyfile(FIXTURES / "pattern.png", work / "two.png")
        make_clip(work / "clip.mp4")
        for name in ("c1.jpg", "c2.jpg", "c3.jpg"):
            shutil.copyfile(FIXTURES / "scene.jpg", work / name)

        app.load_path(work / "one.jpg")
        pump_until(root, lambda: app.state.preview_image is not None, 20.0)
        app.state.params = app.state.params.with_updates(contrast=22.0)
        app.state.bump_color()

        app.open_batch_window()
        window = app._batch_window
        check(window is not None and window.winfo_exists(), "batch window opened")
        if window is None:
            raise SystemExit("batch window did not open")

        window.set_output_dir(outs)
        window.add_paths([work / "one.jpg", work / "two.png", work / "clip.mp4"])
        pump_until(root, lambda: len(window._meta) == 3, 30.0)
        print("meta:", window._meta)
        check(len(window._rows) == 3, "three rows created", len(window._rows))
        check(len(window._photos) == 3, "three thumbnails rendered", len(window._photos))

        # Layout: every action row must fit, and rows must be tall enough for
        # the thumbnails (a fixed 20px row height used to overlap them).
        style = ttk.Style(window)
        row_height = int(style.lookup("Treeview", "rowheight") or 0)
        check(row_height >= window._thumb_side,
              "tree rows are tall enough for thumbnails",
              (row_height, window._thumb_side))
        for frame in (window.add_btn.master, window.start_btn.master,
                      window.apply_params_btn.master):
            children = [w for w in frame.winfo_children() if w.winfo_width() > 1]
            needed = sum(w.winfo_width() for w in children) + 8 * (len(children) - 1)
            check(needed <= window.winfo_width() - 28,
                  f"action row fits: {children[0].cget('text') if children else '?'}",
                  (needed, window.winfo_width()))

        video_meta = window._meta.get(window.state.items[2].item_id, "")
        check("480×270" in video_meta and "1.0" in video_meta,
              "video row shows size and duration", video_meta)
        for item in window.state.items:
            iid = window._rows[item.item_id]
            check(window.tree.set(iid, "name") == item.source.name,
                  f"row shows the file name: {item.source.name[:10]}",
                  window.tree.set(iid, "name"))
            check(bool(window.tree.item(iid, "image")),
                  f"row has a thumbnail: {item.source.name[:10]}")

        # Parameter fill: only selected, not-yet-started items change.
        window.tree.selection_set(list(window._rows.values()))
        app.state.params = app.state.params.with_updates(contrast=40.0)
        window.apply_current_params()
        first, second, third = (item.item_id for item in window.state.items)
        check(all(item.override is not None for item in window.state.items),
              "current params filled into every selected item")
        check(window.state.item(first).override.contrast == 40.0,
              "filled override carries the editor values")
        check(window.tree.set(window._rows[first], "params") == "单独",
              "row reports per-item parameters")

        window.tree.selection_set([window._rows[second]])
        window.clear_overrides()
        check(window.state.item(first).override is not None
              and window.state.item(second).override is None,
              "clearing one selection leaves the others alone", "")

        window.tree.selection_set(list(window._rows.values()))
        window.clear_overrides()
        check(all(item.override is None for item in window.state.items),
              "uniform baseline restored for the selection")
        check(window.tree.set(window._rows[third], "params") == "统一",
              "row reports the shared baseline")

        window.start()
        check(window._running, "batch reported as running")
        check(app._batch_active, "main window entered batch mode")
        check(str(app.export_img_btn.cget("state")) == "disabled",
              "single-asset export disabled during batch")
        check(str(app.open_btn.cget("state")) == "disabled",
              "material switching disabled during batch")

        # Single-asset paths must refuse rather than compete with the batch.
        app.export_image()
        check("已暂停" in app.message_var.get(), "main export refused during batch",
              app.message_var.get())
        app.load_path(work / "two.png")
        check(app.state.source.path == work / "one.jpg",
              "main window could not switch material during batch")

        finished = pump_until(root, lambda: not window._running, 240.0)
        check(finished, "batch finished")
        pump(root, 0.4)

        statuses = [window.state.record(i.item_id).status for i in window.state.items]
        print("statuses:", [s.value for s in statuses])
        check(all(s is ItemStatus.DONE for s in statuses), "all three items done")
        for item in window.state.items:
            out = window.state.record(item.item_id).output
            check(out is not None and out.is_file(), f"{item.source.name} output exists")
            if out is not None and out.is_file():
                minimum = 1000 if out.suffix.lower() == ".mp4" else 200
                check(out.stat().st_size > minimum,
                      f"{item.source.name} output size", out.stat().st_size)
        still = window.state.record(window.state.items[1].item_id).output
        if still is not None and still.is_file():
            with Image.open(still) as rendered:
                check(rendered.size == (64, 48), "PNG keeps source size", rendered.size)

        check(not app._batch_active, "main window left batch mode")
        check(str(app.export_img_btn.cget("state")) == "normal",
              "single-asset export re-enabled", str(app.export_img_btn.cget("state")))
        check(str(app.open_btn.cget("state")) == "normal",
              "material switching re-enabled", str(app.open_btn.cget("state")))
        check("批次结束" in window.detail_var.get(), "summary shown",
              window.detail_var.get())

        # Duplicates are rejected instead of being queued twice.
        window.add_paths([work / "one.jpg"])
        check(len(window.state.items) == 3, "duplicate source rejected",
              len(window.state.items))

        # Cancel pending: the running item finishes, the rest are cancelled.
        window.add_paths([work / "c1.jpg", work / "c2.jpg", work / "c3.jpg"])
        pump_until(root, lambda: len(window._rows) == 6, 20.0)
        check(len(window.state.items) == 6, "second wave added",
              len(window.state.items))
        window.start()
        check(pump_until(root, lambda: window.runner is not None
                         and window.runner.is_running(), 30.0),
              "second batch started")
        cancelled = window.runner.cancel_pending()
        check(cancelled == 2, "two queued items cancelled", cancelled)
        check(pump_until(root, lambda: not window._running, 180.0),
              "second batch drained")
        pump(root, 0.3)

        first_wave = [window.state.record(i.item_id).status
                      for i in window.state.items[3:]]
        print("second wave:", [s.value for s in first_wave])
        check(first_wave[0] is ItemStatus.DONE, "running item finished")
        check(first_wave[1] is ItemStatus.CANCELLED, "queued item 2 cancelled")
        check(first_wave[2] is ItemStatus.CANCELLED, "queued item 3 cancelled")

        window.close()
        check(app._batch_window is None, "batch window closed")
        check(not app._batch_active, "interlock released after close")
    finally:
        try:
            app.close()
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass
            shutil.rmtree(work, ignore_errors=True)

    if FAILURES:
        print(f"\nFAILURES ({len(FAILURES)}):")
        for item in FAILURES:
            print(" -", item)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
