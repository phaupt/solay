"""Mock-Daten-Generator: Erzeugt realistische Zeitreihen für Tests und UI-Entwicklung.

Generiert einen kompletten Tag mit ~10s-Intervallen, basierend auf
der Anlage 14.725 kWp in Oberrieden. Die generierten Datenpunkte
entsprechen dem Format der Solar Manager lokalen API.

Design-Review-Modus: Erzeugt immer Daten bis 14:30 Lokalzeit mit
Batteriesimulation, unabhängig von der tatsächlichen Uhrzeit.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config
from src.models import DailySummary, DeviceStatus, SensorPoint
from src.storage import Storage

# Design-review cutoff: local hour at which mock data stops.
# 14.5 = 14:30, giving a nice mid-afternoon solar state.
DESIGN_REVIEW_HOUR = 14.5
DESIGN_REVIEW_RANDOM_SEED = 20260319

# Exact Figma review state for the live-flow panel.
DESIGN_REVIEW_LIVE_SAMPLE = {
    "p_w": 2204.0,
    "c_w": 3104.0,
    "bc_w": 0.0,
    "bd_w": 603.0,
    "soc": 84.0,
}

# Exact 7-day values currently shown in the approved Figma review.
DESIGN_REVIEW_WEEK_KWH = [
    ("Monday", 11.5, 5.0),
    ("Tuesday", 42.4, 10.2),
    ("Wednesday", 67.8, 5.2),
    ("Thursday", 39.8, 6.1),
    ("Friday", 32.1, 5.6),
    ("Saturday", 31.1, 7.5),
    ("Today", 57.3, 2.1),
]

# Battery simulation parameters
BATTERY_CAPACITY_WH = 10000  # 10 kWh typical home battery
BATTERY_MAX_CHARGE_W = 3500
BATTERY_MAX_DISCHARGE_W = 3500
BATTERY_INITIAL_SOC_PCT = 25.0


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


def _review_pv_curve(hour: float) -> float:
    """Spikier day profile matching the approved Figma review chart."""
    anchors = [
        (0.0, 0), (6.8, 0), (7.2, 150), (8.0, 2200), (8.8, 4600),
        (9.4, 6500), (10.0, 7600), (10.3, 3600), (10.6, 7400), (10.9, 6200),
        (11.2, 8800), (11.5, 5200), (11.8, 7900), (12.1, 7200), (12.4, 2400),
        (12.9, 9200), (13.2, 2800), (13.6, 4100), (14.0, 2100), (14.5, 3900),
        (15.0, 8900), (15.4, 4300), (15.8, 6600), (16.2, 3600), (16.7, 5400),
        (17.3, 3600), (18.0, 1200), (18.6, 0), (24.0, 0),
    ]
    return _interpolate_curve(hour, anchors)


def _review_consumption_curve(hour: float) -> float:
    anchors = [
        (0.0, 120), (6.5, 140), (7.0, 280), (7.6, 620), (8.2, 420),
        (9.0, 520), (9.8, 360), (10.8, 1450), (11.2, 380), (11.7, 1650),
        (12.2, 260), (13.1, 210), (14.0, 240), (15.2, 280), (16.1, 1050),
        (16.8, 260), (17.6, 920), (18.2, 1030), (19.0, 760), (20.0, 910),
        (21.0, 840), (22.0, 950), (23.0, 1020), (24.0, 150),
    ]
    return _interpolate_curve(hour, anchors)


def _interpolate_curve(hour: float, anchors: list[tuple[float, float]]) -> float:
    if hour <= anchors[0][0]:
        return anchors[0][1]
    if hour >= anchors[-1][0]:
        return anchors[-1][1]
    for index in range(1, len(anchors)):
        h0, v0 = anchors[index - 1]
        h1, v1 = anchors[index]
        if h0 <= hour <= h1:
            ratio = 0 if h1 == h0 else (hour - h0) / (h1 - h0)
            return v0 + (v1 - v0) * ratio
    return anchors[-1][1]


def generate_day_points(
    target_date: date | None = None,
    up_to_now: bool = True,
    up_to_local_hour: float | None = None,
    interval_seconds: int = 10,
    noise_factor: float = 0.05,
    simulate_battery: bool = False,
    initial_soc_pct: float = BATTERY_INITIAL_SOC_PCT,
    profile: str = "default",
    seed: int | None = None,
) -> list[SensorPoint]:
    """Generiere eine komplette Tages-Zeitreihe mit realistischen Werten.

    Args:
        target_date: Datum für das generiert wird (default: heute).
        up_to_now: Nur bis zur aktuellen Uhrzeit generieren.
        up_to_local_hour: Override cutoff with specific local hour (e.g. 14.5
            for 14:30). Takes precedence over up_to_now.
        interval_seconds: Intervall zwischen Datenpunkten.
        noise_factor: Relative Zufallsvariation (0.05 = 5%).
        simulate_battery: If True, simulate a home battery system.
        initial_soc_pct: Starting battery SOC in percent (0-100).

    Returns:
        Liste von SensorPoint-Objekten, chronologisch sortiert.
    """
    tz = ZoneInfo(config.TIMEZONE)

    if target_date is None:
        target_date = datetime.now(tz).date()

    points = []
    rng = random.Random(seed)

    # Tag von 00:00 bis 23:59 Lokalzeit (oder bis cutoff)
    day_start_local = datetime(
        target_date.year, target_date.month, target_date.day, tzinfo=tz,
    )
    day_start = day_start_local.astimezone(timezone.utc)
    day_end = (day_start_local + timedelta(days=1)).astimezone(timezone.utc)

    if up_to_local_hour is not None:
        # Fixed cutoff at specific local hour
        if up_to_local_hour >= 24:
            day_end = (day_start_local + timedelta(days=1)).astimezone(timezone.utc)
        else:
            cutoff_h = int(up_to_local_hour)
            cutoff_m = int((up_to_local_hour - cutoff_h) * 60)
            cutoff_local = day_start_local.replace(
                hour=cutoff_h, minute=cutoff_m, second=0,
            )
            day_end = cutoff_local.astimezone(timezone.utc)
    elif up_to_now:
        now = datetime.now(timezone.utc)
        if day_end > now:
            day_end = now

    # Battery state
    soc = initial_soc_pct if simulate_battery else None
    interval_h = interval_seconds / 3600.0

    current = day_start
    while current < day_end:
        local_dt = current.astimezone(tz)
        local_hour = local_dt.hour + local_dt.minute / 60.0

        # Leistungswerte mit Rauschen
        pv_curve = _review_pv_curve if profile == "figma_review" else _solar_curve
        cons_curve = _review_consumption_curve if profile == "figma_review" else _consumption_curve
        pv = pv_curve(local_hour) * (1 + rng.gauss(0, noise_factor))
        pv = max(0, round(pv))
        cons = cons_curve(local_hour) * (1 + rng.gauss(0, noise_factor))
        cons = max(100, round(cons))

        # Battery simulation
        bc_w_val = 0.0
        bd_w_val = 0.0
        current_soc = soc

        if simulate_battery and soc is not None:
            surplus = pv - cons
            if surplus > 50 and soc < 98:
                # Charge from solar surplus
                bc_w_val = min(surplus * 0.7, BATTERY_MAX_CHARGE_W)
                max_energy = (100 - soc) / 100 * BATTERY_CAPACITY_WH
                bc_w_val = min(bc_w_val, max_energy / interval_h)
                energy_wh = bc_w_val * interval_h
                soc = min(100, soc + energy_wh / BATTERY_CAPACITY_WH * 100)
            elif surplus < -50 and soc > 5:
                # Discharge to cover deficit
                bd_w_val = min(-surplus * 0.5, BATTERY_MAX_DISCHARGE_W)
                max_energy = soc / 100 * BATTERY_CAPACITY_WH
                bd_w_val = min(bd_w_val, max_energy / interval_h)
                energy_wh = bd_w_val * interval_h
                soc = max(0, soc - energy_wh / BATTERY_CAPACITY_WH * 100)
            current_soc = soc

        # Energiebilanz (battery-aware)
        self_cons_w = min(pv, cons + bc_w_val)
        grid_w = cons + bc_w_val - pv - bd_w_val
        import_w = max(0, grid_w)
        export_w = max(0, -grid_w)

        points.append(SensorPoint(
            timestamp=current,
            c_w=cons,
            p_w=pv,
            bc_w=round(bc_w_val),
            bd_w=round(bd_w_val),
            c_wh=round(cons * interval_h, 4),
            p_wh=round(pv * interval_h, 4),
            bc_wh=round(bc_w_val * interval_h, 4),
            bd_wh=round(bd_w_val * interval_h, 4),
            sc_wh=round(self_cons_w * interval_h, 4),
            cpv_wh=round(min(pv, cons) * interval_h, 4),
            i_wh=round(import_w * interval_h, 4),
            e_wh=round(export_w * interval_h, 4),
            soc=current_soc,
        ))

        current += timedelta(seconds=interval_seconds)

    return points


def generate_history_summaries(days: int = 30) -> list[DailySummary]:
    """Generiere Tages-Zusammenfassungen für die letzten N Tage."""
    summaries = []
    today = datetime.now(ZoneInfo(config.TIMEZONE)).date()
    review_start = today - timedelta(days=6)
    rng = random.Random(DESIGN_REVIEW_RANDOM_SEED)

    for i in range(days, 0, -1):
        d = today - timedelta(days=i)
        if d >= review_start:
            offset = (d - review_start).days
            _, prod_kwh, cons_kwh = DESIGN_REVIEW_WEEK_KWH[offset]
            prod = round(prod_kwh * 1000)
            cons = round(cons_kwh * 1000)
            self_cons = min(prod, cons) * 0.92
            export = max(0, prod - self_cons)
            imp = max(0, cons - self_cons)
        else:
            weather = rng.choice([0.3, 0.5, 0.7, 0.85, 0.95, 1.0, 1.0, 0.9])
            prod = round(40000 * weather * (1 + rng.gauss(0, 0.1)))
            cons = round(12000 * (1 + rng.gauss(0, 0.15)))
            self_cons = min(prod, cons) * rng.uniform(0.85, 0.98)
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


def get_mock_review_history() -> list[DailySummary]:
    """Return the exact 7-day strip shown in the approved Figma review."""
    today = datetime.now(ZoneInfo(config.TIMEZONE)).date()
    start = today - timedelta(days=6)
    items: list[DailySummary] = []
    for offset, (_, prod_kwh, cons_kwh) in enumerate(DESIGN_REVIEW_WEEK_KWH):
        local_date = start + timedelta(days=offset)
        prod_wh = round(prod_kwh * 1000)
        cons_wh = round(cons_kwh * 1000)
        self_cons = min(prod_wh, cons_wh) * 0.92
        items.append(
            DailySummary(
                local_date=local_date,
                production_wh=prod_wh,
                consumption_wh=cons_wh,
                import_wh=max(0, cons_wh - self_cons),
                export_wh=max(0, prod_wh - self_cons),
                self_consumption_wh=self_cons,
                battery_charge_wh=0,
                battery_discharge_wh=0,
                samples=8640,
            )
        )
    return items


def seed_mock_database(storage: Storage):
    """Befülle die Datenbank mit realistischen Mock-Daten.

    Design-Review-Modus: Generiert Daten bis 14:30 Lokalzeit mit
    Batteriesimulation, damit die Vorschau unabhängig von der Tageszeit
    immer einen repräsentativen Zustand zeigt.

    Erzeugt:
    - Heutigen Tagesverlauf bis 14:30 mit Batterie (für Chart + Flow)
    - 30 Tage Historie (für 7-Tage-Strip)
    """
    import logging
    logger = logging.getLogger(__name__)

    # Heute: Zeitreihe bis Design-Review-Cutoff mit Batteriesimulation
    logger.info("Generiere Mock-Zeitreihe (Figma-Review-Profil, voller Tag mit Referenz-Livezustand)...")
    today_points = generate_day_points(
        up_to_now=False,
        up_to_local_hour=24.0,
        simulate_battery=True,
        profile="figma_review",
        seed=DESIGN_REVIEW_RANDOM_SEED,
    )
    for point in today_points:
        storage.store_point(point, source="mock")
    logger.info("  %d Datenpunkte gespeichert", len(today_points))

    # Historie: Tages-Zusammenfassungen
    logger.info("Generiere 30-Tage Mock-Historie...")
    summaries = generate_history_summaries(days=30)
    for summary in summaries:
        storage.store_daily_summary(summary)
    logger.info("  %d Tages-Zusammenfassungen gespeichert", len(summaries))


def get_mock_live_point() -> SensorPoint:
    """Return the exact live state used in the current approved Figma review."""
    tz = ZoneInfo(config.TIMEZONE)
    today = datetime.now(tz).date()
    live_local = datetime(today.year, today.month, today.day, 14, 32, tzinfo=tz)
    live_utc = live_local.astimezone(timezone.utc)
    p_w = DESIGN_REVIEW_LIVE_SAMPLE["p_w"]
    c_w = DESIGN_REVIEW_LIVE_SAMPLE["c_w"]
    bc_w = DESIGN_REVIEW_LIVE_SAMPLE["bc_w"]
    bd_w = DESIGN_REVIEW_LIVE_SAMPLE["bd_w"]
    return SensorPoint(
        timestamp=live_utc,
        c_w=c_w,
        p_w=p_w,
        bc_w=bc_w,
        bd_w=bd_w,
        c_wh=round(c_w / 360.0, 4),
        p_wh=round(p_w / 360.0, 4),
        bc_wh=round(bc_w / 360.0, 4),
        bd_wh=round(bd_w / 360.0, 4),
        sc_wh=round(min(p_w, c_w) / 360.0, 4),
        cpv_wh=round(min(p_w, c_w) / 360.0, 4),
        i_wh=round(max(0, c_w + bc_w - p_w - bd_w) / 360.0, 4),
        e_wh=round(max(0, -(c_w + bc_w - p_w - bd_w)) / 360.0, 4),
        soc=DESIGN_REVIEW_LIVE_SAMPLE["soc"],
    )
