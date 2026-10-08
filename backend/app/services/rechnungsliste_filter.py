"""Filter fuer die Rechnungsliste — getrennt von der Listenroute selbst."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Query

from app.models.customer import Customer
from app.models.invoice import Invoice
from app.services.beleg_status import ohne_erstversand_bedingung
from app.services.storno_wirkung import WIRKSAM_STORNIERT
from app.zeit import heute as kalender_heute


@dataclass(frozen=True, slots=True)
class Listenfilter:
    art: str
    faellig: str
    versand: str
    storno: str


def filtere_rechnungsliste(
    query: Query,
    *,
    status: str = "",
    q: str = "",
    art: str = "",
    faellig: str = "",
    versand: str = "",
    storno: str = "",
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
        query = query.filter(Invoice.due_date < (heute or kalender_heute()))
    else:
        faellig = ""

    if versand == "offen":
        # dieselbe Bedingung wie beleg_status.ist_nicht_versendet (bei status=issued)
        query = query.filter(ohne_erstversand_bedingung(Invoice.datev_sent_at))
    else:
        versand = ""

    if storno == "ohne":
        # dieselbe Bedingung wie die Kacheln der Uebersicht (Issue #141)
        query = query.filter(~WIRKSAM_STORNIERT)
    else:
        storno = ""

    return query, Listenfilter(art=art, faellig=faellig, versand=versand, storno=storno)
