"""Filter fuer die Rechnungsliste — getrennt von der Listenroute selbst."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Query

from app.models.customer import Customer
from app.models.invoice import Invoice
from app.services.beleg_status import ohne_zustellung_bedingung
from app.services.belegart import rohwerte
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
        from app.services.dashboard_kennzahlen import UMSATZ_BELEGARTEN_FILTER
        query = query.filter(UMSATZ_BELEGARTEN_FILTER)
    elif art == "honorargutschrift":
        query = query.filter(Invoice.invoice_type.in_(rohwerte("self_billing")))
    elif art == "honorargutschrift_storno":
        # Eigene Auswahl: der reine 389-Filter bleibt auch fuer die Kachel eindeutig.
        query = query.filter(Invoice.invoice_type.in_(rohwerte("self_billing_storno")))
    elif art == "gutschrift":
        query = query.filter(Invoice.invoice_type.in_(rohwerte("credit_note")))
    else:
        art = ""

    if faellig == "ueberfaellig":
        # Ein Beleg ohne Fälligkeit ist nie überfällig (BR-CO-25, Bauschritt 2b):
        # dieselbe Bedingung wie die Kennzahl der Uebersicht.
        query = query.filter(
            Invoice.due_date.isnot(None),
            Invoice.due_date < (heute or kalender_heute()),
        )
    else:
        faellig = ""

    if versand == "offen":
        # dieselbe Bedingung wie beleg_status.ist_nicht_versendet (bei status=issued):
        # die fehlende ZUSTELLUNG AN DEN KUNDEN (Bauschritt 5b). Ein Beleg nur an
        # die Buchhaltung bleibt in der Menge.
        query = query.filter(ohne_zustellung_bedingung(Invoice.kunde_zugestellt_am))
    else:
        versand = ""

    if storno == "ohne":
        # dieselbe Bedingung wie die Kacheln der Uebersicht (Issue #141)
        query = query.filter(~WIRKSAM_STORNIERT)
    else:
        storno = ""

    return query, Listenfilter(art=art, faellig=faellig, versand=versand, storno=storno)
