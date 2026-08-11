"""
POST /invoices/{id}/storno als ECHTE Integration (Follow-up zum Audit-#10-Sweep).

Der bisherige Happy-Path (test_storno_router.py) lief gegen _FakeDB und prüfte nur
db.added — db.add() passiert VOR db.commit(), also bliebe der Test grün, wenn der
Commit fehlte. Storno erzeugt eine rechtlich relevante Gutschrift; Persistenz muss
bewiesen sein. Hier: pg_session, Re-Query nach dem Commit.
"""
import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem


def teardown_function():
    app.dependency_overrides.clear()


def _original(pg_session, status="issued"):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number="ALT-2025-500", customer_id=c.id,
                  issue_date=date(2025, 6, 11), due_date=date(2025, 6, 25), currency="EUR",
                  zugferd_profile="EN16931", tax_category="S", status=status,
                  net_total=Decimal("1000.00"), tax_total=Decimal("190.00"),
                  gross_total=Decimal("1190.00"))
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Std",
                             quantity=Decimal("10"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("1000.00"),
                             tax_amount=Decimal("190.00"), gross_amount=Decimal("1190.00"))]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def test_storno_persists_credit_note_and_leaves_original(pg_session):
    original = _original(pg_session, "issued")
    r = _client(pg_session).post(f"/invoices/{original.id}/storno")
    assert r.status_code == 303

    pg_session.expire_all()
    storno = (pg_session.query(Invoice)
              .filter(Invoice.original_invoice_id == original.id).first())
    assert storno is not None, "Storno wurde nicht persistiert (fehlender Commit?)"
    assert storno.invoice_type == "credit_note"
    assert storno.gross_total == Decimal("1190.00")          # positiv (Wirkung via TypeCode 381)
    assert storno.status == "draft"
    assert len(storno.items) == 1
    assert storno.invoice_number != original.invoice_number  # frische fortlaufende Nummer

    original = pg_session.get(Invoice, original.id)
    assert original.status == "issued"                       # Original unverändert
    assert original.invoice_type is None


def test_storno_of_draft_persists_nothing(pg_session):
    original = _original(pg_session, "draft")
    r = _client(pg_session).post(f"/invoices/{original.id}/storno")
    assert r.status_code == 400
    pg_session.expire_all()
    assert pg_session.query(Invoice).filter(
        Invoice.original_invoice_id == original.id).first() is None


def test_storno_of_credit_note_is_rejected(pg_session):
    """Eine Gutschrift kann nicht erneut storniert werden → 400 (portiert aus dem
    gelöschten Mock-Test test_storno_router.py, jetzt mit echter DB). Als credit_note
    in EINER Txn angelegt — nachträgliches Setzen an einer issued-Rechnung würde am
    invoice_guard scheitern."""
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.flush()
    original = Invoice(invoice_number="GS-2025-1", customer_id=c.id,
                       issue_date=date(2025, 6, 11), due_date=date(2025, 6, 25),
                       currency="EUR", zugferd_profile="EN16931", tax_category="S",
                       status="issued", invoice_type="credit_note",
                       net_total=Decimal("1000.00"), tax_total=Decimal("190.00"),
                       gross_total=Decimal("1190.00"))
    pg_session.add(original)
    pg_session.commit()
    r = _client(pg_session).post(f"/invoices/{original.id}/storno")
    assert r.status_code == 400
    pg_session.expire_all()
    assert pg_session.query(Invoice).filter(
        Invoice.original_invoice_id == original.id).first() is None


def test_storno_of_unknown_invoice_is_404(pg_session):
    r = _client(pg_session).post(f"/invoices/{uuid.uuid4()}/storno")
    assert r.status_code == 404
