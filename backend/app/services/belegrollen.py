"""Unveränderliche Stammdaten der Parteien eines Belegs.

Die Rollen gelten für XML, PDF und Pflichtfeldprüfung. Zahlung und Versand
haben eigene Empfänger und dürfen deshalb nicht durch diesen Tausch laufen.
"""
from dataclasses import dataclass

from app.services.belegart import belegart


@dataclass(frozen=True, slots=True)
class Partei:
    name: str = ""
    address_line1: str = ""
    address_line2: str = ""
    zip_code: str = ""
    city: str = ""
    country: str = "DE"
    email: str = ""
    phone: str = ""
    steuernummer: str = ""
    ust_id: str = ""
    kennung: str = ""
    kontakt_name: str | None = None
    rechtsform: str = ""
    sitz: str = ""
    registergericht: str = ""
    registernummer: str = ""
    vertretung: str = ""
    aufsichtsrat_vorsitz: str = ""

    # Die bestehenden Ausgabehelfer lesen diese Stammdaten-Bezeichner.
    @property
    def tax_number(self):
        return self.steuernummer

    @property
    def vat_id(self):
        return self.ust_id

    @property
    def customer_number(self):
        return self.kennung


@dataclass(frozen=True, slots=True)
class Besetzung:
    verkaeufer: Partei
    erwerber: Partei
    verkaeufer_ist_firma: bool


def _partei(objekt, *, firma: bool) -> Partei:
    def wert(feld):
        return (getattr(objekt, feld, None) or "").strip()

    felder = {
        feld: wert(feld) for feld in (
            "name", "address_line1", "address_line2", "zip_code", "city",
            "email", "phone", "rechtsform", "sitz", "registergericht",
            "registernummer", "vertretung", "aufsichtsrat_vorsitz",
        )
    }
    return Partei(
        **felder, country=wert("country") or "DE",
        steuernummer=wert("tax_number"), ust_id=wert("vat_id"),
        kennung="" if firma else wert("customer_number"),
        # Nur die Firma hat einen gepflegten Kontaktpunkt. Beim Kunden ist
        # BG-6 optional; ein Firmenname darf dort keinen Kontakt erfinden.
        kontakt_name=(wert("contact_name") or wert("name") or None) if firma else None,
    )


def besetzung(invoice, firma, kunde) -> Besetzung:
    art = belegart(getattr(invoice, "invoice_type", None))
    eigene = _partei(firma, firma=True)
    gegenpartei = _partei(kunde, firma=False)
    if art.intern == "self_billing":
        return Besetzung(gegenpartei, eigene, False)
    return Besetzung(eigene, gegenpartei, True)
