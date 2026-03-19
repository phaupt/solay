from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone

from src import api_cloud
from src.models import SensorPoint
from src.storage import Storage


class _FakeCloudClient:
    configured = True

    def get_statistics(self, start_utc, end_utc):
        return {
            "production": 12000.0,
            "consumption": 5000.0,
            "selfConsumption": 4200.0,
        }

    def get_range(self, start_utc, end_utc, *, interval_seconds=300):
        return [
            {
                "t": "2026-03-19T08:00:00.000Z",
                "cW": 900,
                "pW": 1800,
                "cWh": 75,
                "pWh": 150,
                "bcW": 0,
                "bdW": 0,
                "bcWh": 0,
                "bdWh": 0,
                "iWh": 0,
                "eWh": 75,
                "scWh": 75,
                "cPvWh": 75,
            }
        ]


def test_summary_from_statistics_derives_import_export():
    summary = api_cloud._summary_from_statistics(  # noqa: SLF001 - local helper test
        datetime(2026, 3, 18).date(),
        {"production": 10000.0, "consumption": 6000.0, "selfConsumption": 4500.0},
    )

    assert summary.import_wh == 1500.0
    assert summary.export_wh == 5500.0


def test_optional_backfill_populates_missing_days_and_today_prefix(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        storage = Storage(db_path=path)
        storage.store_point(
            SensorPoint(
                timestamp=datetime(2026, 3, 19, 12, 0, tzinfo=timezone.utc),
                c_w=1000,
                p_w=2000,
                c_wh=50,
                p_wh=100,
            )
        )

        class _FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                current = datetime(2026, 3, 19, 13, 0, tzinfo=timezone.utc)
                if tz is None:
                    return current
                return current.astimezone(tz)

        monkeypatch.setattr(api_cloud, "CloudApiClient", _FakeCloudClient)
        monkeypatch.setattr(api_cloud, "datetime", _FixedDateTime)
        monkeypatch.setattr(api_cloud.config, "SM_CLOUD_BACKFILL_ENABLED", True)
        monkeypatch.setattr(api_cloud.config, "SM_CLOUD_BACKFILL_DAYS", 3)
        monkeypatch.setattr(api_cloud.config, "SM_CLOUD_BACKFILL_INTERVAL_SECONDS", 300)

        added = api_cloud.optional_backfill(storage)

        assert added >= 3
        assert storage.get_daily_summary(datetime(2026, 3, 17).date()) is not None
        assert storage.get_daily_summary(datetime(2026, 3, 18).date()) is not None
        assert storage.point_count() >= 2
    finally:
        os.unlink(path)
