"""Tests für SQLite-Persistenz."""

import os
import tempfile
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from src.models import DailySummary, SensorPoint
from src.storage import Storage


@pytest.fixture
def storage():
    """Temporäre In-Memory-ähnliche DB für Tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = Storage(db_path=path)
    yield s
    os.unlink(path)


def _make_point(hour=12, minute=0, second=0, **kwargs):
    ts = datetime(2026, 3, 18, hour, minute, second, tzinfo=timezone.utc)
    return SensorPoint(timestamp=ts, c_w=500, p_w=3000, **kwargs)


class TestStoragePoints:
    def test_store_and_retrieve(self, storage):
        p = _make_point(12, 0, 0)
        storage.store_point(p, source="test")
        assert storage.point_count() == 1

        latest = storage.get_latest_point()
        assert latest is not None
        assert latest.c_w == 500
        assert latest.p_w == 3000

    def test_duplicate_ignored(self, storage):
        p = _make_point(12, 0, 0)
        storage.store_point(p)
        storage.store_point(p)  # Gleicher Timestamp
        assert storage.point_count() == 1

    def test_get_points_for_date(self, storage):
        tz_cet = ZoneInfo("Europe/Zurich")

        # 3 Punkte am 18.3., 1 Punkt am 19.3. (UTC)
        storage.store_point(_make_point(8, 0, 0))
        storage.store_point(_make_point(12, 0, 0))
        storage.store_point(_make_point(20, 0, 0))
        # 19.3. UTC 02:00 = 19.3. CET 03:00
        p4 = SensorPoint(
            timestamp=datetime(2026, 3, 19, 2, 0, 0, tzinfo=timezone.utc),
            c_w=100, p_w=0,
        )
        storage.store_point(p4)

        # Lokaler Tag 18.3. mit Europe/Zurich (CET = +1h)
        points = storage.get_points_for_date(date(2026, 3, 18), tz=tz_cet)
        # UTC 2026-03-17T23:00 bis 2026-03-18T23:00
        # Die 3 Punkte um 08:00, 12:00, 20:00 UTC fallen rein
        assert len(points) == 3

    def test_get_points_for_date_dst_transition(self, storage):
        """Sommerzeitwechsel: 29.3.2026 wechselt CET→CEST (UTC+1→UTC+2).

        Lokaler Tag 29.3.: 00:00 CEST = 28.3. 23:00 UTC (noch CET an Tagesstart)
        Am 29.3. um 02:00 CET → 03:00 CEST, der Tag hat nur 23 Stunden.
        """
        tz_zurich = ZoneInfo("Europe/Zurich")

        # Punkt um 28.3. 22:30 UTC = 28.3. 23:30 CET → gehört noch zum 28.3.
        p_before = SensorPoint(
            timestamp=datetime(2026, 3, 28, 22, 30, 0, tzinfo=timezone.utc),
            c_w=100, p_w=0,
        )
        # Punkt um 28.3. 23:30 UTC = 29.3. 00:30 CET → gehört zum 29.3.
        p_start = SensorPoint(
            timestamp=datetime(2026, 3, 28, 23, 30, 0, tzinfo=timezone.utc),
            c_w=200, p_w=0,
        )
        # Punkt um 29.3. 12:00 UTC = 29.3. 14:00 CEST → gehört zum 29.3.
        p_mid = SensorPoint(
            timestamp=datetime(2026, 3, 29, 12, 0, 0, tzinfo=timezone.utc),
            c_w=300, p_w=0,
        )
        # Punkt um 29.3. 22:30 UTC = 30.3. 00:30 CEST → gehört zum 30.3.
        p_after = SensorPoint(
            timestamp=datetime(2026, 3, 29, 22, 30, 0, tzinfo=timezone.utc),
            c_w=400, p_w=0,
        )

        for p in [p_before, p_start, p_mid, p_after]:
            storage.store_point(p)

        points = storage.get_points_for_date(date(2026, 3, 29), tz=tz_zurich)
        assert len(points) == 2
        assert points[0].c_w == 200
        assert points[1].c_w == 300


class TestStorageDailySummary:
    def test_store_and_retrieve(self, storage):
        s = DailySummary(
            local_date=date(2026, 3, 18),
            production_wh=25000,
            consumption_wh=12000,
            import_wh=2000,
            export_wh=15000,
            self_consumption_wh=10000,
            samples=8640,
        )
        storage.store_daily_summary(s)
        summaries = storage.get_daily_summaries(days=7)
        assert len(summaries) == 1
        assert summaries[0].production_wh == 25000
        assert summaries[0].samples == 8640

    def test_upsert(self, storage):
        """Zweites Speichern aktualisiert die bestehende Summary."""
        s1 = DailySummary(local_date=date(2026, 3, 18), production_wh=10000, samples=100)
        storage.store_daily_summary(s1)

        s2 = DailySummary(local_date=date(2026, 3, 18), production_wh=25000, samples=8640)
        storage.store_daily_summary(s2)

        summaries = storage.get_daily_summaries()
        assert len(summaries) == 1
        assert summaries[0].production_wh == 25000
