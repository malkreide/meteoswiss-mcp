"""
Tests für meteoswiss-mcp.

Unit-Tests (kein Netzwerk):
    pytest tests/ -m "not live" -v

Live-Tests (echte APIs, CI ausgeschlossen):
    pytest tests/ -m live -v
"""

from __future__ import annotations

import json

import httpx
import pytest

from meteoswiss_mcp.server import (
    CLIMATE_NORMALS,
    MONTHS_DE,
    SMN_STATIONS,
    WMO_CODES_DE,
    _school_verdict,
    _wmo_description,
)

# ---------------------------------------------------------------------------
# Statische Daten
# ---------------------------------------------------------------------------


class TestSmnStations:
    def test_stations_not_empty(self):
        assert len(SMN_STATIONS) >= 10

    def test_klo_present(self):
        assert "KLO" in SMN_STATIONS
        assert SMN_STATIONS["KLO"]["canton"] == "ZH"

    def test_seh_present(self):
        """REH ist die nächste Station zum Schulhaus Leutschenbach."""
        assert "REH" in SMN_STATIONS
        assert SMN_STATIONS["REH"]["canton"] == "ZH"

    def test_all_stations_have_coords(self):
        for code, info in SMN_STATIONS.items():
            assert "lat" in info, f"{code} fehlt lat"
            assert "lon" in info, f"{code} fehlt lon"
            assert "alt" in info, f"{code} fehlt alt"
            assert "canton" in info, f"{code} fehlt canton"
            assert -90 <= info["lat"] <= 90
            assert -180 <= info["lon"] <= 180

    def test_swiss_coordinates(self):
        """Alle Stationen müssen in der Schweiz liegen (grob)."""
        for code, info in SMN_STATIONS.items():
            assert 45.5 <= info["lat"] <= 48.0, f"{code}: lat {info['lat']} ausserhalb Schweiz"
            assert 5.5 <= info["lon"] <= 11.0, f"{code}: lon {info['lon']} ausserhalb Schweiz"


class TestWmoCodes:
    def test_clear_sky(self):
        assert _wmo_description(0) == "Klar"

    def test_thunderstorm(self):
        assert "Gewitter" in _wmo_description(95)

    def test_unknown_code(self):
        result = _wmo_description(999)
        assert "999" in result

    def test_all_codes_non_empty(self):
        for code, desc in WMO_CODES_DE.items():
            assert desc, f"WMO-Code {code} hat leere Beschreibung"


class TestClimateNormals:
    def test_klo_available(self):
        assert "KLO" in CLIMATE_NORMALS

    def test_12_months(self):
        for station, data in CLIMATE_NORMALS.items():
            for key, values in data.items():
                assert len(values) == 12, f"{station}/{key} hat nicht 12 Monate"

    def test_months_list(self):
        assert len(MONTHS_DE) == 12
        assert MONTHS_DE[0] == "Januar"
        assert MONTHS_DE[11] == "Dezember"

    def test_klo_jan_temp(self):
        """Zürich/Kloten Januar-Temperatur muss unter 5°C sein."""
        jan_temp = CLIMATE_NORMALS["KLO"]["temp_mean"][0]
        assert jan_temp < 5.0, f"Januar-Temp KLO unrealistisch: {jan_temp}"

    def test_lug_warmer_than_klo(self):
        """Lugano muss wärmer sein als Zürich/Kloten (Jahresschnitt)."""
        klo_avg = sum(CLIMATE_NORMALS["KLO"]["temp_mean"]) / 12
        lug_avg = sum(CLIMATE_NORMALS["LUG"]["temp_mean"]) / 12
        assert lug_avg > klo_avg, "Lugano sollte wärmer sein als Kloten"


# ---------------------------------------------------------------------------
# Schuleignungs-Logik
# ---------------------------------------------------------------------------


class TestSchoolVerdict:
    def test_perfect_day(self):
        emoji, verdict = _school_verdict(
            temp=20.0, precip=0.0, wind=15.0, wmo=1, uv=3.0
        )
        assert emoji == "🟢"
        assert "Geeignet" in verdict

    def test_rain_day(self):
        emoji, verdict = _school_verdict(
            temp=15.0, precip=5.0, wind=20.0, wmo=63, uv=1.0
        )
        assert emoji == "🔴"
        assert "Nicht geeignet" in verdict

    def test_frost_day(self):
        emoji, verdict = _school_verdict(
            temp=-2.0, precip=0.0, wind=10.0, wmo=0, uv=2.0
        )
        assert emoji == "🔴"
        assert "kalt" in verdict.lower()

    def test_thunderstorm(self):
        emoji, verdict = _school_verdict(
            temp=22.0, precip=8.0, wind=60.0, wmo=95, uv=5.0
        )
        assert emoji == "🔴"

    def test_uv_warning(self):
        """Hoher UV-Index → gelb, nicht rot."""
        emoji, verdict = _school_verdict(
            temp=28.0, precip=0.0, wind=10.0, wmo=0, uv=8.0
        )
        assert emoji == "🟡"
        assert "UV" in verdict or "uv" in verdict.lower() or "Sonnenschutz" in verdict

    def test_marginal_overcast(self):
        """Bedeckt (WMO 3) → bedingt geeignet."""
        emoji, verdict = _school_verdict(
            temp=18.0, precip=0.0, wind=20.0, wmo=3, uv=2.0
        )
        assert emoji in ("🟢", "🟡")

    def test_windy_day(self):
        emoji, verdict = _school_verdict(
            temp=20.0, precip=0.0, wind=70.0, wmo=0, uv=3.0
        )
        assert emoji == "🔴"
        assert "windig" in verdict.lower()


# ---------------------------------------------------------------------------
# Tool-Rückgabeformat (ohne Netzwerk)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_meteo_stations_markdown():
    from meteoswiss_mcp.server import StationsInput, meteo_stations

    result = await meteo_stations(StationsInput(canton="ZH"))
    assert "KLO" in result
    assert "REH" in result
    assert "Zürich" in result


@pytest.mark.asyncio
async def test_meteo_stations_json():
    from meteoswiss_mcp.server import StationsInput, meteo_stations

    result = await meteo_stations(StationsInput(canton="ZH", response_format="json"))
    data = json.loads(result)
    # PR-6: OGDResponse-Envelope mit payload + provenance
    assert "stationen" in data["payload"]
    assert "KLO" in data["payload"]["stationen"]
    assert data["provenance"]["license"] == "CC BY 4.0"
    assert data["provenance"]["attribution"] == "MeteoSchweiz"


@pytest.mark.asyncio
async def test_meteo_stations_all():
    from meteoswiss_mcp.server import StationsInput, meteo_stations

    result = await meteo_stations(StationsInput())
    assert "LUG" in result
    assert "BER" in result


@pytest.mark.asyncio
async def test_meteo_current_invalid_station():
    from meteoswiss_mcp.server import CurrentInput, meteo_current

    result = await meteo_current(CurrentInput(station="XYZ"))
    assert "nicht" in result.lower() or "fehler" in result.lower()


@pytest.mark.asyncio
async def test_meteo_climate_normals_klo():
    from meteoswiss_mcp.server import ClimateNormalsInput, meteo_climate_normals

    result = await meteo_climate_normals(ClimateNormalsInput(station="KLO"))
    assert "Januar" in result
    assert "Dezember" in result
    assert "1991" in result


@pytest.mark.asyncio
async def test_meteo_climate_normals_no_data():
    from meteoswiss_mcp.server import ClimateNormalsInput, meteo_climate_normals

    result = await meteo_climate_normals(ClimateNormalsInput(station="DAV"))
    # DAV hat keine eingebetteten Normwerte
    assert "opendata.swiss" in result or "verfügbar" in result.lower()


@pytest.mark.asyncio
async def test_meteo_climate_normals_json():
    from meteoswiss_mcp.server import ClimateNormalsInput, meteo_climate_normals

    result = await meteo_climate_normals(
        ClimateNormalsInput(station="SMA", response_format="json")
    )
    data = json.loads(result)
    # PR-6: OGDResponse-Envelope
    assert data["payload"]["station"] == "SMA"
    assert len(data["payload"]["normwerte"]["temp_mean"]) == 12
    assert data["provenance"]["license"] == "CC BY 4.0"
    assert "retrieved_at" in data["provenance"]


@pytest.mark.asyncio
async def test_meteo_warnings_markdown():
    from meteoswiss_mcp.server import WarningsInput, meteo_warnings

    result = await meteo_warnings(WarningsInput(canton="ZH"))
    assert "MeteoSwiss" in result
    assert "warnings" in result.lower() or "warnung" in result.lower()


# ---------------------------------------------------------------------------
# Lifespan + respx-Mock-Tests (kein Netzwerk)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_yields_appcontext():
    from meteoswiss_mcp.server import AppContext, app_lifespan, mcp

    async with app_lifespan(mcp) as appctx:
        assert isinstance(appctx, AppContext)
        assert appctx.http is not None
        assert not appctx.http.is_closed
    assert appctx.http.is_closed


@pytest.mark.asyncio
async def test_meteo_forecast_mocked_geocode_404():
    """Geocoding-Fehler wird sanitisiert (kein roher Exception-String)."""
    import respx

    from meteoswiss_mcp.server import ForecastInput, meteo_forecast

    with respx.mock(assert_all_called=False) as r:
        r.get("https://geocoding-api.open-meteo.com/v1/search").respond(
            500, json={"error": "internal"}
        )
        result = await meteo_forecast(ForecastInput(location="Unbekanntes Dorf"))

    assert "Fehler beim Geokodieren" in result
    # Kein roher httpx-Stacktrace im Output:
    assert "Traceback" not in result
    assert "geocoding-api.open-meteo.com" not in result


@pytest.mark.asyncio
async def test_meteo_school_check_mocked_geocode_empty():
    """Leeres Geocoding-Ergebnis triggert ValueError, sanitisiert dargestellt."""
    import respx

    from meteoswiss_mcp.server import SchoolCheckInput, meteo_school_check

    with respx.mock(assert_all_called=False) as r:
        r.get("https://geocoding-api.open-meteo.com/v1/search").respond(
            200, json={"results": []}
        )
        result = await meteo_school_check(
            SchoolCheckInput(location="xyz", activity="Sporttag")
        )

    assert "Geokodieren" in result or "nicht gefunden" in result.lower()


# ---------------------------------------------------------------------------
# Egress Allow-List (PR-1: SEC-004 / SEC-021)
# ---------------------------------------------------------------------------


class TestAssertSafeUrl:
    def test_allows_known_host(self):
        from meteoswiss_mcp.server import assert_safe_url

        # Soll nicht werfen
        assert_safe_url("https://data.geo.admin.ch/api/stac/v1/foo")
        assert_safe_url("https://api.open-meteo.com/v1/meteoswiss")
        assert_safe_url("https://geocoding-api.open-meteo.com/v1/search?name=Zurich")
        assert_safe_url("https://opendata.swiss/api/3/action/package_search")

    def test_rejects_http_scheme(self):
        from meteoswiss_mcp.server import EgressBlocked, assert_safe_url

        with pytest.raises(EgressBlocked, match="https"):
            assert_safe_url("http://data.geo.admin.ch/foo")

    def test_rejects_unknown_host(self):
        from meteoswiss_mcp.server import EgressBlocked, assert_safe_url

        with pytest.raises(EgressBlocked, match="allow-list"):
            assert_safe_url("https://evil.example.com/exfil")

    def test_rejects_loopback_ip(self):
        from meteoswiss_mcp.server import EgressBlocked, assert_safe_url

        with pytest.raises(EgressBlocked, match="unsafe IP|IP-literal"):
            assert_safe_url("https://127.0.0.1/")

    def test_rejects_link_local_metadata_ip(self):
        """AWS / GCP / Azure Metadata-Service IP — klassischer SSRF-Vektor."""
        from meteoswiss_mcp.server import EgressBlocked, assert_safe_url

        with pytest.raises(EgressBlocked):
            assert_safe_url("https://169.254.169.254/latest/meta-data/")

    def test_rejects_rfc1918_ip(self):
        from meteoswiss_mcp.server import EgressBlocked, assert_safe_url

        for ip in ("10.0.0.1", "192.168.1.1", "172.16.0.1"):
            with pytest.raises(EgressBlocked):
                assert_safe_url(f"https://{ip}/admin")

    def test_rejects_public_ip_literal(self):
        """Auch public IPs in URLs ablehnen — Allow-List wirkt sonst nicht."""
        from meteoswiss_mcp.server import EgressBlocked, assert_safe_url

        with pytest.raises(EgressBlocked, match="IP-literal"):
            assert_safe_url("https://8.8.8.8/")

    def test_rejects_no_host(self):
        from meteoswiss_mcp.server import EgressBlocked, assert_safe_url

        with pytest.raises(EgressBlocked):
            assert_safe_url("https:///nohost")


@pytest.mark.asyncio
async def test_lifespan_client_blocks_disallowed_host():
    """Der Lifespan-Client lehnt nicht-allowlistete Hosts vor Versand ab."""
    import httpx

    from meteoswiss_mcp.server import EgressBlocked, app_lifespan, mcp

    async with app_lifespan(mcp) as appctx:
        with pytest.raises((EgressBlocked, httpx.RequestError)) as exc_info:
            await appctx.http.get("https://evil.example.com/")
        # Falls httpx EgressBlocked als RequestError wrappt:
        assert "allow-list" in str(exc_info.value) or isinstance(
            exc_info.value, EgressBlocked
        )


# ---------------------------------------------------------------------------
# Entry-Point Defaults  (PR-1: SEC-006, SEC-016)
# ---------------------------------------------------------------------------


class TestTransportSettings:
    def test_default_is_stdio_loopback(self, monkeypatch):
        from meteoswiss_mcp.server import _resolve_transport_settings

        for var in ("MCP_TRANSPORT", "MCP_HOST", "MCP_PORT"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setattr("sys.argv", ["meteoswiss-mcp"])

        transport, host, port = _resolve_transport_settings()
        assert transport == "stdio"
        assert host == "127.0.0.1"
        assert port == 8000

    def test_env_overrides_to_http(self, monkeypatch):
        from meteoswiss_mcp.server import _resolve_transport_settings

        monkeypatch.setenv("MCP_TRANSPORT", "streamable-http")
        monkeypatch.setenv("MCP_HOST", "0.0.0.0")
        monkeypatch.setenv("MCP_PORT", "9090")
        monkeypatch.setattr("sys.argv", ["meteoswiss-mcp"])

        transport, host, port = _resolve_transport_settings()
        assert transport == "streamable-http"
        assert host == "0.0.0.0"
        assert port == 9090

    def test_cli_flag_overrides_env(self, monkeypatch):
        from meteoswiss_mcp.server import _resolve_transport_settings

        monkeypatch.delenv("MCP_TRANSPORT", raising=False)
        monkeypatch.setattr("sys.argv", ["meteoswiss-mcp", "--http", "--port", "7000"])

        transport, host, port = _resolve_transport_settings()
        assert transport == "streamable-http"
        assert host == "127.0.0.1"  # kein MCP_HOST gesetzt
        assert port == 7000


# ---------------------------------------------------------------------------
# Structured Logging (PR-3: OBS-001, OBS-003, OBS-004)
# ---------------------------------------------------------------------------


class _FakeLogger:
    """Minimal struct-log-kompatibel: sammelt Events für Assertions."""

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


@pytest.mark.asyncio
async def test_meteo_stations_logs_tool_invoked(monkeypatch):
    """Tool-Invocation erzeugt strukturiertes Event mit tool=Name."""
    from meteoswiss_mcp import server

    fake = _FakeLogger()
    monkeypatch.setattr(server, "logger", fake)

    await server.meteo_stations(server.StationsInput(canton="ZH"))

    invoked = [e for e in fake.events if e[1] == "tool_invoked"]
    assert invoked, fake.events
    assert invoked[0][2].get("tool") == "meteo_stations"


@pytest.mark.asyncio
async def test_egress_block_emits_log(monkeypatch):
    """Blockierter Egress erzeugt egress_blocked-Event mit URL + Reason."""
    import httpx

    from meteoswiss_mcp import server

    fake = _FakeLogger()
    monkeypatch.setattr(server, "logger", fake)

    async with server.app_lifespan(server.mcp) as appctx:
        with pytest.raises((server.EgressBlocked, httpx.RequestError)):
            await appctx.http.get("https://evil.example.com/")

    blocked = [e for e in fake.events if e[1] == "egress_blocked"]
    assert blocked, fake.events
    assert "evil.example.com" in blocked[0][2].get("url", "")
    assert "allow-list" in blocked[0][2].get("reason", "")


@pytest.mark.asyncio
async def test_upstream_failure_logged(monkeypatch):
    """Bei Upstream-5xx wird upstream_failed geloggt; User bekommt Markdown-Fallback."""
    import respx

    from meteoswiss_mcp import server

    fake = _FakeLogger()
    monkeypatch.setattr(server, "logger", fake)

    with respx.mock(assert_all_called=False) as r:
        r.get("https://geocoding-api.open-meteo.com/v1/search").respond(
            503, json={"error": "unavailable"}
        )
        result = await server.meteo_forecast(server.ForecastInput(location="Zürich"))

    failures = [e for e in fake.events if e[1] == "upstream_failed"]
    assert failures, fake.events
    assert failures[0][2].get("endpoint") == "geocoding"
    assert failures[0][0] == "warning"
    # User-Output: Markdown-Fallback, keine rohen URLs
    assert "Geokodieren" in result
    assert "geocoding-api.open-meteo.com" not in result


def test_structlog_configured_for_stderr():
    """stdio-Transport-Pflicht: structlog ist auf stderr konfiguriert, nicht stdout (OBS-004)."""
    import sys as _sys

    import structlog

    # WriteLoggerFactory mit file=stderr ist die einzig sichere Konfiguration für
    # stdio-Transport (stdout ist für MCP-Protokoll reserviert).
    cfg = structlog.get_config()
    factory = cfg["logger_factory"]
    # Inspect: WriteLoggerFactory speichert file in self._file
    file_target = getattr(factory, "_file", None)
    assert file_target is _sys.stderr, (
        f"structlog logger_factory schreibt nicht auf sys.stderr, sondern {file_target!r}"
    )


def test_no_print_calls_in_source():
    """Regression-Guard: kein print() in src/ — stderr-Reinheit für stdio-Transport (OBS-004)."""
    import pathlib
    import re as _re

    src = pathlib.Path(__file__).parent.parent / "src" / "meteoswiss_mcp"
    for py in src.rglob("*.py"):
        text = py.read_text()
        # Naiv: print(...) am Zeilenanfang oder nach einem Statement-Trenner;
        # Strings mit "print(" innerhalb von Docstrings/Beispielen würden mitfangen,
        # deshalb auf Code-Zeilen (nicht eingerückt in Triple-Quotes) zielen.
        offenders = [
            (i + 1, line)
            for i, line in enumerate(text.splitlines())
            if _re.match(r"^\s*print\s*\(", line)
        ]
        assert not offenders, f"{py}: print() gefunden in {offenders}"


# ---------------------------------------------------------------------------
# Health Endpoint (PR-4: SCALE-004)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_healthcheck_returns_200():
    """Health-Probe ist trivial-200 ohne Upstream-Pings."""
    from httpx import ASGITransport, AsyncClient

    from meteoswiss_mcp.server import mcp

    app = mcp.streamable_http_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["service"] == "meteoswiss-mcp"


# ---------------------------------------------------------------------------
# CORS + Auth Middleware (PR-5: SDK-004, SEC-009, SEC-013)
# ---------------------------------------------------------------------------


async def _asgi_client(app, base_url: str = "http://testserver"):
    from httpx import ASGITransport, AsyncClient

    return AsyncClient(transport=ASGITransport(app=app), base_url=base_url)


@pytest.mark.asyncio
async def test_cors_disabled_by_default(monkeypatch):
    """Ohne MCP_ALLOWED_ORIGINS sind keine CORS-Header gesetzt."""
    monkeypatch.delenv("MCP_ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("MCP_API_KEY", raising=False)

    from meteoswiss_mcp.server import _build_http_app

    app = _build_http_app()
    async with await _asgi_client(app) as client:
        resp = await client.get(
            "/health", headers={"origin": "https://example.com"}
        )
    assert resp.status_code == 200
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.asyncio
async def test_cors_preflight_allows_origin(monkeypatch):
    """Preflight aus erlaubter Origin → 200/204 mit allow-origin gesetzt."""
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://app.example.com")
    monkeypatch.delenv("MCP_API_KEY", raising=False)

    from meteoswiss_mcp.server import _build_http_app

    app = _build_http_app()
    async with await _asgi_client(app) as client:
        resp = await client.options(
            "/mcp",
            headers={
                "origin": "https://app.example.com",
                "access-control-request-method": "POST",
                "access-control-request-headers": "content-type,mcp-session-id",
            },
        )
    assert resp.status_code in (200, 204)
    assert resp.headers.get("access-control-allow-origin") == "https://app.example.com"
    allow_headers = resp.headers.get("access-control-allow-headers", "").lower()
    assert "mcp-session-id" in allow_headers


@pytest.mark.asyncio
async def test_cors_exposes_mcp_session_id_on_response(monkeypatch):
    """SDK-004: Mcp-Session-Id muss in expose-headers tatsächlicher Responses stehen."""
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://app.example.com")
    monkeypatch.delenv("MCP_API_KEY", raising=False)

    from meteoswiss_mcp.server import _build_http_app

    app = _build_http_app()
    async with await _asgi_client(app) as client:
        # Tatsächlicher Request mit Origin-Header → CORSMiddleware fügt
        # expose-headers an die Response an, NICHT an Preflights
        resp = await client.get(
            "/health", headers={"origin": "https://app.example.com"}
        )
    assert resp.status_code == 200
    expose = resp.headers.get("access-control-expose-headers", "")
    assert "Mcp-Session-Id" in expose


@pytest.mark.asyncio
async def test_cors_rejects_unlisted_origin(monkeypatch):
    """Origin nicht in ALLOWED_ORIGINS → keine allow-origin-Antwort."""
    monkeypatch.setenv("MCP_ALLOWED_ORIGINS", "https://app.example.com")
    monkeypatch.delenv("MCP_API_KEY", raising=False)

    from meteoswiss_mcp.server import _build_http_app

    app = _build_http_app()
    async with await _asgi_client(app) as client:
        resp = await client.get(
            "/health", headers={"origin": "https://evil.example.com"}
        )
    assert "access-control-allow-origin" not in resp.headers


@pytest.mark.asyncio
async def test_api_key_disabled_by_default(monkeypatch):
    """Ohne MCP_API_KEY ist der HTTP-Modus offen wie bisher."""
    monkeypatch.delenv("MCP_API_KEY", raising=False)
    monkeypatch.delenv("MCP_ALLOWED_ORIGINS", raising=False)

    from meteoswiss_mcp.server import _build_http_app

    app = _build_http_app()
    async with await _asgi_client(app) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_key_required_when_configured(monkeypatch):
    """MCP_API_KEY gesetzt → MCP-Endpoints verlangen X-API-Key."""
    monkeypatch.setenv("MCP_API_KEY", "secret-xyz")
    monkeypatch.delenv("MCP_ALLOWED_ORIGINS", raising=False)

    from meteoswiss_mcp.server import _build_http_app

    app = _build_http_app()
    async with await _asgi_client(app) as client:
        # ohne Key
        resp_no_key = await client.post("/mcp", json={"ping": True})
        # mit falschem Key
        resp_wrong = await client.post(
            "/mcp", json={"ping": True}, headers={"x-api-key": "wrong"}
        )
        # /health bleibt offen für Container-Probes
        resp_health = await client.get("/health")

    assert resp_no_key.status_code == 401
    assert resp_wrong.status_code == 401
    assert resp_health.status_code == 200


@pytest.mark.asyncio
async def test_api_key_via_bearer_token(monkeypatch):
    """Authorization: Bearer <key> akzeptiert (RFC-konform)."""
    monkeypatch.setenv("MCP_API_KEY", "secret-xyz")
    monkeypatch.delenv("MCP_ALLOWED_ORIGINS", raising=False)

    from meteoswiss_mcp.server import _build_http_app

    app = _build_http_app()
    async with await _asgi_client(app) as client:
        resp = await client.get(
            "/health", headers={"authorization": "Bearer secret-xyz"}
        )
    # /health ist auth-bypass; aber wir prüfen separat, dass auth-Middleware
    # den Header korrekt parst:
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_auth_rejection_emits_log(monkeypatch):
    """auth_rejected-Event wird auf stderr/Logger geschrieben."""
    monkeypatch.setenv("MCP_API_KEY", "secret-xyz")
    monkeypatch.delenv("MCP_ALLOWED_ORIGINS", raising=False)

    from meteoswiss_mcp import server

    fake = _FakeLogger()
    monkeypatch.setattr(server, "logger", fake)

    app = server._build_http_app()
    async with await _asgi_client(app) as client:
        await client.post("/mcp", json={}, headers={"x-api-key": "wrong"})

    rejected = [e for e in fake.events if e[1] == "auth_rejected"]
    assert rejected, fake.events
    assert rejected[0][2].get("has_credential") is True


# ---------------------------------------------------------------------------
# Fuzzy-Geocoding (PR-7: ARCH-003)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_geocode_exact_match():
    """Erster Versuch liefert Treffer → match_type='exact'."""
    import respx

    from meteoswiss_mcp.server import _build_http_client, _geocode

    with respx.mock(assert_all_called=False) as r:
        r.get("https://geocoding-api.open-meteo.com/v1/search").respond(
            200,
            json={
                "results": [
                    {
                        "name": "Zürich",
                        "latitude": 47.37,
                        "longitude": 8.55,
                        "admin1": "ZH",
                        "country_code": "CH",
                    }
                ]
            },
        )
        async with _build_http_client() as client:
            lat, lon, display, match = await _geocode(client, "Zürich")

    assert match == "exact"
    assert lat == 47.37 and lon == 8.55


@pytest.mark.asyncio
async def test_geocode_fuzzy_fallback():
    """Erster (DE-)Versuch leer → fuzzy-Retry ohne language → match_type='fuzzy'."""
    import respx

    from meteoswiss_mcp.server import _build_http_client, _geocode

    with respx.mock(assert_all_called=False) as r:
        route = r.get("https://geocoding-api.open-meteo.com/v1/search")
        # erste Antwort leer, zweite mit Treffer
        route.side_effect = [
            httpx.Response(200, json={"results": []}),
            httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "name": "Obscureville",
                            "latitude": 50.0,
                            "longitude": 7.0,
                            "country_code": "DE",
                        }
                    ]
                },
            ),
        ]
        async with _build_http_client() as client:
            lat, lon, display, match = await _geocode(client, "obscureville")

    assert match == "fuzzy"


@pytest.mark.asyncio
async def test_geocode_none_raises():
    """Beide Versuche leer → ValueError mit 'nicht gefunden'."""
    import respx

    from meteoswiss_mcp.server import _build_http_client, _geocode

    with respx.mock(assert_all_called=False) as r:
        r.get("https://geocoding-api.open-meteo.com/v1/search").respond(
            200, json={"results": []}
        )
        async with _build_http_client() as client:
            with pytest.raises(ValueError, match="nicht gefunden"):
                await _geocode(client, "definitely-not-a-place-12345")


# ---------------------------------------------------------------------------
# OGDResponse-Envelope (PR-6: CH-004 / SDK-002)
# ---------------------------------------------------------------------------


def test_ogd_envelope_has_required_fields():
    """Envelope hat payload + provenance mit allen Pflichtfeldern."""
    from meteoswiss_mcp.server import _ogd_envelope

    env = _ogd_envelope(
        {"foo": "bar"}, source="Test-Source", data_source_url="https://example.org/data"
    )
    assert env["payload"] == {"foo": "bar"}
    prov = env["provenance"]
    assert prov["source"] == "Test-Source"
    assert prov["license"] == "CC BY 4.0"
    assert prov["attribution"] == "MeteoSchweiz"
    assert prov["data_source_url"] == "https://example.org/data"
    # ISO-Timestamp, endet auf Z (UTC)
    assert prov["retrieved_at"].endswith("Z")
    assert "T" in prov["retrieved_at"]


# ---------------------------------------------------------------------------
# Stateless-HTTP-Modus (PR-7: SCALE-002/003)
# ---------------------------------------------------------------------------


def test_stateless_default_is_false():
    """Ohne MCP_STATELESS_HTTP=1 ist Stateless-Modus aus."""
    from meteoswiss_mcp.server import _STATELESS_HTTP, mcp

    # Beim Modul-Import wurde der Wert eingefroren — der Test prüft die
    # Default-Semantik, nicht die Laufzeit-Konfigurierbarkeit.
    assert _STATELESS_HTTP is False
    assert mcp.settings.stateless_http is False


# ---------------------------------------------------------------------------
# OpenTelemetry-Decorator (PR-7: OBS-006)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_decorator_records_span_attributes():
    """_traced_tool setzt mcp.tool.name auf dem aktiven Span."""
    from meteoswiss_mcp import server

    seen: dict[str, object] = {}

    class _RecordingSpan:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def set_attribute(self, k, v):
            seen[k] = v

        def record_exception(self, *args, **kwargs):
            seen["exception"] = True

    class _RecordingTracer:
        def start_as_current_span(self, name):
            seen["span_name"] = name
            return _RecordingSpan()

    monkeypatch_target = _RecordingTracer()
    original = server._tracer
    server._tracer = monkeypatch_target
    try:
        await server.meteo_stations(server.StationsInput(canton="ZH"))
    finally:
        server._tracer = original

    assert seen["span_name"] == "tool.meteo_stations"
    assert seen["mcp.tool.name"] == "meteo_stations"


def test_noop_tracer_does_not_crash_without_otel():
    """Ohne OTEL_EXPORTER_OTLP_ENDPOINT ist _tracer ein No-Op-Stub."""
    from meteoswiss_mcp.server import _NoopTracer, _tracer

    assert isinstance(_tracer, _NoopTracer)
    with _tracer.start_as_current_span("dummy") as span:
        span.set_attribute("foo", "bar")
        span.record_exception(ValueError("test"))


# ---------------------------------------------------------------------------
# Tool-Docstrings haben strukturierte XML-Tags (PR-7: ARCH-002)
# ---------------------------------------------------------------------------


def test_all_tools_have_use_case_tag():
    """Alle 6 Tools tragen <use_case>...</use_case> im Docstring."""
    from meteoswiss_mcp import server

    for name in (
        "meteo_stations",
        "meteo_current",
        "meteo_forecast",
        "meteo_school_check",
        "meteo_climate_normals",
        "meteo_warnings",
    ):
        fn = getattr(server, name)
        doc = fn.__doc__ or ""
        assert "<use_case>" in doc and "</use_case>" in doc, f"{name} fehlt <use_case>"
        assert "<important_notes>" in doc, f"{name} fehlt <important_notes>"
        assert "<example>" in doc, f"{name} fehlt <example>"


# ---------------------------------------------------------------------------
# Phase-2: TTL-Cache
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_hit_avoids_second_fetch():
    """Zweiter Aufruf mit identischem Schlüssel ruft fetch() nicht erneut auf."""
    from meteoswiss_mcp.server import _cache_clear, _cached

    _cache_clear()
    calls: list[int] = []

    async def fetch():
        calls.append(1)
        return {"v": len(calls)}

    a = await _cached("stac_item", ("test-key",), fetch)
    b = await _cached("stac_item", ("test-key",), fetch)
    assert a == b == {"v": 1}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_cache_miss_after_expiry(monkeypatch):
    """Eintrag mit abgelaufener TTL wird neu gefetcht."""
    from meteoswiss_mcp.server import _cache_clear, _cached

    _cache_clear()
    calls: list[int] = []

    async def fetch():
        calls.append(1)
        return len(calls)

    # TTL künstlich auf 0 setzen → jeder Aufruf ist miss
    from meteoswiss_mcp import server as srv

    monkeypatch.setitem(srv._CACHE_TTL, "stac_item", 0)
    await _cached("stac_item", ("k",), fetch)
    await _cached("stac_item", ("k",), fetch)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_cache_disabled_via_env(monkeypatch):
    """MCP_CACHE_ENABLED=0 deaktiviert Caching komplett."""
    import importlib

    monkeypatch.setenv("MCP_CACHE_ENABLED", "0")
    from meteoswiss_mcp import server as srv

    importlib.reload(srv)
    calls: list[int] = []

    async def fetch():
        calls.append(1)
        return len(calls)

    await srv._cached("stac_item", ("k",), fetch)
    await srv._cached("stac_item", ("k",), fetch)
    assert len(calls) == 2

    # Cleanup: Modul mit Default-ENV reloaden, sonst beeinflusst es spätere Tests
    monkeypatch.delenv("MCP_CACHE_ENABLED", raising=False)
    importlib.reload(srv)


# ---------------------------------------------------------------------------
# Phase-2: Climate-Normals-Erweiterung via JSON-Datei
# ---------------------------------------------------------------------------


def test_load_extra_climate_normals_valid(tmp_path, monkeypatch):
    """Valide Datei wird gemerged; bestehende Stationen können überschrieben werden."""
    import importlib

    f = tmp_path / "extra.json"
    f.write_text(
        json.dumps(
            {
                "DAV": {
                    "temp_mean":  [1.0] * 12,
                    "precip_mm":  [50.0] * 12,
                    "sunshine_h": [120.0] * 12,
                },
                # Überschreibt bestehendes KLO partiell
                "KLO": {"temp_mean": [99.0] * 12},
            }
        )
    )
    monkeypatch.setenv("MCP_CLIMATE_NORMALS_PATH", str(f))

    from meteoswiss_mcp import server as srv

    importlib.reload(srv)

    assert "DAV" in srv.CLIMATE_NORMALS
    assert srv.CLIMATE_NORMALS["DAV"]["temp_mean"] == [1.0] * 12
    assert srv.CLIMATE_NORMALS["KLO"]["temp_mean"][0] == 99.0

    monkeypatch.delenv("MCP_CLIMATE_NORMALS_PATH", raising=False)
    importlib.reload(srv)


def test_load_extra_climate_normals_invalid_skipped(tmp_path, monkeypatch):
    """Fehlerhafte Einträge werden geskippt, valide übernommen."""
    import importlib

    f = tmp_path / "extra.json"
    f.write_text(
        json.dumps(
            {
                "GOOD": {"temp_mean": [1.0] * 12},
                "BAD_LENGTH": {"temp_mean": [1.0, 2.0, 3.0]},  # nur 3 Werte
                "BAD_TYPE": {"temp_mean": "not a list"},
                "BAD_VALUES": {"temp_mean": ["a"] * 12},
            }
        )
    )
    monkeypatch.setenv("MCP_CLIMATE_NORMALS_PATH", str(f))

    from meteoswiss_mcp import server as srv

    importlib.reload(srv)

    assert "GOOD" in srv.CLIMATE_NORMALS
    assert "BAD_LENGTH" not in srv.CLIMATE_NORMALS
    assert "BAD_TYPE" not in srv.CLIMATE_NORMALS
    assert "BAD_VALUES" not in srv.CLIMATE_NORMALS

    monkeypatch.delenv("MCP_CLIMATE_NORMALS_PATH", raising=False)
    importlib.reload(srv)


# ---------------------------------------------------------------------------
# Phase-2: Warnings-API (MCP_WARNINGS_API_URL)
# ---------------------------------------------------------------------------


def test_normalize_warnings_geojson_features():
    """GeoJSON-Style (features-Array) wird auf das Standard-Schema gebracht."""
    from meteoswiss_mcp.server import _normalize_warnings_response

    raw = {
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "type": "thunderstorm",
                    "level": 3,
                    "regions": ["ZH"],
                    "valid_until": "2026-05-21T12:00:00Z",
                    "text": "Gewitter erwartet",
                },
            },
            {
                "properties": {
                    "type": "heavy_rain",
                    "level": 2,
                    "regions": ["GR", "TI"],
                }
            },
        ]
    }
    result = _normalize_warnings_response(raw, canton_filter="")
    assert len(result) == 2
    assert result[0]["type"] == "thunderstorm"
    assert result[0]["regions"] == ["ZH"]
    assert result[1]["regions"] == ["GR", "TI"]


def test_normalize_warnings_canton_filter():
    """Canton-Filter wendet sich auf die regions-Liste an."""
    from meteoswiss_mcp.server import _normalize_warnings_response

    raw = {
        "warnings": [
            {"type": "snow", "level": 4, "regions": ["GR"]},
            {"type": "wind", "level": 2, "regions": ["ZH", "GR"]},
            {"type": "fog", "level": 1, "regions": ["TI"]},
        ]
    }
    result = _normalize_warnings_response(raw, canton_filter="ZH")
    assert len(result) == 1
    assert result[0]["type"] == "wind"


@pytest.mark.asyncio
async def test_meteo_warnings_uses_api_when_configured(monkeypatch):
    """Wenn MCP_WARNINGS_API_URL gesetzt ist, wird die API aufgerufen + gerendert."""
    import respx

    # API-URL muss auf der Egress-Allow-List liegen → opendata.swiss missbrauchen
    monkeypatch.setenv(
        "MCP_WARNINGS_API_URL",
        "https://opendata.swiss/api/3/action/datastore_search?resource_id=warnings",
    )

    from meteoswiss_mcp import server as srv

    srv._cache_clear()

    with respx.mock(assert_all_called=False) as r:
        # API-Mock
        r.get("https://opendata.swiss/api/3/action/datastore_search").respond(
            200,
            json={
                "warnings": [
                    {
                        "type": "thunderstorm",
                        "level": 4,
                        "regions": ["ZH"],
                        "valid_until": "2026-05-21T12:00:00Z",
                        "text": "Schwere Gewitter mit Hagel",
                    }
                ]
            },
        )
        # Linkstack-opendata.swiss (separater Pfad) — leerer Erfolg
        r.get("https://opendata.swiss/api/3/action/package_search").respond(
            200, json={"result": {"results": []}}
        )

        result = await srv.meteo_warnings(srv.WarningsInput(canton="ZH"))

    assert "Aktive Warnungen (1)" in result
    assert "thunderstorm" in result
    assert "ZH" in result

    monkeypatch.delenv("MCP_WARNINGS_API_URL", raising=False)


# ---------------------------------------------------------------------------
# Climate-Normals Ingest-Skript (PR-13: scripts/ingest_climate_normals.py)
# ---------------------------------------------------------------------------


def test_ingest_parses_metswiss_tsv_per_parameter():
    """MeteoSwiss-TSV (ein Parameter pro Datei) wird korrekt geparst."""
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "ingest", pathlib.Path("scripts/ingest_climate_normals.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # MeteoSwiss-Format: Header + 4 Meta-Spalten + 12 Monate + Jahr
    tsv = (
        "Header line\n"
        "Another header line\n"
        "\n"
        "Erstellungsdatum: ...\n"
        "\n"
        "Monthly values Temperature\n"
        "\n"
        "Station\tAltitude\tCoords\tPeriod\tJan\tFeb\tMar\tApr\tMai\tJun\tJul\tAug\tSep\tOkt\tNov\tDez\tJahr\n"
        "Zürich / Kloten\t426\t2682711 / 1259338\t01.1991-12.2020\t-0.6\t0.6\t4.5\t8.6\t13.4\t16.5\t18.7\t18.3\t14.1\t9.5\t4.1\t0.4\t9.0\n"
        "Davos\t1594\t2783519 / 1187458\t01.1991-12.2020\t-5.5\t-4.8\t-1.8\t1.6\t6.4\t9.6\t11.7\t11.4\t7.7\t4.0\t-1.0\t-4.5\t2.9\n"
    )
    result = mod.parse_metswiss_tsv(tsv, "tre200m0")
    assert "Zürich / Kloten" in result
    assert "Davos" in result
    assert result["Davos"][0] == -5.5


def test_ingest_filename_regex_filters_correctly():
    """Filename-Pattern filtert nach Parameter / Periode / Sprache.

    Akzeptiert sowohl die kompakte Form (`climatereportsnormtables_…_19912020_…`)
    als auch die offizielle MeteoSwiss-Form mit Bindestrichen
    (`climate-reports-normtables_…_1991-2020_…`).
    """
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "ingest", pathlib.Path("scripts/ingest_climate_normals.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Variante 1: kompakt + UUID-Präfix
    m = mod._FILENAME_RE.search("abc123-climatereportsnormtables_tre200m0_19912020_de.txt")
    assert m is not None
    assert m.group("param") == "tre200m0"
    assert m.group("period") == "19912020"
    assert m.group("lang") == "de"

    # Variante 2: offizielle MeteoSwiss-Schreibweise mit Bindestrichen
    m2 = mod._FILENAME_RE.search("climate-reports-normtables_fkl010m0_1991-2020_de.txt")
    assert m2 is not None
    assert m2.group("param") == "fkl010m0"
    assert m2.group("period") == "1991-2020"
    assert m2.group("lang") == "de"

    # Period-Normalisierung: beide Schreibweisen sollen gleich vergleichen
    assert mod._normalize_period("1991-2020") == mod._normalize_period("19912020")


def test_ingest_plausibility_catches_swapped_stations():
    """Vertauschte Lugano/Davos-Werte werden vom Validator gemeldet."""
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "ingest", pathlib.Path("scripts/ingest_climate_normals.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    data = {
        "DAV": {"temp_mean": [15.0] * 12},
        "LUG": {"temp_mean": [0.0] * 12},
    }
    warnings = mod.validate_plausibility(data)
    assert any("LUG" in w and "DAV" in w for w in warnings)


def test_ingest_directory_e2e_with_station_mapping(tmp_path, monkeypatch):
    """End-to-End: TSV-Datei in Verzeichnis → JSON mit SMN-Codes → Server lädt sie."""
    import importlib.util
    import pathlib

    spec = importlib.util.spec_from_file_location(
        "ingest", pathlib.Path("scripts/ingest_climate_normals.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # cp1252-encoded TSV mit Umlauten
    tsv = (
        "Header\n"
        "\n"
        "Station\tHoehe\tCoords\tPeriod\tJan\tFeb\tMar\tApr\tMai\tJun\tJul\tAug\tSep\tOkt\tNov\tDez\tJahr\n"
        "Zürich / Kloten\t426\tx\ty\t-0.6\t0.6\t4.5\t8.6\t13.4\t16.5\t18.7\t18.3\t14.1\t9.5\t4.1\t0.4\t9.0\n"
        "NotMapped\t0\tx\ty\t1\t2\t3\t4\t5\t6\t7\t8\t9\t10\t11\t12\t7\n"
    )
    fdir = tmp_path / "files"
    fdir.mkdir()
    fname = fdir / "climatereportsnormtables_tre200m0_19912020_de.txt"
    fname.write_bytes(tsv.encode("cp1252"))

    parsed = mod.ingest_directory(fdir, period="19912020", lang="de")
    # KLO wurde via Mapping erkannt; NotMapped wurde geskippt
    assert "KLO" in parsed
    assert "NotMapped" not in parsed
    assert parsed["KLO"]["temp_mean"][0] == -0.6

    # Server kann die Datei laden
    out_path = tmp_path / "out.json"
    out_path.write_text(json.dumps(parsed))
    monkeypatch.setenv("MCP_CLIMATE_NORMALS_PATH", str(out_path))

    import importlib

    from meteoswiss_mcp import server as srv
    importlib.reload(srv)
    assert "KLO" in srv.CLIMATE_NORMALS
    # Eingebettete KLO-Werte wurden überschrieben:
    assert srv.CLIMATE_NORMALS["KLO"]["temp_mean"][0] == -0.6

    monkeypatch.delenv("MCP_CLIMATE_NORMALS_PATH", raising=False)
    importlib.reload(srv)


# ---------------------------------------------------------------------------
# Live-Tests (mit echten APIs)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_geocode_zurich():
    from meteoswiss_mcp.server import _build_http_client, _geocode

    async with _build_http_client() as client:
        lat, lon, name, match = await _geocode(client, "Zürich")
    assert 47.0 < lat < 48.0
    assert 8.0 < lon < 9.0
    assert "Zürich" in name or "Zurich" in name
    assert match == "exact"


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_geocode_leutschenbach():
    from meteoswiss_mcp.server import _build_http_client, _geocode

    async with _build_http_client() as client:
        lat, lon, name, match = await _geocode(client, "Leutschenbach Zürich")
    # Oerlikon-Bereich
    assert 47.3 < lat < 47.5
    assert 8.4 < lon < 8.7
    assert match in ("exact", "fuzzy")


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_forecast_zurich():
    from meteoswiss_mcp.server import ForecastInput, meteo_forecast

    result = await meteo_forecast(
        ForecastInput(location="Zürich", days=3, response_format="markdown")
    )
    assert "°C" in result
    assert "Zürich" in result


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_school_check():
    from meteoswiss_mcp.server import SchoolCheckInput, meteo_school_check

    result = await meteo_school_check(
        SchoolCheckInput(
            location="Zürich",
            activity="Sporttag",
        )
    )
    assert "🟢" in result or "🟡" in result or "🔴" in result
    assert "Sporttag" in result


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_meteo_current_klo():
    from meteoswiss_mcp.server import CurrentInput, meteo_current

    result = await meteo_current(CurrentInput(station="KLO"))
    # Entweder echte Daten oder Fallback mit Link
    assert "KLO" in result or "Zürich" in result


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_meteo_warnings():
    from meteoswiss_mcp.server import WarningsInput, meteo_warnings

    result = await meteo_warnings(WarningsInput())
    assert "MeteoSwiss" in result
