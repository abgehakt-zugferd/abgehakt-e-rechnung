"""Ersatzrechnung: Regeln am Anlageweg und beim Finalisieren (docs/specs/ersatzrechnung.md).

Naht ist POST /invoices/neu mit `ersetzt_invoice_id`. Eine Ablehnung muss vor der
Nummernvergabe fallen: kein Datensatz, kein erhoehter Zaehler.
Die Pipeline bis zum ZUGFeRD-PDF prueft test_ersatzrechnung_e2e.py.
"""
import json
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem


@pytest.fixture
def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def _kunde(pg_session, name="Probe Kunde GmbH"):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name=name,
                 address_line1="Weg 1", zip_code="80331", city="Muenchen", country="DE")
    pg_session.add(c)
    pg_session.flush()
    return c


def _beleg(pg_session, kunde, *, status="issued", invoice_type=None, original=None):
    inv = Invoice(invoice_number=f"RE-ERS-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
                  issue_date=date(2026, 7, 8), due_date=date(2026, 7, 22),
                  delivery_date=date(2026, 7, 8), currency="EUR", tax_category="S",
                  status=status, invoice_type=invoice_type,
                  original_invoice_id=original.id if original else None,
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"))
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Stunde",
                             quantity=Decimal("1"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
                             tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"))]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _gutschrift(pg_session, original, *, status="issued"):
    return _beleg(pg_session, original.customer, status=status,
                  invoice_type="credit_note", original=original)


def _payload(kunde, ersetzt):
    return {
        "customer_id": str(kunde.id),
        "issue_date": "2026-07-10",
        "due_date": "2026-07-24",
        "tax_category": "S",
        "ersetzt_invoice_id": str(ersetzt) if ersetzt is not None else "",
        "items_json": json.dumps([{"description": "Beratung", "unit": "Stunde",
                                   "quantity": "1", "unit_price": "100",
                                   "tax_rate": "19"}]),
    }


def _zaehler(pg_session):
    return pg_session.query(Company).filter(Company.id == 1).one().invoice_counter


def _abgelehnt_ohne_wirkung(pg_session, client, payload, code):
    zaehler_vorher = _zaehler(pg_session)
    anzahl_vorher = pg_session.query(Invoice).count()

    r = client.post("/invoices/neu", data=payload)

    assert r.status_code == 400, r.text
    assert code in r.text
    pg_session.expire_all()
    assert pg_session.query(Invoice).count() == anzahl_vorher
    assert _zaehler(pg_session) == zaehler_vorher, (
        "Abgelehnte Ersatzrechnung hat den Nummernzaehler erhoeht (Nummernluecke ohne Beleg)."
    )


def test_ersatz_ohne_gutschrift_wird_vor_der_nummernvergabe_abgelehnt(pg_session, client):
    kunde = _kunde(pg_session)
    original = _beleg(pg_session, kunde)

    _abgelehnt_ohne_wirkung(pg_session, client, _payload(kunde, original.id),
                            "ERSATZ_OHNE_GUTSCHRIFT")


@pytest.mark.parametrize("kennung", ["kaputt", str(uuid.uuid4())])
def test_ersatz_zu_unbekannter_rechnung_wird_abgelehnt(pg_session, client, kennung):
    kunde = _kunde(pg_session)

    _abgelehnt_ohne_wirkung(pg_session, client, _payload(kunde, kennung),
                            "ERSATZ_ORIGINAL_UNBEKANNT")


@pytest.mark.parametrize("lage", ["gutschrift", "honorargutschrift", "entwurf", "verworfen"])
def test_nur_eine_gestellte_rechnung_ist_ersetzbar(pg_session, client, lage):
    kunde = _kunde(pg_session)
    if lage == "gutschrift":
        quelle = _gutschrift(pg_session, _beleg(pg_session, kunde))
    elif lage == "honorargutschrift":
        quelle = _beleg(pg_session, kunde, invoice_type="self_billing",
                        original=_beleg(pg_session, kunde))
    else:
        quelle = _beleg(pg_session, kunde,
                        status="draft" if lage == "entwurf" else "discarded")
    # Eine Gutschrift auf die Quelle, damit nicht die Gutschrift-Regel antwortet.
    _gutschrift(pg_session, quelle)

    _abgelehnt_ohne_wirkung(pg_session, client, _payload(kunde, quelle.id),
                            "ERSATZ_ORIGINAL_KEINE_RECHNUNG")
