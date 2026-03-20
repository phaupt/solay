"""HTML/CSS/SVG dashboard renderer for browser-faithful preview."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from markupsafe import Markup

import config
from src.flow_logic import FLOW_THRESHOLD_W, determine_flow_active
from src.i18n import normalize_language, tr, weekday_name
from src.models import DashboardData

SVG_NS = "http://www.w3.org/2000/svg"
_FLOW_KEYS = [
    ("solar", "home"),
    ("solar", "grid"),
    ("solar", "battery"),
    ("grid", "home"),
    ("grid", "battery"),
    ("battery", "home"),
]
_STRAIGHT_PATHS = set(_FLOW_KEYS)


def _local_timezone() -> ZoneInfo:
    return ZoneInfo(config.TIMEZONE)


def _to_local_timestamp(ts: datetime) -> datetime:
    tz = _local_timezone()
    if ts.tzinfo is None:
        return ts.replace(tzinfo=tz)
    return ts.astimezone(tz)


def _resolved_theme(theme: str | None) -> str:
    candidate = (theme or config.DASHBOARD_THEME or "light").strip().lower()
    return candidate if candidate in {"light", "dark"} else "light"


def _resolved_language(language: str | None) -> str:
    return normalize_language(language or config.DASHBOARD_LANGUAGE)


def _format_kw_value(watts: float) -> str:
    kw = abs(watts) / 1000
    if kw < 0.01:
        return "0"
    if kw >= 100:
        return f"{kw:.0f}"
    if kw >= 10:
        return f"{kw:.1f}"
    return f"{kw:.2f}"


def _format_kw_signed(watts: float) -> str:
    if abs(watts) < FLOW_THRESHOLD_W:
        return "0"
    sign = "+" if watts > 0 else "\u2212"
    return f"{sign}{_format_kw_value(watts)}"


def _format_kwh(wh: float) -> str:
    kwh = wh / 1000
    if kwh >= 100:
        return f"{kwh:.0f}"
    return f"{kwh:.1f}"


def _format_watts_label(watts: float) -> str:
    return f"{int(round(max(0.0, watts)))} W"


def _history_name_class(label: str) -> str:
    length = len(label)
    if length <= 5:
        return "history-day__name--short"
    if length <= 7:
        return "history-day__name--medium"
    if length <= 9:
        return "history-day__name--long"
    return "history-day__name--xlong"


def _is_live_stale(data: DashboardData) -> bool:
    if data.live is None:
        return False
    delta = datetime.now(_local_timezone()) - _to_local_timestamp(data.live.timestamp)
    return delta.total_seconds() > config.STALE_DATA_SECONDS


def _battery_secondary(data: DashboardData, language: str) -> tuple[str, str, bool]:
    live = data.live
    if live is None or not live.has_battery:
        return "\u2014", "", True

    primary = _format_kw_value(max(live.bc_w, live.bd_w))

    if live.soc is not None:
        secondary = f"kW \u00b7 {int(round(live.soc))}%"
    elif live.bc_w > FLOW_THRESHOLD_W or live.bd_w > FLOW_THRESHOLD_W:
        secondary = "kW"
    else:
        secondary = "kW"
    return primary, secondary, False


def _battery_fill_ratio(soc: float | None) -> float:
    if soc is None:
        return 0.0
    return max(0.0, min(1.0, soc / 100.0))


def _node_state(data: DashboardData, language: str) -> dict[str, dict[str, object]]:
    live = data.live
    if live is None:
        return {
            "solar": {"label": tr(language, "node_solar"), "value": "\u2014", "sub": tr(language, "no_live_data"), "dimmed": True},
            "grid": {"label": tr(language, "node_grid"), "value": "\u2014", "sub": tr(language, "no_live_data"), "dimmed": True},
            "home": {"label": tr(language, "node_home"), "value": "\u2014", "sub": tr(language, "no_live_data"), "dimmed": True},
            "battery": {"label": tr(language, "node_battery"), "value": "\u2014", "sub": tr(language, "unavailable"), "dimmed": True},
        }

    battery_value, battery_sub, battery_dimmed = _battery_secondary(data, language)
    stale = _is_live_stale(data)
    return {
        "solar": {
            "label": tr(language, "node_solar"),
            "value": _format_kw_value(live.p_w),
            "sub": "kW",
            "dimmed": stale and live.p_w <= FLOW_THRESHOLD_W,
        },
        "grid": {
            "label": tr(language, "node_grid"),
            "value": _format_kw_signed(live.grid_w),
            "sub": "kW",
            "dimmed": stale and abs(live.grid_w) <= FLOW_THRESHOLD_W,
        },
        "home": {
            "label": tr(language, "node_home"),
            "value": _format_kw_value(live.c_w),
            "sub": "kW",
            "dimmed": stale and live.c_w <= FLOW_THRESHOLD_W,
        },
        "battery": {
            "label": tr(language, "node_battery"),
            "value": battery_value,
            "sub": battery_sub,
            "dimmed": stale or battery_dimmed,
        },
    }


def _icon_markup(kind: str, *, battery_soc: float | None = None) -> str:
    if kind == "solar":
        return """
        <g class="flow-node__icon-shape" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">
          <circle cx="0" cy="-10" r="8"></circle>
          <line x1="0" y1="-26" x2="0" y2="-21"></line>
          <line x1="0" y1="1" x2="0" y2="6"></line>
          <line x1="-16" y1="-10" x2="-11" y2="-10"></line>
          <line x1="11" y1="-10" x2="16" y2="-10"></line>
          <line x1="-11.5" y1="-21.5" x2="-8" y2="-18"></line>
          <line x1="8" y1="-18" x2="11.5" y2="-21.5"></line>
          <line x1="-11.5" y1="1.5" x2="-8" y2="-2"></line>
          <line x1="8" y1="-2" x2="11.5" y2="1.5"></line>
        </g>
        """
    if kind == "grid":
        return """
        <g class="flow-node__icon-shape" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
          <path d="M0 -22 L-12 18"></path>
          <path d="M0 -22 L12 18"></path>
          <path d="M-16 -10 H16"></path>
          <path d="M-10 1 H10"></path>
          <path d="M-5 11 H5"></path>
          <path d="M-9 -10 L0 1 L9 -10"></path>
          <path d="M-6 1 L0 11 L6 1"></path>
        </g>
        """
    if kind == "home":
        return """
        <g class="flow-node__icon-shape" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
          <path d="M-17 -2 L0 -17 L17 -2"></path>
          <path d="M-12 -3 V15 H12 V-3"></path>
          <path d="M-2 15 V5 H5 V15"></path>
        </g>
        """
    if kind == "battery":
        fill_ratio = _battery_fill_ratio(battery_soc)
        max_fill_width = 32.0
        fill_width = max_fill_width * fill_ratio
        return f"""
        <g class="flow-node__icon-shape" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
          <rect class="flow-node__icon-battery-track" x="-17" y="-7" width="32" height="14" rx="3.4"></rect>
          <rect class="flow-node__icon-battery-fill" x="-17" y="-7" width="{fill_width:.1f}" height="14" rx="3.4"></rect>
          <rect x="-21" y="-11" width="42" height="22" rx="5"></rect>
          <line x1="21" y1="-4" x2="28" y2="-4"></line>
          <line x1="21" y1="4" x2="28" y2="4"></line>
        </g>
        """
    return """
    <g class="flow-node__icon-shape" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
      <path d="M-17 -2 L0 -17 L17 -2"></path>
      <path d="M-12 -3 V15 H12 V-3"></path>
      <path d="M-2 15 V5 H5 V15"></path>
    </g>
    """


def _flow_path_d(
    key: tuple[str, str],
    start: tuple[float, float],
    end: tuple[float, float],
    center: tuple[float, float],
    *,
    is_straight: bool,
) -> str:
    if is_straight:
        return f"M {start[0]:.1f} {start[1]:.1f} L {end[0]:.1f} {end[1]:.1f}"
    control_points = {
        ("solar", "grid"): (center[0] - 124, center[1] - 92),
        ("solar", "home"): (center[0] + 126, center[1] - 92),
        ("grid", "battery"): (center[0] - 122, center[1] + 96),
        ("battery", "home"): (center[0] + 122, center[1] + 96),
    }
    control_x, control_y = control_points.get(key, center)
    return (
        f"M {start[0]:.1f} {start[1]:.1f} "
        f"Q {control_x:.1f} {control_y:.1f} {end[0]:.1f} {end[1]:.1f}"
    )


def _flow_point_and_angle(
    key: tuple[str, str],
    start: tuple[float, float],
    end: tuple[float, float],
    center: tuple[float, float],
    *,
    t: float = 0.5,
    is_straight: bool,
) -> tuple[float, float, float]:
    if is_straight:
        mid_x = start[0] + ((end[0] - start[0]) * t)
        mid_y = start[1] + ((end[1] - start[1]) * t)
        dx = end[0] - start[0]
        dy = end[1] - start[1]
    else:
        control_points = {
            ("solar", "grid"): (center[0] - 124, center[1] - 92),
            ("solar", "home"): (center[0] + 126, center[1] - 92),
            ("grid", "battery"): (center[0] - 122, center[1] + 96),
            ("battery", "home"): (center[0] + 122, center[1] + 96),
        }
        cx, cy = control_points.get(key, center)
        mt = 1 - t
        mid_x = (mt * mt * start[0]) + (2 * mt * t * cx) + (t * t * end[0])
        mid_y = (mt * mt * start[1]) + (2 * mt * t * cy) + (t * t * end[1])
        dx = 2 * mt * (cx - start[0]) + 2 * t * (end[0] - cx)
        dy = 2 * mt * (cy - start[1]) + 2 * t * (end[1] - cy)

    angle = 0.0
    if dx or dy:
        import math

        angle = math.degrees(math.atan2(dy, dx))
    return mid_x, mid_y, angle


def _build_flow_svg(data: DashboardData, language: str) -> Markup:
    width, height = 760, 760
    cx = width / 2
    radius = 98
    positions = {
        "solar": (cx, 122),
        "grid": (156, 374),
        "home": (604, 374),
        "battery": (cx, 620),
    }
    center = (cx, 374)
    edge_gap = 10
    edges = {
        "solar": (positions["solar"][0], positions["solar"][1] + radius + edge_gap),
        "grid": (positions["grid"][0] + radius + edge_gap, positions["grid"][1]),
        "home": (positions["home"][0] - radius - edge_gap, positions["home"][1]),
        "battery": (positions["battery"][0], positions["battery"][1] - radius - edge_gap),
    }

    active_map = {key: False for key in _FLOW_KEYS}
    stale = _is_live_stale(data)
    if data.live is not None and not stale:
        active_map.update(
            determine_flow_active(
                data.live.p_w,
                data.live.c_w,
                data.live.grid_w,
                data.live.bc_w,
                data.live.bd_w,
                data.live.has_battery,
            )
        )

    path_markup: list[str] = []
    arrow_markup: list[str] = []
    for key in _FLOW_KEYS:
        path_d = _flow_path_d(
            key,
            edges[key[0]],
            edges[key[1]],
            center,
            is_straight=key in _STRAIGHT_PATHS,
        )
        path_markup.append(
            f'<path class="flow-path flow-path--inactive" d="{path_d}" />'
        )
    for key in _FLOW_KEYS:
        if active_map.get(key, False):
            path_d = _flow_path_d(
                key,
                edges[key[0]],
                edges[key[1]],
                center,
                is_straight=key in _STRAIGHT_PATHS,
            )
            path_markup.append(
                f'<path class="flow-path flow-path--active" d="{path_d}" />'
            )
            arrow_x, arrow_y, arrow_angle = _flow_point_and_angle(
                key,
                edges[key[0]],
                edges[key[1]],
                center,
                t=0.5,
                is_straight=key in _STRAIGHT_PATHS,
            )
            import math

            offset_dx = math.cos(math.radians(arrow_angle)) * 13
            offset_dy = math.sin(math.radians(arrow_angle)) * 13
            for direction in (-1, 1):
                arrow_markup.append(
                    f'<g class="flow-arrow" transform="translate({arrow_x + (direction * offset_dx):.1f} {arrow_y + (direction * offset_dy):.1f}) rotate({arrow_angle:.1f})">'
                    '<path d="M -18 -11 L 5 0 L -18 11 Z" />'
                    '</g>'
                )

    node_state = _node_state(data, language)
    node_markup: list[str] = []
    for kind, (x, y) in positions.items():
        state = node_state[kind]
        dimmed_class = " is-dimmed" if state["dimmed"] else ""
        value = escape(str(state["value"]))
        sub = escape(str(state["sub"]))
        battery_soc = data.live.soc if kind == "battery" and data.live is not None else None
        node_markup.append(
            f'''
            <g class="flow-node{dimmed_class}" transform="translate({x} {y})">
              <circle class="flow-node__circle" r="{radius}" />
              <g class="flow-node__icon">{_icon_markup(kind, battery_soc=battery_soc)}</g>
              <text class="flow-node__value" x="0" y="30" text-anchor="middle">{value}</text>
              <text class="flow-node__sub" x="0" y="66" text-anchor="middle">{sub}</text>
            </g>
            '''
        )

    status_markup = ""
    if data.live is None:
        status_markup = (
            '<text class="flow-state flow-state--offline" x="380" y="736" text-anchor="middle">'
            f"{escape(tr(language, 'no_live_data'))}</text>"
        )

    svg = f"""
    <svg class="flow-svg" viewBox="0 0 {width} {height}" xmlns="{SVG_NS}" role="img" aria-label="{escape(tr(language, 'flow_aria'))}">
      <g class="flow-paths">
        {''.join(path_markup)}
      </g>
      <g class="flow-arrows">
        {''.join(arrow_markup)}
      </g>
      <g class="flow-nodes">
        {''.join(node_markup)}
      </g>
      {status_markup}
    </svg>
    """
    return Markup(svg)


def _chart_area_path(points: list[tuple[float, float]], baseline_y: float) -> str:
    if not points:
        return ""
    first = points[0]
    last = points[-1]
    segments = [f"M {first[0]:.1f} {baseline_y:.1f}", f"L {first[0]:.1f} {first[1]:.1f}"]
    segments.extend(f"L {x:.1f} {y:.1f}" for x, y in points[1:])
    segments.append(f"L {last[0]:.1f} {baseline_y:.1f} Z")
    return " ".join(segments)


def _chart_line_path(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    first = points[0]
    segments = [f"M {first[0]:.1f} {first[1]:.1f}"]
    segments.extend(f"L {x:.1f} {y:.1f}" for x, y in points[1:])
    return " ".join(segments)


def _build_chart_svg(data: DashboardData, language: str) -> Markup:
    width, height = 760, 840
    left_pad, right_pad = 76, 10
    top_pad, bottom_pad = 10, 34
    plot_left = left_pad
    plot_top = top_pad
    plot_right = width - right_pad
    plot_bottom = height - bottom_pad
    plot_width = plot_right - plot_left
    plot_height = plot_bottom - plot_top

    def time_to_x(hours: float) -> float:
        return plot_left + (plot_width * hours / 24.0)

    buckets = data.chart_buckets
    chart_peak_production_w = max((bucket.p_w_avg for bucket in buckets), default=0.0)
    max_power = max(
        chart_peak_production_w,
        max((bucket.c_w_avg for bucket in buckets), default=0.0),
    )
    padded_peak = max_power * 1.02
    y_max = max(4000, int(((padded_peak + 1999) // 2000) * 2000))

    def power_to_y(watts: float) -> float:
        clamped = max(0.0, min(watts, y_max))
        return plot_bottom - (plot_height * clamped / y_max)

    grid_lines: list[str] = []
    y_step = max(2000, int(((y_max / 6) + 1999) // 2000) * 2000)
    for value in range(0, y_max + 1, y_step):
        y = power_to_y(value)
        grid_lines.append(
            f'<line class="chart-grid-line" x1="{plot_left:.1f}" y1="{y:.1f}" x2="{plot_right:.1f}" y2="{y:.1f}" />'
        )
        grid_lines.append(
            f'<text class="chart-axis chart-axis--y" x="{plot_left - 12:.1f}" y="{y + 6:.1f}" text-anchor="end">{int(value / 1000)} kW</text>'
        )

    x_labels: list[str] = []
    for hour in range(0, 25, 2):
        x = time_to_x(hour)
        label = "24" if hour == 24 else f"{hour:02d}"
        x_labels.append(
            f'<text class="chart-axis chart-axis--x" x="{x:.1f}" y="{plot_bottom + 22:.1f}" text-anchor="middle">{label}</text>'
        )

    production_points: list[tuple[float, float]] = []
    consumption_points: list[tuple[float, float]] = []
    if buckets:
        tz = _local_timezone()
        for bucket in buckets:
            local = bucket.timestamp.astimezone(tz)
            hour = local.hour + local.minute / 60.0
            x = time_to_x(hour)
            production_points.append((x, power_to_y(bucket.p_w_avg)))
            consumption_points.append((x, power_to_y(bucket.c_w_avg)))

    production_area = _chart_area_path(production_points, plot_bottom)
    consumption_area = _chart_area_path(consumption_points, plot_bottom)
    production_line = _chart_line_path(production_points)
    consumption_line = _chart_line_path(consumption_points)
    peak_line_markup = ""
    peak_label_markup = ""
    marker_peak_w = chart_peak_production_w or data.peak_production_w
    if marker_peak_w > 0:
        peak_y = power_to_y(marker_peak_w)
        label_y = min(max(plot_top + 18, peak_y - 10), plot_bottom - 8)
        peak_line_markup = (
            f'<line class="chart-peak-line" x1="{plot_left:.1f}" y1="{peak_y:.1f}" '
            f'x2="{plot_right:.1f}" y2="{peak_y:.1f}" />'
            f'<circle class="chart-peak-dot" cx="{plot_right:.1f}" cy="{peak_y:.1f}" r="4.5" />'
        )
        peak_label = (
            f"{tr(language, 'peak_production')}: {_format_watts_label(marker_peak_w)}"
        )
        peak_label_markup = (
            f'<text class="chart-peak-label" x="{plot_right - 8:.1f}" y="{label_y:.1f}" '
            f'text-anchor="end">{escape(peak_label)}</text>'
        )

    empty_markup = ""
    if not buckets:
        empty_markup = (
            f'<text class="chart-empty" x="{width / 2:.1f}" y="{height / 2:.1f}" text-anchor="middle">'
            f"{escape(tr(language, 'current_day_empty'))}</text>"
        )

    svg = f"""
    <svg class="chart-svg" viewBox="0 0 {width} {height}" xmlns="{SVG_NS}" role="img" aria-label="{escape(tr(language, 'chart_aria'))}">
      <g class="chart-grid">
        {''.join(grid_lines)}
      </g>
      {peak_line_markup}
      {f'<path class="chart-area chart-area--production" d="{production_area}" />' if production_area else ''}
      {f'<path class="chart-area chart-area--consumption" d="{consumption_area}" />' if consumption_area else ''}
      {f'<path class="chart-line chart-line--production" d="{production_line}" />' if production_line else ''}
      {f'<path class="chart-line chart-line--consumption" d="{consumption_line}" />' if consumption_line else ''}
      {peak_label_markup}
      <line class="chart-axis-line" x1="{plot_left:.1f}" y1="{plot_bottom:.1f}" x2="{plot_right:.1f}" y2="{plot_bottom:.1f}" />
      <line class="chart-axis-line" x1="{plot_left:.1f}" y1="{plot_top:.1f}" x2="{plot_left:.1f}" y2="{plot_bottom:.1f}" />
      <g class="chart-x-labels">{''.join(x_labels)}</g>
      {empty_markup}
    </svg>
    """
    return Markup(svg)


def _week_history_items(data: DashboardData, language: str) -> list[dict[str, object]]:
    history_map = {summary.local_date: summary for summary in data.daily_history}
    custom_labels = data.history_labels[-7:] if len(data.history_labels) >= 7 else []
    if data.live is not None:
        today = _to_local_timestamp(data.live.timestamp).date()
    else:
        today = datetime.now(_local_timezone()).date()

    dates = [today - timedelta(days=offset) for offset in range(6, -1, -1)]
    items: list[dict[str, object]] = []
    for index, item_date in enumerate(dates):
        summary = history_map.get(item_date)
        produced_wh = summary.production_wh if summary is not None else 0.0
        consumed_wh = summary.consumption_wh if summary is not None else 0.0
        is_today = item_date == today
        label = weekday_name(language, item_date.weekday())
        if len(custom_labels) == len(dates):
            label = custom_labels[index]
        items.append(
            {
                "label": label,
                "name_class": _history_name_class(label),
                "produced": _format_kwh(produced_wh),
                "consumed": _format_kwh(consumed_wh),
                "is_today": is_today,
            }
        )
    return items


def build_dashboard_context(
    data: DashboardData,
    theme: str | None = None,
    lang: str | None = None,
    refresh_seconds: int | None = None,
) -> dict[str, object]:
    resolved_theme = _resolved_theme(theme)
    resolved_language = _resolved_language(lang)
    live = data.live
    if live is None:
        last_update = tr(resolved_language, "no_live_data")
    else:
        local_ts = _to_local_timestamp(live.timestamp)
        last_update = f"{tr(resolved_language, 'last_update')} · {local_ts:%H:%M}"
        if _is_live_stale(data):
            last_update = f"{last_update} · {tr(resolved_language, 'stale')}"

    return {
        "theme_default": resolved_theme,
        "lang_code": resolved_language,
        "page_title": tr(resolved_language, "page_title"),
        "dashboard_aria": tr(resolved_language, "dashboard_aria"),
        "chart_aria": tr(resolved_language, "chart_aria"),
        "flow_aria": tr(resolved_language, "flow_aria"),
        "history_aria": tr(resolved_language, "history_aria"),
        "produced_label": tr(resolved_language, "produced"),
        "consumed_label": tr(resolved_language, "consumed"),
        "history_empty_label": tr(resolved_language, "no_history"),
        "refresh_seconds": config.RENDER_INTERVAL_SECONDS if refresh_seconds is None else refresh_seconds,
        "chart_svg": _build_chart_svg(data, resolved_language),
        "flow_svg": _build_flow_svg(data, resolved_language),
        "week_history": _week_history_items(data, resolved_language),
        "last_update": last_update,
        "has_history": bool(data.daily_history),
        "display_width": config.DISPLAY_WIDTH,
        "display_height": config.DISPLAY_HEIGHT,
    }
