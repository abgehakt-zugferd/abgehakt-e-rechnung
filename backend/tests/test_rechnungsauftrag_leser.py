"""Der Leser fuer rechnungsauftrag (§ 8a, Fassung 1.7) - Teil 1a: Grundregeln.

Nur die Grundregeln: die Art ist lesbar, der Feldbestand, typcode, waehrung,
der Kalendermonat, die Geldform und die Summen. Gruppen, Bezeichnungen,
Grundlagen und der Auftragsschluessel folgen in eigenen Teilen; jeder Fall
hier ist erfunden (helpers/uebergabe.rechnungsauftrag).
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
    """Regel 6: exakt, ohne Toleranz - ein Cent daneben ist keiner."""
    urteil = _urteil(schluessel, rechnungsauftrag(summe={"netto": "171.35"}))

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
    )

    urteil = _urteil(schluessel, nutzlast)

    assert _befunde(urteil) == [("SUMME_STIMMT_NICHT", "$.nutzlast.summe.netto")]
