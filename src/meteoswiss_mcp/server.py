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

Alle Daten: öffentlich, keine Authentifizierung erforderlich.
Lizenz: Creative Commons BY 4.0 (MeteoSwiss Open Government Data).

Anker-Demo:
  «Wie war das Wetter beim Schulhaus Leutschenbach gestern?»
  → meteo_current(station='REH') kombiniert mit swiss-environment-mcp
"""

from __future__ import annotations

import csv
import io
import json
import os
from enum import Enum
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, field_validator

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
# Server-Initialisierung
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "meteoswiss_mcp",
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
# Pydantic-Eingabemodelle
# ---------------------------------------------------------------------------


class ResponseFormat(str, Enum):
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
    response_format: ResponseFormat = Field(default=ResponseFormat.MARKDOWN)


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


async def _geocode(location: str) -> tuple[float, float, str]:
    """Löst einen Ortsnamen in (lat, lon, display_name) auf."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            GEOCODING_BASE,
            params={"name": location, "count": 1, "language": "de", "format": "json"},
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            raise ValueError(f"Ort '{location}' nicht gefunden.")
        r = results[0]
        display = r.get("name", location)
        admin = r.get("admin1", "")
        country = r.get("country_code", "")
        if admin:
            display = f"{display}, {admin} ({country})"
        return float(r["latitude"]), float(r["longitude"]), display


async def _fetch_open_meteo_forecast(
    lat: float,
    lon: float,
    days: int,
    hourly: bool,
) -> dict[str, Any]:
    """Ruft MeteoSwiss ICON-Prognose von Open-Meteo ab."""
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
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(OPEN_METEO_BASE, params=params)
        resp.raise_for_status()
        return resp.json()


async def _fetch_stac_now_csv(station: str) -> list[dict[str, str]]:
    """
    Lädt die neueste 10-Minuten-CSV einer SMN-Station via STAC API.
    Gibt die letzten Zeilen als Liste von Dictionaries zurück.
    """
    station_lower = station.lower()
    # STAC Item für die Station abrufen
    stac_item_url = (
        f"{STAC_BASE}/collections/{SMN_COLLECTION}/items/"
        f"ch.meteoschweiz.ogd-smn-{station_lower}"
    )
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(stac_item_url)
        resp.raise_for_status()
        item = resp.json()

    # Asset-URL für die "now"-Datei finden (10-Minuten-Werte, neueste)
    assets = item.get("assets", {})
    now_url: str | None = None

    # Suche nach dem "now"-Asset (10-Minuten-Granularität)
    for key, asset in assets.items():
        href = asset.get("href", "")
        if "/now/" in href and "_t_" in href and href.endswith(".csv"):
            now_url = href
            break

    # Fallback: erstes CSV-Asset nehmen
    if not now_url:
        for key, asset in assets.items():
            href = asset.get("href", "")
            if href.endswith(".csv"):
                now_url = href
                break

    if not now_url:
        raise ValueError(f"Kein CSV-Asset für Station '{station}' in STAC gefunden.")

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(now_url)
        resp.raise_for_status()
        content = resp.text

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
async def meteo_stations(params: StationsInput) -> str:
    """
    Listet SwissMetNet (SMN)-Messstationen auf, die in diesem Server eingebettet sind.

    SMN ist das automatische Bodenmessnetz von MeteoSwiss mit über 160 Stationen.
    Dieser Server enthält eine kuratierte Auswahl von ~20 Stationen mit Relevanz
    für städtische Planung, Schulen und Bildungseinrichtungen.

    Stationskürzel werden für meteo_current und meteo_climate_normals benötigt.

    Schul-Tipp: Station REH (Zürich/Affoltern) ist die nächste SMN-Station
    zum Schulhaus Leutschenbach und zum Schulkreis Schwamendingen.

    Args:
        params (StationsInput):
            - canton: Kantonskürzel (z.B. 'ZH') – leer = alle
            - response_format: 'markdown' oder 'json'

    Returns:
        str: Stationsliste mit Kürzel, Name, Kanton, Koordinaten und Höhe.
    """
    filtered = {
        code: info
        for code, info in SMN_STATIONS.items()
        if not params.canton or info["canton"].upper() == params.canton.upper()
    }

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(
            {
                "stationen": filtered,
                "total": len(filtered),
                "filter_kanton": params.canton or "alle",
                "stac_collection": f"https://data.geo.admin.ch/api/stac/v1/collections/{SMN_COLLECTION}",
                "opendata_meteoswiss": "https://opendatadocs.meteoswiss.ch",
                "quelle": "MeteoSwiss SwissMetNet (SMN) – Open Government Data",
            },
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
async def meteo_current(params: CurrentInput) -> str:
    """
    Ruft aktuelle Wettermesswerte einer SwissMetNet-Station ab (10-Minuten-Granularität).

    Daten werden über die BGDI STAC API bezogen: Jede Station hat eine CSV-Datei
    im «now»-Verzeichnis, die alle 10 Minuten aktualisiert wird.

    Messgrössen: Temperatur, Niederschlag, Sonnenschein, Wind, Feuchte, Druck.

    Schul-Beispiel:
      «Wie war das Wetter beim Schulhaus Leutschenbach jetzt gerade?»
      → meteo_current(station='REH')  # Zürich/Affoltern, nächste SMN-Station

    Args:
        params (CurrentInput):
            - station: SMN-Kürzel, z.B. 'KLO', 'SMA', 'REH', 'BER'
            - response_format: 'markdown' oder 'json'

    Returns:
        str: Aktuelle Messwerte mit Zeitstempel, oder Fallback mit Direktlinks.
    """
    code = params.station.upper()
    station_info = SMN_STATIONS.get(code)

    if not station_info:
        known = ", ".join(sorted(SMN_STATIONS.keys()))
        return (
            f"Fehler: Station '{code}' nicht in der eingebetteten Liste.\n"
            f"Bekannte Kürzel: {known}\n"
            f"→ `meteo_stations` aufrufen für vollständige Übersicht.\n"
            f"→ Vollständige Stationsliste: https://opendatadocs.meteoswiss.ch"
        )

    try:
        rows = await _fetch_stac_now_csv(code)
    except Exception as exc:
        stac_url = (
            f"https://data.geo.admin.ch/api/stac/v1/collections/{SMN_COLLECTION}/items/"
            f"ch.meteoschweiz.ogd-smn-{code.lower()}"
        )
        return (
            f"⚠️ Live-Daten für Station {code} nicht abrufbar: {exc}\n\n"
            f"**Station:** {station_info['name']} ({code})\n"
            f"**STAC-Item:** {stac_url}\n"
            f"**MeteoSwiss Explorer:** https://www.meteoswiss.admin.ch/local-forecasts/regions/"
            f"stations/{code.lower()}.html\n"
            f"**Open Data Dokumentation:** https://opendatadocs.meteoswiss.ch/de/a-data-groundbased/a1-automatic-weather-stations"
        )

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(
            {
                "station": code,
                "name": station_info["name"],
                "canton": station_info["canton"],
                "lat": station_info["lat"],
                "lon": station_info["lon"],
                "alt_m": station_info["alt"],
                "beobachtungen": rows,
                "quelle": "MeteoSwiss SMN via BGDI STAC API",
            },
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
async def meteo_forecast(params: ForecastInput) -> str:
    """
    Ruft eine Wetterprognose auf Basis des MeteoSwiss ICON-CH1/CH2-EPS-Modells ab.

    Daten werden über Open-Meteo bezogen, das die MeteoSwiss ICON-Modellausgabe
    mit 1–2 km Auflösung bereitstellt. Prognosen bis 16 Tage.

    Täglich: Temperatur Min/Max, Niederschlag, Windspitze, UV-Index,
             Sonnenscheindauer, Sonnenauf/-untergang, WMO-Wettercode.
    Stündlich (optional): Temperatur, Niederschlag, Wind, Bewölkung, UV.

    Schul-Beispiel:
      «Wie wird das Wetter beim Schulhaus Leutschenbach nächsten Dienstag?»
      → meteo_forecast(location='Schulhaus Leutschenbach Zürich', days=7)

    Args:
        params (ForecastInput):
            - location: Ortsname (geokodiert) ODER lat/lon direkt
            - days: Prognosetage (1–16, Standard: 7)
            - hourly: True für Stundenwerte
            - response_format: 'markdown' oder 'json'

    Returns:
        str: Tages- (und optional Stunden-)Prognose mit Wettercode und Planung.
    """
    # Koordinaten bestimmen
    if params.latitude is not None and params.longitude is not None:
        lat, lon = params.latitude, params.longitude
        display_name = f"{lat:.4f}° N, {lon:.4f}° E"
    elif params.location:
        try:
            lat, lon, display_name = await _geocode(params.location)
        except Exception as exc:
            return (
                f"Fehler beim Geokodieren von '{params.location}': {exc}\n"
                "Tipp: Verwende lat/lon direkt, z.B. lat=47.3769, lon=8.5417 für Zürich."
            )
    else:
        # Fallback: Zürich
        lat, lon, display_name = 47.3769, 8.5417, "Zürich"

    try:
        data = await _fetch_open_meteo_forecast(lat, lon, params.days, params.hourly)
    except Exception as exc:
        return (
            f"⚠️ Prognosedaten nicht abrufbar: {exc}\n\n"
            "**Direktzugang MeteoSwiss:**\n"
            "- https://www.meteoswiss.admin.ch/local-forecasts.html\n"
            "- https://www.meteoswiss.admin.ch/weather/forecasts/local-forecasts.html"
        )

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(
            {
                "ort": display_name,
                "lat": lat,
                "lon": lon,
                "prognose_tage": params.days,
                "modell": "MeteoSwiss ICON-CH1/CH2-EPS via Open-Meteo",
                "daten": data,
            },
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
async def meteo_school_check(params: SchoolCheckInput) -> str:
    """
    Bewertet das Wetter auf Eignung für Schulveranstaltungen im Freien.

    Gibt eine 🟢/🟡/🔴-Ampel pro Tag aus:
    - 🟢 Geeignet: Gutes Wetter, alle Parameter im grünen Bereich
    - 🟡 Bedingt: Leichte Einschränkungen (z.B. UV, leichte Bewölkung)
    - 🔴 Nicht geeignet: Regen, Gewitter, Frost, Hitze, Sturm

    Schwellenwerte:
    - Temperatur: 5–33 °C
    - Niederschlag: < 1.5 mm/Tag
    - Wind: < 50 km/h
    - UV-Index ≥ 6: Warnung (Sonnenschutz obligatorisch)

    Schul-Beispiel:
      «Welche Tage eignen sich nächste Woche für den Sporttag beim
       Schulhaus Leutschenbach?»
      → meteo_school_check(location='Zürich Oerlikon', activity='Sporttag')

    Args:
        params (SchoolCheckInput):
            - location: Ort (geokodiert), z.B. 'Zürich Oerlikon'
            - date: Optional – spezifischer Tag (YYYY-MM-DD)
            - activity: Art der Aktivität ('Sporttag', 'Schulreise', etc.)

    Returns:
        str: Ampel-Bewertung für die nächsten 7 Tage (oder Einzeltag).
    """
    try:
        lat, lon, display_name = await _geocode(params.location)
    except Exception as exc:
        return f"Fehler beim Geokodieren von '{params.location}': {exc}"

    try:
        data = await _fetch_open_meteo_forecast(lat, lon, 7, hourly=False)
    except Exception as exc:
        return f"⚠️ Prognosedaten nicht abrufbar: {exc}"

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
async def meteo_climate_normals(params: ClimateNormalsInput) -> str:
    """
    Liefert monatliche Klimanormwerte 1991–2020 für eine SMN-Station.

    Normwerte sind 30-jährige Mittelwerte, die als Referenz für «typisches Wetter»
    eines Ortes dienen. Nützlich für Schuljahresplanung, Budgetierung von
    Veranstaltungen und Vergleiche mit aktuellen Messwerten.

    Enthält: Monatsmitteltemperatur, Monatsniederschlag, Sonnenscheinstunden.

    Hinweis: Eingebettete Normwerte für KLO, SMA, BER, LUG, GVE.
    Für weitere Stationen: opendata.swiss MeteoSwiss Klimanormwerte.

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

    if not station_info:
        known = ", ".join(sorted(SMN_STATIONS.keys()))
        return (
            f"Fehler: Station '{code}' nicht bekannt. Gültige Kürzel: {known}"
        )

    if not normals:
        available = ", ".join(sorted(CLIMATE_NORMALS.keys()))
        return (
            f"Station '{code}' ({station_info['name']}) hat keine eingebetteten Normwerte.\n\n"
            f"**Verfügbar:** {available}\n\n"
            f"**Vollständige Normwerte auf opendata.swiss:**\n"
            f"https://opendata.swiss/de/dataset?q=meteoschweiz+klimanormwerte\n\n"
            f"*→ `meteo_forecast` für aktuelle Prognose verwenden.*"
        )

    if params.response_format == ResponseFormat.JSON:
        return json.dumps(
            {
                "station": code,
                "name": station_info["name"],
                "canton": station_info["canton"],
                "periode": "1991–2020",
                "monate": MONTHS_DE,
                "normwerte": normals,
                "quelle": "MeteoSwiss Klimanormwerte 1991–2020 (OGD)",
            },
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
async def meteo_warnings(params: WarningsInput) -> str:
    """
    Ruft aktuelle Wetterwarnungen von MeteoSwiss ab.

    MeteoSwiss gibt Warnungen auf einer 5-stufigen Skala aus:
    1=Keine, 2=Gering, 3=Mässig, 4=Stark, 5=Sehr stark.
    Warntypen: Gewitter, Starkregen, Sturm, Schnee, Eis, Hitze, Frost,
               Nebel, Waldbrand, Glatteis.

    Wichtig für Schulplanung: Aktive Warnungen → Aussenveranstaltungen verschieben.

    Da die MeteoSwiss Warnings-API noch nicht als offizielle REST-API
    verfügbar ist (geplant Q2 2026+), liefert dieses Tool direkte Links
    zur offiziellen Warnungsseite und zum CAP-Feed.

    Args:
        params (WarningsInput):
            - canton: Kantonskürzel zum Filtern (z.B. 'ZH')
            - response_format: 'markdown' oder 'json'

    Returns:
        str: Links zu aktuellen MeteoSwiss-Warnungen und Warnkarte.
    """
    # Versuche CAP-Feed zu lesen (MeteoSwiss Common Alerting Protocol)
    cap_url = "https://opendata.swiss/api/3/action/package_search?q=meteoschweiz+warnungen&rows=5"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(cap_url)
            resp.raise_for_status()
            data = resp.json()
        datasets = data.get("result", {}).get("results", [])
    except Exception:
        datasets = []

    canton_filter = params.canton.upper() if params.canton else ""

    lines = [
        "## ⚠️ MeteoSwiss Wetterwarnungen\n",
        f"*{('Kanton ' + canton_filter) if canton_filter else 'Ganze Schweiz'} | Quelle: MeteoSwiss*\n",
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
        return json.dumps(
            {
                "kanton_filter": canton_filter or "alle",
                "warnungen_url": "https://www.meteoswiss.admin.ch/warnings.html",
                "meteoalarm_url": "https://www.meteoalarm.org/en/live/country/?s=CH",
                "ogd_datensaetze": datasets[:3],
                "hinweis": "Direkte Warnings-API geplant ab Q2 2026 (MeteoSwiss OGD Phase 2)",
            },
            ensure_ascii=False,
            indent=2,
        )

    lines += [
        "",
        "**Hinweis:** Die direkte MeteoSwiss Warnings-REST-API wird mit",
        "OGD Phase 2 (geplant: Q2 2026) verfügbar sein.",
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
# Entry Point
# ---------------------------------------------------------------------------


def main() -> None:
    port = int(os.environ.get("PORT", 8000))
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport == "streamable_http":
        mcp.run(transport="streamable_http", port=port)
    else:
        mcp.run()


if __name__ == "__main__":
    main()
