"""Tests für Aggregations-Logik."""

from datetime import date, datetime, timedelta, timezone

from src.aggregator import aggregate_chart_buckets, aggregate_daily_summary
from src.models import SensorPoint


def _make_point(hour: int, minute: int, second: int = 0, **kwargs) -> SensorPoint:
    """Hilfsfunktion: Erstelle einen SensorPoint zu einer bestimmten Uhrzeit (UTC)."""
    ts = datetime(2026, 3, 18, hour, minute, second, tzinfo=timezone.utc)
    defaults = dict(
        timestamp=ts, c_w=500, p_w=3000,
        bc_w=0, bd_w=0,
        c_wh=1.389, p_wh=8.333,  # 500W bzw 3000W * 10s/3600
        bc_wh=0, bd_wh=0,
        sc_wh=1.389, cpv_wh=1.389,
        i_wh=0, e_wh=6.944,
    )
    defaults.update(kwargs)
    return SensorPoint(**defaults)


class TestAggregateChartBuckets:
    def test_empty_input(self):
        assert aggregate_chart_buckets([]) == []

    def test_single_bucket(self):
        """Punkte im selben 5-min-Fenster werden gemittelt."""
        points = [
            _make_point(10, 0, 0, p_w=2000, c_w=400),
            _make_point(10, 0, 10, p_w=3000, c_w=600),
            _make_point(10, 0, 20, p_w=4000, c_w=500),
        ]
        buckets = aggregate_chart_buckets(points, bucket_minutes=5)
        assert len(buckets) == 1
        b = buckets[0]
        assert b.samples == 3
        assert abs(b.p_w_avg - 3000) < 0.1  # (2000+3000+4000)/3
        assert abs(b.c_w_avg - 500) < 0.1   # (400+600+500)/3

    def test_multiple_buckets(self):
        """Punkte in verschiedenen 5-min-Fenstern werden getrennt."""
        points = [
            _make_point(10, 0, p_w=2000),
            _make_point(10, 4, p_w=2500),  # Gleicher Bucket (10:00-10:04)
            _make_point(10, 5, p_w=3000),  # Neuer Bucket (10:05-10:09)
            _make_point(10, 10, p_w=4000),  # Neuer Bucket (10:10-10:14)
        ]
        buckets = aggregate_chart_buckets(points, bucket_minutes=5)
        assert len(buckets) == 3
        assert buckets[0].samples == 2
        assert buckets[1].samples == 1
        assert buckets[2].samples == 1

    def test_grid_correctly_calculated(self):
        """grid_w_avg nutzt die korrekte Formel (cW + bcW - pW - bdW)."""
        points = [
            _make_point(12, 0, c_w=500, p_w=7000, bc_w=0, bd_w=0),
        ]
        buckets = aggregate_chart_buckets(points)
        assert len(buckets) == 1
        # grid = 500 + 0 - 7000 - 0 = -6500 (Einspeisung)
        assert abs(buckets[0].grid_w_avg - (-6500)) < 0.1

    def test_grid_with_battery(self):
        """Batterie wird bei Netzberechnung im Bucket korrekt berücksichtigt."""
        points = [
            _make_point(12, 0, c_w=500, p_w=7000, bc_w=2000, bd_w=0),
        ]
        buckets = aggregate_chart_buckets(points)
        # grid = 500 + 2000 - 7000 - 0 = -4500 (weniger Einspeisung wg. Batterieladung)
        assert abs(buckets[0].grid_w_avg - (-4500)) < 0.1

    def test_sorted_output(self):
        """Buckets sind chronologisch sortiert."""
        points = [
            _make_point(14, 0),
            _make_point(10, 0),
            _make_point(12, 0),
        ]
        buckets = aggregate_chart_buckets(points)
        timestamps = [b.timestamp for b in buckets]
        assert timestamps == sorted(timestamps)


class TestAggregateDailySummary:
    def test_empty_input(self):
        s = aggregate_daily_summary([], date(2026, 3, 18))
        assert s.production_wh == 0
        assert s.samples == 0

    def test_sums_wh_values(self):
        """Tageswerte = Summe aller Intervall-Wh-Werte."""
        points = [
            _make_point(10, 0, 0, p_wh=8.0, c_wh=1.5, i_wh=0, e_wh=6.5, sc_wh=1.5),
            _make_point(10, 0, 10, p_wh=8.0, c_wh=1.5, i_wh=0, e_wh=6.5, sc_wh=1.5),
            _make_point(10, 0, 20, p_wh=8.0, c_wh=1.5, i_wh=0, e_wh=6.5, sc_wh=1.5),
        ]
        s = aggregate_daily_summary(points, date(2026, 3, 18))
        assert s.samples == 3
        assert abs(s.production_wh - 24.0) < 0.001  # 3 * 8.0
        assert abs(s.consumption_wh - 4.5) < 0.001  # 3 * 1.5
        assert abs(s.export_wh - 19.5) < 0.001      # 3 * 6.5
        assert abs(s.self_consumption_wh - 4.5) < 0.001

    def test_derived_rates(self):
        """Eigenverbrauchsquote und Autarkiegrad aus aggregierten Werten."""
        points = [
            _make_point(10, 0, p_wh=10.0, c_wh=4.0, sc_wh=3.0, i_wh=1.0, e_wh=7.0),
        ]
        s = aggregate_daily_summary(points, date(2026, 3, 18))
        # Eigenverbrauchsquote: 3 / 10 = 30%
        assert abs(s.self_consumption_rate - 0.3) < 0.001
        # Autarkiegrad: 1 - 1/4 = 75%
        assert abs(s.autarchy_degree - 0.75) < 0.001

    def test_battery_wh_accumulated(self):
        """Batterie-Wh werden korrekt aufsummiert."""
        points = [
            _make_point(12, 0, bc_wh=5.0, bd_wh=0),
            _make_point(18, 0, bc_wh=0, bd_wh=3.0),
        ]
        s = aggregate_daily_summary(points, date(2026, 3, 18))
        assert abs(s.battery_charge_wh - 5.0) < 0.001
        assert abs(s.battery_discharge_wh - 3.0) < 0.001
