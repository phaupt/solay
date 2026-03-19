"""Render the dashboard document outside Flask for export and preview reuse."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

_SRC_DIR = Path(__file__).resolve().parent
_TEMPLATE_DIR = _SRC_DIR / "templates"
_STATIC_CSS = _SRC_DIR / "static" / "dashboard.css"

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


def render_dashboard_standalone(context: dict[str, object]) -> str:
    css = _STATIC_CSS.read_text(encoding="utf-8")
    return render_dashboard_html(context, embedded_css=css)
