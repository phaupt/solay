"""Tests für Datenmodelle und API-Mapping."""

from datetime import datetime, timezone

from src.models import DailySummary, DeviceStatus, SensorPoint


class TestSensorPointFromApi:
    """API-Response korrekt auf SensorPoint mappen."""

    def test_basic_mapping(self):
        data = {
            "t": "2026-03-18T11:43:00Z",
            "v": 2,
            "cW": 500,
            "pW": 7400,
            "bcW": 0,
            "bdW": 0,
            "cWh": 1.5,
            "pWh": 21.6,
            "bcWh": 0,
            "bdWh": 0,
            "scWh": 0.8,
            "cPvWh": 0.7,
            "iWh": 0.3,
            "eWh": 5.2,
            "devices": [],
        }
        point = SensorPoint.from_api(data)
        assert point.c_w == 500
        assert point.p_w == 7400
        assert point.p_wh == 21.6
        assert point.sc_wh == 0.8
        assert point.soc is None
        assert not point.has_battery

    def test_battery_soc_extraction(self):
        """SOC wird aus dem ersten Batterie-Device extrahiert."""
        data = {
            "t": "2026-03-18T12:00:00Z",
            "cW": 1000, "pW": 5000,
            "bcW": 2000, "bdW": 0,
            "cWh": 0, "pWh": 0, "bcWh": 0, "bdWh": 0,
            "scWh": 0, "cPvWh": 0, "iWh": 0, "eWh": 0,
            "devices": [
                {"_id": "wallbox_01", "signal": "connected", "power": 0, "soc": 0},
                {"_id": "battery_01", "signal": "connected", "power": 2000, "soc": 72},
            ],
        }
        point = SensorPoint.from_api(data)
        assert point.soc == 72.0
        assert point.has_battery
        assert point.bc_w == 2000

    def test_grid_calculation_without_battery(self):
        """grid_w = cW + bcW - pW - bdW, ohne Batterie."""
        point = SensorPoint(
            timestamp=datetime.now(timezone.utc),
            c_w=500, p_w=7400,
            bc_w=0, bd_w=0,
        )
        # 500 + 0 - 7400 - 0 = -6900 (Einspeisung)
        assert point.grid_w == -6900

    def test_grid_calculation_with_battery_charging(self):
        """Bei Batterieladung steigt der rechnerische Netzbezug."""
        point = SensorPoint(
            timestamp=datetime.now(timezone.utc),
            c_w=500, p_w=7400,
            bc_w=3000, bd_w=0,  # Batterie lädt mit 3kW
        )
        # 500 + 3000 - 7400 - 0 = -3900 (Einspeisung, reduziert um Batterieladung)
        assert point.grid_w == -3900

    def test_grid_calculation_with_battery_discharging(self):
        """Bei Batterieentladung sinkt der Netzbezug."""
        point = SensorPoint(
            timestamp=datetime.now(timezone.utc),
            c_w=3000, p_w=0,
            bc_w=0, bd_w=2000,  # Batterie entlädt mit 2kW
        )
        # 3000 + 0 - 0 - 2000 = 1000 (Netzbezug, reduziert um Batterieentladung)
        assert point.grid_w == 1000

    def test_missing_fields_default_to_zero(self):
        """Fehlende Felder in der API-Response → 0."""
        data = {"t": "2026-03-18T12:00:00Z"}
        point = SensorPoint.from_api(data)
        assert point.c_w == 0
        assert point.p_w == 0
        assert point.grid_w == 0


class TestDailySummary:
    """Eigenverbrauchsquote und Autarkiegrad korrekt berechnen."""

    def test_self_consumption_rate(self):
        """Eigenverbrauchsquote = Eigenverbrauch / Produktion."""
        s = DailySummary(
            local_date=datetime.now().date(),
            production_wh=10000,
            consumption_wh=5000,
            self_consumption_wh=4000,  # 40% der Produktion selbst genutzt
            import_wh=1000,
            export_wh=6000,
        )
        assert abs(s.self_consumption_rate - 0.4) < 0.001

    def test_autarchy_degree(self):
        """Autarkiegrad = 1 - Netzbezug / Verbrauch."""
        s = DailySummary(
            local_date=datetime.now().date(),
            production_wh=10000,
            consumption_wh=5000,
            self_consumption_wh=4000,
            import_wh=1000,  # 1000 von 5000 aus dem Netz
            export_wh=6000,
        )
        # 1 - 1000/5000 = 0.8 = 80% Autarkie
        assert abs(s.autarchy_degree - 0.8) < 0.001

    def test_zero_production(self):
        """Nachts: keine Produktion → Eigenverbrauchsquote = 0."""
        s = DailySummary(
            local_date=datetime.now().date(),
            production_wh=0,
            consumption_wh=5000,
            import_wh=5000,
        )
        assert s.self_consumption_rate == 0.0
        assert s.autarchy_degree == 0.0

    def test_kwh_properties(self):
        s = DailySummary(
            local_date=datetime.now().date(),
            production_wh=12345,
            consumption_wh=6789,
        )
        assert abs(s.production_kwh - 12.345) < 0.001
        assert abs(s.consumption_kwh - 6.789) < 0.001


class TestDeviceStatus:
    def test_from_api_with_underscore_id(self):
        """API liefert _id (nicht data_id)."""
        data = {"_id": "bat_01", "signal": "connected", "power": 500, "soc": 80}
        dev = DeviceStatus.from_api(data)
        assert dev.device_id == "bat_01"
        assert dev.power_w == 500
        assert dev.soc == 80.0

    def test_soc_zero_treated_as_none(self):
        """SOC 0 wird als None behandelt (kein Batterie-/Auto-Device)."""
        data = {"_id": "switch_01", "signal": "connected", "power": 0, "soc": 0}
        dev = DeviceStatus.from_api(data)
        assert dev.soc is None
