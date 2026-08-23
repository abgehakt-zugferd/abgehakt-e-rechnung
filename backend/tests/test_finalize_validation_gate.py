"""
Finalize-Validation-Gate (#98 P0.2): Eine Rechnung darf nur finalisiert werden,
wenn die regelbasierte § 14-Prüfung fehlerfrei ist. Bisher prüfte
POST /finalisieren nur `status == "draft"` — ein rechtswidriger Draft (z. B. ohne
Positionen, NO_ITEMS) konnte finalisiert, mit ZUGFeRD-XML versehen und 8 Jahre
archiviert werden. Das Gate blockiert das (400, Draft bleibt unverändert).

echtes Postgres — der Guard darf keine Geister-XML/Statusänderung hinterlassen.
"""
import uuid
from datetime import date
from decimal import Decimal

from app.config import get_settings
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from tests.helpers.finalize_pipeline import (
    cleanup,
    client,
    finalize_with_fake_pipeline,
)

settings = get_settings()


def teardown_function():
    app.dependency_overrides.clear()


def _customer(pg_session):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.flush()
    return c


def _draft(pg_session, *, with_items, delivery_date=date(2026, 7, 8), profile="EN16931",
           net=Decimal("200.00"), tax=Decimal("38.00"), gross=Decimal("238.00")):
    c = _customer(pg_session)
    inv = Invoice(invoice_number=f"RE-2026-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=date(2026, 7, 8), delivery_date=delivery_date,
                  due_date=date(2026, 7, 22), currency="EUR", zugferd_profile=profile,
                  tax_category="S", status="draft",
                  payment_terms="Zahlbar in 14 Tagen.",
                  net_total=net if with_items else Decimal("0"),
                  tax_total=tax if with_items else Decimal("0"),
                  gross_total=gross if with_items else Decimal("0"))
    if with_items:
        inv.items = [InvoiceItem(position=1, description="Beratung", unit="Std",
                                 quantity=Decimal("1"), unit_price=net,
                                 tax_rate=Decimal("19"), net_amount=net,
                                 tax_amount=tax, gross_amount=gross)]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_finalize_blocked_when_validation_fails(pg_session):
    """Draft ohne Positionen (NO_ITEMS) → Finalize muss mit 400 abgewiesen werden
    und die Rechnung unverändert als Draft ohne XML/PDF zurücklassen."""
    inv = _draft(pg_session, with_items=False)
    r = client(pg_session).post(f"/invoices/{inv.id}/finalisieren")
    assert r.status_code == 400

    pg_session.expire_all()
    row = pg_session.get(Invoice, inv.id)
    assert row.status == "draft"          # nicht finalisiert
    assert row.zugferd_xml is None        # keine XML erzeugt
    assert row.pdf_filename is None       # kein PDF erzeugt


def test_finalize_blocked_for_non_compliant_profile(pg_session):
    """#98 E4: ein Draft mit nicht rechtskonformem Profil (MINIMUM/BASIC-WL) darf
    NICHT finalisiert werden. Das Gate blockiert fail-closed mit 400 (nicht 500) —
    es wird keine XML/kein PDF erzeugt, die Rechnung bleibt Draft."""
    inv = _draft(pg_session, with_items=True, profile="MINIMUM")
    r = client(pg_session).post(f"/invoices/{inv.id}/finalisieren")
    assert r.status_code == 400

    pg_session.expire_all()
    row = pg_session.get(Invoice, inv.id)
    assert row.status == "draft"
    assert row.zugferd_xml is None
    assert row.pdf_filename is None


def test_finalize_passes_gate_for_valid_invoice(pg_session):
    """Positiv-Kontrolle: eine § 14-konforme Rechnung kommt am Gate VORBEI und wird
    finalisiert (sonst wäre das Gate ununterscheidbar von „blockiert immer")."""
    inv = _draft(pg_session, with_items=True)
    number = inv.invoice_number
    try:
        r = finalize_with_fake_pipeline(pg_session, inv.id)
        assert r.status_code == 303, r.text
        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.status == "issued"
        assert row.zugferd_xml is not None
        assert row.pdf_filename == f"{number}.pdf"
    finally:
        cleanup(number)


def test_finalize_allowed_despite_warnings(pg_session):
    """Entscheidung (#98 P2, 2026-07-22): WARNUNGEN blockieren die Finalisierung NICHT
    — nur harte § 14-Fehler tun das. Hier erzeugt eine Rechnung über 10.000 € an einen
    Kunden OHNE USt-IdNr. die Warnung HIGH_VALUE_NO_BUYER_VAT_ID (Leistungsdatum ist seit
    E7 gesetzt, sonst wäre es ein Fehler) — sie muss trotzdem finalisierbar bleiben.
    Ändert sich diese Politik, kippt dieser Test bewusst."""
    inv = _draft(pg_session, with_items=True,
                 net=Decimal("10000.00"), tax=Decimal("1900.00"), gross=Decimal("11900.00"))
    number = inv.invoice_number
    try:
        r = finalize_with_fake_pipeline(pg_session, inv.id)
        assert r.status_code == 303, r.text
        pg_session.expire_all()
        assert pg_session.get(Invoice, inv.id).status == "issued"
    finally:
        cleanup(number)


def test_finalize_blocked_without_delivery_date_when_not_simplified(pg_session):
    """#98 E7 (harter Gate): eine Nicht-Kleinbetragsrechnung (≥ 250 €) OHNE Leistungsdatum
    darf NICHT finalisiert werden (§ 14 Abs. 4 Nr. 6 UStG) — 400, bleibt Draft, keine
    XML/PDF. Kleinbetrag bleibt ausgenommen (siehe test_finalize_allowed_* / Validator)."""
    inv = _draft(pg_session, with_items=True, delivery_date=None,
                 net=Decimal("250.00"), tax=Decimal("47.50"), gross=Decimal("297.50"))
    r = client(pg_session).post(f"/invoices/{inv.id}/finalisieren")
    assert r.status_code == 400

    pg_session.expire_all()
    row = pg_session.get(Invoice, inv.id)
    assert row.status == "draft"
    assert row.zugferd_xml is None
    assert row.pdf_filename is None
