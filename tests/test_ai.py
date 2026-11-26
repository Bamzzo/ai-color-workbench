"""AI provider tests with an injected HTTP transport (T09)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import httpx

from ai.deepseek import DeepSeekProvider
from ai.offline import OfflineProvider
from ai.provider import AIError, AIConfig, build_provider, load_config
from baker.params import ColorParams


def _document(**overrides: float) -> dict:
    params = ColorParams.identity().as_dict()
    params.update(overrides)
    return {
        "schema_version": "2.0",
        "algorithm_version": "sdr-srgb-v2",
        "params": params,
    }


def _chat_response(content: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


class FakeTransport:
    """Records requests and replays queued responses/exceptions."""

    def __init__(self, replies: list[object]) -> None:
        self.replies = list(replies)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.replies:
            raise AssertionError("unexpected extra request")
        reply = self.replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


class DeepSeekTests(unittest.TestCase):
    def _provider(
        self,
        fake: FakeTransport,
        *,
        retries: int = 2,
        total_timeout: float = 20.0,
    ) -> DeepSeekProvider:
        config = AIConfig(
            provider="deepseek",
            base_url="https://api.deepseek.com",
            model="deepseek-flash",
            api_key="unit-test-key",
            timeout_seconds=5.0,
            connect_timeout_seconds=2.0,
            total_timeout_seconds=total_timeout,
            max_retries=retries,
        )
        provider = DeepSeekProvider(config, transport=fake.transport())
        # Keep the retry paths fast and deterministic.
        provider._backoff = lambda attempt, deadline: None  # type: ignore[assignment]
        return provider

    def test_t09_valid_output(self) -> None:
        fake = FakeTransport(
            [httpx.Response(200, json=_chat_response(json.dumps(_document(contrast=12))))]
        )
        provider = self._provider(fake)
        proposal = provider.generate("暖一点", ColorParams.identity())

        self.assertEqual(proposal.source, "ai")
        self.assertEqual(proposal.provider, "deepseek")
        self.assertAlmostEqual(proposal.params.contrast, 12.0)
        self.assertEqual(len(fake.requests), 1)

        request = fake.requests[0]
        self.assertEqual(str(request.url), "https://api.deepseek.com/chat/completions")
        self.assertEqual(request.headers["Authorization"], "Bearer unit-test-key")
        payload = json.loads(request.read())
        self.assertEqual(payload["model"], "deepseek-flash")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        # The protocol never carries pixels, EXIF or file paths.
        serialized = json.dumps(payload)
        self.assertNotIn("image", serialized.lower())
        self.assertNotIn("base64", serialized.lower())
        self.assertNotIn("C:\\", serialized)

    def test_t09_repair_after_one_bad_schema(self) -> None:
        bad = json.dumps({"schema_version": "1.0", "params": {}})
        good = json.dumps(_document(saturation=-10))
        fake = FakeTransport(
            [
                httpx.Response(200, json=_chat_response(bad)),
                httpx.Response(200, json=_chat_response(good)),
            ]
        )
        provider = self._provider(fake)
        proposal = provider.generate("淡一点", ColorParams.identity())

        self.assertEqual(len(fake.requests), 2)
        self.assertAlmostEqual(proposal.params.saturation, -10.0)
        repair_payload = json.loads(fake.requests[1].read())
        self.assertEqual(repair_payload["messages"][-1]["role"], "user")
        self.assertIn("修正", repair_payload["messages"][-1]["content"])

    def test_t09_two_invalid_outputs_fail_without_touching_params(self) -> None:
        bad = "not json at all"
        fake = FakeTransport(
            [
                httpx.Response(200, json=_chat_response(bad)),
                httpx.Response(200, json=_chat_response(bad)),
            ]
        )
        provider = self._provider(fake, retries=1)
        with self.assertRaises(AIError) as ctx:
            provider.generate("随便", ColorParams(contrast=5))
        self.assertEqual(ctx.exception.code, "AI_SCHEMA")
        self.assertEqual(len(fake.requests), 2)

    def test_t09_duplicate_keys_and_empty_content(self) -> None:
        base = json.dumps(_document())
        duplicate = base.replace(
            '"contrast": 0.0', '"contrast": 0.0, "contrast": 1.0', 1
        )
        self.assertIn('"contrast": 0.0, "contrast": 1.0', duplicate)
        for content, retries in ((duplicate, 0), ("", 0)):
            with self.subTest(content=content[:12]):
                fake = FakeTransport(
                    [httpx.Response(200, json=_chat_response(content))]
                )
                provider = self._provider(fake, retries=retries)
                with self.assertRaises(AIError) as ctx:
                    provider.generate("测试", ColorParams.identity())
                self.assertEqual(ctx.exception.code, "AI_SCHEMA")

    def test_t09_auth_error_is_not_retried(self) -> None:
        fake = FakeTransport([httpx.Response(401, text="unauthorized")])
        provider = self._provider(fake)
        with self.assertRaises(AIError) as ctx:
            provider.generate("测试", ColorParams.identity())
        self.assertEqual(ctx.exception.code, "AI_AUTH")
        self.assertEqual(len(fake.requests), 1)

    def test_t09_rate_limit_and_server_errors_retry_then_fail(self) -> None:
        for status, code in ((429, "AI_RATE_LIMIT"), (503, "AI_NETWORK")):
            with self.subTest(status=status):
                fake = FakeTransport(
                    [httpx.Response(status, text="busy"), httpx.Response(status, text="busy")]
                )
                provider = self._provider(fake, retries=1)
                with self.assertRaises(AIError) as ctx:
                    provider.generate("测试", ColorParams.identity())
                self.assertEqual(ctx.exception.code, code)
                self.assertEqual(len(fake.requests), 2)

    def test_t09_server_error_then_success(self) -> None:
        fake = FakeTransport(
            [
                httpx.Response(500, text="boom"),
                httpx.Response(
                    200, json=_chat_response(json.dumps(_document(exposure_ev=0.3)))
                ),
            ]
        )
        provider = self._provider(fake, retries=1)
        proposal = provider.generate("亮一点", ColorParams.identity())
        self.assertAlmostEqual(proposal.params.exposure_ev, 0.3)
        self.assertEqual(len(fake.requests), 2)

    def test_t09_timeout_is_retried(self) -> None:
        fake = FakeTransport(
            [
                httpx.ReadTimeout("read timed out"),
                httpx.ReadTimeout("read timed out"),
            ]
        )
        provider = self._provider(fake, retries=1)
        with self.assertRaises(AIError) as ctx:
            provider.generate("测试", ColorParams.identity())
        self.assertEqual(ctx.exception.code, "AI_NETWORK")
        self.assertEqual(len(fake.requests), 2)

    def test_t09_oversized_response_rejected(self) -> None:
        fake = FakeTransport([httpx.Response(200, content=b"x" * (64 * 1024 + 10))])
        provider = self._provider(fake, retries=0)
        with self.assertRaises(AIError) as ctx:
            provider.generate("测试", ColorParams.identity())
        self.assertEqual(ctx.exception.code, "AI_SCHEMA")

    def test_t09_cancel_and_deadline(self) -> None:
        fake = FakeTransport([])
        provider = self._provider(fake)
        event = threading.Event()
        event.set()
        with self.assertRaises(AIError) as ctx:
            provider.generate("测试", ColorParams.identity(), cancel_event=event)
        self.assertEqual(ctx.exception.code, "CANCELLED")
        self.assertEqual(len(fake.requests), 0)

        immediate = self._provider(fake, total_timeout=1.0)
        with self.assertRaises(AIError) as ctx:
            immediate.generate("测试", ColorParams.identity())
        self.assertEqual(ctx.exception.code, "AI_NETWORK")
        self.assertEqual(len(fake.requests), 0)

    def test_t09_empty_intent_rejected(self) -> None:
        fake = FakeTransport([])
        provider = self._provider(fake)
        with self.assertRaises(AIError) as ctx:
            provider.generate("   ", ColorParams.identity())
        self.assertEqual(ctx.exception.code, "AI_SCHEMA")


class ConfigAndOfflineTests(unittest.TestCase):
    def test_offline_provider_is_selected_without_key(self) -> None:
        config = AIConfig(api_key="")
        self.assertFalse(config.configured)
        self.assertIsInstance(build_provider(config), OfflineProvider)

    def test_offline_structured_chip_not_warm_template(self) -> None:
        provider = OfflineProvider()
        from baker.params import load_preset

        intent = (
            "清透日系：曝光 +0.20 EV 提亮整体，高光 -12 压住天空，阴影 +15 打开暗部细节；"
            "色温 +6、色调 +2 保持中性微暖；饱和 -8、自然饱和 +6 降低浓郁度。"
        )
        proposal = provider.generate(intent, ColorParams.identity())
        warm, _ = load_preset("warm")
        soft, _ = load_preset("soft")
        self.assertNotEqual(proposal.params, warm)
        self.assertNotEqual(proposal.params, soft)
        self.assertAlmostEqual(proposal.params.temperature, 6.0)
        self.assertAlmostEqual(proposal.params.exposure_ev, 0.2)

    def test_offline_presets(self) -> None:
        provider = OfflineProvider()
        cases = {
            "暖阳": "warm",
            "冷蓝夜景": "cool",
            "柔和低对比": "soft",
            "电影感青橙": "cinematic",
            "做成黑白": "mono",
        }
        for text, preset in cases.items():
            with self.subTest(text=text):
                proposal = provider.generate(text, ColorParams.identity())
                self.assertEqual(proposal.source, "offline")
                self.assertEqual(proposal.provider, "offline")
                self.assertIn("模板", proposal.summary)
                # Offline templates must agree with the shipped preset files.
                from baker.params import load_preset

                expected, _ = load_preset(preset)
                self.assertEqual(proposal.params, expected)

        identity = provider.generate("没有关键词", ColorParams.identity())
        self.assertTrue(identity.params.is_identity())

    def test_load_config_rejects_insecure_base_url(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "AI_BASE_URL": "http://api.example.com",
                "AI_API_KEY": "k",
            },
            clear=False,
        ):
            with self.assertRaises(AIError) as ctx:
                load_config(env_file=Path(tempfile.gettempdir()) / "absent.env")
            self.assertEqual(ctx.exception.code, "AI_AUTH")

    def test_load_config_env_overrides_and_offline_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "AI_API_KEY=file-key\nAI_MODEL=file-model\nAI_OFFLINE_ONLY=0\n",
                encoding="utf-8",
            )
            with mock.patch.dict(
                os.environ,
                {"AI_API_KEY": "env-key", "AI_MODEL": "env-model"},
                clear=False,
            ):
                config = load_config(env_file)
            self.assertEqual(config.api_key, "env-key")
            self.assertEqual(config.model, "env-model")
            self.assertTrue(config.configured)

        with mock.patch.dict(os.environ, {"AI_OFFLINE_ONLY": "1"}, clear=False):
            config = load_config(Path(tempfile.gettempdir()) / "absent.env")
        self.assertTrue(config.offline_only)
        self.assertFalse(config.configured)
        self.assertIn("离线", config.status)

    def test_retired_model_is_flagged(self) -> None:
        config = AIConfig(api_key="k", model="deepseek-chat")
        self.assertIn("已停用", config.status)
        self.assertIn("deepseek-flash", config.status)
        current = AIConfig(api_key="k", model="deepseek-flash")
        self.assertNotIn("已停用", current.status)
        self.assertIn("deepseek-flash", current.status)

    def test_prompt_targets_v2_schema_and_carries_current_params(self) -> None:
        from ai.prompts import SYSTEM_PROMPT, build_user_message

        self.assertIn("sdr-srgb-v2", SYSTEM_PROMPT)
        self.assertIn('"split_shadow_amount"', SYSTEM_PROMPT)
        self.assertIn("幅度校准", SYSTEM_PROMPT)
        message = build_user_message("暖一点", ColorParams(contrast=7))
        self.assertIn('"contrast": 7.0', message)
        self.assertIn("暖一点", message)


if __name__ == "__main__":
    unittest.main()
