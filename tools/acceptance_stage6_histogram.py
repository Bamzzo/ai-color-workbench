"""Stage-6 acceptance: histogram canvas must contain visible curve pixels."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "runtime" / "test-fixtures" / "scene.jpg"
OUT = ROOT / "runtime" / "benchmark_results" / "stage6_acceptance.json"


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed; pip install playwright && playwright install chromium")
        return 2

    if not FIXTURE.is_file():
        print(f"missing fixture: {FIXTURE}")
        return 2

    base = "http://127.0.0.1:5173"
    payload: dict[str, object] = {"base": base, "checks": []}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

        page.goto(base, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(800)

        with page.expect_file_chooser() as fc_info:
            page.get_by_title("导入图片").click()
        fc = fc_info.value
        fc.set_files(str(FIXTURE))
        page.wait_for_timeout(4000)

        hist_pixels = page.evaluate(
            """() => {
          const c = document.querySelector('.histogram-wrap canvas');
          if (!c) return { ok: false, count: 0, reason: 'no canvas' };
          const ctx = c.getContext('2d');
          const { width, height } = c;
          const img = ctx.getImageData(0, 0, width, height).data;
          let colorful = 0;
          for (let i = 0; i < img.length; i += 4) {
            const r = img[i], g = img[i+1], b = img[i+2], a = img[i+3];
            if (a < 12) continue;
            const isGrid = Math.abs(r - g) < 6 && Math.abs(g - b) < 6 && r < 40;
            if (isGrid) continue;
            if (r > 55 || g > 55 || b > 55) colorful++;
          }
          const glErr = window.__glv?.gl?.getError?.() ?? 0;
          return { ok: colorful > 500, count: colorful, glErr, w: width, h: height };
        }"""
        )

        chip = page.locator(".ai-preset-chip", has_text="清透日系")
        chip.wait_for(state="visible", timeout=8000)
        chip.click()
        page.get_by_role("button", name="✦ AI 生成").click()
        page.wait_for_timeout(4000)

        offline_summary = page.locator("#ai-summary").inner_text()
        warm_leak = "使用暖色模板" in offline_summary

        payload["checks"] = [
            {"name": "histogram_pixels", **hist_pixels},
            {"name": "qingtou_not_warm_template", "warm_leak": warm_leak, "summary": offline_summary[:160]},
            {"name": "console_errors", "errors": errors[:20]},
        ]

        bloom = page.locator(".dock-bloom input.dock-range")
        if bloom.count():
            bloom.fill("70")
            page.wait_for_timeout(1200)
        hist_after_bloom = page.evaluate(
            """() => {
          const c = document.querySelector('.histogram-wrap canvas');
          const ctx = c.getContext('2d');
          const img = ctx.getImageData(0, 0, c.width, c.height).data;
          let colorful = 0;
          for (let i = 0; i < img.length; i += 4) {
            const a = img[i+3]; if (a < 12) continue;
            if (img[i] > 55 || img[i+1] > 55 || img[i+2] > 55) colorful++;
          }
          return colorful;
        }"""
        )
        payload["checks"].append({"name": "histogram_after_bloom", "count": hist_after_bloom, "ok": hist_after_bloom > 500})

        browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    hist = next((c for c in payload["checks"] if c["name"] == "histogram_pixels"), {})
    chip_check = next((c for c in payload["checks"] if c["name"] == "qingtou_not_warm_template"), {})
    bloom_hist = next((c for c in payload["checks"] if c["name"] == "histogram_after_bloom"), {})
    ok = (
        hist.get("count", 0) > 500
        and not chip_check.get("warm_leak", True)
        and bloom_hist.get("count", 0) > 500
    )

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())