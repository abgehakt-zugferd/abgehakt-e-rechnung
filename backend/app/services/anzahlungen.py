"""Verrechnete Anzahlungen einer Schlussrechnung (#259, Teil 1).

Ein Ort fuer alles, was Router, XML und PDF ueber die Verrechnung wissen
muessen: welche Anzahlungen waehlbar sind, welche ein Beleg verrechnet, wie
hoch die Vorauszahlung (BT-113) ist, ob der Beleg gestellt werden darf und wann
eine Anzahlung wieder frei wird. Die Verknuepfung liegt in
`anzahlung_verrechnungen`; der partielle Unique-Index dort sichert, dass eine
Anzahlung hoechstens EINMAL aktiv verrechnet ist.

Die Summen der Schlussrechnung (BT-112, Steuerzusammenfassung) bleiben auf dem
vollen Entgelt; hier entsteht nur der Abzug (BT-113 = Brutto der Anzahlung).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import exists
from sqlalchemy.orm import Session, object_session
from sqlalchemy.orm.exc import UnmappedInstanceError

from app.models.anzahlung_verrechnung import AnzahlungVerrechnung
from app.models.invoice import Invoice
from app.services.belegart import belegart, belegart_filter
from app.services.pruefregeln.befund import Issue
from app.services.rechnung.fehler import RechnungFehler
from app.services.storno_wirkung import WIRKSAM_STORNIERT, stornobelege_zu

NULL = Decimal("0.00")


def _sitzung(beleg) -> Session | None:
    try:
        return object_session(beleg)
    except UnmappedInstanceError:  # Attrappe statt Invoice
        return None


def verrechnete(invoice: Invoice) -> list[Invoice]:
    """Die Anzahlungen, die dieser Beleg verrechnet (auch nach Freigabe als Nachweis).

    Ohne Session (Testattrappe, nicht gespeicherter Beleg) gibt es keine.
    """
    db = _sitzung(invoice)
    if db is None or invoice.id is None:
        return []
    zeilen = (
        db.query(AnzahlungVerrechnung)
        .filter(AnzahlungVerrechnung.schlussrechnung_id == invoice.id)
        .all()
    )
    return sorted((z.anzahlung for z in zeilen), key=lambda a: a.invoice_number)


def vorauszahlung(invoice: Invoice) -> Decimal:
    """BT-113: Summe der Bruttobetraege der verrechneten Anzahlungen."""
    return sum((a.gross_total for a in verrechnete(invoice)), NULL)


def zahlbetrag(invoice: Invoice, brutto: Decimal) -> Decimal:
    """BT-115: Brutto der Schlussrechnung minus Vorauszahlung."""
    return brutto - vorauszahlung(invoice)


def verrechenbare(db: Session, customer_id, schlussrechnung_id=None) -> list[Invoice]:
    """Anzahlungen des Kunden, die ein Entwurf noch verrechnen kann.

    Bezahlt, nicht storniert und in keiner ANDEREN Schlussrechnung aktiv
    verrechnet. Was der Entwurf selbst schon verrechnet, bleibt waehlbar.
    """
    if customer_id is None:
        return []
    anderswo = exists().where(
        AnzahlungVerrechnung.anzahlung_id == Invoice.id,
        AnzahlungVerrechnung.aktiv.is_(True),
        AnzahlungVerrechnung.schlussrechnung_id != schlussrechnung_id,
    ) if schlussrechnung_id is not None else exists().where(
        AnzahlungVerrechnung.anzahlung_id == Invoice.id,
        AnzahlungVerrechnung.aktiv.is_(True),
    )
    return (
        db.query(Invoice)
        .filter(
            Invoice.customer_id == customer_id,
            belegart_filter(Invoice.invoice_type, "prepayment"),
            Invoice.status == "paid",
            Invoice.bezahlt_am.is_not(None),
            ~WIRKSAM_STORNIERT,
            ~anderswo,
        )
        .order_by(Invoice.issue_date, Invoice.invoice_number)
        .all()
    )


def _ids_lesen(rohe_ids) -> list[uuid.UUID]:
    ids: list[uuid.UUID] = []
    for roh in rohe_ids:
        roh = (roh or "").strip()
        if not roh:
            continue
        try:
            wert = uuid.UUID(roh)
        except ValueError as fehler:
            raise RechnungFehler(400, "Ungültige Auswahl der Anzahlung.") from fehler
        if wert not in ids:
            ids.append(wert)
    return ids


def verknuepfen(db: Session, invoice: Invoice, rohe_ids) -> None:
    """Verknuepfung des Entwurfs durch die gewaehlten Anzahlungen ersetzen.

    Nur die Verfuegbarkeit wird hier geprueft (die Datenbank sichert sie
    zusaetzlich); die fachlichen Regeln pruefen erst beim Finalisieren, damit
    ein Entwurf mit Auswahl speicherbar bleibt.
    """
    ids = _ids_lesen(rohe_ids)
    for alt in db.query(AnzahlungVerrechnung).filter(
            AnzahlungVerrechnung.schlussrechnung_id == invoice.id).all():
        db.delete(alt)
    db.flush()
    for anzahlung_id in ids:
        anzahlung = db.get(Invoice, anzahlung_id)
        if anzahlung is None:
            raise RechnungFehler(400, "Die gewählte Anzahlung gibt es nicht.")
        _frei_pruefen(db, anzahlung)
        db.add(AnzahlungVerrechnung(schlussrechnung_id=invoice.id, anzahlung_id=anzahlung_id))
    db.flush()


def _frei_pruefen(db: Session, anzahlung: Invoice) -> None:
    schon = (
        db.query(AnzahlungVerrechnung)
        .filter(AnzahlungVerrechnung.anzahlung_id == anzahlung.id,
                AnzahlungVerrechnung.aktiv.is_(True))
        .first()
    )
    if schon is not None:
        raise RechnungFehler(
            400,
            f"Die Anzahlung {anzahlung.invoice_number} ist schon in einer anderen "
            "Rechnung verrechnet.",
        )


def gewaehlte_ids(invoice: Invoice) -> list[str]:
    """Ids der verrechneten Anzahlungen fuer die Vorauswahl im Formular."""
    return [str(a.id) for a in verrechnete(invoice)]


def freigeben(db: Session, invoice: Invoice) -> None:
    """Verworfener Entwurf oder aufgehobene Schlussrechnung: Anzahlungen wieder frei.

    Die Zeilen bleiben als Nachweis stehen, nur `aktiv` endet.
    """
    for zeile in db.query(AnzahlungVerrechnung).filter(
            AnzahlungVerrechnung.schlussrechnung_id == invoice.id).all():
        zeile.aktiv = False


def wieder_binden(db: Session, invoice: Invoice) -> None:
    """Zurueckgeholter Entwurf: Verrechnung wieder aktiv, sofern die Anzahlung frei ist."""
    for zeile in db.query(AnzahlungVerrechnung).filter(
            AnzahlungVerrechnung.schlussrechnung_id == invoice.id).all():
        _frei_pruefen(db, zeile.anzahlung)
        zeile.aktiv = True


def pruefe(invoice: Invoice) -> list[Issue]:
    """Sperren vor dem Finalisieren; Meldungen sind fuer die Anwenderin geschrieben."""
    anzahlungen = verrechnete(invoice)
    if not anzahlungen:
        return []
    fehler: list[str] = []
    if belegart(invoice.invoice_type).intern is not None:
        fehler.append("Nur eine Standardrechnung kann eine Anzahlung verrechnen.")
    if len(anzahlungen) > 1:
        fehler.append(
            "Es ist mehr als eine Anzahlung gewählt. Verrechnet wird vorerst genau "
            "eine Anzahlung je Rechnung.")
    if invoice.abzug_betrag is not None:
        fehler.append(
            "Anzahlung und Abzug auf Belegebene lassen sich nicht zugleich "
            "verrechnen. Bitte einen der beiden Abzüge entfernen.")
    if invoice.ersetzt_invoice_id or invoice.original_invoice_id:
        fehler.append(
            "Eine Ersatzrechnung oder ein Folgebeleg verweist schon auf eine "
            "vorausgegangene Rechnung und kann daneben keine Anzahlung verrechnen.")
    fehler.extend(f for a in anzahlungen if (f := _pruefe_anzahlung(invoice, a)))
    fehler.extend(_pruefe_betrag(invoice, anzahlungen))
    return [Issue("ANZAHLUNG_NICHT_VERRECHENBAR", "error", f, "anzahlung_ids") for f in fehler]


def _pruefe_betrag(invoice: Invoice, anzahlungen: list[Invoice]) -> list[str]:
    summe = sum((a.gross_total for a in anzahlungen), NULL)
    if summe > invoice.gross_total:
        return [
            f"Die Anzahlung ({summe} {invoice.currency}) ist höher als der "
            f"Rechnungsbetrag ({invoice.gross_total} {invoice.currency}). Ein "
            "Zahlbetrag unter null ist nicht zulässig."]
    return []


def _pruefe_anzahlung(invoice: Invoice, a: Invoice) -> str:
    nr = a.invoice_number
    if belegart(a.invoice_type).intern != "prepayment":
        return f"Beleg {nr} ist keine Anzahlungsrechnung."
    if a.status != "paid" or a.bezahlt_am is None:
        return f"Die Anzahlung {nr} ist noch nicht als bezahlt erfasst."
    if a.customer_id != invoice.customer_id:
        return f"Die Anzahlung {nr} gehört zu einem anderen Kunden."
    if a.currency != invoice.currency:
        return f"Die Anzahlung {nr} ist in einer anderen Währung ausgestellt."
    if a.tax_category != invoice.tax_category:
        return f"Die Anzahlung {nr} hat eine andere Steuerkategorie als diese Rechnung."
    db = _sitzung(a)
    if db is not None and stornobelege_zu(db, [a.id]):
        return f"Die Anzahlung {nr} ist storniert."
    return ""
