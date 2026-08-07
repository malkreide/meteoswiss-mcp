#!/usr/bin/env python3
"""Zeichnet die Unit-Test-Fixtures von den echten Quellen auf.

    python scripts/record_fixtures.py

WARUM ES DIESES SKRIPT GIBT. Ein handgeschriebener Mock kodiert die Annahme
seines Autors und kann sie deshalb prinzipiell nicht widerlegen: Produktivcode
und Fixture stammen aus demselben Kopf, derselben Stunde, derselben Lektuere der
Doku. Wo beide irren, irren beide gleich, und die Suite bleibt gruen.

Ohne Aufzeichnungsdatum ist «aufgezeichnet» nach zwei Jahren von «ausgedacht»
nicht mehr zu unterscheiden — die Datei sieht gleich aus.

DER STAC-ITEM-AUSSCHNITT IST DER WICHTIGSTE. `_select_smn_now_asset` waehlt
bewusst nur `_t_now.csv` bzw. `_t_recent.csv` und lehnt jeden Fallback ab, weil
im selben Asset-Dict auch Tages-, Monats-, Jahres- und Jahrzehnt-Historien
liegen — «die als aktuelle Beobachtung auszugeben waere schlimmer als ein
sauberer Fehler», sagt der Docstring. Die handgeschriebene Fixture fuehrte vier
Assets; die Quelle liefert **16**, darunter `_h_historical_1980-1989.csv` bis
`_h_historical_2020-2029.csv`. Der Selektor wurde also nie gegen die Ablenker
geprueft, gegen die es ihn gibt. Das Item wird deshalb **vollstaendig**
aufgezeichnet.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

STAC = "https://data.geo.admin.ch/api/stac/v1"
APP = "https://app-prod-ws.meteoswiss-app.ch/v1"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

STATION = "klo"
PLZ = "800100"
# Zuerich, fest statt «hier»: Eine Fixture, deren Auswahl vom Ort des Laufs
# abhaengt, erzeugt bei jedem Aufzeichnen einen anderen Diff.
LAT, LON = 47.3769, 8.5417
SMN_ROWS = 3


def record() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    recorded_at = datetime.now(UTC).strftime("%Y-%m-%d")
    entries: list[dict] = []

    def write(name: str, text: str, url: str, rule: str) -> None:
        (FIXTURES / name).write_text(text, encoding="utf-8")
        entries.append(
            {
                "name": name,
                "url": url,
                "rule": rule,
                "bytes": len(text.encode("utf-8")),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            }
        )
        print(f"ok  {name:<26} {len(text.encode('utf-8')):>7} B")

    with httpx.Client(timeout=90.0, follow_redirects=True) as c:
        # 1) STAC-Item — vollstaendig, siehe Modul-Docstring.
        url = f"{STAC}/collections/ch.meteoschweiz.ogd-smn/items/{STATION}"
        r = c.get(url)
        r.raise_for_status()
        item = r.json()
        assets = item.get("assets", {})
        now_assets = [k for k in assets if k.endswith("_t_now.csv")]
        distractors = [k for k in assets if "_historical" in k or k.endswith(("_m.csv", "_y.csv"))]
        if not now_assets:
            raise SystemExit(
                f"STAC {STATION}: kein *_t_now.csv unter {len(assets)} Assets — "
                "der Selektor haette nichts zu waehlen"
            )
        if not distractors:
            # Ohne Ablenker prueft der Selektor-Test nichts: Er waehlt dann aus
            # einer Menge, in der jede Wahl richtig waere.
            raise SystemExit(
                f"STAC {STATION}: keine Historik-/Monats-/Jahres-Assets mehr — "
                "der Selektor-Test bestuende leer, Auswahlregel pruefen"
            )
        write(
            "stac_item_klo.json",
            json.dumps(item, ensure_ascii=False, indent=2) + "\n",
            url,
            f"vollstaendig; {len(assets)} Assets, davon {len(distractors)} "
            "Ablenker (Historik/Monat/Jahr), die der Selektor ablehnen muss",
        )

        # 2) Die 10-Minuten-CSV, auf wenige Zeilen gekuerzt.
        now_href = assets[now_assets[0]]["href"]
        r = c.get(now_href)
        r.raise_for_status()
        lines = r.text.splitlines()
        header, rows = lines[0], [x for x in lines[1:] if x.strip()]
        if not rows:
            raise SystemExit(f"{now_href}: keine Datenzeile")
        kept = rows[-SMN_ROWS:]
        n_cols = len(header.split(";"))
        empty_cells = sum(1 for x in kept for cell in x.split(";") if cell == "")
        write(
            "smn_now.csv",
            header + "\n" + "\n".join(kept) + "\n",
            now_href,
            f"Kopfzeile unveraendert ({n_cols} Spalten — die handgeschriebene "
            f"Vorgaengerin hatte 7); die letzten {len(kept)} von {len(rows)} "
            f"Zeilen. Enthaelt {empty_cells} leere Zellen, wie die Quelle sie "
            "liefert",
        )

        # 3) Die App-Antwort (Warnungen, Vorhersage).
        url = f"{APP}/plzDetail?plz={PLZ}"
        r = c.get(url)
        r.raise_for_status()
        detail = r.json()
        for key in ("warnings", "currentWeather", "forecast"):
            if key not in detail:
                raise SystemExit(f"plzDetail: Feld {key!r} fehlt — Antwortform geaendert")
        write(
            "app_plz_detail.json",
            json.dumps(detail, ensure_ascii=False, indent=2) + "\n",
            url,
            f"vollstaendig fuer PLZ {PLZ}; Felder "
            f"{sorted(detail)} — «warnings» mit {len(detail.get('warnings') or [])} Eintrag/Eintraegen",
        )

        # 4) Open-Meteo als Fallback-Quelle.
        params = {
            "latitude": LAT,
            "longitude": LON,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
            "timezone": "Europe/Zurich",
            "forecast_days": 7,
        }
        r = c.get(OPEN_METEO, params=params)
        r.raise_for_status()
        forecast = r.json()
        daily = forecast.get("daily") or {}
        if len(daily.get("time", [])) < 7:
            raise SystemExit("open-meteo: weniger als 7 Tage geliefert")
        write(
            "open_meteo_forecast.json",
            json.dumps(forecast, ensure_ascii=False, indent=2) + "\n",
            str(r.request.url),
            f"vollstaendig; {len(daily['time'])} Tage fuer Zuerich "
            f"({LAT}, {LON}), Variablen {sorted(daily)}",
        )

    _write_provenance(recorded_at, entries)
    print(f"\nPROVENANCE.md geschrieben, Aufzeichnungsdatum {recorded_at}")
    return 0


def _write_provenance(recorded_at: str, entries: list[dict]) -> None:
    lines = [
        "# Herkunft der Fixtures",
        "",
        "**Erzeugt von `scripts/record_fixtures.py`. Nicht von Hand pflegen.**",
        "",
        f"Aufgezeichnet am **{recorded_at}** von den drei Quellen dieses Servers:",
        f"`{STAC}`, `{APP}` und `{OPEN_METEO}`.",
        "",
        "Ohne Datum ist «aufgezeichnet» nach zwei Jahren von «ausgedacht» nicht",
        "mehr zu unterscheiden — die Datei sieht gleich aus.",
        "",
        "**Wetterdaten altern schnell.** Diese Fixtures belegen die *Form* der",
        "Antwort und einen datierten Ausschnitt ihres Inhalts — Temperaturen und",
        "Warnungen darin sind der Stand des Aufzeichnungstags und keine Aussage",
        "ueber heute. Zusicherungen in den Tests leiten ihre Erwartungen deshalb",
        "aus der Fixture ab, statt Zahlen hineinzuschreiben.",
        "",
    ]
    for e in entries:
        lines += [
            f"## `{e['name']}`",
            "",
            f"- **Quelle:** `{e['url']}`",
            f"- **Aufgezeichnet:** {recorded_at}",
            f"- **Auswahl:** {e['rule']}",
            f"- **Groesse:** {e['bytes']} B",
            f"- **SHA-256:** `{e['sha256']}`",
            "",
        ]
    (FIXTURES / "PROVENANCE.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    try:
        raise SystemExit(record())
    except httpx.HTTPError as exc:
        print(f"FEHLER: Quelle nicht erreichbar: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
