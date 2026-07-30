"""Eingehende Host/Origin-Prüfung des Streamable-HTTP-Transports (SEC-005).

Auslöser war kein fehlender Schutz, sondern ein zu strenger an der falschen
Adresse. mcp 2.x aktiviert automatisch eine Allow-List auf ``127.0.0.1:*``, wenn
das ``host``-Argument der App loopback-artig aussieht — und
``streamable_http_app()`` defaultet genau darauf. Der Einstiegspunkt sieht
``MCP_HOST=0.0.0.0`` ausdrücklich fürs Cloud-Deployment vor (mit
``MCP_ALLOW_ANY_HOST=1``), also bekam genau dieser Fall auf jede Anfrage unter
einem echten Hostnamen HTTP 421.

Der Server hat bereits einen optionalen API-Key-Schutz. Der ersetzt die
Host-Prüfung nicht: er prüft, *wer* fragt, nicht *unter welchem Namen* der
Server angesprochen wird — DNS-Rebinding zielt auf Letzteres.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from meteoswiss_mcp.server import _build_http_app, build_transport_security

_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}
_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("MCP_ALLOWED_HOSTS", "MCP_ALLOWED_ORIGINS", "MCP_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield


def test_loopback_bind_is_protected():
    sec = build_transport_security("127.0.0.1", 8000)
    assert sec is not None
    assert sec.enable_dns_rebinding_protection is True
    assert "127.0.0.1:8000" in sec.allowed_hosts


def test_wildcard_bind_without_allowlist_stays_off():
    """Der eigentliche Fix.

    Auf 0.0.0.0 ist der erreichbare Name hier unbekannt, und der
    SDK-Loopback-Default ist genau eine Vermutung — er reproduziert das 421.
    """
    assert build_transport_security("0.0.0.0", 8000) is None


def test_wildcard_bind_with_allowlist_is_protected(monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "meteo.example.ch")
    sec = build_transport_security("0.0.0.0", 8000)
    assert sec is not None
    assert "meteo.example.ch" in sec.allowed_hosts
    # Loopback bleibt drin, sonst brechen Health-Probes.
    assert "127.0.0.1:8000" in sec.allowed_hosts


def test_cors_origins_pass_the_transport_check(monkeypatch):
    """Sonst weist der Transport genau die Browser-Clients ab, die CORS erlaubt."""
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://claude.ai")
    sec = build_transport_security("127.0.0.1", 8000)
    assert "https://claude.ai" in sec.allowed_origins


def test_wildcard_cors_is_not_copied(monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "*")
    sec = build_transport_security("127.0.0.1", 8000)
    assert "*" not in sec.allowed_origins


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_all_loopback_forms_count_as_local(host):
    assert build_transport_security(host, 8000) is not None


def _post(app, host_header: str) -> int:
    with TestClient(app) as client:
        return client.post(
            "/mcp", headers={"Host": host_header, **_HEADERS}, json=_INIT
        ).status_code


def test_a_public_bind_is_reachable_again():
    """Die Regression selbst, durch den echten ASGI-Stack.

    Ohne den ``host``-Kwarg ist das ein 421 — der Zustand, den dieser Commit
    behebt.
    """
    assert _post(_build_http_app("0.0.0.0", 8000), "meteo.example.ch") == 200


def test_configured_host_is_served(monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "meteo.example.ch")
    assert _post(_build_http_app("0.0.0.0", 8000), "meteo.example.ch") == 200


def test_foreign_host_is_rejected(monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "meteo.example.ch")
    assert _post(_build_http_app("0.0.0.0", 8000), "evil.example.com") == 421


def test_right_host_wrong_port_is_rejected(monkeypatch):
    """Der tragende Fall.

    ``evil.example.com`` allein beweist wenig: ein zurückfallender
    Loopback-Default würde ihn ebenfalls abweisen. Nur „richtiger Hostname,
    falscher Port" unterscheidet eine portgenaue Allow-List von einer, die alles
    durchlässt.
    """
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "meteo.example.ch:8000")
    assert _post(_build_http_app("0.0.0.0", 8000), "meteo.example.ch:9999") == 421


def test_stateless_setting_still_reaches_the_app(monkeypatch):
    """Der bereits vorhandene Kwarg darf beim Ergänzen nicht verloren gehen —
    genau diese Fehlerklasse wird hier ja gerade aufgeräumt."""
    import meteoswiss_mcp.server as srv

    captured: dict = {}
    real = type(srv.mcp).streamable_http_app

    def _spy(self, **kwargs):
        captured.update(kwargs)
        return real(self, **kwargs)

    monkeypatch.setattr(type(srv.mcp), "streamable_http_app", _spy)
    srv._build_http_app("127.0.0.1", 8000)
    assert "stateless_http" in captured
    assert captured["host"] == "127.0.0.1"
    assert captured["transport_security"] is not None
