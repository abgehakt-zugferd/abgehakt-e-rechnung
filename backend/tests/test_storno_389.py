"""#156: Ein 389-Storno behält Rollen und positive Beträge, mit Originalbezug."""
from datetime import date
from decimal import Decimal

import pytest

from app.services.belegart import belegart
from app.services.belegrollen import besetzung
from app.services.storno import build_storno, pruefe_stornierbar
from app.services.validator import validate_invoice
from app.services.zugferd_xml import generate_xml
from tests.factories import company_stub, validator_invoice_stub, item_stub
from tests.test_validator_389 import _kunde, _entwurf


@pytest.mark.parametrize('art,erwartet', [('self_billing', True), (None, False), ('credit_note', False)])
def test_nullpreis_nur_389(art, erwartet):
    inv = validator_invoice_stub(invoice_type=art, items=[item_stub(unit_price=Decimal('0'))])
    errors, _ = validate_invoice(inv, company_stub())
    befunde = [e for e in errors if e.code == 'ITEM_PRICE_ZERO']
    assert bool(befunde) == erwartet
    if erwartet:
        assert befunde[0].field == 'items[1].unit_price'


def test_storno_389_beleg(pg_session):
    original = _entwurf(pg_session, _kunde(pg_session))
    original.status = 'issued'
    pg_session.commit()
    pruefe_stornierbar(original)
    storno = build_storno(original, 'ST-389', date(2026, 10, 17))
    storno.customer = original.customer
    storno.original_invoice = original
    art = belegart(storno.invoice_type)
    assert art.intern == 'self_billing_storno'
    assert art.braucht_original and not art.manuell_waehlbar
    assert storno.original_invoice_id == original.id
    assert storno.net_total == original.net_total > 0
    assert storno.items[0].unit_price == original.items[0].unit_price > 0
    rollen = besetzung(storno, company_stub(), original.customer)
    assert not rollen.verkaeufer_ist_firma
    assert rollen.verkaeufer.name == original.customer.name
    assert 'Storno zur Gutschrift' in storno.payment_terms
    assert original.invoice_number in storno.notes
    xml = generate_xml(storno, company_stub())
    assert f'<ram:TypeCode>{art.bt3}</ram:TypeCode>' in xml
    assert f'Stornierung der Gutschrift Nr. {original.invoice_number}' in xml
    assert '<ram:InvoiceReferencedDocument>' in xml


@pytest.mark.parametrize('sprache,titel', [
    ('de', 'Stornierung der Gutschrift'),
    ('en', 'Cancellation of self-billed invoice'),
])
def test_storno_389_pdf_und_systemnote(pg_session, tmp_path, sprache, titel):
    from tests.test_pdf_besetzung_389 import _pdf_text, _firma
    original = _entwurf(pg_session, _kunde(pg_session))
    original.document_language = sprache
    storno = build_storno(original, 'ST-PDF-389', date(2026, 10, 17))
    storno.customer = original.customer
    storno.original_invoice = original
    storno.notes = None
    text = _pdf_text(storno, _firma(), tmp_path)
    assert titel in text
    assert 'Stornierung der Gutschrift Nr.' in generate_xml(storno, company_stub())


def test_storno_389_bleibt_betragsgleich_und_gesperrt(client, pg_session):
    from app.models.invoice import Invoice
    from app.services.ersatzrechnung import ErsatzNichtMoeglich, pruefe_ersetzbar
    original = _entwurf(pg_session, _kunde(pg_session))
    original.status = 'issued'
    pg_session.commit()
    response = client.post(f'/invoices/{original.id}/storno')
    assert response.status_code == 303, response.text
    storno = pg_session.query(Invoice).filter(Invoice.original_invoice_id == original.id).one()
    assert storno.invoice_type == 'self_billing_storno'
    assert client.post(f'/invoices/{original.id}/storno').status_code == 400
    assert client.get(f'/invoices/{storno.id}/bearbeiten').status_code == 400
    assert client.post(f'/invoices/{storno.id}/bearbeiten', data={}).status_code == 400
    with pytest.raises(ErsatzNichtMoeglich, match='ERSATZ_ORIGINAL_KEINE_RECHNUNG'):
        pruefe_ersetzbar(pg_session, original.id)
    storno.net_total += Decimal('1')
    errors, _ = validate_invoice(storno, company_stub())
    assert 'STORNO_AMOUNT_MISMATCH' in {e.code for e in errors}
