"""Honorargutschrift (389) auf der Uebersicht: Vorsteuer mindert die geschaetzten Abgaben.

Entscheidung des Betreibers vom 2026-09-30 (docs/specs/gutschriftverfahren-389.md):
die Vorsteuer aus Honorargutschriften wird in „Geschaetzte Steuerabgaben“ abgezogen,
nicht in „Schuldige Umsatzsteuer“. Geprueft werden beide Richtungen am selben Beleg.
"""
import uuid
from datetime import date
from decimal import Decimal

import app.main as main
from app.models.customer import Customer
from app.models.invoice import Invoice
from tests.test_dashboard import _inv, _request


def _honorargutschrift(pg_session, status, gross, net, tax):
    """Der Wächter verbietet, einen gestellten Beleg umzutypisieren; die Art gilt ab Anlage."""
    autor = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Autor",
                     address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(autor)
    pg_session.flush()
    inv = Invoice(invoice_number=f"HG-{uuid.uuid4().hex[:6]}", customer_id=autor.id,
                  issue_date=date.today(), due_date=date.today(), currency="EUR",
                  net_total=net, tax_total=tax, gross_total=Decimal(gross),
                  status=status, invoice_type="self_billing")
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_vorsteuer_mindert_steuerabgaben_nicht_schuldige_ust(pg_session):
    _inv(pg_session, "issued", "1190.00", net=Decimal("1000.00"), tax=Decimal("190.00"))
    _honorargutschrift(
        pg_session, "issued", "535.00", net=Decimal("500.00"), tax=Decimal("35.00"),
    )

    ctx = main.dashboard(_request(), pg_session).context

    assert Decimal(ctx["vat_liability_ytd"]) == Decimal("190.00")
    assert Decimal(ctx["vorsteuer_honorargutschriften_ytd"]) == Decimal("35.00")
    assert Decimal(ctx["estimated_tax_ytd"]) == (
        Decimal("155.00") + Decimal(ctx["steuer_ruecklage_ytd"])
    )


def test_entwurf_einer_honorargutschrift_mindert_nichts(pg_session):
    _inv(pg_session, "issued", "1190.00", net=Decimal("1000.00"), tax=Decimal("190.00"))
    _honorargutschrift(
        pg_session, "draft", "535.00", net=Decimal("500.00"), tax=Decimal("35.00"),
    )

    ctx = main.dashboard(_request(), pg_session).context

    assert Decimal(ctx["vorsteuer_honorargutschriften_ytd"]) == Decimal("0")
    assert Decimal(ctx["estimated_tax_ytd"]) == (
        Decimal("190.00") + Decimal(ctx["steuer_ruecklage_ytd"])
    )


def test_uebersicht_zeigt_den_abzug(client, pg_session):
    _honorargutschrift(
        pg_session, "issued", "535.00", net=Decimal("500.00"), tax=Decimal("35.00"),
    )
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "− Vorsteuer Honorargutschriften 35" in r.text
