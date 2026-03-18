"""Aggregator: Berechnet Chart-Buckets und Tages-Zusammenfassungen aus Rohdaten.

Wichtig: Die Wh-Werte der API gelten pro Intervall (~10s). Tageswerte
entstehen durch Aufsummierung aller gespeicherten Intervalle eines Tages.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from src.models import ChartBucket, DailySummary, SensorPoint

logger = logging.getLogger(__name__)

# Chart-Bucket-Grösse in Minuten
CHART_BUCKET_MINUTES = 5


def aggregate_chart_buckets(
    points: list[SensorPoint],
    bucket_minutes: int = CHART_BUCKET_MINUTES,
) -> list[ChartBucket]:
    """Gruppiere Datenpunkte in Zeitintervalle für die Tagesgrafik.

    Berechnet Durchschnittswerte der Leistung (W) pro Bucket.
    """
    if not points:
        return []

    buckets: dict[datetime, list[SensorPoint]] = defaultdict(list)

    for p in points:
        # Runde auf Bucket-Start
        ts = p.timestamp.replace(second=0, microsecond=0)
        minute = (ts.minute // bucket_minutes) * bucket_minutes
        bucket_ts = ts.replace(minute=minute)
        buckets[bucket_ts].append(p)

    result = []
    for bucket_ts in sorted(buckets.keys()):
        pts = buckets[bucket_ts]
        n = len(pts)
        result.append(
            ChartBucket(
                timestamp=bucket_ts,
                p_w_avg=sum(p.p_w for p in pts) / n,
                c_w_avg=sum(p.c_w for p in pts) / n,
                grid_w_avg=sum(p.grid_w for p in pts) / n,
                bc_w_avg=sum(p.bc_w for p in pts) / n,
                bd_w_avg=sum(p.bd_w for p in pts) / n,
                samples=n,
            )
        )

    return result


def aggregate_daily_summary(points: list[SensorPoint], local_date: date) -> DailySummary:
    """Berechne Tages-Zusammenfassung durch Aufsummierung der Intervall-Wh-Werte.

    Dies ist die fachlich korrekte Methode: jeder Datenpunkt liefert Wh für
    sein ~10s-Intervall, die Tagessumme ergibt sich aus der Addition.
    """
    if not points:
        return DailySummary(local_date=local_date)

    return DailySummary(
        local_date=local_date,
        production_wh=sum(p.p_wh for p in points),
        consumption_wh=sum(p.c_wh for p in points),
        import_wh=sum(p.i_wh for p in points),
        export_wh=sum(p.e_wh for p in points),
        self_consumption_wh=sum(p.sc_wh for p in points),
        battery_charge_wh=sum(p.bc_wh for p in points),
        battery_discharge_wh=sum(p.bd_wh for p in points),
        samples=len(points),
    )
