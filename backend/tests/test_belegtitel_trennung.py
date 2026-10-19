"""#156: Namen am erzeugten Beleg prüfen, einschließlich automatischer Texte."""
import pytest

from tests.test_pdf_besetzung_389 import _beleg, _firma, _kunde, _pdf_text


@pytest.mark.parametrize('sprache,titel', [('de', 'STORNORECHNUNG'), ('en', 'CANCELLATION INVOICE')])
@pytest.mark.parametrize('art', ['credit_note', 'credit', 'storno'])
def test_381_pdf_ohne_gutschrift(tmp_path, sprache, titel, art):
    inv = _beleg(art, _kunde())
    inv.document_language = sprache
    inv.payment_terms = None
    text = _pdf_text(inv, _firma(), tmp_path).upper()
    assert titel in text
    assert 'GUTSCHRIFT' not in text
    assert 'CREDIT NOTE' not in text


@pytest.mark.parametrize('sprache,titel', [('de', 'GUTSCHRIFT'), ('en', 'SELF-BILLED INVOICE')])
def test_389_pdf_pflichtangabe_in_beiden_sprachen(tmp_path, sprache, titel):
    inv = _beleg('self_billing', _kunde())
    inv.document_language = sprache
    text = _pdf_text(inv, _firma(), tmp_path).upper()
    assert titel in text
    assert 'GUTSCHRIFT' in text


def test_namen_in_liste_detail_und_formular(client, pg_session):
    import re
    from tests.test_belegart import _kunde as kunde_anlegen, _entwurf, _optionen

    kunde = kunde_anlegen(pg_session)
    storno = _entwurf(pg_session, kunde, invoice_type='credit_note')
    honorar = _entwurf(pg_session, kunde, invoice_type='self_billing')
    def sichtbar(html):
        return re.sub(r'<[^>]+>', '', re.sub(r'<!--.*?-->', '', html, flags=re.S))
    detail = client.get(f'/invoices/{storno.id}')
    assert detail.status_code == 200
    assert 'Stornorechnung' in sichtbar(detail.text)
    assert 'gutschrift' not in sichtbar(detail.text).lower()
    assert 'Honorargutschrift' in client.get(f'/invoices/{honorar.id}').text
    liste = client.get('/invoices/')
    assert 'Stornorechnung' in sichtbar(liste.text)
    assert 'Honorargutschrift' in sichtbar(liste.text)
    form = client.get('/invoices/neu')
    assert _optionen(form.text, 'invoice_type') == ['standard', 'prepayment', 'honorargutschrift']
    assert 'Honorargutschrift (Gutschriftverfahren)' in sichtbar(form.text)


@pytest.mark.parametrize('art,titel', [
    ('self_billing', 'SELF-BILLED INVOICE (Gutschrift)'),
    ('self_billing_storno', 'Cancellation of self-billed invoice'),
])
def test_langer_titel_ueberlappt_nummer_im_pdf_nicht(tmp_path, art, titel):
    from pypdf import PdfReader
    from reportlab.pdfbase import pdfmetrics
    from app.services.pdf_fonts import register_fonts

    inv = _beleg(art, _kunde())
    inv.document_language = 'en'
    _pdf_text(inv, _firma(), tmp_path)
    fundstellen = {}
    def sammeln(text, cm, tm, font, size):
        text = text.strip()
        if text == titel or (text == inv.invoice_number and round(size, 1) == 22):
            fundstellen[text] = (cm[0] * tm[4] + cm[2] * tm[5] + cm[4], size)
    PdfReader(str(tmp_path / 'beleg.pdf')).pages[0].extract_text(visitor_text=sammeln)
    x, size = fundstellen[titel]
    nummer_x, _ = fundstellen[inv.invoice_number]
    assert x + pdfmetrics.stringWidth(titel, register_fonts()['pixel'], size) + 8 <= nummer_x + 0.01
