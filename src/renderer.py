"""Dashboard-Renderer: Erzeugt ein 1872x1404 Graustufen-Bild mit Pillow.

Rendert basierend auf dem typisierten DashboardData-Modell:
- Energiefluss-Karten (PV, Haus, Netz, optional Batterie)
- Tagesgrafik "Heute" mit Zeitachse und Leistungskurven
- Tageswerte (korrekt aggregiert)
- Geräte-Status
- PV-Performance (7/30 Tage)

Korrekte Netzberechnung: grid = cW + bcW - pW - bdW
Eigenverbrauchsquote vs. Autarkiegrad klar getrennt.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont

import config
from src.models import ChartBucket, DailySummary, DashboardData, SensorPoint

_LOCAL_TZ = ZoneInfo(config.TIMEZONE)

# --- Graustufen-Palette (quantisiert auf 16 Stufen: 0,17,34,...,255) ---
BLACK = 0
DARK_GRAY = 51
MID_GRAY = 119
LIGHT_GRAY = 187
CARD_BG = 238
WHITE = 255

# Chart-Farben
CHART_PV = 68  # Dunkler für PV-Fläche
CHART_PV_FILL = 204  # Heller für PV-Füllung
CHART_CONSUMPTION = 34  # Fast schwarz für Verbrauch-Linie
CHART_GRID_LINE = 170  # Grau für Achsen


def _load_fonts() -> dict[str, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    """Lade Schriften mit Fallback-Kette."""
    font_paths = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    sizes = {
        "title": 42, "date": 34, "card_label": 28, "card_value": 68,
        "card_unit": 28, "flow_label": 24, "stats_label": 26,
        "stats_value": 42, "device_text": 26, "small": 20,
        "chart_label": 20, "chart_value": 18,
    }
    fonts = {}
    for path in font_paths:
        try:
            for name, size in sizes.items():
                fonts[name] = ImageFont.truetype(path, size)
            return fonts
        except (OSError, IOError):
            continue

    default = ImageFont.load_default()
    return {name: default for name in sizes}


FONTS = _load_fonts()


def _format_power(watts: float) -> tuple[str, str]:
    """Formatiere Watt-Wert: ab 1000W als kW."""
    if abs(watts) >= 10000:
        return f"{watts / 1000:.0f}", "kW"
    if abs(watts) >= 1000:
        return f"{watts / 1000:.1f}", "kW"
    return f"{round(watts)}", "W"


def _format_kwh(wh: float) -> str:
    """Formatiere Wh als kWh."""
    kwh = wh / 1000
    if kwh >= 100:
        return f"{kwh:.0f}"
    if kwh >= 10:
        return f"{kwh:.1f}"
    return f"{kwh:.2f}"


def _rounded_rect(draw: ImageDraw.Draw, xy: tuple, radius: int,
                  fill: int, outline: int | None = None):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline)


def render_dashboard(data: DashboardData) -> Image.Image:
    """Rendere das komplette Dashboard als PIL Image.

    Returns:
        PIL Image im Modus "L" (Graustufen), 1872x1404 px.
    """
    W = config.DISPLAY_WIDTH
    H = config.DISPLAY_HEIGHT
    img = Image.new("L", (W, H), WHITE)
    draw = ImageDraw.Draw(img)

    # === HEADER ===
    _draw_header(draw, data, W)

    # === ENERGIEFLUSS ===
    flow_bottom = _draw_energy_flow(draw, data, W)

    # === TAGESGRAFIK ===
    chart_top = flow_bottom + 15
    chart_bottom = chart_top + 340
    _draw_daily_chart(draw, data, W, chart_top, chart_bottom)

    # === TRENNLINIE ===
    sep1 = chart_bottom + 15
    draw.line([(60, sep1), (W - 60, sep1)], fill=LIGHT_GRAY, width=1)

    # === TAGESWERTE ===
    _draw_daily_stats(draw, data, W, sep1 + 10)

    # === TRENNLINIE ===
    sep2 = sep1 + 135
    draw.line([(60, sep2), (W - 60, sep2)], fill=LIGHT_GRAY, width=1)

    # === GERÄTE + PV-PERFORMANCE ===
    _draw_bottom_row(draw, data, W, H, sep2 + 10)

    # Quantisierung auf 16 Graustufen
    img = _quantize_16_grayscale(img)

    return img


def _draw_header(draw: ImageDraw.Draw, data: DashboardData, W: int):
    draw.text((60, 35), "\u2600  SOLAR DASHBOARD", fill=BLACK, font=FONTS["title"])

    if data.live:
        local_ts = data.live.timestamp.astimezone(_LOCAL_TZ)
        date_str = local_ts.strftime("%d.%m.%Y  %H:%M")
    else:
        date_str = datetime.now(_LOCAL_TZ).strftime("%d.%m.%Y  %H:%M")

    bbox = FONTS["date"].getbbox(date_str)
    draw.text((W - 60 - (bbox[2] - bbox[0]), 40), date_str,
              fill=DARK_GRAY, font=FONTS["date"])
    draw.line([(60, 90), (W - 60, 90)], fill=LIGHT_GRAY, width=1)


def _draw_energy_flow(draw: ImageDraw.Draw, data: DashboardData, W: int) -> int:
    """Energiefluss-Karten. Gibt die Y-Position unterhalb zurück."""
    live = data.live
    if live is None:
        draw.text((60, 120), "Keine Live-Daten", fill=MID_GRAY, font=FONTS["card_label"])
        return 300

    has_bat = live.has_battery
    card_w = 340 if has_bat else 400
    card_h = 170
    y_top = 110

    # Layout: 3 oder 4 Karten in einer Reihe
    if has_bat:
        # PV | Haus | Batterie | Netz
        gap = (W - 120 - 4 * card_w) // 3
        positions = [(60, y_top)]
        for i in range(1, 4):
            positions.append((60 + i * (card_w + gap), y_top))

        _draw_power_card(draw, *positions[0], card_w, card_h,
                         "PV", live.p_w, icon="\u2600")
        _draw_power_card(draw, *positions[1], card_w, card_h,
                         "HAUS", live.c_w, icon="\u2302")
        _draw_battery_card(draw, *positions[2], card_w, card_h,
                           live.bc_w, live.bd_w, live.soc)

        grid_w = live.grid_w
        grid_label = "EINSPEISUNG" if grid_w <= 0 else "BEZUG"
        _draw_power_card(draw, *positions[3], card_w, card_h,
                         grid_label, abs(grid_w), icon="\u26A1")
    else:
        # PV | Haus | Netz
        gap = (W - 120 - 3 * card_w) // 2
        positions = [(60, y_top)]
        for i in range(1, 3):
            positions.append((60 + i * (card_w + gap), y_top))

        _draw_power_card(draw, *positions[0], card_w, card_h,
                         "PV", live.p_w, icon="\u2600")
        _draw_power_card(draw, *positions[1], card_w, card_h,
                         "HAUS", live.c_w, icon="\u2302")

        grid_w = live.grid_w
        grid_label = "EINSPEISUNG" if grid_w <= 0 else "BEZUG"
        _draw_power_card(draw, *positions[2], card_w, card_h,
                         grid_label, abs(grid_w), icon="\u26A1")

    # Fluss-Pfeile zwischen den Karten
    arrow_y = y_top + card_h // 2
    for i in range(len(positions) - 1):
        x1 = positions[i][0] + card_w
        x2 = positions[i + 1][0]
        mid_x = (x1 + x2) // 2
        draw.line([(x1 + 4, arrow_y), (x2 - 4, arrow_y)], fill=MID_GRAY, width=2)
        # Pfeilspitze
        draw.polygon(
            [(x2 - 4, arrow_y), (x2 - 14, arrow_y - 6), (x2 - 14, arrow_y + 6)],
            fill=MID_GRAY,
        )

    return y_top + card_h


def _draw_power_card(draw: ImageDraw.Draw, x: int, y: int, w: int, h: int,
                     label: str, watts: float, icon: str = ""):
    _rounded_rect(draw, (x, y, x + w, y + h), radius=16, fill=CARD_BG)
    # Label
    label_text = f"{icon}  {label}" if icon else label
    draw.text((x + 16, y + 14), label_text, fill=DARK_GRAY, font=FONTS["card_label"])
    # Wert
    val, unit = _format_power(watts)
    draw.text((x + 16, y + 55), val, fill=BLACK, font=FONTS["card_value"])
    val_bbox = FONTS["card_value"].getbbox(val)
    unit_x = x + 16 + (val_bbox[2] - val_bbox[0]) + 8
    draw.text((unit_x, y + 80), unit, fill=MID_GRAY, font=FONTS["card_unit"])


def _draw_battery_card(draw: ImageDraw.Draw, x: int, y: int, w: int, h: int,
                       charge_w: float, discharge_w: float, soc: float | None):
    _rounded_rect(draw, (x, y, x + w, y + h), radius=16, fill=CARD_BG)

    if discharge_w > 0:
        label = "BATTERIE \u25BC"  # Entladen
        power = discharge_w
    elif charge_w > 0:
        label = "BATTERIE \u25B2"  # Laden
        power = charge_w
    else:
        label = "BATTERIE"
        power = 0

    draw.text((x + 16, y + 14), label, fill=DARK_GRAY, font=FONTS["card_label"])

    # SOC-Balken
    if soc is not None:
        bar_x = x + 16
        bar_y = y + 52
        bar_w = w - 32
        bar_h = 20
        _rounded_rect(draw, (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
                      radius=6, fill=WHITE, outline=MID_GRAY)
        fill_w = max(0, min(bar_w - 2, int((bar_w - 2) * soc / 100)))
        if fill_w > 2:
            _rounded_rect(draw, (bar_x + 1, bar_y + 1, bar_x + 1 + fill_w, bar_y + bar_h - 1),
                          radius=5, fill=DARK_GRAY)
        soc_text = f"{soc:.0f}%"
        draw.text((bar_x + bar_w + 8 - 50, bar_y + 1), soc_text,
                  fill=BLACK, font=FONTS["chart_label"])

    # Leistung
    if power > 0:
        val, unit = _format_power(power)
        draw.text((x + 16, y + 85), val, fill=BLACK, font=FONTS["stats_value"])
        val_bbox = FONTS["stats_value"].getbbox(val)
        draw.text((x + 16 + (val_bbox[2] - val_bbox[0]) + 6, y + 95),
                  unit, fill=MID_GRAY, font=FONTS["chart_label"])
    else:
        draw.text((x + 16, y + 85), "Standby", fill=MID_GRAY, font=FONTS["stats_value"])


def _draw_daily_chart(draw: ImageDraw.Draw, data: DashboardData, W: int,
                      y_top: int, y_bottom: int):
    """Tagesgrafik: PV-Produktion und Verbrauch über den Tag."""
    chart_left = 120
    chart_right = W - 60
    chart_top = y_top + 35
    chart_bottom = y_bottom - 30
    chart_w = chart_right - chart_left
    chart_h = chart_bottom - chart_top

    # Titel
    draw.text((60, y_top + 5), "HEUTE", fill=BLACK, font=FONTS["stats_label"])

    buckets = data.chart_buckets
    if not buckets:
        draw.text((chart_left + chart_w // 2 - 80, chart_top + chart_h // 2 - 10),
                  "Keine Daten", fill=MID_GRAY, font=FONTS["card_label"])
        # Trotzdem Achsen zeichnen
        draw.line([(chart_left, chart_bottom), (chart_right, chart_bottom)],
                  fill=CHART_GRID_LINE, width=1)
        draw.line([(chart_left, chart_top), (chart_left, chart_bottom)],
                  fill=CHART_GRID_LINE, width=1)
        return

    # Y-Achse: Max-Wert bestimmen
    max_power = max(
        max((b.p_w_avg for b in buckets), default=0),
        max((b.c_w_avg for b in buckets), default=0),
    )
    y_max = max(1000, math.ceil(max_power / 2000) * 2000)  # Aufrunden auf 2kW

    # X-Achse: 0-24h
    def time_to_x(hour: float) -> int:
        return chart_left + int(chart_w * hour / 24)

    def power_to_y(watts: float) -> int:
        return chart_bottom - int(chart_h * min(watts, y_max) / y_max)

    # Gitterlinien (horizontal)
    for kw in range(0, int(y_max / 1000) + 1, 2):
        y = power_to_y(kw * 1000)
        draw.line([(chart_left, y), (chart_right, y)], fill=LIGHT_GRAY, width=1)
        draw.text((chart_left - 55, y - 10), f"{kw} kW",
                  fill=MID_GRAY, font=FONTS["chart_value"])

    # Gitterlinien (vertikal, alle 3h)
    for h in range(0, 25, 3):
        x = time_to_x(h)
        draw.line([(x, chart_top), (x, chart_bottom)], fill=LIGHT_GRAY, width=1)
        if h < 24:
            draw.text((x - 8, chart_bottom + 4), f"{h:02d}",
                      fill=MID_GRAY, font=FONTS["chart_value"])

    # PV-Produktion als gefüllte Fläche
    pv_points = []
    for b in buckets:
        ts_local = b.timestamp.astimezone(_LOCAL_TZ)
        hour = ts_local.hour + ts_local.minute / 60.0
        x = time_to_x(hour)
        y = power_to_y(b.p_w_avg)
        pv_points.append((x, y))

    if len(pv_points) >= 2:
        # Geschlossenes Polygon für Füllung
        fill_points = [(pv_points[0][0], chart_bottom)]
        fill_points.extend(pv_points)
        fill_points.append((pv_points[-1][0], chart_bottom))
        draw.polygon(fill_points, fill=CHART_PV_FILL)

        # PV-Linie obendrauf
        draw.line(pv_points, fill=CHART_PV, width=3)

    # Verbrauch als Linie
    cons_points = []
    for b in buckets:
        ts_local = b.timestamp.astimezone(_LOCAL_TZ)
        hour = ts_local.hour + ts_local.minute / 60.0
        x = time_to_x(hour)
        y = power_to_y(b.c_w_avg)
        cons_points.append((x, y))

    if len(cons_points) >= 2:
        draw.line(cons_points, fill=CHART_CONSUMPTION, width=2)

    # Legende
    legend_x = chart_right - 200
    legend_y = y_top + 5
    draw.rectangle([(legend_x, legend_y + 4), (legend_x + 20, legend_y + 14)],
                   fill=CHART_PV_FILL, outline=CHART_PV)
    draw.text((legend_x + 26, legend_y), "PV", fill=DARK_GRAY, font=FONTS["chart_label"])
    draw.line([(legend_x + 70, legend_y + 9), (legend_x + 90, legend_y + 9)],
              fill=CHART_CONSUMPTION, width=2)
    draw.text((legend_x + 96, legend_y), "Verbr.", fill=DARK_GRAY, font=FONTS["chart_label"])

    # Achsen
    draw.line([(chart_left, chart_bottom), (chart_right, chart_bottom)],
              fill=CHART_GRID_LINE, width=1)
    draw.line([(chart_left, chart_top), (chart_left, chart_bottom)],
              fill=CHART_GRID_LINE, width=1)


def _draw_daily_stats(draw: ImageDraw.Draw, data: DashboardData, W: int, y_start: int):
    """Tageswerte: korrekt aggregiert aus gespeicherten Intervallen."""
    summary = data.daily_summary

    if summary is None or summary.samples == 0:
        draw.text((60, y_start + 10), "Keine Tagesdaten",
                  fill=MID_GRAY, font=FONTS["stats_label"])
        return

    stats = [
        ("Produktion", f"{_format_kwh(summary.production_wh)} kWh"),
        ("Verbrauch", f"{_format_kwh(summary.consumption_wh)} kWh"),
        ("Eigenverbr.", f"{summary.self_consumption_rate * 100:.0f}%"),
        ("Autarkie", f"{summary.autarchy_degree * 100:.0f}%"),
        ("Einspeisung", f"{_format_kwh(summary.export_wh)} kWh"),
        ("Bezug", f"{_format_kwh(summary.import_wh)} kWh"),
    ]

    box_w = (W - 120) // len(stats)
    for i, (label, value) in enumerate(stats):
        bx = 60 + i * box_w
        by = y_start

        _rounded_rect(draw, (bx, by, bx + box_w - 10, by + 105),
                      radius=12, fill=CARD_BG)
        draw.text((bx + 12, by + 8), label, fill=DARK_GRAY, font=FONTS["small"])
        draw.text((bx + 12, by + 35), value, fill=BLACK, font=FONTS["stats_value"])


def _draw_bottom_row(draw: ImageDraw.Draw, data: DashboardData, W: int,
                     H: int, y_start: int):
    """Geräte links, PV-Performance rechts."""
    mid_x = W // 2

    # --- Geräte (linke Hälfte) ---
    draw.text((60, y_start), "GERÄTE", fill=DARK_GRAY, font=FONTS["small"])
    devices = data.devices
    if devices:
        dx = 60
        dy = y_start + 28
        for dev in devices[:4]:  # Max 4 Geräte anzeigen
            _rounded_rect(draw, (dx, dy, dx + mid_x - 100, dy + 50),
                          radius=10, fill=CARD_BG, outline=LIGHT_GRAY)
            # Status-Punkt
            color = DARK_GRAY if dev.signal == "connected" else LIGHT_GRAY
            draw.ellipse((dx + 12, dy + 18, dx + 24, dy + 30), fill=color)

            if dev.power_w > 0:
                val, unit = _format_power(dev.power_w)
                text = f"{dev.name}: {val} {unit}"
                text_color = BLACK
            elif dev.soc is not None:
                text = f"{dev.name}: {dev.soc:.0f}%"
                text_color = BLACK
            else:
                text = f"{dev.name}: ---"
                text_color = MID_GRAY
            draw.text((dx + 32, dy + 12), text, fill=text_color,
                      font=FONTS["device_text"])
            dy += 58
    else:
        draw.text((60, y_start + 30), "Keine Geräte",
                  fill=MID_GRAY, font=FONTS["device_text"])

    # --- PV-Performance (rechte Hälfte) ---
    perf_x = mid_x + 30
    draw.text((perf_x, y_start), "PV-PERFORMANCE (30 TAGE)", fill=DARK_GRAY,
              font=FONTS["small"])

    history = data.daily_history
    if not history:
        draw.text((perf_x, y_start + 30), "Keine Historie",
                  fill=MID_GRAY, font=FONTS["device_text"])
        return

    # Mini-Balkendiagramm
    bar_y_top = y_start + 30
    bar_y_bottom = H - 30
    bar_h = bar_y_bottom - bar_y_top
    available_w = W - 60 - perf_x
    bar_w = max(4, min(20, available_w // len(history) - 2))
    gap = max(1, (available_w - bar_w * len(history)) // max(1, len(history) - 1))

    max_prod = max((s.production_wh for s in history), default=1)

    for i, summary in enumerate(history):
        bx = perf_x + i * (bar_w + gap)
        ratio = summary.production_wh / max_prod if max_prod > 0 else 0
        filled_h = max(2, int(bar_h * ratio))
        bar_top = bar_y_bottom - filled_h

        # Balken
        fill = DARK_GRAY if ratio > 0.5 else MID_GRAY
        draw.rectangle([(bx, bar_top), (bx + bar_w, bar_y_bottom)], fill=fill)


def _quantize_16_grayscale(img: Image.Image) -> Image.Image:
    """Quantisiere auf 16 Graustufen (4-bit) für E-Ink-Kompatibilität."""
    import numpy as np
    arr = np.array(img, dtype=np.float32)
    # 16 Stufen: 0, 17, 34, 51, ..., 238, 255
    arr = np.round(arr / 17) * 17
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, mode="L")
