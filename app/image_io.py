"""Image loading, normalization, preview resampling and atomic export.

Input is any still-image container Pillow decodes to 8-bit RGB(A): JPEG, PNG,
WebP, BMP, TIFF, and the MPO files most phones produce (a JPEG main image plus
a depth/gain map — only the main image is graded). Everything is normalized to
straight (non-premultiplied) RGBA8 encoded sRGB. Alpha is never colour-managed.
"""

from __future__ import annotations

import hashlib
import io
import math
import os
import struct
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms, ImageOps, UnidentifiedImageError

MAX_PIXELS = 40_000_000
MAX_SIDE = 16384
MAX_FILE_BYTES = 100 * 1024 * 1024
PREVIEW_LONG_SIDE = 1280

# Containers we can decode to 8-bit RGB(A) with the base Pillow install.
DECODABLE_FORMATS = {
    "JPEG": "JPEG",
    "PNG": "PNG",
    "MPO": "JPEG",  # multi-picture JPEG: main image + depth/gain map
    "WEBP": "WebP",
    "BMP": "BMP",
    "TIFF": "TIFF",
    "GIF": "GIF",
}
# Formats that legitimately hold several pictures; we grade the first frame and
# say so. APNG is deliberately absent: an animated PNG is usually an animation,
# not a photo with an embedded extra image.
MULTIFRAME_OK = {"MPO", "GIF", "WEBP", "TIFF", "HEIF", "AVIF"}

HEIF_HINT = (
    "iPhone/HEIF 文件需要 pillow-heif 插件："
    ".\\.venv\\Scripts\\python.exe -m pip install pillow-heif，"
    "或先用系统「照片」导出为 JPEG"
)

# Optional HEIF/AVIF support: registers a Pillow opener when the plugin exists.
HEIF_AVAILABLE = False
try:  # pragma: no cover - depends on the local environment
    from pillow_heif import register_heif_opener

    register_heif_opener()
    DECODABLE_FORMATS["HEIF"] = "HEIF"
    DECODABLE_FORMATS["AVIF"] = "AVIF"
    HEIF_AVAILABLE = True
except Exception:
    HEIF_AVAILABLE = False

RGBA_MAGIC = b"ACRGBA01"
RGBA_HEADER = struct.Struct("<8sIIII")


class ImageError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class SourceImage:
    path: Path
    fingerprint: str
    width: int
    height: int
    image: Image.Image  # RGBA8 straight, EXIF-normalized, encoded sRGB
    orientation: int = 1
    had_alpha: bool = False
    icc_action: str = "assumed-srgb"
    notes: list[str] = field(default_factory=list)
    container: str = ""  # Pillow format of the file that was opened


def srgb_profile_bytes() -> bytes:
    try:
        profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
        return profile.tobytes()
    except Exception:  # pragma: no cover - depends on littlecms build
        return b""


def file_fingerprint(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


HEIF_SUFFIXES = (".heic", ".heif", ".avif")


def _unidentified_message(path: Path) -> str:
    """Explain an unopenable file instead of surfacing Pillow's raw error."""
    if path.suffix.lower() in HEIF_SUFFIXES:
        return HEIF_HINT
    readable = " / ".join(sorted(DECODABLE_FORMATS))
    suffix = path.suffix.lower() or "（无扩展名）"
    return f"无法识别 {suffix} 文件；可打开 {readable}"


def _check_container(im: Image.Image, path: Path) -> str | None:
    """Validate a just-opened (header-parsed) image; return a note if useful.

    Runs before ``load()`` so an oversized or unsupported file costs a header
    read rather than a full decode.
    """
    fmt = (im.format or "").upper()
    if fmt not in DECODABLE_FORMATS:
        if fmt in ("HEIF", "HEIC", "AVIF") or path.suffix.lower() in HEIF_SUFFIXES:
            raise ImageError("IMAGE_INVALID", HEIF_HINT)
        raise ImageError(
            "IMAGE_INVALID", f"不支持的图像格式 {fmt or '未知'}；{_unidentified_message(path)}"
        )
    frames = int(getattr(im, "n_frames", 1) or 1)
    if frames > 1 and fmt not in MULTIFRAME_OK:
        raise ImageError("IMAGE_INVALID", "不支持动画/多帧文件")

    mode = im.mode
    if mode in ("I;16", "I;16B", "I;16L", "I", "F"):
        raise ImageError(
            "IMAGE_INVALID", "不支持 16 位/浮点图像，请先转换为 8 位 sRGB"
        )
    if mode in ("CMYK", "YCbCr", "LAB", "HSV"):
        raise ImageError(
            "IMAGE_INVALID", f"不支持 {mode} 颜色模式，请先转换为 sRGB"
        )

    width, height = im.size
    if width <= 0 or height <= 0:
        raise ImageError("IMAGE_INVALID", "图像尺寸无效")
    if width > MAX_SIDE or height > MAX_SIDE:
        raise ImageError(
            "IMAGE_INVALID", f"单边超过 {MAX_SIDE} 像素限制"
        )
    if width * height > MAX_PIXELS:
        raise ImageError(
            "IMAGE_INVALID", "图像超过 40 百万像素限制"
        )

    note = None
    if frames > 1:
        if fmt == "MPO":
            note = "MPO 多图容器：只使用主图（第 1 帧），不读取景深/增益图"
        else:
            note = f"{fmt} 含 {frames} 帧：只使用第 1 帧"
    return note


def _icc_to_srgb(im: Image.Image, notes: list[str]) -> tuple[Image.Image, str]:
    icc = im.info.get("icc_profile")
    gamma = im.info.get("gamma")
    chromaticity = im.info.get("chromaticity")

    has_alpha = im.mode in ("RGBA", "LA") or "transparency" in im.info
    alpha = None
    if im.mode in ("RGBA", "LA"):
        alpha = im.getchannel("A")
    elif "transparency" in im.info:
        alpha = im.convert("RGBA").getchannel("A")

    if icc:
        if gamma is not None or chromaticity is not None:
            raise ImageError(
                "COLORSPACE_UNSUPPORTED",
                "PNG 同时带有 ICC 与 gAMA/cHRM，P0 不做自写颜色管理；请先转换",
            )
        try:
            src_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            if getattr(src_profile.profile, "xcolor_space", "") != "RGB ":
                raise ImageError(
                    "COLORSPACE_UNSUPPORTED", "仅支持 RGB ICC 配置文件"
                )
            dst_profile = ImageCms.createProfile("sRGB")
            rgb = im.convert("RGB")
            converted = ImageCms.profileToProfile(
                rgb,
                src_profile,
                dst_profile,
                renderingIntent=0,
                outputMode="RGB",
            )
        except ImageError:
            raise
        except Exception as exc:
            raise ImageError(
                "COLORSPACE_UNSUPPORTED", f"ICC 转换失败: {exc}"
            ) from exc
        if alpha is not None:
            converted.putalpha(alpha)
        notes.append("已按 ICC 转换为 sRGB")
        return converted.convert("RGBA"), "icc-to-srgb"

    if gamma is not None and abs(float(gamma) - 0.45455) > 0.02:
        notes.append(
            f"PNG 声明 gamma={float(gamma):.4f}，P0 按 sRGB 解释，未做转换"
        )
        return im.convert("RGBA"), "assumed-srgb-gamma-mismatch"
    if gamma is not None:
        notes.append("PNG gamma 与 sRGB 一致")
    return im.convert("RGBA"), "assumed-srgb"


def load_source_image(path: str | Path) -> SourceImage:
    file_path = Path(path)
    try:
        stat = file_path.stat()
    except OSError as exc:
        raise ImageError("EXPORT_IO", f"无法访问文件: {exc}") from exc
    if stat.st_size > MAX_FILE_BYTES:
        raise ImageError("IMAGE_INVALID", "文件超过 100 MiB 限制")
    fingerprint = file_fingerprint(file_path)

    try:
        opened_cm = Image.open(file_path)
    except UnidentifiedImageError as exc:
        raise ImageError("IMAGE_INVALID", _unidentified_message(file_path)) from exc

    try:
        with opened_cm as opened:
            # Header-only checks come first: Image.open has parsed the JPEG SOF /
            # PNG IHDR by now, so format, frame count, mode and dimensions are
            # known without decoding a single pixel. Doing this before load()
            # means an oversized file costs a header read instead of hundreds of
            # megabytes of decoded buffer.
            container_note = _check_container(opened, file_path)
            container = (opened.format or "").upper()
            opened.load()
            orientation = 1
            try:
                orientation = int(opened.getexif().get(0x0112, 1) or 1)
            except Exception:
                orientation = 1
            if not 1 <= orientation <= 8:
                orientation = 1
            had_alpha = opened.mode in ("RGBA", "LA") or "transparency" in opened.info
            notes: list[str] = []
            if container_note:
                notes.append(container_note)
            oriented = ImageOps.exif_transpose(opened)
            rgba, icc_action = _icc_to_srgb(oriented, notes)
            rgba = rgba.convert("RGBA")
            width, height = rgba.size
    except ImageError:
        raise
    except (OSError, ValueError) as exc:
        raise ImageError("IMAGE_INVALID", f"无法解码图像: {exc}") from exc

    # EXIF rotation can swap the axes, so the post-transpose pixel count is the
    # one that decides how much memory the rest of the pipeline will need.
    if width * height > MAX_PIXELS:
        raise ImageError("IMAGE_INVALID", "图像超过 40 百万像素限制")

    return SourceImage(
        path=file_path,
        fingerprint=fingerprint,
        width=width,
        height=height,
        image=rgba,
        orientation=orientation,
        had_alpha=had_alpha,
        icc_action=icc_action,
        notes=notes,
        container=container,
    )


def _resize_premultiplied(rgba: Image.Image, size: tuple[int, int]) -> Image.Image:
    """Resize in premultiplied space so transparent edges do not fringe.

    The float path below materialises several full-size float32 buffers: for a
    40 MP source that is ~640 MB per temporary and pushed the measured peak to
    about 3 GB. Fully opaque images (every JPEG, and most PNGs) can skip the
    whole dance — premultiplying by 255/255 is the identity, so resizing the RGB
    channels directly gives the same pixels.
    """
    if rgba.getchannel("A").getextrema() == (255, 255):
        return rgba.convert("RGB").resize(size, Image.Resampling.LANCZOS).convert("RGBA")

    arr = np.asarray(rgba, dtype=np.float32)
    alpha = arr[..., 3:4] / 255.0
    premultiplied = np.concatenate([arr[..., :3] * alpha, arr[..., 3:4]], axis=2)
    pm_image = Image.fromarray(np.clip(np.rint(premultiplied), 0, 255).astype(np.uint8))
    resized = pm_image.resize(size, Image.Resampling.LANCZOS)
    out = np.asarray(resized, dtype=np.float32)
    a = out[..., 3:4] / 255.0
    rgb = np.where(a > 0.0, out[..., :3] / np.maximum(a, 1e-6), out[..., :3])
    result = np.concatenate([np.clip(np.rint(rgb), 0, 255), out[..., 3:4]], axis=2)
    return Image.fromarray(result.astype(np.uint8))


def make_preview(
    rgba: Image.Image, long_side: int = PREVIEW_LONG_SIDE
) -> tuple[Image.Image, bool]:
    width, height = rgba.size
    longest = max(width, height)
    if longest <= long_side:
        return rgba.copy(), False
    scale = long_side / float(longest)
    new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return _resize_premultiplied(rgba, new_size), True


def write_rgba_bridge(path: str | Path, rgba: Image.Image) -> tuple[int, int]:
    arr = np.asarray(rgba.convert("RGBA"), dtype=np.uint8)
    height, width = arr.shape[:2]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + f".{uuid.uuid4().hex}.tmp")
    header = RGBA_HEADER.pack(RGBA_MAGIC, width, height, width * 4, 1)
    try:
        with tmp.open("wb") as f:
            f.write(header)
            f.write(arr.tobytes(order="C"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ImageError("EXPORT_IO", f"写入 RGBA 桥失败: {exc}") from exc
    return width, height


def read_rgba_bridge(path: str | Path) -> Image.Image:
    file_path = Path(path)
    try:
        raw = file_path.read_bytes()
    except OSError as exc:
        raise ImageError("EXPORT_IO", f"无法读取渲染结果: {exc}") from exc
    if len(raw) < RGBA_HEADER.size:
        raise ImageError("IMAGE_INVALID", "渲染结果头不完整")
    magic, width, height, stride, fmt = RGBA_HEADER.unpack_from(raw, 0)
    if magic != RGBA_MAGIC:
        raise ImageError("IMAGE_INVALID", "渲染结果 magic 不正确")
    if fmt != 1 or width <= 0 or height <= 0:
        raise ImageError("IMAGE_INVALID", "渲染结果格式不支持")
    if stride != width * 4 or len(raw) != RGBA_HEADER.size + width * height * 4:
        raise ImageError("IMAGE_INVALID", "渲染结果长度与头不一致")
    arr = np.frombuffer(raw, dtype=np.uint8, offset=RGBA_HEADER.size)
    arr = arr.reshape((height, width, 4))
    return Image.fromarray(arr.copy(), mode="RGBA")


def _atomic_pillow_save(image: Image.Image, target: Path, **kwargs) -> None:
    tmp = target.with_name(target.name + f".{uuid.uuid4().hex}.tmp")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tmp.open("wb") as f:
            image.save(f, **kwargs)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, target)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ImageError("EXPORT_IO", f"写入图像失败: {exc}") from exc


def save_png_atomic(rgba: Image.Image, target: str | Path) -> None:
    image = rgba.convert("RGBA")
    icc = srgb_profile_bytes()
    _atomic_pillow_save(
        image,
        Path(target),
        format="PNG",
        icc_profile=icc if icc else None,
    )
    try:
        with Image.open(target) as check:
            check.load()
            if check.size != image.size or check.mode != "RGBA":
                raise ImageError("EXPORT_IO", "PNG 回读校验失败")
            if not np.array_equal(
                np.asarray(check.convert("RGBA"), dtype=np.uint8),
                np.asarray(image, dtype=np.uint8),
            ):
                raise ImageError("EXPORT_IO", "PNG 回读像素不一致")
    except OSError as exc:
        raise ImageError("EXPORT_IO", f"PNG 回读失败: {exc}") from exc


def save_jpeg_atomic(
    rgba: Image.Image, target: str | Path, quality: int = 95
) -> None:
    if not 1 <= int(quality) <= 100:
        raise ImageError("EXPORT_IO", "JPEG 质量必须在 [1, 100]")
    image = rgba.convert("RGBA")
    background = Image.new("RGBA", image.size, (255, 255, 255, 255))
    composed = Image.alpha_composite(background, image).convert("RGB")
    icc = srgb_profile_bytes()
    _atomic_pillow_save(
        composed,
        Path(target),
        format="JPEG",
        quality=int(quality),
        subsampling=0,
        icc_profile=icc if icc else None,
    )
    try:
        with Image.open(target) as check:
            check.load()
            if check.size != image.size:
                raise ImageError("EXPORT_IO", "JPEG 回读尺寸不一致")
    except OSError as exc:
        raise ImageError("EXPORT_IO", f"JPEG 回读失败: {exc}") from exc


def default_export_path(source: Path, extension: str) -> Path:
    return source.with_name(f"{source.stem}_graded{extension}")


def is_same_file(a: str | Path, b: str | Path) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


def estimate_rgba_bytes(width: int, height: int) -> int:
    return int(width) * int(height) * 4


def clamp_preview_size(width: int, height: int, long_side: int) -> tuple[int, int]:
    longest = max(width, height)
    if longest <= long_side:
        return width, height
    scale = long_side / float(longest)
    return max(1, math.floor(width * scale)), max(1, math.floor(height * scale))
