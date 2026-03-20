from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from mock_data import DESIGN_REVIEW_WEEK_KWH, get_mock_live_point
from src.html_renderer import build_dashboard_context
from src.i18n import weekday_name
from src.models import DailySummary, DashboardData, SensorPoint
from src.models import ChartBucket
from src.preview_scenarios import apply_preview_scenario
from src import web_preview


def _make_history():
    today = date.today()
    return [
        DailySummary(
            local_date=today - timedelta(days=6 - i),
            production_wh=42000 + i * 100,
            consumption_wh=9000 + i * 50,
            samples=120,
        )
        for i in range(7)
    ]


def _make_live(ts: datetime | None = None, **kwargs) -> SensorPoint:
    defaults = dict(
        timestamp=ts or datetime.now(timezone.utc),
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
    assert context["week_history"][-1]["label"] == weekday_name("en", date.today().weekday())
    assert context["week_history"][-1]["produced"]


def test_chart_includes_peak_production_marker_and_label():
    data = DashboardData(
        live=_make_live(),
        chart_buckets=[],
        peak_production_w=1221,
        daily_history=_make_history(),
    )

    context = build_dashboard_context(data)
    chart = str(context["chart_svg"])

    assert "chart-peak-line" in chart
    assert "chart-peak-label" in chart
    assert "Peak Production: 1221 W" in chart


def test_peak_marker_uses_raw_peak_for_y_scale_not_only_bucket_average():
    data = DashboardData(
        live=_make_live(),
        chart_buckets=[
            ChartBucket(
                timestamp=datetime(2026, 3, 19, 10, 0, tzinfo=timezone.utc),
                p_w_avg=5200,
                c_w_avg=1800,
                samples=5,
            )
        ],
        peak_production_w=10135,
        daily_history=_make_history(),
    )

    chart = str(build_dashboard_context(data)["chart_svg"])

    assert 'Peak Production: 5200 W' in chart
    assert '<line class="chart-peak-line" x1="76.0" y1="10.0"' not in chart


def test_build_dashboard_context_marks_stale_live_data():
    local_tz = ZoneInfo("Europe/Zurich")
    stale_local = datetime.now(local_tz) - timedelta(minutes=10)
    stale_utc = stale_local.astimezone(timezone.utc)
    data = DashboardData(live=_make_live(ts=stale_utc), daily_history=_make_history())

    context = build_dashboard_context(data)

    assert "stale" in context["last_update"]
    assert "Stale live data" not in str(context["flow_svg"])


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


def test_build_dashboard_context_pads_week_history_to_seven_days():
    today = date.today()
    data = DashboardData(
        live=_make_live(),
        daily_history=[
            DailySummary(local_date=today - timedelta(days=1), production_wh=12000, consumption_wh=5000),
            DailySummary(local_date=today, production_wh=8000, consumption_wh=3000),
        ],
    )

    context = build_dashboard_context(data)

    assert len(context["week_history"]) == 7
    assert context["week_history"][-1]["label"] == weekday_name("en", date.today().weekday())
    assert context["week_history"][0]["produced"] == "0.0"


def test_build_dashboard_context_supports_localized_literals():
    data = DashboardData(live=_make_live(), daily_history=_make_history())

    context = build_dashboard_context(data, lang="de")

    assert context["last_update"].startswith("Letztes Update")
    assert context["produced_label"] == "produziert"
    assert context["week_history"][-1]["label"] == weekday_name("de", date.today().weekday())


def test_week_history_uses_full_labels_with_safe_sizing():
    data = DashboardData(live=_make_live(), daily_history=_make_history())

    context = build_dashboard_context(data, lang="de")

    labels = [item["label"] for item in context["week_history"]]
    expected = [
        weekday_name("de", (date.today() - timedelta(days=offset)).weekday())
        for offset in range(6, -1, -1)
    ]
    assert labels == expected
    assert any(item["name_class"] == "history-day__name--xlong" for item in context["week_history"])


def test_flask_preview_supports_scenario_override():
    web_preview._get_dashboard_data = lambda: DashboardData(
        live=_make_live(),
        daily_history=_make_history(),
    )
    client = web_preview.app.test_client()

    response = client.get("/?scenario=no_battery")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "unavailable" not in body
    assert '<text class="flow-node__sub" x="0" y="66" text-anchor="middle"></text>' in body


def test_flask_preview_scenario_preserves_peak_marker():
    web_preview._get_dashboard_data = lambda: DashboardData(
        live=_make_live(),
        peak_production_w=1221,
        daily_history=_make_history(),
    )
    client = web_preview.app.test_client()

    response = client.get("/?scenario=pv_surplus")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "chart-peak-line" in body
    assert "Peak Production: 1221 W" in body


def test_flow_active_paths_use_midline_arrow_glyphs():
    data = DashboardData(
        live=_make_live(p_w=4200, c_w=1800, bc_w=800, bd_w=0),
        daily_history=_make_history(),
    )

    flow_svg = str(build_dashboard_context(data)["flow_svg"])

    assert 'marker-end=' not in flow_svg
    assert flow_svg.count('class="flow-arrow"') >= 2


def test_flask_preview_scenarios_index_lists_links():
    client = web_preview.app.test_client()

    response = client.get("/scenarios")

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Dashboard Preview Scenarios" in body
    assert "?scenario=pv_surplus&lang=en" in body
    assert "?scenario=stale&lang=it" in body
    assert ">EN</a>" in body
    assert ">DE</a>" in body
    assert ">FR</a>" in body
    assert ">IT</a>" in body


def test_build_dashboard_context_uses_custom_history_labels():
    labels = [label for label, _, _ in DESIGN_REVIEW_WEEK_KWH]
    data = DashboardData(
        live=_make_live(),
        daily_history=_make_history(),
        history_labels=labels,
    )

    context = build_dashboard_context(data)

    assert [item["label"] for item in context["week_history"]] == labels
    assert context["week_history"][2]["name_class"] == "history-day__name--long"


def test_mock_dashboard_data_uses_localized_weekday_labels(tmp_path):
    from main import build_mock_dashboard_data
    from src.storage import Storage

    data = build_mock_dashboard_data(Storage(str(tmp_path / "mock.db")))
    context = build_dashboard_context(data, lang="de")

    labels = [item["label"] for item in context["week_history"]]
    expected = [
        weekday_name("de", (date.today() - timedelta(days=offset)).weekday())
        for offset in range(6, -1, -1)
    ]
    assert labels == expected
    assert "Heute" not in labels
    assert "Today" not in labels


def test_mock_dashboard_data_is_fresh_by_default(tmp_path):
    from main import build_mock_dashboard_data
    from src.storage import Storage

    data = build_mock_dashboard_data(Storage(str(tmp_path / "mock.db")))
    context = build_dashboard_context(data, lang="en")

    assert "stale" not in context["last_update"].lower()


def test_preview_pv_surplus_is_fresh_but_stale_scenario_is_marked(tmp_path):
    from main import build_mock_dashboard_data
    from src.storage import Storage

    data = build_mock_dashboard_data(Storage(str(tmp_path / "mock.db")))
    fresh = build_dashboard_context(apply_preview_scenario(data, "pv_surplus"), lang="en")
    stale = build_dashboard_context(apply_preview_scenario(data, "stale"), lang="en")

    assert "stale" not in fresh["last_update"].lower()
    assert "stale" in stale["last_update"].lower()


def test_mock_live_reference_matches_figma_state():
    point = get_mock_live_point()

    assert point.timestamp.hour == 13  # 14:32 Europe/Zurich in UTC on 2026-03-19
    assert point.p_w == 2204.0
    assert point.c_w == 3104.0
    assert point.grid_w > 0


def test_battery_icon_fill_tracks_soc_more_granularly():
    data = DashboardData(live=_make_live(soc=84), daily_history=_make_history())

    context = build_dashboard_context(data)
    svg = str(context["flow_svg"])

    assert "flow-node__icon-battery-fill" in svg
    assert 'width="26.9"' in svg


def test_battery_icon_renders_empty_when_soc_is_zero():
    data = DashboardData(live=_make_live(soc=0), daily_history=_make_history())

    context = build_dashboard_context(data)
    svg = str(context["flow_svg"])

    assert "flow-node__icon-battery-fill" in svg
    assert 'width="0.0"' in svg
