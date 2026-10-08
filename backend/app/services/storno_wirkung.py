"""Wie eine Stornierung per Gutschrift in Summen wirkt (Issue #141).

Grundsatz (docs/specs/kennzahlen-storno.md): eine Stornierung wirkt in jeder
Kennzahl genau einmal, und eine Gutschrift gehoert in denselben Topf wie ihr
Original. Wirksam ist eine gestellte Gutschrift (issued oder paid); sie spiegelt
ihr Original vollstaendig (STORNO_AMOUNT_MISMATCH im Validator, `build_storno`).
Die Kennzahlen fragen hier, statt die Regel je Funktion neu zu formulieren.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import and_, exists, func
from sqlalchemy.orm import Session, aliased

from app.models.invoice import Invoice

_AUSGESTELLT = ("issued", "paid")

_Gutschrift = aliased(Invoice)

# SQL-Bedingung an `Invoice`: zu dieser Rechnung besteht eine wirksame Gutschrift.
# Sie korreliert fest auf die Basistabelle `Invoice`. Eine Abfrage, deren aeussere
# Entitaet ein `aliased(Invoice)` ist, bekaeme ein unkorreliertes EXISTS (wahr,
# sobald irgendeine Gutschrift existiert); dort die Bedingung neu bilden.
WIRKSAM_STORNIERT = exists().where(
    _Gutschrift.original_invoice_id == Invoice.id,
    _Gutschrift.invoice_type == "credit_note",
    _Gutschrift.status.in_(_AUSGESTELLT),
)


def summe_gutschriften(
    db: Session,
    feld,
    seit: date,
    *,
    topf: str | None,
    bis: date | None = None,
    ausgezahlt: bool = False,
) -> Decimal:
    """Summiert gestellte Gutschriften, deren Original in `topf` zaehlt.

    Eine Gutschrift gehoert in denselben Topf wie ihr Original (Issue #141):
    `topf` None ist die gewoehnliche Rechnung, sonst der `invoice_type` des
    Originals. Gutschriften ohne Original (Altbestand) zaehlen zur
    gewoehnlichen Rechnung. Gezaehlt wird nach dem Datum der Gutschrift.

    Mit `ausgezahlt` zaehlen nur Rueckzahlungen: ausgezahlte (paid) Gutschriften
    zu einem bezahlten Original, nach ihrem `bezahlt_am` (`bis` inklusive). Ohne
    bezahltes Original ist nie Geld hereingekommen, das zurueckgehen koennte.
    """
    original = aliased(Invoice)
    if topf is None:
        # Ohne Original ist der Alias im LEFT JOIN NULL; die eine Bedingung deckt
        # die Standardrechnung und den Altbestand zugleich ab.
        topf_filter = original.invoice_type.is_(None)
    else:
        topf_filter = original.invoice_type == topf
    if ausgezahlt:
        topf_filter = and_(topf_filter, original.status == "paid")
    datum = Invoice.bezahlt_am if ausgezahlt else Invoice.issue_date
    status = ("paid",) if ausgezahlt else _AUSGESTELLT
    bedingungen = [
        Invoice.status.in_(status),
        Invoice.invoice_type == "credit_note",
        topf_filter,
        datum >= seit,
    ]
    if bis is not None:
        bedingungen.append(datum <= bis)
    return (
        db.query(func.coalesce(func.sum(feld), 0))
        .select_from(Invoice)
        .outerjoin(original, Invoice.original_invoice_id == original.id)
        .filter(*bedingungen)
        .scalar()
    ) or Decimal("0")
