"""Kennzahlen nach Storno per Gutschrift (Issue #141, docs/specs/kennzahlen-storno.md).

Grundsatz: eine Stornierung wirkt in jeder Kennzahl genau einmal. Wirksam ist eine
Gutschrift (381) mit Status issued oder paid; sie spiegelt ihr Original vollstaendig.
Die Belege entstehen hier so, wie die Anwendung sie erzeugt: mit Bezug und vollem Betrag.
"""
import uuid
from datetime import date
from decimal import Decimal

from app.models.customer import Customer
from app.models.invoice import Invoice
from app.services.dashboard_kennzahlen import offene_forderungen, ueberfaellige_forderungen

HEUTE = date(2026, 10, 8)


def _beleg(pg_session, *, status="issued", art=None, original=None,
           netto="100.00", steuer="19.00", ausgestellt=date(2026, 9, 1),
           faellig=date(2026, 9, 15)):
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Probe Kunde",
                     address_line1="Weg 1", zip_code="80331", city="Muenchen", country="DE")
    pg_session.add(kunde)
    pg_session.flush()
    netto, steuer = Decimal(netto), Decimal(steuer)
    inv = Invoice(invoice_number=f"RE-KS-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
                  issue_date=ausgestellt, due_date=faellig, currency="EUR",
                  net_total=netto, tax_total=steuer, gross_total=netto + steuer,
                  status=status, invoice_type=art,
                  original_invoice_id=original.id if original else None,
                  bezahlt_am=ausgestellt if status == "paid" else None)
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _gutschrift(pg_session, original, *, status="issued", ausgestellt=None):
    return _beleg(pg_session, status=status, art="credit_note", original=original,
                  netto=str(original.net_total), steuer=str(original.tax_total),
                  ausgestellt=ausgestellt or original.issue_date,
                  faellig=ausgestellt or original.issue_date)


def test_wirksam_stornierte_rechnung_ist_nicht_mehr_offen(pg_session):
    original = _beleg(pg_session)
    _gutschrift(pg_session, original)

    assert offene_forderungen(pg_session).betrag == Decimal("0")
    assert offene_forderungen(pg_session).anzahl == 0
    ueberfaellig = ueberfaellige_forderungen(pg_session, HEUTE)
    assert ueberfaellig.betrag == Decimal("0")
    assert ueberfaellig.aeltester_tage is None
