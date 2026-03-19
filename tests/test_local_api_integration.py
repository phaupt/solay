"""Optionale lokale Integrationstests gegen ein echtes Solar Manager Gateway.

Diese Tests laufen nur, wenn RUN_LOCAL_SM_TESTS=1 gesetzt ist und eine lokale
Konfiguration vorhanden ist. Sie sind für die lokale Entwicklung gedacht und
nicht für CI.
"""

from __future__ import annotations

import os

import pytest

import config
from src.api_local import LocalApiClient
from src.models import SensorPoint


def _should_run_live_tests() -> tuple[bool, str]:
    if os.getenv("RUN_LOCAL_SM_TESTS") != "1":
        return False, "Setze RUN_LOCAL_SM_TESTS=1 für echte lokale API-Tests."

    if config.SM_LOCAL_BASE_URL == "http://192.168.1.XXX":
        return False, "SM_LOCAL_BASE_URL ist nicht konfiguriert."

    return True, ""


_RUN_LIVE_TESTS, _SKIP_REASON = _should_run_live_tests()
pytestmark = pytest.mark.skipif(not _RUN_LIVE_TESTS, reason=_SKIP_REASON)


def test_local_point_endpoint_returns_valid_payload():
    client = LocalApiClient()
    payload = client.get_point()

    assert isinstance(payload, dict)
    assert "t" in payload
    assert "cW" in payload
    assert "pW" in payload

    point = SensorPoint.from_api(payload)
    assert point.timestamp is not None
    assert point.c_w >= 0
    assert point.p_w >= 0


def test_local_devices_endpoint_returns_list():
    client = LocalApiClient()
    payload = client.get_devices()

    assert isinstance(payload, list)
