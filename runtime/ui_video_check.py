"""End-to-end check for video support in the real UI.

Generates a short clip with ffmpeg, opens it through ``load_path``, scrubs to a
new timestamp, and runs the graded-video export through the same job path the
"导出视频" button uses. Exits non-zero if any step fails.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR))

from app import image_io, video_io  # noqa: E402
from app.pipeline import RenderSnapshot  # noqa: E402
from app.ui import ColorApp  # noqa: E402


def main() -> int:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        print("SKIP: ffmpeg/ffprobe not on PATH")
        return 0

    work = Path(tempfile.mkdtemp(prefix="ui-video-check-"))
    clip = work / "clip.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=30:duration=2",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(clip),
        ],
        check=True,
        capture_output=True,
    )
    target = work / "graded.mp4"

    root = tk.Tk()
    app = ColorApp(root)
    failures: list[str] = []

    def pump(seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            root.update()
            time.sleep(0.01)

    try:
        app.load_path(clip)
        pump(0.2)
        info = app.state.video
        if info is None:
            failures.append("video info was not installed")
        else:
            print(f"loaded: {info.display_width}x{info.display_height} "
                  f"{info.duration_s:.2f}s {info.fps:.2f}fps")
            if app.state.video_time <= 0:
                failures.append("initial frame time was not set")
            if str(app.video_bar.grid_info()) == "":
                failures.append("video strip is not mapped")
            if str(app.export_video_btn.cget("state")) != "normal":
                failures.append("export-video button not enabled")

        # Scrub: the same document must keep its params and swap the frame.
        app.state.params = app.state.params.with_updates(exposure_ev=0.6)
        revision_before = app.state.revision
        app.video_scale.set(1500.0)
        app._on_video_release()
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            pump(0.1)
            if abs(app.state.video_time - 1.5) < 0.05:
                break
        print(f"after scrub: t={app.state.video_time:.2f} rev={app.state.revision}")
        if abs(app.state.video_time - 1.5) > 0.05:
            failures.append("scrub did not land on the requested time")
        if app.state.revision <= revision_before:
            failures.append("scrub did not bump the colour revision")
        if abs(app.state.params.exposure_ev - 0.6) > 1e-6:
            failures.append("scrub reset the grading parameters")

        # Export through the exact job the button submits. ``_poll`` drains the
        # runner every 40 ms, so capture the outcome where the UI sees it.
        snapshot = RenderSnapshot.from_state(app.state)
        captured: dict[str, object] = {}
        original_handle = app._handle_export

        def capture(outcome, kind):
            captured["outcome"] = outcome
            return original_handle(outcome, kind)

        app._handle_export = capture
        # Mirror the button's submit path exactly, token included, so the result
        # text is attributed to the material the way the real export is.
        token = app._export_started("视频", snapshot.revision, info.path.name)
        app.runner.submit(
            "export-video",
            lambda cancel: app._run_video_export(snapshot, info, target, cancel),
            coalesce_key="export-video",
            revision=snapshot.revision,
            coalesce=False,
            token=token,
        )
        deadline = time.monotonic() + 300.0
        while time.monotonic() < deadline:
            pump(0.1)
            if "outcome" in captured:
                break
        outcome = captured.get("outcome")
        if outcome is None:
            failures.append("video export never completed")
        elif outcome.error is not None:
            failures.append(f"video export failed: {outcome.error}")
        else:
            result = outcome.value
            print(f"exported: {result.path} · {result.detail}")
            if not target.is_file():
                failures.append("exported file is missing")
            else:
                out_info = video_io.probe(target)
                if abs(out_info.duration_s - info.duration_s) > 0.15:
                    failures.append("exported duration drifted")
                frame = video_io.extract_frame(target, 0.5, work / "out.png")
                source = image_io.load_source_image(frame)
                print(f"exported frame: {source.width}x{source.height}")
        if app._export_tickets:
            failures.append("export label was not cleared")
        print("busy at end:", repr(app.busy_var.get()))
        print("message:", app.message_var.get())
    finally:
        app.close()
        shutil.rmtree(work, ignore_errors=True)

    if failures:
        print("\nFAILURES:")
        for item in failures:
            print(" -", item)
        return 1
    print("\nOK: video open, scrub and graded export all worked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
