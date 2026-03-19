"""Tests für StreamCollector: Polling-Fallback bei Stream-Ausfall."""

import os
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

from src.api_local import StreamCollector
from src.storage import Storage


def _make_api_response(ts_suffix="00"):
    """Erzeugt eine minimale API-Response für /v2/point."""
    return {
        "t": f"2026-03-18T12:00:{ts_suffix}Z",
        "v": 2,
        "cW": 500,
        "pW": 3000,
        "bcW": 0,
        "bdW": 0,
        "cWh": 1.5,
        "pWh": 8.0,
        "bcWh": 0,
        "bdWh": 0,
        "scWh": 1.5,
        "cPvWh": 1.5,
        "iWh": 0,
        "eWh": 6.5,
        "devices": [],
    }


class TestPollingFallback:
    def test_poll_until_collects_points(self):
        """Wenn der Stream ausfällt, soll _poll_until aktiv Punkte sammeln."""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            storage = Storage(db_path=path)
            client = MagicMock()

            call_count = 0
            def fake_get_point():
                nonlocal call_count
                call_count += 1
                return _make_api_response(f"{call_count:02d}")

            client.get_point = fake_get_point

            collector = StreamCollector(storage=storage, client=client)
            collector._running = True

            # Polle für 1.5 Sekunden mit 0.5s Intervall
            with patch("config.POLL_INTERVAL_SECONDS", 0.5):
                collector._poll_until(1.5)

            # Sollte mindestens 2 Punkte gesammelt haben
            assert storage.point_count() >= 2
            assert call_count >= 2
        finally:
            os.unlink(path)

    def test_process_point_enriches_devices_with_catalog_metadata(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            storage = Storage(db_path=path)
            client = MagicMock()
            client.get_devices.return_value = [
                {"deviceId": "car_01", "type": "car", "name": "Tesla Model Y"},
            ]

            collector = StreamCollector(storage=storage, client=client)
            payload = _make_api_response()
            payload["devices"] = [{"_id": "car_01", "signal": "connected", "soc": 74}]

            collector._process_point(payload)

            assert collector.latest_point is not None
            assert collector.latest_point.soc is None
            assert collector.latest_devices[0].device_type == "car"
        finally:
            os.unlink(path)

    def test_poll_until_stops_when_not_running(self):
        """_poll_until bricht ab wenn _running=False gesetzt wird."""
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            storage = Storage(db_path=path)
            client = MagicMock()
            client.get_point.return_value = _make_api_response()

            collector = StreamCollector(storage=storage, client=client)
            collector._running = True

            def stop_soon():
                time.sleep(0.3)
                collector._running = False

            threading.Thread(target=stop_soon, daemon=True).start()

            with patch("config.POLL_INTERVAL_SECONDS", 0.5):
                start = time.monotonic()
                collector._poll_until(10.0)  # Würde 10s laufen, aber stop kommt
                elapsed = time.monotonic() - start

            assert elapsed < 2.0  # Muss deutlich vor 10s abbrechen
        finally:
            os.unlink(path)
