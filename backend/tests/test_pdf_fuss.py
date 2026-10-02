"""Fester Fuß auf jeder Seite und „Seite x von y“.

Bisher stand der Fuß (Steuernummern, Pflichtangaben) am Ende des Textflusses und
damit nur auf der letzten Seite. Pflichtangaben gehören auf den Geschäftsbrief, und
eine mehrseitige Rechnung ohne Seitenzählung lässt nicht erkennen, ob ein Blatt fehlt.
"""
import pytest
from pypdf import PdfReader

from app.services import pdf_generator
from tests.factories import orm_company, orm_invoice, orm_item
from tests.probe_daten import HRB_PROBE, IBAN_FIRMA_PROBE, UST_DE_PROBE

FUSS_GROESSE = 7


def _lang(n=60, **over):
    items = [orm_item(nr, "1", "10.00", "19", description=f"Leistung {nr}") for nr in range(1, n + 1)]
    return orm_invoice(items, delivery_date=None, **over)


def _seiten(inv, tmp_path, company=None, **kw):
    pfad = tmp_path / "beleg.pdf"
    pdf_generator.generate_pdf(inv, company or orm_company(), pfad, **kw)
    return [" ".join((s.extract_text() or "").split()) for s in PdfReader(str(pfad)).pages]


@pytest.mark.parametrize("sprache, muster", [("de", "Seite {i} von {n}"), ("en", "Page {i} of {n}")])
def test_jede_seite_traegt_seitenzahl_und_den_vollstaendigen_fuss(tmp_path, sprache, muster):
    seiten = _seiten(_lang(document_language=sprache), tmp_path)

    n = len(seiten)
    assert n >= 2, "Testrechnung muss mehrseitig sein"
    for i, text in enumerate(seiten, 1):
        assert muster.format(i=i, n=n) in text, f"Seite {i}"
        assert text.count("123/456/78901") == 1, f"Seite {i}: Steuernummer auch im Fluss?"
        assert text.count(HRB_PROBE) == 1, f"Seite {i}: Registerangabe auch im Fluss?"


def test_fuss_enthaelt_jede_angabe_genau_einmal_je_seite(tmp_path):
    pfad = tmp_path / "beleg.pdf"
    pdf_generator.generate_pdf(_lang(), orm_company(), pfad)

    erwartet = [
        "Muster Handwerk GmbH", "Musterstraße 1", "12345 Musterstadt", "info@example.de",
        "Steuernummer: 123/456/78901", f"USt-IdNr.: {UST_DE_PROBE}",
        "Sitz: Musterstadt · Registergericht:", f"Amtsgericht Musterstadt, {HRB_PROBE}",
        "Geschäftsführung: Probe Geschäftsführerin",
        "Testbank", f"IBAN: {IBAN_FIRMA_PROBE}", "BIC: ABCDDEFF",
    ]
    texte = _texte(pfad)
    seiten = {t[0] for t in texte}
    assert len(seiten) >= 2
    for seite in seiten:
        fuss = [" ".join(t.split()) for s, _, g, t in texte if s == seite and g == FUSS_GROESSE]
        for angabe in erwartet:
            assert fuss.count(angabe) == 1, f"Seite {seite + 1}: {angabe!r} im Fuß {fuss.count(angabe)}x"


def _texte(pfad):
    """(Seite, y, Größe, Text) aus dem echten PDF."""
    funde = []
    for nr, seite in enumerate(PdfReader(str(pfad)).pages):
        def besuch(text, cm_, tm, _schrift, groesse, nr=nr):
            if text.strip():
                y = cm_[1] * tm[4] + cm_[3] * tm[5] + cm_[5]
                funde.append((nr, y, round(groesse, 1), text.strip()))
        seite.extract_text(visitor_text=besuch)
    return funde


def test_textfluss_endet_ueber_dem_fuss_auch_wenn_der_fuss_hoch_wird(tmp_path):
    """Der Fuß misst seine Höhe; ein geschätzter Rand ließe Positionen in ihn laufen."""
    viele = ", ".join(f"Probe Geschäftsführerin {i}" for i in range(1, 16))
    company = orm_company(vertretung=viele, name="Probe Handwerk und Gestaltung mit sehr langem Firmennamen GmbH")
    pfad = tmp_path / "beleg.pdf"
    pdf_generator.generate_pdf(_lang(), company, pfad)

    texte = _texte(pfad)
    for seite in {t[0] for t in texte}:
        fuss = [y for s, y, g, _ in texte if s == seite and g == FUSS_GROESSE]
        fluss = [y for s, y, g, _ in texte if s == seite and g > FUSS_GROESSE]
        assert fuss and fluss
        assert min(fluss) > max(fuss) + FUSS_GROESSE, f"Seite {seite + 1}: Text läuft in den Fuß"


def test_rechnung_nennt_die_eigene_bank_auf_jeder_seite_gutschrift_nicht(tmp_path):
    """Bei Gutschriften fließt das Geld zum Kunden; die eigene IBAN wäre eine
    falsche Zahlungsaufforderung (#18)."""
    from tests.probe_daten import IBAN_FIRMA_PROBE

    rechnung = _seiten(_lang(), tmp_path)
    assert all(IBAN_FIRMA_PROBE in s for s in rechnung)

    gutschrift = _seiten(_lang(invoice_type="credit_note", original_invoice_id=1), tmp_path)
    for angabe in ("IBAN", IBAN_FIRMA_PROBE, "ABCDDEFF", "Testbank"):
        assert not any(angabe in s for s in gutschrift), angabe


def test_entwurf_traegt_wasserzeichen_und_fuss_auf_jeder_seite(tmp_path):
    seiten = _seiten(_lang(), tmp_path, draft=True)

    assert len(seiten) >= 2
    for i, text in enumerate(seiten, 1):
        assert "ENTWURF" in text, f"Seite {i}"
        assert f"Seite {i} von {len(seiten)}" in text
        assert HRB_PROBE in text
