# `data/` — Externe Datendateien

## `climate-normals.json`

JSON mit Klimanormwerten 1991–2020, geladen via `MCP_CLIMATE_NORMALS_PATH`. Merged sich mit den eingebetteten 5 Stationen (KLO/SMA/BER/LUG/GVE) — Datei gewinnt bei Konflikten.

### Stationen, für die wir Werte wollen (Prio: hoch → niedrig)

| Code | Name | Höhe | Status |
|---|---|---|---|
| `KLO` | Zürich/Kloten | 436 m | ✅ eingebettet |
| `SMA` | Zürich/MeteoSchweiz | 556 m | ✅ eingebettet |
| `BER` | Bern/Zollikofen | 552 m | ✅ eingebettet |
| `LUG` | Lugano | 273 m | ✅ eingebettet |
| `GVE` | Genf/Cointrin | 411 m | ✅ eingebettet |
| `BAS` | Basel/Binningen | 317 m | ⬜ TODO |
| `LUZ` | Luzern | 454 m | ⬜ TODO |
| `STG` | St. Gallen | 775 m | ⬜ TODO |
| `SIO` | Sitten/Sion | 482 m | ⬜ TODO |
| `CHU` | Chur | 556 m | ⬜ TODO |
| `INT` | Interlaken | 577 m | ⬜ TODO |
| `PUY` | Payerne | 491 m | ⬜ TODO |
| `WAE` | Wädenswil | 485 m | ⬜ TODO |
| `TAE` | Tänikon | 539 m | ⬜ TODO |
| `REC` | Zürich/Reckenholz | 443 m | ⬜ TODO |
| `REH` | Zürich/Affoltern | 444 m | ⬜ TODO |
| `DAV` | Davos | 1594 m | ⬜ TODO (Bergstation) |
| `JUN` | Jungfraujoch | 3571 m | ⬜ TODO (Bergstation) |
| `SAE` | Säntis | 2501 m | ⬜ TODO (Bergstation) |
| `PIL` | Pilatus | 2106 m | ⬜ TODO (Bergstation) |

### Quelle der offiziellen Werte

- Offizielle Klimanormwerte-Seite: <https://www.meteoswiss.admin.ch/climate/the-climate-of-switzerland/climate-normals.html>
- opendata.swiss-Suche: <https://opendata.swiss/de/dataset?q=meteoschweiz+klimanormwerte+1991>
- Üblicher CSV-Download über die Detailseite des Datensatzes («Ressourcen» → CSV-Link)

### Workflow

1. CSV von MeteoSwiss runterladen, z.B. `klimanormwerte_1991-2020.csv` (Wide-Format, Semikolon-Trenner, Parameter pro Zeile).
2. `python scripts/ingest_climate_normals.py <pfad-zur-csv> --out data/climate-normals.json`
   - Parser akzeptiert die typische Wide-Form: `Station;Parameter;Jan;…;Dez;Jahr`
   - Konvertiert MeteoSwiss-Parameter-Codes: `tre200m0`→`temp_mean`, `rre150m0`→`precip_mm`, `sre000m0`→`sunshine_h`
   - Andere Parameter (Druck, Feuchte, Wind) werden ignoriert
3. Validierung: `python scripts/ingest_climate_normals.py --validate data/climate-normals.json`
   - Plausibilitäts-Ranges (z.B. Temperatur −25…+28 °C)
   - Cross-Station-Sanity (Lugano > Davos im Jahresmittel)
4. Lokal testen: `MCP_CLIMATE_NORMALS_PATH=data/climate-normals.json meteoswiss-mcp` → die zusätzlichen Stationen sind in `meteo_climate_normals` verfügbar.

### Wenn dein CSV anders aussieht

Das Skript verlangt die Spalten in dieser Reihenfolge: `Station, Parameter, Jan, Feb, …, Dez, Jahr`. Falls das opendata.swiss-CSV anders strukturiert ist (z.B. Long-Format mit `month`-Spalte), öffne ein Issue mit einer Sample-Zeile — Parser ergänzen wir dann hier.

## `climate-normals.example.json`

Beispiel-Skeleton mit Platzhalter-Werten — zeigt das Format, **nicht** für produktive Nutzung gedacht.
