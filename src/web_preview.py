"""Flask dev preview for the HTML/CSS/SVG dashboard."""

from __future__ import annotations

import logging
from typing import Callable

from flask import Flask, Response, request, url_for

import config
from src.dashboard_document import render_dashboard_html
from src.html_renderer import build_dashboard_context
from src.i18n import SUPPORTED_LANGUAGES, normalize_language
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
    theme = request.args.get("theme")
    selected_lang = normalize_language(request.args.get("lang") or config.DASHBOARD_LANGUAGE)
    language_codes = [lang.upper() for lang in SUPPORTED_LANGUAGES]

    def _href(*, scenario: str | None = None, lang: str | None = None) -> str:
        params = []
        if scenario:
            params.append(f"scenario={scenario}")
        if lang:
            params.append(f"lang={lang}")
        if theme:
            params.append(f"theme={theme}")
        query = f"?{'&'.join(params)}" if params else ""
        return f"{url_for('index')}{query}"

    default_links = " · ".join(
        f"<a href='{_href(lang=lang)}'>{lang.upper()}</a>" for lang in SUPPORTED_LANGUAGES
    )
    rows = []
    for key, label in SCENARIO_LABELS.items():
        cells = "".join(
            f"<td><a href='{_href(scenario=key, lang=lang)}'>{lang.upper()}</a></td>"
            for lang in SUPPORTED_LANGUAGES
        )
        rows.append(f"<tr><th scope='row'>{label}</th>{cells}</tr>")
    body = (
        "<!DOCTYPE html><html><body style='font-family:sans-serif;padding:24px;line-height:1.5'>"
        "<h1>Dashboard Preview Scenarios</h1>"
        "<p>Use this page to open each preview state directly in EN, DE, FR, or IT.</p>"
        f"<p><strong>Default preview:</strong> {default_links}</p>"
        f"<p><strong>Current default language:</strong> {selected_lang.upper()}</p>"
        "<table style='border-collapse:collapse;margin-top:16px'>"
        "<thead><tr><th style='text-align:left;padding:6px 12px 6px 0'>Scenario</th>"
        + "".join(
            f"<th style='text-align:left;padding:6px 12px'>{lang}</th>"
            for lang in language_codes
        )
        + "</tr></thead>"
        "<tbody>"
        + "".join(rows)
        + "</tbody></table>"
        "</body></html>"
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
