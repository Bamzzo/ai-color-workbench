"""Manual-acceptance helper for the single-asset UI and the batch window.

This script does the boring part of a GUI acceptance pass:

* builds the awkward fixtures (very long file name, deep output directory,
  short video clip) so nobody has to hand-craft them;
* shrinks the main window to its minimum size and measures whether the
  toolbar, sidebar scrollbar, histogram and compare row still fit;
* drives the video timeline, A/B split and the full batch flow
  (import -> run -> long-name outputs);
* saves screenshots next to the fixtures so the visual pass has artefacts.

Everything is written under a system temp directory and removed at the end
unless ``--keep-artifacts`` is given, in which case the directory is printed
and kept for inspection.

DPI scaling is *not* simulated: 125%/150% must be checked by changing the
Windows display scale and restarting the app (see the checklist doc).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from PIL import Image, ImageGrab  # noqa: E402

from app.batch import ItemStatus  # noqa: E402
from app.ui import ColorApp, RenderSnapshot  # noqa: E402

FIXTURES = ROOT_DIR / "runtime" / "test-fixtures"
LONG_NAME = (
    "很长的素材文件名称_用于检查列表截断与提示换行_"
    "2026年11月11日_超长命名_编号0123456789.jpg"
)
LONG_DIR = "很长的输出目录名称_用于检查路径显示与截断_0123456789"
FAILURES: list[str] = []


def check(condition: bool, label: str, detail: object = "") -> None:
    if not condition:
        FAILURES.append(label)
        print(f"FAIL: {label} {detail}")


def note(text: str) -> None:
    print(f"  · {text}")


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
            "-f", "lavfi", "-i", "testsrc2=size=480x270:rate=24:duration=2",
            "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def box(widget: tk.Misc) -> tuple[int, int, int, int]:
    return (
        widget.winfo_rootx(),
        widget.winfo_rooty(),
        widget.winfo_width(),
        widget.winfo_height(),
    )


def overlap(a: tk.Misc, b: tk.Misc) -> bool:
    ax, ay, aw, ah = box(a)
    bx, by, bw, bh = box(b)
    if aw <= 1 or ah <= 1 or bw <= 1 or bh <= 1:
        return False
    return not (
        ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay
    )


def screenshot(root: tk.Tk, path: Path) -> bool:
    """Capture the whole window; returns False when the platform refuses."""
    try:
        root.update_idletasks()
        x, y, w, h = box(root)
        shot = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        shot.save(path)
        return True
    except Exception as exc:  # DPI-awareness or headless session
        print(f"  ! screenshot unavailable: {exc}")
        return False


def text_width(widget: tk.Misc, text: str) -> int:
    import tkinter.font as tkfont

    font = tkfont.nametofont("TkDefaultFont")
    try:
        font = tkfont.Font(font=widget.cget("font"))
    except tk.TclError:
        pass
    return font.measure(text)


def toolbar_checks(app: ColorApp) -> None:
    toolbar = app.open_btn.master
    children = [c for c in toolbar.winfo_children() if c.winfo_width() > 1]
    toolbar_w = toolbar.winfo_width()

    def label(widget: tk.Misc) -> str:
        try:
            text = widget.cget("text")
        except tk.TclError:
            text = ""
        return f"{widget.winfo_class()}:{text}" if text else widget.winfo_class()

    for child in children:
        x, width = child.winfo_x(), child.winfo_width()
        check(0 <= x and x + width <= toolbar_w,
              f"toolbar child fits: {label(child)}", (x, width, toolbar_w))
    for index, first in enumerate(children):
        for second in children[index + 1:]:
            check(not overlap(first, second),
                  f"toolbar children do not overlap: {label(first)}/"
                  f"{label(second)}")


def min_size_checks(app: ColorApp) -> None:
    root = app.root
    min_w = int(root.minsize()[0])
    min_h = int(root.minsize()[1])
    root.geometry(f"{min_w}x{min_h}")
    pump(root, 0.6)
    check(root.winfo_width() >= min_w - 2 and root.winfo_height() >= min_h - 2,
          "window honours its minimum size",
          (root.winfo_width(), root.winfo_height(), min_w, min_h))
    toolbar_checks(app)

    canvas = app.sidebar_canvas
    bar = app.sidebar_canvas.master.winfo_children()
    scrollbars = [w for w in bar if w.winfo_class() == "TScrollbar"]
    check(bool(scrollbars) and scrollbars[0].winfo_ismapped(),
          "sidebar scrollbar is visible at minimum size")
    top, bottom = app.sidebar_canvas.yview()
    check(bottom < 1.0, "sidebar content overflows and can scroll", (top, bottom))
    before = app.sidebar_canvas.yview()
    app.sidebar_canvas.yview_scroll(3, "units")
    pump(root, 0.2)
    check(app.sidebar_canvas.yview() != before, "sidebar actually scrolls")
    app.sidebar_canvas.yview_moveto(0.0)
    pump(root, 0.1)

    check(app.hist_holder.winfo_ismapped(), "histogram stays visible")
    root_bottom = root.winfo_rooty() + root.winfo_height()
    hist_bottom = app.hist_holder.winfo_rooty() + app.hist_holder.winfo_height()
    check(hist_bottom <= root_bottom, "histogram is not clipped by the window",
          (hist_bottom, root_bottom))
    check(app.compare_group.winfo_ismapped(), "compare row stays visible")
    check(app.compare_group.winfo_rooty() >= app.canvas.winfo_rooty(),
          "compare row is below the preview canvas")


def long_name_checks(app: ColorApp, work: Path, long_image: Path, long_out: Path) -> None:
    app.load_path(long_image)
    ok = pump_until(root_(app), lambda: app.state.preview_image is not None, 30.0)
    check(ok, "long-named image loads")
    check(app.state.source.path.name == LONG_NAME, "long file name preserved",
          app.state.source.path.name)
    check(LONG_NAME in app.root.title(), "title carries the long name",
          app.root.title())
    shot = work / "01-main-long-name.png"
    check(screenshot(app.root, shot), "main window screenshot saved", shot)

    app.state.params = app.state.params.with_updates(contrast=18.0)
    app.state.bump_color()
    pump_until(root_(app), lambda: app.state.preview_image is not None, 30.0)
    target = long_out / long_image.name
    # Same path as export_image() minus the save dialog: freeze a snapshot,
    # take a ticket, submit through the normal export queue.
    snapshot = RenderSnapshot.from_state(app.state)
    token = app._export_started("图片", snapshot.revision, app._material_name())
    app._submit_export(
        token,
        "export-image",
        lambda cancel: app.pipeline.export_image(snapshot, target, "PNG", 95, cancel),
        snapshot.revision,
    )
    done = pump_until(
        root_(app),
        lambda: (
            app._outstanding_exports() == 0
            and target.is_file()
            and target.stat().st_size > 0
        ),
        90.0,
    )
    check(done, "long path export completes", target)
    check(target.is_file() and target.stat().st_size > 0,
          "long path output written")
    check(LONG_NAME in app.message_var.get(), "completion message names the asset",
          app.message_var.get())


def root_(app: ColorApp) -> tk.Tk:
    return app.root


def video_checks(app: ColorApp, work: Path, clip: Path) -> None:
    app.load_path(clip)
    ok = pump_until(root_(app), lambda: app.state.video is not None, 30.0)
    check(ok, "video loads")
    if not ok:
        return
    info = app.state.video
    check(app.video_scale.winfo_ismapped(), "video timeline is visible")
    app.video_scale.set(info.duration_s * 1000.0 * 0.5)
    app._on_video_release()
    sought = pump_until(
        root_(app),
        lambda: app.state.preview_image is not None
        and app.state.video_time >= info.duration_s * 0.3,
        30.0,
    )
    check(sought, "timeline seek reaches the middle of the clip",
          getattr(app.state, "video_time", None))
    check(app.video_scale.winfo_width() > 100, "timeline has usable width",
          app.video_scale.winfo_width())

    app.split_var.set(0.5)
    app._on_split_scale("0.5")
    pump(root_(app), 0.5)
    check(abs(app.state.split_t - 0.5) < 1e-6, "A/B split ratio applied",
          app.state.split_t)
    app.split_var.set(1.0)
    app._on_split_scale("1.0")
    pump(root_(app), 0.3)
    check(app.state.split_t == 1.0, "A/B split restores the full view")
    shot = work / "02-main-video-ab.png"
    check(screenshot(app.root, shot), "video screenshot saved", shot)


def batch_checks(app: ColorApp, work: Path, long_image: Path, clip: Path,
                 long_out: Path) -> None:
    app.open_batch_window()
    window = app._batch_window
    check(window is not None and window.winfo_exists(), "batch window opens")
    if window is None:
        return
    try:
        window.set_output_dir(long_out)
        window.add_paths([long_image, clip])
        pump_until(root_(app), lambda: len(window._meta) == 2, 30.0)
        first = window.state.items[0].item_id
        tree = window.tree
        width = tree.winfo_width()
        columns = sum(int(tree.column(c, "width")) for c in tree["columns"])
        columns += int(tree.column("#0", "width"))
        check(columns <= width + 24, "batch columns fit the window",
              (columns, width))
        horizontal = [
            w for w in tree.master.winfo_children()
            if w.winfo_class() == "TScrollbar"
            and str(w.cget("orient")) == "horizontal"
        ]
        check(bool(horizontal), "batch list has a horizontal scrollbar")
        name_width = int(tree.column("name", "width"))
        note(f"long name needs {text_width(tree, LONG_NAME)} px, "
             f"name column is {name_width} px (Treeview clips, use h-scroll)")
        check(name_width >= 160, "name column keeps a usable width", name_width)
        check(int(tree.column("#0", "width")) >= window._thumb_side,
              "thumbnail column fits the thumbnails",
              (tree.column("#0", "width"), window._thumb_side))

        window.start()
        finished = pump_until(root_(app), lambda: not window._running, 240.0)
        check(finished, "batch finishes with awkward names")
        statuses = [window.state.record(i.item_id).status
                    for i in window.state.items]
        print("statuses:", [s.value for s in statuses])
        check(all(s is ItemStatus.DONE for s in statuses),
              "both long-name items are done", statuses)
        for item in window.state.items:
            out = window.state.record(item.item_id).output
            check(out is not None and out.is_file(),
                  f"output exists: {item.source.name[:12]}…", out)
        check(window.state.record(first).output is not None
              and Path(LONG_NAME).stem in window.state.record(first).output.name,
              "output keeps the long stem",
              window.state.record(first).output)
        shot = work / "03-batch-long-names.png"
        check(screenshot(window, shot), "batch window screenshot saved", shot)
    finally:
        window.close()
        pump(root_(app), 0.3)
        check(app._batch_window is None, "batch window closes")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-artifacts", action="store_true")
    args = parser.parse_args()

    if not (FIXTURES / "scene.jpg").is_file():
        print("SKIP: fixture missing: scene.jpg")
        return 0
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        print("SKIP: ffmpeg/ffprobe not on PATH")
        return 0

    work = Path(tempfile.mkdtemp(prefix="ui-acceptance-"))
    root = tk.Tk()
    app = ColorApp(root)
    try:
        long_dir = work / LONG_DIR
        long_dir.mkdir()
        long_image = work / LONG_NAME
        shutil.copyfile(FIXTURES / "scene.jpg", long_image)
        clip = work / "验收用短片_时间轴检查.mp4"
        make_clip(clip)

        print("-- minimum window layout --")
        min_size_checks(app)

        print("-- long file name and long output path --")
        long_name_checks(app, work, long_image, long_dir)

        print("-- video timeline and A/B split --")
        video_checks(app, work, clip)

        print("-- batch flow with awkward names --")
        batch_checks(app, work, long_image, clip, long_dir)
    finally:
        try:
            app.close()
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass

    print(f"\nartifacts: {work}")
    if not args.keep_artifacts:
        shutil.rmtree(work, ignore_errors=True)
        print("removed (pass --keep-artifacts to inspect screenshots)")

    if FAILURES:
        print(f"\nFAILURES ({len(FAILURES)}):")
        for item in FAILURES:
            print(" -", item)
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
