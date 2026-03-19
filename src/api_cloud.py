"""Optional Solar Manager cloud backfill client."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from datetime import date, datetime, time as time_of_day, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import requests

import config
from src.aggregator import aggregate_daily_summary
from src.models import DailySummary, SensorPoint
from src.storage import Storage

logger = logging.getLogger(__name__)


class CloudBackfillError(RuntimeError):
    """Raised when cloud backfill configuration or requests fail."""


class CloudApiClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        email: str | None = None,
        password: str | None = None,
        sm_id: str | None = None,
        timeout: int | None = None,
    ):
        self._base_url = (base_url or config.SM_CLOUD_BASE_URL).rstrip("/")
        self._email = email or config.SM_CLOUD_EMAIL
        self._password = password or config.SM_CLOUD_PASSWORD
        self._sm_id = sm_id or config.SM_CLOUD_SMID
        self._timeout = timeout or config.SM_CLOUD_TIMEOUT_SECONDS
        self._session = requests.Session()
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._token_type = "Bearer"
        self._expires_at = 0.0

    @property
    def configured(self) -> bool:
        return bool(self._email and self._password and self._sm_id)

    @property
    def sm_id(self) -> str:
        if not self._sm_id:
            raise CloudBackfillError("SM_CLOUD_SMID or SM_GATEWAY_ID is not configured")
        return self._sm_id

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._access_token:
            headers["Authorization"] = f"{self._token_type} {self._access_token}"
        return headers

    def _login(self) -> None:
        response = self._session.post(
            f"{self._base_url}/v1/oauth/login",
            json={"email": self._email, "password": self._password},
            timeout=self._timeout,
        )
        response.raise_for_status()
        payload = response.json()
        self._access_token = payload["accessToken"]
        self._refresh_token = payload.get("refreshToken")
        self._token_type = payload.get("tokenType", "Bearer")
        self._expires_at = time.time() + max(60, int(payload.get("expiresIn", 3600)) - 60)

    def _refresh(self) -> bool:
        if not self._refresh_token:
            return False
        response = self._session.post(
            f"{self._base_url}/v1/oauth/refresh",
            json={"refreshToken": self._refresh_token},
            timeout=self._timeout,
        )
        if response.status_code >= 400:
            return False
        payload = response.json()
        self._access_token = payload["accessToken"]
        self._refresh_token = payload.get("refreshToken", self._refresh_token)
        self._token_type = payload.get("tokenType", "Bearer")
        self._expires_at = time.time() + max(60, int(payload.get("expiresIn", 3600)) - 60)
        return True

    def _ensure_auth(self) -> None:
        if not self.configured:
            raise CloudBackfillError(
                "Cloud backfill requires SM_CLOUD_EMAIL, SM_CLOUD_PASSWORD, and SM_CLOUD_SMID/SM_GATEWAY_ID"
            )
        if self._access_token and time.time() < self._expires_at:
            return
        if self._access_token and self._refresh():
            return
        self._login()

    def _get(self, path: str, *, params: dict[str, Any]) -> Any:
        self._ensure_auth()
        response = self._session.get(
            f"{self._base_url}{path}",
            params=params,
            headers=self._headers(),
            timeout=self._timeout,
        )
        if response.status_code == 401 and self._refresh():
            response = self._session.get(
                f"{self._base_url}{path}",
                params=params,
                headers=self._headers(),
                timeout=self._timeout,
            )
        response.raise_for_status()
        return response.json()

    def get_statistics(self, start_utc: datetime, end_utc: datetime) -> dict[str, Any]:
        return self._get(
            f"/v1/statistics/gateways/{self.sm_id}",
            params={
                "accuracy": "high",
                "from": start_utc.isoformat().replace("+00:00", "Z"),
                "to": end_utc.isoformat().replace("+00:00", "Z"),
            },
        )

    def get_range(self, start_utc: datetime, end_utc: datetime, *, interval_seconds: int = 300) -> list[dict]:
        payload = self._get(
            f"/v3/users/{self.sm_id}/data/range",
            params={
                "from": start_utc.isoformat().replace("+00:00", "Z"),
                "to": end_utc.isoformat().replace("+00:00", "Z"),
                "interval": interval_seconds,
            },
        )
        return payload.get("data", [])


def _local_day_bounds(local_date: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start_local = datetime.combine(local_date, time_of_day.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _summary_from_statistics(local_date: date, payload: dict[str, Any]) -> DailySummary:
    production_wh = float(payload.get("production", 0.0))
    consumption_wh = float(payload.get("consumption", 0.0))
    self_consumption_wh = float(payload.get("selfConsumption", 0.0))
    import_wh = max(0.0, consumption_wh - self_consumption_wh)
    export_wh = max(0.0, production_wh - self_consumption_wh)
    return DailySummary(
        local_date=local_date,
        production_wh=production_wh,
        consumption_wh=consumption_wh,
        import_wh=import_wh,
        export_wh=export_wh,
        self_consumption_wh=self_consumption_wh,
        battery_charge_wh=0.0,
        battery_discharge_wh=0.0,
        samples=1,
    )


def optional_backfill(storage: Storage, *, skip_today: bool = False) -> int:
    """Optionally backfill missing daily history and the current-day prefix.

    Previous full days are filled via `/v1/statistics/gateways/{smId}`.
    The current-day prefix before the first local point is filled via
    `/v3/users/{smId}/data/range` to avoid double counting later local samples.
    """

    if not config.SM_CLOUD_BACKFILL_ENABLED:
        return 0

    client = CloudApiClient()
    if not client.configured:
        logger.info("Cloud backfill skipped: cloud credentials or smId not configured")
        return 0

    tz = ZoneInfo(config.TIMEZONE)
    today = datetime.now(tz).date()
    days = max(1, config.SM_CLOUD_BACKFILL_DAYS)
    added = 0

    for offset in range(days - 1, 0, -1):
        target_date = today - timedelta(days=offset)
        if storage.get_daily_summary(target_date) is not None:
            continue
        start_utc, end_utc = _local_day_bounds(target_date, tz)
        stats = client.get_statistics(start_utc, end_utc)
        storage.store_daily_summary(_summary_from_statistics(target_date, stats))
        added += 1

    if not skip_today:
        today_points = storage.get_points_for_date(today, tz=tz)
        day_start_utc, _ = _local_day_bounds(today, tz)
        prefix_end_utc = min((point.timestamp for point in today_points), default=datetime.now(timezone.utc))
        if prefix_end_utc > day_start_utc + timedelta(minutes=5):
            raw_points = client.get_range(
                day_start_utc,
                prefix_end_utc,
                interval_seconds=config.SM_CLOUD_BACKFILL_INTERVAL_SECONDS,
            )
            grouped: dict[date, list[SensorPoint]] = defaultdict(list)
            for item in raw_points:
                point = SensorPoint.from_api(item)
                storage.store_point(point, source="cloud_backfill")
                grouped[point.timestamp.astimezone(tz).date()].append(point)
            for local_date, points in grouped.items():
                storage.store_daily_summary(aggregate_daily_summary(points, local_date))
            added += len(raw_points)

    return added
