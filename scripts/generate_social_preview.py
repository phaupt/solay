#!/usr/bin/env python3
"""Generate a GitHub/social preview image for the repository."""

from __future__ import annotations

from pathlib import Path
import textwrap

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SCREENSHOT_DIR = ROOT / "docs" / "screenshots"
OUTPUT_PATH = SCREENSHOT_DIR / "github-social-preview.jpg"

CANVAS_WIDTH = 1280
CANVAS_HEIGHT = 640


def _load_font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = []
    if bold:
        candidates.extend(
            [
                "/Library/Fonts/exljbris - MuseoSans-700.ttf",
                "/System/Library/Fonts/Supplemental/DIN Alternate Bold.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            ]
        )
    else:
        candidates.extend(
            [
                "/Library/Fonts/exljbris - MuseoSans-500.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf",
            ]
        )

    for candidate in candidates:
        path = Path(candidate)
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def _crop_to_fill(path: Path, size: tuple[int, int]) -> Image.Image:
    image = Image.open(path).convert("RGB")
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    return mask


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        width = draw.textbbox((0, 0), candidate, font=font)[2]
        if width <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def _draw_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    xy: tuple[int, int],
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
    max_width: int,
    line_gap: int,
) -> int:
    x, y = xy
    for line in _wrap(draw, text, font, max_width):
        draw.text((x, y), line, font=font, fill=fill)
        line_height = draw.textbbox((0, 0), line, font=font)[3]
        y += line_height + line_gap
    return y


def _add_shadow(base: Image.Image, card: Image.Image, xy: tuple[int, int], radius: int, blur: int) -> None:
    x, y = xy
    shadow = Image.new("RGBA", (card.width + blur * 2, card.height + blur * 2), (0, 0, 0, 0))
    shadow_mask = _rounded_mask((card.width, card.height), radius)
    shadow_alpha = Image.new("L", (card.width, card.height), 92)
    shadow.paste((16, 28, 23, 255), (blur, blur), ImageChops.multiply(shadow_mask, shadow_alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(shadow, (x - blur // 2, y - blur // 3))


def _paste_card(base: Image.Image, image: Image.Image, box: tuple[int, int, int, int], radius: int) -> None:
    x0, y0, x1, y1 = box
    width = x1 - x0
    height = y1 - y0
    card = image.resize((width, height), Image.Resampling.LANCZOS).convert("RGBA")
    mask = _rounded_mask((width, height), radius)
    _add_shadow(base, card, (x0, y0), radius, blur=24)
    frame = Image.new("RGBA", (width, height), (255, 255, 255, 230))
    base.alpha_composite(frame, (x0, y0))
    inner = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    inner.paste(card, (0, 0), mask)
    base.alpha_composite(inner, (x0, y0))


def _draw_pill(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, *, fill: tuple[int, int, int], text_fill: tuple[int, int, int]) -> int:
    font = _load_font(21, bold=True)
    padding_x = 18
    padding_y = 10
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0] + padding_x * 2
    height = bbox[3] - bbox[1] + padding_y * 2
    x, y = xy
    draw.rounded_rectangle((x, y, x + width, y + height), radius=height // 2, fill=fill)
    draw.text((x + padding_x, y + padding_y - 2), text, font=font, fill=text_fill)
    return width


def main() -> None:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

    canvas = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (241, 238, 229, 255))

    bg = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 0))
    bg_draw = ImageDraw.Draw(bg)
    for index in range(CANVAS_HEIGHT):
        blend = index / CANVAS_HEIGHT
        r = int(246 * (1 - blend) + 215 * blend)
        g = int(241 * (1 - blend) + 232 * blend)
        b = int(230 * (1 - blend) + 216 * blend)
        bg_draw.line((0, index, CANVAS_WIDTH, index), fill=(r, g, b, 255))
    bg_draw.ellipse((770, -80, 1320, 460), fill=(226, 197, 112, 70))
    bg_draw.ellipse((-140, 340, 340, 820), fill=(115, 149, 129, 72))
    bg_draw.rounded_rectangle((32, 32, CANVAS_WIDTH - 32, CANVAS_HEIGHT - 32), radius=36, outline=(255, 255, 255, 125), width=2)
    canvas.alpha_composite(bg)

    photo = _crop_to_fill(SCREENSHOT_DIR / "hero-product-photo.png", (600, 266))
    dashboard = _crop_to_fill(SCREENSHOT_DIR / "mock-dashboard-v4.png", (500, 375))

    _paste_card(canvas, photo, (44, 324, 644, 590), radius=34)
    _paste_card(canvas, dashboard, (732, 208, 1232, 583), radius=26)

    draw = ImageDraw.Draw(canvas)
    kicker_font = _load_font(22, bold=True)
    title_font = _load_font(60, bold=True)
    subtitle_font = _load_font(26, bold=False)
    caption_font = _load_font(22, bold=False)
    label_font = _load_font(19, bold=True)

    draw.text((48, 48), "SOLAR MANAGER  •  WAVESHARE  •  RASPBERRY PI", font=kicker_font, fill=(63, 86, 74))
    y = _draw_text_block(
        draw,
        "E-Paper Energy Dashboard",
        xy=(48, 88),
        font=title_font,
        fill=(26, 42, 33),
        max_width=620,
        line_gap=4,
    )
    y = _draw_text_block(
        draw,
        "Live energy flow, a 24-hour chart, and a 7-day history on a quiet always-on wall display.",
        xy=(48, y + 16),
        font=subtitle_font,
        fill=(55, 73, 63),
        max_width=610,
        line_gap=8,
    )

    pill_y = y + 26
    x = 48
    for text, fill, text_fill in [
        ("Solar Manager", (44, 106, 78), (255, 255, 255)),
        ("Waveshare 7.8 in", (234, 224, 197), (71, 66, 55)),
        ("Open Source", (255, 255, 255), (44, 106, 78)),
    ]:
        width = _draw_pill(draw, (x, pill_y), text, fill=fill, text_fill=text_fill)
        x += width + 14

    draw.text((737, 68), "Always-on energy overview", font=label_font, fill=(67, 95, 82))
    _draw_text_block(
        draw,
        "Built for Solar Manager owners who want a dedicated display instead of a tablet on the wall.",
        xy=(737, 98),
        font=caption_font,
        fill=(46, 58, 51),
        max_width=450,
        line_gap=6,
    )
    draw.text((741, 596), "GitHub: phaupt/solay", font=label_font, fill=(60, 83, 71))

    output = canvas.convert("RGB")
    output.save(OUTPUT_PATH, quality=88, optimize=True, progressive=True)
    print(OUTPUT_PATH.relative_to(ROOT))


if __name__ == "__main__":
    main()
