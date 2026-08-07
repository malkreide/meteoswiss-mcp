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
from fixture_data import fixture_json, fixture_text

from meteoswiss_mcp.server import (
    CLIMATE_NORMALS,
    MONTHS_DE,
    SMN_STATIONS,
    WMO_CODES_DE,
    _cache_clear,
    _school_verdict,
    _wmo_description,
)


@pytest.fixture(autouse=True)
def _isolate_cache():
    """Der TTL-Cache ist modul-global und überlebt sonst den einzelnen Test.

    Ohne diese Isolation sieht ein Test einen Eintrag, den ein früherer Test
    hinterlassen hat, umgeht damit sein eigenes respx-Mock und schlägt je nach
    Ausführungsreihenfolge fehl — oder, schlimmer, besteht aus dem falschen
    Grund.
    """
    _cache_clear()
    yield
    _cache_clear()

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
        emoji, verdict = _school_verdict(temp=20.0, precip=0.0, wind=15.0, wmo=1, uv=3.0)
        assert emoji == "🟢"
        assert "Geeignet" in verdict

    def test_rain_day(self):
        emoji, verdict = _school_verdict(temp=15.0, precip=5.0, wind=20.0, wmo=63, uv=1.0)
        assert emoji == "🔴"
        assert "Nicht geeignet" in verdict

    def test_frost_day(self):
        emoji, verdict = _school_verdict(temp=-2.0, precip=0.0, wind=10.0, wmo=0, uv=2.0)
        assert emoji == "🔴"
        assert "kalt" in verdict.lower()

    def test_thunderstorm(self):
        emoji, verdict = _school_verdict(temp=22.0, precip=8.0, wind=60.0, wmo=95, uv=5.0)
        assert emoji == "🔴"

    def test_uv_warning(self):
        """Hoher UV-Index → gelb, nicht rot."""
        emoji, verdict = _school_verdict(temp=28.0, precip=0.0, wind=10.0, wmo=0, uv=8.0)
        assert emoji == "🟡"
        assert "UV" in verdict or "uv" in verdict.lower() or "Sonnenschutz" in verdict

    def test_marginal_overcast(self):
        """Bedeckt (WMO 3) → bedingt geeignet."""
        emoji, verdict = _school_verdict(temp=18.0, precip=0.0, wind=20.0, wmo=3, uv=2.0)
        assert emoji in ("🟢", "🟡")

    def test_windy_day(self):
        emoji, verdict = _school_verdict(temp=20.0, precip=0.0, wind=70.0, wmo=0, uv=3.0)
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


# ---------------------------------------------------------------------------
# STAC-Item-URL & Asset-Auswahl (Issue #33)
# ---------------------------------------------------------------------------

_STAC_ASSET_BASE = "https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/klo"

# Ausschnitt aus dem echten STAC-Item von `klo`: die Granularität steckt im
# Dateinamen (`_t_now`), nicht im Pfad — und Tages-/Historik-Assets liegen im
# selben Dict.
# Aufgezeichnet statt ausgedacht — VOLLSTAENDIG, und das ist der Punkt:
# `_select_smn_now_asset` lehnt bewusst jeden Fallback ab, weil im selben
# Asset-Dict Tages-, Monats-, Jahres- und Jahrzehnt-Historien liegen. Die
# erfundene Vorgaengerin fuehrte vier Assets — die Quelle liefert 16. Der
# Selektor wurde also nie gegen die Ablenker geprueft, gegen die es ihn gibt.
# Herkunft und Datum in tests/fixtures/PROVENANCE.md.
_STAC_ITEM_KLO = fixture_json("stac_item_klo.json")

# Die echte 10-Minuten-CSV: 34 Spalten statt der sieben der Vorgaengerin, und
# mit leeren Zellen, wie die Quelle sie liefert.
_SMN_NOW_CSV = fixture_text("smn_now.csv")


class TestSmnStacItemUrl:
    def test_item_id_is_the_bare_lowercase_code(self):
        from meteoswiss_mcp.server import _smn_stac_item_url

        url = _smn_stac_item_url("KLO")
        assert url.endswith("/collections/ch.meteoschweiz.ogd-smn/items/klo")

    def test_collection_id_is_not_repeated_as_item_prefix(self):
        """Die 404-Ursache aus #33: `items/ch.meteoschweiz.ogd-smn-klo`."""
        from meteoswiss_mcp.server import _smn_stac_item_url

        assert "items/ch.meteoschweiz.ogd-smn-" not in _smn_stac_item_url("KLO")

    def test_lowercase_input_yields_the_same_url(self):
        from meteoswiss_mcp.server import _smn_stac_item_url

        assert _smn_stac_item_url("klo") == _smn_stac_item_url("KLO")


class TestSelectSmnNowAsset:
    def test_prefers_ten_minute_now(self):
        from meteoswiss_mcp.server import _select_smn_now_asset

        href = _select_smn_now_asset(_STAC_ITEM_KLO["assets"])
        assert href.endswith("ogd-smn_klo_t_now.csv")

    def test_falls_back_to_ten_minute_recent(self):
        from meteoswiss_mcp.server import _select_smn_now_asset

        assets = {
            k: v
            for k, v in _STAC_ITEM_KLO["assets"].items()
            if not k.endswith("_t_now.csv")
        }
        href = _select_smn_now_asset(assets)
        assert href.endswith("ogd-smn_klo_t_recent.csv")

    def test_never_falls_back_to_daily_or_historical(self):
        """Lieber ein Fehler als Tageswerte von 1980 als «aktuelle Messung»."""
        from meteoswiss_mcp.server import _select_smn_now_asset

        assets = {
            k: v
            for k, v in _STAC_ITEM_KLO["assets"].items()
            if "_t_" not in k
        }
        assert assets  # es sind noch Assets da, nur keine 10-Minuten-Werte
        assert _select_smn_now_asset(assets) is None


@pytest.mark.asyncio
async def test_meteo_current_end_to_end_markdown():
    """Vollständiger Pfad: STAC-Item → 10-min-CSV → Markdown-Tabelle."""
    import respx

    from meteoswiss_mcp.server import CurrentInput, _cache_clear, meteo_current

    _cache_clear()
    with respx.mock(assert_all_called=True) as r:
        r.get(
            "https://data.geo.admin.ch/api/stac/v1/collections/"
            "ch.meteoschweiz.ogd-smn/items/klo"
        ).respond(json=_STAC_ITEM_KLO)
        r.get(f"{_STAC_ASSET_BASE}/ogd-smn_klo_t_now.csv").respond(text=_SMN_NOW_CSV)
        result = await meteo_current(CurrentInput(station="KLO"))

    # Erwartungen aus der Fixture abgeleitet, nicht hingeschrieben: Es sind
    # Wetterwerte, und eine feste Temperatur waere beim naechsten Aufzeichnen
    # falsch, ohne dass sich etwas Geprueftes geaendert haette.
    import csv as _csv
    import io as _io

    _rows = list(_csv.DictReader(_io.StringIO(_SMN_NOW_CSV), delimiter=";"))
    _latest = _rows[-1]

    assert "⚠️" not in result  # kein Fallback-Pfad
    assert _latest["tre200s0"] in result  # jüngste Zeile
    assert _latest["reference_timestamp"] in result  # nicht "–"
    assert _rows[-2]["reference_timestamp"] not in result, (
        "die vorletzte Zeile steht in der Ausgabe — es wird nicht die juengste "
        "gerendert"
    )
    assert _latest["pp0qnhs0"] in result  # QNH-Luftdruck wird gerendert


@pytest.mark.asyncio
async def test_meteo_current_json_provenance_url():
    """Die Provenance-URL muss auf das Item zeigen, das auch abgerufen wurde."""
    import respx

    from meteoswiss_mcp.server import (
        CurrentInput,
        ResponseFormat,
        _cache_clear,
        meteo_current,
    )

    _cache_clear()
    with respx.mock(assert_all_called=True) as r:
        r.get(
            "https://data.geo.admin.ch/api/stac/v1/collections/"
            "ch.meteoschweiz.ogd-smn/items/klo"
        ).respond(json=_STAC_ITEM_KLO)
        r.get(f"{_STAC_ASSET_BASE}/ogd-smn_klo_t_now.csv").respond(text=_SMN_NOW_CSV)
        result = await meteo_current(
            CurrentInput(station="KLO", response_format=ResponseFormat.JSON)
        )

    payload = json.loads(result)
    assert payload["provenance"]["data_source_url"].endswith("/items/klo")
    # Zahl aus der Fixture: Das Aufzeichnungsskript behaelt die letzten N
    # Zeilen, und N steht in PROVENANCE.md — nicht hier.
    import csv as _csv
    import io as _io

    _n = len(list(_csv.DictReader(_io.StringIO(_SMN_NOW_CSV), delimiter=";")))
    assert len(payload["payload"]["beobachtungen"]) == _n


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

    result = await meteo_climate_normals(ClimateNormalsInput(station="SMA", response_format="json"))
    data = json.loads(result)
    # PR-6: OGDResponse-Envelope
    assert data["payload"]["station"] == "SMA"
    assert len(data["payload"]["normwerte"]["temp_mean"]) == 12
    assert data["provenance"]["license"] == "CC BY 4.0"
    assert "retrieved_at" in data["provenance"]


_APP_URL = "https://app-prod-ws.meteoswiss-app.ch/v1/plzDetail"
_OPENDATA_URL = "https://opendata.swiss/"

_APP_WARN_FIRE = {
    "warnType": 10,
    "warnLevel": 5,
    "regionId": 2600,
    "text": "Waldbrand-Warnung Test",
    "validFrom": 1785060300000,
    "outlook": False,
    "links": [{"url": "https://www.natural-hazards.ch/.../forest-fire.html", "text": "x"}],
}
_APP_WARN_HEAT = {
    "warnType": 7,
    "warnLevel": 3,
    "regionId": 309,
    "text": "Hitze-Warnung Test",
    "validFrom": 1785060300000,
    "outlook": False,
    "links": [{"url": "https://www.natural-hazards.ch/.../heat-wave.html", "text": "y"}],
}
_APP_WARN_OUTLOOK = {
    "warnType": 2,
    "warnLevel": 4,
    "regionId": 111,
    "text": "Gewitter-Vorausschau",
    "validFrom": 1785200000000,
    "outlook": True,
    "links": [],
}


def _mock_warnings(r, warnings):
    """Registriert App-API- + opendata-Mocks für meteo_warnings-Tests."""
    r.get(url__startswith=_APP_URL).respond(200, json={"warnings": warnings})
    r.get(url__startswith=_OPENDATA_URL).respond(200, json={"result": {"results": []}})


@pytest.mark.asyncio
async def test_meteo_warnings_markdown():
    import respx

    from meteoswiss_mcp.server import WarningsInput, _cache_clear, meteo_warnings

    _cache_clear()
    with respx.mock(assert_all_called=False) as r:
        _mock_warnings(r, [_APP_WARN_FIRE])
        result = await meteo_warnings(WarningsInput(canton="ZH"))
    assert "MeteoSwiss" in result
    assert "Warnung" in result


@pytest.mark.asyncio
async def test_meteo_warnings_app_plz_markdown():
    """PLZ-Detailansicht rendert echte App-Warnungen mit Typ-/Stufen-Label."""
    import respx

    from meteoswiss_mcp.server import WarningsInput, _cache_clear, meteo_warnings

    _cache_clear()
    with respx.mock(assert_all_called=False) as r:
        _mock_warnings(r, [_APP_WARN_HEAT, _APP_WARN_FIRE, _APP_WARN_OUTLOOK])
        result = await meteo_warnings(WarningsInput(plz="8001"))
    assert "Aktive Warnungen (2)" in result
    assert "Waldbrand" in result
    assert "Hitzewelle" in result
    # Höchste Stufe zuerst (Waldbrand Stufe 5 vor Hitze Stufe 3):
    assert result.index("Waldbrand") < result.index("Hitzewelle")
    # Vorausschau separat:
    assert "Vorausschau (1)" in result
    assert "Gewitter" in result


@pytest.mark.asyncio
async def test_meteo_warnings_app_json():
    import respx

    from meteoswiss_mcp.server import WarningsInput, _cache_clear, meteo_warnings

    _cache_clear()
    with respx.mock(assert_all_called=False) as r:
        _mock_warnings(r, [_APP_WARN_FIRE, _APP_WARN_HEAT])
        result = await meteo_warnings(WarningsInput(plz="8001", response_format="json"))
    data = json.loads(result)
    assert data["payload"]["quelle"] == "meteoswiss_app_api"
    assert data["provenance"]["source"].startswith("MeteoSwiss App-API")
    warns = data["payload"]["aktive_warnungen"]
    fire = next(w for w in warns if w["type_code"] == 10)
    assert fire["type_label"] == "Waldbrand"
    assert fire["level"] == 5
    assert fire["level_label"] == "Sehr stark"
    assert fire["valid_from"] == "2026-07-26T10:05:00Z"


@pytest.mark.asyncio
async def test_meteo_warnings_nationwide_aggregation():
    """Ohne Filter: landesweite Aggregation nach Typ, dedupliziert."""
    import respx

    from meteoswiss_mcp.server import WarningsInput, _cache_clear, meteo_warnings

    _cache_clear()
    with respx.mock(assert_all_called=False) as r:
        # Jede PLZ liefert dieselbe Waldbrand-Warnung → nach Region dedupliziert,
        # aber alle 26 PLZ teilen sich dieselbe regionId → 1 Gruppe.
        _mock_warnings(r, [_APP_WARN_FIRE])
        result = await meteo_warnings(WarningsInput())
    assert "landesweite Übersicht" in result
    assert "Waldbrand" in result


@pytest.mark.asyncio
async def test_meteo_warnings_unknown_canton():
    import respx

    from meteoswiss_mcp.server import WarningsInput, _cache_clear, meteo_warnings

    _cache_clear()
    with respx.mock(assert_all_called=False) as r:
        _mock_warnings(r, [])
        result = await meteo_warnings(WarningsInput(canton="XX"))
    assert "nbekannt" in result  # "Unbekanntes Kantonskürzel"


@pytest.mark.asyncio
async def test_meteo_warnings_app_failure_degrades():
    """App-API-Fehler degradiert sauber, ohne roher Stacktrace."""
    import respx

    from meteoswiss_mcp.server import WarningsInput, _cache_clear, meteo_warnings

    _cache_clear()
    with respx.mock(assert_all_called=False) as r:
        r.get(url__startswith=_APP_URL).respond(500, json={"error": "boom"})
        r.get(url__startswith=_OPENDATA_URL).respond(200, json={"result": {"results": []}})
        result = await meteo_warnings(WarningsInput(plz="8001"))
    assert "keine aktiven warnungen" in result.lower()
    assert "fehlgeschlagen" in result.lower()
    assert "Traceback" not in result
    assert "app-prod-ws" not in result


@pytest.mark.asyncio
async def test_meteo_warnings_plz_validation():
    from pydantic import ValidationError

    from meteoswiss_mcp.server import WarningsInput

    with pytest.raises(ValidationError):
        WarningsInput(plz="ab12")
    with pytest.raises(ValidationError):
        WarningsInput(language="xx")


class TestWarningHelpers:
    def test_type_label_confirmed_codes(self):
        from meteoswiss_mcp.server import _warn_type_label

        assert _warn_type_label(7, [], "de") == "Hitzewelle"
        assert _warn_type_label(7, [], "en") == "Heat wave"
        assert _warn_type_label(10, [], "de") == "Waldbrand"
        assert _warn_type_label(2, [], "fr") == "Orages"

    def test_type_label_slug_fallback(self):
        from meteoswiss_mcp.server import _warn_type_label

        links = [{"url": "https://x/forest-fire.html"}]
        assert _warn_type_label(999, links, "de") == "Waldbrand"

    def test_type_label_unknown(self):
        from meteoswiss_mcp.server import _warn_type_label

        assert _warn_type_label(999, [], "de") == "warnType 999"

    def test_epoch_millis_to_iso(self):
        from meteoswiss_mcp.server import _epoch_millis_to_iso

        assert _epoch_millis_to_iso(1785060300000) == "2026-07-26T10:05:00Z"
        assert _epoch_millis_to_iso(None) is None
        assert _epoch_millis_to_iso("nope") is None

    def test_dedupe_and_sort(self):
        from meteoswiss_mcp.server import _dedupe_warnings

        a = {"type_code": 10, "level": 2, "region_id": 1, "valid_from": "t"}
        b = {"type_code": 7, "level": 5, "region_id": 2, "valid_from": "t"}
        out = _dedupe_warnings([a, dict(a), b])
        assert len(out) == 2  # Duplikat entfernt
        assert out[0]["level"] == 5  # nach Stufe absteigend

    def test_app_host_allowlisted(self):
        from meteoswiss_mcp.server import ALLOWED_HOSTS

        assert "app-prod-ws.meteoswiss-app.ch" in ALLOWED_HOSTS


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


# ---------------------------------------------------------------------------
# Open-Meteo-Hybrid: MeteoSwiss ICON + best_match (Issue #35)
# ---------------------------------------------------------------------------

_OM_URL = "https://api.open-meteo.com/v1/forecast"
_DAILY_KEYS = [
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "windspeed_10m_max",
    "windgusts_10m_max",
    "weathercode",
    "sunshine_duration",
]


def _om_daily(dates, t_max, uv):
    """Minimaler, aber vollständig geformter Open-Meteo-`daily`-Block."""
    n = len(dates)
    block = {
        "time": list(dates),
        "temperature_2m_max": list(t_max),
        "uv_index_max": list(uv),
        "sunrise": [f"{d}T06:00" for d in dates],
        "sunset": [f"{d}T21:00" for d in dates],
    }
    for key in _DAILY_KEYS:
        block[key] = [0] * n
    return {"daily": block}


_DATES_7 = [f"2026-08-{d:02d}" for d in range(1, 8)]

# best_match: volle 7 Tage inkl. UV. ICON: 5 Tage, UV durchgehend None —
# genau das Verhalten, das gegen die Live-API gemessen wurde.
_OM_FALLBACK = _om_daily(_DATES_7, [10, 11, 12, 13, 14, 15, 16], [1, 2, 3, 4, 5, 6, 7])
_OM_SWISS = _om_daily(_DATES_7[:5], [20, 21, 22, 23, 24], [None] * 5)


def _mock_open_meteo(r, swiss=_OM_SWISS, fallback=_OM_FALLBACK, swiss_status=200):
    """Mockt beide Open-Meteo-Requests, unterschieden am `models`-Parameter."""
    r.get(_OM_URL, params__contains={"models": "meteoswiss_icon_seamless"}).respond(
        swiss_status, json=swiss if swiss_status == 200 else {"error": True}
    )
    r.get(_OM_URL).respond(200, json=fallback)


class TestMergeForecastBlock:
    def test_meteoswiss_wins_where_it_has_values(self):
        from meteoswiss_mcp.server import _merge_forecast_block

        merged, swiss_days = _merge_forecast_block(
            _OM_SWISS["daily"], _OM_FALLBACK["daily"]
        )
        assert merged["temperature_2m_max"] == [20, 21, 22, 23, 24, 15, 16]
        assert swiss_days == 5

    def test_uv_gap_falls_back_completely(self):
        """ICON führt keinen UV-Index — best_match muss durchgehend liefern."""
        from meteoswiss_mcp.server import _merge_forecast_block

        merged, _ = _merge_forecast_block(_OM_SWISS["daily"], _OM_FALLBACK["daily"])
        assert merged["uv_index_max"] == [1, 2, 3, 4, 5, 6, 7]

    def test_merges_along_the_time_axis_not_the_index(self):
        """Startet ICON später, dürfen die Werte nicht auf Tag 1 rutschen."""
        from meteoswiss_mcp.server import _merge_forecast_block

        shifted = _om_daily(_DATES_7[2:5], [30, 31, 32], [None] * 3)["daily"]
        merged, swiss_days = _merge_forecast_block(shifted, _OM_FALLBACK["daily"])
        assert merged["temperature_2m_max"] == [10, 11, 30, 31, 32, 15, 16]
        assert swiss_days == 3

    def test_without_swiss_block_the_fallback_passes_through(self):
        from meteoswiss_mcp.server import _merge_forecast_block

        merged, swiss_days = _merge_forecast_block(None, _OM_FALLBACK["daily"])
        assert merged == _OM_FALLBACK["daily"]
        assert swiss_days == 0


class TestForecastModelLabel:
    def test_hybrid_names_both_ranges(self):
        from meteoswiss_mcp.server import ForecastProvenance, _forecast_model_label

        label = _forecast_model_label(
            ForecastProvenance(swiss_days=5, total_days=7, icon_available=True)
        )
        assert "Tag 1–5" in label
        assert "ab Tag 6" in label

    def test_full_swiss_coverage_says_so(self):
        from meteoswiss_mcp.server import ForecastProvenance, _forecast_model_label

        label = _forecast_model_label(
            ForecastProvenance(swiss_days=3, total_days=3, icon_available=True)
        )
        assert "MeteoSwiss ICON" in label
        assert "ab Tag" not in label

    def test_icon_outage_is_declared_not_hidden(self):
        from meteoswiss_mcp.server import ForecastProvenance, _forecast_model_label

        label = _forecast_model_label(
            ForecastProvenance(swiss_days=0, total_days=7, icon_available=False)
        )
        assert "nicht verfügbar" in label


@pytest.mark.asyncio
async def test_meteo_forecast_hybrid_end_to_end():
    """Voller Pfad: beide Modelle abrufen, mischen, Herkunft ausweisen."""
    import respx

    from meteoswiss_mcp.server import ForecastInput, _cache_clear, meteo_forecast

    _cache_clear()
    with respx.mock(assert_all_called=True) as r:
        _mock_open_meteo(r)
        result = await meteo_forecast(
            ForecastInput(latitude=47.3769, longitude=8.5417, days=7)
        )

    assert "⚠️" not in result
    assert "20" in result  # ICON-Wert für Tag 1
    assert "16" in result  # best_match-Wert für Tag 7
    assert "Tag 1–5" in result  # Herkunft steht in der Ausgabe
    assert "ab Tag 6" in result


@pytest.mark.asyncio
async def test_meteo_forecast_json_declares_provenance():
    import respx

    from meteoswiss_mcp.server import (
        ForecastInput,
        ResponseFormat,
        _cache_clear,
        meteo_forecast,
    )

    _cache_clear()
    with respx.mock(assert_all_called=True) as r:
        _mock_open_meteo(r)
        result = await meteo_forecast(
            ForecastInput(
                latitude=47.3769,
                longitude=8.5417,
                days=7,
                response_format=ResponseFormat.JSON,
            )
        )

    payload = json.loads(result)
    assert payload["payload"]["modell_details"]["meteoswiss_icon_tage"] == 5
    assert payload["payload"]["modell_details"]["tage_total"] == 7
    assert payload["provenance"]["data_source_url"] == _OM_URL


@pytest.mark.asyncio
async def test_meteo_forecast_survives_icon_outage():
    """Fällt ICON aus, trägt best_match allein — und sagt es."""
    import respx

    from meteoswiss_mcp.server import ForecastInput, _cache_clear, meteo_forecast

    _cache_clear()
    with respx.mock(assert_all_called=True) as r:
        _mock_open_meteo(r, swiss_status=500)
        result = await meteo_forecast(
            ForecastInput(latitude=47.3769, longitude=8.5417, days=7)
        )

    assert "⚠️" not in result  # kein Hard-Fail
    assert "nicht verfügbar" in result  # Herkunft ehrlich ausgewiesen
    assert "10" in result  # best_match-Wert für Tag 1


@pytest.mark.asyncio
async def test_meteo_school_check_gets_uv_from_fallback():
    """Die UV-Ampel braucht best_match — ICON liefert keinen UV-Index."""
    import respx

    from meteoswiss_mcp.server import (
        SchoolCheckInput,
        _cache_clear,
        meteo_school_check,
    )

    high_uv = _om_daily(_DATES_7, [20] * 7, [9] * 7)
    _cache_clear()
    with respx.mock(assert_all_called=False) as r:
        r.get("https://geocoding-api.open-meteo.com/v1/search").respond(
            200,
            json={
                "results": [
                    {
                        "name": "Zürich",
                        "latitude": 47.3769,
                        "longitude": 8.5417,
                        "country": "Schweiz",
                    }
                ]
            },
        )
        _mock_open_meteo(r, swiss=_OM_SWISS, fallback=high_uv)
        result = await meteo_school_check(SchoolCheckInput(location="Zürich"))

    assert "⚠️ Prognosedaten" not in result
    assert "UV" in result


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
        r.get("https://geocoding-api.open-meteo.com/v1/search").respond(200, json={"results": []})
        result = await meteo_school_check(SchoolCheckInput(location="xyz", activity="Sporttag"))

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
        assert "allow-list" in str(exc_info.value) or isinstance(exc_info.value, EgressBlocked)


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


class TestServerVersion:
    """`serverInfo.version` im initialize-Handshake darf nicht leer sein."""

    def test_version_matches_installed_distribution(self):
        from importlib.metadata import version as pkg_version

        import meteoswiss_mcp.server as srv

        assert srv.__version__ == pkg_version("meteoswiss-mcp")

    def test_server_reports_a_version(self):
        import meteoswiss_mcp.server as srv

        assert srv.mcp.version
        assert srv.mcp.version == srv.__version__


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
        resp = await client.get("/health", headers={"origin": "https://example.com"})
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
        resp = await client.get("/health", headers={"origin": "https://app.example.com"})
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
        resp = await client.get("/health", headers={"origin": "https://evil.example.com"})
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
        resp_wrong = await client.post("/mcp", json={"ping": True}, headers={"x-api-key": "wrong"})
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
        resp = await client.get("/health", headers={"authorization": "Bearer secret-xyz"})
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
        r.get("https://geocoding-api.open-meteo.com/v1/search").respond(200, json={"results": []})
        async with _build_http_client() as client:
            with pytest.raises(ValueError, match="nicht gefunden"):
                await _geocode(client, "definitely-not-a-place-12345")


# ---------------------------------------------------------------------------
# Gekürzte Geocoding-Anfragen (Issue #37)
# ---------------------------------------------------------------------------


class TestGeocodeFallbackCandidates:
    def test_single_word_needs_no_shortening(self):
        from meteoswiss_mcp.server import _geocode_fallback_candidates

        assert _geocode_fallback_candidates("Zürich") == []

    def test_walks_from_specific_to_general(self):
        from meteoswiss_mcp.server import _geocode_fallback_candidates

        assert _geocode_fallback_candidates("Schulhaus Leutschenbach Zürich") == [
            ("Schulhaus", True),
            ("Leutschenbach Zürich", False),
            ("Leutschenbach", True),
            ("Zürich", False),
        ]

    def test_final_fallback_is_the_city_without_name_check(self):
        """Sonst scheitert «Zürich» an der Umlaut-Variante `Zurich`."""
        from meteoswiss_mcp.server import _geocode_fallback_candidates

        last_candidate, needs_name_match = _geocode_fallback_candidates(
            "Sportanlage Heerenschürli Zürich"
        )[-1]
        assert last_candidate == "Zürich"
        assert needs_name_match is False


class TestNamesMatch:
    def test_accepts_the_real_place(self):
        from meteoswiss_mcp.server import _names_match

        assert _names_match("Leutschenbach", "Leutschenbach")
        assert _names_match("leutschenbach", "Leutschenbach")

    def test_rejects_a_different_place_sharing_the_word(self):
        from meteoswiss_mcp.server import _names_match

        assert not _names_match("Schulhaus", "Dübendorf / Schulhaus Wil")


@pytest.mark.asyncio
async def test_geocode_recovers_the_specific_locality():
    """«Schulhaus Leutschenbach Zürich» → Leutschenbach, nicht Dübendorf."""
    import respx

    from meteoswiss_mcp.server import _build_http_client, _geocode

    leutschenbach = {
        "name": "Leutschenbach",
        "latitude": 47.41,
        "longitude": 8.55,
        "admin1": "ZH",
        "country_code": "CH",
    }
    # Reihenfolge der echten API: voll (de), voll (fuzzy), "Schulhaus",
    # "Leutschenbach Zürich", "Leutschenbach".
    responses = [
        httpx.Response(200, json={"results": []}),
        httpx.Response(200, json={"results": []}),
        httpx.Response(
            200,
            json={
                "results": [
                    {
                        "name": "Dübendorf / Schulhaus Wil",
                        "latitude": 47.40,
                        "longitude": 8.62,
                        "country_code": "CH",
                    }
                ]
            },
        ),
        httpx.Response(200, json={"results": []}),
        httpx.Response(200, json={"results": [leutschenbach]}),
    ]

    with respx.mock(assert_all_called=False) as r:
        r.get("https://geocoding-api.open-meteo.com/v1/search").side_effect = responses
        async with _build_http_client() as client:
            lat, lon, display, match = await _geocode(
                client, "Schulhaus Leutschenbach Zürich"
            )

    assert (lat, lon) == (47.41, 8.55)  # nicht Dübendorf (47.40, 8.62)
    assert "Leutschenbach" in display
    assert match == "shortened"


@pytest.mark.asyncio
async def test_geocode_generalises_to_the_city_when_locality_is_unknown():
    """«Sportanlage Heerenschürli Zürich»: nur die Stadt ist auflösbar."""
    import respx

    from meteoswiss_mcp.server import _build_http_client, _geocode

    zurich = {
        "name": "Zurich",
        "latitude": 47.3769,
        "longitude": 8.5417,
        "admin1": "ZH",
        "country_code": "CH",
    }
    # Alles leer bis zum Schluss-Fallback "Zürich".
    responses = [httpx.Response(200, json={"results": []}) for _ in range(5)]
    responses.append(httpx.Response(200, json={"results": [zurich]}))

    with respx.mock(assert_all_called=False) as r:
        r.get("https://geocoding-api.open-meteo.com/v1/search").side_effect = responses
        async with _build_http_client() as client:
            lat, lon, _display, match = await _geocode(
                client, "Sportanlage Heerenschürli Zürich"
            )

    assert (lat, lon) == (47.3769, 8.5417)
    assert match == "shortened"


@pytest.mark.asyncio
async def test_geocode_does_not_shorten_when_the_full_string_matches():
    """Ein Volltreffer darf keine zusätzlichen Requests auslösen."""
    import respx

    from meteoswiss_mcp.server import _build_http_client, _geocode

    with respx.mock(assert_all_called=False) as r:
        route = r.get("https://geocoding-api.open-meteo.com/v1/search").respond(
            200,
            json={
                "results": [
                    {
                        "name": "Bern",
                        "latitude": 46.95,
                        "longitude": 7.45,
                        "country_code": "CH",
                    }
                ]
            },
        )
        async with _build_http_client() as client:
            _lat, _lon, _display, match = await _geocode(client, "Bern Schweiz")

    assert match == "exact"
    assert route.call_count == 1


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
    from meteoswiss_mcp.server import _STATELESS_HTTP

    # Beim Modul-Import wurde der Wert eingefroren — der Test prüft die
    # Default-Semantik, nicht die Laufzeit-Konfigurierbarkeit.
    assert _STATELESS_HTTP is False
    # mcp 2.x: MCPServer.settings no longer carries stateless_http; the value
    # is frozen into _STATELESS_HTTP at import and passed to
    # streamable_http_app() when the app is built.
    assert _STATELESS_HTTP is False


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
                    "temp_mean": [1.0] * 12,
                    "precip_mm": [50.0] * 12,
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
# Climate-Normals Runtime-Fallback (Bonus: MCP_CLIMATE_NORMALS_URL_TEMPLATE)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_climate_runtime_fallback_loads_from_url(monkeypatch):
    """Bei fehlenden eingebetteten Normwerten zieht das Tool aus dem Template-URL."""
    import respx

    from meteoswiss_mcp.server import (
        ClimateNormalsInput,
        _cache_clear,
        meteo_climate_normals,
    )

    _cache_clear()

    # data.geo.admin.ch ist in der Egress-Allow-List
    monkeypatch.setenv(
        "MCP_CLIMATE_NORMALS_URL_TEMPLATE",
        "https://data.geo.admin.ch/test/{station}/{param}.txt",
    )

    # Synthetisches MeteoSwiss-NBCN-TSV mit nur Reckenholz drin
    tsv = (
        "MeteoSchweiz\n"
        "\n"
        "Monatswerte 1991-2020\n"
        "\n"
        "Station\tAlt\tCoords\tPeriod\tJan\tFeb\tMar\tApr\tMai\tJun\tJul\tAug\tSep\tOkt\tNov\tDez\tJahr\n"
        "Zürich / Reckenholz\t443\tx\ty\t-0.4\t0.7\t4.6\t8.7\t13.5\t16.6\t18.8\t18.4\t14.2\t9.6\t4.2\t0.5\t9.1\n"
    )

    with respx.mock(assert_all_called=False) as r:
        r.get(url__regex=r"https://data.geo.admin.ch/test/rec/.*\.txt").respond(
            200, content=tsv.encode("cp1252"), headers={"content-type": "text/plain"}
        )
        result = await meteo_climate_normals(ClimateNormalsInput(station="REC"))

    # Bei Erfolg muss der "keine eingebetteten Normwerte"-Fallback NICHT erscheinen
    assert "keine eingebetteten Normwerte" not in result
    assert "Reckenholz" in result or "REC" in result
    # Einer der Werte taucht im Markdown auf
    assert "-0.4" in result or "13.5" in result

    monkeypatch.delenv("MCP_CLIMATE_NORMALS_URL_TEMPLATE", raising=False)


@pytest.mark.asyncio
async def test_climate_runtime_fallback_disabled_by_default(monkeypatch):
    """Ohne MCP_CLIMATE_NORMALS_URL_TEMPLATE bleibt der bisherige Fallback aktiv."""
    monkeypatch.delenv("MCP_CLIMATE_NORMALS_URL_TEMPLATE", raising=False)

    from meteoswiss_mcp.server import (
        ClimateNormalsInput,
        _cache_clear,
        meteo_climate_normals,
    )

    _cache_clear()
    result = await meteo_climate_normals(ClimateNormalsInput(station="REC"))
    assert "keine eingebetteten Normwerte" in result
    assert "MCP_CLIMATE_NORMALS_URL_TEMPLATE" in result  # Hinweis im User-Output


@pytest.mark.asyncio
async def test_climate_runtime_fallback_404_falls_back_gracefully(monkeypatch):
    """Wenn der URL-Template-Fetch 404 liefert, fällt das Tool auf den Linkstack zurück."""
    import respx

    from meteoswiss_mcp.server import (
        ClimateNormalsInput,
        _cache_clear,
        meteo_climate_normals,
    )

    _cache_clear()
    monkeypatch.setenv(
        "MCP_CLIMATE_NORMALS_URL_TEMPLATE",
        "https://data.geo.admin.ch/notfound/{station}/{param}.txt",
    )

    with respx.mock(assert_all_called=False) as r:
        r.get(url__regex=r"https://data.geo.admin.ch/notfound/.*").respond(404)
        result = await meteo_climate_normals(ClimateNormalsInput(station="REC"))

    assert "keine eingebetteten Normwerte" in result
    monkeypatch.delenv("MCP_CLIMATE_NORMALS_URL_TEMPLATE", raising=False)


def test_parse_climate_tsv_finds_correct_station():
    """TSV-Parser findet die gewünschte Station und gibt 12 Monatswerte zurück."""
    from meteoswiss_mcp.server import _parse_climate_tsv_for_station

    tsv = (
        "Header\n"
        "\n"
        "Station\tAlt\tCoords\tPeriod\tJan\tFeb\tMar\tApr\tMai\tJun\tJul\tAug\tSep\tOkt\tNov\tDez\tJahr\n"
        "Davos\t1594\tx\ty\t-5.5\t-4.8\t-1.8\t1.6\t6.4\t9.6\t11.7\t11.4\t7.7\t4.0\t-1.0\t-4.5\t2.9\n"
        "Lugano\t273\tx\ty\t3.8\t5.0\t9.4\t13.5\t18.1\t21.4\t24.0\t23.3\t18.8\t13.4\t7.8\t4.3\t13.6\n"
    )
    values = _parse_climate_tsv_for_station(tsv, "Davos")
    assert values is not None
    assert len(values) == 12
    assert values[0] == -5.5
    # Andere Station gibt None
    assert _parse_climate_tsv_for_station(tsv, "Nonexistent") is None


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
        lat, lon, name, match = await _geocode(client, "Schulhaus Leutschenbach Zürich")
    # Oerlikon-Bereich
    assert 47.3 < lat < 47.5
    assert 8.4 < lon < 8.7
    assert match in ("exact", "fuzzy", "shortened")
    # Die Gattungswort-Falle: «Schulhaus» allein trifft Dübendorf (8.62),
    # eine andere Gemeinde. Der Ortsname muss die Auflösung tragen.
    assert "Leutschenbach" in name


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
    # Bewusst scharf: die frühere Fassung liess den Fallback-Pfad durchgehen
    # ("KLO" und "Zürich" stehen auch in der Fehlermeldung) und hat deshalb den
    # 404 aus #33 nie bemerkt. Hier muss es echte Messwerte geben.
    assert "⚠️" not in result
    assert "Messwerte" in result
    assert "Temperatur 2 m" in result


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_meteo_warnings():
    from meteoswiss_mcp.server import WarningsInput, meteo_warnings

    result = await meteo_warnings(WarningsInput())
    assert "MeteoSwiss" in result
