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

from sqlalchemy import and_, case, func, or_
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.invoice import Invoice
from app.services.beleg_status import nicht_versendet_bedingung, ueberfaellig_bedingung
from app.services.belegart import belegart_filter
from app.services.steuer_ruecklage import steuerruecklage_anteil
from app.services.storno_wirkung import GESTELLT, WIRKSAM_STORNIERT, summe_gutschriften

# Umsatz-Belegarten (Standardrechnung und Anzahlungsrechnung) — einzige Quelle
# dieser Menge. storno_wirkung definiert sie nicht neu, sondern bekommt sie als
# `topf` gereicht (Issue #160); auch die Rechnungsliste filtert darueber
# (rechnungsliste_filter importiert UMSATZ_BELEGARTEN_FILTER).
# Filter inkl. Aliase der Standardrechnung ueber belegart_filter (#172).
UMSATZ_BELEGARTEN = (None, "prepayment")
UMSATZ_BELEGARTEN_FILTER = belegart_filter(Invoice.invoice_type, None, "prepayment")
# Anzahlungen loesen Steuer erst bei Zahlung aus; Rechnungen der Umsatz-Belegarten behalten
# ihre bisherige Besteuerung nach Ausstellung. NULL bezahlt_am zaehlt nie.
_UMSATZ_STEUERDATUM = case(
    (belegart_filter(Invoice.invoice_type, "prepayment"), Invoice.bezahlt_am),
    else_=Invoice.issue_date,
)


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
    art: str | tuple | None,
    bis_ausschliesslich: date | None = None,
) -> Decimal:
    """Summiert ein Betragsfeld gestellter Belege einer Art seit `seit`.

    `art` ist `invoice_type`; None steht fuer die gewoehnliche Rechnung.
    Gutschriften summiert `storno_wirkung.summe_gutschriften`, nicht diese Funktion.
    Betraege werden ohne Ruecksicht auf `invoices.currency` addiert. Das ist eine
    bestehende Vereinfachung: gemischte Waehrungen werden nicht getrennt.

    Halboffener Zeitraum [seit, bis_ausschliesslich) wie bei allen Kennzahlen
    (Issue #160).
    """
    datum = Invoice.issue_date
    if art == UMSATZ_BELEGARTEN:
        # Unbezahlte Anzahlung zaehlt nicht; Standard (inkl. Aliase) immer.
        typ_filter = and_(UMSATZ_BELEGARTEN_FILTER, or_(
            belegart_filter(Invoice.invoice_type, None), Invoice.status == "paid",
            and_(Invoice.status == "cancelled", WIRKSAM_STORNIERT,
                 Invoice.bezahlt_am.is_not(None)),
        ))
        datum = _UMSATZ_STEUERDATUM
    elif art is None:
        typ_filter = belegart_filter(Invoice.invoice_type, None)
    else:
        typ_filter = belegart_filter(Invoice.invoice_type, art)
    # Von Hand auf cancelled gesetzt, aber schon per Gutschrift aufgehoben: das
    # Original zaehlt, die Gutschrift zieht ab. Sonst wirkte die Stornierung
    # doppelt (Issue #141).
    gestellt = or_(Invoice.status.in_(GESTELLT),
                   and_(Invoice.status == "cancelled", WIRKSAM_STORNIERT))
    bedingungen = [
        gestellt,
        typ_filter,
        datum >= seit,
    ]
    if bis_ausschliesslich is not None:
        bedingungen.append(datum < bis_ausschliesslich)
    return (
        db.query(func.coalesce(func.sum(feld), 0))
        .filter(*bedingungen)
        .scalar()
    ) or Decimal("0")


def schuldige_umsatzsteuer(
    db: Session, von: date, bis_ausschliesslich: date | None = None,
) -> Decimal:
    """Ausgewiesene USt auf gestellten Belegen im halboffenen Zeitraum
    [von, bis_ausschliesslich), netto nach Gutschriften."""
    ust = _summe_feld(db, Invoice.tax_total, von, art=UMSATZ_BELEGARTEN,
                      bis_ausschliesslich=bis_ausschliesslich)
    gutschrift_ust = summe_gutschriften(
        db, Invoice.tax_total, von, topf=UMSATZ_BELEGARTEN,
        bis_ausschliesslich=bis_ausschliesslich,
    )
    return (ust - gutschrift_ust).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def schuldige_umsatzsteuer_ytd(db: Session, seit: date) -> Decimal:
    """Ausgewiesene USt auf gestellten Belegen im Zeitraum, netto nach Gutschriften."""
    return schuldige_umsatzsteuer(db, seit, None)


def nettoumsatz_ytd(db: Session, seit: date) -> Decimal:
    """Nettoumsatz gestellter Belege im Zeitraum, abzueglich Gutschriften."""
    netto = _summe_feld(db, Invoice.net_total, seit, art=UMSATZ_BELEGARTEN)
    gutschrift_netto = summe_gutschriften(db, Invoice.net_total, seit, topf=UMSATZ_BELEGARTEN)
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
    """Gestellte, nicht wirksam stornierte Rechnungen der Umsatz-Belegarten: Anzahl und Bruttosumme."""
    return _offene_posten(db, UMSATZ_BELEGARTEN_FILTER)


def offene_auszahlungen(db: Session) -> OffenePosten:
    """Unbezahlte 389 ohne wirksames Storno, Anzahl und Bruttosumme."""
    return _offene_posten(db, belegart_filter(Invoice.invoice_type, "self_billing"))


def _offene_posten(db: Session, typ_filter) -> OffenePosten:
    anzahl, betrag = db.query(
        func.count(Invoice.id), func.coalesce(func.sum(Invoice.gross_total), 0),
    ).filter(Invoice.status == "issued", typ_filter, ~WIRKSAM_STORNIERT).one()
    return OffenePosten(anzahl=anzahl, betrag=betrag)


def ueberfaellige_forderungen(db: Session, heute: date) -> Ueberfaellig:
    """Offene Rechnungen der Umsatz-Belegarten mit Faelligkeit vor heute."""
    # Eine Bedingung mit dem Listenfilter (Issue #177); Inhalt in beleg_status.
    filter_ = (ueberfaellig_bedingung(heute),)
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
    """Gestellte Rechnungen der Umsatz-Belegarten ohne Zustellung an den Kunden.

    Gezaehlt wird in der Datenbank, nicht im Speicher: die Uebersicht laedt sonst
    bei jedem Aufruf die ganze Rechnungstabelle, um am Ende eine Zahl zu zeigen.
    Die Bedingung kommt aus `beleg_status`, nicht noch einmal hier formuliert;
    sie liest `kunde_zugestellt_am` (Bauschritt 5b): Ein Beleg nur an die
    Buchhaltung zaehlt weiter als nicht versendet.
    """
    return (
        db.query(func.count(Invoice.id))
        .filter(
            UMSATZ_BELEGARTEN_FILTER,
            nicht_versendet_bedingung(Invoice.status, Invoice.kunde_zugestellt_am),
        )
        .scalar()
    ) or 0


def bezahlt_im_zeitraum(
    db: Session, von: date, bis_ausschliesslich: date | None = None,
) -> Decimal:
    """Bruttosumme bezahlter Rechnungen der Umsatz-Belegarten nach `bezahlt_am` (Geldeingang).

    Halboffener Zeitraum [von, bis_ausschliesslich): Ein am Stichtag bezahlter
    Beleg gehoert zum Folgezeitraum, angrenzende Monate greifen nicht ineinander.
    """
    bedingungen = [
        Invoice.status == "paid",
        UMSATZ_BELEGARTEN_FILTER,
        Invoice.bezahlt_am >= von,
    ]
    if bis_ausschliesslich is not None:
        bedingungen.append(Invoice.bezahlt_am < bis_ausschliesslich)
    return (
        db.query(func.coalesce(func.sum(Invoice.gross_total), 0))
        .filter(*bedingungen)
        .scalar()
    ) or Decimal("0")


def umsatz_im_zeitraum(
    db: Session, von: date, bis_ausschliesslich: date | None = None,
) -> Decimal:
    """Nettoumsatz bezahlter Rechnungen der Umsatz-Belegarten nach `bezahlt_am`.

    Entscheidung des Betreibers vom 2026-09-30: Umsatz ist, was bezahlt wurde.
    Gestellte, unbezahlte Rechnungen sind offene Forderungen und zaehlen hier nicht.
    Ausgezahlte Gutschriften mindern ihn nach ihrem `bezahlt_am` (Issue #141).

    Halboffener Zeitraum [von, bis_ausschliesslich), wie `bezahlt_im_zeitraum`
    (Issue #160): vorher zaehlte diese Funktion den Stichtag mit, die Bruttosumme
    daneben nicht.
    """
    bedingungen = [
        Invoice.status == "paid",
        UMSATZ_BELEGARTEN_FILTER,
        Invoice.bezahlt_am >= von,
    ]
    if bis_ausschliesslich is not None:
        bedingungen.append(Invoice.bezahlt_am < bis_ausschliesslich)
    eingang = (
        db.query(func.coalesce(func.sum(Invoice.net_total), 0))
        .filter(*bedingungen)
        .scalar()
    ) or Decimal("0")
    ausgezahlt = summe_gutschriften(
        db, Invoice.net_total, von, topf=UMSATZ_BELEGARTEN,
        bis_ausschliesslich=bis_ausschliesslich, ausgezahlt=True,
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
