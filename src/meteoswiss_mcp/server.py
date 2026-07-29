"""
MeteoSwiss MCP Server

MCP-Server für Schweizer Wetter- und Klimadaten von MeteoSwiss.
Bietet 6 Tools in 3 thematischen Clustern:

  Beobachtungen (2): meteo_stations, meteo_current
  Prognosen     (2): meteo_forecast, meteo_school_check
  Klimatologie  (2): meteo_climate_normals, meteo_warnings

Datenquellen:
- BGDI STAC API (data.geo.admin.ch): SwissMetNet-Bodenbeobachtungen
- Open-Meteo (api.open-meteo.com): MeteoSwiss ICON-CH1/CH2-EPS Prognosen
- Open-Meteo Geocoding: Ortsnamens-Auflösung
- opendata.swiss: MeteoSwiss-Datenkatalog
- MeteoSwiss App-Backend (app-prod-ws.meteoswiss-app.ch): aktive amtliche
  Wetterwarnungen (öffentlich, ohne Auth; meteo_warnings)

Alle Daten: öffentlich, keine Authentifizierung erforderlich.
Lizenz: Creative Commons BY 4.0 (MeteoSwiss Open Government Data).

Anker-Demo:
  «Wie war das Wetter beim Schulhaus Leutschenbach gestern?»
  → meteo_current(station='REH') kombiniert mit swiss-environment-mcp
"""

from __future__ import annotations

import asyncio
import csv
import io
import ipaddress
import json
import logging
import os
import re
import sys
import time as _time
from asyncio import Lock as _AsyncioLock
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog
from mcp.server.mcpserver import Context, MCPServer
from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Structured Logging (PR-3: OBS-001, OBS-003, OBS-004)
# ---------------------------------------------------------------------------
#
# Wichtig für stdio-Transport: alle Logs gehen auf stderr — stdout ist
# ausschliesslich für das MCP-JSON-RPC-Protokoll reserviert. structlog wird
# einmal modul-global konfiguriert (idempotent via cache_logger_on_first_use).

_LOG_LEVEL = os.environ.get("MCP_LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    stream=sys.stderr,
    format="%(message)s",
)

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, _LOG_LEVEL, logging.INFO)
    ),
    logger_factory=structlog.WriteLoggerFactory(file=sys.stderr),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("meteoswiss_mcp")


# ---------------------------------------------------------------------------
# OpenTelemetry-Tracing (PR-7: OBS-006) — opt-in via OTEL_EXPORTER_OTLP_ENDPOINT
# ---------------------------------------------------------------------------
#
# Aktivierung in Render / Container:
#     pip install meteoswiss-mcp[otel]
#     OTEL_EXPORTER_OTLP_ENDPOINT=https://collector.example.com
#     OTEL_SERVICE_NAME=meteoswiss-mcp
#
# Ohne ENV bleibt _tracer ein No-Op-Stub (kein Performance-Overhead, keine
# Pflicht-Dependency). Tools rufen `_tracer.start_as_current_span(...)`
# unverändert auf — der Stub akzeptiert die Signatur und macht nichts.


class _NoopSpan:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set_attribute(self, *args, **kwargs):
        pass

    def record_exception(self, *args, **kwargs):
        pass


class _NoopTracer:
    def start_as_current_span(self, *args, **kwargs):
        return _NoopSpan()


_tracer: Any = _NoopTracer()


def _traced_tool(name: str):
    """Wrappt einen async Tool-Handler in einen OTel-Span.

    Span-Attribute (OBS-006-Schema):
        mcp.tool.name
        mcp.tool.result.is_error
    """
    import functools

    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            with _tracer.start_as_current_span(f"tool.{name}") as span:
                span.set_attribute("mcp.tool.name", name)
                try:
                    return await fn(*args, **kwargs)
                except Exception as exc:
                    span.set_attribute("mcp.tool.result.is_error", True)
                    span.record_exception(exc)
                    raise

        return wrapper

    return decorator

if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
    try:
        from opentelemetry import trace as _ot_trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        _resource = Resource.create(
            {"service.name": os.environ.get("OTEL_SERVICE_NAME", "meteoswiss_mcp")}
        )
        _provider = TracerProvider(resource=_resource)
        _provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        _ot_trace.set_tracer_provider(_provider)
        _tracer = _ot_trace.get_tracer("meteoswiss_mcp")
        # httpx-Calls automatisch instrumentieren (alle 4 Tool-Endpoints)
        HTTPXClientInstrumentor().instrument()
        logger.info("otel_initialized", endpoint=os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"])
    except ImportError:
        logger.warning(
            "otel_disabled",
            reason="opentelemetry deps missing — install meteoswiss-mcp[otel]",
        )

# ---------------------------------------------------------------------------
# Konstanten
# ---------------------------------------------------------------------------

STAC_BASE = "https://data.geo.admin.ch/api/stac/v1"
SMN_COLLECTION = "ch.meteoschweiz.ogd-smn"
OPEN_METEO_BASE = "https://api.open-meteo.com/v1/meteoswiss"
GEOCODING_BASE = "https://geocoding-api.open-meteo.com/v1/search"

# SwissMetNet-Stationen: Auswahl mit Relevanz für Schulen / städtische Planung
# Koordinaten: WGS84, Höhe in m ü. M.
SMN_STATIONS: dict[str, dict[str, Any]] = {
    # Kanton Zürich
    "KLO": {"name": "Zürich/Kloten (Flughafen)", "lat": 47.4802, "lon": 8.5364, "alt": 436, "canton": "ZH"},
    "SMA": {"name": "Zürich/MeteoSchweiz", "lat": 47.3783, "lon": 8.5651, "alt": 556, "canton": "ZH"},
    "REH": {"name": "Zürich/Affoltern", "lat": 47.4297, "lon": 8.5121, "alt": 444, "canton": "ZH"},
    "REC": {"name": "Zürich/Reckenholz (MeteoSchweiz)", "lat": 47.4524, "lon": 8.5147, "alt": 443, "canton": "ZH"},
    "WAE": {"name": "Wädenswil", "lat": 47.2203, "lon": 8.6839, "alt": 485, "canton": "ZH"},
    "TAE": {"name": "Tänikon (Agroscope)", "lat": 47.4771, "lon": 8.9033, "alt": 539, "canton": "TG"},
    # Kanton Bern
    "BER": {"name": "Bern/Zollikofen", "lat": 46.9907, "lon": 7.4649, "alt": 552, "canton": "BE"},
    "INT": {"name": "Interlaken", "lat": 46.6655, "lon": 7.8706, "alt": 577, "canton": "BE"},
    # Kanton Basel
    "BAS": {"name": "Basel/Binningen", "lat": 47.5404, "lon": 7.5836, "alt": 317, "canton": "BS"},
    # Kanton Luzern
    "LUZ": {"name": "Luzern", "lat": 47.0359, "lon": 8.3010, "alt": 454, "canton": "LU"},
    # Kanton St. Gallen
    "STG": {"name": "St. Gallen", "lat": 47.4238, "lon": 9.3951, "alt": 775, "canton": "SG"},
    # Kanton Graubünden
    "DAV": {"name": "Davos (Wolfgang)", "lat": 46.8133, "lon": 9.8444, "alt": 1594, "canton": "GR"},
    "CHU": {"name": "Chur", "lat": 46.8697, "lon": 9.5309, "alt": 556, "canton": "GR"},
    # Kanton Wallis
    "SIO": {"name": "Sitten/Sion", "lat": 46.2171, "lon": 7.3296, "alt": 482, "canton": "VS"},
    # Kanton Tessin
    "LUG": {"name": "Lugano", "lat": 46.0044, "lon": 8.9608, "alt": 273, "canton": "TI"},
    # Kanton Genf
    "GVE": {"name": "Genf/Cointrin", "lat": 46.2483, "lon": 6.1289, "alt": 411, "canton": "GE"},
    # Kanton Waadt
    "PUY": {"name": "Payerne", "lat": 46.8117, "lon": 6.9453, "alt": 491, "canton": "VD"},
    # Bergstationen
    "JUN": {"name": "Jungfraujoch", "lat": 46.5475, "lon": 7.9856, "alt": 3571, "canton": "BE"},
    "SAE": {"name": "Säntis", "lat": 47.2495, "lon": 9.3437, "alt": 2501, "canton": "SG"},
    "PIL": {"name": "Pilatus", "lat": 46.9793, "lon": 8.2526, "alt": 2106, "canton": "OW"},
}

# WMO-Wettercodes (Deutsch)
WMO_CODES_DE: dict[int, str] = {
    0: "Klar",
    1: "Überwiegend klar",
    2: "Teilweise bewölkt",
    3: "Bedeckt",
    45: "Nebel",
    48: "Gefrierender Nebel",
    51: "Leichter Nieselregen",
    53: "Mässiger Nieselregen",
    55: "Starker Nieselregen",
    56: "Leichter gefrierender Nieselregen",
    57: "Starker gefrierender Nieselregen",
    61: "Leichter Regen",
    63: "Mässiger Regen",
    65: "Starker Regen",
    66: "Leichter gefrierender Regen",
    67: "Starker gefrierender Regen",
    71: "Leichter Schneefall",
    73: "Mässiger Schneefall",
    75: "Starker Schneefall",
    77: "Schneekristalle",
    80: "Leichte Regenschauer",
    81: "Mässige Regenschauer",
    82: "Starke Regenschauer",
    85: "Leichte Schneeschauer",
    86: "Starke Schneeschauer",
    95: "Gewitter",
    96: "Gewitter mit leichtem Hagel",
    99: "Gewitter mit schwerem Hagel",
}

# SMN CSV-Parameter: Kürzel → menschenlesbarer Name + Einheit
SMN_PARAMS: dict[str, dict[str, str]] = {
    "tre200s0": {"name": "Temperatur 2 m", "unit": "°C"},
    "rre150z0": {"name": "Niederschlag (10 min)", "unit": "mm"},
    "sre000z0": {"name": "Sonnenscheindauer (10 min)", "unit": "min"},
    "fkl010z0": {"name": "Windgeschwindigkeit", "unit": "m/s"},
    "dkl010z0": {"name": "Windrichtung", "unit": "°"},
    "fu3010z0": {"name": "Windböe", "unit": "m/s"},
    "ure200s0": {"name": "Relative Luftfeuchte", "unit": "%"},
    "prestas0": {"name": "Luftdruck (Stationsdruckniveau)", "unit": "hPa"},
    "prestah0": {"name": "Luftdruck (reduziert auf Meeresniveau)", "unit": "hPa"},
}

# Schwellenwerte für Schulaktivitäten im Freien
SCHOOL_THRESHOLDS: dict[str, Any] = {
    "temp_min_c": 5.0,
    "temp_max_c": 33.0,
    "precip_max_mm": 1.5,
    "wind_max_kmh": 50.0,
    "uv_warning": 6,      # UV-Index ab dem Sonnenschutz empfohlen wird
    "good_wmo_codes": {0, 1, 2},
    "marginal_wmo_codes": {3, 45},
    "bad_wmo_codes": {
        48, 51, 53, 55, 56, 57,
        61, 63, 65, 66, 67,
        71, 73, 75, 77,
        80, 81, 82, 85, 86,
        95, 96, 99,
    },
}

# ---------------------------------------------------------------------------
# Egress Allow-List (PR-1: SEC-004 SSRF, SEC-021 Egress-Control)
# ---------------------------------------------------------------------------

# Exakte Host-Whitelist für alle ausgehenden HTTP-Calls. Jeder Request
# (inklusive Redirect-Follow-Ups) wird vor dem Versand gegen diese Liste
# geprüft — siehe `_validate_request_hook` unten.
ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "data.geo.admin.ch",
        "api.open-meteo.com",
        "geocoding-api.open-meteo.com",
        "opendata.swiss",
        # MeteoSwiss App-Backend (undokumentierte, aber öffentliche JSON-API des
        # offiziellen MeteoSwiss-Apps) — einzige Live-Quelle für aggregierte
        # Wetterwarnungen bis die OGD-Warnings-REST-API verfügbar ist.
        "app-prod-ws.meteoswiss-app.ch",
    }
)


class EgressBlocked(ValueError):
    """Wird geworfen, wenn ein Request gegen die Allow-List verstösst."""


def assert_safe_url(url: str) -> None:
    """Validiert eine ausgehende URL.

    Hebt `EgressBlocked` wenn:
    - Schema nicht `https`
    - Host nicht in ALLOWED_HOSTS
    - Host ist IP-Literal (Allow-List wirkt sonst nicht; SSRF-Vektor)
    - Host ist private/loopback/link-local/reserved IP

    Der Check ist defense-in-depth gegen SEC-004 (SSRF) und SEC-021 (Egress).
    Anwendung pro Request via httpx event_hooks — schliesst Redirect-Targets ein.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise EgressBlocked(f"only https allowed, got {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise EgressBlocked(f"URL has no host: {url!r}")
    # IP-Literale grundsätzlich ablehnen — Allow-List arbeitet hostnamebasiert
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise EgressBlocked(f"unsafe IP host: {ip}")
        raise EgressBlocked(f"IP-literal hosts not allowed: {ip}")
    if host not in ALLOWED_HOSTS:
        raise EgressBlocked(f"host not in allow-list: {host!r}")


async def _validate_request_hook(request: httpx.Request) -> None:
    """httpx event_hook: validiert URL VOR jedem Request (inkl. Redirect-Follows)."""
    try:
        assert_safe_url(str(request.url))
    except EgressBlocked as exc:
        # Security-relevantes Event — sichtbar im SIEM/Log
        logger.warning(
            "egress_blocked",
            url=str(request.url),
            method=request.method,
            reason=str(exc),
        )
        raise


# ---------------------------------------------------------------------------
# TTL-Cache (Phase 2: reduziert Upstream-Last, asyncio-safe)
# ---------------------------------------------------------------------------
#
# Minimaler in-memory Cache. Bewusst keine extra Dependency:
# - Schlüssel ist ein Tuple aus Endpoint-Name + Params (Hashable).
# - Value enthält fetched_at (ISO-Timestamp) + payload.
# - Wenn Eintrag stale ist, wird er beim Zugriff entfernt und der Caller
#   refetcht. asyncio.Lock pro Schlüssel verhindert thundering-herd.
#
# Per-Endpoint-TTLs aus ENV überschreibbar; Defaults sind konservativ
# (= "wenig schneller, niemals zu alt").

_CACHE_TTL = {
    "stac_item":      int(os.environ.get("MCP_CACHE_TTL_STAC", "300")),       # 5 min
    "open_meteo":     int(os.environ.get("MCP_CACHE_TTL_OPEN_METEO", "600")), # 10 min
    "geocoding":      int(os.environ.get("MCP_CACHE_TTL_GEOCODING", "3600")), # 1 h
    "opendata_swiss": int(os.environ.get("MCP_CACHE_TTL_OPENDATA", "3600")),  # 1 h
    "warnings_api":   int(os.environ.get("MCP_CACHE_TTL_WARNINGS", "300")),   # 5 min
    "stac_climate":   int(os.environ.get("MCP_CACHE_TTL_STAC_CLIMATE", "86400")),  # 24 h
}
_CACHE_ENABLED = os.environ.get("MCP_CACHE_ENABLED", "1") == "1"

_cache_store: dict[tuple, tuple[float, Any]] = {}
_cache_locks: dict[tuple, _AsyncioLock] = {}


def _cache_lock(key: tuple) -> _AsyncioLock:
    lock = _cache_locks.get(key)
    if lock is None:
        lock = _AsyncioLock()
        _cache_locks[key] = lock
    return lock


async def _cached(category: str, key: tuple, fetch):
    """Liefert gecachten Wert oder ruft `fetch()` (async) auf und cached das Ergebnis.

    `key` ist ein zur category gehöriges Tuple, das den Request eindeutig
    identifiziert (z.B. ("stac_item", "klo")).
    """
    if not _CACHE_ENABLED:
        return await fetch()

    ttl = _CACHE_TTL.get(category, 300)
    full_key = (category, *key)
    now = _time.time()

    entry = _cache_store.get(full_key)
    if entry is not None:
        expires_at, value = entry
        if expires_at > now:
            logger.debug("cache_hit", category=category)
            return value
        _cache_store.pop(full_key, None)

    async with _cache_lock(full_key):
        # Double-checked: anderer Coroutine könnte gerade gefüllt haben
        entry = _cache_store.get(full_key)
        if entry is not None:
            expires_at, value = entry
            if expires_at > now:
                return value

        value = await fetch()
        _cache_store[full_key] = (now + ttl, value)
        logger.debug("cache_miss", category=category, ttl=ttl)
        return value


def _cache_clear() -> None:
    """Leert den gesamten Cache — primär für Tests."""
    _cache_store.clear()
    _cache_locks.clear()


# ---------------------------------------------------------------------------
# MeteoSwiss App-Backend: aggregierte Wetterwarnungen
# ---------------------------------------------------------------------------
#
# Der offizielle MeteoSwiss-App-Server (`app-prod-ws.meteoswiss-app.ch`) liefert
# unter `/v1/plzDetail?plz=<PLZ6>` neben Wetter/Prognose auch das Feld
# `warnings` — die aktiven amtlichen Warnungen für die Warnregion der PLZ.
# Es gibt (Stand 2026-07) keinen landesweiten Sammel-Endpoint, deshalb wird pro
# Kanton eine repräsentative Kantonshauptort-PLZ abgefragt und aggregiert.
#
# Schema pro Warnung (empirisch verifiziert 2026-07-26):
#   warnType   int  — Gefahrentyp (Mapping s.u.; via natural-hazards.ch-Slug
#                      gegengeprüft: 7=Hitze, 10=Waldbrand bestätigt)
#   warnLevel  int  — 1..5 (grün→dunkelrot)
#   regionId   int  — MeteoSwiss-Warnregion-ID
#   validFrom  int  — Epoch-Millis
#   text/htmlText   — lokalisierter Warntext (via Accept-Language)
#   outlook    bool — True = Vorausschau, noch nicht aktiv
#   links      list — offizielle Handlungsempfehlungen
#
# Diese Quelle ist das App-Backend, nicht die (noch nicht existente)
# OGD-Warnings-REST-API — undokumentiert, aber öffentlich und ohne Auth.

MS_APP_BASE = "https://app-prod-ws.meteoswiss-app.ch/v1"

# warnType-Code → (de, fr, it, en). 7 (Hitze) und 10 (Waldbrand) sind gegen die
# in den `links` referenzierten natural-hazards.ch-Slugs verifiziert; die
# übrigen folgen der etablierten MeteoSwiss-Warntyp-Nummerierung. Unbekannte
# Codes fallen auf den Slug bzw. "warnType <n>" zurück (siehe _warn_type_label).
WARN_TYPE_LABELS: dict[int, dict[str, str]] = {
    1: {"de": "Wind", "fr": "Vent", "it": "Vento", "en": "Wind"},
    2: {"de": "Gewitter", "fr": "Orages", "it": "Temporali", "en": "Thunderstorms"},
    3: {"de": "Regen", "fr": "Pluie", "it": "Pioggia", "en": "Rain"},
    4: {"de": "Schnee", "fr": "Neige", "it": "Neve", "en": "Snow"},
    5: {
        "de": "Strassenglätte",
        "fr": "Verglas",
        "it": "Strade ghiacciate",
        "en": "Slippery roads",
    },
    6: {"de": "Frost", "fr": "Gel", "it": "Gelo", "en": "Frost"},
    7: {"de": "Hitzewelle", "fr": "Canicule", "it": "Canicola", "en": "Heat wave"},
    8: {"de": "Hochwasser", "fr": "Crues", "it": "Piene", "en": "Flood"},
    9: {"de": "Lawinen", "fr": "Avalanches", "it": "Valanghe", "en": "Avalanches"},
    10: {
        "de": "Waldbrand",
        "fr": "Feux de forêt",
        "it": "Incendi boschivi",
        "en": "Forest fire",
    },
    11: {"de": "Erdbeben", "fr": "Séisme", "it": "Terremoto", "en": "Earthquake"},
}

# natural-hazards.ch-URL-Slug → warnType (Fallback-Auflösung für unbekannte Codes)
_SLUG_TO_WARN_TYPE: dict[str, int] = {
    "wind": 1,
    "thunderstorm": 2,
    "thunderstorms": 2,
    "rain": 3,
    "snow": 4,
    "snowfall": 4,
    "slipperiness": 5,
    "slippery-roads": 5,
    "frost": 6,
    "heat-wave": 7,
    "flood": 8,
    "floods": 8,
    "avalanches": 9,
    "avalanche": 9,
    "forest-fire": 10,
    "earthquakes": 11,
    "earthquake": 11,
}

WARN_LEVEL_LABELS: dict[int, dict[str, str]] = {
    1: {"de": "Keine/gering", "fr": "Nul/faible", "it": "Nullo/debole", "en": "None/minor"},
    2: {"de": "Gering", "fr": "Faible", "it": "Debole", "en": "Minor"},
    3: {"de": "Mässig", "fr": "Modéré", "it": "Moderato", "en": "Moderate"},
    4: {"de": "Stark", "fr": "Fort", "it": "Forte", "en": "Severe"},
    5: {"de": "Sehr stark", "fr": "Très fort", "it": "Molto forte", "en": "Very severe"},
}

# Kanton → repräsentative Kantonshauptort-PLZ (6-stellig: 4-stellige PLZ + "00").
# Für die landesweite Aggregation und den Kantons-Filter. Bewusst je genau eine
# PLZ pro Kanton — die App-API ist PLZ- (Warnregion-)basiert; der Hauptort deckt
# die bevölkerungsreichste Warnregion ab (Einschränkung dokumentiert).
CANTON_CAPITAL_PLZ: dict[str, int] = {
    "ZH": 800100,  # Zürich
    "BE": 301100,  # Bern
    "LU": 600300,  # Luzern
    "UR": 646000,  # Altdorf
    "SZ": 643000,  # Schwyz
    "OW": 606000,  # Sarnen
    "NW": 637000,  # Stans
    "GL": 875000,  # Glarus
    "ZG": 630000,  # Zug
    "FR": 170000,  # Fribourg
    "SO": 450000,  # Solothurn
    "BS": 400100,  # Basel
    "BL": 441000,  # Liestal
    "SH": 820000,  # Schaffhausen
    "AR": 910000,  # Herisau
    "AI": 905000,  # Appenzell
    "SG": 900000,  # St. Gallen
    "GR": 700000,  # Chur
    "AG": 500000,  # Aarau
    "TG": 850000,  # Frauenfeld
    "TI": 650000,  # Bellinzona
    "VD": 100300,  # Lausanne
    "VS": 195000,  # Sion
    "NE": 200000,  # Neuchâtel
    "GE": 120100,  # Genève
    "JU": 280000,  # Delémont
}

_WARN_LANGS = frozenset({"de", "fr", "it", "en"})


def _warn_type_label(warn_type: Any, links: Any, lang: str) -> str:
    """Löst einen warnType-Code zu einem lesbaren Label auf.

    Primär via `WARN_TYPE_LABELS`; bei unbekanntem Code Fallback auf den
    natural-hazards.ch-Slug aus `links`; sonst "warnType <n>".
    """
    labels = WARN_TYPE_LABELS.get(warn_type) if isinstance(warn_type, int) else None
    if labels is None and isinstance(links, list):
        for link in links:
            url = link.get("url", "") if isinstance(link, dict) else ""
            for slug, code in _SLUG_TO_WARN_TYPE.items():
                if f"/{slug}.html" in url:
                    labels = WARN_TYPE_LABELS.get(code)
                    break
            if labels is not None:
                break
    if labels is not None:
        return labels.get(lang) or labels.get("en") or labels.get("de")
    return f"warnType {warn_type}"


def _epoch_millis_to_iso(value: Any) -> str | None:
    """Wandelt Epoch-Millisekunden in einen ISO-8601-UTC-String."""
    if not isinstance(value, (int, float)):
        return None
    from datetime import UTC, datetime

    try:
        return datetime.fromtimestamp(value / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, OverflowError, OSError):
        return None


def _normalize_app_warning(raw: Any, lang: str) -> dict[str, Any] | None:
    """Normalisiert eine einzelne App-API-Warnung auf ein stabiles Schema."""
    if not isinstance(raw, dict):
        return None
    warn_type = raw.get("warnType")
    links = raw.get("links") or []
    text = (raw.get("text") or raw.get("htmlText") or "").strip()
    level = raw.get("warnLevel")
    return {
        "type_code": warn_type,
        "type_label": _warn_type_label(warn_type, links, lang),
        "level": level,
        "level_label": (
            WARN_LEVEL_LABELS.get(level, {}).get(lang)
            or WARN_LEVEL_LABELS.get(level, {}).get("en")
            if isinstance(level, int)
            else None
        ),
        "region_id": raw.get("regionId"),
        "valid_from": _epoch_millis_to_iso(raw.get("validFrom")),
        "outlook": bool(raw.get("outlook")),
        "text": text,
        "link": next(
            (link.get("url") for link in links if isinstance(link, dict) and link.get("url")),
            None,
        ),
    }


async def _fetch_app_warnings(
    client: httpx.AsyncClient, plz6: int, lang: str
) -> list[dict[str, Any]]:
    """Ruft die Warnungen einer PLZ vom MeteoSwiss-App-Backend ab (gecacht)."""
    url = f"{MS_APP_BASE}/plzDetail?plz={plz6}"

    async def _do_fetch():
        resp = await client.get(url, headers={"Accept-Language": lang})
        resp.raise_for_status()
        data = resp.json()
        return data.get("warnings") or []

    raw_warnings = await _cached("warnings_api", (plz6, lang), _do_fetch)
    normalized = [_normalize_app_warning(w, lang) for w in raw_warnings]
    return [w for w in normalized if w is not None]


def _dedupe_warnings(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Entfernt Duplikate (gleicher Typ+Stufe+Region), sortiert nach Stufe desc."""
    seen: set[tuple] = set()
    unique: list[dict[str, Any]] = []
    for w in warnings:
        key = (w.get("type_code"), w.get("level"), w.get("region_id"), w.get("valid_from"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(w)
    unique.sort(key=lambda w: (w.get("level") or 0), reverse=True)
    return unique


async def _collect_app_warnings(
    client: httpx.AsyncClient, plz_list: list[int], lang: str
) -> tuple[list[dict[str, Any]], int]:
    """Aggregiert Warnungen über mehrere PLZ hinweg.

    Gibt (deduplizierte Warnungen, Anzahl fehlgeschlagener Abfragen) zurück.
    Einzelne Fehlschläge degradieren nicht den ganzen Aufruf.
    """
    results = await asyncio.gather(
        *(_fetch_app_warnings(client, plz, lang) for plz in plz_list),
        return_exceptions=True,
    )
    collected: list[dict[str, Any]] = []
    failures = 0
    for res in results:
        if isinstance(res, BaseException):
            failures += 1
            logger.warning(
                "upstream_failed",
                tool="meteo_warnings",
                endpoint="app_warnings",
                error_type=res.__class__.__name__,
            )
            continue
        collected.extend(res)
    return _dedupe_warnings(collected), failures


def _warning_table_row(w: dict[str, Any]) -> str:
    """Rendert eine App-Warnung als Markdown-Tabellenzeile (Detailansicht)."""
    level = w.get("level") or "–"
    level_label = w.get("level_label") or ""
    level_cell = f"{level} ({level_label})" if level_label else str(level)
    region = w.get("region_id") or "–"
    valid_from = w.get("valid_from") or "–"
    # Text auf eine Zeile + Länge begrenzen, Pipes escapen (Tabellen-sicher).
    text = " ".join((w.get("text") or "").split())[:90].replace("|", "/")
    return f"| {level_cell} | {w.get('type_label')} | {region} | {valid_from} | {text} |"


def _aggregate_warnings_by_type(warnings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gruppiert Warnungen nach Typ für die landesweite Übersicht.

    Pro Typ: höchste Stufe, Anzahl betroffener Regionen, ein Beispieltext.
    Sortiert nach höchster Stufe absteigend.
    """
    groups: dict[Any, dict[str, Any]] = {}
    for w in warnings:
        code = w.get("type_code")
        level = w.get("level") or 0
        g = groups.get(code)
        if g is None:
            g = {
                "type_code": code,
                "type_label": w.get("type_label"),
                "max_level": level,
                "region_ids": set(),
                "sample_text": " ".join((w.get("text") or "").split())[:70].replace("|", "/"),
            }
            groups[code] = g
        g["region_ids"].add(w.get("region_id"))
        if level > g["max_level"]:
            g["max_level"] = level
            if w.get("text"):
                g["sample_text"] = " ".join(w["text"].split())[:70].replace("|", "/")
    out: list[dict[str, Any]] = []
    for g in groups.values():
        out.append(
            {
                "type_code": g["type_code"],
                "type_label": g["type_label"],
                "max_level": g["max_level"],
                "max_level_label": (WARN_LEVEL_LABELS.get(g["max_level"], {}).get("de") or ""),
                "region_count": len(g["region_ids"]),
                "sample_text": g["sample_text"],
            }
        )
    out.sort(key=lambda g: g["max_level"], reverse=True)
    return out


def _normalize_warnings_response(
    raw: Any, canton_filter: str
) -> list[dict[str, Any]]:
    """Bringt unterschiedliche Warnings-API-Schemas auf ein gemeinsames Format.

    Erwartete Felder pro Warnung (best-effort über mehrere Schemata):
        type      — z.B. "thunderstorm" / "heavy_rain"
        level     — 1..5 (MeteoSwiss-Skala)
        valid_from / valid_until — ISO-Timestamps
        regions   — Liste Kantons-/Regions-Codes
        text      — kurze Beschreibung

    Akzeptierte Eingabe-Formen:
    - {"warnings": [...]}     — Standard-Schema (geplante MeteoSwiss-API)
    - {"features": [...]}     — GeoJSON-style (CAP-konform)
    - [...]                   — direkte Liste
    - {"items": [...]}        — STAC-style

    Unbekannte Felder werden als "extra" durchgereicht; nichts wird verworfen.
    """
    items: list[Any]
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = raw.get("warnings") or raw.get("features") or raw.get("items") or []
    else:
        items = []

    normalized: list[dict[str, Any]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        props = it.get("properties", it)  # GeoJSON-Features haben "properties"
        regions = (
            props.get("regions")
            or props.get("canton")
            or props.get("cantons")
            or []
        )
        if isinstance(regions, str):
            regions = [regions]
        regions_upper = [str(r).upper() for r in regions]

        if canton_filter and canton_filter not in regions_upper:
            continue

        normalized.append(
            {
                "type": props.get("type") or props.get("warning_type") or "unknown",
                "level": props.get("level") or props.get("severity"),
                "valid_from": props.get("valid_from") or props.get("from"),
                "valid_until": props.get("valid_until") or props.get("until"),
                "regions": regions_upper,
                "text": props.get("text") or props.get("description") or "",
                "extra": {
                    k: v
                    for k, v in props.items()
                    if k
                    not in {
                        "type",
                        "warning_type",
                        "level",
                        "severity",
                        "valid_from",
                        "from",
                        "valid_until",
                        "until",
                        "regions",
                        "canton",
                        "cantons",
                        "text",
                        "description",
                    }
                },
            }
        )
    return normalized


# ---------------------------------------------------------------------------
# Lifespan + HTTP-Client (PR-2: SDK-001, SDK-003, OBS-002)
# ---------------------------------------------------------------------------


@dataclass
class AppContext:
    """In Tools via `ctx.request_context.lifespan_context` verfügbar."""

    http: httpx.AsyncClient


def _build_http_client() -> httpx.AsyncClient:
    """Erstellt einen httpx.AsyncClient mit Allow-List-Validation + sicheren Defaults."""
    return httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        event_hooks={"request": [_validate_request_hook]},
    )


@asynccontextmanager
async def app_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    """Erstellt einen wiederverwendeten httpx.AsyncClient für die Server-Lebenszeit.

    Der Client führt vor jedem Request `_validate_request_hook` aus — auch bei
    Redirect-Follows. Das schliesst SEC-004 (SSRF) und SEC-021 (Egress-Control).
    follow_redirects=True bleibt aktiv, weil BGDI-STAC-Assets auf data.geo.admin.ch
    selbst redirecten (innerhalb des Allow-List-Hosts).
    """
    async with _build_http_client() as http:
        yield AppContext(http=http)


@asynccontextmanager
async def _http_client(ctx: Context | None) -> AsyncIterator[httpx.AsyncClient]:
    """Liefert den Lifespan-Client wenn `ctx` gesetzt ist, sonst einen transienten.

    Der transiente Pfad existiert ausschliesslich für direkte Unit-Tests, die
    Tools ohne MCPServer-Runtime aufrufen.
    """
    if ctx is not None:
        try:
            yield ctx.request_context.lifespan_context.http
            return
        except (AttributeError, LookupError):
            pass
    async with _build_http_client() as client:
        yield client


def _sanitize_error(exc: BaseException) -> str:
    """Reduziert eine Exception-Message auf Typ + erste Zeile, ohne URLs/Headers."""
    raw = str(exc).splitlines()[0] if str(exc) else ""
    # httpx schreibt typisch " for url '<url>'" hinten dran — entfernen
    cleaned = re.sub(r"\s*for url\s+['\"]?\S+['\"]?", "", raw)
    # Beliebige verbleibende URLs strippen (defense-in-depth)
    cleaned = re.sub(r"https?://\S+", "<url>", cleaned)
    cleaned = cleaned.strip()
    if not cleaned:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {cleaned[:120]}"


# ---------------------------------------------------------------------------
# Server-Initialisierung
# ---------------------------------------------------------------------------

# Stateless-Modus (PR-7: SCALE-002 / SCALE-003) erlaubt Multi-Replica-Deploys
# ohne Sticky-Session-Layer. Jeder HTTP-Request erzeugt eine neue MCP-Session,
# was für read-only-Server wie diesen kein Datenverlust-Problem ist.
_STATELESS_HTTP = os.environ.get("MCP_STATELESS_HTTP", "0") == "1"

mcp = MCPServer(
    "meteoswiss_mcp",
    lifespan=app_lifespan,
    instructions="""
MCP-Server für Schweizer Wetter- und Klimadaten von MeteoSwiss.
Bietet Zugriff auf SwissMetNet-Beobachtungen (10-Minuten-Intervall),
MeteoSwiss ICON-Prognosen (bis 16 Tage) und Klimanormwerte.

Wichtige Tools:
- meteo_stations: Übersicht aller eingebetteten SMN-Stationen
- meteo_current: Aktuelle Beobachtungen einer Station (STAC-Download)
- meteo_forecast: Wetterprognose für Koordinaten oder Ortsname
- meteo_school_check: Eignungsprüfung für Schulveranstaltungen im Freien
- meteo_climate_normals: Monatliche Klimanormwerte einer Station
- meteo_warnings: Aktuelle MeteoSwiss-Warnungen

Zeitzone: Europe/Zurich (CET/CEST).
Datenquelle: MeteoSwiss OGD (data.geo.admin.ch) + Open-Meteo.
Lizenz: Creative Commons BY 4.0 – Quelle: MeteoSchweiz.

Synergien:
- swiss-environment-mcp → kombiniere Luftqualität + Wetter (Leutschenbach-Beispiel)
- zurich-opendata-mcp → Schulhausstandorte → Wetterprognose
""",
)

# ---------------------------------------------------------------------------
# Response-Envelope (PR-6: CH-004 Per-Response-Attribution, SDK-002)
# ---------------------------------------------------------------------------


def _ogd_envelope(
    payload: Any,
    *,
    source: str,
    data_source_url: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Wickelt eine JSON-Antwort in ein konsistentes OGD-Provenance-Envelope.

    Felder:
      payload          — die eigentlichen Daten
      provenance       — Per-Response-Attribution für CC BY 4.0
        source         — z.B. "MeteoSwiss SwissMetNet via BGDI STAC"
        license        — immer "CC BY 4.0" für OGD-Quellen
        attribution    — "MeteoSchweiz" (Pflicht laut DSGVO/Lizenz)
        retrieved_at   — ISO-Timestamp des Tool-Aufrufs
        data_source_url — falls vorhanden, Direkt-URL der Quelle
    """
    from datetime import UTC, datetime

    env: dict[str, Any] = {
        "payload": payload,
        "provenance": {
            "source": source,
            "license": "CC BY 4.0",
            "attribution": "MeteoSchweiz",
            "retrieved_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data_source_url": data_source_url,
        },
    }
    if extra:
        env.update(extra)
    return env


# ---------------------------------------------------------------------------
# Pydantic-Eingabemodelle
# ---------------------------------------------------------------------------


class ResponseFormat(StrEnum):
    MARKDOWN = "markdown"
    JSON = "json"


class StationsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    canton: str = Field(
        default="",
        description="Kantonskürzel zum Filtern (z.B. 'ZH', 'BE') – leer = alle Kantone",
        max_length=2,
    )
    response_format: ResponseFormat = Field(
        default=ResponseFormat.MARKDOWN,
        description="Ausgabeformat: 'markdown' (lesbar) oder 'json' (strukturiert)",
    )


class CurrentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    station: str = Field(
        ...,
        description=(
            "SMN-Stationskürzel, 3 Buchstaben (z.B. 'KLO' für Zürich/Kloten, "
            "'SMA' für Zürich/MeteoSchweiz, 'REH' für Zürich/Affoltern). "
            "→ meteo_stations für vollständige Liste."
        ),
        min_length=2,
        max_length=5,
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)

    @field_validator("station")
    @classmethod
    def upper_station(cls, v: str) -> str:
        return v.upper().strip()


class ForecastInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    location: str = Field(
        default="",
        description=(
            "Ortsname (z.B. 'Zürich', 'Luzern', 'Schulhaus Leutschenbach Zürich'). "
            "Wird automatisch geokodiert. Alternativ: lat/lon verwenden."
        ),
        max_length=200,
    )
    latitude: float | None = Field(
        default=None,
        description="Breitengrad (WGS84), z.B. 47.3769 für Zürich. Überschreibt 'location'.",
        ge=-90.0,
        le=90.0,
    )
    longitude: float | None = Field(
        default=None,
        description="Längengrad (WGS84), z.B. 8.5417 für Zürich. Überschreibt 'location'.",
        ge=-180.0,
        le=180.0,
    )
    days: int = Field(
        default=7,
        description="Prognosetage (1–16). Standard: 7 Tage.",
        ge=1,
        le=16,
    )
    hourly: bool = Field(
        default=False,
        description="True = Stundenwerte zurückgeben; False (Standard) = nur Tageswerte.",
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


class SchoolCheckInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    location: str = Field(
        default="Zürich",
        description=(
            "Ort der geplanten Aussenaktivität (z.B. 'Schulhaus Leutschenbach Zürich', "
            "'Sportanlage Heerenschürli Zürich', 'Zürich'). Wird geokodiert."
        ),
        max_length=200,
    )
    date: str = Field(
        default="",
        description=(
            "Gewünschtes Datum im Format YYYY-MM-DD (z.B. '2025-06-15'). "
            "Leer = nächsten 7 Tage anzeigen."
        ),
        max_length=10,
    )
    activity: str = Field(
        default="Aussenunterricht",
        description=(
            "Art der Aktivität, z.B. 'Sporttag', 'Aussenunterricht', "
            "'Schulreise', 'Schulsport'. Beeinflusst die Empfehlung."
        ),
        max_length=60,
    )


class ClimateNormalsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")

    station: str = Field(
        ...,
        description=(
            "SMN-Stationskürzel (z.B. 'KLO', 'BER', 'LUG'). "
            "→ meteo_stations für vollständige Liste."
        ),
        min_length=2,
        max_length=5,
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)

    @field_validator("station")
    @classmethod
    def upper_station(cls, v: str) -> str:
        return v.upper().strip()


class WarningsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    canton: str = Field(
        default="",
        description="Kantonskürzel zum Filtern (z.B. 'ZH') – leer = ganze Schweiz",
        max_length=2,
    )
    plz: str = Field(
        default="",
        description=(
            "4-stellige Schweizer PLZ für ortsgenaue Warnungen (z.B. '8001'). "
            "Präziser als 'canton'; leer = kanton- bzw. landesweite Aggregation."
        ),
        max_length=4,
    )
    language: str = Field(
        default="de",
        description="Sprache der Warntexte: 'de', 'fr', 'it' oder 'en'.",
        max_length=2,
    )
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)

    @field_validator("plz")
    @classmethod
    def _digits_only(cls, v: str) -> str:
        v = v.strip()
        if v and not v.isdigit():
            raise ValueError("plz muss numerisch sein (z.B. '8001')")
        return v

    @field_validator("language")
    @classmethod
    def _known_lang(cls, v: str) -> str:
        v = v.strip().lower() or "de"
        if v not in _WARN_LANGS:
            raise ValueError("language muss 'de', 'fr', 'it' oder 'en' sein")
        return v


# ---------------------------------------------------------------------------
# API-Hilfsfunktionen
# ---------------------------------------------------------------------------


def _wmo_description(code: int) -> str:
    return WMO_CODES_DE.get(code, f"WMO-Code {code}")


def _school_verdict(
    temp: float,
    precip: float,
    wind: float,
    wmo: int,
    uv: float,
) -> tuple[str, str]:
    """Gibt (Ampel-Emoji, Beschreibung) zurück."""
    is_bad_weather = wmo in SCHOOL_THRESHOLDS["bad_wmo_codes"]
    is_too_cold = temp < SCHOOL_THRESHOLDS["temp_min_c"]
    is_too_hot = temp > SCHOOL_THRESHOLDS["temp_max_c"]
    is_too_windy = wind > SCHOOL_THRESHOLDS["wind_max_kmh"]
    is_too_wet = precip > SCHOOL_THRESHOLDS["precip_max_mm"]
    uv_high = uv >= SCHOOL_THRESHOLDS["uv_warning"]

    blockers = []
    if is_bad_weather:
        blockers.append(f"Ungünstiges Wetter ({_wmo_description(wmo)})")
    if is_too_cold:
        blockers.append(f"Zu kalt ({temp:.1f} °C)")
    if is_too_hot:
        blockers.append(f"Zu heiss ({temp:.1f} °C – Hitzegefahr)")
    if is_too_windy:
        blockers.append(f"Zu windig ({wind:.0f} km/h)")
    if is_too_wet:
        blockers.append(f"Zu viel Niederschlag ({precip:.1f} mm)")

    warnings = []
    if uv_high:
        warnings.append(f"UV-Index {uv:.0f} – Sonnenschutz obligatorisch")

    if blockers:
        return "🔴", "Nicht geeignet: " + "; ".join(blockers)
    if warnings or wmo in SCHOOL_THRESHOLDS["marginal_wmo_codes"]:
        note = "; ".join(warnings) if warnings else _wmo_description(wmo)
        return "🟡", f"Bedingt geeignet – {note}"
    return "🟢", "Geeignet für Aussenaktivitäten"


async def _geocode(
    client: httpx.AsyncClient, location: str
) -> tuple[float, float, str, str]:
    """Löst einen Ortsnamen in (lat, lon, display_name, match_type).

    match_type:
        "exact"  — erster Treffer der DE-Suche
        "fuzzy"  — Fallback ohne Sprache + count=5, dann bester Hit
        "none"   — keine Treffer (wirft ValueError, wie zuvor)

    ARCH-003: kein stilles «not found» mehr — bei Misserfolg wird mit relaxter
    Suche nachgehakt, bevor der Fehler eskaliert wird.

    Ergebnis ist gecached (TTL: MCP_CACHE_TTL_GEOCODING, default 1 h) — Orte
    bewegen sich selten.
    """

    async def _do_fetch():
        # Versuch 1: exakter Match auf Deutsch
        resp = await client.get(
            GEOCODING_BASE,
            params={"name": location, "count": 1, "language": "de", "format": "json"},
        )
        resp.raise_for_status()
        d = resp.json()
        rs = d.get("results", [])
        m = "exact"

        if not rs:
            # Versuch 2 (fuzzy): ohne language-Restriktion, mehrere Kandidaten
            resp2 = await client.get(
                GEOCODING_BASE,
                params={"name": location, "count": 5, "format": "json"},
            )
            resp2.raise_for_status()
            d = resp2.json()
            rs = d.get("results", [])
            m = "fuzzy"

        if not rs:
            raise ValueError(f"Ort '{location}' nicht gefunden.")

        r = rs[0]
        display = r.get("name", location)
        admin = r.get("admin1", "")
        country = r.get("country_code", "")
        if admin:
            display = f"{display}, {admin} ({country})"
        return float(r["latitude"]), float(r["longitude"]), display, m

    return await _cached("geocoding", (location.lower().strip(),), _do_fetch)


async def _fetch_open_meteo_forecast(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
    days: int,
    hourly: bool,
) -> dict[str, Any]:
    """Ruft MeteoSwiss ICON-Prognose von Open-Meteo ab.

    Gecached (TTL: MCP_CACHE_TTL_OPEN_METEO, default 10 min).
    """
    daily_vars = [
        "temperature_2m_max",
        "temperature_2m_min",
        "precipitation_sum",
        "precipitation_probability_max",
        "windspeed_10m_max",
        "windgusts_10m_max",
        "weathercode",
        "uv_index_max",
        "sunshine_duration",
        "sunrise",
        "sunset",
    ]
    params: dict[str, Any] = {
        "latitude": lat,
        "longitude": lon,
        "daily": ",".join(daily_vars),
        "forecast_days": days,
        "timezone": "Europe/Zurich",
    }
    if hourly:
        params["hourly"] = (
            "temperature_2m,precipitation,windspeed_10m,weathercode,"
            "cloudcover,uv_index,relative_humidity_2m"
        )

    async def _do_fetch():
        resp = await client.get(OPEN_METEO_BASE, params=params)
        resp.raise_for_status()
        return resp.json()

    # Cache-Key: gerundete Koordinaten + days + hourly
    # (Open-Meteo gibt für gleiche Stelle gleiche Daten zurück; sub-km-Drift
    # ist für Cache-Granularität irrelevant.)
    return await _cached(
        "open_meteo",
        (round(lat, 3), round(lon, 3), days, bool(hourly)),
        _do_fetch,
    )


async def _fetch_stac_now_csv(
    client: httpx.AsyncClient, station: str
) -> list[dict[str, str]]:
    """
    Lädt die neueste 10-Minuten-CSV einer SMN-Station via STAC API.
    Gibt die letzten Zeilen als Liste von Dictionaries zurück.

    Gecached (TTL: MCP_CACHE_TTL_STAC, default 5 min). MeteoSwiss-SMN-Daten
    werden alle 10 Minuten aktualisiert — 5 min Cache reduziert die Last,
    ohne dass die Daten zu stale werden.
    """
    station_lower = station.lower()

    async def _do_fetch():
        # STAC Item für die Station abrufen
        stac_item_url = (
            f"{STAC_BASE}/collections/{SMN_COLLECTION}/items/"
            f"ch.meteoschweiz.ogd-smn-{station_lower}"
        )
        resp = await client.get(stac_item_url)
        resp.raise_for_status()
        item = resp.json()

        # Asset-URL für die "now"-Datei finden (10-Minuten-Werte, neueste)
        assets = item.get("assets", {})
        now_url: str | None = None

        # Suche nach dem "now"-Asset (10-Minuten-Granularität)
        for _key, asset in assets.items():
            href = asset.get("href", "")
            if "/now/" in href and "_t_" in href and href.endswith(".csv"):
                now_url = href
                break

        # Fallback: erstes CSV-Asset nehmen
        if not now_url:
            for _key, asset in assets.items():
                href = asset.get("href", "")
                if href.endswith(".csv"):
                    now_url = href
                    break

        if not now_url:
            raise ValueError(
                f"Kein CSV-Asset für Station '{station}' in STAC gefunden."
            )

        resp_csv = await client.get(now_url)
        resp_csv.raise_for_status()
        return resp_csv.text

    content = await _cached("stac_item", (station_lower,), _do_fetch)

    # CSV parsen (MeteoSwiss nutzt Semikolon als Trennzeichen)
    lines = content.strip().splitlines()
    if len(lines) < 2:
        return []

    reader = csv.DictReader(io.StringIO(content), delimiter=";")
    rows = list(reader)
    return rows[-6:] if len(rows) >= 6 else rows  # letzte 6 Zeilen (= 1 Stunde)


def _format_smn_rows(rows: list[dict[str, str]], station_info: dict[str, Any]) -> str:
    """Formatiert SMN-CSV-Zeilen als Markdown-Tabelle."""
    if not rows:
        return "*Keine Daten verfügbar.*"

    latest = rows[-1]
    timestamp = latest.get("time", latest.get("Date", latest.get("datum", "–")))

    lines = [
        f"**Zeitstempel (UTC):** {timestamp}\n",
        "| Parameter | Wert | Einheit |",
        "|-----------|------|---------|",
    ]

    for code, meta in SMN_PARAMS.items():
        val = latest.get(code)
        if val and val not in ("-", "", "nan"):
            lines.append(f"| {meta['name']} | **{val}** | {meta['unit']} |")

    return "\n".join(lines)


# Monatliche Klimanormwerte 1991–2020 für ausgewählte Stationen (eingebettet)
# Quellen: MeteoSwiss Klimanormwerte 1991–2020
CLIMATE_NORMALS: dict[str, dict[str, list[float]]] = {
    "KLO": {
        "temp_mean":  [-0.6, 0.6, 4.5, 8.6, 13.4, 16.5, 18.7, 18.3, 14.1, 9.5, 4.1, 0.4],
        "precip_mm":  [61, 56, 66, 74, 100, 112, 99, 104, 81, 69, 72, 68],
        "sunshine_h": [60, 78, 127, 159, 191, 208, 229, 210, 162, 114, 65, 50],
    },
    "SMA": {
        "temp_mean":  [0.2, 1.4, 5.4, 9.6, 14.3, 17.3, 19.7, 19.3, 14.9, 10.3, 4.7, 1.2],
        "precip_mm":  [66, 60, 72, 79, 103, 118, 107, 112, 87, 73, 77, 73],
        "sunshine_h": [62, 81, 131, 163, 196, 213, 234, 217, 166, 116, 67, 52],
    },
    "BER": {
        "temp_mean":  [0.9, 2.0, 6.2, 10.0, 14.7, 17.7, 20.0, 19.5, 15.2, 10.5, 5.0, 1.6],
        "precip_mm":  [72, 64, 75, 80, 109, 120, 110, 118, 92, 75, 82, 78],
        "sunshine_h": [63, 82, 133, 164, 197, 213, 236, 219, 168, 118, 68, 52],
    },
    "LUG": {
        "temp_mean":  [3.8, 5.0, 9.4, 13.5, 18.1, 21.4, 24.0, 23.3, 18.8, 13.4, 7.8, 4.3],
        "precip_mm":  [60, 64, 100, 153, 195, 165, 122, 149, 172, 137, 116, 69],
        "sunshine_h": [108, 124, 167, 194, 228, 244, 277, 255, 202, 163, 103, 90],
    },
    "GVE": {
        "temp_mean":  [2.3, 3.5, 7.5, 11.4, 16.0, 19.1, 21.5, 20.9, 16.5, 11.7, 6.0, 2.8],
        "precip_mm":  [73, 65, 74, 68, 84, 82, 65, 78, 87, 81, 94, 91],
        "sunshine_h": [67, 88, 141, 174, 209, 228, 256, 235, 183, 133, 75, 59],
    },
}

MONTHS_DE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def _load_extra_climate_normals() -> dict[str, dict[str, list[float]]]:
    """Lädt zusätzliche Klimanormwerte aus einer JSON-Datei (MCP_CLIMATE_NORMALS_PATH).

    Format der JSON-Datei (gleich wie eingebettete CLIMATE_NORMALS):
        {
          "DAV": {
            "temp_mean":  [-5.0, ...],   # 12 Monatswerte
            "precip_mm":  [...],
            "sunshine_h": [...]
          },
          ...
        }

    Validation:
    - Werte müssen 12-elementige Listen sein
    - Pro Station mindestens "temp_mean" oder "precip_mm" oder "sunshine_h"
    - Fehlerhafte Einträge werden geloggt + übersprungen, nicht gefatalt

    Diese Datei ist die offizielle Erweiterungsstelle für Stationen über die
    5 eingebetteten hinaus. Quelle: MeteoSwiss Klimanormwerte 1991–2020,
    siehe https://opendata.swiss/de/dataset?q=meteoschweiz+klimanormwerte
    """
    path = os.environ.get("MCP_CLIMATE_NORMALS_PATH", "").strip()
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        logger.warning("climate_normals_file_missing", path=path)
        return {}
    except json.JSONDecodeError as exc:
        logger.warning(
            "climate_normals_file_invalid", path=path, error=str(exc)[:80]
        )
        return {}

    if not isinstance(raw, dict):
        logger.warning("climate_normals_file_invalid", reason="root must be object")
        return {}

    cleaned: dict[str, dict[str, list[float]]] = {}
    for station, values in raw.items():
        if not isinstance(values, dict):
            continue
        entry: dict[str, list[float]] = {}
        for key in ("temp_mean", "precip_mm", "sunshine_h"):
            v = values.get(key)
            if isinstance(v, list) and len(v) == 12 and all(
                isinstance(x, int | float) for x in v
            ):
                entry[key] = [float(x) for x in v]
        if entry:
            cleaned[station.upper()] = entry
        else:
            logger.warning(
                "climate_normals_station_skipped",
                station=station,
                reason="no_valid_monthly_arrays",
            )
    if cleaned:
        logger.info("climate_normals_loaded", path=path, stations=list(cleaned))
    return cleaned


# Eingebettet + ENV-Erweiterung mergen; Datei-Werte gewinnen bei Konflikten,
# damit der User korrigierte/aktualisierte Werte ohne Code-Patch ausrollen kann.
_CLIMATE_NORMALS_EXTRA = _load_extra_climate_normals()
CLIMATE_NORMALS = {**CLIMATE_NORMALS, **_CLIMATE_NORMALS_EXTRA}


# MeteoSwiss-NBCN-Stationscode-Mapping (siehe scripts/ingest_climate_normals.py).
# Wird auch zur Laufzeit für den Runtime-Fallback gebraucht.
_STATION_CODE_TO_LONG_NAME: dict[str, str] = {
    "KLO": "Zürich / Kloten",
    "SMA": "Zürich / Fluntern",
    "REH": "Zürich / Affoltern",
    "REC": "Zürich / Reckenholz",
    "WAE": "Wädenswil",
    "TAE": "Aadorf / Tänikon",
    "BER": "Bern / Zollikofen",
    "INT": "Interlaken",
    "BAS": "Basel / Binningen",
    "LUZ": "Luzern",
    "STG": "St. Gallen",
    "DAV": "Davos",
    "CHU": "Chur",
    "SIO": "Sion",
    "LUG": "Lugano",
    "GVE": "Genève / Cointrin",
    "PUY": "Payerne",
    "JUN": "Jungfraujoch",
    "SAE": "Säntis",
    "PIL": "Pilatus",
}

# Welche Parameter holt der Runtime-Fallback? In dieser Reihenfolge versucht das
# Tool die Templates aufzurufen. Filename-Tokens, die im URL-Template ersetzt
# werden: {station} (lowercase), {STATION} (uppercase), {param} (MeteoSwiss-Code).
_CLIMATE_PARAM_ORDER: tuple[tuple[str, str], ...] = (
    ("tre200m0", "temp_mean"),
    ("rre150m0", "precip_mm"),
    ("sre000m0", "sunshine_h"),
)


def _parse_climate_tsv_for_station(text: str, station_long_name: str) -> list[float] | None:
    """Sucht in einem MeteoSwiss-NBCN-TSV-Dump die Zeile für `station_long_name`
    und gibt die 12 Monatswerte zurück. None wenn nicht gefunden / unparseable.
    """
    import csv as _csv
    import io as _io

    # Header-Block überspringen (5-9 Zeilen) bis zur Spaltenüberschrift
    in_data = False
    reader = _csv.reader(_io.StringIO(text), delimiter="\t")
    for row in reader:
        if not row or not row[0].strip():
            continue
        if not in_data:
            if row[0].strip().lower() in {"station", "stazione"} and len(row) >= 14:
                in_data = True
            continue
        if row[0].strip() != station_long_name:
            continue
        # 4 Meta-Spalten + 12 Monate
        if len(row) < 16:
            return None
        try:
            return [float(c.replace(",", ".")) for c in row[4:16]]
        except ValueError:
            return None
    return None


async def _try_runtime_fetch_climate_normals(
    client: httpx.AsyncClient, station_code: str
) -> dict[str, list[float]] | None:
    """Versucht, Klimanormwerte für eine Station zur Laufzeit von einer
    konfigurierbaren URL nachzuladen.

    Aktiviert via ENV `MCP_CLIMATE_NORMALS_URL_TEMPLATE`. Beispiel-Templates:

        MCP_CLIMATE_NORMALS_URL_TEMPLATE=https://data.geo.admin.ch/api/stac/v1/\
collections/ch.meteoschweiz.ogd-nbcn/items/{station}/assets/{param}.txt

    Token-Substitution:
        {station} → Stationscode lowercase (z.B. "rec")
        {STATION} → Stationscode uppercase (z.B. "REC")
        {param}   → MeteoSwiss-Parametercode (tre200m0/rre150m0/sre000m0)

    Pro Tool-Call werden bis zu 3 GETs gemacht (einer pro Parameter). Antwort wird
    als MeteoSwiss-NBCN-TSV interpretiert (gleiches Format wie der Dump-Ingest).
    Das Ergebnis ist gecacht (TTL: MCP_CACHE_TTL_STAC_CLIMATE, default 24 h).

    Returns:
        {"temp_mean": [...], "precip_mm": [...], "sunshine_h": [...]} sofern
        mindestens 1 Parameter erfolgreich geladen wurde, sonst None.
    """
    template = os.environ.get("MCP_CLIMATE_NORMALS_URL_TEMPLATE", "").strip()
    if not template:
        return None

    station_long = _STATION_CODE_TO_LONG_NAME.get(station_code)
    if not station_long:
        return None  # ohne Mapping kein TSV-Lookup möglich

    result: dict[str, list[float]] = {}

    for ms_param, our_field in _CLIMATE_PARAM_ORDER:
        url = (
            template
            .replace("{station}", station_code.lower())
            .replace("{STATION}", station_code.upper())
            .replace("{param}", ms_param)
        )

        async def _do_fetch(url_=url):
            resp = await client.get(url_)
            resp.raise_for_status()
            # MeteoSwiss-Files sind typischerweise cp1252-encoded
            try:
                resp.encoding = "cp1252"
                _ = resp.text
            except Exception:
                pass
            return resp.text

        try:
            text = await _cached(
                "stac_climate", (url, station_code, ms_param), _do_fetch
            )
        except Exception as exc:
            logger.warning(
                "climate_runtime_fetch_failed",
                station=station_code,
                param=ms_param,
                error_type=exc.__class__.__name__,
            )
            continue

        values = _parse_climate_tsv_for_station(text, station_long)
        if values is not None and len(values) == 12:
            result[our_field] = values
        else:
            logger.warning(
                "climate_runtime_parse_failed",
                station=station_code,
                param=ms_param,
                reason="station_not_found_or_invalid_format",
            )

    if not result:
        return None
    logger.info(
        "climate_runtime_fetched",
        station=station_code,
        params=list(result.keys()),
    )
    return result


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool(
    name="meteo_stations",
    annotations={
        "title": "SwissMetNet-Stationen auflisten",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@_traced_tool("meteo_stations")
async def meteo_stations(params: StationsInput) -> str:
    """<use_case>
    Liefert eine Übersicht der SwissMetNet (SMN)-Messstationen, die in diesem
    Server eingebettet sind. Nützlich, um Stationskürzel für meteo_current
    oder meteo_climate_normals zu finden.
    </use_case>

    <important_notes>
    - Kuratierte Auswahl (~20 Stationen) mit Schul-/Stadtplanungs-Fokus
    - Datenquelle: MeteoSwiss SMN-Katalog (160+ Stationen total)
    - Lizenz: CC BY 4.0 – Quelle: MeteoSchweiz
    </important_notes>

    <example>
    meteo_stations(canton="ZH")
    → KLO, SMA, REH, REC, WAE
    </example>

    Schul-Tipp: Station REH (Zürich/Affoltern) ist die nächste SMN-Station
    zum Schulhaus Leutschenbach.

    Args:
        params (StationsInput):
            - canton: Kantonskürzel (z.B. 'ZH') – leer = alle
            - response_format: 'markdown' oder 'json'

    Returns:
        str: Stationsliste mit Kürzel, Name, Kanton, Koordinaten und Höhe.
    """
    logger.info("tool_invoked", tool="meteo_stations", canton=params.canton or "all")
    filtered = {
        code: info
        for code, info in SMN_STATIONS.items()
        if not params.canton or info["canton"].upper() == params.canton.upper()
    }

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(
            _ogd_envelope(
                {
                    "stationen": filtered,
                    "total": len(filtered),
                    "filter_kanton": params.canton or "alle",
                },
                source="MeteoSwiss SwissMetNet (SMN) – kuratierte Auswahl, eingebettet",
                data_source_url=f"https://data.geo.admin.ch/api/stac/v1/collections/{SMN_COLLECTION}",
            ),
            ensure_ascii=False,
            indent=2,
        )

    lines = [
        "## SwissMetNet-Messstationen (MeteoSwiss)\n",
        f"**{len(filtered)} Stationen** | Filter: Kanton={params.canton or 'alle'}\n",
        "| Kürzel | Station | Kanton | Lat | Lon | Höhe (m) |",
        "|--------|---------|--------|-----|-----|----------|",
    ]
    for code, info in sorted(filtered.items(), key=lambda x: x[1]["canton"]):
        lines.append(
            f"| **{code}** | {info['name']} | {info['canton']} "
            f"| {info['lat']} | {info['lon']} | {info['alt']} |"
        )
    lines += [
        "",
        "**Schul-Tipp:** `REH` (Zürich/Affoltern) → nächste Station zum Schulhaus Leutschenbach",
        "**Vollständige Stationsliste:** https://www.meteoswiss.admin.ch/weather/measurement-systems/land-based-stations/automatic-measurement-network.html",
        "**STAC-Kollektion:** https://data.geo.admin.ch/api/stac/v1/collections/ch.meteoschweiz.ogd-smn",
        "",
        "*→ `meteo_current` für aktuelle Messwerte | `meteo_forecast` für Prognosen*",
    ]
    return "\n".join(lines)


@mcp.tool(
    name="meteo_current",
    annotations={
        "title": "Aktuelle SwissMetNet-Beobachtungen",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
@_traced_tool("meteo_current")
async def meteo_current(params: CurrentInput, ctx: Context | None = None) -> str:
    """<use_case>
    Aktuelle 10-Minuten-Wettermesswerte einer SwissMetNet-Station abrufen
    (Temperatur, Niederschlag, Sonnenschein, Wind, Feuchte, Druck).
    </use_case>

    <important_notes>
    - Granularität: 10-Minuten-Werte, letzte ~6 Beobachtungen
    - Quelle: BGDI STAC API (data.geo.admin.ch)
    - Live-Daten — Tool ist NICHT idempotent
    - Bei Upstream-Ausfall: Fallback mit Direktlinks statt Hard-Fail
    </important_notes>

    <example>
    meteo_current(station="REH")  → Zürich/Affoltern (nächste SMN-Station
                                     zum Schulhaus Leutschenbach)
    </example>

    Args:
        params (CurrentInput):
            - station: SMN-Kürzel, z.B. 'KLO', 'SMA', 'REH', 'BER'
            - response_format: 'markdown' oder 'json'

    Returns:
        str: Aktuelle Messwerte mit Zeitstempel, oder Fallback mit Direktlinks.
    """
    code = params.station.upper()
    station_info = SMN_STATIONS.get(code)
    logger.info("tool_invoked", tool="meteo_current", station=code)

    if not station_info:
        logger.info("tool_input_invalid", tool="meteo_current", reason="unknown_station", station=code)
        known = ", ".join(sorted(SMN_STATIONS.keys()))
        return (
            f"Fehler: Station '{code}' nicht in der eingebetteten Liste.\n"
            f"Bekannte Kürzel: {known}\n"
            f"→ `meteo_stations` aufrufen für vollständige Übersicht.\n"
            f"→ Vollständige Stationsliste: https://opendatadocs.meteoswiss.ch"
        )

    try:
        if ctx is not None:
            await ctx.info(f"Lade STAC-Item für Station {code}")
        async with _http_client(ctx) as client:
            rows = await _fetch_stac_now_csv(client, code)
    except Exception as exc:
        logger.warning(
            "upstream_failed",
            tool="meteo_current",
            endpoint="stac",
            station=code,
            error_type=exc.__class__.__name__,
        )
        if ctx is not None:
            await ctx.warning(f"STAC-Fetch fehlgeschlagen: {_sanitize_error(exc)}")
        stac_url = (
            f"https://data.geo.admin.ch/api/stac/v1/collections/{SMN_COLLECTION}/items/"
            f"ch.meteoschweiz.ogd-smn-{code.lower()}"
        )
        return (
            f"⚠️ Live-Daten für Station {code} nicht abrufbar: {_sanitize_error(exc)}\n\n"
            f"**Station:** {station_info['name']} ({code})\n"
            f"**STAC-Item:** {stac_url}\n"
            f"**MeteoSwiss Explorer:** https://www.meteoswiss.admin.ch/local-forecasts/regions/"
            f"stations/{code.lower()}.html\n"
            f"**Open Data Dokumentation:** https://opendatadocs.meteoswiss.ch/de/a-data-groundbased/a1-automatic-weather-stations"
        )

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(
            _ogd_envelope(
                {
                    "station": code,
                    "name": station_info["name"],
                    "canton": station_info["canton"],
                    "lat": station_info["lat"],
                    "lon": station_info["lon"],
                    "alt_m": station_info["alt"],
                    "beobachtungen": rows,
                },
                source="MeteoSwiss SwissMetNet via BGDI STAC API",
                data_source_url=(
                    f"https://data.geo.admin.ch/api/stac/v1/collections/{SMN_COLLECTION}/items/"
                    f"ch.meteoschweiz.ogd-smn-{code.lower()}"
                ),
            ),
            ensure_ascii=False,
            indent=2,
        )

    header = [
        f"## Aktuelle Beobachtungen: {station_info['name']} ({code})\n",
        f"- **Kanton:** {station_info['canton']}",
        f"- **Koordinaten:** {station_info['lat']}° N, {station_info['lon']}° E",
        f"- **Höhe:** {station_info['alt']} m ü. M.",
        "",
        "### Messwerte (10-Minuten-Intervall, UTC)",
    ]
    table = _format_smn_rows(rows, station_info)
    footer = [
        "",
        f"**MeteoSwiss-Stationsseite:** https://www.meteoswiss.admin.ch/local-forecasts/regions/stations/{code.lower()}.html",
        f"**STAC-API:** https://data.geo.admin.ch/api/stac/v1/collections/{SMN_COLLECTION}",
        "",
        "*→ `meteo_forecast` für Wetterprognose | `swiss-environment-mcp` für Luftqualität*",
    ]
    return "\n".join(header) + "\n" + table + "\n" + "\n".join(footer)


@mcp.tool(
    name="meteo_forecast",
    annotations={
        "title": "Wetterprognose (MeteoSwiss ICON-Modell)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
@_traced_tool("meteo_forecast")
async def meteo_forecast(params: ForecastInput, ctx: Context | None = None) -> str:
    """<use_case>
    1-16 Tage Wetterprognose für einen Ortsnamen oder Koordinaten — basierend
    auf dem MeteoSwiss-ICON-Modell (1-2 km Auflösung). Liefert Tageswerte
    (Temperatur Min/Max, Niederschlag, Wind, UV, Sonnenstunden, WMO-Code)
    und optional Stundenwerte.
    </use_case>

    <important_notes>
    - Modell: MeteoSwiss ICON-CH1/CH2-EPS via Open-Meteo
    - location wird geokodiert (Fuzzy-Fallback bei Misserfolg); lat/lon
      überschreibt location und spart einen HTTP-Roundtrip
    - Stündliche Daten füllen die ersten 48 Stunden, nicht den vollen Range
    - Bei Upstream-Ausfall: Direktlinks statt Hard-Fail
    </important_notes>

    <example>
    meteo_forecast(location="Schulhaus Leutschenbach Zürich", days=7)
    meteo_forecast(latitude=47.3769, longitude=8.5417, days=3, hourly=True)
    </example>

    Args:
        params (ForecastInput):
            - location: Ortsname (geokodiert) ODER lat/lon direkt
            - days: Prognosetage (1–16, Standard: 7)
            - hourly: True für Stundenwerte
            - response_format: 'markdown' oder 'json'

    Returns:
        str: Tages- (und optional Stunden-)Prognose mit Wettercode und Planung.
    """
    logger.info("tool_invoked", tool="meteo_forecast", days=params.days, has_coords=params.latitude is not None)
    async with _http_client(ctx) as client:
        # Koordinaten bestimmen
        if params.latitude is not None and params.longitude is not None:
            lat, lon = params.latitude, params.longitude
            display_name = f"{lat:.4f}° N, {lon:.4f}° E"
        elif params.location:
            if ctx is not None:
                await ctx.info(f"Geokodiere '{params.location}'")
            try:
                lat, lon, display_name, _match = await _geocode(client, params.location)
            except Exception as exc:
                logger.warning(
                    "upstream_failed",
                    tool="meteo_forecast",
                    endpoint="geocoding",
                    error_type=exc.__class__.__name__,
                )
                return (
                    f"Fehler beim Geokodieren von '{params.location}': {_sanitize_error(exc)}\n"
                    "Tipp: Verwende lat/lon direkt, z.B. lat=47.3769, lon=8.5417 für Zürich."
                )
        else:
            # Fallback: Zürich
            lat, lon, display_name = 47.3769, 8.5417, "Zürich"

        if ctx is not None:
            await ctx.info(f"Lade Prognose für {display_name}")
        try:
            data = await _fetch_open_meteo_forecast(
                client, lat, lon, params.days, params.hourly
            )
        except Exception as exc:
            logger.warning(
                "upstream_failed",
                tool="meteo_forecast",
                endpoint="open_meteo",
                error_type=exc.__class__.__name__,
            )
            if ctx is not None:
                await ctx.warning(f"Forecast-Fetch fehlgeschlagen: {_sanitize_error(exc)}")
            return (
                f"⚠️ Prognosedaten nicht abrufbar: {_sanitize_error(exc)}\n\n"
                "**Direktzugang MeteoSwiss:**\n"
                "- https://www.meteoswiss.admin.ch/local-forecasts.html\n"
                "- https://www.meteoswiss.admin.ch/weather/forecasts/local-forecasts.html"
            )

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(
            _ogd_envelope(
                {
                    "ort": display_name,
                    "lat": lat,
                    "lon": lon,
                    "prognose_tage": params.days,
                    "modell": "MeteoSwiss ICON-CH1/CH2-EPS via Open-Meteo",
                    "daten": data,
                },
                source="MeteoSwiss ICON-CH1/CH2-EPS via Open-Meteo",
                data_source_url="https://api.open-meteo.com/v1/meteoswiss",
            ),
            ensure_ascii=False,
            indent=2,
        )

    daily = data.get("daily", {})
    dates = daily.get("time", [])
    t_max = daily.get("temperature_2m_max", [])
    t_min = daily.get("temperature_2m_min", [])
    precip = daily.get("precipitation_sum", [])
    precip_prob = daily.get("precipitation_probability_max", [])
    wind = daily.get("windspeed_10m_max", [])
    wmo = daily.get("weathercode", [])
    uv = daily.get("uv_index_max", [])
    sun_h = daily.get("sunshine_duration", [])  # in Sekunden
    sunrise = daily.get("sunrise", [])
    sunset = daily.get("sunset", [])

    lines = [
        f"## Wetterprognose: {display_name}\n",
        f"*{params.days}-Tage-Prognose | Modell: MeteoSwiss ICON-CH1/CH2-EPS | via Open-Meteo*\n",
        "| Datum | Wetter | T min | T max | Regen | Regen-% | Wind | UV |",
        "|-------|--------|-------|-------|-------|---------|------|----|",
    ]

    for i, date in enumerate(dates):
        code_val = int(wmo[i]) if i < len(wmo) and wmo[i] is not None else 0
        wmo_desc = _wmo_description(code_val)
        t_mn = f"{t_min[i]:.1f} °C" if i < len(t_min) and t_min[i] is not None else "–"
        t_mx = f"{t_max[i]:.1f} °C" if i < len(t_max) and t_max[i] is not None else "–"
        pr = f"{precip[i]:.1f} mm" if i < len(precip) and precip[i] is not None else "–"
        pr_p = f"{int(precip_prob[i])} %" if i < len(precip_prob) and precip_prob[i] is not None else "–"
        w = f"{wind[i]:.0f} km/h" if i < len(wind) and wind[i] is not None else "–"
        uv_val = f"{uv[i]:.0f}" if i < len(uv) and uv[i] is not None else "–"
        lines.append(f"| {date} | {wmo_desc} | {t_mn} | {t_mx} | {pr} | {pr_p} | {w} | {uv_val} |")

    # Sonnenzeiten der ersten Tage
    if sunrise and sunset:
        lines += [
            "",
            "### Sonnenzeiten",
            "| Datum | Aufgang | Untergang | Sonnenschein |",
            "|-------|---------|-----------|--------------|",
        ]
        for i, date in enumerate(dates[:7]):
            sr = sunrise[i][11:16] if i < len(sunrise) and sunrise[i] else "–"
            ss = sunset[i][11:16] if i < len(sunset) and sunset[i] else "–"
            sh_sec = sun_h[i] if i < len(sun_h) and sun_h[i] is not None else 0
            sh_str = f"{sh_sec / 3600:.1f} h" if sh_sec else "–"
            lines.append(f"| {date} | {sr} | {ss} | {sh_str} |")

    # Stundenwerte (kompakt)
    if params.hourly:
        hourly = data.get("hourly", {})
        h_times = hourly.get("time", [])[:48]  # Erste 2 Tage
        h_temp = hourly.get("temperature_2m", [])
        h_precip = hourly.get("precipitation", [])
        h_wmo = hourly.get("weathercode", [])

        lines += [
            "",
            "### Stundenwerte (erste 48 Stunden)",
            "| Zeit (Zürich) | Wetter | Temperatur | Niederschlag |",
            "|---------------|--------|------------|--------------|",
        ]
        for i, t in enumerate(h_times):
            h_wmo_code = int(h_wmo[i]) if i < len(h_wmo) and h_wmo[i] is not None else 0
            h_desc = _wmo_description(h_wmo_code)
            h_t = f"{h_temp[i]:.1f} °C" if i < len(h_temp) and h_temp[i] is not None else "–"
            h_p = f"{h_precip[i]:.1f} mm" if i < len(h_precip) and h_precip[i] is not None else "–"
            lines.append(f"| {t[11:16]} | {h_desc} | {h_t} | {h_p} |")

    lines += [
        "",
        "**Quelle:** MeteoSwiss ICON-CH1/CH2-EPS via Open-Meteo (api.open-meteo.com)",
        "**MeteoSwiss Prognosen:** https://www.meteoswiss.admin.ch/weather/forecasts/local-forecasts.html",
        "",
        "*→ `meteo_school_check` für Schuleignungs-Ampel | `meteo_current` für aktuelle Beobachtungen*",
    ]
    return "\n".join(lines)


@mcp.tool(
    name="meteo_school_check",
    annotations={
        "title": "Wettereignung für Schulveranstaltungen prüfen",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
@_traced_tool("meteo_school_check")
async def meteo_school_check(
    params: SchoolCheckInput, ctx: Context | None = None
) -> str:
    """<use_case>
    Aggregiert Geocoding + 7-Tage-Forecast + Schwellenwert-Check zu einer
    Ampel-Bewertung (🟢/🟡/🔴) für Schulveranstaltungen im Freien. Ein
    Tool-Call ersetzt die Kombi meteo_forecast + manuelle Bewertung.
    </use_case>

    <important_notes>
    Schwellenwerte:
    - Temperatur: 5–33 °C (sonst zu kalt / zu heiss)
    - Niederschlag: < 1.5 mm/Tag
    - Wind: < 50 km/h
    - UV-Index ≥ 6: Warnung (Sonnenschutz)
    Quelle: SUVA / BAG / MeteoSchweiz-Warnklassen.
    Bei date-Parameter: nur dieser eine Tag wird zurückgegeben.
    </important_notes>

    <example>
    meteo_school_check(location="Zürich Oerlikon", activity="Sporttag")
    meteo_school_check(location="Lugano", date="2026-06-15", activity="Schulreise")
    </example>

    Args:
        params (SchoolCheckInput):
            - location: Ort (geokodiert), z.B. 'Zürich Oerlikon'
            - date: Optional – spezifischer Tag (YYYY-MM-DD)
            - activity: Art der Aktivität ('Sporttag', 'Schulreise', etc.)

    Returns:
        str: Ampel-Bewertung für die nächsten 7 Tage (oder Einzeltag).
    """
    logger.info("tool_invoked", tool="meteo_school_check", activity=params.activity)
    async with _http_client(ctx) as client:
        if ctx is not None:
            await ctx.info(f"Geokodiere '{params.location}'")
        try:
            lat, lon, display_name, _match = await _geocode(client, params.location)
        except Exception as exc:
            logger.warning(
                "upstream_failed",
                tool="meteo_school_check",
                endpoint="geocoding",
                error_type=exc.__class__.__name__,
            )
            return (
                f"Fehler beim Geokodieren von '{params.location}': "
                f"{_sanitize_error(exc)}"
            )

        if ctx is not None:
            await ctx.info(f"Lade 7-Tage-Forecast für {display_name}")
        try:
            data = await _fetch_open_meteo_forecast(
                client, lat, lon, 7, hourly=False
            )
        except Exception as exc:
            logger.warning(
                "upstream_failed",
                tool="meteo_school_check",
                endpoint="open_meteo",
                error_type=exc.__class__.__name__,
            )
            return f"⚠️ Prognosedaten nicht abrufbar: {_sanitize_error(exc)}"

    daily = data.get("daily", {})
    dates = daily.get("time", [])
    t_max = daily.get("temperature_2m_max", [])
    t_min = daily.get("temperature_2m_min", [])
    precip = daily.get("precipitation_sum", [])
    wind = daily.get("windspeed_10m_max", [])
    wmo = daily.get("weathercode", [])
    uv = daily.get("uv_index_max", [])

    lines = [
        f"## 🏫 Wettereignung: {params.activity} – {display_name}\n",
        f"*Aktivität: {params.activity} | Prüfzeitraum: {dates[0] if dates else '?'} bis {dates[-1] if dates else '?'}*\n",
        "| Datum | Ampel | Bewertung | T max | Regen | Wind |",
        "|-------|-------|-----------|-------|-------|------|",
    ]

    best_days = []
    for i, date in enumerate(dates):
        # Spezifisches Datum filtern
        if params.date and date != params.date:
            continue

        t_mx = t_max[i] if i < len(t_max) and t_max[i] is not None else 20.0
        t_mn = t_min[i] if i < len(t_min) and t_min[i] is not None else 10.0
        pr = precip[i] if i < len(precip) and precip[i] is not None else 0.0
        w = wind[i] if i < len(wind) and wind[i] is not None else 0.0
        wmo_code = int(wmo[i]) if i < len(wmo) and wmo[i] is not None else 0
        uv_val = uv[i] if i < len(uv) and uv[i] is not None else 0.0

        # Tagestemperatur: Minimum für Kältebewertung, Maximum für Hitzebewertung
        temp_for_check = min(t_mn, t_mx)  # konservativ für Kälte
        heat_check = t_mx

        emoji, verdict = _school_verdict(
            temp=temp_for_check,
            precip=pr,
            wind=w,
            wmo=wmo_code,
            uv=uv_val,
        )
        # Hitzegefahr separat prüfen
        if heat_check > SCHOOL_THRESHOLDS["temp_max_c"]:
            emoji = "🔴"
            verdict = f"Zu heiss ({heat_check:.1f} °C – Hitzewarnung)"

        if emoji == "🟢":
            best_days.append(date)

        t_str = f"{t_mx:.1f} °C"
        pr_str = f"{pr:.1f} mm"
        w_str = f"{w:.0f} km/h"
        lines.append(f"| {date} | {emoji} | {verdict[:60]} | {t_str} | {pr_str} | {w_str} |")

    lines += [""]

    if best_days:
        lines.append(f"✅ **Empfohlene Tage für {params.activity}:** {', '.join(best_days)}")
    else:
        lines.append(f"⚠️ **Keine optimalen Tage** für {params.activity} im Prognosezeitraum.")

    lines += [
        "",
        "**Schwellenwerte:** Temp 5–33 °C | Regen < 1.5 mm | Wind < 50 km/h | UV ≥ 6 → Sonnenschutz",
        "**Quelle:** MeteoSwiss ICON-CH1/CH2-EPS via Open-Meteo",
        "**MeteoSwiss Warnungen:** https://www.meteoswiss.admin.ch/warnings.html",
        "",
        "*→ `meteo_forecast` für detaillierte Prognose | `meteo_warnings` für aktive Warnungen*",
    ]
    return "\n".join(lines)


@mcp.tool(
    name="meteo_climate_normals",
    annotations={
        "title": "Klimanormwerte einer SMN-Station",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
@_traced_tool("meteo_climate_normals")
async def meteo_climate_normals(
    params: ClimateNormalsInput, ctx: Context | None = None
) -> str:
    """<use_case>
    Monatliche 30-Jahres-Klimanormwerte (Temperatur ∅, Niederschlag,
    Sonnenstunden) für eine MeteoSwiss-Station. Referenz für «typisches
    Wetter» — Schuljahresplanung, Veranstaltungs-Budgetierung, Vergleich
    mit aktuellen Messwerten.
    </use_case>

    <important_notes>
    - Periode: 1991–2020 (WMO-Standard)
    - Eingebettete Normwerte verfügbar: KLO, SMA, BER, LUG, GVE
    - Für andere Stationen: Tool gibt Liste verfügbarer Codes + opendata.swiss-Link
    - Statische Daten — Tool ist idempotent, kein Netzwerk-Roundtrip
    </important_notes>

    <example>
    meteo_climate_normals(station="KLO")  → Zürich/Kloten Jahresgang
    meteo_climate_normals(station="LUG", response_format="json")
    </example>

    Args:
        params (ClimateNormalsInput):
            - station: SMN-Kürzel (z.B. 'KLO', 'SMA', 'BER')
            - response_format: 'markdown' oder 'json'

    Returns:
        str: Monatliche Klimanormwerte-Tabelle 1991–2020.
    """
    code = params.station.upper()
    station_info = SMN_STATIONS.get(code)
    normals = CLIMATE_NORMALS.get(code)
    logger.info("tool_invoked", tool="meteo_climate_normals", station=code)

    if not station_info:
        known = ", ".join(sorted(SMN_STATIONS.keys()))
        return (
            f"Fehler: Station '{code}' nicht bekannt. Gültige Kürzel: {known}"
        )

    if not normals:
        # Runtime-Fallback: konfigurierbare URL via MCP_CLIMATE_NORMALS_URL_TEMPLATE
        # (z.B. STAC). Bleibt None wenn ENV nicht gesetzt oder Fetch fehlschlägt.
        if ctx is not None:
            await ctx.info(f"Versuche Runtime-Fetch für Station {code}")
        async with _http_client(ctx) as client:
            normals = await _try_runtime_fetch_climate_normals(client, code)

        if not normals:
            available = ", ".join(sorted(CLIMATE_NORMALS.keys()))
            return (
                f"Station '{code}' ({station_info['name']}) hat keine eingebetteten Normwerte.\n\n"
                f"**Verfügbar:** {available}\n\n"
                f"**Vollständige Normwerte auf opendata.swiss:**\n"
                f"https://opendata.swiss/de/dataset?q=meteoschweiz+klimanormwerte\n\n"
                f"**Tipp:** Setze `MCP_CLIMATE_NORMALS_URL_TEMPLATE` für Laufzeit-Lookup, "
                f"siehe README.\n\n"
                f"*→ `meteo_forecast` für aktuelle Prognose verwenden.*"
            )

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(
            _ogd_envelope(
                {
                    "station": code,
                    "name": station_info["name"],
                    "canton": station_info["canton"],
                    "periode": "1991–2020",
                    "monate": MONTHS_DE,
                    "normwerte": normals,
                },
                source="MeteoSwiss Klimanormwerte 1991–2020 (OGD, eingebettet)",
                data_source_url="https://opendata.swiss/de/dataset?q=meteoschweiz+klimanormwerte",
            ),
            ensure_ascii=False,
            indent=2,
        )

    lines = [
        f"## Klimanormwerte 1991–2020: {station_info['name']} ({code})\n",
        f"- **Kanton:** {station_info['canton']}",
        f"- **Höhe:** {station_info['alt']} m ü. M.",
        "",
        "| Monat | Temp ∅ (°C) | Niederschlag (mm) | Sonnenschein (h) |",
        "|-------|-------------|-------------------|-----------------|",
    ]

    temp = normals.get("temp_mean", [])
    precip = normals.get("precip_mm", [])
    sun = normals.get("sunshine_h", [])

    for i, month in enumerate(MONTHS_DE):
        t = f"{temp[i]:.1f}" if i < len(temp) else "–"
        p = f"{precip[i]}" if i < len(precip) else "–"
        s = f"{sun[i]}" if i < len(sun) else "–"
        lines.append(f"| {month} | {t} | {p} | {s} |")

    # Jahreszusammenfassung
    if temp and precip and sun:
        lines += [
            "|-------|-------------|-------------------|-----------------|",
            f"| **Jahr** | **{sum(temp)/12:.1f}** | **{sum(precip)}** | **{sum(sun)}** |",
        ]

    lines += [
        "",
        "**Periode:** Klimanormperiode 1991–2020 (WMO-Standard)",
        "**Quelle:** MeteoSwiss – https://opendata.swiss/de/dataset?q=meteoschweiz+klimanormwerte",
        "",
        "*→ `meteo_forecast` für aktuelle Prognose | `meteo_current` für Beobachtungen*",
    ]
    return "\n".join(lines)


@mcp.tool(
    name="meteo_warnings",
    annotations={
        "title": "Aktuelle MeteoSwiss-Wetterwarnungen",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
@_traced_tool("meteo_warnings")
async def meteo_warnings(params: WarningsInput, ctx: Context | None = None) -> str:
    """<use_case>
    Aktive amtliche MeteoSwiss-Wetterwarnungen (Gewitter, Sturm, Starkregen,
    Schnee, Hitze, Frost, Waldbrand, ...) live abrufen — landesweit, pro Kanton
    oder ortsgenau via PLZ. Ergänzt um Warnkarte, MeteoAlarm und OGD-Katalog.
    </use_case>

    <important_notes>
    - Live-Quelle ist das öffentliche MeteoSwiss-App-Backend
      (`app-prod-ws.meteoswiss-app.ch/v1/plzDetail`); es gibt keinen landesweiten
      Sammel-Endpoint, daher wird ohne `plz`/`canton` je eine Kantonshauptort-PLZ
      pro Kanton abgefragt und aggregiert. Für ortsgenaue Warnungen `plz` setzen.
    - Warnstufen-Skala: 1=Keine/gering, 2=Gering, 3=Mässig, 4=Stark, 5=Sehr stark.
    - Bei aktiven Warnungen Stufe 4+: Aussenveranstaltungen verschieben.
    - `MCP_WARNINGS_API_URL` überschreibt die App-Quelle (Vorbereitung auf die
      künftige offizielle OGD-Warnings-REST-API).
    </important_notes>

    <example>
    meteo_warnings(plz="8001")    → ortsgenaue Warnungen für Zürich-City
    meteo_warnings(canton="TI")   → Warnungen für das Tessin
    meteo_warnings()              → landesweite Aggregation über alle Kantone
    </example>

    Args:
        params (WarningsInput):
            - canton: Kantonskürzel zum Filtern (z.B. 'ZH')
            - plz: 4-stellige PLZ für ortsgenaue Warnungen (z.B. '8001')
            - language: 'de' | 'fr' | 'it' | 'en' (Sprache der Warntexte)
            - response_format: 'markdown' oder 'json'

    Returns:
        str: Aktive Warnungen + Warnkarte/MeteoAlarm-Links.
    """
    canton_filter = params.canton.upper() if params.canton else ""
    plz_query = params.plz
    lang = params.language
    logger.info(
        "tool_invoked",
        tool="meteo_warnings",
        canton=canton_filter or "all",
        plz=plz_query or "",
        lang=lang,
    )

    # Bevorzugt eine explizit konfigurierte OGD-Warnings-REST-API (Zukunft);
    # per Default die öffentliche MeteoSwiss-App-Quelle.
    warnings_api_url = os.environ.get("MCP_WARNINGS_API_URL", "").strip()
    # Aktive Warnungen im App-Schema (type_code/type_label/level/region_id/...).
    app_warnings: list[dict[str, Any]] = []
    # Aktive Warnungen im ENV-Override-Schema (type/level/regions/...).
    structured_warnings: list[dict[str, Any]] | None = None
    warn_scope = (
        f"PLZ {plz_query}"
        if plz_query
        else (f"Kanton {canton_filter}" if canton_filter else "Ganze Schweiz")
    )
    unknown_canton = False
    app_failures = 0

    if warnings_api_url:
        try:
            async with _http_client(ctx) as client:

                async def _do_fetch_warnings():
                    resp = await client.get(warnings_api_url)
                    resp.raise_for_status()
                    return resp.json()

                api_data = await _cached(
                    "warnings_api",
                    (warnings_api_url, canton_filter),
                    _do_fetch_warnings,
                )
            structured_warnings = _normalize_warnings_response(api_data, canton_filter)
            logger.info(
                "warnings_api_ok",
                count=len(structured_warnings),
                canton=canton_filter or "all",
            )
        except Exception as exc:
            logger.warning(
                "upstream_failed",
                tool="meteo_warnings",
                endpoint="warnings_api",
                error_type=exc.__class__.__name__,
            )
            if ctx is not None:
                await ctx.warning(
                    f"Warnings-API-Fetch fehlgeschlagen: {_sanitize_error(exc)}"
                )
    else:
        # MeteoSwiss-App-Backend: PLZ-Liste je nach Filter bestimmen.
        if plz_query:
            plz_list = [int(plz_query + "00")]
        elif canton_filter:
            plz6 = CANTON_CAPITAL_PLZ.get(canton_filter)
            if plz6 is None:
                unknown_canton = True
                plz_list = []
            else:
                plz_list = [plz6]
        else:
            plz_list = sorted(set(CANTON_CAPITAL_PLZ.values()))

        if plz_list:
            try:
                async with _http_client(ctx) as client:
                    app_warnings, app_failures = await _collect_app_warnings(
                        client, plz_list, lang
                    )
                logger.info(
                    "warnings_app_ok",
                    count=len(app_warnings),
                    queried=len(plz_list),
                    failures=app_failures,
                    scope=warn_scope,
                )
            except Exception as exc:
                logger.warning(
                    "upstream_failed",
                    tool="meteo_warnings",
                    endpoint="app_warnings",
                    error_type=exc.__class__.__name__,
                )
                if ctx is not None:
                    await ctx.warning(
                        f"MeteoSwiss-App-Fetch fehlgeschlagen: {_sanitize_error(exc)}"
                    )

    # Linkstack-Ergänzung: opendata.swiss-Katalog (immer als ergänzende Info)
    cap_url = "https://opendata.swiss/api/3/action/package_search?q=meteoschweiz+warnungen&rows=5"

    try:
        async with _http_client(ctx) as client:

            async def _do_fetch_opendata():
                resp = await client.get(cap_url)
                resp.raise_for_status()
                return resp.json()

            data = await _cached("opendata_swiss", (cap_url,), _do_fetch_opendata)
        datasets = data.get("result", {}).get("results", [])
    except Exception as exc:
        logger.warning(
            "upstream_failed",
            tool="meteo_warnings",
            endpoint="opendata_swiss",
            error_type=exc.__class__.__name__,
        )
        if ctx is not None:
            await ctx.warning(f"opendata.swiss-Fetch fehlgeschlagen: {_sanitize_error(exc)}")
        datasets = []

    lines = [
        "## ⚠️ MeteoSwiss Wetterwarnungen\n",
        f"*{warn_scope} | Quelle: MeteoSwiss*\n",
    ]

    if unknown_canton:
        lines += [
            f"_Unbekanntes Kantonskürzel '{canton_filter}'. Gültig: "
            + ", ".join(sorted(CANTON_CAPITAL_PLZ)),
            "",
        ]

    # ENV-Override-API (altes Schema): rendern, wenn aktiv.
    if warnings_api_url:
        if structured_warnings:
            lines += [
                f"### Aktive Warnungen ({len(structured_warnings)})",
                "| Stufe | Typ | Region | Gültig bis | Hinweis |",
                "|-------|-----|--------|------------|---------|",
            ]
            for w in structured_warnings:
                level = w.get("level") or "–"
                wtype = w.get("type") or "–"
                regions = ", ".join(w.get("regions") or []) or "–"
                until = w.get("valid_until") or "–"
                text = (w.get("text") or "")[:80]
                lines.append(f"| {level} | {wtype} | {regions} | {until} | {text} |")
            lines.append("")
        else:
            lines += [
                "_Keine aktiven Warnungen (strukturierte API lieferte 0 Einträge)._",
                "",
            ]
    else:
        # MeteoSwiss-App-Quelle (neues Schema).
        active = [w for w in app_warnings if not w.get("outlook")]
        outlook = [w for w in app_warnings if w.get("outlook")]
        if not app_warnings:
            lines += [
                "✅ _Zurzeit keine aktiven Warnungen für diesen Perimeter._",
                "",
            ]
        else:
            if plz_query or canton_filter:
                # Detailansicht (ein Perimeter).
                lines += [
                    f"### Aktive Warnungen ({len(active)})",
                    "| Stufe | Typ | Region | Gültig ab | Hinweis |",
                    "|-------|-----|--------|-----------|---------|",
                ]
                for w in active:
                    lines.append(_warning_table_row(w))
                if outlook:
                    lines += ["", f"### Vorausschau ({len(outlook)})"]
                    lines += [
                        "| Stufe | Typ | Region | Gültig ab |",
                        "|-------|-----|--------|-----------|",
                    ]
                    for w in outlook:
                        lines.append(
                            f"| {w.get('level') or '–'} | {w.get('type_label')} "
                            f"| {w.get('region_id') or '–'} | {w.get('valid_from') or '–'} |"
                        )
                lines.append("")
            else:
                # Landesweite Aggregation: nach Typ gruppiert.
                grouped = _aggregate_warnings_by_type(active)
                lines += [
                    f"### Aktive Warnungen — landesweite Übersicht ({len(active)} in "
                    f"{len(grouped)} Typen)",
                    "| Höchste Stufe | Typ | Betroffene Regionen | Beispiel-Hinweis |",
                    "|---------------|-----|---------------------|------------------|",
                ]
                for g in grouped:
                    lines.append(
                        f"| {g['max_level']} ({g['max_level_label']}) | {g['type_label']} "
                        f"| {g['region_count']} | {g['sample_text']} |"
                    )
                lines += [
                    "",
                    "_Aggregation über je eine Kantonshauptort-PLZ pro Kanton; "
                    "für Details einen Kanton oder eine PLZ angeben._",
                    "",
                ]
        if app_failures:
            lines += [
                f"_Hinweis: {app_failures} PLZ-Abfrage(n) fehlgeschlagen — "
                "Übersicht ggf. unvollständig._",
                "",
            ]

    lines += [
        "### Direkte Warnungsübersicht",
        "",
        "🔗 **Aktuelle Warnkarte (interaktiv):**",
        "   https://www.meteoswiss.admin.ch/warnings.html\n",
        "🔗 **Warnungen nach Region:**",
        "   https://www.meteoswiss.admin.ch/local-forecasts.html\n",
        "🔗 **MeteoAlarm (europäische Zusammenfassung):**",
        "   https://www.meteoalarm.org/en/live/country/?s=CH\n",
        "### Warnungsskala MeteoSwiss",
        "| Stufe | Bedeutung | Empfehlung (Schule) |",
        "|-------|-----------|---------------------|",
        "| 1 – Keine | Normales Wetter | Aussenaktivitäten möglich |",
        "| 2 – Gering | Leichte Beeinträchtigung | Aktivitäten möglich, aufmerksam bleiben |",
        "| 3 – Mässig | Beeinträchtigung möglich | Aktivitäten überdenken, Alternativen bereitstellen |",
        "| 4 – Stark | Erhebliche Beeinträchtigung | Aussenveranstaltungen absagen |",
        "| 5 – Sehr stark | Extreme Gefahr | Innenräume aufsuchen, Schulbetrieb einschränken |",
        "",
        "### MeteoSwiss App & Alarme",
        "Die offizielle **MeteoSwiss-App** (iOS/Android) sendet Push-Warnungen",
        "direkt an Ihr Gerät. Empfohlen für Schulverantwortliche.\n",
        "📱 https://www.meteoswiss.admin.ch/services-and-publications/applications/mobile-apps.html",
    ]

    if datasets:
        lines += [
            "",
            "### OGD-Datensätze auf opendata.swiss",
        ]
        for ds in datasets[:3]:
            title = ds.get("title", {})
            name = title.get("de") or title.get("fr") or ds.get("name", "–")
            slug = ds.get("name", "")
            url = f"https://opendata.swiss/de/dataset/{slug}" if slug else "–"
            lines.append(f"- [{name}]({url})")

    if params.response_format == ResponseFormat.JSON:
        payload: dict[str, Any] = {
            "scope": warn_scope,
            "kanton_filter": canton_filter or "alle",
            "plz_filter": plz_query or None,
            "sprache": lang,
            "warnungen_url": "https://www.meteoswiss.admin.ch/warnings.html",
            "meteoalarm_url": "https://www.meteoalarm.org/en/live/country/?s=CH",
            "ogd_datensaetze": datasets[:3],
        }
        if warnings_api_url:
            payload["quelle"] = "override"
            payload["warnings_api_active"] = True
            payload["warnings_api_url"] = warnings_api_url
            payload["aktive_warnungen"] = structured_warnings or []
        else:
            payload["quelle"] = "meteoswiss_app_api"
            payload["warnings_api_active"] = True
            payload["aktive_warnungen"] = [
                w for w in app_warnings if not w.get("outlook")
            ]
            payload["vorausschau"] = [w for w in app_warnings if w.get("outlook")]
            if not (plz_query or canton_filter):
                payload["zusammenfassung"] = _aggregate_warnings_by_type(
                    [w for w in app_warnings if not w.get("outlook")]
                )
            if app_failures:
                payload["fehlgeschlagene_abfragen"] = app_failures
            if unknown_canton:
                payload["fehler"] = f"unbekannter Kanton: {canton_filter}"
        return json.dumps(
            _ogd_envelope(
                payload,
                source=(
                    "MeteoSwiss Warnings API (Override)"
                    if warnings_api_url
                    else "MeteoSwiss App-API (plzDetail)"
                ),
                data_source_url=(warnings_api_url or f"{MS_APP_BASE}/plzDetail"),
            ),
            ensure_ascii=False,
            indent=2,
        )

    lines += [
        "",
        "*→ `meteo_school_check` für Schuleignungs-Ampel | `meteo_forecast` für Prognose*",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MCP Resources
# ---------------------------------------------------------------------------


@mcp.resource("meteo://stationen/smn")
async def get_stations_resource() -> str:
    """Vollständige eingebettete SMN-Stationsliste als JSON-Ressource."""
    return json.dumps(
        {
            "stationen": SMN_STATIONS,
            "total": len(SMN_STATIONS),
            "quelle": "MeteoSwiss SwissMetNet – Open Government Data",
            "stac_collection": f"{STAC_BASE}/collections/{SMN_COLLECTION}",
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.resource("meteo://schulplanung/schwellenwerte")
async def get_school_thresholds_resource() -> str:
    """Schwellenwerte für die Schuleignungs-Ampel (meteo_school_check)."""
    return json.dumps(
        {
            "schwellenwerte": {
                "temperatur_min_celsius": SCHOOL_THRESHOLDS["temp_min_c"],
                "temperatur_max_celsius": SCHOOL_THRESHOLDS["temp_max_c"],
                "niederschlag_max_mm": SCHOOL_THRESHOLDS["precip_max_mm"],
                "wind_max_kmh": SCHOOL_THRESHOLDS["wind_max_kmh"],
                "uv_warnung_ab": SCHOOL_THRESHOLDS["uv_warning"],
            },
            "beschreibung": "Schwellenwerte für Aussenaktivitäten an Volksschulen",
            "rechtsgrundlage": "SUVA-Empfehlungen, BAG UV-Schutz, MeteoSchweiz-Warnklassen",
        },
        ensure_ascii=False,
        indent=2,
    )


@mcp.resource("meteo://wmo/codes")
async def get_wmo_codes_resource() -> str:
    """WMO-Wettercodes mit deutschen Beschreibungen."""
    return json.dumps(
        {"wmo_codes": {str(k): v for k, v in WMO_CODES_DE.items()}},
        ensure_ascii=False,
        indent=2,
    )


# ---------------------------------------------------------------------------
# Health Endpoint (PR-4: SCALE-004 Container HEALTHCHECK + Render healthCheckPath)
# ---------------------------------------------------------------------------


@mcp.custom_route("/health", methods=["GET"], include_in_schema=False)
async def healthcheck(request):  # type: ignore[no-untyped-def]
    """Liveness-Probe für Container-Orchestrators (Render/k8s/Docker HEALTHCHECK).

    Bewusst trivial: gibt 200 OK zurück, sobald die ASGI-App läuft.
    Keine Upstream-Pings — sonst macht jeder Probe einen Open-Meteo-Call.
    """
    from starlette.responses import JSONResponse

    return JSONResponse({"status": "ok", "service": "meteoswiss-mcp"})


# ---------------------------------------------------------------------------
# Entry Point  (PR-1: SEC-006 MCP_TRANSPORT-Env, SEC-016 MCP_HOST default 127.0.0.1)
# ---------------------------------------------------------------------------


def _resolve_transport_settings() -> tuple[str, str, int]:
    """Liest Transport / Host / Port aus ENV (mit CLI-Argument-Fallback).

    Defaults:
    - MCP_TRANSPORT=stdio          (kein HTTP, sicherer Default)
    - MCP_HOST=127.0.0.1           (kein 0.0.0.0; verhindert NeighborJack)
    - MCP_PORT=8000

    CLI-Flags `--http` / `--port N` überschreiben die ENV-Variablen.
    Für Cloud-Deployment ist `MCP_HOST=0.0.0.0` bewusst zu setzen.
    """
    transport = os.environ.get("MCP_TRANSPORT", "stdio").lower()
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("MCP_PORT", "8000"))
    except ValueError:
        port = 8000

    argv = sys.argv[1:]
    if "--http" in argv:
        transport = "streamable-http"
    if "--port" in argv:
        try:
            port = int(argv[argv.index("--port") + 1])
        except (IndexError, ValueError):
            pass
    return transport, host, port


def _parse_origins(raw: str) -> list[str]:
    """Komma-separierte ENV-Liste in eine bereinigte Origin-Liste umwandeln."""
    return [o.strip() for o in raw.split(",") if o.strip()]


def _build_http_app():
    """Baut den Streamable-HTTP-ASGI-Stack: MCP-App + optionale CORS + optionale Auth.

    Middleware-Order (von aussen nach innen):
        Request → APIKey → CORS → MCP-App

    Beide Middlewares sind opt-in via ENV:
      MCP_ALLOWED_ORIGINS=https://app.example.com,https://other.example.com
      MCP_API_KEY=<random-secret>     # wenn gesetzt, ist Header X-API-Key Pflicht

    /health bleibt aus der API-Key-Pflicht ausgenommen (sonst Health-Probes 401).
    """
    import secrets as _secrets

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.responses import JSONResponse

    # mcp 2.x: stateless mode is a property of the app being built, not a
    # constructor argument.
    app = mcp.streamable_http_app(stateless_http=_STATELESS_HTTP)

    # CORS (SDK-004): Mcp-Session-Id muss browser-clients exposed werden.
    origins = _parse_origins(os.environ.get("MCP_ALLOWED_ORIGINS", ""))
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=[
                "Content-Type",
                "Authorization",
                "Mcp-Session-Id",
                "MCP-Protocol-Version",
                "X-API-Key",
            ],
            expose_headers=["Mcp-Session-Id"],
            max_age=600,
        )
        logger.info("cors_configured", origins=origins)

    # API-Key Auth (SEC-009 / SEC-013): dokumentierter Auth-Layer für HTTP-Modus.
    api_key = os.environ.get("MCP_API_KEY")
    if api_key:

        class _ApiKeyMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                if request.url.path == "/health":
                    return await call_next(request)
                presented = (
                    request.headers.get("x-api-key")
                    or request.headers.get("authorization", "")
                    .removeprefix("Bearer ")
                    .strip()
                )
                if not presented or not _secrets.compare_digest(
                    presented, api_key
                ):
                    logger.warning(
                        "auth_rejected",
                        path=request.url.path,
                        has_credential=bool(presented),
                    )
                    return JSONResponse(
                        {"error": "unauthorized"}, status_code=401
                    )
                return await call_next(request)

        app.add_middleware(_ApiKeyMiddleware)
        logger.info("auth_enabled", layer="api_key")
    else:
        logger.warning("auth_disabled", reason="MCP_API_KEY not set")

    return app


def main() -> None:
    transport, host, port = _resolve_transport_settings()
    if transport in ("streamable-http", "http", "sse"):
        # 0.0.0.0-Binding nur mit expliziter Opt-In-ENV erlauben (SEC-016)
        if host == "0.0.0.0" and os.environ.get("MCP_ALLOW_ANY_HOST") != "1":
            sys.stderr.write(
                "refusing to bind to 0.0.0.0 without MCP_ALLOW_ANY_HOST=1 "
                "(set explicitly in container/cloud manifest)\n"
            )
            sys.exit(2)
        # Wir bauen die ASGI-App selbst, damit wir CORS/Auth-Middleware
        # davorhängen können. uvicorn übernimmt dann das Serving.
        import uvicorn

        app = _build_http_app()
        uvicorn.run(app, host=host, port=port, log_config=None)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
