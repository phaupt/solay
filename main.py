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
from dataclasses import replace
from datetime import datetime, timezone
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
        peak_production_w=max((point.p_w for point in points), default=0.0),
        daily_summary=daily_summary,
        daily_history=daily_history,
        devices=devices,
    )


def build_mock_dashboard_data(storage: Storage) -> DashboardData:
    from mock_data import (
        get_mock_devices,
        get_mock_live_point,
        get_mock_review_history,
    )

    data = build_dashboard_data(storage)
    data.devices = get_mock_devices()
    # Keep the approved review values, but refresh the timestamp so the default
    # mock preview and non-stale scenarios do not appear stale later in the day.
    data.live = replace(get_mock_live_point(), timestamp=datetime.now(timezone.utc))
    data.daily_history = get_mock_review_history()
    return data


def run_mock_mode(port: int):
    """Mock-Modus: Separate DB mit Testdaten füllen, dann Browser-Preview."""
    from mock_data import seed_mock_database

    db_path = config.MOCK_DB_PATH
    # Frische Mock-DB (nie die Live-DB anfassen)
    if os.path.exists(db_path):
        os.remove(db_path)

    storage = Storage(db_path)
    seed_mock_database(storage)
    logger.info("Mock-Datenbank bereit: %d Punkte", storage.point_count())

    from src.web_preview import start_server

    def get_data() -> DashboardData:
        return build_mock_dashboard_data(storage)

    start_server(get_data, port=port)


def build_live_dashboard_data(storage: Storage, collector) -> DashboardData:
    return build_dashboard_data(storage, collector=collector)


def _maybe_run_cloud_backfill(storage: Storage):
    from src.api_cloud import optional_backfill

    try:
        added = optional_backfill(storage)
    except Exception as exc:
        logger.warning("Cloud backfill fehlgeschlagen: %s", exc)
        return

    if added > 0:
        logger.info("Cloud backfill ergänzt: %d Datenpunkte/Zusammenfassungen", added)


def create_live_storage_and_collector():
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
    _maybe_run_cloud_backfill(storage)
    client = LocalApiClient()
    collector = StreamCollector(storage=storage, client=client)

    # Collector starten (Daemon-Thread)
    collector.start()

    # Initialer Point-Request als Sofortdaten
    logger.info("Hole initialen Datenpunkt...")
    collector.poll_once()

    return storage, collector


def run_live_mode(port: int):
    """Live-Modus: Stream-Collector → SQLite → Browser-Preview."""
    storage, collector = create_live_storage_and_collector()

    from src.web_preview import start_server

    def get_data() -> DashboardData:
        return build_live_dashboard_data(storage, collector=collector)

    start_server(get_data, port=port)


def export_once(mock: bool, output_path: str, theme: str | None = None, lang: str | None = None):
    from mock_data import seed_mock_database
    from src.export_dashboard import export_dashboard_png

    if mock:
        db_path = config.MOCK_DB_PATH
        if os.path.exists(db_path):
            os.remove(db_path)
        storage = Storage(db_path)
        seed_mock_database(storage)
        data = build_mock_dashboard_data(storage)
    else:
        storage, collector = create_live_storage_and_collector()
        data = build_live_dashboard_data(storage, collector=collector)
        collector.stop()

    exported = export_dashboard_png(data, output_path, theme=theme, lang=lang)
    logger.info("PNG export geschrieben: %s", exported)


def _validate_vcom(vcom_str: str) -> float:
    """Validate EPAPER_VCOM. Exit with error if invalid."""
    if not vcom_str.strip():
        logger.error(
            "EPAPER_VCOM not set. Check the label on the panel ribbon cable "
            "and set EPAPER_VCOM in .env.local (e.g. EPAPER_VCOM=-1.48)."
        )
        sys.exit(1)
    try:
        vcom = float(vcom_str)
    except ValueError:
        logger.error("EPAPER_VCOM='%s' is not a valid number.", vcom_str)
        sys.exit(1)
    if vcom > 0 or vcom < -5.0:
        logger.error(
            "EPAPER_VCOM=%.2f is outside expected range (-5.0 to 0.0). "
            "Check the panel label.", vcom
        )
        sys.exit(1)
    return vcom


def run_production_mode(no_display: bool, theme: str | None, lang: str | None):
    """Production mode: collect → render → display loop."""
    from src.renderer_png import PersistentPlaywrightRenderer
    from src.production import ProductionLoop

    if not no_display:
        vcom = _validate_vcom(config.EPAPER_VCOM)

    storage, collector = create_live_storage_and_collector()
    renderer = PersistentPlaywrightRenderer(theme=theme, lang=lang)

    display = None
    if not no_display:
        from src.epaper import EpaperDisplay
        display = EpaperDisplay(vcom=vcom)

    loop = ProductionLoop(storage, collector, renderer, display)
    loop.run()


def main():
    parser = argparse.ArgumentParser(description="Solar E-Ink Dashboard")
    parser.add_argument("--mock", action="store_true",
                        help="Mock-Daten für UI-Entwicklung verwenden")
    parser.add_argument("--production", action="store_true",
                        help="Production mode: collect → render → e-ink display loop")
    parser.add_argument("--export-png", type=str, default="",
                        help="Dashboard einmalig als PNG exportieren")
    parser.add_argument("--no-display", action="store_true",
                        help="Production mode without e-paper hardware (headless)")
    parser.add_argument("--port", type=int, default=config.WEB_PORT,
                        help="Web-Preview Port (default: 8080)")
    parser.add_argument("--theme", type=str, default="",
                        help="Theme override: light|dark")
    parser.add_argument("--lang", type=str, default="",
                        help="Language override: en|de|fr|it")
    args = parser.parse_args()

    # --production is mutually exclusive with --mock and --export-png,
    # but --mock and --export-png CAN combine (existing documented workflow:
    # `main.py --mock --export-png out/dashboard.png`).
    if args.production and args.mock:
        parser.error("--production and --mock are mutually exclusive")
    if args.production and args.export_png:
        parser.error("--production and --export-png are mutually exclusive")

    if args.export_png:
        export_once(
            args.mock,
            args.export_png,
            theme=args.theme or None,
            lang=args.lang or None,
        )
        return

    if args.production:
        logger.info("Starting in production mode")
        run_production_mode(
            args.no_display,
            theme=args.theme or None,
            lang=args.lang or None,
        )
        return

    if args.mock:
        logger.info("Starte im Mock-Modus")
        run_mock_mode(args.port)
    else:
        logger.info("Starte im Live-Modus")
        run_live_mode(args.port)


if __name__ == "__main__":
    main()
