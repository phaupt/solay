"""Tests for quantize_image and renderer_png module."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from PIL import Image

from src.export_dashboard import quantize_image
from src.models import DailySummary, DashboardData, SensorPoint


# ---------------------------------------------------------------------------
# quantize_image tests
# ---------------------------------------------------------------------------


class TestQuantizeImage:
    def test_converts_to_grayscale(self):
        rgb = Image.new("RGB", (10, 10), (128, 64, 200))
        result = quantize_image(rgb, 16)
        assert result.mode == "L"

    def test_levels_2_produces_black_and_white(self):
        gray = Image.new("L", (4, 4), 100)
        result = quantize_image(gray, 2)
        pixels = list(result.get_flattened_data())
        assert all(p in (0, 255) for p in pixels)

    def test_levels_1_returns_grayscale(self):
        gray = Image.new("L", (4, 4), 100)
        result = quantize_image(gray, 1)
        assert result.mode == "L"

    def test_identity_at_256_levels(self):
        gray = Image.new("L", (4, 4), 137)
        result = quantize_image(gray, 256)
        assert list(result.get_flattened_data()) == [137] * 16


# ---------------------------------------------------------------------------
# Playwright availability gate
# ---------------------------------------------------------------------------


def _has_playwright():
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            pw.chromium.launch().close()
        return True
    except Exception:
        return False


_skip_no_playwright = pytest.mark.skipif(
    not _has_playwright(),
    reason="Playwright/Chromium not installed",
)


# ---------------------------------------------------------------------------
# Helper: minimal DashboardData
# ---------------------------------------------------------------------------


def _make_minimal_dashboard_data() -> DashboardData:
    now = datetime.now(tz=timezone.utc)
    live = SensorPoint(
        timestamp=now,
        p_w=1500.0,
        c_w=800.0,
    )
    daily = DailySummary(
        local_date=date.today(),
        production_wh=5000.0,
        consumption_wh=3000.0,
    )
    return DashboardData(
        live=live,
        daily_summary=daily,
        daily_history=[daily],
        history_labels=["Mon"],
    )


# ---------------------------------------------------------------------------
# PersistentPlaywrightRenderer tests
# ---------------------------------------------------------------------------


@_skip_no_playwright
class TestPersistentPlaywrightRenderer:
    def test_render_returns_grayscale_image(self):
        from src.renderer_png import PersistentPlaywrightRenderer

        renderer = PersistentPlaywrightRenderer()
        try:
            img = renderer.render(_make_minimal_dashboard_data())
            assert img.mode == "L"
            assert img.size == (1872, 1404)
        finally:
            renderer.close()

    def test_render_to_file_writes_png(self, tmp_path):
        from src.renderer_png import PersistentPlaywrightRenderer

        renderer = PersistentPlaywrightRenderer()
        try:
            out = tmp_path / "dashboard.png"
            renderer.render_to_file(_make_minimal_dashboard_data(), out)
            assert out.exists()
            img = Image.open(out)
            assert img.mode == "L"
            assert img.size == (1872, 1404)
        finally:
            renderer.close()

    def test_multiple_renders_reuse_browser(self):
        from src.renderer_png import PersistentPlaywrightRenderer

        renderer = PersistentPlaywrightRenderer()
        try:
            img1 = renderer.render(_make_minimal_dashboard_data())
            img2 = renderer.render(_make_minimal_dashboard_data())
            assert img1.size == (1872, 1404)
            assert img2.size == (1872, 1404)
        finally:
            renderer.close()

    def test_close_is_idempotent(self):
        from src.renderer_png import PersistentPlaywrightRenderer

        renderer = PersistentPlaywrightRenderer()
        renderer.close()
        renderer.close()  # should not raise


# ---------------------------------------------------------------------------
# OneShotPlaywrightRenderer tests
# ---------------------------------------------------------------------------


@_skip_no_playwright
class TestOneShotPlaywrightRenderer:
    def test_render_returns_grayscale_image(self):
        from src.renderer_png import OneShotPlaywrightRenderer

        renderer = OneShotPlaywrightRenderer()
        try:
            img = renderer.render(_make_minimal_dashboard_data())
            assert img.mode == "L"
            assert img.size == (1872, 1404)
        finally:
            renderer.close()

    def test_close_is_noop(self):
        from src.renderer_png import OneShotPlaywrightRenderer

        renderer = OneShotPlaywrightRenderer()
        renderer.close()  # should not raise
