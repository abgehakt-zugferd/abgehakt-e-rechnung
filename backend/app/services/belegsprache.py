"""Belegsprache: gespeicherter Sprachcode → vollstaendige Belegdarstellung.

Reine Darstellungslogik ohne HTTP, Jinja, Datenbank, ReportLab, XML oder Invoice.
`de` und `en` sind die einzigen Codes. Unbekannte Werte fallen nicht auf Deutsch
zurueck: ein fremdsprachiger Beleg wuerde sonst unbemerkt falsch beschriftet.

Formatierung ist zustandsfrei: kein locale.setlocale, keine globale aktuelle
Sprache. Jeder Aufruf von `darstellung(sprache)` liefert einen unveraenderlichen
Datensatz mit eigenen Formatmethoden.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

Belegsprache = Literal["de", "en"]

_PLATZHALTER = "\x00"

AE_HINWEIS = (
    "Steuerschuldnerschaft des Leistungsempfängers / reverse charge, "
    "Art. 196 Council Directive 2006/112/EC"
)


class UnknownDocumentLanguageError(ValueError):
    """Gespeicherter oder uebermittelter Sprachcode ist weder de noch en."""

    def __init__(self, wert):
        self.wert = wert
        super().__init__(f"Unbekannte Belegsprache: {wert!r}")


def resolve_belegsprache(wert: str | None) -> Belegsprache:
    """Nur `de` und `en`. Jeder andere Wert — inkl. None und leer — ist ein Fehler.

    Der Kompatibilitaetsdefault `de` fuer ein fehlendes Formularfeld liegt im
    Router vor dem Aufruf, nicht hier: ein bereits gespeicherter ungueltiger
    Wert darf nicht still auf Deutsch fallen.
    """
    if wert == "de" or wert == "en":
        return wert
    raise UnknownDocumentLanguageError(wert)


def _betrag_roh(wert, nachkommastellen: int = 2) -> str:
    """Kaufmaennisch gerundete Zahl ohne Waehrung, mit englischen Trennzeichen."""
    zahl = wert if isinstance(wert, Decimal) else Decimal(str(wert))
    stufe = Decimal(1).scaleb(-nachkommastellen)
    zahl = zahl.quantize(stufe, rounding=ROUND_HALF_UP)
    return f"{zahl:,.{nachkommastellen}f}"


def _betrag_de(wert, nachkommastellen: int = 2) -> str:
    return (
        _betrag_roh(wert, nachkommastellen)
        .replace(",", _PLATZHALTER)
        .replace(".", ",")
        .replace(_PLATZHALTER, ".")
    )


def _menge_roh(wert) -> str:
    zahl = wert if isinstance(wert, Decimal) else Decimal(str(wert))
    zahl = zahl.normalize()
    if zahl == zahl.to_integral_value():
        zahl = zahl.to_integral_value()
    return format(zahl, "f")


@dataclass(frozen=True, slots=True)
class Belegdarstellung:
    """Unveraenderlicher Datensatz: Schablonentexte und Formate einer Sprache."""

    code: Belegsprache

    # Belegtitel
    titel_rechnung: str
    titel_anzahlung: str
    titel_gutschrift: str
    titel_korrektur: str

    # Kopf / Meta
    label_rechnungsnummer: str
    label_rechnungsdatum: str
    label_leistungsdatum: str
    label_leistungszeitraum: str
    label_vorauss_leistungszeitraum: str
    label_faelligkeit: str
    label_kundennummer: str
    label_ihre_referenz: str
    label_bestellnummer: str
    label_ust_id_kunde: str

    # Tabellenkopf
    label_pos: str
    label_beschreibung: str
    label_menge: str
    label_einheit: str
    label_einzelpreis: str
    label_mwst: str
    label_betrag: str

    # Summen
    label_netto: str
    label_gutschriftbetrag: str
    label_rechnungsbetrag: str
    steuerzeile_muster: str  # mit {satz} und {basis}

    # Zahlung / QR / Stempel
    label_verwendungszweck: str
    label_scan_to_pay: str
    label_ust_id: str
    label_steuernummer: str
    stempel_entwurf: str
    fallback_gutschrift_ueberweisung: str
    fallback_gutschrift_ohne: str
    fallback_zahlbar: str

    # Storno-automatisierte Texte (Muster mit {nummer} und {datum})
    storno_zahlungsbedingungen: str
    storno_bemerkung: str

    # Steuerhinweise PDF (E/K/O lokalisiert; AE immer zweisprachig)
    hinweis_ae: str
    hinweis_e: str
    hinweis_k: str
    hinweis_o: str

    def format_betrag(self, wert, waehrung: str = "EUR") -> str:
        if self.code == "de":
            zahl = _betrag_de(wert)
            if waehrung == "EUR":
                return f"{zahl} €"
            return f"{zahl} {waehrung}"
        return f"{waehrung} {_betrag_roh(wert)}"

    def format_menge(self, wert) -> str:
        roh = _menge_roh(wert)
        if self.code == "de":
            return roh.replace(".", ",")
        return roh

    def format_datum(self, datum: date) -> str:
        if self.code == "de":
            return datum.strftime("%d.%m.%Y")
        return datum.strftime("%Y-%m-%d")

    def titel(self, belegart_intern: str | None) -> str:
        """Sichtbarer Belegtitel zum fachlichen internen Wert (nach belegart())."""
        mapping = {
            None: self.titel_rechnung,
            "standard": self.titel_rechnung,
            "invoice": self.titel_rechnung,
            "prepayment": self.titel_anzahlung,
            "credit_note": self.titel_gutschrift,
            "credit": self.titel_gutschrift,
            "storno": self.titel_gutschrift,
            "correction": self.titel_korrektur,
            "self_billing": self.titel_gutschrift,
            "self-billing": self.titel_gutschrift,
        }
        return mapping[belegart_intern]

    def steuerhinweis(self, kategorie: str) -> str | None:
        hinweise = {
            "AE": self.hinweis_ae,
            "E": self.hinweis_e,
            "K": self.hinweis_k,
            "O": self.hinweis_o,
        }
        return hinweise.get(kategorie)

    def steuerzeile(self, satz: str, basis: str) -> str:
        return self.steuerzeile_muster.format(satz=satz, basis=basis)


_DE = Belegdarstellung(
    code="de",
    titel_rechnung="RECHNUNG",
    titel_anzahlung="ANZAHLUNGSRECHNUNG",
    titel_gutschrift="GUTSCHRIFT",
    titel_korrektur="KORREKTURRECHNUNG",
    label_rechnungsnummer="Rechnungsnummer:",
    label_rechnungsdatum="Rechnungsdatum:",
    label_leistungsdatum="Leistungsdatum:",
    label_leistungszeitraum="Leistungszeitraum:",
    label_vorauss_leistungszeitraum="Voraussichtlicher Leistungszeitraum:",
    label_faelligkeit="Fälligkeitsdatum:",
    label_kundennummer="Kundennummer:",
    label_ihre_referenz="Ihre Referenz:",
    label_bestellnummer="Bestellnummer:",
    label_ust_id_kunde="USt-IdNr. Kunde:",
    label_pos="Pos.",
    label_beschreibung="Beschreibung",
    label_menge="Menge",
    label_einheit="Einheit",
    label_einzelpreis="Einzelpreis",
    label_mwst="MwSt.",
    label_betrag="Betrag",
    label_netto="Nettobetrag",
    label_gutschriftbetrag="Gutschriftbetrag",
    label_rechnungsbetrag="Rechnungsbetrag",
    steuerzeile_muster="zzgl. {satz} MwSt. auf {basis}",
    label_verwendungszweck="Verwendungszweck:",
    label_scan_to_pay="Zum Überweisen scannen.",
    label_ust_id="USt-IdNr.:",
    label_steuernummer="Steuernummer:",
    stempel_entwurf="ENTWURF",
    fallback_gutschrift_ueberweisung=(
        "Bitte überweisen Sie den Gutschriftbetrag auf die unten genannte Bankverbindung."
    ),
    fallback_gutschrift_ohne="Gutschrift ohne Zahlungsaufforderung.",
    fallback_zahlbar="Zahlbar ohne Abzug.",
    storno_zahlungsbedingungen="Gutschrift/Storno zur Rechnung {nummer}.",
    storno_bemerkung="Storno zur Rechnung {nummer} vom {datum}.",
    hinweis_ae=AE_HINWEIS,
    hinweis_e="Kein Ausweis von Umsatzsteuer, da Kleinunternehmer gemäß § 19 UStG.",
    hinweis_k=(
        "Steuerfreie innergemeinschaftliche Lieferung gemäß § 4 Nr. 1b UStG "
        "i.V.m. § 6a UStG."
    ),
    hinweis_o="Nicht im Steuergebiet des Ausstellers steuerbar gemäß § 3a Abs. 2 UStG.",
)

_EN = Belegdarstellung(
    code="en",
    titel_rechnung="INVOICE",
    titel_anzahlung="PREPAYMENT INVOICE",
    titel_gutschrift="CREDIT NOTE",
    titel_korrektur="CORRECTIVE INVOICE",
    label_rechnungsnummer="Invoice number:",
    label_rechnungsdatum="Invoice date:",
    label_leistungsdatum="Date of supply:",
    label_leistungszeitraum="Period of supply:",
    label_vorauss_leistungszeitraum="Expected period of supply:",
    label_faelligkeit="Due date:",
    label_kundennummer="Customer number:",
    label_ihre_referenz="Your reference:",
    label_bestellnummer="Purchase order number:",
    label_ust_id_kunde="Customer VAT ID:",
    label_pos="No.",
    label_beschreibung="Description",
    label_menge="Quantity",
    label_einheit="Unit",
    label_einzelpreis="Unit price",
    label_mwst="VAT",
    label_betrag="Amount",
    label_netto="Net amount",
    label_gutschriftbetrag="Credit note amount",
    label_rechnungsbetrag="Invoice total",
    steuerzeile_muster="plus {satz} VAT on {basis}",
    label_verwendungszweck="Reference:",
    label_scan_to_pay="Scan to pay",
    label_ust_id="VAT ID:",
    label_steuernummer="Tax number:",
    stempel_entwurf="DRAFT",
    fallback_gutschrift_ueberweisung=(
        "Please transfer the credit note amount to the bank account below."
    ),
    fallback_gutschrift_ohne="Credit note without payment request.",
    fallback_zahlbar="Payable without deduction.",
    storno_zahlungsbedingungen="Credit note / cancellation of invoice {nummer}.",
    storno_bemerkung="Cancellation of invoice {nummer} dated {datum}.",
    hinweis_ae=AE_HINWEIS,
    hinweis_e=(
        "No VAT charged as the supplier is a small business under "
        "section 19 of the German VAT Act (UStG)."
    ),
    hinweis_k=(
        "VAT-exempt intra-Community supply under section 4 no. 1b UStG "
        "in conjunction with section 6a UStG."
    ),
    hinweis_o=(
        "Not taxable in the supplier's territory under section 3a (2) UStG."
    ),
)

_DARSTELLUNGEN: dict[Belegsprache, Belegdarstellung] = {"de": _DE, "en": _EN}


def darstellung(sprache: Belegsprache) -> Belegdarstellung:
    """Liefert die unveraenderliche Darstellung zur Sprache (zustandslos)."""
    return _DARSTELLUNGEN[sprache]
