from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from mock_data import DESIGN_REVIEW_WEEK_KWH, get_mock_live_point
from src.html_renderer import build_dashboard_context
from src.models import DailySummary, DashboardData, SensorPoint
from src import web_preview


def _make_history():
    return [
        DailySummary(
            local_date=date(2026, 3, day),
            production_wh=42000 + day * 100,
            consumption_wh=9000 + day * 50,
            samples=120,
        )
        for day in range(13, 20)
    ]


def _make_live(ts: datetime | None = None, **kwargs) -> SensorPoint:
    defaults = dict(
        timestamp=ts or datetime(2026, 3, 19, 13, 32, 0, tzinfo=timezone.utc),
        c_w=3107,
        p_w=2204,
        bc_w=0,
        bd_w=610,
        soc=84,
    )
    defaults.update(kwargs)
    return SensorPoint(**defaults)


def test_build_dashboard_context_has_expected_sections():
    data = DashboardData(live=_make_live(), daily_history=_make_history())
    context = build_dashboard_context(data)

    assert "Last update" in context["last_update"]
    assert "flow-svg" in str(context["flow_svg"])
    assert "chart-svg" in str(context["chart_svg"])
    assert context["week_history"][-1]["label"] == "Today"
    assert context["week_history"][-1]["produced"]


def test_build_dashboard_context_marks_stale_live_data():
    local_tz = ZoneInfo("Europe/Zurich")
    stale_local = datetime.now(local_tz) - timedelta(minutes=10)
    stale_utc = stale_local.astimezone(timezone.utc)
    data = DashboardData(live=_make_live(ts=stale_utc), daily_history=_make_history())

    context = build_dashboard_context(data)

    assert "stale" in context["last_update"]
    assert "Stale live data" in str(context["flow_svg"])


def test_flask_preview_serves_html_dashboard():
    web_preview._get_dashboard_data = lambda: DashboardData(
        live=_make_live(),
        daily_history=_make_history(),
    )
    client = web_preview.app.test_client()

    response = client.get("/")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Solar Manager Dashboard Preview" in body
    assert "Last update" in body
    assert "produced" in body


def test_flask_preview_supports_scenario_override():
    web_preview._get_dashboard_data = lambda: DashboardData(
        live=_make_live(),
        daily_history=_make_history(),
    )
    client = web_preview.app.test_client()

    response = client.get("/?scenario=no_battery")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "unavailable" in body


def test_flask_preview_scenarios_index_lists_links():
    client = web_preview.app.test_client()

    response = client.get("/scenarios")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Dashboard Preview Scenarios" in body
    assert "?scenario=pv_surplus" in body
    assert "?scenario=stale" in body


def test_build_dashboard_context_uses_custom_history_labels():
    labels = [label for label, _, _ in DESIGN_REVIEW_WEEK_KWH]
    data = DashboardData(
        live=_make_live(),
        daily_history=_make_history(),
        history_labels=labels,
    )

    context = build_dashboard_context(data)

    assert [item["label"] for item in context["week_history"]] == labels


def test_mock_live_reference_matches_figma_state():
    point = get_mock_live_point()

    assert point.timestamp.hour == 13  # 14:32 Europe/Zurich in UTC on 2026-03-19
    assert point.p_w == 2204.0
    assert point.c_w == 3104.0
    assert point.grid_w > 0


def test_battery_icon_uses_discrete_quarter_fill_levels():
    data = DashboardData(live=_make_live(soc=84), daily_history=_make_history())

    context = build_dashboard_context(data)
    svg = str(context["flow_svg"])

    assert "flow-node__icon-battery-fill--level-3" in svg
    assert 'width="24.0"' in svg


def test_battery_icon_renders_empty_when_soc_is_zero():
    data = DashboardData(live=_make_live(soc=0), daily_history=_make_history())

    context = build_dashboard_context(data)
    svg = str(context["flow_svg"])

    assert "flow-node__icon-battery-fill--level-0" in svg
    assert 'width="0.0"' in svg
