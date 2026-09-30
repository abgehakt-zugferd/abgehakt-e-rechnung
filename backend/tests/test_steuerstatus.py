"""Umsatzsteuerstatus am Kunden fuer das Gutschriftverfahren (389).

Der Status entscheidet, ob auf einer Honorargutschrift 7 % stehen oder keine.
Steht USt auf einer Gutschrift an einen Kleinunternehmer, schuldet er sie nach
§ 14c UStG. Die Voreinstellung ist deshalb bewusst ungeklaert, nicht
regelbesteuert.
"""

import uuid
from datetime import date
from decimal import Decimal

from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from tests.helpers.finalize_pipeline import client, patched_success_pipeline


def teardown_function():
    app.dependency_overrides.clear()


def _kunde(pg_session, **over):
    kw = dict(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Jürgen Weiß",
        address_line1="Weg 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
        gutschriftempfaenger=True,
        ust_status="ungeklaert",
        tax_number="12/345/67890",
    )
    kw.update(over)
    kunde = Customer(**kw)
    pg_session.add(kunde)
    pg_session.flush()
    return kunde


def _original(pg_session, kunde):
    """Bezug, den self_billing heute noch verlangt (braucht_original=True)."""
    inv = Invoice(
        invoice_number=f"RE-ORG-{uuid.uuid4().hex[:6]}",
        customer_id=kunde.id,
        issue_date=date(2026, 7, 1),
        delivery_date=date(2026, 7, 1),
        due_date=date(2026, 7, 15),
        currency="EUR",
        zugferd_profile="EN16931",
        tax_category="S",
        status="issued",
        payment_terms="14 Tage netto",
        net_total=Decimal("100.00"),
        tax_total=Decimal("7.00"),
        gross_total=Decimal("107.00"),
    )
    inv.items = [
        InvoiceItem(
            position=1,
            description="Bezug",
            unit="Stück",
            quantity=Decimal("1"),
            unit_price=Decimal("100.00"),
            tax_rate=Decimal("7"),
            net_amount=Decimal("100.00"),
            tax_amount=Decimal("7.00"),
            gross_amount=Decimal("107.00"),
        )
    ]
    pg_session.add(inv)
    pg_session.flush()
    return inv


def _honorargutschrift(pg_session, kunde, *, tax_category="S", tax_rate=Decimal("7.00"),
                       original=None):
    netto = Decimal("100.00")
    steuer = (netto * tax_rate / Decimal("100")).quantize(Decimal("0.01"))
    inv = Invoice(
        invoice_number=f"HG-{uuid.uuid4().hex[:6]}",
        customer_id=kunde.id,
        issue_date=date(2026, 7, 8),
        delivery_date=date(2026, 7, 8),
        due_date=date(2026, 7, 22),
        currency="EUR",
        zugferd_profile="EN16931",
        tax_category=tax_category,
        invoice_type="self_billing",
        status="draft",
        payment_terms="14 Tage netto",
        original_invoice_id=original.id if original else None,
        net_total=netto,
        tax_total=steuer,
        gross_total=netto + steuer,
    )
    inv.items = [
        InvoiceItem(
            position=1,
            description="Beteiligung am Deckungsbeitrag",
            unit="Stück",
            quantity=Decimal("1"),
            unit_price=netto,
            tax_rate=tax_rate,
            net_amount=netto,
            tax_amount=steuer,
            gross_amount=netto + steuer,
        )
    ]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_finalisierung_einer_389_mit_ungeklaertem_status_wird_abgewiesen(pg_session):
    """Durchstich: HTTP-Finalisierung bleibt draft, wenn der Status ungeklaert ist."""
    kunde = _kunde(pg_session, ust_status="ungeklaert")
    original = _original(pg_session, kunde)
    inv = _honorargutschrift(pg_session, kunde, original=original)

    with patched_success_pipeline():
        antwort = client(pg_session).post(f"/invoices/{inv.id}/finalisieren")

    assert antwort.status_code == 400
    assert "ungeklaert" in antwort.text.lower() or "ust_status" in antwort.text.lower() \
        or "steuerstatus" in antwort.text.lower() or "umsatzsteuer" in antwort.text.lower()
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).status == "draft"
