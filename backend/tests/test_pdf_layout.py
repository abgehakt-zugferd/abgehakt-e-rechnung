"""Layout des Rechnungs-PDFs nach dem Vorbild einer DATEV-Rechnung (2026-10-02).

Geprüft wird, was sich messen lässt: Text wörtlich vorhanden, Lage auf der Seite,
Zusammenhalt über Seitenumbrüche. Ob es gefällt, ist eine Frage für die Augen.
"""
import pytest
from pypdf import PdfReader

from app.services import pdf_generator
from tests.factories import orm_company, orm_invoice, orm_item


def _text(pfad) -> str:
    return " ".join("".join(s.extract_text() or "" for s in PdfReader(str(pfad)).pages).split())


@pytest.mark.parametrize("feld", ["notes", "payment_terms"])
def test_notizen_und_zahlungsbedingungen_erscheinen_woertlich(tmp_path, feld):
    """Beide gingen roh ins ReportLab-Markup: `5<x` brach die Erzeugung mit
    „unclosed tags“ ab, `&` und `<b>` wurden verschluckt bzw. als Markup gelesen."""
    inv = orm_invoice([orm_item(1, "1", "100.00", "19")], delivery_date=None,
                      **{feld: "Rabatt bei Menge 5<x & <b>Skonto</b>"})
    pfad = tmp_path / "beleg.pdf"

    pdf_generator.generate_pdf(inv, orm_company(), pfad)

    assert "Rabatt bei Menge 5<x & <b>Skonto</b>" in _text(pfad)


def test_firmen_und_bankangaben_mit_markup_zeichen_erscheinen_woertlich(tmp_path):
    company = orm_company(name="Probe <Werk> & Söhne GmbH", address_line1="Weg <1> & 2",
                          bank_name="Probe <Bank> & Co")
    inv = orm_invoice([orm_item(1, "1", "100.00", "19")], delivery_date=None)
    pfad = tmp_path / "beleg.pdf"

    pdf_generator.generate_pdf(inv, company, pfad)

    text = _text(pfad)
    # Kontaktblock im Kopf, Absenderzeile und Fuß, dazu der Stempel in Großbuchstaben.
    assert text.count("Probe <Werk> & Söhne GmbH") == 3
    assert "PROBE <WERK> & SÖHNE GMBH" in text
    assert text.count("Weg <1> & 2") == 3
    # Zahlungsblock und Fuß: zweimal. Einmal hieße, einer von beiden verschluckt ihn.
    assert text.count("Probe <Bank> & Co") == 2


def test_kundenanschrift_und_kopfangaben_mit_markup_zeichen_erscheinen_woertlich(tmp_path):
    from tests.factories import orm_customer

    kunde = orm_customer(name="Probe <Kunde> & Co", customer_number="K-<7>&1")
    inv = orm_invoice([orm_item(1, "1", "100.00", "19")], delivery_date=None, customer=kunde,
                      buyer_reference="Ref <A> & B", buyer_order_reference="PO <9> & 8")
    pfad = tmp_path / "beleg.pdf"

    pdf_generator.generate_pdf(inv, orm_company(), pfad)

    text = _text(pfad)
    for erwartet in ("Probe <Kunde> & Co", "K-<7>&1", "Ref <A> & B", "PO <9> & 8"):
        assert erwartet in text, erwartet


def _positionen(pfad):
    """{Text: (Seite, x)} des ersten Vorkommens, aus dem echten PDF."""
    lage = {}
    for nr, seite in enumerate(PdfReader(str(pfad)).pages):
        def besuch(text, cm_, tm, _f, _g, nr=nr):
            t = " ".join(text.split())
            if t and t not in lage:
                lage[t] = (nr, cm_[0] * tm[4] + cm_[2] * tm[5] + cm_[4])
        seite.extract_text(visitor_text=besuch)
    return lage


def test_summenblock_steht_rechts(tmp_path):
    from reportlab.lib.pagesizes import A4

    inv = orm_invoice([orm_item(1, "1", "100.00", "19")], delivery_date=None)
    pfad = tmp_path / "beleg.pdf"
    pdf_generator.generate_pdf(inv, orm_company(), pfad)

    lage = _positionen(pfad)
    assert lage["Nettobetrag"][1] > A4[0] / 2
    assert lage["Rechnungsbetrag"][1] > A4[0] / 2


@pytest.mark.parametrize("positionen", [1, 36])
def test_zahlungsblock_haelt_zusammen_qr_links_text_rechts(tmp_path, positionen):
    """36 Positionen schoben die Bildunterschrift bisher allein auf eine neue Seite."""
    items = [orm_item(n, "1", "11.56", "19") for n in range(1, positionen + 1)]
    inv = orm_invoice(items, delivery_date=None, payment_terms="Zahlbar binnen 14 Tagen.")
    pfad = tmp_path / "beleg.pdf"
    pdf_generator.generate_pdf(inv, orm_company(), pfad)

    lage = _positionen(pfad)
    qr = next(v for k, v in lage.items() if k.startswith("Zum Überweisen"))
    zweck = next(v for k, v in lage.items() if k.startswith("Verwendungszweck:"))
    bedingung = lage["Zahlbar binnen 14 Tagen."]
    assert qr[0] == zweck[0] == bedingung[0], "Zahlungsblock über eine Seitengrenze gerissen"
    assert zweck[1] > qr[1] + 2.5 * 28.35, "Zahlungstext steht nicht rechts neben dem QR-Code"


def test_absenderzeile_steht_klein_direkt_ueber_der_empfaengeranschrift(tmp_path):
    """Wie auf der DATEV-Rechnung. Eine Fensterposition nach DIN 5008 wird damit nicht
    zugesagt; dafür stünde die Anschrift an festen Koordinaten."""
    inv = orm_invoice([orm_item(1, "1", "100.00", "19")], delivery_date=None)
    pfad = tmp_path / "beleg.pdf"
    pdf_generator.generate_pdf(inv, orm_company(name="Probe & Söhne GmbH"), pfad)

    funde = {}
    def besuch(text, cm_, tm, _f, groesse):
        t = " ".join(text.split())
        if t:
            funde.setdefault(t, (cm_[3] * tm[5] + cm_[5], groesse))
    PdfReader(str(pfad)).pages[0].extract_text(visitor_text=besuch)

    absender = funde["Probe & Söhne GmbH · Musterstraße 1 · 12345 Musterstadt"]
    empfaenger = funde["Kunde GmbH"]
    assert absender[1] < 8, "Absenderzeile soll klein sein"
    assert 0 < absender[0] - empfaenger[0] < 25, "Absenderzeile gehört direkt über die Anschrift"


@pytest.mark.parametrize("sprache, preis, endbetrag", [
    ("en", "12345.67", "EUR 14,691.35"),
    ("de", "1234567.89", "1.469.135,79 €"),
])
def test_endbetrag_steht_in_einem_stueck_auf_einer_zeile(tmp_path, sprache, preis, endbetrag):
    """Code-Review 2026-10-02: in 3,2 cm brach „EUR 12,345.67“ im getönten Endbetrag
    auf zwei Zeilen um, deutsch ab einer Million."""
    inv = orm_invoice([orm_item(1, "1", preis, "19")], delivery_date=None, document_language=sprache)
    pfad = tmp_path / "beleg.pdf"
    pdf_generator.generate_pdf(inv, orm_company(), pfad)

    assert endbetrag in _positionen(pfad)
