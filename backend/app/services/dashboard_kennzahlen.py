"""Kennzahlen fuer die Uebersicht — Umsatzsteuer und Steuer-Ruecklagen.

Abgehakt kennt nur Ausgangsrechnungen, keine Eingangsrechnungen und keine
Betriebsausgaben. „Schuldige Umsatzsteuer“ ist deshalb die auf gestellten
Belegen ausgewiesene USt (abzueglich Gutschriften) — kein Vorsteuerabzug.
„Geschaetzte Steuerabgaben“ addiert dazu die in den Einstellungen hinterlegte
GmbH-Ruecklage (KSt + GewSt) auf den Nettoumsatz.
"""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.invoice import Invoice
from app.services.steuer_ruecklage import steuerruecklage_anteil

_AUSGESTELLT = ("issued", "paid")


def _summe_feld(
    db: Session,
    feld,
    seit: date,
    *,
    rechnung: bool,
) -> Decimal:
    """Summiert ein Betragsfeld fuer Rechnungen oder Gutschriften seit `seit`."""
    if rechnung:
        typ_filter = Invoice.invoice_type.is_(None)
    else:
        typ_filter = Invoice.invoice_type == "credit_note"
    return (
        db.query(func.coalesce(func.sum(feld), 0))
        .filter(
            Invoice.status.in_(_AUSGESTELLT),
            typ_filter,
            Invoice.issue_date >= seit,
        )
        .scalar()
    ) or Decimal("0")


def schuldige_umsatzsteuer_ytd(db: Session, seit: date) -> Decimal:
    """Ausgewiesene USt auf gestellten Belegen im Zeitraum, netto nach Gutschriften."""
    ust = _summe_feld(db, Invoice.tax_total, seit, rechnung=True)
    gutschrift_ust = _summe_feld(db, Invoice.tax_total, seit, rechnung=False)
    return (ust - gutschrift_ust).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def nettoumsatz_ytd(db: Session, seit: date) -> Decimal:
    """Nettoumsatz gestellter Belege im Zeitraum, abzueglich Gutschriften."""
    netto = _summe_feld(db, Invoice.net_total, seit, rechnung=True)
    gutschrift_netto = _summe_feld(db, Invoice.net_total, seit, rechnung=False)
    return (netto - gutschrift_netto).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def geschaetzte_steuerabgaben(
    schuldige_ust: Decimal,
    nettoumsatz: Decimal,
    company: Company | None = None,
) -> Decimal:
    """USt plus pauschale GmbH-Ruecklage auf positiven Nettoumsatz."""
    ruecklage = gmbh_ruecklage_ytd(nettoumsatz, company)
    return (schuldige_ust + ruecklage).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def gmbh_ruecklage_ytd(
    nettoumsatz: Decimal,
    company: Company | None = None,
) -> Decimal:
    """Pauschale KSt/GewSt-Ruecklage auf positiven Nettoumsatz im Jahr."""
    anteil = steuerruecklage_anteil(company)
    return (max(nettoumsatz, Decimal("0")) * anteil).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP,
    )
