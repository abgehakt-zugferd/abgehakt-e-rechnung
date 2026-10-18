"""Befunde aus dem Review des 389-Umfangs (Honorargutschrift, Storno, Einspielen).

Jeder Test haelt einen belegten Befund fest, nicht eine Vermutung. Die Nummern
vor den Tests entsprechen der Reihenfolge des Review-Protokolls.
"""
import uuid
from datetime import date
from decimal import Decimal

from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem


def _kunde(pg_session, **over):
    kw = dict(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Probe Empfaenger GmbH",
        address_line1="Weg 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
    )
    kw.update(over)
    kunde = Customer(**kw)
    pg_session.add(kunde)
    pg_session.commit()
    return kunde


def _beleg(pg_session, kunde, *, invoice_type, status="issued", **over):
    inv = Invoice(
        invoice_number=f"RE-REV-{uuid.uuid4().hex[:6]}",
        customer_id=kunde.id,
        issue_date=date(2026, 10, 1),
        due_date=date(2026, 10, 15),
        currency="EUR",
        tax_category="S",
        invoice_type=invoice_type,
        status=status,
        net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
        payment_terms="Zahlbar in 14 Tagen.",
    )
    inv.items = [InvoiceItem(
        position=1, description="Leistung", unit="Stück",
        quantity=Decimal("1"), unit_price=Decimal("100.00"),
        tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
        tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"),
    )]
    for feld, wert in over.items():
        setattr(inv, feld, wert)
    pg_session.add(inv)
    pg_session.commit()
    return inv


# ── Befund 1: Titel-Filter wirft bei unbekannter Belegart ──────────────────


def test_liste_und_detail_bleiben_200_bei_unbekannter_belegart(client, pg_session):
    """Die Spalte invoice_type ist unbeschränkt; der Jinja-Filter beleg_bezeichnung
    rief belegart() auf, das fuer einen unbekannten gespeicherten Wert wirft.
    Liste und Detailseite endeten dann in HTTP 500, statt den Bestand zu zeigen."""
    kunde = _kunde(pg_session)
    inv = _beleg(pg_session, kunde, invoice_type="altwert")

    liste = client.get("/invoices/")
    detail = client.get(f"/invoices/{inv.id}")

    assert liste.status_code == 200, (
        "Die Rechnungsliste stuerzt über einen unbekannten gespeicherten Typ ab"
    )
    assert detail.status_code == 200, (
        "Die Detailseite stuerzt über einen unbekannten gespeicherten Typ ab"
    )
    # Der Rohwert bleibt sichtbar, damit der Bestand erkennbar und korrigierbar ist.
    assert "altwert" in liste.text
    assert "altwert" in detail.text
