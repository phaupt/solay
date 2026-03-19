"""Dashboard renderer – Figma-aligned layout.

Side-by-side chart + energy-flow at top, 7-day history strip at bottom.
Four-node energy flow diamond: Solar, Grid, Home, Battery.
"""

from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import config
from src.models import DashboardData

# ── Grayscale palette ──────────────────────────────────────────────

BLACK = 0
TEXT_DARK = 34
TEXT_MID = 102
TEXT_LIGHT = 153
LINE_DARK = 68
LINE_MID = 136
LINE_LIGHT = 187
FILL_NODE = 238
FILL_PANEL = 247
WHITE = 255

CHART_PV_FILL = 214
CHART_PV_LINE = 170
CHART_CON_FILL = 136
CHART_CON_LINE = 51

FLOW_THRESHOLD_W = 50

# ── Layout constants ───────────────────────────────────────────────

MARGIN = 48
GAP = 24


# ── Font loading ───────────────────────────────────────────────────

def _load_fonts() -> dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    font_paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    sizes = {
        "title": 28,
        "meta": 18,
        "node_label": 20,
        "node_value": 46,
        "node_unit": 20,
        "node_sub": 17,
        "chart_axis": 20,
        "week_day": 24,
        "week_value_lg": 36,
        "week_value_sm": 28,
        "week_label": 16,
    }
    for path in font_paths:
        try:
            return {name: ImageFont.truetype(path, size) for name, size in sizes.items()}
        except (OSError, IOError):
            continue
    default = ImageFont.load_default()
    return {name: default for name in sizes}


FONTS = _load_fonts()


# ── Utility functions ──────────────────────────────────────────────

def _local_timezone() -> ZoneInfo:
    return ZoneInfo(config.TIMEZONE)


def _to_local_timestamp(ts: datetime) -> datetime:
    tz = _local_timezone()
    if ts.tzinfo is None:
        return ts.replace(tzinfo=tz)
    return ts.astimezone(tz)


def _rounded_rect(draw: ImageDraw.Draw, xy: tuple[int, int, int, int], radius: int,
                  fill: int, outline: int | None = None, width: int = 1) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def _centered_text(draw: ImageDraw.Draw, center_x: float, top_y: float, text: str,
                   *, font: ImageFont.ImageFont, fill: int) -> tuple[float, float]:
    bbox = font.getbbox(text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = center_x - text_w / 2
    draw.text((x, top_y), text, fill=fill, font=font)
    return x, top_y + text_h


def _format_power(watts: float) -> tuple[str, str]:
    watts = abs(watts)
    if watts >= 10000:
        return f"{watts / 1000:.0f}", "kW"
    if watts >= 1000:
        return f"{watts / 1000:.1f}", "kW"
    return f"{round(watts)}", "W"


def _format_power_signed(watts: float) -> tuple[str, str]:
    """Format power with explicit sign for grid display."""
    if abs(watts) < FLOW_THRESHOLD_W:
        return "0", "W"
    sign = "+" if watts > 0 else "-"
    abs_w = abs(watts)
    if abs_w >= 10000:
        return f"{sign}{abs_w / 1000:.0f}", "kW"
    if abs_w >= 1000:
        return f"{sign}{abs_w / 1000:.1f}", "kW"
    return f"{sign}{round(abs_w)}", "W"


def _format_kwh(wh: float) -> str:
    kwh = wh / 1000
    if kwh >= 100:
        return f"{kwh:.0f}"
    if kwh >= 10:
        return f"{kwh:.1f}"
    return f"{kwh:.2f}"


# ── Main entry point ──────────────────────────────────────────────

def render_dashboard(data: DashboardData) -> Image.Image:
    width = config.DISPLAY_WIDTH
    height = config.DISPLAY_HEIGHT

    img = Image.new("L", (width, height), WHITE)
    draw = ImageDraw.Draw(img)

    header_bottom = _draw_header(draw, data, width)

    main_top = header_bottom + 12
    weekly_h = 260
    weekly_bottom = height - 36
    weekly_top = weekly_bottom - weekly_h
    main_bottom = weekly_top - GAP

    chart_w = 1000
    chart_left = MARGIN
    chart_right = chart_left + chart_w
    flow_left = chart_right + GAP
    flow_right = width - MARGIN

    _draw_daily_chart(draw, data, chart_left, main_top, chart_right, main_bottom)
    _draw_energy_flow(draw, data, flow_left, main_top, flow_right, main_bottom)
    _draw_week_history(draw, data, MARGIN, weekly_top, width - MARGIN, weekly_bottom)

    return _quantize_16_grayscale(img)


# ── Header ─────────────────────────────────────────────────────────

def _draw_header(draw: ImageDraw.Draw, data: DashboardData, width: int) -> int:
    draw.text((MARGIN, 28), config.DASHBOARD_TITLE, fill=TEXT_DARK, font=FONTS["title"])
    return 64


# ── Energy flow ────────────────────────────────────────────────────

def _draw_flow_node(draw: ImageDraw.Draw, cx: int, cy: int, radius: int,
                    label: str, label_pos: str, value: str, unit: str,
                    *, sub: str | None = None, dimmed: bool = False) -> None:
    """Draw one flow node: circle with outer label and inner value."""
    fill_color = FILL_NODE if not dimmed else 250
    outline_color = LINE_MID if not dimmed else LINE_LIGHT
    outline_w = 3 if not dimmed else 2

    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                 fill=fill_color, outline=outline_color, width=outline_w)

    lbl_fill = TEXT_MID if not dimmed else TEXT_LIGHT
    if label_pos == "top":
        _centered_text(draw, cx, cy - radius - 30, label,
                       font=FONTS["node_label"], fill=lbl_fill)
    else:
        _centered_text(draw, cx, cy + radius + 10, label,
                       font=FONTS["node_label"], fill=lbl_fill)

    val_fill = TEXT_DARK if not dimmed else TEXT_LIGHT
    unit_fill = TEXT_MID if not dimmed else TEXT_LIGHT
    val_y = cy - 24 if sub else cy - 16

    if unit:
        val_bbox = FONTS["node_value"].getbbox(value)
        unit_bbox = FONTS["node_unit"].getbbox(unit)
        val_w = val_bbox[2] - val_bbox[0]
        unit_w = unit_bbox[2] - unit_bbox[0]
        total_w = val_w + 6 + unit_w
        start_x = cx - total_w / 2
        draw.text((start_x, val_y), value, fill=val_fill, font=FONTS["node_value"])
        draw.text((start_x + val_w + 6, val_y + 20), unit,
                  fill=unit_fill, font=FONTS["node_unit"])
    else:
        _centered_text(draw, cx, val_y, value,
                       font=FONTS["node_value"], fill=val_fill)

    if sub:
        sub_fill = TEXT_MID if not dimmed else TEXT_LIGHT
        _centered_text(draw, cx, cy + 22, sub,
                       font=FONTS["node_sub"], fill=sub_fill)


def _draw_flow_path(draw: ImageDraw.Draw, start: tuple[int, int],
                    end: tuple[int, int], radius: int, *, active: bool) -> None:
    """Draw a flow path (line + optional arrowhead)."""
    x1, y1 = start
    x2, y2 = end
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    if dist == 0:
        return

    ux, uy = dx / dist, dy / dist
    edge_gap = radius + 6
    sx, sy = x1 + ux * edge_gap, y1 + uy * edge_gap
    ex, ey = x2 - ux * edge_gap, y2 - uy * edge_gap

    if active:
        draw.line([(sx, sy), (ex, ey)], fill=LINE_DARK, width=5)
        a_len, a_half = 16, 8
        px, py = -uy, ux
        tip = (ex, ey)
        left = (ex - ux * a_len + px * a_half, ey - uy * a_len + py * a_half)
        right = (ex - ux * a_len - px * a_half, ey - uy * a_len - py * a_half)
        draw.polygon([tip, left, right], fill=LINE_DARK)
    else:
        draw.line([(sx, sy), (ex, ey)], fill=LINE_LIGHT, width=2)


def _draw_energy_flow(draw: ImageDraw.Draw, data: DashboardData,
                      panel_left: int, panel_top: int,
                      panel_right: int, panel_bottom: int) -> None:
    _rounded_rect(draw, (panel_left, panel_top, panel_right, panel_bottom),
                  radius=20, fill=FILL_PANEL, outline=LINE_LIGHT)

    cx = (panel_left + panel_right) // 2
    panel_h = panel_bottom - panel_top
    panel_w = panel_right - panel_left

    # Diamond layout, leaving bottom space for "Last update" meta text
    diamond = min(700, panel_w - 60, panel_h - 100)
    meta_reserve = 50
    avail_h = panel_h - meta_reserve
    diamond_top = panel_top + (avail_h - diamond) // 2

    solar_pos = (cx, diamond_top + int(diamond * 0.12))
    grid_pos = (cx - int(diamond * 0.32), diamond_top + int(diamond * 0.50))
    home_pos = (cx + int(diamond * 0.32), diamond_top + int(diamond * 0.50))
    battery_pos = (cx, diamond_top + int(diamond * 0.88))

    radius = 82

    all_path_keys = [
        ("solar", "home"),
        ("solar", "grid"),
        ("solar", "battery"),
        ("grid", "home"),
        ("battery", "home"),
    ]
    positions = {
        "solar": solar_pos,
        "grid": grid_pos,
        "home": home_pos,
        "battery": battery_pos,
    }

    live = data.live

    if live is None:
        for key, pos in positions.items():
            lbl = {"solar": "SOLAR", "grid": "NETZ", "home": "HAUS", "battery": "BATTERIE"}[key]
            lpos = "bottom" if key == "battery" else "top"
            _draw_flow_node(draw, *pos, radius, lbl, lpos, "\u2014", "", dimmed=True)
        for a, b in all_path_keys:
            _draw_flow_path(draw, positions[a], positions[b], radius, active=False)
        _centered_text(draw, cx, panel_bottom - 36, "Keine Live-Daten",
                       font=FONTS["meta"], fill=TEXT_LIGHT)
        return

    p_w, c_w, grid_w = live.p_w, live.c_w, live.grid_w
    bc_w, bd_w, soc = live.bc_w, live.bd_w, live.soc
    has_bat = live.has_battery

    # ── Nodes ──

    pv_v, pv_u = _format_power(p_w)
    _draw_flow_node(draw, *solar_pos, radius, "SOLAR", "top", pv_v, pv_u)

    grid_v, grid_u = _format_power_signed(grid_w)
    grid_sub = ("Import" if grid_w > FLOW_THRESHOLD_W
                else ("Export" if grid_w < -FLOW_THRESHOLD_W else None))
    _draw_flow_node(draw, *grid_pos, radius, "NETZ", "top", grid_v, grid_u, sub=grid_sub)

    home_v, home_u = _format_power(c_w)
    _draw_flow_node(draw, *home_pos, radius, "HAUS", "top", home_v, home_u)

    if has_bat:
        bat_w = max(bc_w, bd_w)
        bat_v, bat_u = _format_power(bat_w)
        if soc is not None:
            bat_sub = f"{int(soc)}%"
            if bc_w > FLOW_THRESHOLD_W:
                bat_sub += " Laden"
            elif bd_w > FLOW_THRESHOLD_W:
                bat_sub += " Entladen"
        else:
            bat_sub = None
        _draw_flow_node(draw, *battery_pos, radius, "BATTERIE", "bottom",
                        bat_v, bat_u, sub=bat_sub)
    else:
        _draw_flow_node(draw, *battery_pos, radius, "BATTERIE", "bottom",
                        "\u2014", "", dimmed=True)

    # ── Paths ──

    active_map = {
        ("solar", "home"): p_w > FLOW_THRESHOLD_W and c_w > FLOW_THRESHOLD_W,
        ("solar", "grid"): grid_w < -FLOW_THRESHOLD_W,
        ("solar", "battery"): has_bat and bc_w > FLOW_THRESHOLD_W,
        ("grid", "home"): grid_w > FLOW_THRESHOLD_W,
        ("battery", "home"): has_bat and bd_w > FLOW_THRESHOLD_W,
    }

    # Draw inactive first, then active on top
    for a, b in all_path_keys:
        if not active_map[(a, b)]:
            _draw_flow_path(draw, positions[a], positions[b], radius, active=False)
    for a, b in all_path_keys:
        if active_map[(a, b)]:
            _draw_flow_path(draw, positions[a], positions[b], radius, active=True)

    # ── Meta: last update ──

    local_ts = _to_local_timestamp(live.timestamp)
    update_str = f"Last update \u00b7 {local_ts.strftime('%H:%M')}"
    bbox = FONTS["meta"].getbbox(update_str)
    text_w = bbox[2] - bbox[0]
    draw.text((panel_right - text_w - 24, panel_bottom - 36),
              update_str, fill=TEXT_LIGHT, font=FONTS["meta"])


# ── Chart ──────────────────────────────────────────────────────────

def _draw_daily_chart(draw: ImageDraw.Draw, data: DashboardData,
                      panel_left: int, panel_top: int,
                      panel_right: int, panel_bottom: int) -> int:
    _rounded_rect(draw, (panel_left, panel_top, panel_right, panel_bottom),
                  radius=20, fill=FILL_PANEL, outline=LINE_LIGHT)

    chart_left = panel_left + 90
    chart_right = panel_right - 24
    chart_top = panel_top + 44
    chart_bottom = panel_bottom - 52
    chart_width = chart_right - chart_left
    chart_height = chart_bottom - chart_top

    draw.text((panel_left + 20, panel_top + 4), "kW",
              fill=TEXT_MID, font=FONTS["chart_axis"])

    buckets = data.chart_buckets
    max_power = max(
        max((b.p_w_avg for b in buckets), default=0),
        max((b.c_w_avg for b in buckets), default=0),
    )
    y_max = max(1000, math.ceil(max_power / 2000) * 2000)

    def time_to_x(hour: float) -> int:
        return chart_left + int(chart_width * hour / 24.0)

    def power_to_y(watts: float) -> int:
        clamped = max(0.0, min(watts, y_max))
        return chart_bottom - int(chart_height * clamped / y_max)

    # Y grid lines + labels
    y_step_kw = max(2, int(math.ceil((y_max / 1000) / 6)))
    if y_step_kw % 2 != 0:
        y_step_kw += 1
    for kw in range(0, int(y_max / 1000) + 1, y_step_kw):
        y = power_to_y(kw * 1000)
        draw.line([(chart_left, y), (chart_right, y)], fill=LINE_LIGHT, width=1)
        draw.text((panel_left + 20, y - 10), str(kw),
                  fill=TEXT_MID, font=FONTS["chart_axis"])

    # X grid lines + labels
    for hour in range(0, 25, 2):
        x = time_to_x(hour)
        draw.line([(x, chart_top), (x, chart_bottom)], fill=LINE_LIGHT, width=1)
        label = "24" if hour == 24 else f"{hour:02d}"
        draw.text((x - 10, chart_bottom + 8), label,
                  fill=TEXT_MID, font=FONTS["chart_axis"])

    # Data areas
    if buckets:
        tz = _local_timezone()
        pv_pts: list[tuple[int, int]] = []
        con_pts: list[tuple[int, int]] = []
        for bucket in buckets:
            lt = bucket.timestamp.astimezone(tz)
            h = lt.hour + lt.minute / 60.0
            x = time_to_x(h)
            pv_pts.append((x, power_to_y(bucket.p_w_avg)))
            con_pts.append((x, power_to_y(bucket.c_w_avg)))

        if len(pv_pts) >= 2:
            fill_pts = [(pv_pts[0][0], chart_bottom), *pv_pts,
                        (pv_pts[-1][0], chart_bottom)]
            draw.polygon(fill_pts, fill=CHART_PV_FILL)
            draw.line(pv_pts, fill=CHART_PV_LINE, width=2)

        if len(con_pts) >= 2:
            fill_pts = [(con_pts[0][0], chart_bottom), *con_pts,
                        (con_pts[-1][0], chart_bottom)]
            draw.polygon(fill_pts, fill=CHART_CON_FILL)
            draw.line(con_pts, fill=CHART_CON_LINE, width=2)
    else:
        _centered_text(draw, (chart_left + chart_right) / 2,
                       chart_top + chart_height / 2 - 10,
                       "Keine Daten", font=FONTS["week_day"], fill=TEXT_MID)

    # Axes
    draw.line([(chart_left, chart_bottom), (chart_right, chart_bottom)],
              fill=LINE_DARK, width=1)
    draw.line([(chart_left, chart_top), (chart_left, chart_bottom)],
              fill=LINE_DARK, width=1)
    return panel_bottom


# ── 7-day history ──────────────────────────────────────────────────

def _draw_week_history(draw: ImageDraw.Draw, data: DashboardData,
                       panel_left: int, panel_top: int,
                       panel_right: int, panel_bottom: int) -> None:
    _rounded_rect(draw, (panel_left, panel_top, panel_right, panel_bottom),
                  radius=20, fill=FILL_PANEL, outline=LINE_LIGHT)

    history = data.daily_history[-7:]
    if not history:
        _centered_text(draw, (panel_left + panel_right) / 2,
                       (panel_top + panel_bottom) / 2 - 10,
                       "Noch keine 7-Tage-Historie",
                       font=FONTS["week_day"], fill=TEXT_MID)
        return

    if data.live is not None:
        today_local = _to_local_timestamp(data.live.timestamp).date()
    else:
        today_local = datetime.now(_local_timezone()).date()

    content_left = panel_left + 16
    content_right = panel_right - 16
    col_w = (content_right - content_left) / len(history)

    weekday_short = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

    for i, summary in enumerate(history):
        x = int(content_left + i * col_w)

        if i > 0:
            draw.line([(x, panel_top + 14), (x, panel_bottom - 14)],
                      fill=LINE_LIGHT, width=1)

        tx = x + 18

        # Day label
        if summary.local_date == today_local:
            day_label = "Heute"
        else:
            day_label = weekday_short[summary.local_date.weekday()]
        draw.text((tx, panel_top + 22), day_label,
                  fill=TEXT_MID, font=FONTS["week_day"])

        # Production
        prod = f"{_format_kwh(summary.production_wh)} kWh"
        draw.text((tx, panel_top + 62), prod,
                  fill=TEXT_DARK, font=FONTS["week_value_lg"])
        draw.text((tx, panel_top + 104), "Produktion",
                  fill=TEXT_LIGHT, font=FONTS["week_label"])

        # Consumption
        cons = f"{_format_kwh(summary.consumption_wh)} kWh"
        draw.text((tx, panel_top + 138), cons,
                  fill=TEXT_MID, font=FONTS["week_value_sm"])
        draw.text((tx, panel_top + 172), "Verbrauch",
                  fill=TEXT_LIGHT, font=FONTS["week_label"])


# ── Post-processing ───────────────────────────────────────────────

def _quantize_16_grayscale(img: Image.Image) -> Image.Image:
    arr = np.array(img, dtype=np.float32)
    arr = np.round(arr / 17) * 17
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="L")
