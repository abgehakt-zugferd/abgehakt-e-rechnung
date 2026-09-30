"""Issue #120: eine Position darf eine finalisierte Rechnung nicht per Umhängen verlassen.

Der Positions-Guard fragte den Status der Rechnung ab, auf die `invoice_id` NACH der
Änderung zeigt. Hängt man eine Position von einer finalisierten Rechnung auf einen
Entwurf um, sieht er nur den Entwurf. Die Datenbank-Auslöser sperren kein UPDATE, und
Positionen werden nicht auditiert; der Guard ist hier die einzige Verteidigungslinie.

Geprüft über beide Wege, die das ORM anbietet: den Fremdschlüssel und die Beziehung.
"""
import pytest

from app.models.invoice import InvoiceItem
from app.services.invoice_guard import InvoiceStateError
from tests.test_invoice_guard import _invoice_with_item


def _unveraendert(session, finalisiert, item_id):
    session.rollback()
    session.expire_all()
    assert session.get(InvoiceItem, item_id).invoice_id == finalisiert.id
    assert len(finalisiert.items) == 1


@pytest.mark.parametrize("status", ["issued", "paid", "cancelled"])
def test_umhaengen_per_fremdschluessel_auf_entwurf_verboten(pg_session, status):
    finalisiert = _invoice_with_item(pg_session, status=status)
    entwurf = _invoice_with_item(pg_session, status="draft")
    item = finalisiert.items[0]
    item_id = item.id

    item.invoice_id = entwurf.id
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    _unveraendert(pg_session, finalisiert, item_id)


def test_umhaengen_per_beziehung_auf_entwurf_verboten(pg_session):
    finalisiert = _invoice_with_item(pg_session, status="issued")
    entwurf = _invoice_with_item(pg_session, status="draft")
    item = finalisiert.items[0]
    item_id = item.id

    entwurf.items.append(item)
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    _unveraendert(pg_session, finalisiert, item_id)


def test_umhaengen_zwischen_entwuerfen_erlaubt(pg_session):
    """Gegenstück: ohne finalisierte Seite ist Umhängen gewöhnliche Bearbeitung."""
    quelle = _invoice_with_item(pg_session, status="draft")
    ziel = _invoice_with_item(pg_session, status="draft")
    item = quelle.items[0]

    item.invoice_id = ziel.id
    pg_session.commit()
    assert pg_session.get(InvoiceItem, item.id).invoice_id == ziel.id
