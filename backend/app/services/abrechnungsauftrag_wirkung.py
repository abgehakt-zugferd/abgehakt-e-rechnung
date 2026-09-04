"""Aus einem angenommenen Uebergabebeleg werden Entwuerfe (abgehakt#22).

Getrennt vom Lesen, und zwar mit Absicht: `uebergabe_befund.py` beurteilt und
schreibt nichts, hier wird geschrieben und nicht mehr beurteilt. Erst der Knopf
"Als Rechnung anlegen" ruft diese Stelle auf.

Was hier entsteht, ist ein ENTWURF. Aus ihm wird ein Dokument durch
Finalisieren, und das bleibt menschlich; danach ist nur noch Storno moeglich.
Nichts wird automatisch finalisiert, nichts automatisch versendet.

Die Steuer entsteht HIER, aus dem Status des Kunden hinter der `partner_id` -
der Auftrag traegt sie nicht. Eine falsche Ableitung muss man deshalb im
Entwurf korrigieren koennen; die Betraege dagegen nicht (siehe invoice_guard
und das Bearbeitungsformular).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services.archive_frist import berechne_archive_until
from app.services.invoice_number import generate_next_invoice_number
from app.services.uebergabe_befund import Belegurteil
from app.services.uebergabe_eingang import merken

# § 12 Abs. 2 Nr. 7c UStG: Einraeumung von Nutzungsrechten nach dem UrhG.
TANTIEME_STEUERSATZ = Decimal("7.00")

# Der Wertevorrat des Kundenstatus in dieser Anwendung. `nicht_steuerbar` gibt
# es hier nicht: die Zuweisung an den eigenen Verlag ist kein
# Leistungsaustausch, sie erzeugt drueben gar keine Gutschrift und kommt
# deshalb nie an.
STEUER_AUS_STATUS = {
    "regelbesteuert": ("S", TANTIEME_STEUERSATZ),
    "kleinunternehmer": ("E", Decimal("0.00")),
}

# 389 ist die Abrechnung ueber eine fremde Leistung (Gutschriftverfahren,
# § 14 Abs. 2 UStG), 381 die kaufmaennische Gutschrift. Der Unterschied ist eine
# Entscheidung des Absenders und steht im Klartext im Auftrag.
TYPCODE_BELEGART = {
    "389": "self_billing",
    "381": "credit_note",
}

_CENT = Decimal("0.01")


class WirkungFehler(ValueError):
    """Aus diesem Beleg entsteht nichts."""


class BelegSchonVerarbeitet(WirkungFehler):
    """Zweimal eingelesen heisst einmal gewirkt."""


def steuer_fuer(kunde: Customer) -> tuple:
    """(Steuerkategorie, Satz) aus dem Status des Kunden."""
    status = (kunde.ust_status or "regelbesteuert").strip()
    if status not in STEUER_AUS_STATUS:
        raise WirkungFehler(
            f"Unbekannter Umsatzsteuerstatus '{status}' bei Kunde {kunde.customer_number}"
        )
    return STEUER_AUS_STATUS[status]


def _kunde(db: Session, partner_id) -> Customer:
    try:
        kennung = uuid.UUID(str(partner_id))
    except (ValueError, AttributeError, TypeError) as fehler:
        raise WirkungFehler(f"Keine Kundenkennung: {partner_id}") from fehler
    kunde = (
        db.query(Customer)
        .filter(Customer.id == kennung, Customer.deleted_at.is_(None))
        .first()
    )
    if kunde is None:
        # Ein Kunde entsteht nur von Hand. Zuordnung ueber den Namen ist keine
        # Option: Namensgleichheit ist selten, aber wenn sie eintritt, landet
        # Geld beim Falschen.
        raise WirkungFehler(f"Kein Kunde zu partner_id {partner_id}")
    return kunde


def _datum(wert) -> Optional[date]:
    return date.fromisoformat(wert) if wert else None


def entwuerfe_anlegen(
    db: Session,
    urteil: Belegurteil,
    *,
    company: Optional[Company] = None,
    dateiname: Optional[str] = None,
) -> list:
    """Legt die Entwuerfe an und merkt den Beleg. Committet nicht.

    Alles oder nichts: entweder entstehen alle Gutschriften des Auftrags, oder
    es scheitert und der Aufrufer rollt zurueck.
    """
    if not urteil.angenommen:
        raise WirkungFehler("Aus einem abgelehnten Beleg entsteht nichts.")
    if urteil.bereits_verarbeitet:
        raise BelegSchonVerarbeitet(urteil.beleg_id or urteil.beleg_sha256)
    if not urteil.nutzlast:
        raise WirkungFehler("Der Beleg traegt keine Nutzlast.")

    if company is None:
        company = db.query(Company).filter(Company.id == 1).first()
        if company is None:
            raise WirkungFehler("Firmendaten sind nicht eingerichtet.")

    nutzlast = urteil.nutzlast
    quartal = nutzlast.get("abrechnungsquartal", "")
    projekt = (nutzlast.get("projekt") or {}).get("name", "")
    ausstellung = urteil.erzeugt_am.date() if urteil.erzeugt_am else date.today()
    faellig = ausstellung + timedelta(days=14)

    entwuerfe = []
    for gutschrift in nutzlast.get("gutschriften", []):
        belegart = TYPCODE_BELEGART.get(str(gutschrift.get("typcode")))
        if belegart is None:
            raise WirkungFehler(f"Unbekannter typcode {gutschrift.get('typcode')}")

        kunde = _kunde(db, (gutschrift.get("beteiligter") or {}).get("partner_id"))
        kategorie, satz = steuer_fuer(kunde)
        zeitraum = gutschrift.get("leistungszeitraum") or {}

        entwurf = Invoice(
            invoice_number=generate_next_invoice_number(db, issue_date=ausstellung),
            customer_id=kunde.id,
            issue_date=ausstellung,
            due_date=faellig,
            service_period_start=_datum(zeitraum.get("von")),
            service_period_end=_datum(zeitraum.get("bis")),
            payment_terms=company.payment_terms_default,
            buyer_reference=quartal or None,
            notes=f"Abrechnungsauftrag {quartal}, {projekt}".strip(", "),
            tax_category=kategorie,
            invoice_type=belegart,
            status="draft",
            uebergabe_beleg_id=urteil.beleg_id,
            uebergabe_beleg_sha256=urteil.beleg_sha256,
        )
        db.add(entwurf)
        db.flush()

        netto_summe = Decimal("0")
        steuer_summe = Decimal("0")
        for lfd, position in enumerate(gutschrift.get("positionen") or [], 1):
            netto = Decimal(str(position["netto"])).quantize(_CENT)
            steuer = (netto * satz / 100).quantize(_CENT, rounding=ROUND_HALF_UP)
            db.add(InvoiceItem(
                invoice_id=entwurf.id,
                position=lfd,
                description=str(position.get("bezeichnung", "")).strip(),
                unit="Pauschal",
                quantity=Decimal("1"),
                unit_price=netto,
                tax_rate=satz,
                net_amount=netto,
                tax_amount=steuer,
                gross_amount=netto + steuer,
            ))
            netto_summe += netto
            steuer_summe += steuer

        entwurf.net_total = netto_summe
        entwurf.tax_total = steuer_summe
        entwurf.gross_total = netto_summe + steuer_summe
        entwurf.archive_until = berechne_archive_until(entwurf.issue_date)
        entwuerfe.append(entwurf)

    if not entwuerfe:
        raise WirkungFehler("Der Auftrag enthaelt keine Gutschrift.")

    merken(db, urteil, dateiname=dateiname)
    return entwuerfe
