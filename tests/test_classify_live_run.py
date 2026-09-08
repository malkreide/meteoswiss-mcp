#!/usr/bin/env python3
"""Tests fuer scripts/classify_live_run.py — die drei Antworten eines Live-Laufs.

Die Einordnung entscheidet, ob ein Issue aufgeht oder zugeht. Genau deshalb
steht sie in einem Skript und nicht in einem `run:`-Block: So kann jemand sie
gegen die Faelle halten, aus denen sie entstanden ist.

Der wichtigste Fall ist `test_alle_uebersprungen_ist_nicht_gruen`. Gemessen am
7.8.2026 an `swiss-transport-mcp`: Ohne `TRANSPORT_API_KEY` ueberspringt die
Live-Suite alle sechs Tests und pytest endet mit 0. Ein Job, der das als gruen
bucht, schliesst ein offenes Issue mit einem Vergleich, den es nie gab.

Kein Netz. Bis auf `HttpxDriftTest`, der die abgeschriebene Namensliste
gegen httpx haelt, auch nur Standardbibliothek.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import classify_live_run as clr  # noqa: E402


def write(tmp: Path, xml: str) -> Path:
    path = tmp / "live-report.xml"
    path.write_text(xml, encoding="utf-8")
    return path


def suite(tests: int, failures: int = 0, errors: int = 0, skipped: int = 0) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<testsuites><testsuite name="pytest" tests="{tests}" failures="{failures}" '
        f'errors="{errors}" skipped="{skipped}"></testsuite></testsuites>'
    )


def faelle(*faelle_: tuple[str, str | None]) -> str:
    """Report MIT Einzelfaellen: (Testname, Fehlertext oder None fuer gruen).

    So schreibt pytest wirklich — die aggregierten Attribute allein sind die
    Form, die `suite()` baut, und beide muessen eingeordnet werden koennen.
    """
    from xml.sax.saxutils import escape, quoteattr

    kaputt = [(n, t) for n, t in faelle_ if t is not None]
    teile = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<testsuites><testsuite name="pytest" tests="{len(faelle_)}" '
        f'failures="{len(kaputt)}" errors="0" skipped="0">',
    ]
    for name, text in faelle_:
        if text is None:
            teile.append(f'<testcase name="{name}"/>')
        else:
            kopf = text.splitlines()[0]
            teile.append(
                f'<testcase name="{name}">'
                f"<failure message={quoteattr(kopf)}>{escape(text)}</failure>"
                f"</testcase>"
            )
    teile.append("</testsuite></testsuites>")
    return "".join(teile)


def cli(*extra: str) -> tuple[str, str]:
    """Ruft `main` mit gesetztem $GITHUB_OUTPUT und liest zurueck, was ankam."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "gh-output"
        out.write_text("", encoding="utf-8")
        os.environ["GITHUB_OUTPUT"] = str(out)
        try:
            clr.main([str(Path(tmp) / "live-report.xml"), *extra])
        finally:
            del os.environ["GITHUB_OUTPUT"]
        written = out.read_text(encoding="utf-8")
    werte = dict(line.split("=", 1) for line in written.splitlines() if line)
    return werte["state"], werte["reason"]


class ClassifyTest(unittest.TestCase):
    def _state(self, xml: str) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            return clr.classify(write(Path(tmp), xml))

    def test_alles_gruen_ist_clear(self):
        state, reason = self._state(suite(tests=3))
        self.assertEqual(state, clr.CLEAR)
        self.assertIn("3 von 3", reason)

    def test_ein_fehlschlag_ist_ein_finding(self):
        state, _ = self._state(suite(tests=3, failures=1))
        self.assertEqual(state, clr.FINDING)

    def test_ein_fehler_ist_ein_finding(self):
        state, _ = self._state(suite(tests=3, errors=1))
        self.assertEqual(state, clr.FINDING)

    def test_alle_uebersprungen_ist_nicht_gruen(self):
        """swiss-transport-mcp ohne TRANSPORT_API_KEY: 6 von 6 uebersprungen."""
        state, reason = self._state(suite(tests=6, skipped=6))
        self.assertEqual(state, clr.UNKNOWN)
        self.assertIn("uebersprungen", reason)

    def test_teilweise_uebersprungen_ist_gruen(self):
        """Ein einzelner Skip ist eine Entscheidung im Test, kein Ausfall."""
        state, reason = self._state(suite(tests=6, skipped=5))
        self.assertEqual(state, clr.CLEAR)
        self.assertIn("1 von 6", reason)

    def test_null_tests_ist_kein_erfolg(self):
        """Die Marke umbenannt, die Dateien verschoben — pytest meldet trotzdem 0."""
        state, reason = self._state(suite(tests=0))
        self.assertEqual(state, clr.UNKNOWN)
        self.assertIn("null Tests", reason)

    def test_ein_fehlschlag_schlaegt_uebersprungene(self):
        state, _ = self._state(suite(tests=6, skipped=5, failures=1))
        self.assertEqual(state, clr.FINDING)

    def test_mehrere_testsuites_werden_summiert(self):
        xml = (
            "<testsuites>"
            '<testsuite tests="2" failures="0" errors="0" skipped="2"/>'
            '<testsuite tests="3" failures="0" errors="0" skipped="0"/>'
            "</testsuites>"
        )
        state, _ = self._state(xml)
        self.assertEqual(state, clr.CLEAR)

    def test_eine_einzelne_testsuite_ohne_huelle(self):
        xml = '<testsuite tests="2" failures="0" errors="0" skipped="0"/>'
        state, _ = self._state(xml)
        self.assertEqual(state, clr.CLEAR)


class OhneAntwortTest(unittest.TestCase):
    """Ein Fehlschlag, bei dem die Quelle nie geantwortet hat, ist kein Befund.

    Der Lauf vom 3.9.2026 (`actions/runs/33740596284`): zweimal rot, beide Male
    nur `ConnectTimeout`/`ReadTimeout` — und beide Male `finding`. Die
    Zusammenfassung behauptete daraufhin «Zweimal rot, also kein Netzaussetzer»
    und verwies auf `scripts/record_fixtures.py`. Nachgefragt lieferten
    Geocoding und Prognose am selben Tag HTTP 200 in unter einer Sekunde.
    """

    def _state(self, xml: str) -> tuple[str, str]:
        with tempfile.TemporaryDirectory() as tmp:
            return clr.classify(write(Path(tmp), xml))

    # Woertlich aus dem roten Lauf. Die abgefangene Form: Der Server macht aus
    # der Ausnahme seinen Degradationstext, die Zusicherung faellt darueber.
    ABGEFANGEN = (
        "def test_live_forecast_zurich():\n"
        '>       assert "°C" in result\n'
        "E       AssertionError: assert '°C' in '⚠️ Prognosedaten nicht "
        "abrufbar: ReadTimeout\\n\\n**Direktzugang MeteoSwiss:**'"
    )
    # Die rohe Form: die Ausnahme schlaegt bis in den Test durch.
    ROH = (
        "src/meteoswiss_mcp/server.py:1315: in _query\n"
        "    resp = await client.get(GEOCODING_BASE, params=params)\n"
        "E   httpx.ConnectTimeout"
    )
    # Und ein echter Befund: Die Quelle HAT geantwortet, nur anders.
    BEFUND = "E       AssertionError: assert '°C' in 'Prognose Zürich: 21 Grad'"

    def test_abgefangener_timeout_ist_unknown(self):
        state, reason = self._state(faelle(("test_live_forecast_zurich", self.ABGEFANGEN)))
        self.assertEqual(state, clr.UNKNOWN)
        self.assertIn("ReadTimeout", reason)
        self.assertIn("ohne Antwort", reason)

    def test_rohe_ausnahme_ist_unknown(self):
        state, reason = self._state(faelle(("test_live_geocode", self.ROH)))
        self.assertEqual(state, clr.UNKNOWN)
        self.assertIn("ConnectTimeout", reason)

    def test_der_rote_lauf_vom_3_9_2026(self):
        """Zweiter Durchgang jenes Laufs, aber ohne den JSONDecodeError."""
        state, reason = self._state(
            faelle(
                ("test_live_geocode_zurich", None),
                ("test_live_geocode_leutschenbach", self.ROH),
                ("test_live_forecast_zurich", self.ABGEFANGEN),
                ("test_live_meteo_current_klo", None),
            )
        )
        self.assertEqual(state, clr.UNKNOWN)
        self.assertIn("ConnectTimeout", reason)
        self.assertIn("ReadTimeout", reason)

    def test_ein_echter_befund_bleibt_ein_finding(self):
        state, _ = self._state(faelle(("test_live_forecast_zurich", self.BEFUND)))
        self.assertEqual(state, clr.FINDING)

    def test_ein_aussetzer_versteckt_keinen_befund(self):
        """Der teuerste Fall: Wuerde hier `unknown` herauskommen, wuerde ein
        echter Formatwechsel als Netzproblem weggebucht."""
        state, reason = self._state(
            faelle(
                ("test_live_forecast_zurich", self.ABGEFANGEN),
                ("test_live_meteo_current_klo", self.BEFUND),
            )
        )
        self.assertEqual(state, clr.FINDING)
        # Der Aussetzer wird trotzdem benannt, sonst sucht jemand zwei Brueche.
        self.assertIn("ReadTimeout", reason)

    def test_ein_4xx_ist_eine_antwort(self):
        """`HTTPStatusError` steht bewusst nicht in der Liste (CLAUDE.md)."""
        state, _ = self._state(
            faelle(("test_live_forecast_zurich", "E   httpx.HTTPStatusError: 400"))
        )
        self.assertEqual(state, clr.FINDING)

    def test_unlesbares_json_ist_eine_antwort(self):
        """Wer unlesbares Zeug schickt, hat geschickt — genau dafuer ist die Suite da."""
        state, _ = self._state(
            faelle(
                (
                    "test_live_school_check",
                    "E   AssertionError: assert '🟢' in '⚠️ Prognosedaten nicht "
                    "abrufbar: JSONDecodeError: Expecting value: line 1 column 1'",
                )
            )
        )
        self.assertEqual(state, clr.FINDING)

    def test_ohne_einzelfaelle_bleibt_es_ein_finding(self):
        """Ein Report mit blossen Summen belegt nicht, dass alle stumm blieben."""
        state, _ = self._state(suite(tests=3, failures=2))
        self.assertEqual(state, clr.FINDING)

    def test_nicht_jeder_gefallene_test_im_report(self):
        """Zaehlt das Attribut mehr Fehlschlaege als Einzelfaelle da sind, wird
        nicht ueber die ungesehenen hinweg `unknown` behauptet."""
        xml = faelle(("test_live_forecast_zurich", self.ABGEFANGEN)).replace(
            'failures="1"', 'failures="2"'
        )
        state, _ = self._state(xml)
        self.assertEqual(state, clr.FINDING)

    def test_kein_treffer_mitten_im_wort(self):
        """`\\b` in der Suche: Ein Bezeichner, der den Namen bloss enthaelt,
        macht aus einem Befund keinen Aussetzer."""
        state, _ = self._state(
            faelle(("test_x", "E   AssertionError: 'MeinConnectTimeoutHandler' fehlt"))
        )
        self.assertEqual(state, clr.FINDING)

    def test_ein_error_zaehlt_wie_ein_failure(self):
        xml = (
            '<testsuite name="pytest" tests="1" failures="0" errors="1" skipped="0">'
            '<testcase name="test_x"><error message="httpx.ConnectTimeout">'
            "E   httpx.ConnectTimeout</error></testcase></testsuite>"
        )
        state, _ = self._state(xml)
        self.assertEqual(state, clr.UNKNOWN)


class HttpxDriftTest(unittest.TestCase):
    """Die Namensliste ist abgeschrieben — hier wird sie an httpx gehalten."""

    def test_transportnamen_decken_httpx_ab(self):
        import inspect

        import httpx

        erwartet = {
            n
            for n, o in vars(httpx).items()
            if inspect.isclass(o) and issubclass(o, httpx.TransportError)
        }
        self.assertEqual(clr.OHNE_ANTWORT, frozenset(erwartet))

    def test_eine_antwort_gehoert_nicht_dazu(self):
        import httpx

        for name in ("HTTPStatusError", "DecodingError", "TooManyRedirects"):
            self.assertTrue(hasattr(httpx, name))
            self.assertNotIn(name, clr.OHNE_ANTWORT)


class MissingReportTest(unittest.TestCase):
    """Kein Report heisst: pytest kam nicht bis zum Schreiben. Nie clear."""

    def test_fehlender_report_ist_unknown(self):
        state, reason = clr.classify(Path("/nonexistent/live-report.xml"), pytest_exit=4)
        self.assertEqual(state, clr.UNKNOWN)
        self.assertIn("Exit 4", reason)

    def test_kaputtes_xml_ist_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(Path(tmp), "<testsuite tests=")
            state, _ = clr.classify(path)
        self.assertEqual(state, clr.UNKNOWN)

    def test_xml_ohne_testsuite_ist_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write(Path(tmp), "<irgendwas/>")
            state, _ = clr.classify(path)
        self.assertEqual(state, clr.UNKNOWN)


class NotStartedTest(unittest.TestCase):
    """pytest nie aufgerufen: Der Grund kommt vom Aufrufer, nicht vom Exit-Code.

    Beobachtet am 24.8.2026 in `swiss-ip-mcp`: Ohne Zugangsdaten meldete der
    Workflow `--pytest-exit 127`, und daraus wurde «pytest ist nicht bis zum
    Schreiben gekommen (Exit 127)». 127 heisst «command not found» — der Satz
    behauptete einen gescheiterten pytest-Aufruf, den es nie gab.
    """

    def test_grund_wird_woertlich_durchgereicht(self):
        state, reason = clr.classify(
            Path("/nonexistent/live-report.xml"),
            not_started="Secret ist nicht gesetzt",
        )
        self.assertEqual(state, clr.UNKNOWN)
        self.assertEqual(reason, "Secret ist nicht gesetzt")

    def test_kein_erfundener_pytest_lauf_in_der_begruendung(self):
        _, reason = clr.classify(
            Path("/nonexistent/live-report.xml"),
            not_started="Secret ist nicht gesetzt",
        )
        self.assertNotIn("pytest ist nicht bis zum Schreiben gekommen", reason)
        self.assertNotIn("Exit", reason)

    def test_ein_liegengebliebener_report_belegt_nichts(self):
        """Gruenes XML aus einem frueheren Schritt macht einen Nicht-Lauf nicht gruen."""
        with tempfile.TemporaryDirectory() as tmp:
            report = write(Path(tmp), suite(tests=3))
            state, reason = clr.classify(report, not_started="gar nicht gestartet")
        self.assertEqual(state, clr.UNKNOWN)
        self.assertEqual(reason, "gar nicht gestartet")

    def test_leerer_grund_ist_kein_grund(self):
        """Der Workflow reicht `--not-started` nur gesetzt durch; leer heisst: pytest lief."""
        with tempfile.TemporaryDirectory() as tmp:
            report = write(Path(tmp), suite(tests=3))
            state, _ = clr.classify(report, not_started="")
        self.assertEqual(state, clr.CLEAR)

    def test_ueber_die_kommandozeile(self):
        state, reason = cli("--not-started", "kein Secret")
        self.assertEqual(state, "unknown")
        self.assertEqual(reason, "kein Secret")


class GithubOutputTest(unittest.TestCase):
    """Der Workflow liest state und reason ueber $GITHUB_OUTPUT."""

    def test_beide_werte_werden_angehaengt(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = write(Path(tmp), suite(tests=2))
            out = Path(tmp) / "gh-output"
            out.write_text("", encoding="utf-8")
            os.environ["GITHUB_OUTPUT"] = str(out)
            try:
                rc = clr.main([str(report)])
            finally:
                del os.environ["GITHUB_OUTPUT"]
            written = out.read_text(encoding="utf-8")
        self.assertEqual(rc, 0)
        self.assertIn("state=clear", written)
        self.assertIn("reason=", written)

    def test_ein_mehrzeiliger_grund_schiebt_kein_zweites_output_nach(self):
        """`key=value` endet an der ersten neuen Zeile — was danach steht, ist Output."""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "gh-output"
            out.write_text("", encoding="utf-8")
            os.environ["GITHUB_OUTPUT"] = str(out)
            try:
                clr.main(
                    [
                        str(Path(tmp) / "live-report.xml"),
                        "--not-started",
                        "kein Secret\nstate=clear",
                    ]
                )
            finally:
                del os.environ["GITHUB_OUTPUT"]
            zeilen = [z for z in out.read_text(encoding="utf-8").splitlines() if z]
        self.assertEqual([z for z in zeilen if z.startswith("state=")], ["state=unknown"])
        self.assertEqual(len(zeilen), 2)


if __name__ == "__main__":
    unittest.main()
