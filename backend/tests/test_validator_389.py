"""Finalisieren-Ausgang einer Honorargutschrift (Spec #156, Kriterien 1 und 3).

Geprüft wird der AUSGANG des Finalisierens (HTTP und Status des Belegs), nicht
die Anwesenheit eines einzelnen Fehlercodes: ein anderes Fehlerbild, das
denselben Beleg zu Unrecht sperrt oder durchlässt, bleibt hier sichtbar.
"""
import uuid
from datetime import date
from decimal import Decimal

from app.config import get_settings
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services.validator import validate_invoice
from tests.helpers.finalize_pipeline import cleanup, finalize_with_fake_pipeline


def _kunde(pg_session, **over):
    kw = dict(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Probe Leistung GmbH",
        address_line1="Weg 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
        gutschriftempfaenger=True,
        ust_status="regelbesteuert",
        tax_number="12/345/67890",
    )
    kw.update(over)
    kunde = Customer(**kw)
    pg_session.add(kunde)
    pg_session.flush()
    return kunde


def _entwurf(pg_session, kunde, *, invoice_type="self_billing",
             original_invoice_id=None):
    inv = Invoice(
        invoice_number=f"RE-389-{uuid.uuid4().hex[:6]}",
        customer_id=kunde.id,
        issue_date=date(2026, 7, 8),
        delivery_date=date(2026, 7, 8),
        due_date=date(2026, 7, 22),
        currency="EUR",
        zugferd_profile="EN16931",
        tax_category="S",
        invoice_type=invoice_type,
        status="draft",
        payment_terms="14 Tage netto",
        original_invoice_id=original_invoice_id,
        net_total=Decimal("100.00"),
        tax_total=Decimal("7.00"),
        gross_total=Decimal("107.00"),
    )
    inv.items = [InvoiceItem(
        position=1, description="Beteiligung am Deckungsbeitrag",
        unit="Pauschal", quantity=Decimal("1"), unit_price=Decimal("100.00"),
        tax_rate=Decimal("7.00"), net_amount=Decimal("100.00"),
        tax_amount=Decimal("7.00"), gross_amount=Decimal("107.00"),
    )]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _archiv_hat_nichts(number):
    """Kein Zwischenprodukt und kein Beleg im Archiv, das die Nummer trägt."""
    wurzel = get_settings().storage_path
    return [str(p) for p in wurzel.rglob("*") if p.is_file() and number in p.name]


# ── Kriterium 1: Originalbezug, geprüft am Finalisieren-Ausgang ─────────────

def test_389_ohne_original_finalisiert(pg_session):
    """Der Integrationsweg legt den Entwurf ohne Bezug an; das muss reichen."""
    kunde = _kunde(pg_session)
    inv = _entwurf(pg_session, kunde)
    try:
        antwort = finalize_with_fake_pipeline(pg_session, inv.id)
        assert antwort.status_code == 303
        pg_session.expire_all()
        assert pg_session.get(Invoice, inv.id).status == "issued"
    finally:
        cleanup(inv.invoice_number)


def test_389_mit_original_wird_abgewiesen(pg_session):
    """Diese Anwendung kennt kein Original, auf das ein 389 zeigen könnte;
    ein gesetzter Bezug ist erfunden und sperrt das Finalisieren."""
    kunde = _kunde(pg_session)
    # Ein existierender Beleg erfüllt den Fremdschlüssel; erst der Validator
    # soll den fachlich unzulässigen Bezug der 389 abweisen.
    original = _entwurf(pg_session, kunde, invoice_type=None)
    original.status = "issued"
    pg_session.commit()
    inv = _entwurf(pg_session, kunde, original_invoice_id=original.id)
    try:
        antwort = finalize_with_fake_pipeline(pg_session, inv.id)
        assert antwort.status_code == 400
        pg_session.expire_all()
        assert pg_session.get(Invoice, inv.id).status == "draft"
    finally:
        cleanup(inv.invoice_number)


def test_381_ohne_original_wird_weiterhin_abgewiesen(pg_session):
    kunde = _kunde(pg_session)
    inv = _entwurf(pg_session, kunde, invoice_type="credit_note")
    antwort = finalize_with_fake_pipeline(pg_session, inv.id)
    assert antwort.status_code == 400
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).status == "draft"


def test_384_ohne_original_wird_weiterhin_abgewiesen(pg_session):
    kunde = _kunde(pg_session)
    inv = _entwurf(pg_session, kunde, invoice_type="correction")
    antwort = finalize_with_fake_pipeline(pg_session, inv.id)
    assert antwort.status_code == 400
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).status == "draft"


# ── Kriterium 3, Fall „nichts": gezielter Befund, Entwurf, leeres Archiv ────

def test_389_ohne_steuerkennung_des_verkaeufers_nennt_den_eigenen_befund(pg_session):
    """§ 14 Abs. 4 S. 1 Nr. 2 UStG: die Kennung gehört dem Verkäufer, und das
    ist bei 389 der Kunde. Der Befund nennt diese Rolle namentlich."""
    kunde = _kunde(pg_session, tax_number=None, vat_id=None)
    inv = _entwurf(pg_session, kunde)
    pg_session.refresh(inv)
    inv.customer  # noqa: B018 – Beziehung vor dem Validator laden

    errors, _ = validate_invoice(
        inv, pg_session.query(Company).filter(Company.id == 1).one())
    codes = {e.code for e in errors}
    assert "SELF_BILLING_SELLER_TAX_ID_MISSING" in codes
    assert any(e.field == "customer.tax" for e in errors
               if e.code == "SELF_BILLING_SELLER_TAX_ID_MISSING")


def test_389_ohne_steuerkennung_bleibt_entwurf_und_archiv_bleibt_leer(pg_session):
    kunde = _kunde(pg_session, tax_number=None, vat_id=None)
    inv = _entwurf(pg_session, kunde)
    try:
        antwort = finalize_with_fake_pipeline(pg_session, inv.id)
        assert antwort.status_code == 400
        pg_session.expire_all()
        assert pg_session.get(Invoice, inv.id).status == "draft"
        assert _archiv_hat_nichts(inv.invoice_number) == []
    finally:
        cleanup(inv.invoice_number)
