"""AI provider interface, configuration and local summary text."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from baker.params import ColorParams, PARAM_KEYS, PARAM_LABELS, PARAM_RANGES


class AIError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Proposal:
    params: ColorParams
    summary: str
    source: str  # "ai" | "offline"
    provider: str
    model: str


@dataclass(frozen=True)
class AIConfig:
    provider: str = "deepseek"
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    api_key: str = ""
    timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 10.0
    total_timeout_seconds: float = 65.0
    pool_timeout_seconds: float = 5.0
    max_retries: int = 2
    temperature: float = 0.3
    offline_only: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.api_key) and not self.offline_only

    @property
    def status(self) -> str:
        if self.offline_only:
            return "离线模式（配置强制）"
        if not self.api_key:
            return "在线未配置（缺少 AI_API_KEY）"
        if self.model in RETIRED_MODELS:
            return (
                f"在线 · {self.provider} · {self.model}（该型号已停用，"
                "请改为 deepseek-flash）"
            )
        return f"在线 · {self.provider} · {self.model}"


# DeepSeek retired these aliases on 2026-07-24; new integrations must use the
# version-independent id `deepseek-flash` (V4.1 Flash).
RETIRED_MODELS = frozenset({"deepseek-chat", "deepseek-reasoner"})


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def _float_env(
    name: str, default: float, minimum: float = 1.0, maximum: float | None = None
) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value < minimum or value != value:  # NaN check
        return default
    if maximum is not None and value > maximum:
        return default
    return value


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def load_config(env_file: str | Path | None = None) -> AIConfig:
    """Load .env, then let process environment win (override=False)."""
    if env_file is None:
        from app.paths import ENV_FILE

        env_file = ENV_FILE
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=Path(env_file), override=False)
    except Exception:
        # Missing .env is normal; only environment variables are used.
        pass

    provider = (os.environ.get("AI_PROVIDER") or "deepseek").strip().lower()
    base_url = (os.environ.get("AI_BASE_URL") or "https://api.deepseek.com").strip()
    model = (os.environ.get("AI_MODEL") or "deepseek-flash").strip()
    # DEEPSEEK_API_KEY 为历史/兼容写法，与 AI_API_KEY 等价。
    api_key = (
        os.environ.get("AI_API_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
    ).strip()

    parsed = urlparse(base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username:
        raise AIError(
            "AI_AUTH",
            "AI_BASE_URL 必须是 https 地址，且不能包含账号信息",
        )

    return AIConfig(
        provider=provider,
        base_url=base_url.rstrip("/"),
        model=model,
        api_key=api_key,
        timeout_seconds=_float_env("AI_TIMEOUT_SECONDS", 30.0),
        connect_timeout_seconds=_float_env("AI_CONNECT_TIMEOUT_SECONDS", 10.0),
        total_timeout_seconds=_float_env("AI_TOTAL_TIMEOUT_SECONDS", 65.0),
        pool_timeout_seconds=_float_env("AI_POOL_TIMEOUT_SECONDS", 5.0),
        max_retries=_int_env("AI_MAX_RETRIES", 2, 0, 5),
        temperature=_float_env("AI_TEMPERATURE", 0.3, 0.0, 1.5),
        offline_only=_truthy(os.environ.get("AI_OFFLINE_ONLY")),
    )


def summary_from_params(params: ColorParams) -> str:
    parts: list[str] = []
    for key in PARAM_KEYS:
        value = float(getattr(params, key))
        if abs(value) < 1e-9:
            continue
        label = PARAM_LABELS.get(key, key)
        if key == "exposure_ev":
            parts.append(f"{label} {value:+.2f}")
        elif key.endswith("_hue"):
            parts.append(f"{label} {value:.0f}°")
        else:
            parts.append(f"{label} {value:+.0f}")
    if not parts:
        return "原图参数：全部为 0，不做颜色变化"
    text = "全局调色：" + "，".join(parts)
    if len(text) > 300:
        text = text[:297] + "…"
    return text


def build_provider(config: AIConfig):
    if not config.configured:
        from .offline import OfflineProvider

        return OfflineProvider()
    if config.provider != "deepseek":
        raise AIError(
            "AI_AUTH",
            f"暂未实现 provider={config.provider}；P0 仅支持 deepseek 与离线模板",
        )
    from .deepseek import DeepSeekProvider

    return DeepSeekProvider(config)


__all__ = [
    "AIError",
    "AIConfig",
    "Proposal",
    "load_config",
    "build_provider",
    "summary_from_params",
    "PARAM_RANGES",
]
