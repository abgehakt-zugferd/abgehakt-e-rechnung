"""
Regelbasierte Rechnungsprüfung nach § 14 UStG und ZUGFeRD EN16931-Anforderungen.

Bewusst regelbasiert und nachlesbar: jede Meldung lässt sich auf eine Zeile in
diesem Modul und von dort auf eine Vorschrift zurückführen. Eine Prüfung, deren
Begründung niemand nachvollziehen kann, ist in einem Steuerkontext wertlos.
"""
from decimal import Decimal, ROUND_HALF_UP
from dataclasses import dataclass
from app.services.leistungszeit import (
    hat_leistungszeitpunkt,
    leistungszeitraum_teilweise,
    leistungszeitraum_ungueltig,
)
from app.models.invoice import Invoice
from app.models.company import Company
from app.services.zugferd_xml import TYPE_CODE_MAP, COMPLIANT_PROFILES


VALID_TAX_RATES = {Decimal("0"), Decimal("7"), Decimal("19")}
SIMPLIFIED_INVOICE_THRESHOLD = Decimal("250")  # § 33 UStDV
# "E" ist seit #152 gültig und meint hier genau einen Fall: den Kleinunternehmer
# nach § 19 UStG. Der Befreiungsgrund in EXEMPTION_REASONS nennt § 19 ausdrücklich,
# und wer eine andere Befreiung nach § 4 UStG braucht (Heilbehandlung, Versicherung),
# bekäme mit diesem Text eine falsche Begründung auf den Beleg. Solche Fälle daher
# erst aufnehmen, wenn der Grund pro Rechnung wählbar ist — nicht heimlich mitnutzen.
#
# Weiterhin NICHT gültig: "G" (Ausfuhr Drittland). Inländische 0 %-Umsätze bleiben
# "Z" (steuerpflichtig zum Satz null), das ist etwas anderes als steuerbefreit.
VALID_TAX_CATEGORIES = {"S", "AE", "K", "O", "E"}
# Kategorien, in denen keine Steuer ausgewiesen werden darf. Bei "E" ist das keine
# Formalie: ein Kleinunternehmer, der Umsatzsteuer ausweist, schuldet sie nach
# § 14c Abs. 2 UStG, obwohl er sie gar nicht erheben durfte.
STEUERFREIE_KATEGORIEN = {"AE", "K", "O", "E"}


@dataclass
class Issue:
    code: str
    severity: str  # error | warning | info
    message: str
    field: str | None = None


def _ust_id_validator_issues(
    entity,
    errors: list[Issue],
    warnings: list[Issue],
    prefix: str,
    field: str,
) -> None:
    """VIES-Pruefstand aus Kunde/Firma in Validator-Meldungen."""
    checked = getattr(entity, "vat_id_checked_at", None)
    valid = getattr(entity, "vat_id_check_valid", None)
    name_match = getattr(entity, "vat_id_name_match", None)
    if not checked:
        warnings.append(Issue(
            f"{prefix}_VAT_ID_NOT_CHECKED", "warning",
            "USt-IdNr. wurde noch nicht bei VIES geprueft.",
            field,
        ))
        return
    if valid is None:
        warnings.append(Issue(
            f"{prefix}_VAT_ID_VIES_UNAVAILABLE", "warning",
            "VIES war beim letzten Pruefversuch nicht erreichbar; Gueltigkeit unbekannt.",
            field,
        ))
        return
    if valid is False:
        errors.append(Issue(
            f"{prefix}_VAT_ID_VIES_INVALID", "error",
            "USt-IdNr. ist bei VIES als ungueltig oder nicht registriert gemeldet.",
            field,
        ))
    if name_match == "weicht_ab":
        if prefix == "BUYER":
            kundenname = (getattr(entity, "name", None) or "").strip()
            vies_name = (getattr(entity, "vat_id_vies_name", None) or "").strip()
            # Abgleich ohne hinterlegten Namen oder ohne VIES-Namen: nur im Kundenstamm.
            if not kundenname or not vies_name:
                return
        warnings.append(Issue(
            f"{prefix}_VAT_ID_NAME_MISMATCH", "warning",
            "Der bei VIES registrierte Name weicht vom hinterlegten Namen ab.",
            field,
        ))


def validate_invoice(invoice: Invoice, company: Company) -> tuple[list[Issue], list[Issue]]:
    errors: list[Issue] = []
    warnings: list[Issue] = []

    gross = invoice.gross_total
    tax_category = getattr(invoice, "tax_category", "S")
    # „nicht uebersteigt" (§ 33 UStDV) heisst bis EINSCHLIESSLICH 250 €. Mit `<`
    # verlangte die Pruefung bei genau 250,00 € brutto ein Leistungsdatum und wies
    # die Finalisierung ab, fuer eine Rechnung, die das Gesetz davon befreit (#23).
    simplified = gross <= SIMPLIFIED_INVOICE_THRESHOLD

    # ZUGFeRD-Profil muss EN16931-konform sein (§ 14 UStG). MINIMUM/BASIC-WL sind
    # nicht rechtskonform und werden NICHT als E-Rechnung akzeptiert (#98 E4) —
    # harter Fehler, damit das Finalize-Gate fail-closed 400 statt 500 liefert.
    # None/leer = Modell-Default EN16931 (Spalte nullable=False) → kein Fehler.
    if (invoice.zugferd_profile or "EN16931") not in COMPLIANT_PROFILES:
        errors.append(Issue(
            "PROFILE_NOT_COMPLIANT", "error",
            f"ZUGFeRD-Profil '{invoice.zugferd_profile}' ist als E-Rechnung unzulässig "
            f"(mind. EN16931 erforderlich; MINIMUM/BASIC-WL sind nicht rechtskonform). "
            f"Erlaubt: {', '.join(sorted(COMPLIANT_PROFILES))}.",
            "zugferd_profile",
        ))

    # § 14 Abs. 4 UStG – Pflichtangaben Leistungserbringer
    if not company.name or not company.name.strip():
        errors.append(Issue("SELLER_NAME_MISSING", "error", "Firmenname fehlt in den Einstellungen.", "company.name"))
    if not company.address_line1 or not company.zip_code or not company.city:
        errors.append(Issue("SELLER_ADDRESS_MISSING", "error", "Vollständige Adresse des Leistungserbringers fehlt.", "company.address"))
    if not company.tax_number and not company.vat_id:
        errors.append(Issue("SELLER_TAX_ID_MISSING", "error", "Steuernummer oder USt-IdNr. des Leistungserbringers fehlt (§ 14 Abs. 4 Nr. 2 UStG).", "company.tax"))
    elif tax_category == "O" and not company.tax_number:
        errors.append(Issue(
            "SELLER_TAX_NUMBER_REQUIRED_FOR_O", "error",
            "Bei Steuerbefreiung nach § 4 Nr. 21 UStG (Kategorie O) muss die Steuernummer "
            "in den Einstellungen hinterlegt sein (EN16931 BR-CO-26). Die USt-IdNr. allein "
            "genügt hier nicht.",
            "company.tax_number",
        ))
    if company.vat_id:
        _ust_id_validator_issues(
            company,
            errors,
            warnings,
            prefix="SELLER",
            field="company.vat_id",
        )

    # § 14 Abs. 4 Nr. 1 UStG – Leistungsempfänger
    customer = invoice.customer
    if not customer:
        errors.append(Issue("BUYER_MISSING", "error", "Kein Kunde zugeordnet.", "customer_id"))
    else:
        if not customer.name or not customer.name.strip():
            errors.append(Issue("BUYER_NAME_MISSING", "error", "Name des Kunden fehlt.", "customer.name"))
        if not customer.address_line1 or not customer.zip_code or not customer.city:
            errors.append(Issue("BUYER_ADDRESS_MISSING", "error", "Vollständige Adresse des Kunden fehlt.", "customer.address"))

        # Hoher Rechnungsbetrag ohne USt-IdNr. des Empfängers → Hinweis (kein harter Fehler).
        # § 14a Abs. 1 UStG verlangt die USt-IdNr. des Empfängers nur bei Leistungen i.S.d.
        # § 3a Abs. 2 UStG (grenzüberschreitend/Reverse Charge, s. Kategorien AE/K weiter unten),
        # nicht generell bei inländischen B2B-Rechnungen über 10.000 €. Eine inländische Rechnung
        # über 10.000 € an einen Kunden ohne USt-IdNr. ist zulässig und darf nicht blockiert werden.
        if gross > Decimal("10000") and not customer.vat_id:
            warnings.append(Issue(
                "HIGH_VALUE_NO_BUYER_VAT_ID", "warning",
                f"Rechnungsbetrag {gross:.2f} € übersteigt 10.000 €. "
                f"Bei B2B-Geschäften wird die Angabe der USt-IdNr. des Leistungsempfängers empfohlen.",
                "customer.vat_id"
            ))
        if customer.vat_id:
            _ust_id_validator_issues(
                customer,
                errors,
                warnings,
                prefix="BUYER",
                field="customer.vat_id",
            )

    # § 14 Abs. 4 Nr. 4 UStG – Rechnungsnummer
    if not invoice.invoice_number:
        errors.append(Issue("INVOICE_NUMBER_MISSING", "error", "Rechnungsnummer fehlt.", "invoice_number"))

    # § 14 Abs. 4 Nr. 3 UStG – Ausstellungsdatum
    if not invoice.issue_date:
        errors.append(Issue("ISSUE_DATE_MISSING", "error", "Ausstellungsdatum fehlt.", "issue_date"))

    # Fälligkeitsdatum logisch prüfen
    if invoice.issue_date and invoice.due_date and invoice.due_date < invoice.issue_date:
        errors.append(Issue("DUE_DATE_BEFORE_ISSUE", "error", "Fälligkeitsdatum liegt vor dem Ausstellungsdatum.", "due_date"))

    # § 14 Abs. 4 Nr. 6 UStG – Leistungsdatum. Produktentscheid #98 E7 (2026-07-23):
    # harter Gate statt Warnung. Bei Nicht-Kleinbetragsrechnungen (über 250 €) ist der
    # Leistungszeitpunkt zwingend — fehlt er, blockiert das Finalize-Gate (400).
    # Kleinbetrag (bis 250 € einschließlich, § 33 UStDV) bleibt ausgenommen.
    #
    # Bei innergemeinschaftlicher Lieferung (Kategorie K) gilt die
    # Kleinbetragsausnahme NICHT: EN16931 verlangt über BR-IC-11 das Lieferdatum
    # (BT-72) oder einen Abrechnungszeitraum, unabhängig vom Betrag. § 33 UStDV
    # erlässt nur die nationale Pflichtangabe, die europäische Norm gilt daneben
    # weiter. Ohne diese Zeile kam der Beleg am Gate vorbei und scheiterte danach
    # an Mustang, mit einer Meldung aus dem Werkzeug statt einer aus der
    # Anwendung (#47).
    innergemeinschaftlich = tax_category == "K"
    if leistungszeitraum_teilweise(invoice):
        errors.append(Issue(
            "SERVICE_PERIOD_INCOMPLETE", "error",
            "Leistungszeitraum unvollständig: von- und bis-Datum müssen beide gesetzt sein.",
            "service_period",
        ))
    if leistungszeitraum_ungueltig(invoice):
        errors.append(Issue(
            "SERVICE_PERIOD_INVALID", "error",
            "Leistungszeitraum ungültig: das von-Datum liegt nach dem bis-Datum.",
            "service_period",
        ))
    if not hat_leistungszeitpunkt(invoice) and (not simplified or innergemeinschaftlich):
        errors.append(Issue(
            "DELIVERY_DATE_MISSING", "error",
            "Zeitpunkt der Leistungserbringung fehlt. Bei einer innergemeinschaftlichen "
            "Lieferung ist er unabhängig vom Rechnungsbetrag zwingend (EN16931, BR-IC-11); "
            "die Kleinbetragsregelung des § 33 UStDV gilt dafür nicht."
            if innergemeinschaftlich else
            "Zeitpunkt der Leistungserbringung fehlt (§ 14 Abs. 4 Nr. 6 UStG) — bei Rechnungen über 250 € zwingend erforderlich.",
            "delivery_date"
        ))

    # § 14 Abs. 4 Nr. 5 UStG – Leistungsbeschreibung und Positionen
    if not invoice.items:
        errors.append(Issue("NO_ITEMS", "error", "Keine Rechnungspositionen vorhanden.", "items"))
    else:
        for item in invoice.items:
            if not item.description or not item.description.strip():
                errors.append(Issue(
                    "ITEM_DESCRIPTION_MISSING", "error",
                    f"Position {item.position}: Leistungsbeschreibung fehlt.", f"items[{item.position}].description"
                ))
            if item.quantity <= 0:
                errors.append(Issue(
                    "ITEM_QUANTITY_INVALID", "error",
                    f"Position {item.position}: Menge muss größer als 0 sein.", f"items[{item.position}].quantity"
                ))
            if item.unit_price < 0:
                errors.append(Issue(
                    "ITEM_PRICE_NEGATIVE", "error",
                    f"Position {item.position}: Negativer Einzelpreis ist nicht erlaubt.", f"items[{item.position}].unit_price"
                ))
            rate = item.tax_rate.quantize(Decimal("0"))
            if rate not in VALID_TAX_RATES:
                errors.append(Issue(
                    "TAX_RATE_INVALID", "error",
                    f"Position {item.position}: Steuersatz {item.tax_rate}% ist ungültig. Erlaubt: 0%, 7%, 19%.",
                    f"items[{item.position}].tax_rate"
                ))

            # Betragsprüfung je Position
            expected_net = (item.quantity * item.unit_price).quantize(Decimal("0.01"), ROUND_HALF_UP)
            if abs(item.net_amount - expected_net) > Decimal("0.02"):
                errors.append(Issue(
                    "ITEM_AMOUNT_MISMATCH", "error",
                    f"Position {item.position}: Nettobetrag {item.net_amount} stimmt nicht (erwartet {expected_net}).",
                    f"items[{item.position}].net_amount"
                ))
            expected_tax = (item.net_amount * item.tax_rate / 100).quantize(Decimal("0.01"), ROUND_HALF_UP)
            if abs(item.tax_amount - expected_tax) > Decimal("0.02"):
                errors.append(Issue(
                    "ITEM_TAX_MISMATCH", "error",
                    f"Position {item.position}: Steuerbetrag {item.tax_amount} stimmt nicht (erwartet {expected_tax}).",
                    f"items[{item.position}].tax_amount"
                ))

    # Gesamtbeträge prüfen
    if invoice.items:
        expected_net_total = sum(i.net_amount for i in invoice.items).quantize(Decimal("0.01"), ROUND_HALF_UP)
        expected_tax_total = sum(i.tax_amount for i in invoice.items).quantize(Decimal("0.01"), ROUND_HALF_UP)
        expected_gross = (expected_net_total + expected_tax_total).quantize(Decimal("0.01"), ROUND_HALF_UP)

        if abs(invoice.net_total - expected_net_total) > Decimal("0.02"):
            errors.append(Issue("NET_TOTAL_MISMATCH", "error", f"Nettosumme {invoice.net_total} stimmt nicht (erwartet {expected_net_total}).", "net_total"))
        if abs(invoice.tax_total - expected_tax_total) > Decimal("0.02"):
            errors.append(Issue("TAX_TOTAL_MISMATCH", "error", f"Steuersumme {invoice.tax_total} stimmt nicht (erwartet {expected_tax_total}).", "tax_total"))
        if abs(invoice.gross_total - expected_gross) > Decimal("0.02"):
            errors.append(Issue("GROSS_TOTAL_MISMATCH", "error", f"Bruttosumme {invoice.gross_total} stimmt nicht (erwartet {expected_gross}).", "gross_total"))

    # MwSt.-Kategorie prüfen
    if tax_category not in VALID_TAX_CATEGORIES:
        errors.append(Issue(
            "TAX_CATEGORY_INVALID", "error",
            "Unbekannte MwSt.-Kategorie.", "tax_category"
        ))
    elif tax_category in STEUERFREIE_KATEGORIEN:
        if invoice.items and any(item.tax_rate > Decimal("0") for item in invoice.items):
            meldung = (
                "Als Kleinunternehmer nach § 19 UStG dürfen Sie keine Umsatzsteuer "
                "ausweisen. Ausgewiesene Steuer schulden Sie nach § 14c Abs. 2 UStG "
                "trotzdem. Steuersatz auf 0 % setzen."
                if tax_category == "E" else
                "Bei Reverse Charge / steuerfreien Lieferungen muss der Steuersatz 0 % betragen."
            )
            errors.append(Issue(
                "TAX_CATEGORY_RATE_MISMATCH", "error", meldung, "tax_category"
            ))
        if tax_category in {"AE", "K"} and customer and not customer.vat_id:
            errors.append(Issue(
                "BUYER_VAT_ID_REQUIRED", "error",
                "Für Reverse Charge und innergemeinschaftliche Lieferungen ist die USt-IdNr. des Käufers Pflicht.",
                "customer.vat_id"
            ))

    # Konsistenz Rechnungstyp ↔ Originalbezug (ROADMAP Punkt 3).
    # invoice_type muss bekannt sein; Gutschrift/Storno/Korrektur (TypeCode != 380)
    # verlangen eine Originalreferenz, eine Standardrechnung (380/None) darf keine haben.
    invoice_type = getattr(invoice, "invoice_type", None)
    original_ref = getattr(invoice, "original_invoice_id", None)
    if invoice_type not in TYPE_CODE_MAP:
        errors.append(Issue(
            "INVOICE_TYPE_INVALID", "error",
            f"Unbekannter Rechnungstyp '{invoice_type}'. "
            f"Erlaubt: {', '.join(str(t) for t in TYPE_CODE_MAP if t)}.",
            "invoice_type"
        ))
    else:
        requires_reference = TYPE_CODE_MAP[invoice_type] != "380"
        if requires_reference and not original_ref:
            errors.append(Issue(
                "ORIGINAL_INVOICE_REQUIRED", "error",
                "Gutschrift/Storno/Korrektur muss die Originalrechnung referenzieren "
                "(original_invoice_id fehlt).",
                "original_invoice_id"
            ))
        if not requires_reference and original_ref:
            errors.append(Issue(
                "ORIGINAL_INVOICE_NOT_ALLOWED", "error",
                "Eine Standardrechnung darf keine Originalrechnung referenzieren.",
                "original_invoice_id"
            ))

    # Eine Gutschrift spiegelt ihr Original betragsgleich (#8). `build_storno`
    # kopiert die Summen 1:1, und die Bearbeitungsseite ist für Gutschriften
    # gesperrt — diese Prüfung ist die zweite Schicht davor, so wie die Wächter in
    # der Anwendung und die Auslöser in der Datenbank zwei Schichten derselben
    # Zusage sind. Sie steht hier, weil das Finalisieren fail-closed ist: was den
    # Validator passiert, wandert unwiderruflich ins Archiv.
    #
    # OHNE Toleranz, anders als bei den Positionssummen. Dort wird gerechnet und
    # gerundet, hier wird kopiert; jede Abweichung ist eine Eingabe, keine
    # Rundung. Eine Toleranz ließe genau die Tür offen, die diese Regel schließt.
    #
    # `original_invoice` fehlt bei Testattrappen und bei einer noch nicht
    # geladenen Beziehung; dann greift die Regel nicht. Die Referenz als solche
    # verlangt bereits ORIGINAL_INVOICE_REQUIRED oben.
    if invoice_type == "credit_note":
        original = getattr(invoice, "original_invoice", None)
        if original is not None:
            for feld, bezeichnung in (("net_total", "Nettobetrag"),
                                      ("tax_total", "Steuerbetrag"),
                                      ("gross_total", "Bruttobetrag")):
                if getattr(invoice, feld, None) != getattr(original, feld, None):
                    errors.append(Issue(
                        "STORNO_AMOUNT_MISMATCH", "error",
                        f"{bezeichnung} der Gutschrift weicht von der Originalrechnung "
                        f"{original.invoice_number} ab "
                        f"({getattr(invoice, feld, None)} statt {getattr(original, feld, None)}). "
                        "Eine Stornierung hebt den Beleg vollständig auf; eine "
                        "abweichende Summe wäre eine Teilkorrektur und braucht einen "
                        "eigenen Beleg.",
                        feld
                    ))

    # Empfehlungen
    if not invoice.payment_terms:
        warnings.append(Issue("NO_PAYMENT_TERMS", "warning", "Zahlungsbedingungen fehlen (empfohlen).", "payment_terms"))
    if company and not company.bank_iban and not _gutschrift_auszahlung(invoice):
        warnings.append(Issue("NO_BANK_DETAILS", "warning", "Bankverbindung in den Einstellungen nicht hinterlegt (empfohlen für SEPA-Zahlungen).", "company.bank_iban"))
    if _gutschrift_auszahlung(invoice) and invoice.customer and not invoice.customer.bank_iban:
        warnings.append(Issue(
            "CUSTOMER_BANK_MISSING", "warning",
            "Bankverbindung des Kunden fehlt (IBAN für Gutschrift-Auszahlung und EPC-QR empfohlen).",
            "customer.bank_iban",
        ))

    return errors, warnings


def _gutschrift_auszahlung(invoice: Invoice) -> bool:
    return getattr(invoice, "invoice_type", None) in {
        "credit_note", "credit", "storno", "self_billing",
    }
