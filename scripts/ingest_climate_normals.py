#!/usr/bin/env python3
"""Ingest MeteoSwiss-Klimanormwerte-CSV → climate-normals.json.

Verwendung:
    # Aus Datei
    python scripts/ingest_climate_normals.py path/to/normals.csv --out data/climate-normals.json

    # Aus stdin (z.B. via curl + tee, falls Sandbox-Netzwerk fehlt)
    cat normals.csv | python scripts/ingest_climate_normals.py - --out data/climate-normals.json

    # Nur validieren (Datei muss existieren)
    python scripts/ingest_climate_normals.py --validate data/climate-normals.json

Erwartetes CSV-Schema (MeteoSwiss-OGD Wide-Format):
    Station;Parameter;Jan;Feb;Mar;Apr;Mai;Jun;Jul;Aug;Sep;Okt;Nov;Dez;Jahr

Akzeptiert sowohl deutsche (Mai/Okt/Dez) als auch englische (May/Oct/Dec)
Monatskürzel. Erste Spalte ist Station-Code, zweite Parameter-Code.

Parameter-Mapping:
    tre200m0  → temp_mean       (Lufttemperatur 2m, Monatsmittel °C)
    rre150m0  → precip_mm       (Niederschlag Monatssumme mm)
    sre000m0  → sunshine_h      (Sonnenscheindauer Monatssumme h)

Andere Parameter werden ignoriert (typische CSVs enthalten auch Druck,
Feuchte, Wind etc., die wir hier nicht abbilden).

Quelle:
    https://www.meteoswiss.admin.ch/climate/the-climate-of-switzerland/climate-normals.html
    https://opendata.swiss/de/dataset?q=meteoschweiz+klimanormwerte+1991
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

PARAMETER_MAP = {
    "tre200m0": "temp_mean",
    "rre150m0": "precip_mm",
    "sre000m0": "sunshine_h",
}

# Plausibilitäts-Ranges für die Schweiz (1991-2020 Klimanormen).
# Falls Werte ausserhalb landen, wird die Datei als suspekt geflaggt.
PLAUSIBLE_RANGES: dict[str, tuple[float, float]] = {
    "temp_mean":  (-25.0, 28.0),    # Jungfraujoch-Januar ≈ -14, Lugano-Juli ≈ +24
    "precip_mm":  (0.0, 600.0),     # Säntis-Monat kann 300+ haben, lassen Puffer
    "sunshine_h": (10.0, 350.0),    # Jungfraujoch-Dezember knapp, Lugano-Juli viel
}


def _parse_value(raw: str) -> float | None:
    """Konvertiert MeteoSwiss-Zellwert in float. Akzeptiert '-' / '' als None."""
    raw = (raw or "").strip().replace(",", ".")
    if raw in {"", "-", "–", "NA", "NaN", "nan", "."}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def parse_csv(text: str) -> dict[str, dict[str, list[float]]]:
    """Parse Wide-Format-CSV in {STATION: {param: [12 floats]}}."""
    # Detektiere Delimiter (MeteoSwiss-OGD: ';', manche Exports: ',')
    sample = text[:2048]
    delim = ";" if sample.count(";") > sample.count(",") else ","

    reader = csv.reader(text.splitlines(), delimiter=delim)
    rows = list(reader)
    if len(rows) < 2:
        raise ValueError("CSV scheint leer oder ohne Datenzeilen.")

    header = [c.strip().lower() for c in rows[0]]
    # Erwartet: erste Spalte Station, zweite Parameter, danach 12 Monate (+ optional Jahr)
    if len(header) < 14:
        raise ValueError(
            f"Zu wenige Spalten ({len(header)}); erwartet ≥14 "
            "(Station, Parameter, Jan..Dez)"
        )

    out: dict[str, dict[str, list[float | None]]] = {}
    for line_no, row in enumerate(rows[1:], start=2):
        if not row or all(not c.strip() for c in row):
            continue
        if len(row) < 14:
            print(
                f"warn: Zeile {line_no} hat nur {len(row)} Spalten — übersprungen",
                file=sys.stderr,
            )
            continue
        station = row[0].strip().upper()
        param = row[1].strip().lower()

        canonical = PARAMETER_MAP.get(param)
        if canonical is None:
            continue  # nicht-relevanter Parameter

        values = [_parse_value(c) for c in row[2:14]]
        if any(v is None for v in values):
            print(
                f"warn: {station}/{canonical} Zeile {line_no}: enthält leere Werte — übersprungen",
                file=sys.stderr,
            )
            continue
        out.setdefault(station, {})[canonical] = [float(v) for v in values]  # type: ignore[arg-type]

    # Validierung: pro Station mindestens 1 Parameter mit 12 Monatswerten
    cleaned: dict[str, dict[str, list[float]]] = {}
    for station, params in out.items():
        valid = {
            k: v for k, v in params.items()
            if isinstance(v, list) and len(v) == 12 and all(isinstance(x, float) for x in v)
        }
        if valid:
            cleaned[station] = valid
    return cleaned


def validate_plausibility(data: dict[str, dict[str, list[float]]]) -> list[str]:
    """Plausibilitäts-Checks. Gibt Liste der Warnungen zurück (leer = alles OK)."""
    warnings: list[str] = []

    for station, params in data.items():
        for key, values in params.items():
            lo, hi = PLAUSIBLE_RANGES.get(key, (None, None))
            if lo is None:
                continue
            for month_idx, v in enumerate(values, start=1):
                if v < lo or v > hi:
                    warnings.append(
                        f"{station}/{key}/Monat-{month_idx}: {v} ausserhalb "
                        f"[{lo}, {hi}] — plausibel?"
                    )
            if len(values) != 12:
                warnings.append(f"{station}/{key}: {len(values)} statt 12 Werte")

    # Cross-station-Check: Lugano sollte wärmer sein als Davos im Jahresmittel.
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

    # Existierendes wird übernommen, neue Werte überschreiben pro Station/Parameter
    result = {k: dict(v) for k, v in existing.items() if isinstance(v, dict)}
    for station, params in new_data.items():
        result.setdefault(station, {}).update(params)
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "input",
        nargs="?",
        help="CSV-Datei (oder '-' für stdin). Nicht angeben + --validate für Reine Datei-Validierung.",
    )
    p.add_argument("--out", default="data/climate-normals.json", help="Output-JSON-Pfad")
    p.add_argument("--validate", help="Nur validieren (kein Ingest)")
    p.add_argument("--merge", action="store_true", help="Mit bestehender --out-Datei mergen statt überschreiben")
    args = p.parse_args()

    # Validation-only Modus
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

    if not args.input:
        p.error("Brauche entweder <input> oder --validate")

    # Read input
    if args.input == "-":
        text = sys.stdin.read()
    else:
        text = Path(args.input).read_text(encoding="utf-8")

    parsed = parse_csv(text)
    if not parsed:
        print("Fehler: 0 Stationen aus CSV extrahiert. Prüfe Format und Parameter-Codes.", file=sys.stderr)
        return 2

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
    print(f"OK: {len(parsed)} Stationen → {args.out}")
    print(f"  {stations}")
    return 0 if not warnings else 1


if __name__ == "__main__":
    raise SystemExit(main())
