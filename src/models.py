"""Typisierte Datenmodelle für das Solar Dashboard.

Trennt API-Rohdaten sauber von interner Darstellung.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class SensorPoint:
    """Ein einzelner Datenpunkt vom Solar Manager (Stream oder Point).

    Watt-Werte (W) = momentane Leistung.
    Wattstunden-Werte (Wh) = Energie im aktuellen Intervall (~10s).
    """

    timestamp: datetime  # UTC
    c_w: float = 0.0  # Verbrauch [W]
    p_w: float = 0.0  # PV-Produktion [W]
    bc_w: float = 0.0  # Batterie Ladeleistung [W]
    bd_w: float = 0.0  # Batterie Entladeleistung [W]
    c_wh: float = 0.0  # Verbrauch [Wh] (Intervall)
    p_wh: float = 0.0  # Produktion [Wh] (Intervall)
    bc_wh: float = 0.0  # Batterie Ladung [Wh] (Intervall)
    bd_wh: float = 0.0  # Batterie Entladung [Wh] (Intervall)
    sc_wh: float = 0.0  # Eigenverbrauch [Wh] (Intervall)
    cpv_wh: float = 0.0  # Direktverbrauch aus PV [Wh] (Intervall)
    i_wh: float = 0.0  # Netzbezug [Wh] (Intervall)
    e_wh: float = 0.0  # Einspeisung [Wh] (Intervall)
    soc: float | None = None  # Batterie-SOC [%], None wenn keine Batterie

    @property
    def grid_w(self) -> float:
        """Netzleistung berechnen (batterieberücksichtigt).

        Positiv = Netzbezug, Negativ = Einspeisung.
        Formel: grid = Verbrauch + Batterieladung - Produktion - Batterieentladung
        """
        return self.c_w + self.bc_w - self.p_w - self.bd_w

    @property
    def has_battery(self) -> bool:
        return self.soc is not None or self.bc_w > 0 or self.bd_w > 0

    @classmethod
    def from_api(cls, data: dict) -> SensorPoint:
        """Erstelle SensorPoint aus API-Response (v2/point oder v2/stream)."""
        ts_str = data.get("t", "")
        try:
            timestamp = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            timestamp = datetime.now().astimezone()

        # SOC aus Devices extrahieren (Batterie-Device hat soc-Feld)
        soc = None
        for device in data.get("devices", []):
            device_soc = device.get("soc")
            if device_soc is not None and device_soc > 0:
                soc = float(device_soc)
                break

        return cls(
            timestamp=timestamp,
            c_w=float(data.get("cW", 0)),
            p_w=float(data.get("pW", 0)),
            bc_w=float(data.get("bcW", 0)),
            bd_w=float(data.get("bdW", 0)),
            c_wh=float(data.get("cWh", 0)),
            p_wh=float(data.get("pWh", 0)),
            bc_wh=float(data.get("bcWh", 0)),
            bd_wh=float(data.get("bdWh", 0)),
            sc_wh=float(data.get("scWh", 0)),
            cpv_wh=float(data.get("cPvWh", 0)),
            i_wh=float(data.get("iWh", 0)),
            e_wh=float(data.get("eWh", 0)),
            soc=soc,
        )


@dataclass(frozen=True)
class ChartBucket:
    """Aggregierter Zeitraum für die Tagesgrafik (z.B. 5-Minuten-Bucket)."""

    timestamp: datetime  # Start des Buckets (UTC)
    p_w_avg: float = 0.0  # Ø PV-Produktion [W]
    c_w_avg: float = 0.0  # Ø Verbrauch [W]
    grid_w_avg: float = 0.0  # Ø Netzleistung [W] (pos=Bezug, neg=Einspeisung)
    bc_w_avg: float = 0.0  # Ø Batterie Ladung [W]
    bd_w_avg: float = 0.0  # Ø Batterie Entladung [W]
    samples: int = 0


@dataclass(frozen=True)
class DailySummary:
    """Aggregierte Tageswerte."""

    local_date: date
    production_wh: float = 0.0
    consumption_wh: float = 0.0
    import_wh: float = 0.0
    export_wh: float = 0.0
    self_consumption_wh: float = 0.0
    battery_charge_wh: float = 0.0
    battery_discharge_wh: float = 0.0
    samples: int = 0

    @property
    def self_consumption_rate(self) -> float:
        """Eigenverbrauchsquote: Anteil der Produktion, der selbst verbraucht wird.

        = Eigenverbrauch / Produktion. 100% = alles selbst genutzt.
        """
        if self.production_wh <= 0:
            return 0.0
        return min(1.0, self.self_consumption_wh / self.production_wh)

    @property
    def autarchy_degree(self) -> float:
        """Autarkiegrad: Anteil des Verbrauchs, der ohne Netzbezug gedeckt wird.

        = 1 - (Netzbezug / Verbrauch). 100% = kein Netzbezug nötig.
        """
        if self.consumption_wh <= 0:
            return 0.0
        return max(0.0, min(1.0, 1.0 - self.import_wh / self.consumption_wh))

    @property
    def production_kwh(self) -> float:
        return self.production_wh / 1000

    @property
    def consumption_kwh(self) -> float:
        return self.consumption_wh / 1000

    @property
    def import_kwh(self) -> float:
        return self.import_wh / 1000

    @property
    def export_kwh(self) -> float:
        return self.export_wh / 1000


@dataclass
class DeviceStatus:
    """Aktueller Status eines Geräts."""

    device_id: str
    name: str = ""
    signal: str = "disconnected"
    power_w: float = 0.0
    soc: float | None = None

    @classmethod
    def from_api(cls, data: dict) -> DeviceStatus:
        device_id = data.get("_id", data.get("data_id", "unknown"))
        soc_val = data.get("soc")
        return cls(
            device_id=device_id,
            name=data.get("name", device_id),
            signal=data.get("signal", "disconnected"),
            power_w=float(data.get("power", 0)),
            soc=float(soc_val) if soc_val is not None and soc_val > 0 else None,
        )


@dataclass
class DashboardData:
    """Komplettes Datenpaket für den Renderer."""

    live: SensorPoint | None = None
    chart_buckets: list[ChartBucket] = field(default_factory=list)
    daily_summary: DailySummary | None = None
    daily_history: list[DailySummary] = field(default_factory=list)
    devices: list[DeviceStatus] = field(default_factory=list)
