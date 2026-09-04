"""Was am Entwurf aus einem Beleg bearbeitbar ist, und was nicht (abgehakt#22, Punkt 5).

Bearbeitbar ist, was abgehakt gehoert: Steuersatz, Steuerkategorie und die
Freitexte. Sie entstehen hier aus dem Status des Kunden, und eine falsche
Ableitung muss man korrigieren koennen.

Gesperrt ist, was aus dem signierten Beleg stammt: die Netto-Betraege, der
Beteiligte und der Leistungszeitraum. Wer sie aendert, hat eine Rechnung, die
auf einen Beleg zeigt, den sie nicht mehr wiedergibt, und der Beleg ist die
Autoritaet, acht Jahre lang. Ist ein Netto-Betrag falsch, ist der BELEG falsch:
dann wird er abgelehnt und der Absender erzeugt einen neuen.

Die Sperre steht im Server, nicht im Formular. `readonly` im HTML ist eine
Bitte an den Browser, keine Zusage.
"""

import json
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem


def _kunde(pg_session, name="Autorin A"):
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name=name,
        address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE",
    )
    pg_session.add(kunde)
    pg_session.commit()
    return kunde


def _entwurf(pg_session, kunde, aus_beleg=True):
    invoice = Invoice(
        invoice_number=f"RE-{uuid.uuid4().hex[:6]}",
        customer_id=kunde.id,
        issue_date=date(2026, 9, 3),
        due_date=date(2026, 9, 17),
        service_period_start=date(2026, 4, 1),
        service_period_end=date(2026, 6, 30),
        tax_category="S",
        invoice_type="self_billing" if aus_beleg else None,
        status="draft",
        net_total=Decimal("174.33"),
        tax_total=Decimal("12.20"),
        gross_total=Decimal("186.53"),
        uebergabe_beleg_id="c0c0c0c0-0000-4000-8000-000000000001" if aus_beleg else None,
        uebergabe_beleg_sha256="1" * 64 if aus_beleg else None,
    )
    pg_session.add(invoice)
    pg_session.flush()
    pg_session.add(InvoiceItem(
        invoice_id=invoice.id, position=1,
        description="Beteiligung am Deckungsbeitrag 2026-Q2",
        unit="Pauschal", quantity=Decimal("1"), unit_price=Decimal("174.33"),
        tax_rate=Decimal("7.00"), net_amount=Decimal("174.33"),
        tax_amount=Decimal("12.20"), gross_amount=Decimal("186.53"),
    ))
    pg_session.commit()
    return invoice


def _formular(invoice, kunde, positionen=None, **aenderungen):
    daten = {
        "customer_id": str(kunde.id),
        "issue_date": invoice.issue_date.isoformat(),
        "due_date": invoice.due_date.isoformat(),
        "service_period_start": "2026-04-01",
        "service_period_end": "2026-06-30",
        "tax_category": invoice.tax_category,
        "payment_terms": "",
        "buyer_reference": "",
        "notes": "",
        "items_json": json.dumps(positionen if positionen is not None else [{
            "description": "Beteiligung am Deckungsbeitrag 2026-Q2",
            "unit": "Pauschal", "quantity": "1", "unit_price": "174.33",
            "tax_rate": "7.00",
        }]),
    }
    daten.update(aenderungen)
    return daten


def test_das_formular_nennt_die_herkunft(client, pg_session):
    kunde = _kunde(pg_session)
    entwurf = _entwurf(pg_session, kunde)

    text = client.get(f"/invoices/{entwurf.id}/bearbeiten").text

    assert "aus dem Beleg" in text


def test_der_nettobetrag_laesst_sich_nicht_umschreiben(client, pg_session):
    kunde = _kunde(pg_session)
    entwurf = _entwurf(pg_session, kunde)

    client.post(f"/invoices/{entwurf.id}/bearbeiten", data=_formular(
        entwurf, kunde, positionen=[{
            "description": "Beteiligung am Deckungsbeitrag 2026-Q2",
            "unit": "Pauschal", "quantity": "1", "unit_price": "999.00",
            "tax_rate": "7.00",
        }],
    ))

    pg_session.expire_all()
    frisch = pg_session.query(Invoice).filter(Invoice.id == entwurf.id).one()
    assert frisch.items[0].unit_price == Decimal("174.33")
    assert frisch.net_total == Decimal("174.33")


def test_die_menge_laesst_sich_auch_nicht_umschreiben(client, pg_session):
    """Menge mal Preis ist der Nettobetrag - beide Wege fuehren zu ihm."""
    kunde = _kunde(pg_session)
    entwurf = _entwurf(pg_session, kunde)

    client.post(f"/invoices/{entwurf.id}/bearbeiten", data=_formular(
        entwurf, kunde, positionen=[{
            "description": "Beteiligung am Deckungsbeitrag 2026-Q2",
            "unit": "Pauschal", "quantity": "5", "unit_price": "174.33",
            "tax_rate": "7.00",
        }],
    ))

    pg_session.expire_all()
    frisch = pg_session.query(Invoice).filter(Invoice.id == entwurf.id).one()
    assert frisch.items[0].quantity == Decimal("1")
    assert frisch.net_total == Decimal("174.33")


def test_der_beteiligte_laesst_sich_nicht_umhaengen(client, pg_session):
    kunde = _kunde(pg_session)
    fremder = _kunde(pg_session, name="Jemand anderes")
    entwurf = _entwurf(pg_session, kunde)

    client.post(f"/invoices/{entwurf.id}/bearbeiten",
                data=_formular(entwurf, kunde, customer_id=str(fremder.id)))

    pg_session.expire_all()
    frisch = pg_session.query(Invoice).filter(Invoice.id == entwurf.id).one()
    assert frisch.customer_id == kunde.id


def test_der_leistungszeitraum_bleibt_der_des_belegs(client, pg_session):
    kunde = _kunde(pg_session)
    entwurf = _entwurf(pg_session, kunde)

    client.post(f"/invoices/{entwurf.id}/bearbeiten", data=_formular(
        entwurf, kunde, service_period_start="2026-01-01", service_period_end="2026-03-31",
    ))

    pg_session.expire_all()
    frisch = pg_session.query(Invoice).filter(Invoice.id == entwurf.id).one()
    assert frisch.service_period_start == date(2026, 4, 1)
    assert frisch.service_period_end == date(2026, 6, 30)


def test_die_steuer_laesst_sich_korrigieren(client, pg_session):
    kunde = _kunde(pg_session)
    entwurf = _entwurf(pg_session, kunde)

    client.post(f"/invoices/{entwurf.id}/bearbeiten", data=_formular(
        entwurf, kunde, tax_category="E", positionen=[{
            "description": "Beteiligung am Deckungsbeitrag 2026-Q2",
            "unit": "Pauschal", "quantity": "1", "unit_price": "174.33",
            "tax_rate": "0.00",
        }],
    ))

    pg_session.expire_all()
    frisch = pg_session.query(Invoice).filter(Invoice.id == entwurf.id).one()
    assert frisch.tax_category == "E"
    assert frisch.items[0].tax_rate == Decimal("0.00")
    assert frisch.tax_total == Decimal("0.00")
    assert frisch.net_total == Decimal("174.33")


def test_die_bezeichnung_laesst_sich_aendern(client, pg_session):
    kunde = _kunde(pg_session)
    entwurf = _entwurf(pg_session, kunde)

    client.post(f"/invoices/{entwurf.id}/bearbeiten", data=_formular(
        entwurf, kunde, notes="Nach Rücksprache geprüft", positionen=[{
            "description": "Beteiligung am Deckungsbeitrag, 2. Quartal 2026",
            "unit": "Pauschal", "quantity": "1", "unit_price": "174.33",
            "tax_rate": "7.00",
        }],
    ))

    pg_session.expire_all()
    frisch = pg_session.query(Invoice).filter(Invoice.id == entwurf.id).one()
    assert frisch.items[0].description == "Beteiligung am Deckungsbeitrag, 2. Quartal 2026"
    assert frisch.notes == "Nach Rücksprache geprüft"


def test_eine_andere_zahl_von_positionen_wird_abgewiesen(client, pg_session):
    kunde = _kunde(pg_session)
    entwurf = _entwurf(pg_session, kunde)

    antwort = client.post(f"/invoices/{entwurf.id}/bearbeiten", data=_formular(
        entwurf, kunde, positionen=[],
    ))

    assert antwort.status_code == 400
    pg_session.expire_all()
    frisch = pg_session.query(Invoice).filter(Invoice.id == entwurf.id).one()
    assert len(frisch.items) == 1


def test_eine_rechnung_ohne_beleg_bleibt_frei_bearbeitbar(client, pg_session):
    """Die Gegenprobe: ohne Belegbezug sperrt nichts."""
    kunde = _kunde(pg_session)
    fremder = _kunde(pg_session, name="Jemand anderes")
    entwurf = _entwurf(pg_session, kunde, aus_beleg=False)

    client.post(f"/invoices/{entwurf.id}/bearbeiten", data=_formular(
        entwurf, kunde, customer_id=str(fremder.id), service_period_start="2026-01-01",
        positionen=[{
            "description": "Etwas anderes", "unit": "Stück", "quantity": "2",
            "unit_price": "100.00", "tax_rate": "19.00",
        }],
    ))

    pg_session.expire_all()
    frisch = pg_session.query(Invoice).filter(Invoice.id == entwurf.id).one()
    assert frisch.customer_id == fremder.id
    assert frisch.service_period_start == date(2026, 1, 1)
    assert frisch.net_total == Decimal("200.00")
