"""#156: Derselbe Typ bleibt je nach Herkunft frei oder betragsgebunden."""
import pytest

from app.services.belegart import manuelle_belegart
from tests.test_belegart import _kunde, _entwurf, _payload, _frisch, _gewaehlt


def test_honorargutschrift_formularwert():
    assert manuelle_belegart('honorargutschrift') == 'self_billing'


def test_manuelle_anlage(client, pg_session):
    kunde = _kunde(pg_session)
    form = client.get('/invoices/neu')
    assert 'Honorargutschrift (Gutschriftverfahren)' in form.text
    assert 'Leistung aus, die Sie empfangen haben' in form.text
    response = client.post('/invoices/neu', data=_payload(kunde, invoice_type='honorargutschrift'))
    assert response.status_code == 303, response.text
    edit = client.get(response.headers['location'] + '/bearbeiten')
    assert _gewaehlt(edit.text, 'invoice_type') == 'honorargutschrift'


@pytest.mark.parametrize('aus_beleg,preis', [(False, 250), (True, 100)])
def test_bearbeitung_nach_herkunft(client, pg_session, aus_beleg, preis):
    kunde = _kunde(pg_session)
    inv = _entwurf(pg_session, kunde, invoice_type='self_billing', aus_beleg=aus_beleg)
    response = client.post(f'/invoices/{inv.id}/bearbeiten', data=_payload(kunde, items=[{
        'description': 'Geänderter Text', 'unit': 'Stunde', 'quantity': '1',
        'unit_price': '250', 'tax_rate': '19',
    }]))
    assert response.status_code == 303, response.text
    row = _frisch(pg_session, inv.id)
    assert row.invoice_type == 'self_billing'
    assert row.items[0].unit_price == preis
    assert row.items[0].description == 'Geänderter Text'
