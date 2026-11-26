"""DeepSeek Chat Completions adapter with strict local validation."""

from __future__ import annotations

import json
import logging
import random
import threading
import time
import uuid

import httpx

from baker.params import (
    ColorParams,
    ParamError,
    parse_params_text,
)

from .prompts import MAX_INTENT_CHARS, SYSTEM_PROMPT, build_user_message
from .provider import AIError, AIConfig, Proposal, summary_from_params

LOGGER = logging.getLogger("ai_color.ai")
MAX_RESPONSE_BYTES = 64 * 1024


class _Retryable(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _repair_prompt(problem: str) -> str:
    return (
        "上一次输出不是合法的 ColorParams v2 文档（"
        + problem[:200]
        + "）。只返回修正后的 JSON 对象，不要 Markdown 或解释。"
    )


class DeepSeekProvider:
    name = "deepseek"

    def __init__(self, config: AIConfig, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        self.model = config.model
        # Dependency injection for fault-injection tests.
        self._transport = transport

    def generate(
        self,
        intent: str,
        current_params: ColorParams,
        cancel_event: threading.Event | None = None,
    ) -> Proposal:
        request_id = uuid.uuid4().hex[:10]
        intent = (intent or "").strip()[:MAX_INTENT_CHARS]
        if not intent:
            raise AIError("AI_SCHEMA", "调色描述为空")
        if cancel_event is not None and cancel_event.is_set():
            raise AIError("CANCELLED", "请求已取消")

        deadline = time.monotonic() + self.config.total_timeout_seconds
        base_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": build_user_message(intent, current_params),
            },
        ]
        messages = list(base_messages)
        max_attempts = 1 + self.config.max_retries
        attempt = 0
        repair_used = False

        while attempt < max_attempts:
            attempt += 1
            if cancel_event is not None and cancel_event.is_set():
                raise AIError("CANCELLED", "请求已取消")
            remaining = deadline - time.monotonic()
            if remaining <= 1.0:
                raise AIError("AI_NETWORK", "请求总时限已到")

            started = time.monotonic()
            try:
                content = self._post(messages, remaining, request_id)
            except _Retryable as exc:
                elapsed = (time.monotonic() - started) * 1000.0
                LOGGER.info(
                    "request_id=%s provider=%s model=%s attempt=%d elapsed_ms=%.1f code=%s",
                    request_id,
                    "deepseek",
                    self.model,
                    attempt,
                    elapsed,
                    exc.code,
                )
                if attempt >= max_attempts or time.monotonic() >= deadline:
                    raise AIError(exc.code, exc.message) from exc
                self._backoff(attempt, deadline)
                continue

            try:
                params = self._parse(content)
            except AIError as exc:
                if exc.code != "AI_SCHEMA":
                    raise
                LOGGER.info(
                    "request_id=%s provider=deepseek attempt=%d validation=%s",
                    request_id,
                    attempt,
                    exc.code,
                )
                if repair_used or attempt >= max_attempts:
                    raise AIError(
                        "AI_SCHEMA",
                        "模型输出未通过本地 Schema 校验；已保留当前参数",
                    ) from exc
                repair_used = True
                messages = list(base_messages) + [
                    {"role": "assistant", "content": content[:4000]},
                    {"role": "user", "content": _repair_prompt(str(exc))},
                ]
                continue

            LOGGER.info(
                "request_id=%s provider=deepseek attempt=%d elapsed_ms=%.1f code=OK",
                request_id,
                attempt,
                (time.monotonic() - started) * 1000.0,
            )
            return Proposal(
                params=params,
                summary=summary_from_params(params),
                source="ai",
                provider="deepseek",
                model=self.model,
            )

        raise AIError("AI_SCHEMA", "模型输出未通过校验")

    def _parse(self, content: str) -> ColorParams:
        if not content or not content.strip():
            raise AIError("AI_SCHEMA", "模型返回空内容")
        try:
            document = parse_params_text(content.strip())
            return ColorParams.from_dict(document)
        except ParamError as exc:
            raise AIError("AI_SCHEMA", exc.message) from exc
        except (ValueError, TypeError) as exc:
            raise AIError("AI_SCHEMA", f"参数解析失败: {exc}") from exc

    def _backoff(self, attempt: int, deadline: float) -> None:
        delay = min(2.0 ** (attempt - 1), 2.0) + random.uniform(0.0, 0.25)
        delay = min(delay, max(0.0, deadline - time.monotonic() - 0.2))
        if delay > 0:
            time.sleep(delay)

    def _post(
        self, messages: list[dict[str, str]], remaining: float, request_id: str
    ) -> str:
        cfg = self.config
        read_timeout = max(1.0, min(cfg.timeout_seconds, remaining))
        connect_timeout = max(1.0, min(cfg.connect_timeout_seconds, remaining))
        pool_timeout = max(0.5, min(cfg.pool_timeout_seconds, remaining))
        timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=read_timeout,
            pool=pool_timeout,
        )
        headers = {
            "Authorization": f"Bearer {cfg.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {
            "model": cfg.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": cfg.temperature,
            "max_tokens": 1200,
            "stream": False,
        }
        url = cfg.base_url + "/chat/completions"
        try:
            with httpx.Client(
                timeout=timeout,
                headers=headers,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                with client.stream("POST", url, json=payload) as response:
                    if response.status_code != 200:
                        snippet = b""
                        for chunk in response.iter_bytes():
                            snippet += chunk
                            if len(snippet) >= 2048:
                                break
                        raise self._status_error(response.status_code, snippet)

                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_RESPONSE_BYTES:
                            raise AIError("AI_SCHEMA", "模型响应超过 64 KiB 限制")
        except AIError:
            raise
        except httpx.TimeoutException as exc:
            raise _Retryable("AI_NETWORK", "网络超时") from exc
        except httpx.NetworkError as exc:
            raise _Retryable("AI_NETWORK", f"网络错误: {exc}") from exc
        except httpx.HTTPError as exc:
            raise _Retryable("AI_NETWORK", f"HTTP 客户端错误: {exc}") from exc

        try:
            data = json.loads(bytes(body).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AIError("AI_SCHEMA", "模型响应不是合法 JSON") from exc
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIError("AI_SCHEMA", "模型响应缺少 choices[0].message.content") from exc
        if not isinstance(content, str):
            raise AIError("AI_SCHEMA", "模型 content 不是字符串")
        return content

    @staticmethod
    def _status_error(status: int, body: bytes) -> Exception:
        detail = body.decode("utf-8", errors="replace")[:300]
        if status in (401, 403):
            return AIError("AI_AUTH", f"鉴权失败 (HTTP {status})")
        if status == 429:
            return _Retryable("AI_RATE_LIMIT", "请求过于频繁 (HTTP 429)")
        if status in (408, 425, 500, 502, 503, 504):
            return _Retryable("AI_NETWORK", f"服务暂时不可用 (HTTP {status})")
        return AIError("AI_NETWORK", f"HTTP {status}: {detail}")


__all__ = ["DeepSeekProvider", "SYSTEM_PROMPT"]
