"""Zurueckholen verworfener Storno-Entwuerfe (#178).

Wenn zum selben Original inzwischen eine andere Gutschrift existiert oder das
Original nicht mehr stornierbar ist, muss Zurueckholen fachlich mit 4xx
antworten — nicht mit HTTP 500 am Unique-Index.
"""
import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services.invoice_guard import register_invoice_guard

register_invoice_guard()

GUTSCHRIFT_MELDUNG = "Zu dieser Rechnung existiert bereits die Gutschrift"


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session, *, raise_server_exceptions=True):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(
        app, follow_redirects=False, raise_server_exceptions=raise_server_exceptions,
    )


def _kunde(pg_session):
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Probe Kunde",
        address_line1="Weg 1", zip_code="80331", city="Muenchen",
        country="DE", email="kunde@example.test",
    )
    pg_session.add(c)
    pg_session.flush()
    return c


def _rechnung(pg_session, *, status="issued", art=None, original=None,
              nummer=None):
    c = _kunde(pg_session)
    netto, steuer = Decimal("100.00"), Decimal("19.00")
    inv = Invoice(
        invoice_number=nummer or f"RE-SZ-{uuid.uuid4().hex[:6]}",
        customer_id=c.id, issue_date=date(2026, 9, 1),
        due_date=date(2026, 9, 15), currency="EUR",
        net_total=netto, tax_total=steuer, gross_total=netto + steuer,
        status=status, invoice_type=art,
        original_invoice_id=original.id if original else None,
        zugferd_profile="EN16931", tax_category="S",
    )
    inv.items = [InvoiceItem(
        position=1, description="Beratung", unit="Stunde", quantity=Decimal("1"),
        unit_price=netto, tax_rate=Decimal("19"), net_amount=netto,
        tax_amount=steuer, gross_amount=netto + steuer,
    )]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _verworfene_und_aktive_gutschrift(pg_session):
    original = _rechnung(pg_session, status="issued", nummer="RE-SZ-ZO")
    verworfen = _rechnung(
        pg_session, status="discarded", art="credit_note", original=original,
        nummer="GS-SZ-A",
    )
    aktiv = _rechnung(
        pg_session, status="draft", art="credit_note", original=original,
        nummer="GS-SZ-B",
    )
    return original, verworfen, aktiv


def test_zurueckholen_zweitgutschrift_liefert_fachliche_4xx(pg_session):
    """Verworfene Gutschrift zurueckholen, waehrend schon eine andere zum selben
    Original existiert → fachliche 4xx, kein 500."""
    _, verworfen, _ = _verworfene_und_aktive_gutschrift(pg_session)

    r = _client(pg_session, raise_server_exceptions=False).post(
        f"/invoices/{verworfen.id}/zurueckholen"
    )
    assert 400 <= r.status_code < 500, r.text


def test_zurueckholen_bei_cancelled_original_liefert_fachliche_4xx(pg_session):
    """Original inzwischen von Hand auf cancelled → Zurueckholen fachlich 4xx."""
    original = _rechnung(pg_session, status="issued", nummer="RE-SZ-CAN")
    verworfen = _rechnung(
        pg_session, status="discarded", art="credit_note", original=original,
        nummer="GS-SZ-CAN",
    )
    original.status = "cancelled"
    pg_session.commit()

    r = _client(pg_session, raise_server_exceptions=False).post(
        f"/invoices/{verworfen.id}/zurueckholen"
    )
    assert 400 <= r.status_code < 500, r.text
    pg_session.expire_all()
    assert pg_session.get(Invoice, verworfen.id).status == "discarded"


def test_zurueckholen_storno_ohne_konflikt_klappt(pg_session):
    """Gegentest: verworfene Gutschrift ohne Konkurrenz wird wieder Entwurf."""
    original = _rechnung(pg_session, status="issued", nummer="RE-SZ-OK")
    verworfen = _rechnung(
        pg_session, status="discarded", art="credit_note", original=original,
        nummer="GS-SZ-OK",
    )

    r = _client(pg_session).post(f"/invoices/{verworfen.id}/zurueckholen")
    assert r.status_code == 303, r.text
    pg_session.expire_all()
    assert pg_session.get(Invoice, verworfen.id).status == "draft"


def test_zurueckholen_zweitgutschrift_meldung_wie_beim_anlegen(pg_session):
    """Dieselbe fachliche Meldung wie beim Anlegen einer zweiten Gutschrift."""
    original, verworfen, aktiv = _verworfene_und_aktive_gutschrift(pg_session)
    client = _client(pg_session, raise_server_exceptions=False)

    r_anlegen = client.post(f"/invoices/{original.id}/storno")
    assert r_anlegen.status_code == 400, r_anlegen.text
    assert GUTSCHRIFT_MELDUNG in r_anlegen.text
    assert aktiv.invoice_number in r_anlegen.text

    r_zurueck = client.post(f"/invoices/{verworfen.id}/zurueckholen")
    assert r_zurueck.status_code == 400, r_zurueck.text
    assert GUTSCHRIFT_MELDUNG in r_zurueck.text
    assert aktiv.invoice_number in r_zurueck.text
