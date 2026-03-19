"""Shared flow-state helpers for dashboard renderers."""

from __future__ import annotations

FLOW_THRESHOLD_W = 50


def determine_flow_active(
    p_w: float,
    c_w: float,
    grid_w: float,
    bc_w: float,
    bd_w: float,
    has_bat: bool,
) -> dict[tuple[str, str], bool]:
    """Determine which energy flow paths are active.

    Battery charging source logic uses solar surplus to determine whether
    solar or grid feed the battery:
    - solar_surplus = max(0, p_w - c_w)
    - If surplus > threshold and battery charging -> Solar -> Battery
    - If grid importing and battery charging -> Grid -> Battery
    - Both can be true simultaneously (split charging)
    """
    solar_surplus = max(0, p_w - c_w)

    return {
        ("solar", "home"): p_w > FLOW_THRESHOLD_W and c_w > FLOW_THRESHOLD_W,
        ("solar", "grid"): grid_w < -FLOW_THRESHOLD_W,
        ("solar", "battery"): (
            has_bat and bc_w > FLOW_THRESHOLD_W and solar_surplus > FLOW_THRESHOLD_W
        ),
        ("grid", "home"): grid_w > FLOW_THRESHOLD_W,
        ("grid", "battery"): (
            has_bat and bc_w > FLOW_THRESHOLD_W and grid_w > FLOW_THRESHOLD_W
        ),
        ("battery", "home"): has_bat and bd_w > FLOW_THRESHOLD_W,
    }
