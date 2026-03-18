"""Mock-Daten-Generator: Erzeugt realistische Zeitreihen für Tests und UI-Entwicklung.

Generiert einen kompletten Tag mit ~10s-Intervallen, basierend auf
der Anlage 14.725 kWp in Oberrieden. Die generierten Datenpunkte
entsprechen dem Format der Solar Manager lokalen API.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta, timezone

from src.models import DailySummary, DeviceStatus, SensorPoint
from src.storage import Storage


def _solar_curve(hour: float) -> float:
    """PV-Produktionskurve: Gauss-Glocke um 12:30 Uhr, Max bei ~9.5 kW.

    Kalibriert auf ~35-40 kWh an einem guten Frühlingstag (14.7 kWp Anlage).
    """
    return max(0, 9500 * math.exp(-0.5 * ((hour - 12.5) / 2.5) ** 2))


def _consumption_curve(hour: float) -> float:
    """Typisches Haushaltsprofil: Grundlast + Morgen/Abend-Peaks."""
    base = 350  # Grundlast
    morning_peak = 800 * math.exp(-0.5 * ((hour - 7.5) / 1.0) ** 2)
    noon_peak = 400 * math.exp(-0.5 * ((hour - 12.0) / 1.5) ** 2)
    evening_peak = 1200 * math.exp(-0.5 * ((hour - 19.0) / 2.0) ** 2)
    return base + morning_peak + noon_peak + evening_peak


def generate_day_points(
    target_date: date | None = None,
    up_to_now: bool = True,
    interval_seconds: int = 10,
    noise_factor: float = 0.05,
) -> list[SensorPoint]:
    """Generiere eine komplette Tages-Zeitreihe mit realistischen Werten.

    Args:
        target_date: Datum für das generiert wird (default: heute).
        up_to_now: Nur bis zur aktuellen Uhrzeit generieren.
        interval_seconds: Intervall zwischen Datenpunkten.
        noise_factor: Relative Zufallsvariation (0.05 = 5%).

    Returns:
        Liste von SensorPoint-Objekten, chronologisch sortiert.
    """
    if target_date is None:
        target_date = date.today()

    points = []
    now = datetime.now(timezone.utc)

    # Tag von 00:00 bis 23:59 (oder bis jetzt)
    day_start = datetime(
        target_date.year, target_date.month, target_date.day,
        tzinfo=timezone(timedelta(hours=1)),  # CET
    ).astimezone(timezone.utc)

    day_end = day_start + timedelta(days=1)
    if up_to_now and day_end > now:
        day_end = now

    current = day_start
    while current < day_end:
        local_hour = (current + timedelta(hours=1)).hour + \
                     (current + timedelta(hours=1)).minute / 60.0

        # Leistungswerte mit Rauschen
        pv = _solar_curve(local_hour) * (1 + random.gauss(0, noise_factor))
        pv = max(0, round(pv))
        cons = _consumption_curve(local_hour) * (1 + random.gauss(0, noise_factor))
        cons = max(100, round(cons))

        # Energiebilanz
        self_cons_w = min(pv, cons)
        grid_w = cons - pv  # Vereinfacht ohne Batterie

        import_w = max(0, grid_w)
        export_w = max(0, -grid_w)

        # Wh pro Intervall = W * (Intervall_s / 3600)
        interval_h = interval_seconds / 3600.0

        points.append(SensorPoint(
            timestamp=current,
            c_w=cons,
            p_w=pv,
            bc_w=0,
            bd_w=0,
            c_wh=round(cons * interval_h, 4),
            p_wh=round(pv * interval_h, 4),
            bc_wh=0,
            bd_wh=0,
            sc_wh=round(self_cons_w * interval_h, 4),
            cpv_wh=round(self_cons_w * interval_h, 4),
            i_wh=round(import_w * interval_h, 4),
            e_wh=round(export_w * interval_h, 4),
            soc=None,
        ))

        current += timedelta(seconds=interval_seconds)

    return points


def generate_history_summaries(days: int = 30) -> list[DailySummary]:
    """Generiere Tages-Zusammenfassungen für die letzten N Tage."""
    summaries = []
    today = date.today()

    for i in range(days, 0, -1):
        d = today - timedelta(days=i)
        # Wettervariabilität
        weather = random.choice([0.3, 0.5, 0.7, 0.85, 0.95, 1.0, 1.0, 0.9])
        prod = round(40000 * weather * (1 + random.gauss(0, 0.1)))  # ~40 kWh Spitzentag
        cons = round(12000 * (1 + random.gauss(0, 0.15)))
        self_cons = min(prod, cons) * random.uniform(0.85, 0.98)
        export = prod - self_cons
        imp = max(0, cons - self_cons)

        summaries.append(DailySummary(
            local_date=d,
            production_wh=max(0, prod),
            consumption_wh=max(500, cons),
            import_wh=max(0, imp),
            export_wh=max(0, export),
            self_consumption_wh=max(0, self_cons),
            battery_charge_wh=0,
            battery_discharge_wh=0,
            samples=8640,  # ~1 Tag bei 10s-Intervall
        ))

    return summaries


def get_mock_devices() -> list[DeviceStatus]:
    """Simulierte Geräteliste."""
    return [
        DeviceStatus(device_id="wattpilot_01", name="Wattpilot",
                     signal="connected", power_w=0),
        DeviceStatus(device_id="boiler_01", name="Boiler",
                     signal="connected", power_w=0),
    ]


def seed_mock_database(storage: Storage):
    """Befülle die Datenbank mit realistischen Mock-Daten.

    Erzeugt:
    - Heutigen Tagesverlauf (für Chart)
    - 30 Tage Historie (für PV-Performance)
    """
    import logging
    logger = logging.getLogger(__name__)

    # Heute: komplette Zeitreihe
    logger.info("Generiere Mock-Zeitreihe für heute...")
    today_points = generate_day_points(up_to_now=True)
    for point in today_points:
        storage.store_point(point, source="mock")
    logger.info("  %d Datenpunkte gespeichert", len(today_points))

    # Historie: Tages-Zusammenfassungen
    logger.info("Generiere 30-Tage Mock-Historie...")
    summaries = generate_history_summaries(days=30)
    for summary in summaries:
        storage.store_daily_summary(summary)
    logger.info("  %d Tages-Zusammenfassungen gespeichert", len(summaries))
