"""
GoBD/Stammdaten-Schutz (#98 P0.4): Kunden dürfen NIE hard-gelöscht werden
(docs/ARCHITEKTUR.md: Kunden nie hart löschen — nur deleted_at setzen). Die Soft-Delete-
Route ist getestet (test_customers_delete.py), aber `session.delete(customer)` hatte
keinen DB-Guard — analog invoice_guard schließt customer_guard das auf Session-Ebene,
sodass kein Codepfad (Router, Skript, SQLAlchemy-Shell) es umgehen kann.
"""
import uuid
from datetime import datetime, timezone

import pytest

from app.models.customer import Customer
from app.services.audit import register_audit_listeners
from app.services.customer_guard import CustomerDeleteError, register_customer_guard

register_customer_guard()
register_audit_listeners()


def _customer(session) -> Customer:
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    session.add(c)
    session.commit()
    return c


def test_hard_delete_forbidden(pg_session):
    c = _customer(pg_session)
    pg_session.delete(c)
    with pytest.raises(CustomerDeleteError):
        pg_session.commit()
    pg_session.rollback()


def test_soft_delete_allowed(pg_session):
    c = _customer(pg_session)
    c.deleted_at = datetime.now(timezone.utc)
    pg_session.commit()
    assert pg_session.get(Customer, c.id).deleted_at is not None


def test_edit_allowed(pg_session):
    c = _customer(pg_session)
    c.name = "Kunde AG"
    pg_session.commit()
    assert pg_session.get(Customer, c.id).name == "Kunde AG"


def test_blocked_hard_delete_leaves_no_audit_ghost(pg_session):
    """#98 P2 (analog invoice_guard): der customer_guard MUSS vor dem Audit-Listener
    laufen — sonst bliebe nach einem abgebrochenen Hard-Delete-Flush eine Pending-
    Audit-Zeile in session.info liegen und würde beim nächsten legalen Flush als
    Geister-`delete` geschrieben."""
    from app.models.invoice import AuditLog
    c = _customer(pg_session)
    pg_session.delete(c)
    with pytest.raises(CustomerDeleteError):
        pg_session.commit()
    pg_session.rollback()
    # Legaler Folge-Flush darf keine delete-Audit-Zeile aus dem abgebrochenen Flush erben
    other = _customer(pg_session)
    other.name = "ok"
    pg_session.commit()
    ghosts = (
        pg_session.query(AuditLog)
        .filter(AuditLog.record_id == str(c.id), AuditLog.action == "delete")
        .all()
    )
    assert ghosts == []
