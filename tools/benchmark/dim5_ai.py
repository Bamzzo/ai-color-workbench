"""Dimension 5 - AI intent parsing accuracy and robustness.

24 Chinese instructions in five families:

============================  ====  ==================================
family                        n     what it probes
============================  ====  ==================================
单一参数微调                   6     one parameter, explicit direction
复合氛围描述                   6     several parameters from an atmosphere
增量微调                       4     "再暖一点" relative to current params
极端/边界指令                  4     "拉到最亮" (range saturation)
无关噪声                       4     must not change any parameter
============================  ====  ==================================

For every case the benchmark records schema validity, whether the response
touches a parameter range boundary, whether the produced parameters move in the
physically expected direction, and the end-to-end latency.

``OfflineProvider`` is always evaluated. ``DeepSeekProvider`` is added only when
``--online`` is passed *and* an API key is configured.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import common

TOL = 1e-9
CATEGORY_LABELS = {
    "single": "单维微调",
    "compound": "复合氛围",
    "incremental": "增量微调",
    "extreme": "极端/边界",
    "noise": "无关噪声",
}


@dataclass(frozen=True)
class Check:
    op: str  # "gt" | "lt" | "le" | "ge" | "unchanged"
    keys: tuple[str, ...]
    value: float = 0.0
    mode: str = "all"  # "all" | "any"

    def as_dict(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "keys": list(self.keys),
            "value": self.value,
            "mode": self.mode,
        }


@dataclass(frozen=True)
class Case:
    case_id: str
    category: str
    intent: str
    expect: str
    checks: tuple[Check, ...]
    current: str = "identity"


CASES: tuple[Case, ...] = (
    # --- single-dimension tweaks -------------------------------------------
    Case("S1", "single", "把画面整体调亮一点", "曝光上升", (Check("gt", ("exposure_ev",)),)),
    Case("S2", "single", "画面太亮了，帮我压暗一些", "曝光下降", (Check("lt", ("exposure_ev",)),)),
    Case("S3", "single", "增加一点对比度", "对比度上升", (Check("gt", ("contrast",)),)),
    Case("S4", "single", "把饱和度降下来一点", "饱和度下降", (Check("lt", ("saturation",)),)),
    Case("S5", "single", "整体调得偏暖一些", "色温上升", (Check("gt", ("temperature",)),)),
    Case("S6", "single", "把高光压一压", "高光下降", (Check("lt", ("highlights",)),)),
    # --- compound atmosphere descriptions ----------------------------------
    Case(
        "M1",
        "compound",
        "黄昏暖调，同时压住高光",
        "色温上升 + 高光下降",
        (Check("gt", ("temperature",)), Check("lt", ("highlights",))),
    ),
    Case(
        "M2",
        "compound",
        "清冷通透的日系氛围",
        "色温下降 + 曝光上升",
        (Check("lt", ("temperature",)), Check("gt", ("exposure_ev",))),
    ),
    Case(
        "M3",
        "compound",
        "电影感的青橙色调",
        "分离色调双侧着色",
        (
            Check("gt", ("split_shadow_amount",)),
            Check("gt", ("split_highlight_amount",)),
        ),
    ),
    Case(
        "M4",
        "compound",
        "黑白纪实风格，加强对比",
        "饱和度归零 + 对比度上升",
        (Check("le", ("saturation",), -90.0), Check("gt", ("contrast",))),
    ),
    Case("M5", "compound", "柔和低对比的雾面感", "对比度下降", (Check("lt", ("contrast",)),)),
    Case(
        "M6",
        "compound",
        "鲜艳浓郁的风光大片",
        "色彩浓度上升（饱和度或自然饱和度）",
        (Check("gt", ("saturation", "vibrance"), mode="any"),),
    ),
    # --- incremental micro-tuning ------------------------------------------
    Case(
        "I1",
        "incremental",
        "再暖一点",
        "在当前暖色基础上色温继续上升",
        (Check("gt", ("temperature",)),),
        current="warm",
    ),
    Case(
        "I2",
        "incremental",
        "高光再压一点",
        "在当前基础上高光继续下降",
        (Check("lt", ("highlights",)),),
        current="warm",
    ),
    Case(
        "I3",
        "incremental",
        "饱和度再高一些",
        "在当前基础上饱和度继续上升",
        (Check("gt", ("saturation",)),),
        current="warm",
    ),
    Case(
        "I4",
        "incremental",
        "对比再强一点",
        "在当前基础上对比度继续上升",
        (Check("gt", ("contrast",)),),
        current="warm",
    ),
    # --- extreme / boundary instructions -----------------------------------
    Case(
        "X1",
        "extreme",
        "曝光拉到最亮",
        "曝光接近 +2 EV 上界",
        (Check("ge", ("exposure_ev",), 1.5),),
    ),
    Case(
        "X2",
        "extreme",
        "饱和度全部去掉，越灰越好",
        "饱和度贴近 -100 下界",
        (Check("le", ("saturation",), -90.0),),
    ),
    Case(
        "X3",
        "extreme",
        "色温调到最冷",
        "色温贴近 -100 下界",
        (Check("le", ("temperature",), -50.0),),
    ),
    Case(
        "X4",
        "extreme",
        "对比度拉到极限",
        "对比度贴近 +100 上界",
        (Check("ge", ("contrast",), 50.0),),
    ),
    # --- irrelevant / noisy input ------------------------------------------
    Case(
        "N1",
        "noise",
        "帮我写个冒泡排序",
        "参数保持不变",
        (Check("unchanged", ("*",)),),
    ),
    Case("N2", "noise", "今天天气怎么样", "参数保持不变", (Check("unchanged", ("*",)),)),
    Case("N3", "noise", "1+1 等于几", "参数保持不变", (Check("unchanged", ("*",)),)),
    Case(
        "N4",
        "noise",
        "把这段文字翻译成英文",
        "参数保持不变",
        (Check("unchanged", ("*",)),),
    ),
)


def _current_params(name: str) -> Any:
    from baker.params import ColorParams, load_preset

    if name == "identity":
        return ColorParams.identity()
    params, _ = load_preset(name)
    return params


def _evaluate_checks(before: Any, after: Any, checks: tuple[Check, ...]) -> tuple[bool, list[str]]:
    from baker.params import PARAM_KEYS

    results: list[str] = []
    all_ok = True
    for check in checks:
        keys = PARAM_KEYS if check.keys == ("*",) else list(check.keys)
        if check.op == "unchanged":
            ok = all(
                abs(float(getattr(after, key)) - float(getattr(before, key))) <= TOL
                for key in keys
            )
        else:
            outcomes = []
            for key in keys:
                a = float(getattr(after, key))
                b = float(getattr(before, key))
                if check.op == "gt":
                    outcomes.append((a - b) > TOL)
                elif check.op == "lt":
                    outcomes.append((a - b) < -TOL)
                elif check.op == "le":
                    outcomes.append(a <= check.value)
                elif check.op == "ge":
                    outcomes.append(a >= check.value)
                else:
                    raise ValueError(f"unknown check op {check.op!r}")
            ok = any(outcomes) if check.mode == "any" else all(outcomes)
        all_ok = all_ok and ok
        results.append(f"{check.op}({','.join(keys)})={'PASS' if ok else 'FAIL'}")
    return all_ok, results


def _boundary_hits(params: Any) -> list[str]:
    from baker.params import PARAM_RANGES

    hits = []
    for key, (low, high) in PARAM_RANGES.items():
        value = float(getattr(params, key))
        if abs(value - low) <= 1e-9 or abs(value - high) <= 1e-9:
            hits.append(f"{key}={value:g}")
    return hits


def _evaluate_provider(
    name: str,
    model: str,
    factory: Callable[[], Any],
    results_dir: Any,
) -> dict[str, Any]:
    provider = factory()
    rows: list[dict[str, Any]] = []
    for case in CASES:
        before = _current_params(case.current)
        started = time.perf_counter()
        error = ""
        proposal = None
        try:
            proposal = provider.generate(case.intent, before)
        except Exception as exc:  # provider failures are data, not crashes
            error = f"{type(exc).__name__}: {exc}"
        latency_ms = (time.perf_counter() - started) * 1000.0

        valid = proposal is not None and not error
        direction_ok = False
        check_text: list[str] = []
        boundary: list[str] = []
        after_dict: dict[str, float] = {}
        if proposal is not None:
            after = proposal.params
            after_dict = after.as_dict()
            direction_ok, check_text = _evaluate_checks(before, after, case.checks)
            boundary = _boundary_hits(after)

        rows.append(
            {
                "case": case.case_id,
                "category": case.category,
                "intent": case.intent,
                "expect": case.expect,
                "current": case.current,
                "latency_ms": round(latency_ms, 4),
                "valid": valid,
                "boundary": boundary,
                "direction_ok": direction_ok,
                "checks": check_text,
                "params": after_dict,
                "error": error,
            }
        )
        print(
            f"        {case.case_id} {'OK ' if direction_ok else 'MISS'}"
            f" {latency_ms:8.2f} ms  {case.intent}",
            flush=True,
        )

    return {"provider": name, "model": model, "cases": rows, "summary": _summarise(rows)}


def _summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    import numpy as np

    total = len(rows)
    latencies = [row["latency_ms"] for row in rows]
    summary: dict[str, Any] = {
        "total": total,
        "first_pass_valid_rate": round(100.0 * sum(row["valid"] for row in rows) / total, 2),
        "clamping_rate": round(
            100.0 * sum(1 for row in rows if row["boundary"]) / total, 2
        ),
        "direction_accuracy": round(
            100.0 * sum(row["direction_ok"] for row in rows) / total, 2
        ),
        "latency_mean_ms": round(float(np.mean(latencies)), 4),
        "latency_p95_ms": round(float(np.percentile(latencies, 95.0)), 4),
        "latency_max_ms": round(float(np.max(latencies)), 4),
    }
    by_category: dict[str, Any] = {}
    for category in CATEGORY_LABELS:
        subset = [row for row in rows if row["category"] == category]
        if not subset:
            continue
        by_category[category] = {
            "label": CATEGORY_LABELS[category],
            "total": len(subset),
            "direction_accuracy": round(
                100.0 * sum(row["direction_ok"] for row in subset) / len(subset), 2
            ),
            "mean_latency_ms": round(
                float(np.mean([row["latency_ms"] for row in subset])), 4
            ),
        }
    summary["by_category"] = by_category
    return summary


def _load_baseline() -> dict[str, Any] | None:
    """Load the pre-optimisation offline snapshot kept for the ablation table."""
    path = Path(__file__).with_name("offline_baseline.json")
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or "summary" not in data:
        return None
    return data


def run(online: bool = False, results_dir: Any = None) -> dict[str, Any]:
    from ai.offline import OfflineProvider
    from ai.provider import AIError, build_provider, load_config

    print(f"  [dim5] evaluating OfflineProvider on {len(CASES)} instructions ...", flush=True)
    providers = [
        _evaluate_provider("offline", "template+rules", OfflineProvider, results_dir)
    ]

    online_note = "未请求在线评测（未传入 --online）"
    if online:
        try:
            config = load_config()
        except AIError as exc:
            config = None
            online_note = f"在线配置无效：{exc.message}"
        else:
            if not config.configured:
                online_note = "在线未配置（缺少 AI_API_KEY），已跳过"
            else:
                print(
                    f"  [dim5] evaluating {config.provider}/{config.model} on "
                    f"{len(CASES)} instructions ...",
                    flush=True,
                )
                providers.append(
                    _evaluate_provider(
                        config.provider,
                        config.model,
                        lambda: build_provider(config),
                        results_dir,
                    )
                )
                online_note = f"已评测 {config.provider}/{config.model}"

    baseline = _load_baseline()
    if baseline is not None:
        print(
            f"  [dim5] ablation baseline: {baseline['summary']['direction_accuracy']:.2f}%"
            f" ({baseline.get('label', 'before')})",
            flush=True,
        )

    return {
        "instructions": [case.intent for case in CASES],
        "family_counts": {
            CATEGORY_LABELS[key]: sum(1 for case in CASES if case.category == key)
            for key in CATEGORY_LABELS
        },
        "providers": providers,
        "online_note": online_note,
        "baseline": baseline,
    }


__all__ = ["CASES", "CATEGORY_LABELS", "Check", "run"]
