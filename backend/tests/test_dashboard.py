"""
Dashboard-Aggregation (Audit-#8): main.dashboard zählt Rechnungen nach Status.
Bisher 0 Tests. Wir rufen die Route-Funktion direkt und prüfen den Template-Kontext
(robuster als HTML-Grep auf rohe Zahlen).
"""
import uuid
from datetime import date
from decimal import Decimal

from starlette.requests import Request

import app.main as main
from app.models.customer import Customer
from app.models.invoice import Invoice


def _request() -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/dashboard", "raw_path": b"/dashboard",
        "headers": [], "query_string": b"", "scheme": "http",
        "server": ("test", 80), "client": ("test", 1234),
    })


def _inv(pg_session, status, gross, issue=date.today()):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"RE-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=issue, due_date=issue, currency="EUR",
                  net_total=Decimal("0"), tax_total=Decimal("0"),
                  gross_total=Decimal(gross), status=status)
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _gutschrift(pg_session, status, gross, issue=date.today()):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"GS-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=issue, due_date=issue, currency="EUR",
                  net_total=Decimal("0"), tax_total=Decimal("0"),
                  gross_total=Decimal(gross), status=status,
                  invoice_type="credit_note")
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_dashboard_zaehlt_status_korrekt(pg_session):
    for _ in range(2):
        _inv(pg_session, "draft", "0")
    for _ in range(3):
        _inv(pg_session, "issued", "100.00")
    _inv(pg_session, "paid", "50.00")
    _inv(pg_session, "cancelled", "0")

    ctx = main.dashboard(_request(), pg_session).context
    assert ctx["total_invoices"] == 7
    assert ctx["open_invoices"] == 3      # nur 'issued'
    assert ctx["draft_count"] == 2
    # issued (3×100) + paid (50) fließen ins YTD, cancelled/draft nicht
    assert Decimal(ctx["revenue_ytd"]) == Decimal("350.00")
    assert Decimal(ctx["paid_this_month"]) == Decimal("50.00")


def test_dashboard_bezahlt_diesen_monat_nutzt_zahlungsmonat(pg_session):
    """Juli-Rechnung, im September als bezahlt markiert, zaehlt im September."""
    inv = _inv(pg_session, "issued", "300.00", issue=date(2026, 7, 8))
    inv.status = "paid"
    pg_session.commit()
    ctx = main.dashboard(_request(), pg_session).context
    assert Decimal(ctx["paid_this_month"]) == Decimal("300.00")


def test_dashboard_bezahlt_diesen_monat_ignoriert_vorherigen_monat(pg_session):
    from datetime import datetime, timezone

    _inv(pg_session, "paid", "100.00", issue=date(2026, 7, 8))
    inv = pg_session.query(Invoice).filter(Invoice.gross_total == Decimal("100.00")).one()
    inv.updated_at = datetime(2026, 8, 15, tzinfo=timezone.utc)
    pg_session.commit()
    ctx = main.dashboard(_request(), pg_session).context
    assert Decimal(ctx["paid_this_month"]) == Decimal("0.00")


def test_dashboard_leer_ist_null(pg_session):
    ctx = main.dashboard(_request(), pg_session).context
    assert ctx["total_invoices"] == 0
    assert ctx["open_invoices"] == 0
    assert ctx["draft_count"] == 0
    assert ctx["recent_invoices"] == []


def test_dashboard_per_http_route(client):
    """#42: die Route durchlaufen, nicht nur main.dashboard() direkt aufrufen."""
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "ÜBERSICHT" in r.text
    assert "RECHNUNGEN GESAMT" in r.text


def test_dashboard_http_zeigt_kennzahlen(client, pg_session):
    _inv(pg_session, "issued", "100.00")
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert ">1<" in r.text or "1</p>" in r.text
    assert "100" in r.text


def test_dashboard_ytd_ignoriert_gutschriften(pg_session):
    """#5: Gutschriften duerfen den YTD-Umsatz nicht aufblaehen."""
    _inv(pg_session, "issued", "100.00")
    _gutschrift(pg_session, "issued", "50.00")
    ctx = main.dashboard(_request(), pg_session).context
    assert Decimal(ctx["revenue_ytd"]) == Decimal("100.00")


def test_dashboard_offene_posten_ignorieren_gutschriften(pg_session):
    """#14: ausgestellte Gutschriften sind keine offenen Forderungen."""
    _inv(pg_session, "issued", "100.00")
    _gutschrift(pg_session, "issued", "50.00")
    ctx = main.dashboard(_request(), pg_session).context
    assert ctx["open_invoices"] == 1
