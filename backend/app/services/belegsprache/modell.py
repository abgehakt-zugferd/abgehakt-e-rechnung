from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.services.belegsprache.grundlagen import (
    Belegsprache,
    betrag_de,
    betrag_roh,
    dezimal_klartext,
)
from app.services.belegsprache.texte_geteilt import (
    ANLAGENQUELLEN,
    HERLEITUNGSZEILE_MUSTER,
    SELF_BILLING_STORNO_TITEL,
    SELBSTABRECHNUNG_BEZEICHNUNG,
    UNBEKANNTE_BELEGART_MELDUNG,
)


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
    # der Begriff ist nicht die Positionssumme des Belegs - in en tragen beide
    # zufaellig dasselbe Wort, in de verschiedene.
    label_zwischensumme: str
    abzugzeile_muster: str  # mit {grund}
    label_gutschriftbetrag: str
    label_rechnungsbetrag: str
    label_bereits_gezahlt: str
    label_offener_betrag: str
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
    # denn die Aufstellung ist KEINE Rechnung - keine Steuertitel, kein
    # Rechnungswortlaut, keine Fälligkeit. Der Keine-Rechnung-Satz grenzt
    # gegen § 14 UStG ab; die Zahlung ist die des Auszahlers, nicht eine
    # Forderung des Ausstellers.
    titel_storno_aufstellung: str
    label_original_aufstellung: str
    label_original_anlagen: str
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
            zahl = betrag_de(wert)
            if waehrung == "EUR":
                return f"{zahl} €"
            return f"{zahl} {waehrung}"
        return f"{waehrung} {betrag_roh(wert)}"

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
        return HERLEITUNGSZEILE_MUSTER[self.code].format(
            basis=self.format_betrag(basis, waehrung),
            satz=self.format_menge(satz),
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
            return UNBEKANNTE_BELEGART_MELDUNG[self.code].format(art=art)
        if intern == "self_billing_storno":
            return self.titel(intern)
        if intern == "self_billing":
            return SELBSTABRECHNUNG_BEZEICHNUNG[self.code]
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
        Wert wirft statt still durchzurutschen - fail-closed wie titel()."""
        try:
            return ANLAGENQUELLEN[self.code][quelle]
        except KeyError:
            raise ValueError(f"Unbekannte Anlagenquelle: {quelle!r}")

    def steuerzeile(self, satz: str, basis: str) -> str:
        return self.steuerzeile_muster.format(satz=satz, basis=basis)

    def abzugzeile(self, grund: str) -> str:
        return self.abzugzeile_muster.format(grund=grund)
