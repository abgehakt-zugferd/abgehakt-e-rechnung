"""
POST /invoices/{id}/pruefen mit ECHTEM Validator (Audit-#4).

Der bisher einzige pruefen-Test (test_tempfile_safety) mockt Validator UND Mustang
weg — die § 14-UStG-Prüfung war also nie wirklich getestet. Hier gegen echtes
Postgres + echten validator.validate_invoice:
  - ValidationResult wird persistiert (is_valid + errors)
  - fehlerhafte Rechnung: is_valid=False, NO_ITEMS im errors-Payload
  - Prüfen ändert NIE den Status (draft bleibt draft, auch bei Fehlern)
  - valide Rechnung: is_valid=True

Draft-Rechnungen haben kein zugferd_xml → der Router ruft Mustang gar nicht auf,
daher kein Mustang-Skip nötig.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem, ValidationResult
from app.services import mustang, zugferd_xml

_needs_mustang = pytest.mark.skipif(
    not mustang.jar_available(), reason="Mustang-JAR nicht verfügbar"
)


def teardown_function():
    app.dependency_overrides.clear()


def _customer(pg_session):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.flush()
    return c


def _invoice(pg_session, *, with_item: bool):
    c = _customer(pg_session)
    inv = Invoice(invoice_number=f"RE-2026-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=date(2026, 6, 1), due_date=date(2026, 6, 15), currency="EUR",
                  net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
                  gross_total=Decimal("238.00"), tax_category="S", status="draft",
                  payment_terms="14 Tage")
    if with_item:
        inv.items = [InvoiceItem(
            position=1, description="Beratung", unit="Std", quantity=Decimal("2"),
            unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
            net_amount=Decimal("200.00"), tax_amount=Decimal("38.00"),
            gross_amount=Decimal("238.00"))]
    else:
        inv.net_total = Decimal("0.00")
        inv.tax_total = Decimal("0.00")
        inv.gross_total = Decimal("0.00")
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _latest_result(pg_session, invoice_id):
    return (pg_session.query(ValidationResult)
            .filter(ValidationResult.invoice_id == invoice_id)
            .order_by(ValidationResult.validated_at.desc()).first())


def test_pruefen_persistiert_fehler_und_laesst_draft(pg_session):
    inv = _invoice(pg_session, with_item=False)   # NO_ITEMS-Fehler
    r = _client(pg_session).post(f"/invoices/{inv.id}/pruefen")
    assert r.status_code == 303

    result = _latest_result(pg_session, inv.id)
    assert result is not None
    assert result.is_valid is False
    codes = {e["code"] for e in result.errors}
    assert "NO_ITEMS" in codes

    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).status == "draft"


def test_pruefen_valide_rechnung_is_valid(pg_session):
    inv = _invoice(pg_session, with_item=True)
    _client(pg_session).post(f"/invoices/{inv.id}/pruefen")

    result = _latest_result(pg_session, inv.id)
    assert result is not None
    assert result.is_valid is True, f"unerwartete Fehler: {result.errors}"
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).status == "draft"


def test_pruefen_unbekannte_id_404(pg_session):
    r = _client(pg_session).post(f"/invoices/{uuid.uuid4()}/pruefen")
    assert r.status_code == 404


# ── Mustang-Pfad: Rechnung mit hinterlegter zugferd_xml ───────────────────────
# Der bisher getestete Pfad hat KEIN zugferd_xml → Mustang wird nie aufgerufen.
# Hier wird der zweite Zweig (mustang.validate) real ausgeführt.

@_needs_mustang
def test_pruefen_mit_gueltiger_xml_setzt_mustang_output(pg_session):
    inv = _invoice(pg_session, with_item=True)
    inv.delivery_date = date(2026, 6, 1)   # EN16931: Leistungsdatum für schema-valide XML
    company = pg_session.query(Company).filter(Company.id == 1).first()
    inv.zugferd_xml = zugferd_xml.generate_xml(inv, company)
    pg_session.commit()

    _client(pg_session).post(f"/invoices/{inv.id}/pruefen")
    result = _latest_result(pg_session, inv.id)
    assert result.mustang_output is not None
    assert "XML:valid" in result.mustang_output
    assert result.is_valid is True


@_needs_mustang
def test_pruefen_mit_schemafehler_xml_setzt_is_valid_false(pg_session):
    inv = _invoice(pg_session, with_item=True)
    inv.zugferd_xml = "<nonsense/>"        # schema-invalide XML
    pg_session.commit()

    _client(pg_session).post(f"/invoices/{inv.id}/pruefen")
    result = _latest_result(pg_session, inv.id)
    assert result.mustang_output is not None
    assert result.is_valid is False        # Mustang-Schemafehler zieht is_valid runter
