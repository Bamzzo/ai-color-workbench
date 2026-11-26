"""Deterministic offline intent resolver used when no key is configured.

Two stages, in priority order:

1. **Style presets** - a whole-look template (``mono``/``cinematic``/``warm``/
   ``cool``/``soft``/``identity``) matched by keyword. Used when the prompt is
   *only* describing a look ("暖阳", "电影感青橙"): the reply is byte-identical
   to the shipped preset file.
2. **Parameter-level rules** - when the prompt carries an explicit parameter
   ("高光", "对比度"), a degree modifier ("再/更/一点") or an extreme marker
   ("最/极限/全部去掉"), the resolver applies a delta on top of
   ``current_params`` (or snaps the parameter to a ``PARAM_RANGES`` endpoint)
   and clamps the result. This is what makes "再暖一点" and "曝光拉到最亮"
   behave like an edit rather than a template swap.

Neither stage matching means the prompt is unrelated ("写个冒泡排序"): the
current parameters are returned untouched, so irrelevant chatter can never
silently overwrite an edit.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass

from baker.params import PARAM_KEYS, PARAM_RANGES, ColorParams, load_preset

from .provider import AIError, Proposal, summary_from_params

_WARM = (
    "暖色",
    "暖调",
    "暖阳",
    "夕阳",
    "金色",
    "温馨",
    "阳光",
    "活跃",
    "明快",
    "浓郁",
    "warm",
    "golden",
    "sunset",
    "cozy",
    "vivid",
    "punchy",
)
_COOL = (
    "冷色",
    "冷调",
    "蓝",
    "夜景",
    "清冷",
    "雪",
    "冷调",
    "cool",
    "blue",
    "night",
    "cold",
    "teal blue",
)
_SOFT = (
    "柔",
    "淡",
    "低对比",
    "轻盈",
    "雾",
    "通透",
    "清透",
    "清新",
    "明亮",
    "日系",
    "干净",
    "空气感",
    "soft",
    "pastel",
    "faded",
    "airy",
    "clean",
    "bright",
    "japanese",
)
_CINEMA = (
    "电影",
    "青橙",
    "cinema",
    "cinematic",
    "teal",
    "orange",
    "港风",
    "胶片",
    "film",
    "analog",
)
_MONO = ("黑白", "单色", "mono", "monochrome", "bw", "black and white")
_IDENTITY = ("原图", "不做", "保持原样", "identity", "none", "as is")

# 语义修饰：在命中的基础模板上叠加微调，避免“整套模板硬套”的塑料感。
_TONE_TRANSLUCENT = (
    "通透",
    "清透",
    "清新",
    "明亮",
    "日系",
    "干净",
    "空气感",
    "bright",
    "clean",
    "airy",
    "japanese",
)
_TONE_VIVID = ("活跃", "明快", "鲜艳", "浓郁", "饱满", "vivid", "punchy", "rich")

_TRANSLUCENT_SHIFT = {"exposure_ev": 0.2, "shadows": 15.0, "highlights": -12.0}
_VIVID_SHIFT = {"vibrance": 22.0, "saturation": 10.0}

# Style groups in match priority order (most specific look first).
_STYLE_GROUPS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("mono", _MONO, "匹配到黑白倾向，使用黑白模板"),
    ("cinematic", _CINEMA, "匹配到电影感倾向，使用青橙模板"),
    ("warm", _WARM, "匹配到暖色倾向，使用暖色模板"),
    ("cool", _COOL, "匹配到冷色倾向，使用冷色模板"),
    ("soft", _SOFT, "匹配到柔和/通透倾向，使用柔和模板"),
    ("identity", _IDENTITY, "匹配到原图意图，回到中性参数"),
)

# ---- parameter-level rule engine -----------------------------------------

# 程度修饰词：命中后使用小步长，并在 current_params 上做增量。
_INCREMENTAL_MARKERS = (
    "再",
    "更",
    "一点",
    "一些",
    "稍微",
    "略微",
    "稍",
    "继续",
    "进一步",
    "little",
    "slightly",
    "more",
)
# 极值修饰词：命中后直接把参数推到 PARAM_RANGES 的端点。
_EXTREME_MARKERS = (
    "最",
    "极限",
    "极致",
    "拉满",
    "全部去掉",
    "全去掉",
    "全部",
    "彻底",
    "完全",
    "到底",
    "越",
    "max",
    "maximum",
    "fully",
    "extreme",
)

_STEP_SMALL_EV = 0.25
_STEP_SMALL = 15.0
_STEP_NORMAL_EV = 0.40
_STEP_NORMAL = 25.0

# Cue words are looked up in a window around the parameter noun so that
# "高光压一压" does not leak into the exposure channel.
_WINDOW = 6


@dataclass(frozen=True)
class _ParamSpec:
    key: str
    nouns: tuple[str, ...]
    up: tuple[str, ...]
    down: tuple[str, ...]


_SPECS: tuple[_ParamSpec, ...] = (
    _ParamSpec(
        "exposure_ev",
        ("曝光", "亮度", "亮度值", "曝光度"),
        ("提亮", "调亮", "加亮", "亮", "提高曝光", "增加曝光", "brighten", "brighter"),
        ("压暗", "变暗", "调暗", "太亮", "过曝", "降低曝光", "减少曝光", "暗", "darken"),
    ),
    _ParamSpec(
        "contrast",
        ("对比度", "对比", "反差"),
        ("加强", "增强", "增加", "提高", "提升", "拉", "加", "强", "高", "拉开", "more"),
        ("降低", "减弱", "减少", "压低", "降", "低", "弱", "柔", "平", "收", "less"),
    ),
    _ParamSpec(
        "temperature",
        ("色温", "冷暖", "白平衡"),
        ("暖", "偏暖", "加暖", "升温", "warm"),
        ("冷", "偏冷", "降温", "去暖", "cool"),
    ),
    _ParamSpec(
        "saturation",
        ("饱和度", "饱和", "色彩浓度", "浓度", "鲜艳度"),
        ("鲜艳", "浓郁", "饱满", "提高", "增加", "加强", "提升", "拉", "高", "加", "提", "vivid", "rich"),
        ("降", "低", "去", "灰", "减", "弱", "淡", "褪", "muted", "desaturate"),
    ),
    _ParamSpec(
        "highlights",
        ("高光", "亮部", "高亮"),
        ("提", "亮", "拉高", "恢复", "增加", "抬", "lift"),
        ("压", "降", "低", "收", "抑制", "减", "pull", "reduce"),
    ),
    _ParamSpec(
        "shadows",
        ("阴影", "暗部", "暗区"),
        ("提", "亮", "抬", "增加", "恢复", "lift"),
        ("压", "降", "低", "收", "加深", "crush"),
    ),
    _ParamSpec(
        "whites",
        ("白点", "高光白", "白色"),
        ("提", "加", "亮"),
        ("压", "降", "低", "收"),
    ),
    _ParamSpec(
        "blacks",
        ("黑点", "黑位", "黑色"),
        ("提", "抬", "加"),
        ("压", "沉", "降", "深"),
    ),
)

# "暖/冷" are adjectives rather than parameter nouns, so the temperature spec
# also fires on them directly. Exposure gets the same treatment for "亮/暗",
# but only when no other parameter noun is present in the prompt.
_TEMPERATURE_ADJECTIVES = ("暖", "冷", "warm", "cool")


def _hits(text: str, words: tuple[str, ...]) -> bool:
    return any(word.lower() in text for word in words)


def _window_polarity(text: str, noun: str, spec: _ParamSpec) -> int:
    """Decide +1/-1 for every occurrence of ``noun``; negative cues win."""
    start = 0
    while True:
        index = text.find(noun, start)
        if index < 0:
            return 0
        window = text[max(0, index - _WINDOW) : index + len(noun) + _WINDOW]
        if _hits(window, spec.down):
            return -1
        if _hits(window, spec.up):
            return 1
        start = index + len(noun)


def _exposure_polarity(text: str) -> int:
    spec = _SPECS[0]
    polarity = _window_polarity(text, "曝光", spec)
    if polarity:
        return polarity
    if _hits(text, ("压暗", "变暗", "调暗", "太亮", "过曝", "降低曝光", "暗一些", "暗一点")):
        return -1
    if _hits(text, ("提亮", "调亮", "加亮", "亮一些", "亮一点", "增加曝光", "提高曝光")):
        return 1
    if _hits(text, ("暗",)):
        return -1
    if _hits(text, ("亮", "bright")):
        return 1
    return 0


def _parse_directives(text: str) -> list[tuple[str, int]]:
    """Return [(param_key, direction)] in a deterministic order."""
    directives: list[tuple[str, int]] = []
    has_other_noun = any(
        _hits(text, spec.nouns) for spec in _SPECS if spec.key != "exposure_ev"
    )
    # Exposure also covers the bare 亮/暗 adjectives, so it is only allowed to
    # speak when no more specific parameter was named.
    if not has_other_noun:
        polarity = _exposure_polarity(text)
        if polarity:
            directives.append(("exposure_ev", polarity))
    else:
        polarity = _window_polarity(text, "曝光", _SPECS[0])
        if polarity:
            directives.append(("exposure_ev", polarity))

    for spec in _SPECS[1:]:
        polarity = 0
        for noun in spec.nouns:
            polarity = _window_polarity(text, noun, spec)
            if polarity:
                break
        if not polarity and spec.key == "temperature":
            if _hits(text, _TEMPERATURE_ADJECTIVES):
                # 暖 = raise, 冷 = lower; the adjective itself carries polarity.
                polarity = -1 if _hits(text, ("冷", "cool")) and not _hits(
                    text, ("暖", "warm")
                ) else 1
        if polarity:
            directives.append((spec.key, polarity))
    return directives


def _clamp(params: dict[str, float]) -> dict[str, float]:
    clamped: dict[str, float] = {}
    for key in PARAM_KEYS:
        low, high = PARAM_RANGES[key]
        value = float(params.get(key, 0.0))
        clamped[key] = min(max(value, low), high)
    return clamped


def _fmt_value(key: str, value: float) -> str:
    if key == "exposure_ev":
        return f"{value:+.2f}"
    if abs(value - round(value)) < 1e-9:
        return f"{value:+.0f}"
    return f"{value:+g}"


def _apply(
    base: ColorParams,
    directives: list[tuple[str, int]],
    *,
    extreme: bool,
    incremental: bool,
) -> tuple[ColorParams, list[str]]:
    """Apply deltas (or endpoint snaps) on ``base`` and describe the edit."""
    values = base.as_dict()
    notes: list[str] = []
    for key, direction in directives:
        low, high = PARAM_RANGES[key]
        if extreme:
            value = high if direction > 0 else low
            notes.append(f"{key} → {_fmt_value(key, value)}（推到量程端点）")
        else:
            if key == "exposure_ev":
                step = _STEP_SMALL_EV if incremental else _STEP_NORMAL_EV
            else:
                step = _STEP_SMALL if incremental else _STEP_NORMAL
            value = values[key] + direction * step
            notes.append(
                f"{key} {_fmt_value(key, values[key])} → {_fmt_value(key, value)}"
                f"（{'增量' if incremental else '标准'}步长 {_fmt_value(key, direction * step)}）"
            )
        values[key] = value
    return ColorParams.from_dict(_clamp(values)), notes


def _strip_style_words(text: str) -> str:
    """Remove style vocabulary so only the *edit* part of the prompt remains."""
    stripped = text
    for _, words, _ in _STYLE_GROUPS:
        for word in words:
            stripped = stripped.replace(word.lower(), " ")
    for word in _TONE_TRANSLUCENT + _TONE_VIVID:
        stripped = stripped.replace(word.lower(), " ")
    return re.sub(r"\s+", "", stripped)


_NUMERIC_ASSIGNMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:色温|temperature)\s*([+\-]\s*[\d.]+)", re.I), "temperature"),
    (re.compile(r"(?:色调|tint)\s*([+\-]\s*[\d.]+)", re.I), "tint"),
    (re.compile(r"曝光\s*([+\-]\s*[\d.]+)\s*(?:ev)?", re.I), "exposure_ev"),
    (re.compile(r"(?:高光|highlights)\s*([+\-]\s*[\d.]+)", re.I), "highlights"),
    (re.compile(r"(?:阴影|shadows)\s*([+\-]\s*[\d.]+)", re.I), "shadows"),
    (re.compile(r"(?:白色|whites)\s*([+\-]\s*[\d.]+)", re.I), "whites"),
    (re.compile(r"(?:黑色|blacks)\s*([+\-]\s*[\d.]+)", re.I), "blacks"),
    (re.compile(r"(?:饱和(?:度)?|saturation)\s*([+\-]\s*[\d.]+)", re.I), "saturation"),
    (re.compile(r"(?:自然饱和|vibrance)\s*([+\-]\s*[\d.]+)", re.I), "vibrance"),
    (re.compile(r"(?:对比(?:度)?|contrast)\s*([+\-]\s*[\d.]+)", re.I), "contrast"),
)


def _parse_numeric_assignments(text: str) -> dict[str, float]:
    """Structured chips like「色温 +6」— value is the grading target, not a template."""
    updates: dict[str, float] = {}
    for pattern, key in _NUMERIC_ASSIGNMENTS:
        match = pattern.search(text)
        if not match:
            continue
        raw = match.group(1).replace(" ", "")
        updates[key] = float(raw)
    return updates


def _has_numeric_color_ops(text: str) -> bool:
    return bool(_parse_numeric_assignments(text))


def _match_style(text: str) -> tuple[str, str] | None:
    scrubbed = text.replace("微暖", " ").replace("微冷", " ")
    for key, words, note in _STYLE_GROUPS:
        if _hits(scrubbed, words):
            return key, note
    return None


def _has_explicit_param(body: str) -> bool:
    return any(_hits(body, spec.nouns) for spec in _SPECS)


class OfflineProvider:
    name = "offline"
    model = "template+rules"

    def generate(
        self,
        intent: str,
        current_params: ColorParams,
        cancel_event: threading.Event | None = None,
    ) -> Proposal:
        if cancel_event is not None and cancel_event.is_set():
            raise AIError("CANCELLED", "请求已取消")

        text = (intent or "").strip().lower()
        numeric = _parse_numeric_assignments(text)
        if len(numeric) >= 2:
            merged = current_params.as_dict()
            for key, value in numeric.items():
                low, high = PARAM_RANGES[key]
                merged[key] = min(max(float(value), low), high)
            params = ColorParams.from_dict(merged)
            bits = [f"{k} {numeric[k]:+g}" for k in numeric]
            return Proposal(
                params=params,
                summary=f"按结构化数值解析：{', '.join(bits)}。{summary_from_params(params)}",
                source="offline",
                provider="offline",
                model=self.model,
            )

        style = _match_style(text) if text else None
        incremental = _hits(text, _INCREMENTAL_MARKERS)
        extreme = _hits(text, _EXTREME_MARKERS)
        body = _strip_style_words(text)
        explicit = _has_explicit_param(body)
        directives = _parse_directives(text) if (explicit or incremental or extreme) else []

        # Pure look description, or a style word we cannot turn into a delta:
        # fall back to the shipped template (byte-identical to the preset file).
        pure_style = style is not None and not (incremental or extreme or explicit or numeric)
        if pure_style or (
            style is not None and not directives and not _has_numeric_color_ops(text)
        ):
            return self._from_preset(style, text)

        if not directives:
            # 关键：无法匹配时绝不返回全 0 参数覆盖用户当前编辑。
            return Proposal(
                params=current_params,
                summary=(
                    "离线模式未能识别该描述，已保留当前参数不变。"
                    "可尝试「暖色胶片」「清透日系」「黑白」或「高光压一点」「曝光拉到最亮」。"
                ),
                source="offline",
                provider="offline",
                model=self.model,
            )

        # Relative edits accumulate on the user's current state. A look word
        # without a degree modifier becomes the base of the edit; extreme
        # commands stay surgical and only snap the named parameter.
        if (
            style is not None
            and not incremental
            and not extreme
            and not _has_numeric_color_ops(text)
        ):
            base, _ = load_preset(style[0])
            prefix = f"{style[1]}，在其基础上"
        else:
            base = current_params
            prefix = "在原有参数基础上"

        params, notes = _apply(
            base, directives, extreme=extreme, incremental=incremental
        )
        detail = "，".join(notes)
        mode = "极值" if extreme else ("增量" if incremental else "标准")
        return Proposal(
            params=params,
            summary=f"{prefix}按{mode}规则调整：{detail}。{summary_from_params(params)}",
            source="offline",
            provider="offline",
            model=self.model,
        )

    def _from_preset(self, style: tuple[str, str], text: str) -> Proposal:
        chosen, note = style
        base, _ = load_preset(chosen)
        shifts: dict[str, float] = {}
        if _hits(text, _TONE_TRANSLUCENT):
            shifts.update(_TRANSLUCENT_SHIFT)
        if _hits(text, _TONE_VIVID):
            shifts.update(_VIVID_SHIFT)

        params = base.with_updates(**shifts) if shifts else base
        extras = ""
        if shifts:
            bits = [f"{k} {v:+g}" for k, v in shifts.items()]
            extras = "；叠加 " + "，".join(bits)
        return Proposal(
            params=params,
            summary=f"{note}{extras}。{summary_from_params(params)}",
            source="offline",
            provider="offline",
            model="template",
        )


__all__ = ["OfflineProvider"]
