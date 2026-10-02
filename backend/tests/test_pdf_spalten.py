"""Spaltenbreiten der Positionstabelle aus dem Inhalt statt aus festen Zentimetern.

Auf einer echten Rechnung stand „Stunden“ abgeschnitten in der Spalte „Einheit“.
Gemessen am 2026-10-02 mit den eingebetteten Schriften: bei fest 1,3 cm passten neun
von sechzehn Einheiten nicht, dazu die Köpfe „Pos.“, „Menge“, „Einheit“,
„Quantity“, vierstellige Mengen und englische Beträge ab fünf Stellen.
"""
from decimal import Decimal

import pytest
from reportlab.lib.units import cm
from reportlab.pdfbase.pdfmetrics import stringWidth

from app.services.belegsprache import darstellung
from app.services.einheiten import formular_bezeichnungen
from app.services.pdf_fonts import register_fonts
from app.services.pdf_spalten import spaltenbreiten

GROESSE = 8.5
POLSTER = 8
BREITE = 17 * cm


@pytest.fixture(scope="module")
def schriften():
    f = register_fonts()
    return f["body"], f["body_bold"]


def _passt(text, schrift, breite):
    return stringWidth(text, schrift, GROESSE) + POLSTER <= breite + 0.01


@pytest.mark.parametrize("sprache", ["de", "en"])
@pytest.mark.parametrize("mit_steuer", [True, False])
def test_jede_einheit_und_jeder_kopf_passt_in_seine_spalte(schriften, sprache, mit_steuer):
    body, bold = schriften
    d = darstellung(sprache)
    kopf = [d.label_pos, d.label_beschreibung, d.label_menge, d.label_einheit, d.label_einzelpreis]
    if mit_steuer:
        kopf.append(d.label_mwst)
    kopf.append(d.label_betrag)
    zeilen = []
    for nr, einheit in enumerate(formular_bezeichnungen(), 1):
        zeile = [str(nr), None, d.format_menge(Decimal("1234.5678")), einheit,
                 d.format_betrag(Decimal("12345.6789"), "EUR")]
        if mit_steuer:
            zeile.append("19 %")
        zeile.append(d.format_betrag(Decimal("123456.78"), "EUR"))
        zeilen.append(zeile)

    breiten = spaltenbreiten(kopf, zeilen, BREITE, schrift=body, fett=bold,
                             groesse=GROESSE, polster=POLSTER)

    assert sum(breiten) == pytest.approx(BREITE)
    assert breiten[1] >= 5 * cm, "Die Beschreibung braucht Platz"
    for spalte, breite in enumerate(breiten):
        if spalte == 1:
            continue
        assert _passt(kopf[spalte], bold, breite), (kopf[spalte], breite)
        for zeile in zeilen:
            assert _passt(zeile[spalte], body, breite), (zeile[spalte], breite)


def _tabellentexte(pfad, body, bold):
    """(x, y, Breite, Text) aller Texte in Tabellengröße 8,5 pt, aus dem echten PDF."""
    from pypdf import PdfReader

    funde = []

    def besuch(text, cm_, tm, schrift, groesse):
        text = text.strip()
        if not text or abs(groesse - GROESSE) > 0.01:
            return
        name = str((schrift or {}).get("/BaseFont", ""))
        font = bold if "Bold" in name else body
        x = cm_[0] * tm[4] + cm_[2] * tm[5] + cm_[4]
        y = cm_[1] * tm[4] + cm_[3] * tm[5] + cm_[5]
        funde.append((x, round(y, 1), stringWidth(text, font, GROESSE), text))

    for seite in PdfReader(str(pfad)).pages:
        seite.extract_text(visitor_text=besuch)
    return funde


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_im_gestellten_pdf_ragt_kein_tabellentext_in_die_naechste_spalte(tmp_path, schriften, sprache):
    from app.services import pdf_generator
    from tests.factories import orm_company, orm_invoice, orm_item

    body, bold = schriften
    items = [orm_item(nr, "1234.5678", "12345.6789", "19", unit=einheit, description="Abo")
             for nr, einheit in enumerate(["Pauschale", "Kilometer", "Personen", "Stunden"], 1)]
    inv = orm_invoice(items, delivery_date=None, document_language=sprache)
    pfad = tmp_path / "beleg.pdf"

    pdf_generator.generate_pdf(inv, orm_company(), pfad)

    zeilen: dict[float, list] = {}
    for fund in _tabellentexte(pfad, body, bold):
        zeilen.setdefault(fund[1], []).append(fund)
    assert len(zeilen) >= 5, "Kopf und vier Positionen erwartet"
    for y, funde in zeilen.items():
        funde.sort()
        for (x1, _, b1, t1), (x2, _, _, t2) in zip(funde, funde[1:]):
            assert x1 + b1 + 2 <= x2, f"{t1!r} ragt in {t2!r} (y={y})"
