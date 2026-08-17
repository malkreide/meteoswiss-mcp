#!/usr/bin/env python3
"""Ingest MeteoSwiss-Klimanormwerte → data/climate-normals.json.

Unterstützt zwei Eingabeformen:

1. **Verzeichnis-Modus** (empfohlen für die offiziellen MeteoSwiss-TSV-Dumps):

    python scripts/ingest_climate_normals.py --dir /pfad/zu/files \\
        --out data/climate-normals.json

   Erwartet TSV-Files mit Namens-Pattern
   `climatereportsnormtables_<param>_<period>_<lang>.txt`, z.B.
   `climatereportsnormtables_tre200m0_19912020_de.txt`.

   Filter (defaults):
       - Periode 1991-2020 (anpassbar via --period)
       - Sprache de (anpassbar via --lang)
       - Parameter: nur tre200m0 / rre150m0 / sre000m0 (Temperatur,
         Niederschlag, Sonnenschein). Andere Parameter-Files werden geskippt.

2. **Einzeldatei-Modus** (für Custom-CSV/TSV):

    python scripts/ingest_climate_normals.py path/to/file.csv \\
        --param tre200m0 --out data/climate-normals.json

3. **Validation-Modus**:

    python scripts/ingest_climate_normals.py --validate data/climate-normals.json

Station-Mapping: Die MeteoSwiss-TSV verwendet ausgeschriebene Stations-Namen
(`Zürich / Kloten`), unsere SMN_STATIONS verwendet 3-Buchstaben-Codes (`KLO`).
STATION_NAME_TO_CODE im Code unten mappt die ~20 Server-Stationen. Stationen
ausserhalb dieses Mappings landen in der JSON unter ihrem Namen — sie sind
für den Server-Code unsichtbar, gehen aber nicht verloren.

Encoding: MeteoSwiss-Files sind cp1252-encoded; Decoder wird automatisch
darauf gesetzt.

Quellen:
    https://www.meteoswiss.admin.ch/climate/the-climate-of-switzerland/climate-normals.html
    https://opendata.swiss/de/dataset?q=meteoschweiz+klimanormwerte+1991
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

# Parameter-Code (MeteoSwiss) → unser JSON-Feld-Name
PARAMETER_MAP = {
    "tre200m0": "temp_mean",  # Lufttemperatur 2m, Monatsmittel °C
    "rre150m0": "precip_mm",  # Niederschlag Monatssumme mm
    "sre000m0": "sunshine_h",  # Sonnenscheindauer Monatssumme h
}

# Station-Name aus MeteoSwiss-TSV → 3-Buchstaben-SMN-Code (siehe SMN_STATIONS
# in src/meteoswiss_mcp/server.py). Wenn der Server um weitere Stationen erweitert
# wird, hier ergänzen.
STATION_NAME_TO_CODE = {
    "Zürich / Kloten": "KLO",
    "Zürich / MeteoSchweiz": "SMA",
    "Zürich / Fluntern": "SMA",  # Fluntern-Standort = SMA-Hauptsitz
    "Zürich / Affoltern": "REH",
    "Wädenswil": "WAE",
    "Aadorf / Tänikon": "TAE",
    "Bern / Zollikofen": "BER",
    "Interlaken": "INT",
    "Basel / Binningen": "BAS",
    "Luzern": "LUZ",
    "St. Gallen": "STG",
    "Davos": "DAV",
    "Chur": "CHU",
    "Sion": "SIO",
    "Lugano": "LUG",
    "Genève / Cointrin": "GVE",
    "Payerne": "PUY",
    "Jungfraujoch": "JUN",
    "Säntis": "SAE",
    "Pilatus": "PIL",
}

# Plausibilitäts-Ranges für die Schweiz (1991-2020 Klimanormen).
PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    "temp_mean": (-25.0, 30.0),
    "precip_mm": (0.0, 800.0),
    "sunshine_h": (10.0, 400.0),
}


def _parse_value(raw: str) -> float | None:
    """MeteoSwiss-Zellwert → float. Akzeptiert '-' / leer / NA als None."""
    raw = (raw or "").strip().replace(",", ".")
    if raw in {"", "-", "–", "NA", "NaN", "nan", "."}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _detect_delimiter(sample: str) -> str:
    """Tab vs Semikolon vs Komma erkennen."""
    counts = {sep: sample.count(sep) for sep in ("\t", ";", ",")}
    return max(counts, key=counts.get)


def parse_metswiss_tsv(text: str, param_code: str) -> dict[str, list[float]]:
    """Parse einen MeteoSwiss-TSV-Dump (ein Parameter, viele Stationen).

    Skip-Pattern:
    - Header-Zeilen (Department / Office / Creation date / leere Zeilen)
    - Spalten-Header beginnt mit "Station\t..." oder "Stazione\t..."

    Erwartet ab Daten-Beginn: `name<TAB>altitude<TAB>coords<TAB>period<TAB>Jan..Dez<TAB>Year`
    """
    delim = _detect_delimiter(text[:4096])
    canonical = PARAMETER_MAP.get(param_code)
    if canonical is None:
        raise ValueError(f"Unbekannter Parameter-Code: {param_code!r}")

    out: dict[str, list[float]] = {}
    in_data = False

    reader = csv.reader(text.splitlines(), delimiter=delim)
    for row in reader:
        if not row or all(not c.strip() for c in row):
            continue

        first = row[0].strip()

        if not in_data:
            # Header-Zeile erkennen: erste Spalte ist "Station" oder lokalisiert
            if first.lower() in {"station", "stazione"} and len(row) >= 14:
                in_data = True
            continue

        # Daten-Zeile: erwartet 4 Meta-Spalten + 12 Monate (+ optional Jahr)
        if len(row) < 16:
            continue
        station_name = first
        # row[1]=alt, row[2]=coords, row[3]=period, row[4..15]=Jan..Dez
        months = [_parse_value(c) for c in row[4:16]]
        if any(v is None for v in months):
            continue
        out[station_name] = [float(v) for v in months]  # type: ignore[arg-type]

    return out


_FILENAME_RE = re.compile(
    # Akzeptiert beide Schreibweisen: "climatereportsnormtables_" und
    # "climate-reports-normtables_" (offizielle MeteoSwiss-Variante mit Bindestrichen)
    r"climate-?reports-?normtables_"
    r"(?P<param>[a-z]{3}\d{3}[a-z]\d)"
    # Periode: "1991-2020" (mit Bindestrich, offiziell) oder "19912020"
    r"_(?P<period>\d{4}-?\d{4})"
    r"_(?P<lang>[a-z]{2})\.txt$",
    re.IGNORECASE,
)


def _normalize_period(p: str) -> str:
    """Normalisiert '1991-2020' → '19912020' für Vergleiche."""
    return p.replace("-", "")


def ingest_directory(src: Path, period: str, lang: str) -> dict[str, dict[str, list[float]]]:
    """Scant ein Verzeichnis und gibt {STATION_CODE: {param: [12 floats]}} zurück."""
    files = sorted(src.iterdir())
    relevant: list[tuple[Path, str]] = []

    for f in files:
        if not f.is_file():
            continue
        m = _FILENAME_RE.search(f.name)
        if not m:
            continue
        # Periode kann als "1991-2020" oder "19912020" geschrieben sein —
        # für den Vergleich beide normalisieren.
        if _normalize_period(m.group("period")) != _normalize_period(period):
            continue
        if m.group("lang") != lang:
            continue
        param = m.group("param").lower()
        if param not in PARAMETER_MAP:
            continue
        relevant.append((f, param))

    if not relevant:
        raise SystemExit(
            f"Keine passenden Files in {src} (Filter: period={period}, lang={lang}, "
            f"params={list(PARAMETER_MAP)}). Prüfe Pfad und Filter-Args."
        )

    print(f"Verarbeite {len(relevant)} Files aus {src}:", file=sys.stderr)
    for f, param in relevant:
        print(f"  - {f.name} ({param} → {PARAMETER_MAP[param]})", file=sys.stderr)

    result: dict[str, dict[str, list[float]]] = {}
    unmapped: set[str] = set()

    for f, param in relevant:
        # MeteoSwiss-Files sind cp1252; utf-8 wird gelegentlich auch ausgeliefert
        try:
            text = f.read_text(encoding="cp1252")
        except UnicodeDecodeError:
            text = f.read_text(encoding="utf-8")

        canonical = PARAMETER_MAP[param]
        per_station = parse_metswiss_tsv(text, param)

        for station_name, values in per_station.items():
            code = STATION_NAME_TO_CODE.get(station_name)
            if code is None:
                unmapped.add(station_name)
                continue
            result.setdefault(code, {})[canonical] = values

    if unmapped:
        print(
            f"\nHinweis: {len(unmapped)} Stationen ohne SMN-Code-Mapping (übersprungen):",
            file=sys.stderr,
        )
        for name in sorted(unmapped):
            print(f"  - {name}", file=sys.stderr)
        print(
            "  → Falls eine davon im Server-Code (SMN_STATIONS) erscheinen soll:",
            file=sys.stderr,
        )
        print(
            "    STATION_NAME_TO_CODE in scripts/ingest_climate_normals.py ergänzen.",
            file=sys.stderr,
        )

    return result


def parse_single_csv(text: str, param: str) -> dict[str, list[float]]:
    """Einzeldatei-Modus: für Custom-Quellen ohne Filename-Convention."""
    return parse_metswiss_tsv(text, param)


def validate_plausibility(data: dict[str, dict[str, list[float]]]) -> list[str]:
    warnings: list[str] = []
    for station, params in data.items():
        for key, values in params.items():
            lo, hi = PLAUSIBLE_RANGES.get(key, (None, None))
            if lo is None:
                continue
            for month_idx, v in enumerate(values, start=1):
                if v < lo or v > hi:
                    warnings.append(
                        f"{station}/{key}/Monat-{month_idx}: {v} ausserhalb [{lo}, {hi}]"
                    )
            if len(values) != 12:
                warnings.append(f"{station}/{key}: {len(values)} statt 12 Werte")

    def _yearly_mean(s: str) -> float | None:
        if s in data and "temp_mean" in data[s]:
            return sum(data[s]["temp_mean"]) / 12
        return None

    lug = _yearly_mean("LUG")
    dav = _yearly_mean("DAV")
    if lug is not None and dav is not None and lug <= dav:
        warnings.append(
            f"Plausibilität: LUG-Jahresmittel ({lug:.1f}°C) ≤ DAV-Jahresmittel ({dav:.1f}°C) — vertauscht?"
        )
    return warnings


def merge_with_existing(
    new_data: dict[str, dict[str, list[float]]],
    existing_path: Path | None,
) -> dict[str, dict[str, list[float]]]:
    if existing_path is None or not existing_path.exists():
        return new_data
    try:
        with existing_path.open(encoding="utf-8") as f:
            existing = json.load(f)
    except Exception as exc:
        print(f"warn: konnte bestehendes File nicht lesen ({exc}) — überschreibe", file=sys.stderr)
        return new_data
    result = {k: dict(v) for k, v in existing.items() if isinstance(v, dict)}
    for station, params in new_data.items():
        result.setdefault(station, {}).update(params)
    return result


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("input", nargs="?", help="Einzeldatei CSV/TSV (oder '-' für stdin).")
    p.add_argument("--dir", help="Verzeichnis mit MeteoSwiss-TSV-Dumps")
    p.add_argument("--period", default="19912020", help="Periode-Filter (default 19912020)")
    p.add_argument("--lang", default="de", help="Sprach-Filter (default de)")
    p.add_argument("--param", help="Parameter-Code (Einzeldatei-Modus erforderlich)")
    p.add_argument("--out", default="data/climate-normals.json", help="Output-Pfad")
    p.add_argument("--validate", help="Nur Validierung (kein Ingest)")
    p.add_argument("--merge", action="store_true", help="Mit --out mergen statt überschreiben")
    args = p.parse_args()

    if args.validate:
        with open(args.validate, encoding="utf-8") as f:
            data = json.load(f)
        warnings = validate_plausibility(data)
        if warnings:
            print("Validation-Warnungen:")
            for w in warnings:
                print(f"  - {w}")
            return 1
        print(f"OK: {len(data)} Stationen, alle Werte plausibel.")
        return 0

    if args.dir:
        parsed = ingest_directory(Path(args.dir), period=args.period, lang=args.lang)
    elif args.input:
        if not args.param:
            p.error("--param ist im Einzeldatei-Modus erforderlich")
        text = (
            sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8")
        )
        per_station = parse_single_csv(text, args.param)
        canonical = PARAMETER_MAP[args.param]
        parsed = {}
        for name, values in per_station.items():
            code = STATION_NAME_TO_CODE.get(name)
            if code:
                parsed.setdefault(code, {})[canonical] = values
    else:
        p.error("Brauche entweder --dir <pfad>, <input> --param, oder --validate")

    if args.merge:
        parsed = merge_with_existing(parsed, Path(args.out))

    warnings = validate_plausibility(parsed)
    if warnings:
        print("Validation-Warnungen:", file=sys.stderr)
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(
        json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    stations = ", ".join(sorted(parsed.keys()))
    print(f"\nOK: {len(parsed)} Stationen → {args.out}")
    print(f"  {stations}")
    return 0 if not warnings else 1


if __name__ == "__main__":
    raise SystemExit(main())
