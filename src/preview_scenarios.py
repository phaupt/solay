"""Static preview scenarios for dashboard state validation."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

from src.models import DashboardData, SensorPoint

SCENARIO_LABELS = {
    "pv_surplus": "Solar surplus",
    "pv_deficit": "Solar deficit",
    "night": "Night / grid only",
    "battery_support": "Battery supports house",
    "grid_charge": "Grid charges battery",
    "no_battery": "No battery",
    "stale": "Stale live data",
}


def _base_live(data: DashboardData) -> SensorPoint:
    if data.live is not None:
        return data.live
    return SensorPoint(
        timestamp=datetime.now(timezone.utc),
        c_w=0.0,
        p_w=0.0,
        bc_w=0.0,
        bd_w=0.0,
        soc=None,
    )


def apply_preview_scenario(data: DashboardData, scenario: str | None) -> DashboardData:
    name = (scenario or "").strip().lower()
    if not name:
        return data

    base = _base_live(data)

    if name == "pv_surplus":
        live = replace(base, p_w=5200.0, c_w=1800.0, bc_w=900.0, bd_w=0.0, soc=76.0)
    elif name == "pv_deficit":
        live = replace(base, p_w=2200.0, c_w=3600.0, bc_w=0.0, bd_w=0.0, soc=41.0)
    elif name == "night":
        live = replace(base, p_w=0.0, c_w=950.0, bc_w=0.0, bd_w=0.0, soc=62.0)
    elif name == "battery_support":
        live = replace(base, p_w=700.0, c_w=2600.0, bc_w=0.0, bd_w=1200.0, soc=48.0)
    elif name == "grid_charge":
        live = replace(base, p_w=0.0, c_w=900.0, bc_w=1400.0, bd_w=0.0, soc=30.0)
    elif name == "no_battery":
        live = replace(base, p_w=2600.0, c_w=1900.0, bc_w=0.0, bd_w=0.0, soc=None)
    elif name == "stale":
        live = replace(
            base,
            timestamp=datetime.now(timezone.utc) - timedelta(minutes=15),
            p_w=2200.0,
            c_w=3100.0,
            bc_w=0.0,
            bd_w=600.0,
            soc=84.0,
        )
    else:
        return data

    return DashboardData(
        live=live,
        chart_buckets=data.chart_buckets,
        daily_summary=data.daily_summary,
        daily_history=data.daily_history,
        history_labels=data.history_labels,
        devices=data.devices,
    )
