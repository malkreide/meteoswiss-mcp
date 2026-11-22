"""Tests fuer `_ConnectRetryClient` — ein haengender Handshake ist kein Ausfall.

Am 16. und 20.11.2026 war die Live-Suite rot, beide Male nur durch
`ConnectTimeout` im TLS-Handshake zu open-meteo, waehrend Anfragen an dieselben
Hosts im selben Lauf durchgingen. Die Einordnung sagte richtig `unknown`; der
Server hatte aber keine Toleranz fuer einen einzelnen haengenden
Verbindungsaufbau — Endnutzende sahen dieselbe Meldung «Fehler beim
Geokodieren von 'Zürich': ConnectTimeout».

Die Grenze ist eng gezogen: wiederholt wird nur, was die Quelle nie erreicht
hat. Was geantwortet hat, wird nicht wegwiederholt.
"""

from __future__ import annotations

import httpx
import pytest
import respx
from fixture_data import fixture_json

from meteoswiss_mcp import server

GEO = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"

_GEO_ZUERICH = {
    "results": [
        {
            "name": "Zürich",
            "latitude": 47.37,
            "longitude": 8.55,
            "admin1": "ZH",
            "country_code": "CH",
        }
    ]
}


class _FakeLogger:
    def __init__(self):
        self.events: list[tuple[str, str, dict]] = []

    def info(self, event, **kw):
        self.events.append(("info", event, kw))

    def warning(self, event, **kw):
        self.events.append(("warning", event, kw))

    def error(self, event, **kw):
        self.events.append(("error", event, kw))

    def debug(self, event, **kw):
        self.events.append(("debug", event, kw))


@pytest.fixture(autouse=True)
def _isolate_cache():
    server._cache_clear()
    yield
    server._cache_clear()


@pytest.fixture
def fake_logger(monkeypatch):
    fake = _FakeLogger()
    monkeypatch.setattr(server, "logger", fake)
    return fake


# ---------------------------------------------------------------------------
# Was wiederholt wird
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("fehler", [httpx.ConnectTimeout, httpx.ConnectError])
async def test_ein_gescheiterter_verbindungsaufbau_wird_einmal_wiederholt(fehler):
    with respx.mock() as r:
        route = r.get(GEO).mock(side_effect=[fehler("handshake"), httpx.Response(200, json={})])
        async with server._build_http_client() as client:
            resp = await client.get(GEO)

    assert resp.status_code == 200
    assert route.call_count == 2


@pytest.mark.asyncio
async def test_nur_ein_zweiter_versuch():
    """Bleibt auch der zweite Handshake haengen, ist es ein Ausfall — und der
    gehoert gemeldet, nicht in eine Schleife."""
    with respx.mock() as r:
        route = r.get(GEO).mock(
            side_effect=[
                httpx.ConnectTimeout("eins"),
                httpx.ConnectTimeout("zwei"),
                httpx.Response(200, json={}),
            ]
        )
        async with server._build_http_client() as client:
            with pytest.raises(httpx.ConnectTimeout):
                await client.get(GEO)

    assert route.call_count == 2


@pytest.mark.asyncio
async def test_der_tool_pfad_vom_20_11_2026():
    """Genau die Meldung aus dem roten Lauf: der erste Geocoding-Handshake haengt.

    Ohne Wiederholung steht im Resultat «Fehler beim Geokodieren von 'Zürich':
    ConnectTimeout»; mit ihr eine Prognose. Prueft, dass alle Tools ueber
    `_build_http_client` laufen und nicht an der Wiederholung vorbei.
    """
    with respx.mock(assert_all_called=False) as r:
        r.get(GEO).mock(
            side_effect=[
                httpx.ConnectTimeout("handshake"),
                httpx.Response(200, json=_GEO_ZUERICH),
            ]
        )
        r.get(FORECAST).respond(200, json=fixture_json("open_meteo_forecast.json"))
        result = await server.meteo_forecast(
            server.ForecastInput(location="Zürich", days=3, response_format="markdown")
        )

    assert "Geokodieren" not in result
    assert "°C" in result


# ---------------------------------------------------------------------------
# Was nicht wiederholt wird
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ein_read_timeout_wird_nicht_wiederholt():
    """Die Anfrage kann dort schon angekommen sein."""
    with respx.mock() as r:
        route = r.get(GEO).mock(
            side_effect=[httpx.ReadTimeout("lesen"), httpx.Response(200, json={})]
        )
        async with server._build_http_client() as client:
            with pytest.raises(httpx.ReadTimeout):
                await client.get(GEO)

    assert route.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 503])
async def test_eine_http_antwort_wird_nicht_wiederholt(status):
    """Ein 429 oder 503 ist eine Auskunft der Quelle. Wer ihn wegwiederholt,
    sieht ihn nicht mehr — siehe «Ein 4xx ist kein Nein» in CLAUDE.md."""
    with respx.mock() as r:
        route = r.get(GEO).mock(
            side_effect=[httpx.Response(status, json={}), httpx.Response(200, json={})]
        )
        async with server._build_http_client() as client:
            resp = await client.get(GEO)

    assert resp.status_code == status
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_blockierter_egress_wird_nicht_wiederholt(fake_logger):
    """Die Allow-List ist eine Entscheidung, kein Aussetzer."""
    async with server._build_http_client() as client:
        with pytest.raises(server.EgressBlocked):
            await client.get("https://evil.example.com/")

    assert [e for e in fake_logger.events if e[1] == "egress_blocked"]
    assert not [e for e in fake_logger.events if e[1] == "upstream_retry"]


# ---------------------------------------------------------------------------
# Sichtbarkeit und Rahmen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_die_wiederholung_wird_geloggt(fake_logger):
    """Sonst verschwaende ein gelungener zweiter Versuch spurlos, und wie oft
    der Netzweg hakt, waere nicht mehr messbar."""
    with respx.mock() as r:
        r.get(GEO).mock(side_effect=[httpx.ConnectTimeout("handshake"), httpx.Response(200)])
        async with server._build_http_client() as client:
            await client.get(GEO)

    retries = [e for e in fake_logger.events if e[1] == "upstream_retry"]
    assert len(retries) == 1
    level, _, kw = retries[0]
    assert level == "warning"
    assert kw == {"host": "geocoding-api.open-meteo.com", "error_type": "ConnectTimeout"}


def test_zwei_verbindungsversuche_dauern_nicht_laenger_als_einer_vorher():
    """Vorher ein Versuch mit 20 s. Zwei Versuche duerfen zusammen nicht mehr
    kosten, sonst wird ein echter Ausfall fuer Nutzende langsamer."""
    t = server._HTTP_TIMEOUT
    assert 2 * t.connect <= 20.0
    assert (t.read, t.write, t.pool) == (20.0, 20.0, 20.0)


def test_proxy_aus_der_umgebung_bleibt_erhalten(monkeypatch):
    """Die naheliegende Loesung `transport=httpx.AsyncHTTPTransport(retries=1)`
    schaltet die Proxy-Erkennung ab — httpx setzt `allow_env_proxies = trust_env
    and transport is None`. Der Client haette hinter `HTTPS_PROXY` still keine
    Verbindung mehr. `_mounts` ist privat, aber der einzige Ort, an dem httpx
    die Proxy-Zuordnung zeigt."""
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")

    client = server._build_http_client()
    proxied = {str(k.pattern): v for k, v in client._mounts.items() if v is not None}

    assert "https://" in proxied, client._mounts
