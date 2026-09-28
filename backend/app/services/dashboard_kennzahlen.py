"""Kennzahlen fuer die Uebersicht — Betraege, Zaehlungen und Steuer-Ruecklagen.

Abgehakt kennt nur Ausgangsrechnungen, keine Eingangsrechnungen und keine
Betriebsausgaben. „Schuldige Umsatzsteuer“ ist deshalb die auf gestellten
Belegen ausgewiesene USt (abzueglich Gutschriften) — kein Vorsteuerabzug.
„Geschaetzte Steuerabgaben“ addiert dazu die in den Einstellungen hinterlegte
GmbH-Ruecklage (KSt + GewSt) auf den Nettoumsatz.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.invoice import Invoice
from app.services.beleg_status import ist_nicht_versendet
from app.services.steuer_ruecklage import steuerruecklage_anteil

_AUSGESTELLT = ("issued", "paid")
_STANDARD = Invoice.invoice_type.is_(None)


@dataclass(frozen=True, slots=True)
class Belegzaehlung:
    gesamt: int
    entwurf: int
    gestellt: int
    bezahlt: int
    storniert: int


@dataclass(frozen=True, slots=True)
class OffenePosten:
    anzahl: int
    betrag: Decimal


@dataclass(frozen=True, slots=True)
class Ueberfaellig:
    anzahl: int
    betrag: Decimal
    aeltester_tage: int | None


def _summe_feld(
    db: Session,
    feld,
    seit: date,
    *,
    rechnung: bool,
    bis: date | None = None,
) -> Decimal:
    """Summiert ein Betragsfeld fuer Rechnungen oder Gutschriften seit `seit`.

    Betraege werden ohne Ruecksicht auf `invoices.currency` addiert. Das ist eine
    bestehende Vereinfachung: gemischte Waehrungen werden nicht getrennt.
    """
    if rechnung:
        typ_filter = Invoice.invoice_type.is_(None)
    else:
        typ_filter = Invoice.invoice_type == "credit_note"
    bedingungen = [
        Invoice.status.in_(_AUSGESTELLT),
        typ_filter,
        Invoice.issue_date >= seit,
    ]
    if bis is not None:
        bedingungen.append(Invoice.issue_date <= bis)
    return (
        db.query(func.coalesce(func.sum(feld), 0))
        .filter(*bedingungen)
        .scalar()
    ) or Decimal("0")


def schuldige_umsatzsteuer(
    db: Session, von: date, bis: date | None = None,
) -> Decimal:
    """Ausgewiesene USt auf gestellten Belegen im Zeitraum, netto nach Gutschriften."""
    ust = _summe_feld(db, Invoice.tax_total, von, rechnung=True, bis=bis)
    gutschrift_ust = _summe_feld(db, Invoice.tax_total, von, rechnung=False, bis=bis)
    return (ust - gutschrift_ust).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def schuldige_umsatzsteuer_ytd(db: Session, seit: date) -> Decimal:
    """Ausgewiesene USt auf gestellten Belegen im Zeitraum, netto nach Gutschriften."""
    return schuldige_umsatzsteuer(db, seit, None)


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


def belegzaehlung(db: Session) -> Belegzaehlung:
    """Zaehlt Belege nach Status. Verworfene liegen in gesamt, nicht separat."""
    def _count(status: str | None = None) -> int:
        q = db.query(func.count(Invoice.id))
        if status is not None:
            q = q.filter(Invoice.status == status)
        return q.scalar() or 0

    return Belegzaehlung(
        gesamt=_count(),
        entwurf=_count("draft"),
        gestellt=_count("issued"),
        bezahlt=_count("paid"),
        storniert=_count("cancelled"),
    )


def offene_forderungen(db: Session) -> OffenePosten:
    """Gestellte Standardrechnungen: Anzahl und Bruttosumme."""
    anzahl = (
        db.query(func.count(Invoice.id))
        .filter(Invoice.status == "issued", _STANDARD)
        .scalar()
    ) or 0
    betrag = (
        db.query(func.coalesce(func.sum(Invoice.gross_total), 0))
        .filter(Invoice.status == "issued", _STANDARD)
        .scalar()
    ) or Decimal("0")
    return OffenePosten(anzahl=anzahl, betrag=betrag)


def ueberfaellige_forderungen(db: Session, heute: date) -> Ueberfaellig:
    """Offene Standardrechnungen mit Faelligkeit vor heute."""
    filter_ = (
        Invoice.status == "issued",
        _STANDARD,
        Invoice.due_date < heute,
    )
    anzahl = db.query(func.count(Invoice.id)).filter(*filter_).scalar() or 0
    betrag = (
        db.query(func.coalesce(func.sum(Invoice.gross_total), 0))
        .filter(*filter_)
        .scalar()
    ) or Decimal("0")
    aeltestes = db.query(func.min(Invoice.due_date)).filter(*filter_).scalar()
    aeltester_tage = (heute - aeltestes).days if aeltestes is not None else None
    return Ueberfaellig(anzahl=anzahl, betrag=betrag, aeltester_tage=aeltester_tage)


def nicht_versendet_anzahl(db: Session) -> int:
    """Gestellte Standardrechnungen ohne Erstversand.

    Die Bedingung kommt aus `beleg_status.ist_nicht_versendet`, nicht noch einmal
    hier formuliert.
    """
    belege = (
        db.query(Invoice.status, Invoice.datev_sent_at)
        .filter(_STANDARD)
        .all()
    )
    return sum(
        1 for status, sent_at in belege
        if ist_nicht_versendet(status, sent_at)
    )


def bezahlt_im_zeitraum(
    db: Session, von: datetime, bis: datetime | None = None,
) -> Decimal:
    """Bruttosumme bezahlter Standardrechnungen nach `updated_at`.

    `bis` ist die obere Grenze exklusiv (`updated_at < bis`), damit angrenzende
    Monate sich nicht ueberschneiden.
    """
    bedingungen = [
        Invoice.status == "paid",
        _STANDARD,
        Invoice.updated_at >= von,
    ]
    if bis is not None:
        bedingungen.append(Invoice.updated_at < bis)
    return (
        db.query(func.coalesce(func.sum(Invoice.gross_total), 0))
        .filter(*bedingungen)
        .scalar()
    ) or Decimal("0")


def umsatz_im_zeitraum(
    db: Session, von: date, bis: date | None = None,
) -> Decimal:
    """Bruttoumsatz gestellter und bezahlter Standardrechnungen nach `issue_date`."""
    bedingungen = [
        Invoice.status.in_(_AUSGESTELLT),
        _STANDARD,
        Invoice.issue_date >= von,
    ]
    if bis is not None:
        bedingungen.append(Invoice.issue_date <= bis)
    return (
        db.query(func.coalesce(func.sum(Invoice.gross_total), 0))
        .filter(*bedingungen)
        .scalar()
    ) or Decimal("0")


def vorjahres_stichtag(heute: date) -> date:
    """Selber Kalendertag im Vorjahr; 29.02. wird auf 28.02. abgebildet."""
    try:
        return date(heute.year - 1, heute.month, heute.day)
    except ValueError:
        return date(heute.year - 1, 2, 28)


def umsatz_abweichung_prozent(
    aktuell: Decimal, vorjahr: Decimal,
) -> Decimal | None:
    """Prozentuale Abweichung; None wenn kein Vergleichswert (Vorjahr null)."""
    if vorjahr == 0:
        return None
    return ((aktuell - vorjahr) / vorjahr * Decimal("100")).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP,
    )


def quartalsbeginn(heute: date) -> date:
    """Erster Tag des laufenden Kalenderquartals."""
    monat = ((heute.month - 1) // 3) * 3 + 1
    return date(heute.year, monat, 1)
