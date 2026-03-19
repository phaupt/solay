"""Entry Point: Solar E-Ink Dashboard.

Modi:
  --mock       Mock-Daten in DB seeden und Browser-Preview starten
  (default)    Live-Modus: WebSocket-Stream → SQLite → Renderer

Die Architektur:
  Collector (Stream/Point) → SQLite → Aggregator → Renderer → Web/E-Ink
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

import config
from src.aggregator import aggregate_chart_buckets, aggregate_daily_summary
from src.models import DashboardData
from src.storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def build_dashboard_data(storage: Storage, collector=None) -> DashboardData:
    """Baue DashboardData aus der Datenbank zusammen."""
    tz = ZoneInfo(config.TIMEZONE)
    today = datetime.now(tz).date()

    points = storage.get_points_for_date(today, tz=tz)

    # Chart-Buckets und Tagessummary berechnen
    chart_buckets = aggregate_chart_buckets(points)
    daily_summary = aggregate_daily_summary(points, today)

    # Tages-Summary in DB speichern (für Historie)
    if daily_summary.samples > 0:
        storage.store_daily_summary(daily_summary)

    # Live-Punkt
    live = None
    if collector is not None:
        live = collector.latest_point
    if live is None:
        live = storage.get_latest_point()

    # Geräte
    devices = []
    if collector is not None:
        devices = collector.latest_devices

    # Historie
    daily_history = storage.get_daily_summaries(days=30)

    return DashboardData(
        live=live,
        chart_buckets=chart_buckets,
        daily_summary=daily_summary,
        daily_history=daily_history,
        devices=devices,
    )


def run_mock_mode(port: int):
    """Mock-Modus: Separate DB mit Testdaten füllen, dann Browser-Preview."""
    from mock_data import (
        get_mock_devices,
        get_mock_live_point,
        get_mock_review_history,
        DESIGN_REVIEW_WEEK_KWH,
        seed_mock_database,
    )

    db_path = config.MOCK_DB_PATH
    # Frische Mock-DB (nie die Live-DB anfassen)
    if os.path.exists(db_path):
        os.remove(db_path)

    storage = Storage(db_path)
    seed_mock_database(storage)

    mock_devices = get_mock_devices()
    logger.info("Mock-Datenbank bereit: %d Punkte", storage.point_count())

    from src.web_preview import start_server

    def get_data() -> DashboardData:
        data = build_dashboard_data(storage)
        data.devices = mock_devices
        data.live = get_mock_live_point()
        data.daily_history = get_mock_review_history()
        data.history_labels = [label for label, _, _ in DESIGN_REVIEW_WEEK_KWH]
        return data

    start_server(get_data, port=port)


def run_live_mode(port: int):
    """Live-Modus: Stream-Collector → SQLite → Browser-Preview."""
    from src.api_local import LocalApiClient, StreamCollector

    if config.SM_LOCAL_BASE_URL == "http://192.168.1.XXX":
        logger.error(
            "SM_LOCAL_BASE_URL nicht konfiguriert. "
            "Setze die Umgebungsvariable SM_LOCAL_BASE_URL auf die IP deines Gateways, "
            "z.B.: export SM_LOCAL_BASE_URL=http://192.168.1.100"
        )
        sys.exit(1)

    storage = Storage()
    client = LocalApiClient()
    collector = StreamCollector(storage=storage, client=client)

    # Collector starten (Daemon-Thread)
    collector.start()

    # Initialer Point-Request als Sofortdaten
    logger.info("Hole initialen Datenpunkt...")
    collector.poll_once()

    from src.web_preview import start_server

    def get_data() -> DashboardData:
        return build_dashboard_data(storage, collector=collector)

    start_server(get_data, port=port)


def main():
    parser = argparse.ArgumentParser(description="Solar E-Ink Dashboard")
    parser.add_argument("--mock", action="store_true",
                        help="Mock-Daten für UI-Entwicklung verwenden")
    parser.add_argument("--port", type=int, default=config.WEB_PORT,
                        help="Web-Preview Port (default: 8080)")
    args = parser.parse_args()

    if args.mock:
        logger.info("Starte im Mock-Modus")
        run_mock_mode(args.port)
    else:
        logger.info("Starte im Live-Modus")
        run_live_mode(args.port)


if __name__ == "__main__":
    main()
