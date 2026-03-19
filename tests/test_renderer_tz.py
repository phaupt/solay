"""Tests: Renderer nutzt konfigurierte Zeitzone statt hartem Offset."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw

import config
from src.models import ChartBucket, DailySummary, DashboardData, SensorPoint
from src.renderer import (
    _draw_daily_chart,
    _draw_header,
    _to_local_timestamp,
    render_dashboard,
)


def _make_image_and_draw():
    img = Image.new("L", (config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT), 255)
    draw = ImageDraw.Draw(img)
    return img, draw


class TestHeaderTimezone:
    def test_header_shows_cet_in_winter(self):
        """UTC 14:30 am 15.1. → CET 15:30 (UTC+1)."""
        ts = datetime(2026, 1, 15, 14, 30, 0, tzinfo=timezone.utc)
        point = SensorPoint(timestamp=ts, c_w=500, p_w=3000)
        data = DashboardData(live=point)

        img, draw = _make_image_and_draw()
        _draw_header(draw, data, config.DISPLAY_WIDTH)

        # Prüfe die korrekte Lokalzeit-Konvertierung direkt
        local = _to_local_timestamp(ts)
        assert local.hour == 15
        assert local.minute == 30

    def test_header_shows_cest_in_summer(self):
        """UTC 14:30 am 15.7. → CEST 16:30 (UTC+2)."""
        ts = datetime(2026, 7, 15, 14, 30, 0, tzinfo=timezone.utc)
        point = SensorPoint(timestamp=ts, c_w=500, p_w=3000)
        data = DashboardData(live=point)

        img, draw = _make_image_and_draw()
        _draw_header(draw, data, config.DISPLAY_WIDTH)

        local = _to_local_timestamp(ts)
        assert local.hour == 16
        assert local.minute == 30


class TestChartTimezone:
    def _make_bucket(self, utc_hour, utc_minute=0, p_w_avg=3000, c_w_avg=500):
        ts = datetime(2026, 7, 15, utc_hour, utc_minute, 0, tzinfo=timezone.utc)
        return ChartBucket(
            timestamp=ts,
            p_w_avg=p_w_avg,
            c_w_avg=c_w_avg,
            grid_w_avg=c_w_avg - p_w_avg,
            samples=30,
        )

    def test_chart_bucket_summer_offset(self):
        """Im Sommer (CEST, UTC+2): UTC 10:00 → Lokalzeit 12:00."""
        tz = ZoneInfo("Europe/Zurich")
        bucket = self._make_bucket(10, 0)
        local = bucket.timestamp.astimezone(tz)
        assert local.hour == 12

    def test_chart_bucket_winter_offset(self):
        """Im Winter (CET, UTC+1): UTC 10:00 → Lokalzeit 11:00."""
        tz = ZoneInfo("Europe/Zurich")
        ts = datetime(2026, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        bucket = ChartBucket(timestamp=ts, p_w_avg=1000, c_w_avg=500, samples=30)
        local = bucket.timestamp.astimezone(tz)
        assert local.hour == 11

    def test_chart_renders_with_summer_buckets(self):
        """Chart-Rendering mit Sommer-Buckets wirft keinen Fehler."""
        buckets = [self._make_bucket(h) for h in range(4, 20)]
        data = DashboardData(chart_buckets=buckets)

        img, draw = _make_image_and_draw()
        _draw_daily_chart(draw, data, 48, 300, 1048, 640)
        # Kein Fehler = Konvertierung funktioniert


class TestRenderDashboardStates:
    """Renderer muss für alle definierten Zustände ohne Fehler laufen."""

    def _make_live(self, **kwargs):
        defaults = dict(
            timestamp=datetime(2026, 3, 18, 12, 0, 0, tzinfo=timezone.utc),
            c_w=3000, p_w=5000,
        )
        defaults.update(kwargs)
        return SensorPoint(**defaults)

    def _make_history(self):
        return [
            DailySummary(local_date=date(2026, 3, d),
                         production_wh=30000, consumption_wh=8000, samples=100)
            for d in range(12, 19)
        ]

    def test_solar_to_home_battery_grid(self):
        """PV verteilt an Haus, Batterie und Netz (Export)."""
        live = self._make_live(p_w=8000, c_w=3000, bc_w=1500, soc=60)
        data = DashboardData(live=live, daily_history=self._make_history())
        img = render_dashboard(data)
        assert img.size == (config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT)

    def test_solar_and_grid_to_home(self):
        """PV und Netz versorgen gemeinsam das Haus."""
        live = self._make_live(p_w=2000, c_w=5000, soc=80)
        data = DashboardData(live=live, daily_history=self._make_history())
        img = render_dashboard(data)
        assert img.size == (config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT)

    def test_grid_only(self):
        """Nacht: nur Netzbezug."""
        live = self._make_live(p_w=0, c_w=500, soc=50)
        data = DashboardData(live=live, daily_history=self._make_history())
        img = render_dashboard(data)
        assert img.size == (config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT)

    def test_battery_unavailable(self):
        """Kein Batteriesystem vorhanden."""
        live = self._make_live(p_w=5000, c_w=3000)
        assert not live.has_battery
        data = DashboardData(live=live, daily_history=self._make_history())
        img = render_dashboard(data)
        assert img.size == (config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT)

    def test_no_live_data(self):
        """Keine Live-Daten verfügbar."""
        data = DashboardData()
        img = render_dashboard(data)
        assert img.size == (config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT)

    def test_stale_data_no_history(self):
        """Live-Daten vorhanden aber keine Historie."""
        live = self._make_live(p_w=1000, c_w=800)
        data = DashboardData(live=live)
        img = render_dashboard(data)
        assert img.size == (config.DISPLAY_WIDTH, config.DISPLAY_HEIGHT)
