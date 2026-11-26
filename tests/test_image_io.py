from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, PngImagePlugin

from app import image_io
from app.image_io import ImageError


def _png_header_only(width: int, height: int) -> bytes:
    """A PNG with a valid signature/IHDR/IEND and no image data."""

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IEND", b"")
    )


def _save_with_orientation(path: Path, orientation: int) -> None:
    width, height = 20, 10
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    arr[..., 0] = 30
    arr[..., 1] = 30
    arr[..., 2] = 30
    arr[0, 0] = (255, 0, 0)
    arr[-1, -1] = (0, 0, 255)
    image = Image.fromarray(arr, "RGB")
    exif = Image.Exif()
    exif[0x0112] = orientation
    image.save(path, exif=exif.tobytes())


class ImageLoadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_exif_orientations_1_to_8(self) -> None:
        for orientation in range(1, 9):
            with self.subTest(orientation=orientation):
                path = self.dir / f"o{orientation}.png"
                _save_with_orientation(path, orientation)
                source = image_io.load_source_image(path)
                self.assertEqual(source.orientation, orientation)
                expected = (10, 20) if orientation >= 5 else (20, 10)
                self.assertEqual((source.width, source.height), expected)

    def test_orientation_6_moves_top_left_to_top_right(self) -> None:
        path = self.dir / "o6corners.png"
        _save_with_orientation(path, 6)
        source = image_io.load_source_image(path)
        arr = np.asarray(source.image)
        # 90° CW: the stored top-left lands top-right, the stored bottom-right
        # lands bottom-left.
        self.assertGreater(int(arr[0, -1, 0]), 200)
        self.assertGreater(int(arr[-1, 0, 2]), 200)

    def test_orientation_3_rotates_180(self) -> None:
        path = self.dir / "o3corners.png"
        _save_with_orientation(path, 3)
        source = image_io.load_source_image(path)
        arr = np.asarray(source.image)
        self.assertGreater(int(arr[-1, -1, 0]), 200)
        self.assertGreater(int(arr[0, 0, 2]), 200)

    def test_grayscale_and_palette(self) -> None:
        gray = self.dir / "gray.png"
        Image.fromarray(np.arange(256, dtype=np.uint8).reshape(16, 16), "L").save(gray)
        source = image_io.load_source_image(gray)
        self.assertEqual(source.image.mode, "RGBA")
        self.assertEqual(np.asarray(source.image)[0, 0, 3], 255)

        palette = self.dir / "palette.png"
        image = Image.new("P", (8, 8))
        image.putpalette([255, 0, 0, 0, 255, 0] + [0] * (256 * 3 - 6))
        image.save(palette, transparency=0)
        source = image_io.load_source_image(palette)
        self.assertEqual(source.image.mode, "RGBA")
        self.assertTrue(source.had_alpha)

    def test_16bit_rejected(self) -> None:
        path = self.dir / "16bit.png"
        image = Image.new("I;16", (16, 16))
        image.putdata(list(range(256)))
        image.save(path)
        with self.assertRaises(ImageError) as ctx:
            image_io.load_source_image(path)
        self.assertEqual(ctx.exception.code, "IMAGE_INVALID")

    def test_cmyk_rejected(self) -> None:
        path = self.dir / "cmyk.jpg"
        Image.new("CMYK", (16, 16), (0, 0, 0, 0)).save(path, quality=90)
        with self.assertRaises(ImageError):
            image_io.load_source_image(path)

    def test_mpo_phone_photo_uses_main_image(self) -> None:
        # Most modern phones write JPEG as MPO (main image + depth/gain map).
        # Rejecting the whole container made ordinary photos unopenable.
        path = self.dir / "phone.mpo"
        main = Image.new("RGB", (24, 18), (200, 120, 60))
        extra = Image.new("RGB", (24, 18), (10, 20, 30))
        main.save(path, format="MPO", save_all=True, append_images=[extra])

        source = image_io.load_source_image(path)
        self.assertEqual((source.width, source.height), (24, 18))
        self.assertEqual(source.container, "MPO")
        self.assertTrue(any("主图" in n for n in source.notes))
        pixel = np.asarray(source.image)[9, 12]
        self.assertGreater(int(pixel[0]), 150)  # main image, not the depth map

    def test_additional_still_containers_load(self) -> None:
        base = Image.new("RGB", (32, 20), (90, 140, 200))
        for suffix, fmt in (
            (".webp", "WEBP"),
            (".bmp", "BMP"),
            (".tif", "TIFF"),
            (".gif", "GIF"),
        ):
            with self.subTest(fmt=fmt):
                path = self.dir / f"sample{suffix}"
                base.save(path, format=fmt)
                source = image_io.load_source_image(path)
                self.assertEqual((source.width, source.height), (32, 20))
                self.assertEqual(source.container, fmt)
                self.assertEqual(source.image.mode, "RGBA")

    def test_multiframe_gif_uses_first_frame_with_note(self) -> None:
        path = self.dir / "anim.gif"
        frames = [Image.new("RGB", (8, 8), (i * 40, 0, 0)) for i in range(3)]
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=100)
        source = image_io.load_source_image(path)
        self.assertEqual(source.container, "GIF")
        self.assertTrue(any("只使用第 1 帧" in n for n in source.notes))

    def test_heif_without_plugin_explains_the_fix(self) -> None:
        if image_io.HEIF_AVAILABLE:
            self.skipTest("pillow-heif is installed; HEIF opens natively")
        path = self.dir / "photo.heic"
        # A HEIC-branded ftyp box is enough to reach the container check.
        path.write_bytes(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64)
        with self.assertRaises(ImageError) as ctx:
            image_io.load_source_image(path)
        self.assertIn("pillow-heif", ctx.exception.message)

    def test_unknown_container_names_supported_formats(self) -> None:
        path = self.dir / "vector.svg"
        path.write_text("<svg/>", encoding="utf-8")
        with self.assertRaises(ImageError) as ctx:
            image_io.load_source_image(path)
        self.assertIn("无法识别", ctx.exception.message)
        self.assertIn("JPEG", ctx.exception.message)

    def test_animated_rejected(self) -> None:
        path = self.dir / "anim.png"
        frames = [Image.new("RGBA", (8, 8), (i * 20, 0, 0, 255)) for i in range(3)]
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=100)
        with self.assertRaises(ImageError):
            image_io.load_source_image(path)

    def test_srgb_icc_accepted(self) -> None:
        path = self.dir / "icc.png"
        image = Image.fromarray(np.full((16, 16, 3), 128, dtype=np.uint8), "RGB")
        image.save(path, icc_profile=image_io.srgb_profile_bytes())
        source = image_io.load_source_image(path)
        self.assertEqual(source.icc_action, "icc-to-srgb")
        self.assertEqual(source.width, 16)

    def test_invalid_icc_rejected(self) -> None:
        path = self.dir / "badicc.png"
        image = Image.new("RGB", (8, 8), (10, 20, 30))
        image.save(path, icc_profile=b"not an icc profile")
        with self.assertRaises(ImageError) as ctx:
            image_io.load_source_image(path)
        self.assertEqual(ctx.exception.code, "COLORSPACE_UNSUPPORTED")

    def test_gamma_plus_icc_conflict_rejected(self) -> None:
        path = self.dir / "conflict.png"
        image = Image.new("RGB", (8, 8), (10, 20, 30))
        info = PngImagePlugin.PngInfo()
        info.add(b"gAMA", struct.pack(">I", 45455))
        image.save(
            path,
            icc_profile=image_io.srgb_profile_bytes(),
            pnginfo=info,
        )
        with Image.open(path) as check:
            if "gamma" not in check.info:
                self.skipTest("Pillow did not preserve the gAMA chunk")
        with self.assertRaises(ImageError):
            image_io.load_source_image(path)

    def test_oversize_side_rejected(self) -> None:
        path = self.dir / "wide.png"
        Image.new("RGB", (20000, 1), (0, 0, 0)).save(path)
        with self.assertRaises(ImageError):
            image_io.load_source_image(path)

    def test_oversize_rejected_before_pixels_are_decoded(self) -> None:
        # A PNG whose IHDR alone declares more than 40 MP: no IDAT, so any
        # attempt to decode would fail with a truncation error. Reaching the
        # pixel-count rejection instead proves the header check runs first.
        path = self.dir / "huge-header.png"
        path.write_bytes(_png_header_only(7000, 7000))
        with mock.patch.object(
            Image.Image,
            "load",
            side_effect=AssertionError("decoded oversized image"),
        ):
            with self.assertRaises(ImageError) as ctx:
                image_io.load_source_image(path)
        self.assertEqual(ctx.exception.code, "IMAGE_INVALID")
        self.assertIn("40 百万像素", ctx.exception.message)

    def test_truncated_header_only_file_reports_decode_error(self) -> None:
        # Same trick below the limit: the header passes, so the failure must be
        # the decode error rather than a bogus dimension complaint.
        path = self.dir / "small-header.png"
        path.write_bytes(_png_header_only(32, 32))
        with self.assertRaises(ImageError) as ctx:
            image_io.load_source_image(path)
        self.assertIn("无法解码", ctx.exception.message)

    def test_pixel_limit_boundary_is_inclusive(self) -> None:
        path = self.dir / "exact.png"
        Image.new("RGB", (20, 10), (0, 0, 0)).save(path)
        original = image_io.MAX_PIXELS
        try:
            image_io.MAX_PIXELS = 200  # exactly the pixel count of the fixture
            self.assertEqual(image_io.load_source_image(path).width, 20)
            image_io.MAX_PIXELS = 199
            with self.assertRaises(ImageError) as ctx:
                image_io.load_source_image(path)
            self.assertIn("40 百万像素", ctx.exception.message)
        finally:
            image_io.MAX_PIXELS = original


class ImageExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_png_roundtrip_preserves_alpha_and_icc(self) -> None:
        arr = np.zeros((9, 7, 4), dtype=np.uint8)
        arr[..., 0] = 200
        arr[..., 3] = np.array(
            [0, 64, 128, 255, 0, 64, 128, 255, 255], dtype=np.uint8
        )[:, None]
        image = Image.fromarray(arr, "RGBA")
        target = self.dir / "out.png"
        image_io.save_png_atomic(image, target)
        with Image.open(target) as check:
            check.load()
            self.assertEqual(check.mode, "RGBA")
            self.assertTrue(check.info.get("icc_profile"))
            self.assertTrue(
                np.array_equal(np.asarray(check), np.asarray(image))
            )

    def test_jpeg_flattens_alpha_on_white(self) -> None:
        arr = np.zeros((8, 8, 4), dtype=np.uint8)
        arr[..., 3] = 0
        image = Image.fromarray(arr, "RGBA")
        target = self.dir / "out.jpg"
        image_io.save_jpeg_atomic(image, target, quality=95)
        with Image.open(target) as check:
            check.load()
            self.assertEqual(check.size, (8, 8))
            pixel = np.asarray(check.convert("RGB"))[4, 4]
            self.assertGreater(int(pixel.min()), 245)

    def test_bridge_roundtrip(self) -> None:
        arr = np.arange(4 * 5 * 4, dtype=np.uint8).reshape(4, 5, 4)
        image = Image.fromarray(arr, "RGBA")
        target = self.dir / "bridge.rgba"
        image_io.write_rgba_bridge(target, image)
        back = image_io.read_rgba_bridge(target)
        self.assertTrue(np.array_equal(np.asarray(back), arr))

    def test_bridge_rejects_bad_header(self) -> None:
        target = self.dir / "bad.rgba"
        target.write_bytes(b"ACRGBA01" + b"\x00" * 16)
        with self.assertRaises(ImageError):
            image_io.read_rgba_bridge(target)

    def test_preview_is_long_side_limited(self) -> None:
        image = Image.new("RGBA", (2000, 1000), (10, 20, 30, 255))
        preview, scaled = image_io.make_preview(image, 1280)
        self.assertTrue(scaled)
        self.assertEqual(preview.size, (1280, 640))

    def test_preview_keeps_alpha_transparent_pixels(self) -> None:
        image = Image.new("RGBA", (2000, 1000), (255, 0, 0, 0))
        preview, _ = image_io.make_preview(image, 1280)
        arr = np.asarray(preview)
        self.assertEqual(int(arr[..., 3].max()), 0)

    def test_opaque_preview_matches_the_general_path(self) -> None:
        # The opaque fast path skips the float32 premultiply buffers. It must
        # produce exactly the same pixels, otherwise the memory fix would have
        # changed how photos look.
        rng = np.random.default_rng(20261021)
        arr = rng.integers(0, 256, size=(120, 260, 3), dtype=np.uint8)
        alpha = np.full((120, 260, 1), 255, dtype=np.uint8)
        image = Image.fromarray(np.concatenate([arr, alpha], axis=2), "RGBA")

        fast, scaled = image_io.make_preview(image, 128)
        self.assertTrue(scaled)

        # Reference: the premultiplied float path, alpha == 1 everywhere.
        expected = image.convert("RGB").resize((128, 59), Image.Resampling.LANCZOS)
        self.assertEqual(fast.size, expected.size)
        self.assertTrue(
            np.array_equal(np.asarray(fast.convert("RGB")), np.asarray(expected))
        )
        self.assertEqual(int(np.asarray(fast)[..., 3].min()), 255)

    def test_write_failures_leave_no_partial_or_temp_file(self) -> None:
        # ENOSPC and a permission denial both surface at os.replace; the export
        # must fail loudly and leave neither a half-written target nor a .tmp.
        image = Image.fromarray(
            np.full((8, 8, 4), 90, dtype=np.uint8), "RGBA"
        )
        target = self.dir / "out.png"
        for error in (
            OSError(28, "No space left on device"),
            PermissionError(13, "Permission denied"),
        ):
            with self.subTest(errno=error.errno):
                with mock.patch.object(
                    image_io.os, "replace", side_effect=error
                ):
                    with self.assertRaises(ImageError) as ctx:
                        image_io.save_png_atomic(image, target)
                self.assertEqual(ctx.exception.code, "EXPORT_IO")
                self.assertFalse(target.exists())
                leftovers = [p.name for p in self.dir.iterdir()]
                self.assertEqual(leftovers, [])


if __name__ == "__main__":
    unittest.main()
