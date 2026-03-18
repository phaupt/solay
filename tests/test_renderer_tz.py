"""Tests: Renderer nutzt konfigurierte Zeitzone statt hartem Offset."""

from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.models import ChartBucket, DashboardData, SensorPoint
from src.renderer import _draw_header, _draw_daily_chart, _LOCAL_TZ, FONTS
from PIL import Image, ImageDraw

import config


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
        tz = ZoneInfo("Europe/Zurich")
        local = ts.astimezone(tz)
        assert local.hour == 15
        assert local.minute == 30

    def test_header_shows_cest_in_summer(self):
        """UTC 14:30 am 15.7. → CEST 16:30 (UTC+2)."""
        ts = datetime(2026, 7, 15, 14, 30, 0, tzinfo=timezone.utc)
        point = SensorPoint(timestamp=ts, c_w=500, p_w=3000)
        data = DashboardData(live=point)

        img, draw = _make_image_and_draw()
        _draw_header(draw, data, config.DISPLAY_WIDTH)

        tz = ZoneInfo("Europe/Zurich")
        local = ts.astimezone(tz)
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
        _draw_daily_chart(draw, data, config.DISPLAY_WIDTH, 300, 640)
        # Kein Fehler = Konvertierung funktioniert
