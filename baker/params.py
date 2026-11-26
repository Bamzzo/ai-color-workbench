"""ColorParams v1: strict parsing, normalization and cache keys.

AI output, preset files and manual UI values all pass through this module.
Nothing else in the application is allowed to invent parameter fields.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

import jsonschema

SCHEMA_VERSION = "2.0"
ALGORITHM_VERSION = "sdr-srgb-v2"

PARAM_KEYS = (
    "exposure_ev",
    "contrast",
    "temperature",
    "tint",
    "highlights",
    "shadows",
    "whites",
    "blacks",
    "saturation",
    "vibrance",
    "hue",
    "split_shadow_hue",
    "split_shadow_amount",
    "split_highlight_hue",
    "split_highlight_amount",
    "split_balance",
)

PARAM_RANGES = {
    "exposure_ev": (-2.0, 2.0),
    "contrast": (-100.0, 100.0),
    "temperature": (-100.0, 100.0),
    "tint": (-100.0, 100.0),
    "highlights": (-100.0, 100.0),
    "shadows": (-100.0, 100.0),
    "whites": (-100.0, 100.0),
    "blacks": (-100.0, 100.0),
    "saturation": (-100.0, 100.0),
    "vibrance": (-100.0, 100.0),
    "hue": (-180.0, 180.0),
    "split_shadow_hue": (0.0, 360.0),
    "split_shadow_amount": (0.0, 100.0),
    "split_highlight_hue": (0.0, 360.0),
    "split_highlight_amount": (0.0, 100.0),
    "split_balance": (-100.0, 100.0),
}

PARAM_LABELS = {
    "exposure_ev": "曝光 (EV)",
    "contrast": "对比度",
    "temperature": "色温",
    "tint": "色调",
    "highlights": "高光",
    "shadows": "阴影",
    "whites": "白色",
    "blacks": "黑色",
    "saturation": "饱和度",
    "vibrance": "自然饱和",
    "hue": "色相旋转",
    "split_shadow_hue": "阴影色相",
    "split_shadow_amount": "阴影着色",
    "split_highlight_hue": "高光色相",
    "split_highlight_amount": "高光着色",
    "split_balance": "分离平衡",
}

BASIC_PARAMS = (
    "exposure_ev",
    "contrast",
    "temperature",
    "tint",
    "highlights",
    "shadows",
    "whites",
    "blacks",
    "saturation",
    "vibrance",
    "hue",
)

SPLIT_PARAMS = (
    "split_shadow_hue",
    "split_shadow_amount",
    "split_highlight_hue",
    "split_highlight_amount",
    "split_balance",
)

PARAM_GROUPS = (("基础", BASIC_PARAMS), ("分离色调", SPLIT_PARAMS))

# Hue-style parameters are shown in degrees; everything else as signed units.
HUE_PARAMS = frozenset({"hue", "split_shadow_hue", "split_highlight_hue"})

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"
SCHEMA_PATH = SCHEMA_DIR / "color_params.v2.schema.json"
LEGACY_SCHEMA_PATH = SCHEMA_DIR / "color_params.v1.schema.json"
PRESET_DIR = ROOT / "presets"


class ParamError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _load_schema(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ParamError("SCHEMA_MISSING", f"无法读取参数 schema: {exc}") from exc


_VALIDATORS = {
    "1.0": jsonschema.Draft202012Validator(_load_schema(LEGACY_SCHEMA_PATH)),
    SCHEMA_VERSION: jsonschema.Draft202012Validator(_load_schema(SCHEMA_PATH)),
}


class _DuplicateKey(ValueError):
    pass


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(f"重复的 JSON 键: {key}")
        result[key] = value
    return result


def _reject_constant(token: str) -> None:
    raise ParamError("SCHEMA_INVALID", f"不允许的数值: {token}")


def strict_json_loads(text: str) -> Any:
    """Parse JSON while rejecting duplicate keys and NaN/Infinity."""
    if not isinstance(text, str):
        raise ParamError("SCHEMA_INVALID", "JSON 内容必须是字符串")
    if text.startswith("\ufeff"):
        text = text[1:]
    try:
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_constant,
        )
    except ParamError:
        raise
    except _DuplicateKey as exc:
        raise ParamError("SCHEMA_INVALID", str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise ParamError(
            "SCHEMA_INVALID", f"JSON 解析失败: 第 {exc.lineno} 行 {exc.msg}"
        ) from exc


def _reject_bools_and_nonfinite(value: Any, path: str = "") -> None:
    if isinstance(value, bool):
        raise ParamError("SCHEMA_INVALID", f"{path or 'root'} 不能是布尔值")
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise ParamError("SCHEMA_INVALID", f"{path or 'root'} 不是有限数")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            _reject_bools_and_nonfinite(child, f"{path}.{key}" if path else str(key))
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _reject_bools_and_nonfinite(child, f"{path}[{index}]")


def _normalize_number(value: float) -> float:
    rounded = round(float(value), 6)
    if rounded == 0.0:
        return 0.0
    return rounded


def validate_params_document(document: Any) -> dict[str, float]:
    """Validate a ColorParams document and return normalized params.

    Schema v2 documents carry all sixteen fields. Legacy v1 documents (seven
    fields) remain readable: missing newer fields default to 0, so old presets
    and old AI replies keep their exact previous appearance.
    """
    if not isinstance(document, dict):
        raise ParamError("SCHEMA_INVALID", "根节点必须是对象")
    _reject_bools_and_nonfinite(document)

    version = document.get("schema_version")
    validator = _VALIDATORS.get(version) if isinstance(version, str) else None
    if validator is None:
        raise ParamError(
            "SCHEMA_INVALID", f"不支持的 schema_version: {version!r}"
        )

    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        path = ".".join(str(p) for p in first.path) or "root"
        raise ParamError("SCHEMA_INVALID", f"{path}: {first.message}")

    params = dict(document["params"])
    for key in PARAM_KEYS:
        if key not in params:
            params[key] = 0.0
    return normalize_params(params)


def normalize_params(params: Mapping[str, Any]) -> dict[str, float]:
    normalized: dict[str, float] = {}
    for key in PARAM_KEYS:
        value = float(params.get(key, 0.0))
        low, high = PARAM_RANGES[key]
        if not math.isfinite(value) or value < low or value > high:
            raise ParamError("SCHEMA_INVALID", f"{key} 超出范围 [{low}, {high}]")
        normalized[key] = _normalize_number(value)
    return normalized


def parse_params_text(text: str) -> dict[str, float]:
    return validate_params_document(strict_json_loads(text))


def load_params_file(path: str | Path) -> dict[str, float]:
    try:
        with Path(path).open("r", encoding="utf-8") as f:
            document = strict_json_loads(f.read())
    except OSError as exc:
        raise ParamError("SCHEMA_MISSING", f"无法读取参数文件: {exc}") from exc
    return validate_params_document(document)


@dataclass(frozen=True)
class ColorParams:
    exposure_ev: float = 0.0
    contrast: float = 0.0
    temperature: float = 0.0
    tint: float = 0.0
    highlights: float = 0.0
    shadows: float = 0.0
    whites: float = 0.0
    blacks: float = 0.0
    saturation: float = 0.0
    vibrance: float = 0.0
    hue: float = 0.0
    split_shadow_hue: float = 0.0
    split_shadow_amount: float = 0.0
    split_highlight_hue: float = 0.0
    split_highlight_amount: float = 0.0
    split_balance: float = 0.0

    @classmethod
    def identity(cls) -> "ColorParams":
        return cls()

    @classmethod
    def from_dict(cls, params: Mapping[str, Any]) -> "ColorParams":
        normalized = normalize_params(params)
        return cls(**normalized)

    def as_dict(self) -> dict[str, float]:
        return {key: float(getattr(self, key)) for key in PARAM_KEYS}

    def to_document(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "algorithm_version": ALGORITHM_VERSION,
            "params": self.as_dict(),
        }

    def with_updates(self, **updates: float) -> "ColorParams":
        merged = self.as_dict()
        for key, value in updates.items():
            if key not in PARAM_RANGES:
                raise ParamError("SCHEMA_INVALID", f"未知参数: {key}")
            merged[key] = value
        normalized = normalize_params(merged)
        return replace(self, **normalized)

    def is_identity(self) -> bool:
        return all(abs(value) < 1e-12 for value in self.as_dict().values())


def canonical_params(params: ColorParams | Mapping[str, Any]) -> str:
    values = (
        params.as_dict()
        if isinstance(params, ColorParams)
        else normalize_params(params)
    )
    payload = {
        "algorithm_version": ALGORITHM_VERSION,
        "params": {key: values[key] for key in PARAM_KEYS},
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def lut_cache_key(
    params: ColorParams | Mapping[str, Any],
    n: int,
    domain_min: tuple[float, float, float],
    domain_max: tuple[float, float, float],
    strength: float,
) -> str:
    import hashlib

    payload = {
        "canonical": canonical_params(params),
        "n": int(n),
        "domain_min": [float(v) for v in domain_min],
        "domain_max": [float(v) for v in domain_max],
        "strength": round(float(strength), 6),
    }
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_preset(name: str) -> tuple[ColorParams, str]:
    path = PRESET_DIR / f"{name}.json"
    params = ColorParams.from_dict(load_params_file(path))
    return params, path.name


def list_presets() -> list[tuple[str, str, ColorParams]]:
    labels = {
        "identity": "原图",
        "warm": "暖色",
        "cool": "冷色",
        "soft": "柔和",
        "cinematic": "电影感",
        "mono": "黑白",
    }
    out: list[tuple[str, str, ColorParams]] = []
    for key in ("identity", "warm", "cool", "soft", "cinematic", "mono"):
        params, _ = load_preset(key)
        out.append((key, labels[key], params))
    return out
