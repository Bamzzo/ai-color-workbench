"""Video pipeline tests: probe, frame extraction and LUT re-encode.

Clips are generated with ffmpeg itself, so the tests need no binary fixtures.
Without ffmpeg on PATH the whole module skips instead of failing.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np

from app import image_io, video_io
from baker.cube_writer import export_params_lut
from baker.params import ColorParams

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


def _make_clip(path: Path, *, source: str, duration: float = 1.0) -> None:
    subprocess.run(
        [
            FFMPEG,
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            source,
            "-t",
            f"{duration}",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _pixel(path: Path, time_s: float = 0.0) -> np.ndarray:
    with tempfile.TemporaryDirectory() as tmp:
        frame = video_io.extract_frame(path, time_s, Path(tmp) / "f.png")
        return np.asarray(image_io.load_source_image(frame).image)[..., :3].astype(int)


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg/ffprobe not available")
class VideoPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dir = Path(tempfile.mkdtemp(prefix="video-tests-"))
        cls.clip = cls.dir / "clip.mp4"
        _make_clip(
            cls.clip, source="testsrc2=size=320x180:rate=25:duration=1", duration=1.0
        )
        cls.flat = cls.dir / "flat.mp4"
        _make_clip(
            cls.flat, source="color=c=0x808080:size=320x180:rate=25:duration=1"
        )

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.dir, ignore_errors=True)

    def test_probe_reports_stream_metadata(self) -> None:
        info = video_io.probe(self.clip)
        self.assertAlmostEqual(info.duration_s, 1.0, places=2)
        self.assertAlmostEqual(info.fps, 25.0, places=2)
        self.assertEqual((info.width, info.height), (320, 180))
        self.assertEqual(info.codec, "h264")
        self.assertFalse(info.has_audio)

    def test_probe_rejects_non_video(self) -> None:
        from PIL import Image

        still = self.dir / "still.png"
        Image.new("RGB", (4, 4), (10, 20, 30)).save(still)
        with self.assertRaises(video_io.VideoError) as ctx:
            video_io.probe(still)
        self.assertEqual(ctx.exception.code, "VIDEO_INVALID")

    def test_extract_frame_is_a_loadable_still(self) -> None:
        target = self.dir / "frame.png"
        out = video_io.extract_frame(self.clip, 0.5, target)
        self.assertTrue(out.is_file())
        source = image_io.load_source_image(out)
        self.assertEqual((source.width, source.height), (320, 180))
        self.assertEqual(source.container, "PNG")

    def test_extract_frame_clamps_beyond_duration(self) -> None:
        out = video_io.extract_frame(self.clip, 99.0, self.dir / "late.png")
        self.assertTrue(out.is_file())

    def test_timecode_format(self) -> None:
        info = video_io.probe(self.clip)
        self.assertEqual(info.timecode(0.0), "00:00.00")
        self.assertEqual(info.timecode(61.25), "01:01.25")

    def test_export_applies_the_lut(self) -> None:
        params = ColorParams.identity().with_updates(
            temperature=80.0, exposure_ev=0.5
        )
        cube = self.dir / "grade.cube"
        export_params_lut(params, 1.0, cube, size=33)

        out = video_io.export_graded(self.flat, cube, self.dir / "graded.mp4")
        self.assertTrue(out.is_file())
        self.assertGreater(out.stat().st_size, 0)

        before = _pixel(self.flat).reshape(-1, 3).mean(axis=0)
        after = _pixel(out).reshape(-1, 3).mean(axis=0)
        # Warm + brighter: red rises, and red must gain on blue.
        self.assertGreater(after[0], before[0] + 10)
        self.assertGreater(after[0] - after[2], before[0] - before[2] + 5)

    def test_export_reports_monotonic_progress(self) -> None:
        cube = self.dir / "identity.cube"
        export_params_lut(ColorParams.identity(), 1.0, cube, size=33)
        samples: list[float] = []
        video_io.export_graded(
            self.clip, cube, self.dir / "progress.mp4", on_progress=samples.append
        )
        self.assertGreaterEqual(len(samples), 1)
        self.assertGreaterEqual(samples[-1], 0.99)
        self.assertEqual(samples, sorted(samples))

    def test_export_without_audio_keeps_the_video(self) -> None:
        cube = self.dir / "identity2.cube"
        export_params_lut(ColorParams.identity(), 1.0, cube, size=33)
        out = video_io.export_graded(self.clip, cube, self.dir / "silent.mp4")
        info = video_io.probe(out)
        self.assertFalse(info.has_audio)
        self.assertAlmostEqual(info.duration_s, 1.0, places=2)

    def test_cancel_leaves_no_partial_output(self) -> None:
        cube = self.dir / "identity3.cube"
        export_params_lut(ColorParams.identity(), 1.0, cube, size=33)
        target = self.dir / "cancelled.mp4"
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(video_io.VideoError) as ctx:
            video_io.export_graded(
                self.flat, cube, target, cancel_event=cancel
            )
        self.assertEqual(ctx.exception.code, "CANCELLED")
        self.assertFalse(target.exists())
        self.assertEqual(list(self.dir.glob("*.partial*")), [])

    def test_bad_input_reports_invalid(self) -> None:
        junk = self.dir / "junk.mp4"
        junk.write_bytes(b"\x00" * 512)
        with self.assertRaises(video_io.VideoError) as ctx:
            video_io.probe(junk)
        self.assertEqual(ctx.exception.code, "VIDEO_INVALID")

    def test_quick_fingerprint_changes_with_content(self) -> None:
        other = self.dir / "other.mp4"
        _make_clip(other, source="color=c=0x202020:size=64x64:rate=10:duration=1")
        self.assertNotEqual(
            video_io.quick_fingerprint(self.clip), video_io.quick_fingerprint(other)
        )


class VideoAvailabilityTests(unittest.TestCase):
    def test_missing_ffmpeg_is_explained(self) -> None:
        import os

        previous = os.environ.get("AI_COLOR_FFMPEG")
        previous_probe = os.environ.get("AI_COLOR_FFPROBE")
        missing = str(Path(tempfile.gettempdir()) / "nope.exe")
        os.environ["AI_COLOR_FFMPEG"] = missing
        os.environ["AI_COLOR_FFPROBE"] = missing
        try:
            ok, detail = video_io.availability()
            self.assertFalse(ok)
            self.assertIn("ffmpeg", detail)
            with self.assertRaises(video_io.VideoError) as ctx:
                video_io.probe(Path("whatever.mp4"))
            self.assertEqual(ctx.exception.code, "VIDEO_UNAVAILABLE")
            with self.assertRaises(video_io.VideoError) as ctx:
                video_io.extract_frame(Path("whatever.mp4"), 0.0, Path("out.png"))
            self.assertEqual(ctx.exception.code, "VIDEO_UNAVAILABLE")
        finally:
            for key, value in (
                ("AI_COLOR_FFMPEG", previous),
                ("AI_COLOR_FFPROBE", previous_probe),
            ):
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


if __name__ == "__main__":
    unittest.main()
