"""#157: Zahlungsdatum entscheidet bei Anzahlungen, auch ueber Jahresgrenzen."""
from datetime import date
from decimal import Decimal
from app.models.invoice import Invoice
from app.services import dashboard_kennzahlen as k
from tests.test_dashboard_honorargutschrift import _honorargutschrift


def test_anzahlung_und_honorar_in_derselben_datenbank(pg_session):
    hg = _honorargutschrift(pg_session, "issued", "535", Decimal("500"), Decimal("35"))
    inv = Invoice(invoice_number="AZ-PROBE", customer_id=hg.customer_id,
        invoice_type="prepayment", status="issued", issue_date=date(2025, 12, 1),
        due_date=date(2026, 1, 15), net_total=1000, tax_total=190, gross_total=1190)
    pg_session.add(inv)
    pg_session.commit()
    von, bis = date(2026, 1, 1), date(2026, 1, 31)
    assert k.offene_forderungen(pg_session).betrag == 1190
    assert k.schuldige_umsatzsteuer(pg_session, date(2025, 1, 1)) == 0
    assert k.umsatz_im_zeitraum(pg_session, von, bis) == 0
    assert k.bezahlt_im_zeitraum(pg_session, von) == 0
    inv.status, inv.bezahlt_am = "paid", date(2026, 1, 15)
    pg_session.commit()
    assert k.offene_forderungen(pg_session).betrag == 0
    assert k.umsatz_im_zeitraum(pg_session, von, bis) == 1000
    assert k.bezahlt_im_zeitraum(pg_session, von, date(2026, 2, 1)) == 1190
    assert k.schuldige_umsatzsteuer(pg_session, von, bis) == 190
    assert k.schuldige_umsatzsteuer(pg_session, date(2025, 1, 1), date(2025, 12, 31)) == 0
    assert k.umsatz_im_zeitraum(pg_session, date(2026, 2, 1)) == 0
    assert k.bezahlt_im_zeitraum(pg_session, date(2026, 2, 1)) == 0
    assert k.schuldige_umsatzsteuer(pg_session, date(2026, 2, 1)) == 0
    assert k.offene_auszahlungen(pg_session).betrag == 535


def test_storno_unbezahlter_anzahlung_erzeugt_keine_negative_ust(pg_session):
    hg = _honorargutschrift(pg_session, "issued", "535", Decimal("500"), Decimal("35"))
    inv = Invoice(invoice_number="AZ-OFFEN", customer_id=hg.customer_id,
        invoice_type="prepayment", status="issued", issue_date=date(2026, 1, 1),
        due_date=date(2026, 1, 15), net_total=1000, tax_total=190, gross_total=1190)
    pg_session.add(inv)
    pg_session.flush()
    pg_session.add(Invoice(invoice_number="AZ-STORNO", customer_id=hg.customer_id,
        invoice_type="credit_note", original_invoice_id=inv.id, status="issued",
        issue_date=date(2026, 1, 2), due_date=date(2026, 1, 15),
        net_total=1000, tax_total=190, gross_total=1190))
    pg_session.commit()
    assert k.schuldige_umsatzsteuer(pg_session, date(2026, 1, 1)) == 0
    assert k.offene_forderungen(pg_session).betrag == 0
