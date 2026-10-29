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

from sqlalchemy import and_, exists, func, or_
from sqlalchemy.orm import Session, aliased

from app.models.invoice import Invoice
from app.services.belegart import belegart_filter

# "Gestellt" im Sinne der Kennzahlen: finalisiert (issued) oder bezahlt (paid).
# Einzige Quelle dieser Menge — dashboard_kennzahlen importiert sie (Issue #160),
# sonst formulieren beide Module die Wirksamkeit einer Gutschrift neu und die
# beiden Fassungen laufen auseinander, sobald ein Status dazukommt.
GESTELLT = ("issued", "paid")

_Gutschrift = aliased(Invoice)

# SQL-Bedingung an `Invoice`: zu dieser Rechnung besteht eine wirksame Gutschrift.
# Sie korreliert fest auf die Basistabelle `Invoice`. Eine Abfrage, deren aeussere
# Entitaet ein `aliased(Invoice)` ist, bekaeme ein unkorreliertes EXISTS (wahr,
# sobald irgendeine Gutschrift existiert); dort die Bedingung neu bilden.
WIRKSAM_STORNIERT = exists().where(
    _Gutschrift.original_invoice_id == Invoice.id,
    belegart_filter(_Gutschrift.invoice_type, "credit_note", "self_billing_storno"),
    _Gutschrift.status.in_(GESTELLT),
)


def _topf_filter(original, topf: str | tuple | None):
    """Original-Belegart im Topf, inkl. Aliase der Standardrechnung (#172)."""
    if isinstance(topf, tuple):
        return belegart_filter(original.invoice_type, *topf)
    if topf is None:
        # Ohne Original ist der Alias im LEFT JOIN NULL; belegart_filter(None)
        # deckt Standard, Aliase und fehlendes Original zugleich ab.
        return belegart_filter(original.invoice_type, None)
    return belegart_filter(original.invoice_type, topf)


def gutschrift_bedingungen(
    seit: date,
    *,
    topf: str | tuple | None,
    bis_ausschliesslich: date | None = None,
    ausgezahlt: bool = False,
) -> tuple:
    """(original, Bedingungen) fuer wirksame Gutschriften im Zeitraum.

    `original` ist der Alias des Originalbelegs: die Abfrage muss ihn mit
    `Invoice.original_invoice_id == original.id` aussen verbinden. Einzige
    Quelle der Gutschriftmenge fuer `summe_gutschriften` und die Aufstellung
    je Steuerkategorie (Issue #256).
    """
    original = aliased(Invoice)
    topf_filter = _topf_filter(original, topf)
    if isinstance(topf, tuple) and "prepayment" in topf:
        # Ohne vereinnahmte Anzahlung entstand keine Umsatzsteuer. Ihr Storno
        # darf deshalb auch keinen Steuerabzug erzeugen (#157).
        topf_filter = and_(topf_filter, or_(
            belegart_filter(original.invoice_type, None),
            ~belegart_filter(original.invoice_type, "prepayment"),
            original.bezahlt_am.is_not(None),
        ))
    if ausgezahlt:
        topf_filter = and_(topf_filter, original.status == "paid")
    datum = Invoice.bezahlt_am if ausgezahlt else Invoice.issue_date
    status = ("paid",) if ausgezahlt else GESTELLT
    bedingungen = [
        Invoice.status.in_(status),
        belegart_filter(Invoice.invoice_type, "credit_note", "self_billing_storno"),
        topf_filter,
        datum >= seit,
    ]
    if bis_ausschliesslich is not None:
        bedingungen.append(datum < bis_ausschliesslich)
    return original, bedingungen


def summe_gutschriften(
    db: Session,
    feld,
    seit: date,
    *,
    topf: str | tuple | None,
    bis_ausschliesslich: date | None = None,
    ausgezahlt: bool = False,
) -> Decimal:
    """Summiert gestellte Gutschriften, deren Original in `topf` zaehlt.

    Eine Gutschrift gehoert in denselben Topf wie ihr Original (Issue #141):
    `topf` None ist die gewoehnliche Rechnung, sonst der `invoice_type` des
    Originals. Gutschriften ohne Original (Altbestand) zaehlen zur
    gewoehnlichen Rechnung. Gezaehlt wird nach dem Datum der Gutschrift.

    Mit `ausgezahlt` zaehlen nur Rueckzahlungen: ausgezahlte (paid) Gutschriften
    zu einem bezahlten Original, nach ihrem `bezahlt_am`. Ohne bezahltes
    Original ist nie Geld hereingekommen, das zurueckgehen koennte.

    Der Zeitraum ist halboffen [seit, bis_ausschliesslich) wie bei allen
    Kennzahlen (Issue #160): angrenzende Zeitraeume greifen nicht ineinander.
    """
    original, bedingungen = gutschrift_bedingungen(
        seit, topf=topf, bis_ausschliesslich=bis_ausschliesslich, ausgezahlt=ausgezahlt,
    )
    return (
        db.query(func.coalesce(func.sum(feld), 0))
        .select_from(Invoice)
        .outerjoin(original, Invoice.original_invoice_id == original.id)
        .filter(*bedingungen)
        .scalar()
    ) or Decimal("0")
