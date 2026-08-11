"""Entwürfe verwerfen (#145).

Warum kein Hard-Delete: das Löschen von `invoices` ist doppelt gesperrt
(`invoice_guard` auf Session-Ebene + `BEFORE DELETE`-Trigger aus Migration 019),
und die Rechnungsnummer ist beim Entwurf bereits vergeben — ein echtes Löschen
risse eine Nummernlücke, für die kein Beleg mehr existiert, der sie erklärt.
Stattdessen der Status `discarded`: der Datensatz bleibt, die Nummer bleibt belegt.

`discarded` ist NICHT `cancelled`. `cancelled` ist ein gestellter, stornierter
Beleg mit PDF und XML; `discarded` ist ein nie gestellter Entwurf. Sie dürfen in
Listen, Zählern und Exporten nie zusammenfallen.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.services.invoice_guard import InvoiceStateError


def teardown_function():
    app.dependency_overrides.clear()


def _invoice(pg_session, status="draft"):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"RE-DIS-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=date(2026, 6, 1), due_date=date(2026, 6, 15), currency="EUR",
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"), status=status)
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


# ── Statusmaschine (Guard) ───────────────────────────────────────────────────

def test_draft_darf_verworfen_werden(pg_session):
    inv = _invoice(pg_session, status="draft")
    inv.status = "discarded"
    pg_session.commit()
    assert inv.status == "discarded"


def test_verworfener_entwurf_darf_zurueckgeholt_werden(pg_session):
    """Ein Entwurf ist kein Beleg — hier gibt es nichts zu schützen."""
    inv = _invoice(pg_session, status="discarded")
    inv.status = "draft"
    pg_session.commit()
    assert inv.status == "draft"


@pytest.mark.parametrize("ziel", ["issued", "paid", "cancelled"])
def test_verworfener_entwurf_fuehrt_in_keinen_belegstatus(pg_session, ziel):
    """Aus `discarded` gibt es keinen Weg direkt in einen Beleg — erst zurückholen."""
    inv = _invoice(pg_session, status="discarded")
    inv.status = ziel
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


@pytest.mark.parametrize("start", ["issued", "paid", "cancelled"])
def test_finalisierte_rechnung_kann_nicht_verworfen_werden(pg_session, start):
    """Sonst wäre `discarded` ein Löschknopf für Belege."""
    inv = _invoice(pg_session, status=start)
    inv.status = "discarded"
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


# ── Router ───────────────────────────────────────────────────────────────────

def test_verwerfen_setzt_status_und_leitet_zur_liste(pg_session):
    inv = _invoice(pg_session, status="draft")
    r = _client(pg_session).post(f"/invoices/{inv.id}/verwerfen")
    assert r.status_code == 303
    assert r.headers["location"] == "/invoices"
    pg_session.expire_all()
    assert pg_session.query(Invoice).filter(Invoice.id == inv.id).first().status == "discarded"


@pytest.mark.parametrize("start", ["issued", "paid", "cancelled"])
def test_verwerfen_lehnt_finalisierte_rechnung_ab(pg_session, start):
    inv = _invoice(pg_session, status=start)
    r = _client(pg_session).post(f"/invoices/{inv.id}/verwerfen")
    assert r.status_code == 400
    pg_session.expire_all()
    assert pg_session.query(Invoice).filter(Invoice.id == inv.id).first().status == start


def test_zurueckholen_macht_den_entwurf_wieder_bearbeitbar(pg_session):
    inv = _invoice(pg_session, status="discarded")
    r = _client(pg_session).post(f"/invoices/{inv.id}/zurueckholen")
    assert r.status_code == 303
    pg_session.expire_all()
    assert pg_session.query(Invoice).filter(Invoice.id == inv.id).first().status == "draft"


@pytest.mark.parametrize("pfad", ["bearbeiten", "vorschau"])
def test_verworfener_entwurf_ist_nicht_bearbeitbar(pg_session, pfad):
    inv = _invoice(pg_session, status="discarded")
    r = _client(pg_session).get(f"/invoices/{inv.id}/{pfad}")
    assert r.status_code == 400


def test_verworfener_entwurf_kann_nicht_finalisiert_werden(pg_session):
    inv = _invoice(pg_session, status="discarded")
    r = _client(pg_session).post(f"/invoices/{inv.id}/finalisieren")
    assert r.status_code == 400
    pg_session.expire_all()
    assert pg_session.query(Invoice).filter(Invoice.id == inv.id).first().status == "discarded"


# ── Anzeige ──────────────────────────────────────────────────────────────────

def test_liste_blendet_verworfene_entwuerfe_aus(pg_session):
    offen = _invoice(pg_session, status="draft")
    weg = _invoice(pg_session, status="discarded")
    r = _client(pg_session).get("/invoices/")
    assert r.status_code == 200
    assert offen.invoice_number in r.text
    assert weg.invoice_number not in r.text


def test_liste_zeigt_verworfene_mit_filter(pg_session):
    weg = _invoice(pg_session, status="discarded")
    r = _client(pg_session).get("/invoices/?status=discarded")
    assert r.status_code == 200
    assert weg.invoice_number in r.text


def test_liste_und_detailseite_rendern_verworfene_ohne_absturz(pg_session):
    """Die Badge-Wörterbücher in den Templates sind `{...}[invoice.status]` — ein
    unbekannter Status wirft KeyError und die Seite ist weg, nicht nur das Etikett."""
    inv = _invoice(pg_session, status="discarded")
    c = _client(pg_session)
    assert c.get("/invoices/?status=discarded").status_code == 200
    assert c.get(f"/invoices/{inv.id}").status_code == 200
