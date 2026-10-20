"""Ueberfaellige Forderungen: Kennzahl und Listenfilter zaehlen dieselbe Menge.

Issue #177: der Listenfilter ``faellig=ueberfaellig`` darf nicht nur das
Faelligkeitsdatum pruefen, waehrend die Kennzahl Status, Umsatz-Belegarten und
wirksames Storno mitfiltert.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services.dashboard_kennzahlen import ueberfaellige_forderungen
from app.services.invoice_guard import register_invoice_guard
from app.services.rechnungsliste_filter import filtere_rechnungsliste

register_invoice_guard()

HEUTE = date(2026, 10, 8)
GESTERN = HEUTE - timedelta(days=1)


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _kunde(pg_session):
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Probe Kunde",
        address_line1="Weg 1",
        zip_code="80331",
        city="Muenchen",
        country="DE",
        email="kunde@example.test",
    )
    pg_session.add(c)
    pg_session.flush()
    return c


def _rechnung(
    pg_session,
    *,
    status="issued",
    faellig=GESTERN,
    art=None,
    original=None,
    nummer=None,
):
    c = _kunde(pg_session)
    netto, steuer = Decimal("100.00"), Decimal("19.00")
    inv = Invoice(
        invoice_number=nummer or f"RE-UEB-{uuid.uuid4().hex[:6]}",
        customer_id=c.id,
        issue_date=date(2026, 9, 1),
        due_date=faellig,
        currency="EUR",
        net_total=netto,
        tax_total=steuer,
        gross_total=netto + steuer,
        status=status,
        invoice_type=art,
        original_invoice_id=original.id if original else None,
        bezahlt_am=date(2026, 9, 20) if status == "paid" else None,
        zugferd_profile="EN16931",
        tax_category="S",
    )
    inv.items = [
        InvoiceItem(
            position=1,
            description="Beratung",
            unit="Stunde",
            quantity=Decimal("1"),
            unit_price=netto,
            tax_rate=Decimal("19"),
            net_amount=netto,
            tax_amount=steuer,
            gross_amount=netto + steuer,
        )
    ]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_ueberfaellig_filter_wie_kennzahl_ohne_bezahlt_und_storno(pg_session):
    """Filter „ueberfaellig“ und Kennzahl schliessen bezahlte und wirksam
    stornierte Belege gleich aus; Anzahl Kennzahl == Anzahl Listenfilter."""
    offen = _rechnung(pg_session, status="issued", nummer="RE-UEB-OFF")
    bezahlt = _rechnung(pg_session, status="paid", nummer="RE-UEB-PAY")
    storniert = _rechnung(pg_session, status="issued", nummer="RE-UEB-STO")
    gutschrift = _rechnung(
        pg_session,
        status="issued",
        art="credit_note",
        original=storniert,
        nummer="GS-UEB-STO",
    )
    assert gutschrift.original_invoice_id == storniert.id
    entwurf = _rechnung(pg_session, status="draft", nummer="RE-UEB-ENT")
    anzahlung = _rechnung(
        pg_session, status="issued", art="prepayment", nummer="RE-UEB-ANZ",
    )

    kennzahl = ueberfaellige_forderungen(pg_session, HEUTE)
    query, _ = filtere_rechnungsliste(
        pg_session.query(Invoice), faellig="ueberfaellig", heute=HEUTE,
    )
    listen_ids = {row.id for row in query.all()}

    assert kennzahl.anzahl == len(listen_ids)
    assert kennzahl.anzahl == 2
    assert listen_ids == {offen.id, anzahlung.id}

    r = _client(pg_session).get("/invoices/?faellig=ueberfaellig")
    assert r.status_code == 200
    assert offen.invoice_number in r.text
    assert anzahlung.invoice_number in r.text
    assert bezahlt.invoice_number not in r.text
    assert storniert.invoice_number not in r.text
    assert gutschrift.invoice_number not in r.text
    assert entwurf.invoice_number not in r.text
