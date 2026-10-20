"""Guard als zweite Schicht: bezahlt trotz Gutschrift und Datumsfenster (#174)."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

import app.zeit as zeit
from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services.invoice_guard import InvoiceStateError, register_invoice_guard

register_invoice_guard()


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _kunde(pg_session, *, name="Beispiel GmbH"):
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name=name,
        address_line1="Beispielweg 1",
        zip_code="80331",
        city="Muenchen",
        country="DE",
    )
    pg_session.add(c)
    pg_session.flush()
    return c


def _positionen():
    return [InvoiceItem(
        position=1, description="Beratung", unit="Stunde",
        quantity=Decimal("1"), unit_price=Decimal("100.00"),
        tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
        tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"),
    )]


def _beleg(pg_session, kunde, *, status="issued", invoice_type=None, original=None):
    inv = Invoice(
        invoice_number=f"RE-BG-{uuid.uuid4().hex[:6]}",
        customer_id=kunde.id,
        issue_date=date(2026, 6, 1),
        due_date=date(2026, 6, 15),
        delivery_date=date(2026, 6, 1),
        currency="EUR",
        tax_category="S",
        status=status,
        invoice_type=invoice_type,
        original_invoice_id=original.id if original else None,
        net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
        payment_terms="Zahlbar in 14 Tagen.",
    )
    inv.items = _positionen()
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_c_waechter_sperrt_paid_trotz_aktiver_gutschrift(pg_session):
    """Gewuenscht: Guard kennt BezahltTrotzGutschrift (#15) wie bezahlt_am.py."""
    kunde = _kunde(pg_session)
    original = _beleg(pg_session, kunde)
    _beleg(pg_session, kunde, invoice_type="credit_note", original=original)

    original.status = "paid"
    original.bezahlt_am = date(2026, 6, 10)
    with pytest.raises(InvoiceStateError, match="Gutschrift|bezahlt"):
        pg_session.flush()
    pg_session.rollback()


def test_c_status_route_lehnt_paid_trotz_gutschrift_ab(pg_session):
    """Gegenprobe Route: vorbereiten_bezahlt sperrt (bereits bekannt, #15)."""
    kunde = _kunde(pg_session)
    original = _beleg(pg_session, kunde)
    _beleg(pg_session, kunde, invoice_type="credit_note", original=original)

    r = _client(pg_session).post(
        f"/invoices/{original.id}/status",
        data={"new_status": "paid", "bezahlt_am": "2026-06-10"},
    )

    assert r.status_code == 400, r.text
    pg_session.expire_all()
    assert pg_session.get(Invoice, original.id).status == "issued"


def test_c_waechter_sperrt_bezahlt_am_vor_rechnungsdatum(pg_session, monkeypatch):
    """Guard lehnt paid ab, wenn bezahlt_am vor issue_date liegt."""
    monkeypatch.setattr(
        zeit, "_utc_jetzt",
        lambda: datetime(2026, 6, 20, 12, 0, tzinfo=timezone.utc),
    )
    kunde = _kunde(pg_session)
    inv = _beleg(pg_session, kunde)

    inv.status = "paid"
    inv.bezahlt_am = date(2026, 5, 20)
    with pytest.raises(InvoiceStateError, match="Rechnungsdatum|Zahlungsdatum"):
        pg_session.flush()
    pg_session.rollback()


def test_c_waechter_sperrt_bezahlt_am_in_der_zukunft(pg_session, monkeypatch):
    """Guard lehnt paid ab, wenn bezahlt_am nach heute (app.zeit) liegt."""
    monkeypatch.setattr(
        zeit, "_utc_jetzt",
        lambda: datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc),
    )
    kunde = _kunde(pg_session)
    inv = _beleg(pg_session, kunde)

    inv.status = "paid"
    inv.bezahlt_am = date(2026, 6, 15)
    with pytest.raises(InvoiceStateError, match="Zukunft|Zahlungsdatum"):
        pg_session.flush()
    pg_session.rollback()
