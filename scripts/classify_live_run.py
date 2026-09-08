#!/usr/bin/env python3
"""Was hat der geplante Live-Lauf festgestellt — clear, finding oder unknown?

WARUM DAS EIN SKRIPT IST UND KEIN YAML-BLOCK
--------------------------------------------
`if: failure()` kennt zwei Antworten: rot und nicht rot. Ein Live-Lauf hat
drei, und die dritte ist die, die zaehlt:

  clear    Die Suite ist gelaufen und war gruen.
  finding  Die Suite ist gelaufen und etwas ist gefallen.
  unknown  Die Suite ist NICHT gelaufen — und niemand weiss, ob der Vertrag
           mit der Quelle noch haelt.

Ein gescheitertes `pip install`, ein Timeout, eine umbenannte Marke: alles
`unknown`, alles sieht unter `if: failure()` aus wie ein gebrochener Vertrag.
Und ein Lauf, in dem jeder Test uebersprungen wurde, sieht unter jedem
Exit-Code-Check aus wie Erfolg.

Diese Einordnung entscheidet, ob ein Issue aufgeht oder zugeht. Sie in einen
`run:`-Block zu schreiben hiesse, den einzigen Teil des Workflows, der etwas
behauptet, an die einzige Stelle zu legen, an der ihn niemand testen kann.
Deshalb steht sie hier, neben ihrem Test.

DER UEBERSPRUNGENE LAUF
-----------------------
Gemessen am 7.8.2026 an `swiss-transport-mcp`: Ohne `TRANSPORT_API_KEY`
ueberspringt die Live-Suite alle sechs Tests, und pytest endet mit 0. Ein
woechentlicher Job haette gemeldet: gruen. Geprueft haette er nichts — und ein
offenes Issue haette er zugemacht, mit einem Vergleich, den es nie gab.

`tests - skipped == 0` ist deshalb `unknown` und nicht `clear`. Ein Secret, das
niemand gesetzt hat, ist kein gruener Vertrag mit der Quelle; es ist gar keiner.

DIE QUELLE IST DAS JUNIT-XML, NICHT DER EXIT-CODE
-------------------------------------------------
Der Exit-Code von pytest sagt 0 fuer «alles gruen» und fuer «alles
uebersprungen» dasselbe. Das XML zaehlt Tests, Fehler, Fehlschlaege und
Uebersprungene getrennt, also wird es gelesen. Fehlt es, ist pytest gar nicht
bis zum Schreiben gekommen — auch das ist `unknown`, und zwar mit Grund.

WENN PYTEST NIE GESTARTET WURDE, IST DER EXIT-CODE EINE ERFINDUNG
-----------------------------------------------------------------
Bricht der Workflow ab, bevor er pytest aufruft — etwa weil ein Secret fehlt —,
dann hat er keinen Exit-Code zu melden. Wer an dieser Stelle einen erfindet,
schickt den Leser hinter einer Ursache her, die es nicht gibt: In
`swiss-ip-mcp` stand dort `--pytest-exit 127`, und diese Einordnung machte
daraus «pytest ist nicht bis zum Schreiben gekommen (Exit 127)» — 127 heisst
«command not found», also die Suche nach einem fehlenden Binary, wo in
Wahrheit nie ein Aufruf stattgefunden hatte.

Deshalb `--not-started`: Wer pytest nicht startet, sagt selbst warum, und diese
Einordnung reicht den Grund durch, statt einen zu konstruieren. Sie sieht dann
auch nicht ins XML — ein liegengebliebener Report aus einem frueheren Schritt
belegt nichts ueber einen Lauf, der nicht stattgefunden hat.

DER LAUF, DEN DIE QUELLE NIE BEANTWORTET HAT
--------------------------------------------
Der Absatz oben zaehlt einen Timeout zu `unknown`, und lange stimmte das nur
fuer den Timeout, der pytest selbst umbringt. Der andere kam am 3.9.2026 durch:
Zweimal hintereinander antwortete weder das Geocoding noch die Prognose, der
Server fing die `ConnectTimeout` ab und gab seinen Degradationstext zurueck,
die Zusicherung fiel darueber — und aus «keine Antwort» wurde ein
`finding`. Die Zusammenfassung darunter behauptete dann «Zweimal rot, also kein
Netzaussetzer» und schickte den Leser die Fixtures neu aufzeichnen. Am selben
Tag lieferten beide Endpunkte auf Nachfrage HTTP 200 in unter einer Sekunde;
aufzuzeichnen war nichts.

Ein gefallener Test wird deshalb nicht mehr nur gezaehlt, sondern gelesen:
Steht in seinem Fehlertext eine Transportausnahme, ist keine Antwort angekommen
und er belegt nichts ueber den Vertrag mit der Quelle. Sind ALLE gefallenen
Tests von dieser Art, ist der Lauf `unknown`. Sonst bleibt er `finding` — sonst
koennte sich ein echter Formatwechsel hinter einem gleichzeitigen Aussetzer
verstecken.

Aufruf:
    python scripts/classify_live_run.py live-report.xml
    python scripts/classify_live_run.py live-report.xml --pytest-exit 1
    python scripts/classify_live_run.py live-report.xml --not-started "kein Secret"

Gibt `state=...` und `reason=...` auf stdout aus und haengt beides an
`$GITHUB_OUTPUT` an, wenn die Variable gesetzt ist. Der Exit-Code ist immer 0:
Ueber rot oder gruen entscheidet der Workflow, nicht dieser Reporter.
"""

from __future__ import annotations

import argparse
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

CLEAR = "clear"
FINDING = "finding"
UNKNOWN = "unknown"

# Ausnahmenamen, bei denen GAR KEINE Antwort ankam. Es ist httpx'
# `TransportError`-Teilbaum (httpx 0.28), abgeschrieben statt importiert, weil
# diese Einordnung ohne die Projektabhaengigkeiten laufen koennen muss;
# `test_transportnamen_decken_httpx_ab` haelt die Liste an httpx fest, damit sie
# nicht still veraltet.
#
# Die Grenze ist gewaehlt, nicht geraten, und `CLAUDE.md` benennt sie:
# entscheidend ist nie der Statuscode, sondern ob die Quelle ueberhaupt
# geantwortet hat. Deshalb steht `HTTPStatusError` NICHT hier — ein 4xx ist
# eine Antwort und gehoert eingeordnet. `JSONDecodeError` ebenso wenig: Wer
# unlesbares Zeug schickt, hat geschickt, und genau dafuer gibt es diese Suite.
OHNE_ANTWORT = frozenset(
    {
        "CloseError",
        "ConnectError",
        "ConnectTimeout",
        "LocalProtocolError",
        "NetworkError",
        "PoolTimeout",
        "ProtocolError",
        "ProxyError",
        "ReadError",
        "ReadTimeout",
        "RemoteProtocolError",
        "TimeoutException",
        "TransportError",
        "UnsupportedProtocol",
        "WriteError",
        "WriteTimeout",
    }
)

_OHNE_ANTWORT_RE = re.compile(r"\b(" + "|".join(sorted(OHNE_ANTWORT)) + r")\b")


def _transportnamen(text: str) -> set[str]:
    """Welche Transportausnahmen stehen in diesem Fehlertext?

    Zwei Formen, beide aus demselben roten Lauf vom 3.9.2026: die rohe
    Ausnahme (`E   httpx.ConnectTimeout`) und die vom Server abgefangene,
    die als Text im Werkzeugergebnis landet (`⚠️ Prognosedaten nicht
    abrufbar: ReadTimeout`). `_sanitize_error` schreibt dort
    `exc.__class__.__name__`, also steht der Name in beiden Formen.
    """
    return set(_OHNE_ANTWORT_RE.findall(text))


def _gefallene(root: ET.Element) -> list[set[str]]:
    """Je gefallenem Testcase die Transportausnahmen in seinem Fehlertext.

    Nur Testcases MIT `failure`/`error`-Kind. Ein Report, der bloss die
    Summen in den Attributen fuehrt, liefert hier eine leere Liste — und das
    ist Absicht: Wer die Einzelfaelle nicht sieht, kann nicht behaupten, sie
    seien alle stumm geblieben.
    """
    gefallen = []
    for tc in root.iter("testcase"):
        kinder = [k for k in tc if k.tag in ("failure", "error")]
        if not kinder:
            continue
        namen: set[str] = set()
        for k in kinder:
            namen |= _transportnamen(f"{k.get('message') or ''}\n{k.text or ''}")
        gefallen.append(namen)
    return gefallen


def classify(
    report: Path,
    pytest_exit: int | None = None,
    not_started: str | None = None,
) -> tuple[str, str]:
    """(state, reason) aus einem JUnit-XML und optional dem pytest-Exit-Code.

    `not_started` schlaegt alles andere: Wurde pytest nie aufgerufen, sagt
    weder der Report noch ein Exit-Code etwas ueber den Lauf.
    """
    if not_started:
        return UNKNOWN, not_started
    if not report.is_file():
        return (
            UNKNOWN,
            f"kein Report unter {report} — pytest ist nicht bis zum Schreiben "
            "gekommen" + (f" (Exit {pytest_exit})" if pytest_exit is not None else ""),
        )
    try:
        root = ET.parse(report).getroot()
    except (ET.ParseError, OSError) as exc:
        return UNKNOWN, f"{report} ist nicht lesbar: {exc}"

    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    if not suites:
        return UNKNOWN, f"{report} enthaelt keine testsuite"

    def total(attr: str) -> int:
        return sum(int(s.get(attr) or 0) for s in suites)

    tests, failures, errors, skipped = (
        total("tests"),
        total("failures"),
        total("errors"),
        total("skipped"),
    )

    if failures or errors:
        grund = f"{failures} Fehlschlag/Fehlschlaege und {errors} Fehler von {tests} Test(s)"
        gefallen = _gefallene(root)
        stumm = [namen for namen in gefallen if namen]
        # `unknown` nur, wenn JEDER gefallene Testcase im Report steht und
        # JEDER von ihnen ohne Antwort blieb. Sonst `finding` — ein echter
        # Formatwechsel darf sich nicht hinter einem gleichzeitigen Aussetzer
        # verstecken, und ein Report ohne Einzelfaelle belegt nichts.
        vollstaendig = len(gefallen) >= failures + errors
        if gefallen and vollstaendig and len(stumm) == len(gefallen):
            namen = sorted({n for s in stumm for n in s})
            return (
                UNKNOWN,
                f"alle {len(gefallen)} gefallenen Test(s) blieben ohne Antwort der "
                f"Quelle ({', '.join(namen)}) — verglichen wurde nichts",
            )
        if stumm:
            namen = sorted({n for s in stumm for n in s})
            grund += f"; davon {len(stumm)} ohne Antwort der Quelle ({', '.join(namen)})"
        return FINDING, grund
    if tests == 0:
        return (
            UNKNOWN,
            "null Tests eingesammelt — die Marke oder die Dateien haben sich "
            "bewegt, und ein Erfolg ohne Test ist kein Erfolg",
        )
    if tests - skipped == 0:
        return (
            UNKNOWN,
            f"alle {tests} Test(s) uebersprungen — meist ein fehlendes Secret oder "
            "eine nicht erfuellte Vorbedingung. Geprueft wurde nichts",
        )
    return CLEAR, f"{tests - skipped} von {tests} Test(s) ausgefuehrt, alle gruen"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="classify_live_run")
    ap.add_argument("report", type=Path, help="Pfad zum JUnit-XML von pytest")
    ap.add_argument("--pytest-exit", type=int, default=None)
    ap.add_argument(
        "--not-started",
        default=None,
        help="Grund, warum pytest gar nicht erst aufgerufen wurde. Setzt `unknown`.",
    )
    args = ap.parse_args(argv)

    state, reason = classify(args.report, args.pytest_exit, args.not_started)
    print(f"state={state}")
    print(f"reason={reason}")

    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        # Zeilenumbruch raus, bevor der Grund in `$GITHUB_OUTPUT` geht: Die
        # `key=value`-Form endet an der ersten neuen Zeile, und was danach
        # steht, liest der Runner als naechstes Output. Ein Grund aus einer
        # Parser-Meldung oder aus `--not-started` koennte so ein `state=clear`
        # nachschieben und den roten Lauf gruen faerben.
        flat = " ".join(reason.split())
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"state={state}\n")
            fh.write(f"reason={flat}\n")
    # Immer 0: Ueber rot oder gruen entscheidet der Workflow.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
