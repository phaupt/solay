"""PNG export path for the HTML dashboard."""

from __future__ import annotations

import asyncio
from pathlib import Path

from PIL import Image

import config
from src.dashboard_document import render_dashboard_standalone
from src.html_renderer import build_dashboard_context
from src.models import DashboardData


def _quantize_grayscale(path: Path, levels: int) -> None:
    image = Image.open(path).convert("L")
    if levels <= 1:
        image.save(path)
        return
    step = 255 / (levels - 1)
    quantized = image.point(lambda px: int(round(px / step) * step))
    quantized.save(path)


async def _screenshot_html(html: str, output_path: Path) -> None:
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover - depends on optional runtime package
        raise RuntimeError(
            "PNG export requires the optional 'playwright' package. "
            "Install it with './.venv312/bin/pip install playwright' and "
            "then run './.venv312/bin/python -m playwright install chromium'."
        ) from exc

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(
            viewport={"width": config.DISPLAY_WIDTH, "height": config.DISPLAY_HEIGHT},
            device_scale_factor=1,
        )
        await page.set_content(html, wait_until="load")
        await page.screenshot(path=str(output_path), full_page=False)
        await browser.close()


def export_dashboard_png(
    data: DashboardData,
    output_path: str | Path,
    *,
    theme: str | None = None,
    lang: str | None = None,
    grayscale_levels: int | None = None,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    context = build_dashboard_context(data, theme=theme, lang=lang, refresh_seconds=0)
    html = render_dashboard_standalone(context)
    asyncio.run(_screenshot_html(html, output))

    levels = config.EXPORT_GRAYSCALE_LEVELS if grayscale_levels is None else grayscale_levels
    if levels > 1:
        _quantize_grayscale(output, levels)

    return output
