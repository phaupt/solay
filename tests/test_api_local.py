"""Tests für lokale TLS-Konfiguration und Fingerprint-Pinning."""

from __future__ import annotations

import hashlib
import ssl

import pytest

from src.api_local import (
    FingerprintMismatchError,
    LocalApiClient,
    StreamCollector,
    _build_requests_verify_arg,
    _format_sha256_fingerprint,
    _normalize_sha256_fingerprint,
    _peer_certificate_matches_fingerprint,
)


class _DummyStorage:
    def store_point(self, *args, **kwargs):
        pass


class _FakeSocket:
    def __init__(self, cert_der: bytes):
        self._cert_der = cert_der

    def getpeercert(self, binary_form: bool = False):
        return self._cert_der if binary_form else {}


class _FakeWebSocket:
    def __init__(self, cert_der: bytes):
        self.sock = type("SockWrapper", (), {"sock": _FakeSocket(cert_der)})()


class TestFingerprintHelpers:
    def test_normalize_sha256_fingerprint(self):
        raw = "A7:8B:BD:CF:3B:9A:B9:BF:C5:AA:D0:A5:57:41:E7:73:00:E6:36:37:44:43:E8:72:4A:EF:5E:C9:16:36:96:0D"
        normalized = _normalize_sha256_fingerprint(raw)
        assert normalized == "a78bbdcf3b9ab9bfc5aad0a55741e77300e636374443e8724aef5ec91636960d"

    def test_invalid_sha256_fingerprint_rejected(self):
        with pytest.raises(ValueError):
            _normalize_sha256_fingerprint("abc123")

    def test_format_sha256_fingerprint(self):
        normalized = "a78bbdcf3b9ab9bfc5aad0a55741e77300e636374443e8724aef5ec91636960d"
        assert _format_sha256_fingerprint(normalized).startswith("A7:8B:BD:CF")

    def test_peer_certificate_matches_fingerprint(self):
        cert_der = b"dummy-certificate"
        fingerprint = hashlib.sha256(cert_der).hexdigest()
        assert _peer_certificate_matches_fingerprint(cert_der, fingerprint)
        assert not _peer_certificate_matches_fingerprint(cert_der, "0" * 64)


class TestTlsConfig:
    def test_requests_verify_uses_bool_without_ca_bundle(self):
        assert _build_requests_verify_arg(False, None) is False
        assert _build_requests_verify_arg(True, None) is True

    def test_requests_verify_prefers_ca_bundle(self):
        assert _build_requests_verify_arg(False, "/tmp/ca.pem") == "/tmp/ca.pem"

    def test_client_websocket_sslopt_without_verification(self):
        client = LocalApiClient(
            base_url="https://example.test",
            verify_tls=False,
            ca_bundle="",
            fingerprint_sha256="a7" * 32,
        )
        assert client.websocket_sslopt["cert_reqs"] == ssl.CERT_NONE
        assert client.websocket_sslopt["check_hostname"] is False
        assert client.fingerprint_sha256 == "a7" * 32

    def test_client_websocket_sslopt_with_ca_bundle(self):
        client = LocalApiClient(
            base_url="https://example.test",
            verify_tls=True,
            ca_bundle="/tmp/local-ca.pem",
            fingerprint_sha256=None,
        )
        assert client.websocket_sslopt["cert_reqs"] == ssl.CERT_REQUIRED
        assert client.websocket_sslopt["ca_certs"] == "/tmp/local-ca.pem"
        assert client.requests_verify == "/tmp/local-ca.pem"


class TestWebSocketFingerprintPinning:
    def test_verify_websocket_peer_certificate_accepts_match(self):
        cert_der = b"stream-cert"
        fingerprint = hashlib.sha256(cert_der).hexdigest()
        client = LocalApiClient(
            base_url="https://example.test",
            verify_tls=False,
            fingerprint_sha256=fingerprint,
        )
        collector = StreamCollector(storage=_DummyStorage(), client=client)
        collector._verify_websocket_peer_certificate(_FakeWebSocket(cert_der))

    def test_verify_websocket_peer_certificate_rejects_mismatch(self):
        cert_der = b"stream-cert"
        client = LocalApiClient(
            base_url="https://example.test",
            verify_tls=False,
            fingerprint_sha256="0" * 64,
        )
        collector = StreamCollector(storage=_DummyStorage(), client=client)

        with pytest.raises(FingerprintMismatchError):
            collector._verify_websocket_peer_certificate(_FakeWebSocket(cert_der))
