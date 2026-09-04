"""
Smoke-Tests für die Lese-Routen (#98 P2): GET /invoices/ (Liste, inkl. Status-/
Suchfilter) und GET /invoices/{id} (Detail) waren ungetestet — ein Template-/
Query-Bruch dort fiel bisher durch kein Netz. pg_session, echtes Rendering.
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _invoice(pg_session, number="RE-2026-777", status="issued"):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Smoke GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=number, customer_id=c.id, issue_date=date(2026, 6, 1),
                  due_date=date(2026, 6, 15), currency="EUR", tax_category="S", status=status,
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"))
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Std",
                             quantity=Decimal("1"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
                             tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"))]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_list_invoices_renders(pg_session):
    _invoice(pg_session, number="RE-2026-777")
    r = _client(pg_session).get("/invoices/")
    assert r.status_code == 200
    assert "RE-2026-777" in r.text


def test_list_invoices_status_filter(pg_session):
    _invoice(pg_session, number="RE-2026-777", status="issued")
    _invoice(pg_session, number="RE-2026-778", status="draft")
    r = _client(pg_session).get("/invoices/?status=draft")
    assert r.status_code == 200
    assert "RE-2026-778" in r.text
    assert "RE-2026-777" not in r.text


def test_liste_zeigt_versandstatus_fuer_issued(pg_session):
    """issued ohne Versand ≠ issued mit Versand — beides muss in der Liste lesbar sein."""
    offen = _invoice(pg_session, number="RE-2026-880", status="issued")
    versendet = _invoice(pg_session, number="RE-2026-881", status="issued")
    versendet.datev_sent_at = datetime(2026, 9, 2, 13, 0, tzinfo=timezone.utc)
    pg_session.commit()

    html = _client(pg_session).get("/invoices/").text
    assert "Nicht versendet" in html
    assert "Versendet" in html
    assert offen.invoice_number in html
    assert versendet.invoice_number in html


def test_invoice_detail_renders(pg_session):
    inv = _invoice(pg_session, number="RE-2026-779")
    r = _client(pg_session).get(f"/invoices/{inv.id}")
    assert r.status_code == 200
    assert "RE-2026-779" in r.text


def test_invoice_detail_unknown_404(pg_session):
    r = _client(pg_session).get(f"/invoices/{uuid.uuid4()}")
    assert r.status_code == 404


def test_liste_liest_kunden_ohne_n_plus_eins(pg_session):
    """#1: joinedload verhindert Lazy-Loads je Zeile in der Rechnungsliste."""
    for i in range(5):
        _invoice(pg_session, number=f"RE-N1-{i}")
    engine = pg_session.bind
    abfragen: list[str] = []

    def zaehle(*args, **kwargs):
        abfragen.append(args[0])

    event.listen(engine, "before_cursor_execute", zaehle)
    try:
        r = _client(pg_session).get("/invoices/")
        assert r.status_code == 200
        assert "Smoke GmbH" in r.text
        # Mit N+1 waeren es deutlich mehr als count + eine Join-Abfrage.
        assert len(abfragen) <= 6, f"Zu viele SQL-Abfragen: {len(abfragen)}"
    finally:
        event.remove(engine, "before_cursor_execute", zaehle)
