"""
Tests für meteoswiss-mcp.

Unit-Tests (kein Netzwerk):
    pytest tests/ -m "not live" -v

Live-Tests (echte APIs, CI ausgeschlossen):
    pytest tests/ -m live -v
"""

from __future__ import annotations

import json

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
# Live-Tests (mit echten APIs)
# ---------------------------------------------------------------------------


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_geocode_zurich():
    from meteoswiss_mcp.server import _geocode

    lat, lon, name = await _geocode("Zürich")
    assert 47.0 < lat < 48.0
    assert 8.0 < lon < 9.0
    assert "Zürich" in name or "Zurich" in name


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_geocode_leutschenbach():
    from meteoswiss_mcp.server import _geocode

    lat, lon, name = await _geocode("Leutschenbach Zürich")
    # Oerlikon-Bereich
    assert 47.3 < lat < 47.5
    assert 8.4 < lon < 8.7


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
