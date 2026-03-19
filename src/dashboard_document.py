"""Render the dashboard document outside Flask for export and preview reuse."""

from __future__ import annotations

import base64
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_SRC_DIR = Path(__file__).resolve().parent
_TEMPLATE_DIR = _SRC_DIR / "templates"
_STATIC_CSS = _SRC_DIR / "static" / "dashboard.css"
_FONT_DIR = _SRC_DIR / "static" / "fonts"

_JINJA = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_dashboard_html(
    context: dict[str, object],
    *,
    stylesheet_href: str | None = None,
    embedded_css: str | None = None,
) -> str:
    template = _JINJA.get_template("dashboard.html")
    payload = dict(context)
    payload["stylesheet_href"] = stylesheet_href or "/static/dashboard.css"
    payload["embedded_css"] = embedded_css
    return template.render(**payload)


def _embedded_font_css() -> str:
    """Return @font-face CSS with base64-embedded Inter variable woff2 fonts."""
    font_specs = [
        ("inter-latin-ext.woff2", "U+0100-02BA, U+02BD-02C5, U+02C7-02CC, "
         "U+02CE-02D7, U+02DD-02FF, U+0304, U+0308, U+0329, U+1D00-1DBF, "
         "U+1E00-1E9F, U+1EF2-1EFF, U+2020, U+20A0-20AB, U+20AD-20C0, "
         "U+2113, U+2C60-2C7F, U+A720-A7FF"),
        ("inter-latin.woff2", "U+0000-00FF, U+0131, U+0152-0153, "
         "U+02BB-02BC, U+02C6, U+02DA, U+02DC, U+0304, U+0308, U+0329, "
         "U+2000-206F, U+20AC, U+2122, U+2191, U+2193, U+2212, U+2215, "
         "U+FEFF, U+FFFD"),
    ]
    css_parts = []
    for filename, unicode_range in font_specs:
        font_path = _FONT_DIR / filename
        if not font_path.exists():
            return ""  # no fonts bundled yet
        b64 = base64.b64encode(font_path.read_bytes()).decode("ascii")
        css_parts.append(
            f"@font-face {{\n"
            f"  font-family: 'DashboardFont';\n"
            f"  font-style: normal;\n"
            f"  font-weight: 100 900;\n"
            f"  font-display: swap;\n"
            f"  src: url('data:font/woff2;base64,{b64}') format('woff2');\n"
            f"  unicode-range: {unicode_range};\n"
            f"}}\n"
        )
    return "\n".join(css_parts)


def render_dashboard_standalone(context: dict[str, object]) -> str:
    css = _STATIC_CSS.read_text(encoding="utf-8")
    font_css = _embedded_font_css()
    if font_css:
        css = font_css + "\n" + css
    return render_dashboard_html(context, embedded_css=css)
