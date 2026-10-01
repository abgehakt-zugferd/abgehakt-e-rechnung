"""Umsatzsteuerlicher Status des Kunden fuer Honorargutschriften (389).

Kleine Schnittstelle, grosse Folge: falscher Ausweis loest § 14c UStG aus.
Der Validator und die Abrechnungswirkung lesen beide nur hier.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from app.zeit import heute as kalender_heute

if TYPE_CHECKING:
    from app.models.customer import Customer
    from app.models.invoice import Invoice

# § 12 Abs. 2 Nr. 7c UStG: Einraeumung von Nutzungsrechten nach dem UrhG.
TANTIEME_STEUERSATZ = Decimal("7.00")

UST_STATUS_UNGEKLAERT = "ungeklaert"
UST_STATUS_REGELBESTEUERT = "regelbesteuert"
UST_STATUS_KLEINUNTERNEHMER = "kleinunternehmer"

UST_STATUS_WERTE = frozenset({
    UST_STATUS_UNGEKLAERT,
    UST_STATUS_REGELBESTEUERT,
    UST_STATUS_KLEINUNTERNEHMER,
})

GEKLAERTE_STATUS = frozenset({
    UST_STATUS_REGELBESTEUERT,
    UST_STATUS_KLEINUNTERNEHMER,
})

# Der Wertevorrat, aus dem Kategorie und Satz folgen. `ungeklaert` fehlt
# absichtlich: daraus entsteht keine Steuer.
STEUER_AUS_STATUS = {
    UST_STATUS_REGELBESTEUERT: ("S", TANTIEME_STEUERSATZ),
    UST_STATUS_KLEINUNTERNEHMER: ("E", Decimal("0.00")),
}


class SteuerstatusFehler(ValueError):
    """Aus dem Kundenstatus laesst sich keine Steuer ableiten."""


def ust_status_aus_formular(roh: str) -> str:
    """Geschlossener Wertevorrat; Unbekanntes faellt auf ungeklaert."""
    gewaehlt = (roh or "").strip()
    return gewaehlt if gewaehlt in UST_STATUS_WERTE else UST_STATUS_UNGEKLAERT


def bestaetigungsdatum_nach_wechsel(
    bisher: str | None,
    neu: str,
    bisheriges_datum: date | None,
    *,
    heute: date | None = None,
) -> date | None:
    """Datum setzen bei Wechsel auf geklaert, leeren bei ungeklaert, sonst lassen."""
    if neu == UST_STATUS_UNGEKLAERT:
        return None
    if neu in GEKLAERTE_STATUS and neu != (bisher or "").strip():
        return heute or kalender_heute()
    return bisheriges_datum


def gutschriftempfaenger_aus_formular(roh: str) -> bool:
    return (roh or "").strip() in {"1", "on", "true", "yes"}


def steuerfelder_uebernehmen(
    kunde: Customer,
    *,
    ust_status_roh: str,
    gutschriftempfaenger_roh: str = "",
    tax_number_roh: str = "",
    heute: date | None = None,
) -> None:
    """Schalter, Status, Bestaetigungsdatum und Steuernummer am Kunden setzen."""
    neu = ust_status_aus_formular(ust_status_roh)
    kunde.ust_status_bestaetigt_am = bestaetigungsdatum_nach_wechsel(
        getattr(kunde, "ust_status", None),
        neu,
        getattr(kunde, "ust_status_bestaetigt_am", None),
        heute=heute,
    )
    kunde.ust_status = neu
    kunde.gutschriftempfaenger = gutschriftempfaenger_aus_formular(
        gutschriftempfaenger_roh
    )
    nummer = (tax_number_roh or "").strip()
    kunde.tax_number = nummer or None


def steuer_fuer(kunde: Customer) -> tuple[str, Decimal]:
    """(Steuerkategorie, Satz) aus dem Status eines Gutschriftempfaengers."""
    if not getattr(kunde, "gutschriftempfaenger", False):
        raise SteuerstatusFehler(
            f"Kunde {kunde.customer_number} ist kein Gutschriftempfaenger"
        )
    status = (kunde.ust_status or UST_STATUS_UNGEKLAERT).strip()
    if status == UST_STATUS_UNGEKLAERT:
        raise SteuerstatusFehler(
            f"Umsatzsteuerstatus ungeklaert bei Kunde {kunde.customer_number}"
        )
    if status not in STEUER_AUS_STATUS:
        raise SteuerstatusFehler(
            f"Unbekannter Umsatzsteuerstatus '{status}' bei Kunde {kunde.customer_number}"
        )
    return STEUER_AUS_STATUS[status]


def _issue(code: str, message: str, field: str | None):
    from app.services.validator import Issue
    return Issue(code, "error", message, field)


def pruefe_honorargutschrift(invoice: Invoice) -> list:
    """Pflichtpruefungen fuer self_billing. Liefert Issue-Liste (kann leer sein)."""
    if getattr(invoice, "invoice_type", None) != "self_billing":
        return []
    kunde = getattr(invoice, "customer", None)
    if kunde is None:
        return []
    if not getattr(kunde, "gutschriftempfaenger", False):
        return [_issue(
            "GUTSCHRIFTEMPFAENGER_ERFORDERLICH",
            "Kunde ist kein Gutschriftempfaenger; eine Honorargutschrift "
            "darf nur an solche Kunden gehen.",
            "customer.gutschriftempfaenger",
        )]
    status = (getattr(kunde, "ust_status", None) or UST_STATUS_UNGEKLAERT).strip()
    if status == UST_STATUS_UNGEKLAERT:
        kennung = getattr(kunde, "customer_number", None) or getattr(kunde, "name", "?")
        return [_issue(
            "UST_STATUS_UNGEKLAERT",
            f"Umsatzsteuerstatus des Kunden {kennung} ist "
            "ungeklaert; eine Honorargutschrift darf so nicht finalisiert werden.",
            "customer.ust_status",
        )]
    fehler = []
    if not (getattr(kunde, "tax_number", None) or getattr(kunde, "vat_id", None)):
        fehler.append(_issue(
            "CUSTOMER_TAX_ID_MISSING",
            "Steuernummer oder USt-IdNr. des Kunden fehlt "
            "(§ 14 Abs. 4 S. 1 Nr. 2 UStG).",
            "customer.tax",
        ))
    if status in STEUER_AUS_STATUS:
        fehler.extend(_steuer_passt_zu_status(invoice, status))
    return fehler


def _steuer_passt_zu_status(invoice: Invoice, status: str) -> list:
    erwartet_kat, erwartet_satz = STEUER_AUS_STATUS[status]
    fehler = []
    kat = getattr(invoice, "tax_category", None)
    if kat != erwartet_kat:
        fehler.append(_issue(
            "UST_STATUS_STEUER_MISMATCH",
            f"Steuerkategorie '{kat}' passt nicht zum Status '{status}' "
            f"(erwartet {erwartet_kat}).",
            "tax_category",
        ))
    # Der Satz wird je Position geprueft, nicht aus Kopfsummen zurueckgerechnet:
    # 30,07 EUR zu 7 % ergeben 2,10 EUR, rueckgerechnet 6,98 %. Dass Kopf und
    # Positionen zusammenpassen, sichern ITEM_TAX_MISMATCH und TAX_TOTAL_MISMATCH
    # im Validator schon.
    for pos, item in enumerate(getattr(invoice, "items", None) or [], start=1):
        satz = getattr(item, "tax_rate", None)
        if satz is None:
            continue
        if Decimal(satz).quantize(Decimal("0.01")) != erwartet_satz:
            fehler.append(_issue(
                "UST_STATUS_STEUER_MISMATCH",
                f"Steuersatz {satz} in Position {pos} passt nicht zum Status "
                f"'{status}' (erwartet {erwartet_satz}).",
                f"items[{pos}].tax_rate",
            ))
    return fehler
