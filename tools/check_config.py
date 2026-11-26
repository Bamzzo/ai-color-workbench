"""Fail-safe .env inspection: never prints secret values."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.provider import AIError, load_config  # noqa: E402

QUOTES = "\"'"


def mask(key: str, value: str) -> str:
    if not value:
        return "<empty>"
    if "KEY" in key.upper() or "TOKEN" in key.upper() or "SECRET" in key.upper():
        return f"<set, {len(value)} chars>"
    return value


def main() -> int:
    path = ROOT / ".env"
    print("env_exists:", path.is_file())
    if not path.is_file():
        return 1
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip(QUOTES)
        print(f"{key} = {mask(key, value)}")

    print("---")
    try:
        config = load_config()
    except AIError as exc:
        print("CONFIG_ERROR", exc.code, exc.message)
        return 2
    print("provider:", config.provider)
    print("model:", config.model)
    print("base_url:", config.base_url)
    print("configured:", config.configured)
    print("status:", config.status)
    print("total_timeout_s:", config.total_timeout_seconds)
    print("max_retries:", config.max_retries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
