"""Dashboard renderer – Figma-aligned layout.

Side-by-side chart + energy-flow at top, 7-day history strip at bottom.
Four-node energy flow diamond: Solar, Grid, Home, Battery.
Curved bezier flow paths matching the approved Figma target.
"""

from __future__ import annotations

import math
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import config
from src.flow_logic import FLOW_THRESHOLD_W, determine_flow_active
from src.models import DashboardData

# ── Grayscale palette (E-Ink adapted from dark-theme Figma) ──────

BLACK = 0
TEXT_DARK = 30
TEXT_MID = 85
TEXT_LIGHT = 140
TEXT_MUTED = 178

LINE_DARK = 55
LINE_MID = 120
LINE_LIGHT = 195
LINE_FAINT = 220

FILL_NODE = 243
FILL_PANEL = 250
WHITE = 255

# Chart fills: light production (Figma 15% opacity), darker consumption (30%)
CHART_PV_FILL = 230
CHART_PV_LINE = 185
CHART_CON_FILL = 165
CHART_CON_LINE = 45

# ── Layout constants ──────────────────────────────────────────────

MARGIN = 48
GAP = 24

# ── Font loading ──────────────────────────────────────────────────

_FONT_SPECS: dict[str, tuple[bool, int]] = {
    "title": (False, 24),
    "meta": (False, 16),
    "node_value": (True, 60),
    "node_sub": (False, 18),
    "node_label": (False, 18),
    "chart_axis": (False, 17),
    "chart_unit": (False, 16),
    "week_day": (False, 22),
    "week_prod": (True, 40),
    "week_cons": (True, 30),
    "week_label": (False, 14),
    "week_unit": (False, 16),
}


def _load_fonts() -> dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    """Load regular + bold font variants for all needed sizes."""
    # TTC configs: (path, regular_index, bold_index)
    ttc_configs = [
        ("/System/Library/Fonts/Helvetica.ttc", 0, 1),
        ("/System/Library/Fonts/HelveticaNeue.ttc", 0, 10),
    ]
    for path, reg_idx, bold_idx in ttc_configs:
        try:
            fonts = {}
            for name, (is_bold, size) in _FONT_SPECS.items():
                idx = bold_idx if is_bold else reg_idx
                fonts[name] = ImageFont.truetype(path, size, index=idx)
            return fonts
        except (OSError, IOError):
            continue

    # Linux / Raspberry Pi fallback: separate files
    reg_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    bold_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    try:
        fonts = {}
        for name, (is_bold, size) in _FONT_SPECS.items():
            p = bold_path if is_bold else reg_path
            fonts[name] = ImageFont.truetype(p, size)
        return fonts
    except (OSError, IOError):
        pass

    default = ImageFont.load_default()
    return {name: default for name in _FONT_SPECS}


FONTS = _load_fonts()

# ── Utility functions ─────────────────────────────────────────────


def _local_timezone() -> ZoneInfo:
    return ZoneInfo(config.TIMEZONE)


def _to_local_timestamp(ts: datetime) -> datetime:
    tz = _local_timezone()
    if ts.tzinfo is None:
        return ts.replace(tzinfo=tz)
    return ts.astimezone(tz)


def _rounded_rect(draw: ImageDraw.Draw, xy: tuple[int, int, int, int],
                  radius: int, fill: int,
                  outline: int | None = None, width: int = 1) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill,
                           outline=outline, width=width)


def _centered_text(draw: ImageDraw.Draw, center_x: float, top_y: float,
                   text: str, *, font: ImageFont.ImageFont,
                   fill: int) -> float:
    """Draw text centered horizontally. Returns bottom y."""
    bbox = font.getbbox(text)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = center_x - text_w / 2
    draw.text((x, top_y), text, fill=fill, font=font)
    return top_y + text_h


def _text_width(text: str, font: ImageFont.ImageFont) -> int:
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def _format_power_kw(watts: float) -> str:
    """Format power as kW value string (no unit)."""
    kw = abs(watts) / 1000
    if kw < 0.01:
        return "0"
    if kw >= 100:
        return f"{kw:.0f}"
    if kw >= 10:
        return f"{kw:.1f}"
    return f"{kw:.2f}"


def _format_power_kw_signed(watts: float) -> str:
    """Format grid power as signed kW value."""
    if abs(watts) < FLOW_THRESHOLD_W:
        return "0"
    sign = "+" if watts > 0 else "\u2212"
    kw = abs(watts) / 1000
    if kw >= 100:
        return f"{sign}{kw:.0f}"
    if kw >= 10:
        return f"{sign}{kw:.1f}"
    return f"{sign}{kw:.2f}"


def _format_kwh(wh: float) -> str:
    kwh = wh / 1000
    if kwh >= 100:
        return f"{kwh:.0f}"
    if kwh >= 10:
        return f"{kwh:.1f}"
    return f"{kwh:.2f}"


def _weekday_label_en(weekday: int) -> str:
    return ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][weekday]


# ── Bezier curve helper ──────────────────────────────────────────


def _quadratic_bezier(p0: tuple[float, float], p1: tuple[float, float],
                      p2: tuple[float, float],
                      steps: int = 24) -> list[tuple[float, float]]:
    """Generate points along a quadratic Bézier curve.

    p0 = start, p1 = control point, p2 = end.
    """
    pts: list[tuple[float, float]] = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0]
        y = u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]
        pts.append((x, y))
    return pts


# ── Main entry point ──────────────────────────────────────────────


def render_dashboard(data: DashboardData) -> Image.Image:
    width = config.DISPLAY_WIDTH
    height = config.DISPLAY_HEIGHT

    img = Image.new("L", (width, height), WHITE)
    draw = ImageDraw.Draw(img)

    header_bottom = _draw_header(draw, data, width)

    main_top = header_bottom + 8
    weekly_h = 260
    weekly_bottom = height - 40
    weekly_top = weekly_bottom - weekly_h
    main_bottom = weekly_top - GAP

    # Equal-width panels (Figma: 50/50 split)
    avail_w = width - 2 * MARGIN - GAP
    panel_w = avail_w // 2
    chart_left = MARGIN
    chart_right = chart_left + panel_w
    flow_left = chart_right + GAP
    flow_right = width - MARGIN

    _draw_daily_chart(draw, data, chart_left, main_top, chart_right, main_bottom)
    _draw_energy_flow(draw, data, flow_left, main_top, flow_right, main_bottom)
    _draw_week_history(draw, data, MARGIN, weekly_top, width - MARGIN, weekly_bottom)

    return _quantize_16_grayscale(img)


# ── Header ────────────────────────────────────────────────────────


def _draw_header(draw: ImageDraw.Draw, data: DashboardData, width: int) -> int:
    return 20


# ── Flow semantics ────────────────────────────────────────────────


# ── Energy flow ───────────────────────────────────────────────────

# Straight paths are on the same axis; all others curve through center
_STRAIGHT_PATHS = {("solar", "battery"), ("grid", "home")}

_ALL_FLOW_KEYS = [
    ("solar", "home"),
    ("solar", "grid"),
    ("solar", "battery"),
    ("grid", "home"),
    ("grid", "battery"),
    ("battery", "home"),
]


def _draw_flow_node(draw: ImageDraw.Draw, cx: int, cy: int, radius: int,
                    label: str, label_pos: str, value: str,
                    *, sub: str | None = None,
                    dimmed: bool = False) -> None:
    """Draw one flow node: circle with outer label, inner value + sub."""
    fill_color = FILL_NODE if not dimmed else WHITE
    outline_color = LINE_MID if not dimmed else LINE_LIGHT
    outline_w = 2

    draw.ellipse(
        (cx - radius, cy - radius, cx + radius, cy + radius),
        fill=fill_color, outline=outline_color, width=outline_w,
    )

    # Label outside node
    lbl_fill = TEXT_MID if not dimmed else TEXT_MUTED
    label_gap = 12
    if label_pos == "top":
        _centered_text(draw, cx, cy - radius - 24 - label_gap, label,
                       font=FONTS["node_label"], fill=lbl_fill)
    else:
        _centered_text(draw, cx, cy + radius + label_gap, label,
                       font=FONTS["node_label"], fill=lbl_fill)

    # Value inside node (large, bold — just the number)
    val_fill = TEXT_DARK if not dimmed else TEXT_MUTED
    val_y = cy - 24 if sub else cy - 16
    _centered_text(draw, cx, val_y, value,
                   font=FONTS["node_value"], fill=val_fill)

    # Subvalue (unit, SOC, status)
    if sub:
        sub_fill = TEXT_MID if not dimmed else TEXT_MUTED
        _centered_text(draw, cx, cy + 18, sub,
                       font=FONTS["node_sub"], fill=sub_fill)


def _draw_arrowhead(draw: ImageDraw.Draw,
                    points: list[tuple[float, float]],
                    color: int, size: int = 13) -> None:
    """Draw an arrowhead at the end of a path."""
    if len(points) < 2:
        return
    x1, y1 = points[-2]
    x2, y2 = points[-1]
    dx, dy = x2 - x1, y2 - y1
    dist = math.hypot(dx, dy)
    if dist == 0:
        return
    ux, uy = dx / dist, dy / dist
    px, py = -uy, ux
    half = size * 0.38
    tip = (x2, y2)
    left = (x2 - ux * size + px * half, y2 - uy * size + py * half)
    right = (x2 - ux * size - px * half, y2 - uy * size - py * half)
    draw.polygon([tip, left, right], fill=color)


def _draw_flow_path(draw: ImageDraw.Draw,
                    start_edge: tuple[float, float],
                    end_edge: tuple[float, float],
                    center: tuple[float, float],
                    is_straight: bool, active: bool) -> None:
    """Draw a single flow path (straight or bezier) with optional arrow."""
    if is_straight:
        pts = [start_edge, end_edge]
    else:
        pts = _quadratic_bezier(start_edge, center, end_edge)

    if active:
        draw.line(pts, fill=LINE_DARK, width=4)
        _draw_arrowhead(draw, pts, LINE_DARK, size=14)
    else:
        draw.line(pts, fill=LINE_LIGHT, width=1)


def _draw_energy_flow(draw: ImageDraw.Draw, data: DashboardData,
                      panel_left: int, panel_top: int,
                      panel_right: int, panel_bottom: int) -> None:
    _rounded_rect(draw, (panel_left, panel_top, panel_right, panel_bottom),
                  radius=20, fill=FILL_PANEL, outline=LINE_LIGHT)

    cx = (panel_left + panel_right) // 2
    panel_h = panel_bottom - panel_top
    panel_w = panel_right - panel_left

    # Square diamond area centered in panel (Figma: max-w-700 aspect-square)
    meta_reserve = 44
    avail_h = panel_h - meta_reserve
    diamond = min(680, panel_w - 80, avail_h - 20)
    diamond_top = panel_top + (avail_h - diamond) // 2

    # Node positions (Figma: 20/50/80% within diamond)
    solar_pos = (cx, diamond_top + int(diamond * 0.15))
    grid_pos = (cx - int(diamond * 0.33), diamond_top + int(diamond * 0.50))
    home_pos = (cx + int(diamond * 0.33), diamond_top + int(diamond * 0.50))
    battery_pos = (cx, diamond_top + int(diamond * 0.85))

    radius = 92

    positions = {
        "solar": solar_pos,
        "grid": grid_pos,
        "home": home_pos,
        "battery": battery_pos,
    }

    # Inner edge points (where paths connect to node borders)
    edge_gap = 8
    edges = {
        "solar": (float(solar_pos[0]),
                  float(solar_pos[1] + radius + edge_gap)),
        "grid": (float(grid_pos[0] + radius + edge_gap),
                 float(grid_pos[1])),
        "home": (float(home_pos[0] - radius - edge_gap),
                 float(home_pos[1])),
        "battery": (float(battery_pos[0]),
                    float(battery_pos[1] - radius - edge_gap)),
    }

    diamond_center = (float(cx),
                      (solar_pos[1] + battery_pos[1]) / 2.0)

    live = data.live

    if live is None:
        for key, pos in positions.items():
            lbl = {"solar": "Solar", "grid": "Grid",
                   "home": "Home", "battery": "Battery"}[key]
            lpos = "bottom" if key == "battery" else "top"
            _draw_flow_node(draw, *pos, radius, lbl, lpos,
                            "\u2014", dimmed=True)
        for a, b in _ALL_FLOW_KEYS:
            is_straight = (a, b) in _STRAIGHT_PATHS
            _draw_flow_path(draw, edges[a], edges[b],
                            diamond_center, is_straight, active=False)
        _centered_text(draw, cx, panel_bottom - 36,
                       "No live data",
                       font=FONTS["meta"], fill=TEXT_LIGHT)
        return

    p_w, c_w, grid_w = live.p_w, live.c_w, live.grid_w
    bc_w, bd_w, soc = live.bc_w, live.bd_w, live.soc
    has_bat = live.has_battery

    # ── Nodes ──

    pv_val = _format_power_kw(p_w)
    _draw_flow_node(draw, *solar_pos, radius, "Solar", "top",
                    pv_val, sub="kW")

    grid_val = _format_power_kw_signed(grid_w)
    grid_sub = "kW"
    if grid_w > FLOW_THRESHOLD_W:
        grid_sub = "kW \u00b7 Import"
    elif grid_w < -FLOW_THRESHOLD_W:
        grid_sub = "kW \u00b7 Export"
    _draw_flow_node(draw, *grid_pos, radius, "Grid", "top",
                    grid_val, sub=grid_sub)

    home_val = _format_power_kw(c_w)
    _draw_flow_node(draw, *home_pos, radius, "Home", "top",
                    home_val, sub="kW")

    if has_bat:
        bat_w = max(bc_w, bd_w)
        bat_val = _format_power_kw(bat_w)
        bat_sub = "kW"
        if soc is not None:
            if bc_w > FLOW_THRESHOLD_W:
                bat_sub = f"kW \u00b7 {int(soc)}%"
            elif bd_w > FLOW_THRESHOLD_W:
                bat_sub = f"kW \u00b7 {int(soc)}%"
            else:
                bat_sub = f"kW \u00b7 {int(soc)}%"
        _draw_flow_node(draw, *battery_pos, radius, "Battery",
                        "bottom", bat_val, sub=bat_sub)
    else:
        _draw_flow_node(draw, *battery_pos, radius, "Battery",
                        "bottom", "\u2014", dimmed=True)

    # ── Paths ──

    active_map = determine_flow_active(p_w, c_w, grid_w, bc_w, bd_w,
                                       has_bat)

    # Draw inactive first, then active on top
    for a, b in _ALL_FLOW_KEYS:
        if not active_map.get((a, b), False):
            is_straight = (a, b) in _STRAIGHT_PATHS
            _draw_flow_path(draw, edges[a], edges[b],
                            diamond_center, is_straight, active=False)
    for a, b in _ALL_FLOW_KEYS:
        if active_map.get((a, b), False):
            is_straight = (a, b) in _STRAIGHT_PATHS
            _draw_flow_path(draw, edges[a], edges[b],
                            diamond_center, is_straight, active=True)

    # ── Meta: last update ──

    local_ts = _to_local_timestamp(live.timestamp)
    update_str = f"Last update \u00b7 {local_ts.strftime('%H:%M')}"
    tw = _text_width(update_str, FONTS["meta"])
    draw.text((panel_right - tw - 20, panel_top + 16),
              update_str, fill=TEXT_LIGHT, font=FONTS["meta"])


# ── Daily chart ───────────────────────────────────────────────────


def _draw_daily_chart(draw: ImageDraw.Draw, data: DashboardData,
                      panel_left: int, panel_top: int,
                      panel_right: int, panel_bottom: int) -> int:
    _rounded_rect(draw, (panel_left, panel_top, panel_right, panel_bottom),
                  radius=20, fill=FILL_PANEL, outline=LINE_LIGHT)

    chart_left = panel_left + 78
    chart_right = panel_right - 24
    chart_top = panel_top + 32
    chart_bottom = panel_bottom - 48
    chart_width = chart_right - chart_left
    chart_height = chart_bottom - chart_top

    # Y-axis unit label
    draw.text((panel_left + 18, panel_top + 10), "kW",
              fill=TEXT_MID, font=FONTS["chart_unit"])

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

    # Horizontal grid lines only (Figma style: no vertical grid)
    y_step_kw = max(2, int(math.ceil((y_max / 1000) / 5)))
    if y_step_kw % 2 != 0:
        y_step_kw += 1
    for kw in range(0, int(y_max / 1000) + 1, y_step_kw):
        y = power_to_y(kw * 1000)
        draw.line([(chart_left, y), (chart_right, y)],
                  fill=LINE_FAINT, width=1)
        lbl = str(kw)
        lw = _text_width(lbl, FONTS["chart_axis"])
        draw.text((chart_left - lw - 12, y - 8), lbl,
                  fill=TEXT_MID, font=FONTS["chart_axis"])

    # X-axis tick labels (every 2 hours)
    for hour in range(0, 25, 2):
        x = time_to_x(hour)
        label = "24:00" if hour == 24 else f"{hour:02d}:00"
        lw = _text_width(label, FONTS["chart_axis"])
        draw.text((x - lw // 2, chart_bottom + 10), label,
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

        # Production area (lighter, behind — Figma: 15% opacity)
        if len(pv_pts) >= 2:
            fill_pts = [(pv_pts[0][0], chart_bottom), *pv_pts,
                        (pv_pts[-1][0], chart_bottom)]
            draw.polygon(fill_pts, fill=CHART_PV_FILL)
            draw.line(pv_pts, fill=CHART_PV_LINE, width=2)

        # Consumption area (darker, in front — Figma: 30% opacity)
        if len(con_pts) >= 2:
            fill_pts = [(con_pts[0][0], chart_bottom), *con_pts,
                        (con_pts[-1][0], chart_bottom)]
            draw.polygon(fill_pts, fill=CHART_CON_FILL)
            draw.line(con_pts, fill=CHART_CON_LINE, width=2)
    else:
        _centered_text(draw, (chart_left + chart_right) / 2,
                       chart_top + chart_height / 2 - 10,
                       "Keine Daten",
                       font=FONTS["week_day"], fill=TEXT_MID)

    # Axis lines (subtle)
    draw.line([(chart_left, chart_bottom), (chart_right, chart_bottom)],
              fill=LINE_MID, width=1)
    draw.line([(chart_left, chart_top), (chart_left, chart_bottom)],
              fill=LINE_MID, width=1)
    return panel_bottom


# ── 7-day history ─────────────────────────────────────────────────


def _draw_week_history(draw: ImageDraw.Draw, data: DashboardData,
                       panel_left: int, panel_top: int,
                       panel_right: int, panel_bottom: int) -> None:
    _rounded_rect(draw, (panel_left, panel_top, panel_right, panel_bottom),
                  radius=20, fill=FILL_PANEL, outline=LINE_LIGHT)

    history = data.daily_history[-7:]
    if not history:
        _centered_text(draw, (panel_left + panel_right) / 2,
                       (panel_top + panel_bottom) / 2 - 10,
                       "No 7-day history yet",
                       font=FONTS["week_day"], fill=TEXT_MID)
        return

    if data.live is not None:
        today_local = _to_local_timestamp(data.live.timestamp).date()
    else:
        today_local = datetime.now(_local_timezone()).date()

    content_left = panel_left + 20
    content_right = panel_right - 20
    col_w = (content_right - content_left) / len(history)

    for i, summary in enumerate(history):
        col_left = int(content_left + i * col_w)

        # Column separator
        if i > 0:
            draw.line([(col_left, panel_top + 16),
                       (col_left, panel_bottom - 16)],
                      fill=LINE_FAINT, width=1)

        tx = col_left + 18

        # Day label
        if summary.local_date == today_local:
            day_label = "Today"
        else:
            day_label = _weekday_label_en(summary.local_date.weekday())
        draw.text((tx, panel_top + 18), day_label,
                  fill=TEXT_MID, font=FONTS["week_day"])

        # Production value (large, bold)
        prod_kwh = _format_kwh(summary.production_wh)
        draw.text((tx, panel_top + 48), prod_kwh,
                  fill=TEXT_DARK, font=FONTS["week_prod"])
        prod_w = _text_width(prod_kwh, FONTS["week_prod"])
        draw.text((tx + prod_w + 5, panel_top + 60), "kWh",
                  fill=TEXT_LIGHT, font=FONTS["week_unit"])
        draw.text((tx, panel_top + 96), "produced",
                  fill=TEXT_MUTED, font=FONTS["week_label"])

        # Consumption value (smaller, subdued)
        cons_kwh = _format_kwh(summary.consumption_wh)
        draw.text((tx, panel_top + 132), cons_kwh,
                  fill=TEXT_MID, font=FONTS["week_cons"])
        cons_w = _text_width(cons_kwh, FONTS["week_cons"])
        draw.text((tx + cons_w + 5, panel_top + 138), "kWh",
                  fill=TEXT_LIGHT, font=FONTS["week_unit"])
        draw.text((tx, panel_top + 168), "consumed",
                  fill=TEXT_MUTED, font=FONTS["week_label"])


# ── Post-processing ───────────────────────────────────────────────


def _quantize_16_grayscale(img: Image.Image) -> Image.Image:
    arr = np.array(img, dtype=np.float32)
    arr = np.round(arr / 17) * 17
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr)
