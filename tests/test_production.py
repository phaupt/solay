"""Tests for ProductionLoop."""

from __future__ import annotations

import signal
from datetime import datetime, timedelta
from unittest.mock import MagicMock, call, patch

import pytest
from PIL import Image
from zoneinfo import ZoneInfo

from src.models import DailySummary


TZ = ZoneInfo("Europe/Zurich")


@pytest.fixture
def mock_deps():
    storage = MagicMock()
    storage.get_points_for_date.return_value = []
    storage.get_daily_summaries.return_value = []
    storage.get_latest_point.return_value = None
    collector = MagicMock()
    collector.latest_point = None
    collector.latest_devices = []
    renderer = MagicMock()
    renderer.render.return_value = Image.new("L", (1872, 1404), 128)
    display = MagicMock()
    return storage, collector, renderer, display


# ---------------------------------------------------------------------------
# TestProductionLoopSingleCycle
# ---------------------------------------------------------------------------

class TestProductionLoopSingleCycle:

    @patch("main.build_dashboard_data")
    def test_one_cycle_renders_and_displays(self, mock_build, mock_deps):
        storage, collector, renderer, display = mock_deps
        mock_build.return_value = MagicMock()
        from src.production import ProductionLoop

        loop = ProductionLoop(storage, collector, renderer, display)
        loop._run_one_cycle()

        mock_build.assert_called_once_with(storage, collector)
        renderer.render.assert_called_once()
        display.show_full.assert_called_once()

    @patch("main.build_dashboard_data")
    def test_one_cycle_without_display(self, mock_build, mock_deps):
        storage, collector, renderer, _ = mock_deps
        mock_build.return_value = MagicMock()
        from src.production import ProductionLoop

        loop = ProductionLoop(storage, collector, renderer, display=None)
        loop._run_one_cycle()

        renderer.render.assert_called_once()

    @patch("main.build_dashboard_data")
    def test_renderer_failure_does_not_crash(self, mock_build, mock_deps):
        storage, collector, renderer, display = mock_deps
        mock_build.return_value = MagicMock()
        renderer.render.side_effect = RuntimeError("render boom")
        from src.production import ProductionLoop

        loop = ProductionLoop(storage, collector, renderer, display)
        loop._run_one_cycle()  # Should not raise

        display.show_full.assert_not_called()

    @patch("main.build_dashboard_data")
    def test_display_failure_does_not_crash(self, mock_build, mock_deps):
        storage, collector, renderer, display = mock_deps
        mock_build.return_value = MagicMock()
        display.show_full.side_effect = RuntimeError("display boom")
        from src.production import ProductionLoop

        loop = ProductionLoop(storage, collector, renderer, display)
        loop._run_one_cycle()  # Should not raise


# ---------------------------------------------------------------------------
# TestStartupReconciliation
# ---------------------------------------------------------------------------

class TestStartupReconciliation:

    @patch("src.api_cloud.optional_backfill")
    @patch("src.production.aggregate_daily_summary")
    def test_reconcile_reaggregates_yesterday_on_startup(
        self, mock_agg, mock_backfill, mock_deps
    ):
        storage, collector, renderer, display = mock_deps
        from src.production import ProductionLoop

        yesterday = (datetime.now(TZ) - timedelta(days=1)).date()
        fake_points = [MagicMock(), MagicMock()]
        storage.get_points_for_date.return_value = fake_points
        mock_agg.return_value = MagicMock(spec=DailySummary)

        loop = ProductionLoop(storage, collector, renderer, display)
        loop._reconcile_yesterday()

        storage.get_points_for_date.assert_called_once_with(yesterday, tz=TZ)
        mock_agg.assert_called_once_with(fake_points, yesterday)
        storage.store_daily_summary.assert_called_once_with(mock_agg.return_value)
        mock_backfill.assert_called_once_with(storage, skip_today=True)

    @patch("src.api_cloud.optional_backfill")
    @patch("src.production.aggregate_daily_summary")
    def test_reconcile_skips_if_no_points(
        self, mock_agg, mock_backfill, mock_deps
    ):
        storage, collector, renderer, display = mock_deps
        from src.production import ProductionLoop

        storage.get_points_for_date.return_value = []

        loop = ProductionLoop(storage, collector, renderer, display)
        loop._reconcile_yesterday()

        mock_agg.assert_not_called()
        storage.store_daily_summary.assert_not_called()
        # Backfill should still be called even if no points
        mock_backfill.assert_called_once_with(storage, skip_today=True)


# ---------------------------------------------------------------------------
# TestDayRollover
# ---------------------------------------------------------------------------

class TestDayRollover:

    @patch("src.api_cloud.optional_backfill")
    @patch("src.production.aggregate_daily_summary")
    def test_rollover_reaggregates_yesterday(
        self, mock_agg, mock_backfill, mock_deps
    ):
        storage, collector, renderer, display = mock_deps
        from src.production import ProductionLoop

        yesterday = (datetime.now(TZ) - timedelta(days=1)).date()
        fake_points = [MagicMock()]
        storage.get_points_for_date.return_value = fake_points
        mock_agg.return_value = MagicMock(spec=DailySummary)

        loop = ProductionLoop(storage, collector, renderer, display)
        loop._current_date = yesterday  # Simulate day change
        loop._check_day_rollover()

        storage.get_points_for_date.assert_called_once_with(yesterday, tz=TZ)
        mock_agg.assert_called_once_with(fake_points, yesterday)
        storage.store_daily_summary.assert_called_once()
        mock_backfill.assert_called_once_with(storage, skip_today=True)
        assert loop._current_date == datetime.now(TZ).date()


# ---------------------------------------------------------------------------
# TestRetentionCleanup
# ---------------------------------------------------------------------------

class TestRetentionCleanup:

    @patch("main.build_dashboard_data")
    def test_cleanup_runs_on_first_cycle(self, mock_build, mock_deps):
        storage, collector, renderer, display = mock_deps
        mock_build.return_value = MagicMock()
        from src.production import ProductionLoop

        loop = ProductionLoop(storage, collector, renderer, display)
        loop._run_one_cycle()

        storage.cleanup_old_points.assert_called_once()

    @patch("main.build_dashboard_data")
    def test_cleanup_skips_within_hour(self, mock_build, mock_deps):
        storage, collector, renderer, display = mock_deps
        mock_build.return_value = MagicMock()
        from src.production import ProductionLoop

        loop = ProductionLoop(storage, collector, renderer, display)
        loop._last_cleanup_at = datetime.now(TZ)  # Just ran
        loop._run_one_cycle()

        storage.cleanup_old_points.assert_not_called()

    @patch("main.build_dashboard_data")
    def test_cleanup_runs_after_hour(self, mock_build, mock_deps):
        storage, collector, renderer, display = mock_deps
        mock_build.return_value = MagicMock()
        from src.production import ProductionLoop

        loop = ProductionLoop(storage, collector, renderer, display)
        loop._last_cleanup_at = datetime.now(TZ) - timedelta(hours=1, minutes=1)
        loop._run_one_cycle()

        storage.cleanup_old_points.assert_called_once()


# ---------------------------------------------------------------------------
# TestShutdown
# ---------------------------------------------------------------------------

class TestShutdown:

    def test_stop_sets_flag(self, mock_deps):
        storage, collector, renderer, display = mock_deps
        from src.production import ProductionLoop

        loop = ProductionLoop(storage, collector, renderer, display)
        assert not loop._stopped
        loop.stop()
        assert loop._stopped

    def test_shutdown_order(self, mock_deps):
        storage, collector, renderer, display = mock_deps
        from src.production import ProductionLoop

        call_order = []
        display.sleep.side_effect = lambda: call_order.append("display.sleep")
        renderer.close.side_effect = lambda: call_order.append("renderer.close")
        collector.stop.side_effect = lambda: call_order.append("collector.stop")

        loop = ProductionLoop(storage, collector, renderer, display)
        loop._shutdown()

        assert call_order == ["display.sleep", "renderer.close", "collector.stop"]


# ---------------------------------------------------------------------------
# TestVcomValidation
# ---------------------------------------------------------------------------


class TestVcomValidation:

    def test_vcom_validation_rejects_empty(self):
        from main import _validate_vcom
        with pytest.raises(SystemExit):
            _validate_vcom("")

    def test_vcom_validation_rejects_non_float(self):
        from main import _validate_vcom
        with pytest.raises(SystemExit):
            _validate_vcom("notanumber")

    def test_vcom_validation_rejects_positive(self):
        from main import _validate_vcom
        with pytest.raises(SystemExit):
            _validate_vcom("1.5")

    def test_vcom_validation_accepts_valid(self):
        from main import _validate_vcom
        result = _validate_vcom("-1.48")
        assert result == -1.48
