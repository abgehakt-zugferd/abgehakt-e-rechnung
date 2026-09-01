"""Abrechnungsauftrag aus signiertem Übergabebeleg → Entwürfe (abgehakt#22).

Kein REST, kein Auto-Finalisieren, keine neuen Kunden. Steuer aus abgehakt-Stammdaten
folgt später (#22 Nachzug); vorerst Regelbesteuert § 12 Abs. 2 Nr. 7c mit 7 %.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services.archive_frist import berechne_archive_until
from app.services.invoice_number import generate_next_invoice_number
from app.services.uebergabebeleg import (
    ABSENDER_TANTIEMEN,
    Belegbefund,
    EMPFAENGER_ABGEHAKT,
    UebergabeFehler,
    beleg_pruefen,
)

# § 12 Abs. 2 Nr. 7c UStG — Nutzungsrechte an Werken (Tantieme-Standard)
TANTIEME_STEUERSATZ = Decimal("7.00")
TYP_ABRECHNUNGSAUFTRAG = "abrechnungsauftrag"
TYP_389 = "389"


class AuftragFehler(UebergabeFehler):
    """Nutzlast oder Auftrag passt nicht zum Import."""


class PartnerUnbekannt(AuftragFehler):
    """partner_id fehlt im Kundenstamm (Customer.id)."""


class BelegSchonVerarbeitet(AuftragFehler):
    """Dieser beleg_id wurde bereits importiert."""


def _geld(wert: Decimal) -> str:
    return str(wert.quantize(Decimal("0.01"), ROUND_HALF_UP))


def _netto_decimal(s: str) -> Decimal:
    return Decimal(s).quantize(Decimal("0.01"), ROUND_HALF_UP)


def _calc_item(quantity: Decimal, unit_price: Decimal, tax_rate: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    net = (quantity * unit_price).quantize(Decimal("0.01"), ROUND_HALF_UP)
    tax = (net * tax_rate / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
    return net, tax, net + tax


def _beleg_marker(beleg_id: str) -> str:
    return f"uebergabe-beleg:{beleg_id}"


def _auftrag_pruefen(befund: Belegbefund) -> dict:
    if befund.absender != ABSENDER_TANTIEMEN:
        raise AuftragFehler(f"Absender {befund.absender} ist nicht tantiemen-app")
    if befund.empfaenger != EMPFAENGER_ABGEHAKT:
        raise AuftragFehler(f"Empfänger {befund.empfaenger} ist nicht abgehakt")
    if befund.nutzlast_art != TYP_ABRECHNUNGSAUFTRAG:
        raise AuftragFehler(f"nutzlast_art {befund.nutzlast_art} ist kein Abrechnungsauftrag")
    return befund.nutzlast


def _summe_stimmt(positionen: list[dict], summe_netto: str | None) -> bool:
    if summe_netto is None:
        return True
    erwartet = sum(_netto_decimal(p["netto"]) for p in positionen)
    return _geld(erwartet) == summe_netto


def _kunde_finden(db: Session, partner_id: str) -> Customer:
    try:
        pid = uuid.UUID(partner_id)
    except ValueError as fehler:
        raise PartnerUnbekannt(partner_id) from fehler
    kunde = (
        db.query(Customer)
        .filter(Customer.id == pid, Customer.deleted_at.is_(None))
        .first()
    )
    if not kunde:
        raise PartnerUnbekannt(partner_id)
    return kunde


def _positionen_anlegen(
    db: Session,
    invoice: Invoice,
    positionen: list[dict],
    tax_rate: Decimal,
) -> tuple[Decimal, Decimal]:
    net_total = Decimal("0")
    tax_total = Decimal("0")
    for i, pos in enumerate(positionen, 1):
        netto = _netto_decimal(pos["netto"])
        qty = Decimal("1")
        net, tax, gross = _calc_item(qty, netto, tax_rate)
        db.add(
            InvoiceItem(
                invoice_id=invoice.id,
                position=i,
                description=str(pos.get("bezeichnung", "Beteiligung")).strip(),
                unit="Pauschal",
                quantity=qty,
                unit_price=netto,
                tax_rate=tax_rate,
                net_amount=net,
                tax_amount=tax,
                gross_amount=gross,
            )
        )
        net_total += net
        tax_total += tax
    return net_total, tax_total


def _totals_setzen(invoice: Invoice, net_total: Decimal, tax_total: Decimal) -> None:
    invoice.net_total = net_total.quantize(Decimal("0.01"))
    invoice.tax_total = tax_total.quantize(Decimal("0.01"))
    invoice.gross_total = (net_total + tax_total).quantize(Decimal("0.01"))
    invoice.archive_until = berechne_archive_until(invoice.issue_date)


def _schon_verarbeitet(db: Session, beleg_id: str) -> bool:
    marker = _beleg_marker(beleg_id)
    return (
        db.query(Invoice.id)
        .filter(Invoice.notes.isnot(None), Invoice.notes.contains(marker))
        .first()
        is not None
    )


def entwuerfe_aus_befund(
    db: Session,
    befund: Belegbefund,
    company: Optional[Company] = None,
) -> list[Invoice]:
    """Erzeugt Entwürfe für alle Gutschriften im Auftrag. Committet nicht."""
    nutzlast = _auftrag_pruefen(befund)
    if _schon_verarbeitet(db, befund.beleg_id):
        raise BelegSchonVerarbeitet(befund.beleg_id)

    if company is None:
        company = db.query(Company).filter(Company.id == 1).first()
        if not company:
            raise RuntimeError("Firmendaten nicht konfiguriert")

    quartal = nutzlast.get("abrechnungsquartal", "")
    issue_date = befund.erzeugt_am.date()
    due_date = issue_date + timedelta(days=14)
    marker = _beleg_marker(befund.beleg_id)

    entwuerfe: list[Invoice] = []
    for gutschrift in nutzlast.get("gutschriften", []):
        if gutschrift.get("typcode") != TYP_389:
            raise AuftragFehler(f"typcode {gutschrift.get('typcode')} ist nicht 389")

        beteiligter = gutschrift.get("beteiligter") or {}
        partner_id = beteiligter.get("partner_id")
        if not partner_id:
            raise PartnerUnbekannt("?")

        positionen = gutschrift.get("positionen") or []
        if not positionen:
            raise AuftragFehler(f"Keine Positionen für partner_id {partner_id}")

        summe = gutschrift.get("summe") or {}
        if not _summe_stimmt(positionen, summe.get("netto")):
            raise AuftragFehler(f"Summe netto passt nicht für partner_id {partner_id}")

        kunde = _kunde_finden(db, partner_id)
        lz = gutschrift.get("leistungszeitraum") or {}
        delivery_date = None
        if lz.get("bis"):
            delivery_date = date.fromisoformat(lz["bis"])

        invoice_number = generate_next_invoice_number(db, issue_date=issue_date)
        invoice = Invoice(
            invoice_number=invoice_number,
            customer_id=kunde.id,
            issue_date=issue_date,
            due_date=due_date,
            delivery_date=delivery_date,
            payment_terms=company.payment_terms_default,
            buyer_reference=f"auftrag-{quartal}",
            notes=f"{marker}; quartal={quartal}; partner={partner_id}",
            tax_category="S",
            invoice_type="self_billing",
            status="draft",
        )
        db.add(invoice)
        db.flush()

        net_total, tax_total = _positionen_anlegen(
            db, invoice, positionen, TANTIEME_STEUERSATZ,
        )
        _totals_setzen(invoice, net_total, tax_total)
        entwuerfe.append(invoice)

    if not entwuerfe:
        raise AuftragFehler("Auftrag enthält keine Gutschriften")

    return entwuerfe


def entwuerfe_aus_roh(
    db: Session,
    roh: bytes,
    schluessel_wurzel: Optional[Path] = None,
    company: Optional[Company] = None,
) -> list[Invoice]:
    befund = beleg_pruefen(roh, wurzel=schluessel_wurzel)
    return entwuerfe_aus_befund(db, befund, company=company)


def entwuerfe_aus_datei(
    db: Session,
    pfad: Path,
    schluessel_wurzel: Optional[Path] = None,
    company: Optional[Company] = None,
) -> list[Invoice]:
    return entwuerfe_aus_roh(
        db, Path(pfad).read_bytes(), schluessel_wurzel=schluessel_wurzel, company=company,
    )


def ordner_einlesen(
    db: Session,
    uebergaben_wurzel: Path,
    schluessel_wurzel: Optional[Path] = None,
) -> list[Invoice]:
    """Alle noch nicht verarbeiteten Belege in tantiemen-app-nach-abgehakt."""
    richtung = uebergaben_wurzel / "tantiemen-app-nach-abgehakt"
    if not richtung.is_dir():
        return []

    alle: list[Invoice] = []
    for pfad in sorted(richtung.glob("*.json")):
        try:
            alle.extend(
                entwuerfe_aus_datei(db, pfad, schluessel_wurzel=schluessel_wurzel),
            )
        except BelegSchonVerarbeitet:
            continue
    return alle
