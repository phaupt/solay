"""Flask dev preview for the HTML/CSS/SVG dashboard."""

from __future__ import annotations

import logging
from typing import Callable

from flask import Flask, Response, request, url_for

import config
from src.dashboard_document import render_dashboard_html
from src.html_renderer import build_dashboard_context
from src.models import DashboardData
from src.preview_scenarios import SCENARIO_LABELS, apply_preview_scenario
from src.renderer import render_dashboard

logger = logging.getLogger(__name__)
app = Flask(__name__)

_get_dashboard_data: Callable[[], DashboardData] | None = None


def _require_dashboard_data() -> DashboardData:
    if _get_dashboard_data is None:
        raise RuntimeError("Dashboard data provider is not configured")
    return _get_dashboard_data()


@app.route("/")
def index():
    theme = request.args.get("theme")
    lang = request.args.get("lang")
    scenario = request.args.get("scenario")
    try:
        data = apply_preview_scenario(_require_dashboard_data(), scenario)
        context = build_dashboard_context(data, theme=theme, lang=lang)
    except Exception as exc:  # pragma: no cover - defensive preview fallback
        logger.exception("Preview rendering failed")
        return Response(
            (
                "<!DOCTYPE html><html><body style='font-family:sans-serif;padding:24px'>"
                f"<h1>Dashboard preview failed</h1><pre>{exc!s}</pre></body></html>"
            ),
            status=500,
            mimetype="text/html",
        )
    return Response(
        render_dashboard_html(
            context,
            stylesheet_href=url_for("static", filename="dashboard.css"),
        ),
        mimetype="text/html",
    )


@app.route("/scenarios")
def scenarios():
    links = []
    for key, label in SCENARIO_LABELS.items():
        links.append(
            f"<li><a href='{url_for('index')}?scenario={key}'>{label}</a>"
            f" <code>?scenario={key}</code></li>"
        )
    body = (
        "<!DOCTYPE html><html><body style='font-family:sans-serif;padding:24px;line-height:1.5'>"
        "<h1>Dashboard Preview Scenarios</h1>"
        f"<p><a href='{url_for('index')}'>Default preview</a></p>"
        "<ul>"
        + "".join(links)
        + "</ul></body></html>"
    )
    return Response(body, mimetype="text/html")


@app.route("/dashboard.png")
def dashboard_png():
    """Optional PNG fallback for comparison/export workflows."""
    data = _require_dashboard_data()
    img = render_dashboard(data)
    from io import BytesIO

    buf = BytesIO()
    img.save(buf, format="PNG")
    return Response(
        buf.getvalue(),
        mimetype="image/png",
        headers={"Cache-Control": "no-cache"},
    )


def start_server(
    get_dashboard_data: Callable[[], DashboardData],
    host: str | None = None,
    port: int | None = None,
):
    """Start the local browser preview server."""
    global _get_dashboard_data
    _get_dashboard_data = get_dashboard_data

    host = host or config.WEB_HOST
    port = port or config.WEB_PORT

    logger.info("Dashboard: http://%s:%d", host, port)
    print(f"Dashboard: http://{host}:{port}")
    app.run(host=host, port=port, debug=False)
