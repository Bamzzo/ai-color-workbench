"""Strict reader for the supported Iridas .cube subset.

This mirrors the C++ worker parser. Files outside the subset are rejected
instead of being partially loaded.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MAX_CUBE_BYTES = 32 * 1024 * 1024
MAX_ABS_SAMPLE = 65504.0
MAX_TITLE = 256

KNOWN_HEADERS = {
    "TITLE",
    "LUT_3D_SIZE",
    "DOMAIN_MIN",
    "DOMAIN_MAX",
    "LUT_1D_SIZE",
    "LUT_1D_INPUT_RANGE",
    "LUT_3D_INPUT_RANGE",
    "INPUT_RANGE",
}


class CubeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class CubeLut:
    path: Path
    size: int
    domain_min: tuple[float, float, float]
    domain_max: tuple[float, float, float]
    title: str
    samples: np.ndarray  # float32, shape (N^3, 3), R fastest
    sha256: str

    @property
    def sample_count(self) -> int:
        return self.size * self.size * self.size

    def summary(self) -> str:
        return (
            f"{self.size}³，domain "
            f"[{self.domain_min[0]:g},{self.domain_min[1]:g},{self.domain_min[2]:g}] → "
            f"[{self.domain_max[0]:g},{self.domain_max[1]:g},{self.domain_max[2]:g}]"
        )


def _strip_comment(line: str, title_line: bool) -> str:
    if not title_line:
        index = line.find("#")
        return line if index < 0 else line[:index]
    in_quote = False
    for index, char in enumerate(line):
        if char == '"':
            in_quote = not in_quote
        if char == "#" and not in_quote:
            return line[:index]
    return line


def _parse_float(token: str, *, sample: bool) -> float:
    try:
        value = float(token)
    except ValueError as exc:
        raise CubeError("LUT_PARSE_ERROR", f"无效数值: {token}") from exc
    if not math.isfinite(value):
        raise CubeError("LUT_PARSE_ERROR", f"非有限数值: {token}")
    if sample and abs(value) > MAX_ABS_SAMPLE:
        raise CubeError(
            "LUT_UNSUPPORTED",
            f"样本超出本项目的安全上限 ±{MAX_ABS_SAMPLE:g}",
        )
    return value


def load_cube(path: str | Path) -> CubeLut:
    file_path = Path(path)
    try:
        raw = file_path.read_bytes()
    except OSError as exc:
        raise CubeError("EXPORT_IO", f"无法读取 LUT 文件: {exc}") from exc
    if len(raw) > MAX_CUBE_BYTES:
        raise CubeError("LUT_UNSUPPORTED", "LUT 文件超过 32 MiB")
    digest = hashlib.sha256(raw).hexdigest()

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CubeError("LUT_PARSE_ERROR", "LUT 文件不是 UTF-8") from exc

    size: int | None = None
    domain_min = [0.0, 0.0, 0.0]
    domain_max = [1.0, 1.0, 1.0]
    saw_min = False
    saw_max = False
    saw_title = False
    saw_data = False
    title = ""
    values: list[float] = []
    expected = 0

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        title_line = stripped.startswith("TITLE")
        line = _strip_comment(raw_line, title_line).strip()
        if not line:
            continue
        tokens = line.split()
        key = tokens[0]

        if saw_data or key not in KNOWN_HEADERS:
            if key in KNOWN_HEADERS:
                raise CubeError(
                    "LUT_PARSE_ERROR", f"第 {line_no} 行：数据之后出现 header"
                )
            try:
                float(key)
            except ValueError as exc:
                raise CubeError(
                    "LUT_UNSUPPORTED", f"未知的 .cube 关键字: {key}"
                ) from exc
            if size is None:
                raise CubeError(
                    "LUT_PARSE_ERROR", f"第 {line_no} 行：数据出现在 LUT_3D_SIZE 之前"
                )
            if len(tokens) != 3:
                raise CubeError(
                    "LUT_PARSE_ERROR", f"第 {line_no} 行：应为 3 个数值"
                )
            saw_data = True
            for token in tokens:
                values.append(_parse_float(token, sample=True))
            continue

        if key == "TITLE":
            if saw_title:
                raise CubeError("LUT_PARSE_ERROR", "重复的 TITLE")
            saw_title = True
            rest = line[5:].strip()
            if len(rest) >= 2 and rest.startswith('"') and rest.endswith('"'):
                rest = rest[1:-1]
            if len(rest) > MAX_TITLE:
                raise CubeError("LUT_UNSUPPORTED", "TITLE 超过 256 个字符")
            title = "".join(ch for ch in rest if ch >= " " or ch == "\t")
            continue

        if key == "LUT_3D_SIZE":
            if size is not None:
                raise CubeError("LUT_PARSE_ERROR", "重复的 LUT_3D_SIZE")
            if len(tokens) != 2:
                raise CubeError("LUT_PARSE_ERROR", "无效的 LUT_3D_SIZE")
            raw_size = _parse_float(tokens[1], sample=False)
            if not raw_size.is_integer() or not 2 <= int(raw_size) <= 65:
                raise CubeError(
                    "LUT_UNSUPPORTED", "LUT_3D_SIZE 必须是 [2, 65] 内的整数"
                )
            size = int(raw_size)
            expected = size * size * size * 3
            continue

        if key in ("DOMAIN_MIN", "DOMAIN_MAX"):
            if key == "DOMAIN_MIN":
                if saw_min:
                    raise CubeError("LUT_PARSE_ERROR", "重复的 DOMAIN_MIN")
                saw_min = True
            else:
                if saw_max:
                    raise CubeError("LUT_PARSE_ERROR", "重复的 DOMAIN_MAX")
                saw_max = True
            if len(tokens) != 4:
                raise CubeError("LUT_PARSE_ERROR", f"无效的 {key}")
            parsed = [
                _parse_float(token, sample=False) for token in tokens[1:]
            ]
            if key == "DOMAIN_MIN":
                domain_min = parsed
            else:
                domain_max = parsed
            continue

        raise CubeError("LUT_UNSUPPORTED", f"不支持的 .cube 功能: {key}")

    if size is None:
        raise CubeError("LUT_PARSE_ERROR", "缺少 LUT_3D_SIZE")
    for low, high in zip(domain_min, domain_max):
        if not high > low:
            raise CubeError("LUT_PARSE_ERROR", "DOMAIN_MAX 必须大于 DOMAIN_MIN")
    if len(values) != expected:
        raise CubeError(
            "LUT_PARSE_ERROR",
            f"数据行数 {len(values) // 3} 与 LUT_3D_SIZE={size} 不匹配",
        )

    samples = np.asarray(values, dtype=np.float32).reshape(-1, 3)
    return CubeLut(
        path=file_path,
        size=size,
        domain_min=tuple(domain_min),
        domain_max=tuple(domain_max),
        title=title,
        samples=samples,
        sha256=digest,
    )
