"""SQLite-Persistenz für Sensor-Datenpunkte und Tageswerte.

WAL-Modus für gute Concurrent-Read-Performance (Collector schreibt,
Renderer/Aggregator lesen gleichzeitig).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import config
from src.models import DailySummary, SensorPoint

logger = logging.getLogger(__name__)

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS raw_points (
    ts_utc TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'local_stream',
    c_w REAL NOT NULL DEFAULT 0,
    p_w REAL NOT NULL DEFAULT 0,
    bc_w REAL NOT NULL DEFAULT 0,
    bd_w REAL NOT NULL DEFAULT 0,
    c_wh REAL NOT NULL DEFAULT 0,
    p_wh REAL NOT NULL DEFAULT 0,
    bc_wh REAL NOT NULL DEFAULT 0,
    bd_wh REAL NOT NULL DEFAULT 0,
    sc_wh REAL NOT NULL DEFAULT 0,
    cpv_wh REAL NOT NULL DEFAULT 0,
    i_wh REAL NOT NULL DEFAULT 0,
    e_wh REAL NOT NULL DEFAULT 0,
    soc REAL,
    devices_json TEXT
);

CREATE TABLE IF NOT EXISTS daily_summary (
    local_date TEXT PRIMARY KEY,
    production_wh REAL NOT NULL DEFAULT 0,
    consumption_wh REAL NOT NULL DEFAULT 0,
    import_wh REAL NOT NULL DEFAULT 0,
    export_wh REAL NOT NULL DEFAULT 0,
    self_consumption_wh REAL NOT NULL DEFAULT 0,
    battery_charge_wh REAL NOT NULL DEFAULT 0,
    battery_discharge_wh REAL NOT NULL DEFAULT 0,
    samples_count INTEGER NOT NULL DEFAULT 0,
    updated_at_utc TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_raw_points_ts ON raw_points(ts_utc);
"""


class Storage:
    def __init__(self, db_path: str | None = None):
        self._db_path = db_path or config.DB_PATH
        self._init_db()

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(_CREATE_TABLES)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def store_point(self, point: SensorPoint, source: str = "local_stream",
                    devices_json: str | None = None):
        """Speichere einen einzelnen Datenpunkt. Duplikate werden ignoriert."""
        ts_str = point.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO raw_points
                   (ts_utc, source, c_w, p_w, bc_w, bd_w,
                    c_wh, p_wh, bc_wh, bd_wh, sc_wh, cpv_wh, i_wh, e_wh,
                    soc, devices_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ts_str, source,
                 point.c_w, point.p_w, point.bc_w, point.bd_w,
                 point.c_wh, point.p_wh, point.bc_wh, point.bd_wh,
                 point.sc_wh, point.cpv_wh, point.i_wh, point.e_wh,
                 point.soc, devices_json),
            )

    def get_points_for_date(self, local_date: date,
                            tz: ZoneInfo | None = None) -> list[SensorPoint]:
        """Lade alle Datenpunkte für einen lokalen Kalendertag.

        Verwendet die konfigurierte Zeitzone (oder übergebene tz), um die
        UTC-Range für den lokalen Tag korrekt zu berechnen — auch bei
        Sommer-/Winterzeitwechsel.
        """
        if tz is None:
            tz = ZoneInfo(config.TIMEZONE)

        # Lokaler Tagesstart → UTC (respektiert DST-Offset automatisch)
        day_start_local = datetime(local_date.year, local_date.month,
                                   local_date.day, tzinfo=tz)
        day_start_utc = day_start_local.astimezone(timezone.utc)
        day_end_utc = (day_start_local + timedelta(days=1)).astimezone(timezone.utc)

        start_str = day_start_utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        end_str = day_end_utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM raw_points WHERE ts_utc >= ? AND ts_utc < ? ORDER BY ts_utc",
                (start_str, end_str),
            ).fetchall()

        return [self._row_to_point(row) for row in rows]

    def get_latest_point(self) -> SensorPoint | None:
        """Lade den neusten gespeicherten Datenpunkt."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM raw_points ORDER BY ts_utc DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return self._row_to_point(row)

    def store_daily_summary(self, summary: DailySummary):
        """Speichere oder aktualisiere eine Tages-Zusammenfassung."""
        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO daily_summary
                   (local_date, production_wh, consumption_wh, import_wh, export_wh,
                    self_consumption_wh, battery_charge_wh, battery_discharge_wh,
                    samples_count, updated_at_utc)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (summary.local_date.isoformat(),
                 summary.production_wh, summary.consumption_wh,
                 summary.import_wh, summary.export_wh,
                 summary.self_consumption_wh,
                 summary.battery_charge_wh, summary.battery_discharge_wh,
                 summary.samples, now_utc),
            )

    def get_daily_summaries(self, days: int = 30) -> list[DailySummary]:
        """Lade die letzten N Tages-Zusammenfassungen."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM daily_summary
                   ORDER BY local_date DESC LIMIT ?""",
                (days,),
            ).fetchall()

        return [self._row_to_daily(row) for row in reversed(rows)]

    def cleanup_old_points(self, retention_days: int | None = None):
        """Lösche raw_points älter als retention_days."""
        days = retention_days or config.RAW_RETENTION_DAYS
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with self._connect() as conn:
            result = conn.execute(
                "DELETE FROM raw_points WHERE ts_utc < ?", (cutoff_str,)
            )
            if result.rowcount > 0:
                logger.info("Cleaned up %d old raw points", result.rowcount)

    def point_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) as cnt FROM raw_points").fetchone()
        return row["cnt"]

    @staticmethod
    def _row_to_point(row: sqlite3.Row) -> SensorPoint:
        ts = datetime.fromisoformat(row["ts_utc"].replace("Z", "+00:00"))
        return SensorPoint(
            timestamp=ts,
            c_w=row["c_w"], p_w=row["p_w"],
            bc_w=row["bc_w"], bd_w=row["bd_w"],
            c_wh=row["c_wh"], p_wh=row["p_wh"],
            bc_wh=row["bc_wh"], bd_wh=row["bd_wh"],
            sc_wh=row["sc_wh"], cpv_wh=row["cpv_wh"],
            i_wh=row["i_wh"], e_wh=row["e_wh"],
            soc=row["soc"],
        )

    @staticmethod
    def _row_to_daily(row: sqlite3.Row) -> DailySummary:
        return DailySummary(
            local_date=date.fromisoformat(row["local_date"]),
            production_wh=row["production_wh"],
            consumption_wh=row["consumption_wh"],
            import_wh=row["import_wh"],
            export_wh=row["export_wh"],
            self_consumption_wh=row["self_consumption_wh"],
            battery_charge_wh=row["battery_charge_wh"],
            battery_discharge_wh=row["battery_discharge_wh"],
            samples=row["samples_count"],
        )
