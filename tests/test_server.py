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
    assert "stationen" in data
    assert "KLO" in data["stationen"]


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
    assert data["station"] == "SMA"
    assert len(data["normwerte"]["temp_mean"]) == 12


@pytest.mark.asyncio
async def test_meteo_warnings_markdown():
    from meteoswiss_mcp.server import WarningsInput, meteo_warnings

    result = await meteo_warnings(WarningsInput(canton="ZH"))
    assert "MeteoSwiss" in result
    assert "warnings" in result.lower() or "warnung" in result.lower()


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
