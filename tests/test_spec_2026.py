"""Spec 2026-07-28 nativ: gemessen am Draht, nicht an SDK-Konstanten.

`tests/test_protocol_version.py` haelt die beiden Revisionen gegen die
Konstanten des SDK — die schwaechere Form, dort benannt. Hier steht die
staerkere: echte Anfragen durch `_build_http_app`, also durch denselben Stack
mit Transport-Security, CORS und Auth, den `main()` an uvicorn uebergibt.

Drei Dinge, die ein Konstantenvergleich nicht sieht:

* **Die moderne Aera wird tatsaechlich bedient.** Eine Anfrage mit dem
  `2026-07-28`-Envelope bekommt eine Antwort ohne `Mcp-Session-Id` und mit
  `resultType` — ohne `initialize` davor.
* **Die Handshake-Aera antwortet mit dem Deckel, den die READMEs nennen**,
  auch wenn der Client eine neuere Revision verlangt.
* **Der Server ruft keine Capability auf, die 2026-07-28 abkuendigt.**
  `ctx.info` / `ctx.warning` gehoeren zur Logging-Capability (SEP-2577). Ein
  moderner Client bekommt solche Meldungen nur auf Opt-in pro Anfrage, sonst
  verwirft das SDK sie still. Wo die Meldung einen Fehlschlag trug, las sich
  das Resultat danach wie ein Befund — `meteo_warnings` meldete «keine aktiven
  Warnungen», waehrend die Quelle nicht antwortete.
"""

from __future__ import annotations

import ast
import json
import pathlib
import warnings

import pytest
import respx
from mcp import Client
from mcp.shared.exceptions import MCPDeprecationWarning
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    PROTOCOL_VERSION_META_KEY,
)
from starlette.testclient import TestClient

from meteoswiss_mcp import server as srv

MODERN = "2026-07-28"
HANDSHAKE_CEILING = "2025-11-25"
ENDPOINT = "/mcp"
# Loopback, damit die Host-Pruefung der Transport-Security greift statt 421.
BASE_URL = "http://127.0.0.1:8000"
ACCEPT = "application/json, text/event-stream"

SRC = pathlib.Path(srv.__file__)

STAC_ITEM_KLO = (
    "https://data.geo.admin.ch/api/stac/v1/collections/ch.meteoschweiz.ogd-smn/items/klo"
)
APP_URL = "https://app-prod-ws.meteoswiss-app.ch/v1/plzDetail"
OPENDATA_URL = "https://opendata.swiss/api/3/action/package_search"


@pytest.fixture(autouse=True)
def _isolate_cache():
    srv._cache_clear()
    yield
    srv._cache_clear()


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch):
    for var in ("MCP_API_KEY", "MCP_ALLOWED_ORIGINS", "MCP_WARNINGS_API_URL"):
        monkeypatch.delenv(var, raising=False)
    with TestClient(srv._build_http_app(), base_url=BASE_URL) as client:
        yield client


def _envelope() -> dict:
    return {
        PROTOCOL_VERSION_META_KEY: MODERN,
        CLIENT_CAPABILITIES_META_KEY: {},
        CLIENT_INFO_META_KEY: {"name": "spec-2026-test", "version": "0"},
    }


def _modern_post(http: TestClient, method: str, params: dict, name: str | None = None):
    headers = {
        "Content-Type": "application/json",
        "Accept": ACCEPT,
        "Mcp-Method": method,
        "MCP-Protocol-Version": MODERN,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": {**params, "_meta": _envelope()}}
    return http.post(ENDPOINT, headers=headers, json=body)


# ---------------------------------------------------------------------------
# Draht: beide Aeren durch den zusammengebauten Stack
# ---------------------------------------------------------------------------


def test_server_discover_nennt_die_moderne_revision(http: TestClient) -> None:
    resp = _modern_post(http, "server/discover", {})

    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    assert MODERN in result["supportedVersions"]
    assert "mcp-session-id" not in resp.headers, (
        "eine 2026-07-28-Anfrage ist in sich geschlossen; eine Session-ID heisst, "
        "sie ist in der Handshake-Aera gelandet"
    )


def test_ein_werkzeugaufruf_ohne_handshake(http: TestClient) -> None:
    """Kein `initialize` davor — genau das unterscheidet die Aeren."""
    resp = _modern_post(
        http,
        "tools/call",
        {"name": "meteo_stations", "arguments": {"params": {"canton": "ZH"}}},
        name="meteo_stations",
    )

    assert resp.status_code == 200, resp.text
    result = resp.json()["result"]
    assert result["resultType"] == "complete"
    assert result.get("isError") is not True
    assert "KLO" in result["content"][0]["text"]
    assert "mcp-session-id" not in resp.headers


def test_die_moderne_aera_verlangt_den_passenden_header(http: TestClient) -> None:
    """Negativkontrolle: Envelope und Header widersprechen sich. Ohne sie
    waeren die beiden Tests oben auch gegen einen Server gruen, der den
    Envelope ignoriert und alles irgendwie beantwortet."""
    resp = http.post(
        ENDPOINT,
        headers={
            "Content-Type": "application/json",
            "Accept": ACCEPT,
            "Mcp-Method": "tools/list",
            "MCP-Protocol-Version": HANDSHAKE_CEILING,
        },
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": _envelope()}},
    )
    assert resp.status_code == 400, resp.text


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (HANDSHAKE_CEILING, HANDSHAKE_CEILING),
        # Wer im Handshake nach der modernen Revision fragt, bekommt den Deckel:
        # die moderne Aera erreicht man nur ueber den Envelope.
        (MODERN, HANDSHAKE_CEILING),
    ],
)
def test_der_handshake_deckelt_wo_die_readme_es_sagt(
    http: TestClient, requested: str, expected: str
) -> None:
    resp = http.post(
        ENDPOINT,
        headers={"Content-Type": "application/json", "Accept": ACCEPT},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": requested,
                "capabilities": {},
                "clientInfo": {"name": "spec-2026-test", "version": "0"},
            },
        },
    )

    assert resp.status_code == 200, resp.text
    # Die Handshake-Aera antwortet per SSE; die Nutzlast steht in der `data:`-Zeile.
    data = next(line for line in resp.text.splitlines() if line.startswith("data:"))
    assert json.loads(data.removeprefix("data:"))["result"]["protocolVersion"] == expected
    assert "mcp-session-id" in resp.headers, "Handshake-Aera ohne Session"


# ---------------------------------------------------------------------------
# Keine abgekuendigte Capability im Auslieferungspfad
# ---------------------------------------------------------------------------

# Die Methoden, die `Context` mit `@deprecated(... SEP-2577)` versieht.
_DEPRECATED_CTX_METHODS = {"log", "debug", "info", "notice", "warning", "error", "critical"}


def test_der_quelltext_ruft_keine_logging_methode_des_kontexts() -> None:
    """Statisch, damit auch ein Zweig auffaellt, den kein Test durchlaeuft."""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    offenders = [
        f"{SRC.name}:{node.lineno} ctx.{node.func.attr}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "ctx"
        and node.func.attr in _DEPRECATED_CTX_METHODS
    ]
    assert not offenders, (
        "Logging-Capability ist seit Spec 2026-07-28 abgekuendigt (SEP-2577): "
        f"{offenders}. Zwischenstand -> `_progress`, Fehlschlag -> ins Resultat."
    )


async def _call_modern(name: str, arguments: dict, progress: list | None = None):
    async def on_progress(done: float, total: float | None, message: str | None) -> None:
        if progress is not None:
            progress.append((done, total, message))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        async with Client(srv.mcp, mode=MODERN) as client:
            assert client.protocol_version == MODERN
            result = await client.call_tool(name, arguments, progress_callback=on_progress)
    deprecated = [str(w.message) for w in caught if issubclass(w.category, MCPDeprecationWarning)]
    return result, deprecated


async def test_ein_fehlschlag_ruft_keine_abgekuendigte_capability() -> None:
    """Dynamisch, auf dem Pfad, der frueher `ctx.warning` rief."""
    with respx.mock(assert_all_called=False) as r:
        r.get(STAC_ITEM_KLO).respond(500)
        result, deprecated = await _call_modern("meteo_current", {"params": {"station": "KLO"}})

    assert not deprecated, deprecated
    assert "nicht abrufbar" in result.content[0].text


async def test_der_zwischenstand_kommt_als_fortschritt_an() -> None:
    """Der Kanal, der `ctx.info` ersetzt — und in beiden Aeren gilt."""
    progress: list = []
    with respx.mock(assert_all_called=False) as r:
        r.get(STAC_ITEM_KLO).respond(500)
        _, deprecated = await _call_modern(
            "meteo_current", {"params": {"station": "KLO"}}, progress
        )

    assert not deprecated, deprecated
    assert progress, "kein notifications/progress angekommen"
    assert any("KLO" in (msg or "") for _, _, msg in progress)


# ---------------------------------------------------------------------------
# Wo die abgekuendigte Meldung der einzige Hinweis war: jetzt im Resultat
# ---------------------------------------------------------------------------


async def test_warnungen_ohne_antwort_sind_keine_entwarnung() -> None:
    with respx.mock(assert_all_called=False) as r:
        r.get(url__startswith=APP_URL).respond(500)
        r.get(url__startswith=OPENDATA_URL).respond(200, json={"result": {"results": []}})
        result, deprecated = await _call_modern("meteo_warnings", {"params": {"canton": "ZH"}})

    text = result.content[0].text
    assert not deprecated, deprecated
    assert "Warnlage unbekannt" in text
    assert "keine aktiven Warnungen" not in text


async def test_teilausfall_bleibt_eine_uebersicht_mit_hinweis() -> None:
    """Gegenstueck: nicht jede fehlgeschlagene PLZ macht die Lage unbekannt.
    Faellt nur ein Teil aus, steht die Uebersicht mit Hinweis da — sonst
    wuerde die Behebung oben jeden Einzelaussetzer zur Totalstoerung machen."""
    calls = {"n": 0}

    def flaky(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return respx.MockResponse(500)
        return respx.MockResponse(200, json={"warnings": []})

    with respx.mock(assert_all_called=False) as r:
        r.get(url__startswith=APP_URL).mock(side_effect=flaky)
        r.get(url__startswith=OPENDATA_URL).respond(200, json={"result": {"results": []}})
        result, _ = await _call_modern("meteo_warnings", {"params": {}})

    text = result.content[0].text
    assert "Warnlage unbekannt" not in text
    assert "1 PLZ-Abfrage(n) fehlgeschlagen" in text


async def test_override_api_ohne_antwort_ist_keine_entwarnung(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Der Override-Pfad schrieb frueher «strukturierte API lieferte 0
    Eintraege», wenn sie gar nicht geantwortet hatte."""
    api = "https://opendata.swiss/api/3/action/datastore_search?resource_id=warnings"
    monkeypatch.setenv("MCP_WARNINGS_API_URL", api)
    with respx.mock(assert_all_called=False) as r:
        r.get("https://opendata.swiss/api/3/action/datastore_search").respond(503)
        r.get(url__startswith=OPENDATA_URL).respond(200, json={"result": {"results": []}})
        md, _ = await _call_modern("meteo_warnings", {"params": {"canton": "ZH"}})
        srv._cache_clear()
        js, _ = await _call_modern(
            "meteo_warnings", {"params": {"canton": "ZH", "response_format": "json"}}
        )

    assert "Warnlage unbekannt" in md.content[0].text
    assert "0 Einträge" not in md.content[0].text
    assert '"quelle_nicht_erreichbar": true' in js.content[0].text


async def test_ausgefallener_ogd_katalog_steht_im_resultat() -> None:
    with respx.mock(assert_all_called=False) as r:
        r.get(url__startswith=APP_URL).respond(200, json={"warnings": []})
        r.get(url__startswith=OPENDATA_URL).respond(502)
        result, _ = await _call_modern("meteo_warnings", {"params": {"plz": "8001"}})

    assert "OGD-Katalog auf opendata.swiss nicht abrufbar" in result.content[0].text
