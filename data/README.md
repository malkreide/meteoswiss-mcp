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

### Workflow (offizielle MeteoSwiss-TSV-Dumps)

MeteoSwiss publiziert die Klimanormwerte als ZIP-Archiv mit ~100 TSV-Files (ein File pro Parameter × Periode × Sprache, Pattern `climatereportsnormtables_<param>_<period>_<lang>.txt`). Das Skript scannt das ganze Verzeichnis und pickt automatisch nur die relevanten Files raus.

1. ZIP runterladen, irgendwo entpacken (z.B. `~/Downloads/klimanormwerte/`).
2. Verzeichnis-Scan:

   ```bash
   python scripts/ingest_climate_normals.py \
       --dir ~/Downloads/klimanormwerte \
       --out data/climate-normals.json
   ```

   Defaults: Periode `19912020`, Sprache `de`, nur Parameter `tre200m0` (Temperatur) / `rre150m0` (Niederschlag) / `sre000m0` (Sonnenschein). Andere Files werden ohne Warnung übersprungen.

3. Validierung:

   ```bash
   python scripts/ingest_climate_normals.py --validate data/climate-normals.json
   ```

   - Plausibilitäts-Ranges (Temp −25…+30 °C, Niederschlag 0…800 mm, Sonnenschein 10…400 h)
   - Cross-Station-Sanity (Lugano > Davos im Jahresmittel)

4. Lokal testen:

   ```bash
   MCP_CLIMATE_NORMALS_PATH=data/climate-normals.json meteoswiss-mcp
   ```

### Station-Mapping

Die MeteoSwiss-TSV listet Stationen mit Klartextnamen (`Zürich / Kloten`), unsere Tool-Schnittstelle nutzt 3-Buchstaben-Codes (`KLO`). Mapping liegt in `scripts/ingest_climate_normals.py` als `STATION_NAME_TO_CODE`. Stationen ausserhalb des Mappings werden geloggt und übersprungen — falls eine davon zukünftig im Server-Code (`SMN_STATIONS`) erscheinen soll, Mapping ergänzen.

### Single-File-Modus (für custom CSVs)

```bash
python scripts/ingest_climate_normals.py <datei.csv> --param tre200m0 \
    --out data/climate-normals.json --merge
```

### Wenn dein CSV anders aussieht

Das Skript verlangt die Spalten in dieser Reihenfolge: `Station, Parameter, Jan, Feb, …, Dez, Jahr`. Falls das opendata.swiss-CSV anders strukturiert ist (z.B. Long-Format mit `month`-Spalte), öffne ein Issue mit einer Sample-Zeile — Parser ergänzen wir dann hier.

## `climate-normals.example.json`

Beispiel-Skeleton mit Platzhalter-Werten — zeigt das Format, **nicht** für produktive Nutzung gedacht.
