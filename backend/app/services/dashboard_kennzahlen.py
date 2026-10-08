"""Kennzahlen fuer die Uebersicht — Betraege, Zaehlungen und Steuer-Ruecklagen.

Abgehakt kennt nur Ausgangsrechnungen, keine Eingangsrechnungen und keine
Betriebsausgaben. „Schuldige Umsatzsteuer“ ist deshalb die auf gestellten
Belegen ausgewiesene USt (abzueglich Gutschriften) — kein Vorsteuerabzug.
„Geschaetzte Steuerabgaben“ plant die Zahlung: sie zieht die Vorsteuer aus selbst
ausgestellten Honorargutschriften (389) ab, der einzigen Eingangsseite, die das
Programm kennt, und addiert die in den Einstellungen hinterlegte GmbH-Ruecklage
(KSt + GewSt) auf den Nettoumsatz. Entscheidung des Betreibers vom 2026-09-30.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.invoice import Invoice
from app.services.beleg_status import nicht_versendet_bedingung
from app.services.steuer_ruecklage import steuerruecklage_anteil
from app.services.storno_wirkung import WIRKSAM_STORNIERT, summe_gutschriften

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
    art: str | None,
    bis: date | None = None,
) -> Decimal:
    """Summiert ein Betragsfeld gestellter Belege einer Art seit `seit`.

    `art` ist `invoice_type`; None steht fuer die gewoehnliche Rechnung.
    Gutschriften summiert `storno_wirkung.summe_gutschriften`, nicht diese Funktion.
    Betraege werden ohne Ruecksicht auf `invoices.currency` addiert. Das ist eine
    bestehende Vereinfachung: gemischte Waehrungen werden nicht getrennt.
    """
    if art is None:
        typ_filter = Invoice.invoice_type.is_(None)
    else:
        typ_filter = Invoice.invoice_type == art
    # Von Hand auf cancelled gesetzt, aber schon per Gutschrift aufgehoben: das
    # Original zaehlt, die Gutschrift zieht ab. Sonst wirkte die Stornierung
    # doppelt (Issue #141).
    gestellt = or_(Invoice.status.in_(_AUSGESTELLT),
                   and_(Invoice.status == "cancelled", WIRKSAM_STORNIERT))
    bedingungen = [
        gestellt,
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
    ust = _summe_feld(db, Invoice.tax_total, von, art=None, bis=bis)
    gutschrift_ust = summe_gutschriften(db, Invoice.tax_total, von, topf=None, bis=bis)
    return (ust - gutschrift_ust).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def schuldige_umsatzsteuer_ytd(db: Session, seit: date) -> Decimal:
    """Ausgewiesene USt auf gestellten Belegen im Zeitraum, netto nach Gutschriften."""
    return schuldige_umsatzsteuer(db, seit, None)


def nettoumsatz_ytd(db: Session, seit: date) -> Decimal:
    """Nettoumsatz gestellter Belege im Zeitraum, abzueglich Gutschriften."""
    netto = _summe_feld(db, Invoice.net_total, seit, art=None)
    gutschrift_netto = summe_gutschriften(db, Invoice.net_total, seit, topf=None)
    return (netto - gutschrift_netto).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def vorsteuer_honorargutschriften(db: Session, seit: date) -> Decimal:
    """Ausgewiesene USt auf gestellten Honorargutschriften (389) seit `seit`,
    abzueglich ihrer Stornierungen (Issue #141)."""
    vorsteuer = _summe_feld(db, Invoice.tax_total, seit, art="self_billing")
    storniert = summe_gutschriften(db, Invoice.tax_total, seit, topf="self_billing")
    return (vorsteuer - storniert).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def geschaetzte_steuerabgaben(
    schuldige_ust: Decimal,
    nettoumsatz: Decimal,
    company: Company | None = None,
    vorsteuer: Decimal = Decimal("0"),
) -> Decimal:
    """USt abzueglich Vorsteuer, plus pauschale GmbH-Ruecklage auf positiven Nettoumsatz.

    Die Differenz aus USt und Vorsteuer wird nicht bei null gekappt: uebersteigt die
    Vorsteuer die USt, ist das eine Erstattung und mindert die Ruecklage wirklich.
    """
    ruecklage = gmbh_ruecklage_ytd(nettoumsatz, company)
    return (schuldige_ust - vorsteuer + ruecklage).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP,
    )


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
    """Gestellte, nicht wirksam stornierte Standardrechnungen: Anzahl und Bruttosumme."""
    anzahl = (
        db.query(func.count(Invoice.id))
        .filter(Invoice.status == "issued", _STANDARD, ~WIRKSAM_STORNIERT)
        .scalar()
    ) or 0
    betrag = (
        db.query(func.coalesce(func.sum(Invoice.gross_total), 0))
        .filter(Invoice.status == "issued", _STANDARD, ~WIRKSAM_STORNIERT)
        .scalar()
    ) or Decimal("0")
    return OffenePosten(anzahl=anzahl, betrag=betrag)


def ueberfaellige_forderungen(db: Session, heute: date) -> Ueberfaellig:
    """Offene Standardrechnungen mit Faelligkeit vor heute."""
    filter_ = (
        Invoice.status == "issued",
        _STANDARD,
        ~WIRKSAM_STORNIERT,
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

    Gezaehlt wird in der Datenbank, nicht im Speicher: die Uebersicht laedt sonst
    bei jedem Aufruf die ganze Rechnungstabelle, um am Ende eine Zahl zu zeigen.
    Die Bedingung kommt aus `beleg_status`, nicht noch einmal hier formuliert.
    """
    return (
        db.query(func.count(Invoice.id))
        .filter(
            _STANDARD,
            nicht_versendet_bedingung(Invoice.status, Invoice.datev_sent_at),
        )
        .scalar()
    ) or 0


def bezahlt_im_zeitraum(
    db: Session, von: date, bis: date | None = None,
) -> Decimal:
    """Bruttosumme bezahlter Standardrechnungen nach `bezahlt_am` (Geldeingang).

    `bis` ist die obere Grenze exklusiv (`bezahlt_am < bis`), damit angrenzende
    Monate sich nicht ueberschneiden.
    """
    bedingungen = [
        Invoice.status == "paid",
        _STANDARD,
        Invoice.bezahlt_am >= von,
    ]
    if bis is not None:
        bedingungen.append(Invoice.bezahlt_am < bis)
    return (
        db.query(func.coalesce(func.sum(Invoice.gross_total), 0))
        .filter(*bedingungen)
        .scalar()
    ) or Decimal("0")


def umsatz_im_zeitraum(
    db: Session, von: date, bis: date | None = None,
) -> Decimal:
    """Nettoumsatz bezahlter Standardrechnungen nach `bezahlt_am`.

    Entscheidung des Betreibers vom 2026-09-30: Umsatz ist, was bezahlt wurde.
    Gestellte, unbezahlte Rechnungen sind offene Forderungen und zaehlen hier nicht.
    Ausgezahlte Gutschriften mindern ihn nach ihrem `bezahlt_am` (Issue #141).
    """
    bedingungen = [
        Invoice.status == "paid",
        _STANDARD,
        Invoice.bezahlt_am >= von,
    ]
    if bis is not None:
        bedingungen.append(Invoice.bezahlt_am <= bis)
    eingang = (
        db.query(func.coalesce(func.sum(Invoice.net_total), 0))
        .filter(*bedingungen)
        .scalar()
    ) or Decimal("0")
    ausgezahlt = summe_gutschriften(
        db, Invoice.net_total, von, topf=None, bis=bis, ausgezahlt=True,
    )
    return eingang - ausgezahlt


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
