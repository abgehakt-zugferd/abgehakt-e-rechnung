"""Filter fuer die Rechnungsliste — getrennt von der Listenroute selbst."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Query

from app.models.customer import Customer
from app.models.invoice import Invoice
from app.services.beleg_status import ohne_erstversand_bedingung


@dataclass(frozen=True, slots=True)
class Listenfilter:
    art: str
    faellig: str
    versand: str


def filtere_rechnungsliste(
    query: Query,
    *,
    status: str = "",
    q: str = "",
    art: str = "",
    faellig: str = "",
    versand: str = "",
    heute: date | None = None,
) -> tuple[Query, Listenfilter]:
    """Wendet Status-, Such- und Auswahlfilter an; unbekannte Werte werden geleert."""
    if status:
        query = query.filter(Invoice.status == status)
    else:
        # Verworfene Entwuerfe (#145) erscheinen nur ueber den Statusfilter.
        query = query.filter(Invoice.status != "discarded")
    if q:
        query = query.filter(
            Invoice.invoice_number.ilike(f"%{q}%") | Customer.name.ilike(f"%{q}%")
        )

    if art == "rechnung":
        query = query.filter(Invoice.invoice_type.is_(None))
    elif art == "gutschrift":
        query = query.filter(Invoice.invoice_type == "credit_note")
    else:
        art = ""

    if faellig == "ueberfaellig":
        query = query.filter(Invoice.due_date < (heute or date.today()))
    else:
        faellig = ""

    if versand == "offen":
        # dieselbe Bedingung wie beleg_status.ist_nicht_versendet (bei status=issued)
        query = query.filter(ohne_erstversand_bedingung(Invoice.datev_sent_at))
    else:
        versand = ""

    return query, Listenfilter(art=art, faellig=faellig, versand=versand)
