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


def dezimal_klartext(wert) -> str:
    """`Decimal("60.0000")` → `"60"`, `Decimal("61.5000")` → `"61.5"`.

    Punkt, keine Tausender, nie Exponentenform. `str(x.normalize())` kippt bei
    durch zehn teilbaren Werten in `6E+1`; genau das stand am 2026-09-30 im
    Zahlenfeld des Rechnungsformulars.
    """
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
    titel_storno: str
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
    label_positionssumme: str
    # Zwischensumme einer Positionsgruppe (Bauschritt 3): eigenes Feld, denn
    # der Begriff ist nicht die Positionssumme des Belegs — in en tragen beide
    # zufaellig dasselbe Wort, in de verschiedene.
    label_zwischensumme: str
    abzugzeile_muster: str  # mit {grund}
    label_gutschriftbetrag: str
    label_rechnungsbetrag: str
    steuerzeile_muster: str  # mit {satz} und {basis}

    # Zahlung / QR / Stempel
    label_verwendungszweck: str
    label_scan_to_pay: str
    label_ust_id: str
    label_artikelnummer: str
    seite_muster: str
    label_steuernummer: str
    stempel_entwurf: str
    fallback_gutschrift_ueberweisung: str
    fallback_gutschrift_ohne: str
    fallback_zahlbar: str

    # Storno-automatisierte Texte (Muster mit {nummer} und {datum})
    storno_zahlungsbedingungen: str
    storno_bemerkung: str
    # Storno einer 389 (self_billing): Zahlungsbedingungen und Bemerkung in
    # einem Text, Zahlung und Bezug nennen dasselbe (Muster mit {nummer}/{datum})
    storno_gutschrift_bezug: str
    # Ersatzrechnung (docs/specs/ersatzrechnung.md), Muster mit {nummer} und {datum}
    ersatz_hinweis: str

    # Steuerhinweise PDF (E/K/O lokalisiert; AE immer zweisprachig)
    hinweis_ae: str
    hinweis_e: str
    hinweis_k: str
    hinweis_o: str

    # Abrechnungsaufstellung (§ 8b, Bauschritt 7c): eigene Beschriftungen,
    # denn die Aufstellung ist KEINE Rechnung — keine Steuertitel, kein
    # Rechnungswortlaut, keine Fälligkeit. Der Keine-Rechnung-Satz grenzt
    # gegen § 14 UStG ab; die Zahlung ist die des Auszahlers, nicht eine
    # Forderung des Ausstellers.
    titel_aufstellung: str
    label_aufstellungsnummer: str
    label_ausstellungsdatum: str
    label_leistungsmonat: str
    label_zahlungsnummer: str
    label_zahlungsdatum: str
    label_aussteller: str
    label_auszahler: str
    label_brutto: str
    label_quellensteuer: str
    label_kurs: str
    label_zahlbetrag: str
    label_anlagen: str
    label_quelle: str
    label_dateiname: str
    label_groesse_bytes: str
    label_sha256: str
    hinweis_keine_rechnung: str

    def format_betrag(self, wert, waehrung: str = "EUR") -> str:
        if self.code == "de":
            zahl = _betrag_de(wert)
            if waehrung == "EUR":
                return f"{zahl} €"
            return f"{zahl} {waehrung}"
        return f"{waehrung} {_betrag_roh(wert)}"

    def format_menge(self, wert) -> str:
        roh = dezimal_klartext(wert)
        if self.code == "de":
            return roh.replace(".", ",")
        return roh

    def format_datum(self, datum: date) -> str:
        if self.code == "de":
            return datum.strftime("%d.%m.%Y")
        return datum.strftime("%Y-%m-%d")

    def herleitungszeile(self, basis, satz, waehrung: str = "EUR") -> str:
        """Zusaetzzeile unter einer Position: Bemessungsgrundlage × Beteiligungssatz.

        Der Beteiligungssatz gehoert zur Herleitung, nie zur Umsatzsteuerspalte;
        Betrag und Satz laufen durch die Formatierer der Sprache."""
        if self.code == "de":
            return (
                f"Bemessungsgrundlage {self.format_betrag(basis, waehrung)} "
                f"× {self.format_menge(satz)} %"
            )
        return (
            f"Assessment base {self.format_betrag(basis, waehrung)} "
            f"× {self.format_menge(satz)} %"
        )

    def titel(self, belegart_intern: str | None) -> str:
        """Sichtbarer Belegtitel zum fachlichen internen Wert (nach belegart())."""
        from app.services.belegart import belegart

        mapping = {
            None: self.titel_rechnung,
            "prepayment": self.titel_anzahlung,
            "credit_note": self.titel_storno,
            "correction": self.titel_korrektur,
            "self_billing": self.titel_gutschrift,
            "self_billing_storno": SELF_BILLING_STORNO_TITEL[self.code],
        }
        return mapping[belegart(belegart_intern).intern]

    def bezeichnung(self, art: str | None) -> str:
        """Name in der Oberfläche; der PDF-Titel enthält die Pflichtangabe.

        Ein unbekannter gespeicherter Wert wird gezeigt statt geworfen: die
        Spalte invoice_type ist unbeschraenkt, und Liste und Detailseite
        muessen den Bestand erreichbar lassen (200), damit er korrigiert
        werden kann. Der PDF-Titel (titel()) bleibt fail-closed.
        """
        from app.services.belegart import UnknownInvoiceTypeError, belegart

        try:
            intern = belegart(art).intern
        except UnknownInvoiceTypeError:
            if self.code == "de":
                return f"Unbekannte Belegart: {art}"
            return f"Unknown document type: {art}"
        if intern == "self_billing_storno":
            return self.titel(intern)
        if intern == "self_billing":
            return "Honorargutschrift" if self.code == "de" else "Self-billed Invoice"
        return self.titel(art).capitalize() if self.code == "de" else self.titel(art).title()

    def steuerhinweis(self, kategorie: str) -> str | None:
        hinweise = {
            "AE": self.hinweis_ae,
            "E": self.hinweis_e,
            "K": self.hinweis_k,
            "O": self.hinweis_o,
        }
        return hinweise.get(kategorie)

    def anlagenquelle(self, quelle: str) -> str:
        """Sichtbarer Name einer Anlagenquelle der Aufstellung (§ 8b: genau
        zwei, der DB-CHECK schreibt die internen Werte fest). Ein unbekannter
        Wert wirft statt still durchzurutschen — fail-closed wie titel()."""
        try:
            return ANLAGENQUELLEN[self.code][quelle]
        except KeyError:
            raise ValueError(f"Unbekannte Anlagenquelle: {quelle!r}")

    def steuerzeile(self, satz: str, basis: str) -> str:
        return self.steuerzeile_muster.format(satz=satz, basis=basis)

    def abzugzeile(self, grund: str) -> str:
        return self.abzugzeile_muster.format(grund=grund)


# vorläufig, Prüfung durch Steuerberatung offen (#156)
SELF_BILLING_STORNO_TITEL = {
    "de": "Stornierung der Gutschrift",
    "en": "Cancellation of self-billed invoice",
}

# Anlagen der Aufstellung (§ 8b): genau zwei Quellen, die internen Werte
# stehen im DB-CHECK der Tabelle; hier nur der sichtbare Name je Sprache.
ANLAGENQUELLEN: dict[str, dict[str, str]] = {
    "de": {
        "abrechnungsbericht": "Abrechnungsbericht",
        "zahlungsbericht": "Zahlungsbericht",
    },
    "en": {
        "abrechnungsbericht": "Settlement report",
        "zahlungsbericht": "Payment report",
    },
}

_DE = Belegdarstellung(
    code="de",
    titel_rechnung="RECHNUNG",
    titel_anzahlung="ANZAHLUNGSRECHNUNG",
    titel_storno="STORNORECHNUNG",
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
    label_positionssumme="Positionssumme",
    label_zwischensumme="Zwischensumme",
    abzugzeile_muster="Abzug: {grund}",
    label_gutschriftbetrag="Gutschriftbetrag",
    label_rechnungsbetrag="Rechnungsbetrag",
    steuerzeile_muster="zzgl. {satz} MwSt. auf {basis}",
    label_verwendungszweck="Verwendungszweck:",
    label_scan_to_pay="Zum Überweisen scannen.",
    label_ust_id="USt-IdNr.:",
    label_artikelnummer="Art.-Nr.",
    seite_muster="Seite {seite} von {gesamt}",
    label_steuernummer="Steuernummer:",
    stempel_entwurf="ENTWURF",
    fallback_gutschrift_ueberweisung=(
        "Bitte überweisen Sie den Gutschriftbetrag auf die unten genannte Bankverbindung."
    ),
    fallback_gutschrift_ohne="Gutschrift ohne Zahlungsaufforderung.",
    fallback_zahlbar="Zahlbar ohne Abzug.",
    storno_zahlungsbedingungen="Storno zur Rechnung {nummer}.",
    storno_bemerkung="Storno zur Rechnung {nummer} vom {datum}.",
    storno_gutschrift_bezug="Storno zur Gutschrift {nummer} vom {datum}.",
    ersatz_hinweis="Ersetzt Rechnung {nummer} vom {datum}.",
    hinweis_ae=AE_HINWEIS,
    hinweis_e="Kein Ausweis von Umsatzsteuer, da Kleinunternehmer gemäß § 19 UStG.",
    hinweis_k=(
        "Steuerfreie innergemeinschaftliche Lieferung gemäß § 4 Nr. 1b UStG "
        "i.V.m. § 6a UStG."
    ),
    hinweis_o="Nicht im Steuergebiet des Ausstellers steuerbar gemäß § 3a Abs. 2 UStG.",
    titel_aufstellung="ABRECHNUNGSAUFSTELLUNG",
    label_aufstellungsnummer="Aufstellungsnummer:",
    label_ausstellungsdatum="Ausstellungsdatum:",
    label_leistungsmonat="Leistungsmonat:",
    label_zahlungsnummer="Zahlungsnummer:",
    label_zahlungsdatum="Zahlungsdatum:",
    label_aussteller="Aussteller",
    label_auszahler="Auszahler",
    label_brutto="Brutto",
    label_quellensteuer="Quellensteuer",
    label_kurs="Kurs",
    label_zahlbetrag="Zahlbetrag (EUR)",
    label_anlagen="Anlagen",
    label_quelle="Quelle",
    label_dateiname="Dateiname",
    label_groesse_bytes="Größe (Bytes)",
    label_sha256="SHA-256",
    hinweis_keine_rechnung="Keine Rechnung im Sinne des § 14 UStG.",
)

_EN = Belegdarstellung(
    code="en",
    titel_rechnung="INVOICE",
    titel_anzahlung="PREPAYMENT INVOICE",
    titel_storno="CANCELLATION INVOICE",
    titel_gutschrift="SELF-BILLED INVOICE (Gutschrift)",
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
    label_positionssumme="Subtotal",
    label_zwischensumme="Subtotal",
    abzugzeile_muster="Allowance: {grund}",
    label_gutschriftbetrag="Credit note amount",
    label_rechnungsbetrag="Invoice total",
    steuerzeile_muster="plus {satz} VAT on {basis}",
    label_verwendungszweck="Reference:",
    label_scan_to_pay="Scan to pay",
    label_ust_id="VAT ID:",
    label_artikelnummer="Item no.",
    seite_muster="Page {seite} of {gesamt}",
    label_steuernummer="Tax number:",
    stempel_entwurf="DRAFT",
    fallback_gutschrift_ueberweisung=(
        "Please transfer the credit note amount to the bank account below."
    ),
    fallback_gutschrift_ohne="Credit note without payment request.",
    fallback_zahlbar="Payable without deduction.",
    storno_zahlungsbedingungen="Cancellation of invoice {nummer}.",
    storno_bemerkung="Cancellation of invoice {nummer} dated {datum}.",
    storno_gutschrift_bezug="Cancellation of self-billed invoice {nummer} of {datum}.",
    ersatz_hinweis="Replaces invoice {nummer} dated {datum}.",
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
    titel_aufstellung="SETTLEMENT STATEMENT",
    label_aufstellungsnummer="Statement number:",
    label_ausstellungsdatum="Date of issue:",
    label_leistungsmonat="Month of service:",
    label_zahlungsnummer="Payment number:",
    label_zahlungsdatum="Payment date:",
    label_aussteller="Issuer",
    label_auszahler="Payer",
    label_brutto="Gross",
    label_quellensteuer="Withholding tax",
    label_kurs="Exchange rate",
    label_zahlbetrag="Payment amount (EUR)",
    label_anlagen="Attachments",
    label_quelle="Source",
    label_dateiname="File name",
    label_groesse_bytes="Size (bytes)",
    label_sha256="SHA-256",
    hinweis_keine_rechnung=(
        "Not an invoice within the meaning of section 14 of the German VAT Act."
    ),
)

_DARSTELLUNGEN: dict[Belegsprache, Belegdarstellung] = {"de": _DE, "en": _EN}


def darstellung(sprache: Belegsprache) -> Belegdarstellung:
    """Liefert die unveraenderliche Darstellung zur Sprache (zustandslos)."""
    return _DARSTELLUNGEN[sprache]
