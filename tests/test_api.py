"""FastAPI layer smoke tests (phase 1)."""

from __future__ import annotations

import base64
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from fastapi.testclient import TestClient

from api.media_store import clear_registry_for_tests
from api.job_runner import clear_jobs_for_tests, get_job, JobStatus
from api.server import app
from baker.params import ColorParams

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "runtime" / "test-fixtures" / "pattern.png"
IDENTITY_CUBE = ROOT / "identity17.cube"


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_registry_for_tests()
        clear_jobs_for_tests()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        clear_registry_for_tests()
        clear_jobs_for_tests()

    def test_presets(self) -> None:
        response = self.client.get("/api/presets")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["code"], 0)
        keys = [item["key"] for item in body["data"]]
        self.assertEqual(
            keys,
            ["identity", "warm", "cool", "soft", "cinematic", "mono"],
        )

    def test_params_validate(self) -> None:
        payload = {"params": ColorParams.identity().as_dict()}
        response = self.client.post("/api/params/validate", json=payload)
        body = response.json()
        self.assertEqual(body["code"], 0)
        self.assertEqual(len(body["data"]["params"]), 16)

    def test_lut_bake_binary_layout(self) -> None:
        params = ColorParams.identity().with_updates(contrast=10).as_dict()
        response = self.client.post(
            "/api/lut/bake", json={"params": params, "size": 33}
        )
        body = response.json()
        self.assertEqual(body["code"], 0)
        data = body["data"]
        self.assertEqual(data["size"], 33)
        raw = base64.standard_b64decode(data["data_b64"])
        arr = np.frombuffer(raw, dtype=np.float32)
        self.assertEqual(arr.shape[0], 33 * 33 * 33 * 3)
        self.assertTrue(np.all(np.isfinite(arr)))

    def test_ai_offline_fallback(self) -> None:
        from ai.provider import AIError

        def raise_network(*_args, **_kwargs):
            raise AIError("AI_NETWORK", "offline mock")

        with mock.patch("api.server.build_provider", side_effect=raise_network):
            response = self.client.post(
                "/api/ai/propose",
                json={
                    "intent": "暖色夕阳",
                    "current_params": {},
                    "allow_offline_fallback": True,
                },
            )
        body = response.json()
        self.assertEqual(body["code"], 0)
        self.assertEqual(body["data"]["source"], "offline")
        self.assertIn("params", body["data"])

    def test_media_upload_and_histogram(self) -> None:
        self.assertTrue(FIXTURE.is_file(), f"missing fixture {FIXTURE}")
        with FIXTURE.open("rb") as handle:
            response = self.client.post(
                "/api/media/upload",
                files={"file": ("pattern.png", handle, "image/png")},
            )
        body = response.json()
        self.assertEqual(body["code"], 0)
        media_id = body["data"]["media_id"]
        content = self.client.get(f"/api/media/{media_id}/content")
        self.assertEqual(content.status_code, 200)

        hist = self.client.post("/api/histogram", json={"media_id": media_id})
        hbody = hist.json()
        self.assertEqual(hbody["code"], 0)
        self.assertEqual(len(hbody["data"]["r"]), 256)

    def test_lut_upload_cube(self) -> None:
        if not IDENTITY_CUBE.is_file():
            self.skipTest("identity17.cube missing")
        with IDENTITY_CUBE.open("rb") as handle:
            response = self.client.post(
                "/api/lut/upload_cube",
                files={"file": ("identity17.cube", handle, "text/plain")},
            )
        body = response.json()
        self.assertEqual(body["code"], 0)
        raw = base64.standard_b64decode(body["data"]["data_b64"])
        n = body["data"]["size"]
        self.assertEqual(len(raw), n * n * n * 3 * 4)

    def test_lut_upload_cube_keeps_domain(self) -> None:
        rows = [
            f"{r} {g} {b}"
            for b in (0.0, 1.0)
            for g in (0.0, 1.0)
            for r in (0.0, 1.0)
        ]
        text = "\n".join(
            [
                "LUT_3D_SIZE 2",
                "DOMAIN_MIN -0.25 0 0.1",
                "DOMAIN_MAX 1.5 1 0.9",
                *rows,
                "",
            ]
        )
        response = self.client.post(
            "/api/lut/upload_cube",
            files={"file": ("domain.cube", text.encode("ascii"), "text/plain")},
        )
        body = response.json()
        self.assertEqual(body["code"], 0, body)
        self.assertEqual(body["data"]["domain_min"], [-0.25, 0.0, 0.1])
        self.assertEqual(body["data"]["domain_max"], [1.5, 1.0, 0.9])

    def test_export_image_job_submit(self) -> None:
        self.assertTrue(FIXTURE.is_file())
        with FIXTURE.open("rb") as handle:
            up = self.client.post(
                "/api/media/upload",
                files={"file": ("pattern.png", handle, "image/png")},
            )
        media_id = up.json()["data"]["media_id"]
        from app.pipeline import ExportResult, RenderPipeline

        out_path = ROOT / "runtime" / "cache" / "api_export" / "mock.png"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"mock")

        with mock.patch("api.server.get_pipeline") as mock_pipeline_factory:
            pipeline = mock.Mock()
            real = RenderPipeline()
            pipeline.prepare_preview.side_effect = real.prepare_preview
            pipeline.export_image.return_value = ExportResult(
                path=out_path,
                width=64,
                height=48,
                revision=1,
                detail="PNG · 1 ms",
            )
            mock_pipeline_factory.return_value = pipeline

            response = self.client.post(
                "/api/export/image",
                json={
                    "media_id": media_id,
                    "params": ColorParams.identity().as_dict(),
                    "format": "PNG",
                },
            )
        body = response.json()
        self.assertEqual(body["code"], 0)
        job_id = body["data"]["job_id"]
        for _ in range(40):
            status = self.client.get(f"/api/jobs/{job_id}")
            record = get_job(job_id)
            if record and record.status == JobStatus.DONE:
                break
            time.sleep(0.05)
        final = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(final["code"], 0)
        self.assertEqual(final["data"]["status"], "done")


if __name__ == "__main__":
    unittest.main()