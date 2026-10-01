"""Umsatz der Uebersicht: nur bezahlt, netto, nach bezahlt_am.

Entscheidung des Betreibers vom 2026-09-30. Durchstich ueber main.dashboard;
Vertiefungen fuer Route, Guard und Migration liegen in eigenen Dateien.
"""
import uuid
from datetime import date, datetime, timezone
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


def _probe_kunde(pg_session) -> Customer:
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Probe Kunde GmbH",
        address_line1="Probeweg 1",
        zip_code="80331",
        city="Muenchen",
        country="DE",
    )
    pg_session.add(c)
    pg_session.flush()
    return c


def _rechnung(
    pg_session,
    *,
    status: str,
    gross: str,
    net: str,
    tax: str,
    issue: date,
    bezahlt_am: date | None = None,
) -> Invoice:
    c = _probe_kunde(pg_session)
    inv = Invoice(
        invoice_number=f"RE-{uuid.uuid4().hex[:6]}",
        customer_id=c.id,
        issue_date=issue,
        due_date=issue,
        currency="EUR",
        net_total=Decimal(net),
        tax_total=Decimal(tax),
        gross_total=Decimal(gross),
        status=status,
        bezahlt_am=bezahlt_am,
    )
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_dashboard_umsatz_zaehlt_nur_bezahlte_netto(pg_session):
    """Durchstich: gestellte unbezahlte Rechnung zaehlt nicht; bezahlte mit Netto."""
    heute = date.today()
    _rechnung(
        pg_session,
        status="issued",
        gross="119.00",
        net="100.00",
        tax="19.00",
        issue=heute,
    )
    _rechnung(
        pg_session,
        status="paid",
        gross="238.00",
        net="200.00",
        tax="38.00",
        issue=heute,
        bezahlt_am=heute,
    )
    ctx = main.dashboard(_request(), pg_session).context
    assert Decimal(ctx["revenue_ytd"]) == Decimal("200.00")


def test_dashboard_umsatz_folgt_bezahlt_am_nicht_rechnungsdatum(pg_session):
    """Vorjahr gestellt, dieses Jahr bezahlt: zaehlt. Vorjahr bezahlt: nicht."""
    heute = date.today()
    _rechnung(
        pg_session,
        status="paid",
        gross="119.00",
        net="100.00",
        tax="19.00",
        issue=date(heute.year - 1, 6, 15),
        bezahlt_am=heute,
    )
    _rechnung(
        pg_session,
        status="paid",
        gross="238.00",
        net="200.00",
        tax="38.00",
        issue=heute,
        bezahlt_am=date(heute.year - 1, 12, 15),
    )
    ctx = main.dashboard(_request(), pg_session).context
    assert Decimal(ctx["revenue_ytd"]) == Decimal("100.00")


def test_dashboard_bezahlt_monat_folgt_bezahlt_am_nicht_updated_at(pg_session):
    """Spaeteres datev_sent_at verschiebt updated_at, nicht den Zahlungsmonat."""
    heute = date.today()
    if heute.month == 1:
        bezahlt = date(heute.year - 1, 12, 15)
    else:
        bezahlt = date(heute.year, heute.month - 1, 15)
    inv = _rechnung(
        pg_session,
        status="paid",
        gross="119.00",
        net="100.00",
        tax="19.00",
        issue=bezahlt,
        bezahlt_am=bezahlt,
    )
    inv.datev_sent_at = datetime.now(timezone.utc)
    pg_session.commit()
    ctx = main.dashboard(_request(), pg_session).context
    assert Decimal(ctx["paid_this_month"]) == Decimal("0.00")


def test_dashboard_bezahlt_diesen_monat_summiert_brutto(pg_session):
    """Geldeingang bleibt brutto; Netto und Brutto muessen verschieden sein."""
    heute = date.today()
    _rechnung(
        pg_session,
        status="paid",
        gross="119.00",
        net="100.00",
        tax="19.00",
        issue=heute,
        bezahlt_am=heute,
    )
    ctx = main.dashboard(_request(), pg_session).context
    assert Decimal(ctx["paid_this_month"]) == Decimal("119.00")
