"""Der Leser fuer rechnungsauftrag (§ 8a, Fassung 1.7) - Teil 1a und 1b.

Teil 1a, die Grundregeln: die Art ist lesbar, der Feldbestand, typcode,
waehrung, der Kalendermonat, die Geldform und die Summen. Teil 1b: gruppe
(an allen Positionen oder keiner, zusammenhaengend, nr lueckenlos), bezeichnung
(nur einmal je Beleg, Gleichheit nach Unicode-NFC) und grundlagen (quelle,
beleg_sha256, leistungsperiode, Σ netto == summe). Der Auftragsschluessel
folgt in einem eigenen Teil; jeder Fall hier ist erfunden
(helpers/uebergabe.rechnungsauftrag).
"""

import pytest

from app.services.uebergabe_befund import Empfangslage, beleg_beurteilen
from tests.helpers.uebergabe import beleg, rechnungsauftrag, schluesselpaar


@pytest.fixture
def schluessel(tmp_path):
    return schluesselpaar(tmp_path)


def _urteil(schluessel, nutzlast, **umschlag_aenderungen):
    roh = beleg(
        schluessel[0], nutzlast,
        nutzlast_art="rechnungsauftrag", **umschlag_aenderungen,
    )
    return beleg_beurteilen(roh, Empfangslage(), schluessel_wurzel=schluessel[1])


def _befunde(urteil) -> list:
    return [(f.code, f.pfad) for f in urteil.feststellungen]


def test_ein_gueltiger_rechnungsauftrag_wird_angenommen(schluessel):
    """Regel 1: Die Art steht in LESBARE_ARTEN - vorher fiel jeder gueltig
    signierte rechnungsauftrag an der Artprobe. Die negative Position im
    Beispiel ist erlaubt und muss angenommen werden."""
    urteil = _urteil(schluessel, rechnungsauftrag())

    assert urteil.angenommen, _befunde(urteil)
    assert urteil.feststellungen == ()
    assert urteil.nutzlast_art == "rechnungsauftrag"


def test_steuer_an_der_position_ist_ein_unbekanntes_feld(schluessel):
    """Regel 2: Der Auftrag traegt nur netto. Auch eine Steuer von 0.00
    liess zwei Stellen dieselbe Zahl behaupten."""
    nutzlast = rechnungsauftrag()
    nutzlast["positionen"][0]["steuer"] = "0.00"

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [("UNBEKANNTES_FELD", "$.nutzlast.positionen[0].steuer")]


def test_anlagen_gehoeren_nur_zum_aufstellungsauftrag(schluessel):
    """Regel 2: anlagen kennt in 1.7 nur der aufstellungsauftrag (§ 8b) -
    auch leer ist der rechnungsauftrag ein Feld zu viel."""
    urteil = _urteil(schluessel, rechnungsauftrag(anlagen=[]))

    assert _befunde(urteil) == [("UNBEKANNTES_FELD", "$.nutzlast.anlagen")]


def test_ein_fehlendes_pflichtfeld_ist_kein_unbekanntes_feld(schluessel):
    """Regel 2: grundlagen ist bekannt und nicht da - PFLICHTFELD_FEHLT."""
    nutzlast = rechnungsauftrag()
    del nutzlast["grundlagen"]

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [("PFLICHTFELD_FEHLT", "$.nutzlast.grundlagen")]


def test_ein_typcode_ausserhalb_des_wertevorrats(schluessel):
    """Regel 3: 380 ist der einzige Wert. 389 ist die Gutschrift aus § 8 -
    ein anderer Beleg, kein Typcode mehr."""
    urteil = _urteil(schluessel, rechnungsauftrag(typcode="389"))

    assert _befunde(urteil) == [("WERT_UNBRAUCHBAR", "$.nutzlast.typcode")]


def test_nur_euro(schluessel):
    """Regel 3: GBP als Euro zu lesen waere schlimmer als abzulehnen."""
    urteil = _urteil(schluessel, rechnungsauftrag(waehrung="GBP"))

    assert _befunde(urteil) == [("WERT_UNBRAUCHBAR", "$.nutzlast.waehrung")]


@pytest.mark.parametrize("zeitraum", [
    {"von": "2026-01-01", "bis": "2026-02-28"},  # zwei Monate
    {"von": "2026-02-02", "bis": "2026-02-28"},  # von ist nicht der Erste
    {"von": "2026-02-01", "bis": "2026-02-27"},  # bis ist nicht der Letzte
])
def test_der_leistungszeitraum_ist_genau_ein_kalendermonat(schluessel, zeitraum):
    """Regel 4: von der Erste, bis der Letzte desselben Monats - wer sammelt,
    verliert die Zuordnung zur Zahlung."""
    urteil = _urteil(schluessel, rechnungsauftrag(leistungszeitraum=zeitraum))

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.leistungszeitraum"),
    ]


def test_eine_position_ueber_nichts_ist_keine(schluessel):
    """Regel 5: 0.00 nie - der Sender laesst die Position weg. Die Summe
    bleibt richtig, damit nur die Null den Befund gibt."""
    nutzlast = rechnungsauftrag()
    nutzlast["positionen"][1]["netto"] = "0.00"
    nutzlast["summe"]["netto"] = "174.44"
    nutzlast["grundlagen"][0]["netto"] = "174.44"

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.positionen[1].netto"),
    ]


@pytest.mark.parametrize("pfad, aenderung", [
    ("$.nutzlast.positionen[0].netto", {"positionen": [
        {"nr": 1, "gruppe": "Digital", "bezeichnung": "Nutzungsrechte A",
         "netto": "174.4"},
        {"nr": 2, "gruppe": "Druck", "bezeichnung": "Nutzungsrechte B",
         "netto": "-3.10"},
    ]}),
    ("$.nutzlast.summe.netto", {"summe": {"netto": "171.3"}}),
    ("$.nutzlast.grundlagen[0].netto", {"grundlagen": [{
        "quelle": "abrechnungsbericht", "beleg_sha256": "1a" * 32,
        "leistungsperiode": "2026-02", "netto": "171.340",
    }]}),
])
def test_die_geldform_gilt_zentral_weiter(schluessel, pfad, aenderung):
    """Regel 5: dieselbe Formprobe des § 4 (protokoll.FELDFORMEN), keine
    zweite - auch keine Kopie an dieser Art."""
    urteil = _urteil(schluessel, rechnungsauftrag(**aenderung))

    assert _befunde(urteil) == [("WERT_UNBRAUCHBAR", pfad)]


def test_die_summe_muss_den_positionen_entsprechen(schluessel):
    """Regel 6: exakt, ohne Toleranz - ein Cent daneben ist keiner. Die
    Grundlagen ziehen mit (171.35), damit nur die Positionsprobe den Befund
    gibt."""
    nutzlast = rechnungsauftrag(summe={"netto": "171.35"})
    nutzlast["grundlagen"][0]["netto"] = "171.35"

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [("SUMME_STIMMT_NICHT", "$.nutzlast.summe.netto")]


def test_eine_rechnung_ueber_null_ist_keine(schluessel):
    """Regel 6: Die Summen gehen auf (4.00 - 4.00 = 0.00), aber ueber null
    stellt niemand eine 380 aus."""
    nutzlast = rechnungsauftrag(
        positionen=[
            {"nr": 1, "gruppe": "Digital", "bezeichnung": "Nutzungsrechte A",
             "netto": "4.00"},
            {"nr": 2, "gruppe": "Druck", "bezeichnung": "Nutzungsrechte B",
             "netto": "-4.00"},
        ],
        summe={"netto": "0.00"},
        grundlagen=[{
            "quelle": "abrechnungsbericht", "beleg_sha256": "1a" * 32,
            "leistungsperiode": "2026-02", "netto": "0.00",
        }],
    )

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [("SUMME_STIMMT_NICHT", "$.nutzlast.summe.netto")]


# ---- Teil 1b: gruppe, bezeichnung, grundlagen ----


def test_gruppe_an_allen_oder_keiner_position(schluessel):
    """Teil 1b: Eine gruppe an EINER Position gliedert die ganze Rechnung -
    jede Position ohne gruppe ist unbedeutend fuer die Gliederung und
    verdoppelt die Lesart."""
    nutzlast = rechnungsauftrag()
    del nutzlast["positionen"][1]["gruppe"]

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.positionen[1].gruppe"),
    ]


def test_ohne_jede_gruppe_ist_die_rechnung_ungegliedert(schluessel):
    """Teil 1b: Alle oder keine - ohne jede gruppe ist die Rechnung
    ungegliedert und gueltig, kein Zwang zur Gliederung."""
    nutzlast = rechnungsauftrag()
    for position in nutzlast["positionen"]:
        del position["gruppe"]

    urteil = _urteil(schluessel, nutzlast)

    assert urteil.angenommen, _befunde(urteil)


def test_eine_gruppe_kehrt_nach_einer_anderen_zurueck(schluessel):
    """Teil 1b: Die Positionen derselben Gruppe folgen aufeinander - kehrt
    eine Gruppe nach einer anderen zurueck, bricht genau diese Position den
    Zusammenhang. Die Summen bleiben richtig (174.44 - 1.00 - 2.10)."""
    nutzlast = rechnungsauftrag(
        positionen=[
            {"nr": 1, "gruppe": "Digital", "bezeichnung": "Nutzungsrechte A",
             "netto": "174.44"},
            {"nr": 2, "gruppe": "Druck", "bezeichnung": "Nutzungsrechte B",
             "netto": "-1.00"},
            {"nr": 3, "gruppe": "Digital", "bezeichnung": "Nutzungsrechte C",
             "netto": "-2.10"},
        ],
    )

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.positionen[2].gruppe"),
    ]


def test_die_nr_einer_gruppe_ist_lueckenlos(schluessel):
    """Teil 1b: Innerhalb einer Gruppe zaehlt nr ohne Luecke weiter - der
    Befund trifft die Position, die nicht folgt."""
    nutzlast = rechnungsauftrag(
        positionen=[
            {"nr": 1, "gruppe": "Digital", "bezeichnung": "Nutzungsrechte A",
             "netto": "174.44"},
            {"nr": 3, "gruppe": "Digital", "bezeichnung": "Nutzungsrechte B",
             "netto": "-3.10"},
        ],
    )

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.positionen[1].nr"),
    ]


def test_zerlegtes_und_zusammengesetztes_ue_ist_dieselbe_gruppe(schluessel):
    """Teil 1b (NFC): "Gr\\u00fcn" zusammengesetzt und "Gru\\u0308n" zerlegt
    sind dieselbe Gruppe - erst deshalb kehrt die Gruppe an Position 3
    zurueck und bricht den Zusammenhang. Ohne NFC waere Position 3 eine neue
    Gruppe und der Beleg angenommen."""
    nutzlast = rechnungsauftrag(
        positionen=[
            {"nr": 1, "gruppe": "Gr\u00fcn", "bezeichnung": "Nutzungsrechte A",
             "netto": "174.44"},
            {"nr": 2, "gruppe": "Druck", "bezeichnung": "Nutzungsrechte B",
             "netto": "-1.00"},
            {"nr": 3, "gruppe": "Gru\u0308n", "bezeichnung": "Nutzungsrechte C",
             "netto": "-2.10"},
        ],
    )

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.positionen[2].gruppe"),
    ]


def test_benachbarte_gruppenformen_stiften_keine_neue_gruppe(schluessel):
    """Teil 1b (NFC): Zwei Schreibweisen desselben Textes an Nachbarpositionen
    sind EINE Gruppe und werden angenommen - der Wortlaut selbst wird nie
    geprueft, gruppe ist freier Anzeigetext."""
    nutzlast = rechnungsauftrag(
        positionen=[
            {"nr": 1, "gruppe": "Gr\u00fcn", "bezeichnung": "Nutzungsrechte A",
             "netto": "174.44"},
            {"nr": 2, "gruppe": "Gru\u0308n", "bezeichnung": "Nutzungsrechte B",
             "netto": "-3.10"},
        ],
    )

    urteil = _urteil(schluessel, nutzlast)

    assert urteil.angenommen, _befunde(urteil)


def test_keine_zwei_positionen_derselben_bezeichnung(schluessel):
    """Teil 1b: Eine Bezeichnung nennt die Position, zwei nennen keine - der
    Befund trifft die zweite Stelle, die erste blieb unbeanstandet."""
    nutzlast = rechnungsauftrag(
        positionen=[
            {"nr": 1, "gruppe": "Digital", "bezeichnung": "Nutzungsrechte A",
             "netto": "174.44"},
            {"nr": 2, "gruppe": "Druck", "bezeichnung": "Nutzungsrechte A",
             "netto": "-3.10"},
        ],
    )

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.positionen[1].bezeichnung"),
    ]


def test_bezeichnungen_gleich_nach_nfc(schluessel):
    """Teil 1b (NFC): "B\\u00fccher A" zusammengesetzt und "Bu\\u0308cher A"
    zerlegt sind dieselbe Bezeichnung - ohne NFC waere die zweite eine neue."""
    nutzlast = rechnungsauftrag(
        positionen=[
            {"nr": 1, "gruppe": "Digital", "bezeichnung": "B\u00fccher A",
             "netto": "174.44"},
            {"nr": 2, "gruppe": "Druck", "bezeichnung": "Bu\u0308cher A",
             "netto": "-3.10"},
        ],
    )

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.positionen[1].bezeichnung"),
    ]


@pytest.mark.parametrize("quelle", ["abrechnung", "Abrechnungsbericht"])
def test_grundlagen_quelle_ist_nur_der_abrechnungsbericht(schluessel, quelle):
    """Teil 1b: Andere Quellen und andere Schreibweisen sind unbrauchbar -
    hinter jedem anderen Namen steht ein anderer Bericht."""
    nutzlast = rechnungsauftrag(grundlagen=[{
        "quelle": quelle, "beleg_sha256": "1a" * 32,
        "leistungsperiode": "2026-02", "netto": "171.34",
    }])

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.grundlagen[0].quelle"),
    ]


@pytest.mark.parametrize("sha", [
    "1A" * 32,             # Grossbuchstaben sind eine andere Form
    "1a" * 31 + "g",       # 63 Zeichen
    "1a" * 32 + "a",       # 65 Zeichen
])
def test_beleg_sha256_ist_kleinbuchstaben_hex(schluessel, sha):
    """Teil 1b: 64 Kleinbuchstaben-Hex, wie hashlib.hexdigest() ihn bildet."""
    nutzlast = rechnungsauftrag(grundlagen=[{
        "quelle": "abrechnungsbericht", "beleg_sha256": sha,
        "leistungsperiode": "2026-02", "netto": "171.34",
    }])

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.grundlagen[0].beleg_sha256"),
    ]


@pytest.mark.parametrize("periode", ["2026-2", "2026-13", "2026_02"])
def test_leistungsperiode_ist_ein_monat(schluessel, periode):
    """Teil 1b: JJJJ-MM - ein Monat, kein Quartal, keine Schraegstellung."""
    nutzlast = rechnungsauftrag(grundlagen=[{
        "quelle": "abrechnungsbericht", "beleg_sha256": "1a" * 32,
        "leistungsperiode": periode, "netto": "171.34",
    }])

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("WERT_UNBRAUCHBAR", "$.nutzlast.grundlagen[0].leistungsperiode"),
    ]


def test_grundlagen_summieren_sich_zur_summe(schluessel):
    """Teil 1b: Σ grundlagen[].netto - zwei Grundlagen summieren sich; die
    Probe gilt der Summe ueber alle, nicht der einzelnen."""
    nutzlast = rechnungsauftrag(grundlagen=[
        {"quelle": "abrechnungsbericht", "beleg_sha256": "1a" * 32,
         "leistungsperiode": "2026-02", "netto": "100.00"},
        {"quelle": "abrechnungsbericht", "beleg_sha256": "2b" * 32,
         "leistungsperiode": "2026-02", "netto": "71.34"},
    ])

    urteil = _urteil(schluessel, nutzlast)

    assert urteil.angenommen, _befunde(urteil)


def test_die_grundlagen_muessen_der_summe_entsprechen(schluessel):
    """Teil 1b: Exakt, ohne Toleranz - anders als § 8 (dort hoechstens) ist
    die Herleitung hier kein Auszug; ein Cent daneben ist keiner."""
    nutzlast = rechnungsauftrag(grundlagen=[{
        "quelle": "abrechnungsbericht", "beleg_sha256": "1a" * 32,
        "leistungsperiode": "2026-02", "netto": "100.00",
    }])

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [
        ("SUMME_STIMMT_NICHT", "$.nutzlast.grundlagen"),
    ]
