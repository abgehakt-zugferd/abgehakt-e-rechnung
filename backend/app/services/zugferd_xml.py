"""
Erzeugt ZUGFeRD 2.x CII-XML (Factur-X EN16931) aus Rechnungsdaten.
Seit 01.01.2025 hat der XML-Teil rechtlich Vorrang gegenüber dem PDF (§ 14 UStG n.F.).
Profile MINIMUM und BASIC-WL sind nicht rechtskonform – Standard: EN16931.
"""
from decimal import Decimal, ROUND_HALF_UP
from collections import defaultdict
from app.models.invoice import Invoice
from app.models.company import Company

PROFILE_IDS = {
    # ZUGFeRD 2.5 / Factur-X 1.09 (gültig ab 30.06.2026): EN16931-ID vereinfacht
    "EN16931": "urn:cen.eu:en16931:2017",
    "BASIC": "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic",
    "XRECHNUNG": "urn:cen.eu:en16931:2017#compliant#urn:xoev-de:kosit:standard:xrechnung_2.3",
}

# Rechtlich zulässige (EN16931-konforme) Profile, die dieses System rendert.
# MINIMUM und BASIC-WL sind KEINE gültige E-Rechnung (§ 14 UStG verlangt mind.
# EN16931) — sie werden NICHT still auf EN16931 gemappt, sondern hart abgelehnt.
COMPLIANT_PROFILES = frozenset(PROFILE_IDS)


class NonCompliantProfileError(ValueError):
    """Nicht-EN16931-konformes ZUGFeRD-Profil (z. B. MINIMUM, BASIC-WL) — als
    E-Rechnung unzulässig. Fail-closed statt stillem Fallback auf EN16931."""

# Ohne diesen Text ist eine Rechnung der Kategorie "E" schema-ungültig: EN16931
# verlangt über BR-E-10 zu jeder Steuergruppe "Exempt from VAT" einen Grund
# (BT-120 Text oder BT-121 Code). Fachlich verlangt § 14 Abs. 4 Nr. 8 UStG
# denselben Hinweis auf dem Beleg. Kein Eintrag hier ⇒ keine Rechnung.
EXEMPTION_REASONS = {
    "AE": "Steuerschuldnerschaft des Leistungsempfängers gemäß § 13b UStG (Reverse Charge). Die Umsatzsteuer ist vom Leistungsempfänger zu entrichten.",
    "E": "Kein Ausweis von Umsatzsteuer, da Kleinunternehmer gemäß § 19 UStG.",
    "K": "Steuerfreie innergemeinschaftliche Lieferung gemäß § 4 Nr. 1b UStG i.V.m. § 6a UStG.",
    "O": "Nicht im Steuergebiet des Ausstellers steuerbar gemäß § 3a Abs. 2 UStG.",
}

# Gutschriftverfahren (389): Kleinunternehmer ist der Beteiligte, nicht der Aussteller.
EXEMPTION_SELF_BILLING_E = (
    "Kein Ausweis von Umsatzsteuer gemäß § 19 UStG (Kleinunternehmer Beteiligung)."
)


def exemption_reason(invoice: Invoice) -> str | None:
    """Befreiungstext passend zum Belegtyp — nicht immer identisch mit EXEMPTION_REASONS."""
    cat = getattr(invoice, "tax_category", "S")
    if cat not in EXEMPTION_REASONS:
        return None
    if getattr(invoice, "invoice_type", None) == "self_billing" and cat == "E":
        return EXEMPTION_SELF_BILLING_E
    return EXEMPTION_REASONS[cat]

UN_UNIT_CODES = {
    "Stück": "C62",
    "Stunde": "HUR",
    "Stunden": "HUR",
    "Tag": "DAY",
    "Tage": "DAY",
    "Monat": "MON",
    "Monate": "MON",
    "Kilometer": "KMT",
    "Meter": "MTR",
    "kg": "KGM",
    "Liter": "LTR",
    "Pauschal": "LS",
    "Pauschale": "LS",
}


def _fmt_date(d) -> str:
    return d.strftime("%Y%m%d")


def _fmt_amount(v: Decimal) -> str:
    return str(v.quantize(Decimal("0.01"), ROUND_HALF_UP))


def _unit_code(unit: str) -> str:
    return UN_UNIT_CODES.get(unit, "C62")


def _item_tax_category(rate: Decimal, invoice_tax_category: str) -> str:
    if invoice_tax_category != "S":
        return invoice_tax_category
    return "Z" if rate == Decimal("0") else "S"


def _rate_percent_xml(rate: Decimal, tax_cat: str, indent: str) -> str:
    """BR-O-05: Kategorie O darf keinen Steuersatz (BT-152) tragen."""
    if tax_cat == "O":
        return ""
    return indent + f"<ram:RateApplicablePercent>{_fmt_amount(rate)}</ram:RateApplicablePercent>"


def _line_items_xml(invoice: Invoice) -> str:
    inv_cat = getattr(invoice, "tax_category", "S")
    parts = []
    for item in invoice.items:
        unit_code = _unit_code(item.unit)
        tax_cat = _item_tax_category(item.tax_rate, inv_cat)
        exemption_block = ""
        if inv_cat in EXEMPTION_REASONS:
            grund = exemption_reason(invoice)
            if grund:
                exemption_block = f"\n                    <ram:ExemptionReason>{_esc(grund)}</ram:ExemptionReason>"
        rate_line = _rate_percent_xml(item.tax_rate, inv_cat, "\n                    ")
        parts.append(f"""
        <ram:IncludedSupplyChainTradeLineItem>
            <ram:AssociatedDocumentLineDocument>
                <ram:LineID>{item.position}</ram:LineID>
            </ram:AssociatedDocumentLineDocument>
            <ram:SpecifiedTradeProduct>
                <ram:Name>{_esc(item.description)}</ram:Name>
            </ram:SpecifiedTradeProduct>
            <ram:SpecifiedLineTradeAgreement>
                <ram:NetPriceProductTradePrice>
                    <ram:ChargeAmount>{_fmt_amount(item.unit_price)}</ram:ChargeAmount>
                </ram:NetPriceProductTradePrice>
            </ram:SpecifiedLineTradeAgreement>
            <ram:SpecifiedLineTradeDelivery>
                <ram:BilledQuantity unitCode="{unit_code}">{str(item.quantity.quantize(Decimal("0.0001")))}</ram:BilledQuantity>
            </ram:SpecifiedLineTradeDelivery>
            <ram:SpecifiedLineTradeSettlement>
                <ram:ApplicableTradeTax>
                    <ram:TypeCode>VAT</ram:TypeCode>{exemption_block}
                    <ram:CategoryCode>{tax_cat}</ram:CategoryCode>{rate_line}
                </ram:ApplicableTradeTax>
                <ram:SpecifiedTradeSettlementLineMonetarySummation>
                    <ram:LineTotalAmount>{_fmt_amount(item.net_amount)}</ram:LineTotalAmount>
                </ram:SpecifiedTradeSettlementLineMonetarySummation>
            </ram:SpecifiedLineTradeSettlement>
        </ram:IncludedSupplyChainTradeLineItem>""")
    return "\n".join(parts)


def _tax_summaries_xml(invoice: Invoice) -> str:
    inv_cat = getattr(invoice, "tax_category", "S")
    grouped: dict[Decimal, dict] = defaultdict(lambda: {"basis": Decimal("0"), "tax": Decimal("0")})
    for item in invoice.items:
        rate = item.tax_rate
        grouped[rate]["basis"] += item.net_amount
        grouped[rate]["tax"] += item.tax_amount

    parts = []
    for rate, totals in sorted(grouped.items()):
        tax_cat = _item_tax_category(rate, inv_cat)
        exemption_block = ""
        if inv_cat in EXEMPTION_REASONS:
            grund = exemption_reason(invoice)
            if grund:
                exemption_block = f"\n                <ram:ExemptionReason>{_esc(grund)}</ram:ExemptionReason>"
        rate_line = _rate_percent_xml(rate, inv_cat, "\n                ")
        parts.append(f"""
            <ram:ApplicableTradeTax>
                <ram:CalculatedAmount>{_fmt_amount(totals['tax'])}</ram:CalculatedAmount>
                <ram:TypeCode>VAT</ram:TypeCode>{exemption_block}
                <ram:BasisAmount>{_fmt_amount(totals['basis'])}</ram:BasisAmount>
                <ram:CategoryCode>{tax_cat}</ram:CategoryCode>{rate_line}
            </ram:ApplicableTradeTax>""")
    return "\n".join(parts)


def _seller_id_xml(company: Company, tax_category: str = "S") -> str:
    """BT-29, die Verkäufer-Kennung. Steht als erstes Kind von `SellerTradeParty`
    (die CII-Sequenz ist geordnet: ID, GlobalID, Name, …).

    Warum es sie gibt: EN 16931 verlangt über `BR-CO-26` eine Verkäufer-Kennung
    (BT-29), eine Registernummer (BT-30) ODER die USt-IdNr. (BT-31). Die
    Steuernummer geht als BT-32 ins Dokument und zählt dafür NICHT. Die Einrichtung
    lässt aber ausdrücklich „Steuernummer oder USt-IdNr." zu, weil § 14 UStG das so
    vorsieht. Ohne diese Kennung konnte deshalb jemand ohne USt-IdNr. alles richtig
    ausfüllen und trotzdem keine einzige Rechnung finalisieren (Abnahme 2026-08-09).

    Nur wenn die USt-IdNr. fehlt: liegt sie vor, ist `BR-CO-26` schon erfüllt und
    eine zweite Nennung derselben Nummer wäre Beiwerk. Offengelegt wird nichts Neues,
    die Steuernummer steht nach § 14 ohnehin auf jeder Rechnung.

    Bei Kategorie O entfällt BT-31 (BR-O-02); dann muss BT-29 die Steuernummer
    tragen, auch wenn eine USt-IdNr. in der Einrichtung hinterlegt ist.
    """
    if company.vat_id and tax_category != "O":
        return ""
    if not company.tax_number:
        return ""
    return f"""
                <ram:ID>{_esc(company.tax_number)}</ram:ID>"""


def _seller_contact_xml(company: Company) -> str:
    """BG-6, der Ansprechpartner des Verkäufers (BT-41/42/43).

    Steht in der CII-Sequenz zwischen `SpecifiedLegalOrganization` und
    `PostalTradeAddress` — an anderer Stelle ist es ein Schemafehler.

    Ohne eigens gepflegten Namen tritt der Firmenname an die Stelle: BT-41 ist der
    Kontaktpunkt, nicht zwingend eine natürliche Person, und ein leeres Element
    wäre schema-ungültig. Telefon und Mail entfallen einzeln, wenn sie fehlen.
    """
    name = (company.contact_name or "").strip() or (company.name or "").strip()
    if not name:
        return ""
    teile = [f"""
                    <ram:PersonName>{_esc(name)}</ram:PersonName>"""]
    if company.phone:
        teile.append(f"""
                    <ram:TelephoneUniversalCommunication>
                        <ram:CompleteNumber>{_esc(company.phone)}</ram:CompleteNumber>
                    </ram:TelephoneUniversalCommunication>""")
    if company.email:
        teile.append(f"""
                    <ram:EmailURIUniversalCommunication>
                        <ram:URIID>{_esc(company.email)}</ram:URIID>
                    </ram:EmailURIUniversalCommunication>""")
    return f"""
                <ram:DefinedTradeContact>{''.join(teile)}
                </ram:DefinedTradeContact>"""


def _electronic_address_xml(email) -> str:
    """BT-34 (Verkäufer) bzw. BT-49 (Käufer): die elektronische Adresse, an die
    eine E-Rechnung maschinell zugestellt werden könnte.

    `schemeID="EM"` ist der EAS-Code für eine Mailadresse. Ohne Adresse entfällt
    der ganze Block: ein leeres `URIID` wäre ein Schemafehler, und die Angabe ist
    nach EN 16931 optional.

    Steht in der CII-Sequenz NACH `PostalTradeAddress` und VOR
    `SpecifiedTaxRegistration`.
    """
    if not email:
        return ""
    return f"""
                <ram:URIUniversalCommunication>
                    <ram:URIID schemeID="EM">{_esc(email)}</ram:URIID>
                </ram:URIUniversalCommunication>"""


def _buyer_reference_xml(invoice: Invoice) -> str:
    """BT-10, die Referenz des Käufers. Erstes Kind von
    `ApplicableHeaderTradeAgreement`, also VOR `SellerTradeParty`."""
    referenz = (getattr(invoice, "buyer_reference", None) or "").strip()
    if not referenz:
        return ""
    return f"""
            <ram:BuyerReference>{_esc(referenz)}</ram:BuyerReference>"""


def _seller_tax_xml(company: Company, tax_category: str) -> str:
    parts = []
    if company.tax_number:
        parts.append(f"""
                <ram:SpecifiedTaxRegistration>
                    <ram:ID schemeID="FC">{_esc(company.tax_number)}</ram:ID>
                </ram:SpecifiedTaxRegistration>""")
    # BR-O-02: bei Kategorie O keine Verkaeufer-USt-IdNr. (BT-31).
    if company.vat_id and tax_category != "O":
        parts.append(f"""
                <ram:SpecifiedTaxRegistration>
                    <ram:ID schemeID="VA">{_esc(company.vat_id)}</ram:ID>
                </ram:SpecifiedTaxRegistration>""")
    return "\n".join(parts)


def _buyer_vat_xml(customer, tax_category: str) -> str:
    if tax_category == "O":
        return ""
    if customer and customer.vat_id:
        return f"""
                <ram:SpecifiedTaxRegistration>
                    <ram:ID schemeID="VA">{_esc(customer.vat_id)}</ram:ID>
                </ram:SpecifiedTaxRegistration>"""
    return ""


def _payment_means_xml(company: Company) -> str:
    if not company.bank_iban:
        return ""
    bic_block = ""
    if company.bank_bic:
        bic_block = f"""
                <ram:PayeeSpecifiedCreditorFinancialInstitution>
                    <ram:BICID>{_esc(company.bank_bic)}</ram:BICID>
                </ram:PayeeSpecifiedCreditorFinancialInstitution>"""
    return f"""
            <ram:SpecifiedTradeSettlementPaymentMeans>
                <ram:TypeCode>58</ram:TypeCode>
                <ram:PayeePartyCreditorFinancialAccount>
                    <ram:IBANID>{_esc(company.bank_iban)}</ram:IBANID>
                </ram:PayeePartyCreditorFinancialAccount>{bic_block}
            </ram:SpecifiedTradeSettlementPaymentMeans>"""


def _payment_terms_xml(invoice: Invoice) -> str:
    """Gutschrift ohne Fälligkeit: keine Zahlungsaufforderung in der XML (#48)."""
    text = invoice.payment_terms or "Zahlbar ohne Abzug."
    if invoice.invoice_type == "credit_note":
        return f"""
            <ram:SpecifiedTradePaymentTerms>
                <ram:Description>{_esc(text)}</ram:Description>
            </ram:SpecifiedTradePaymentTerms>"""
    return f"""
            <ram:SpecifiedTradePaymentTerms>
                <ram:Description>{_esc(text)}</ram:Description>
                <ram:DueDateDateTime>
                    <udt:DateTimeString format="102">{_fmt_date(invoice.due_date)}</udt:DateTimeString>
                </ram:DueDateDateTime>
            </ram:SpecifiedTradePaymentTerms>"""


def _settlement_payment_xml(invoice: Invoice, company: Company) -> str:
    if invoice.invoice_type == "credit_note":
        return ""
    return _payment_means_xml(company)


def _esc(text: str | None) -> str:
    if not text:
        return ""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _delivery_xml(invoice: Invoice) -> str:
    inv_cat = getattr(invoice, "tax_category", "S")
    customer = invoice.customer
    ship_to = ""
    if inv_cat == "K" and customer:
        # BR-IC-12: ig. Lieferung braucht Lieferland (BT-80).
        ship_to = f"""
            <ram:ShipToTradeParty>
                <ram:PostalTradeAddress>
                    <ram:CountryID>{_esc(customer.country)}</ram:CountryID>
                </ram:PostalTradeAddress>
            </ram:ShipToTradeParty>"""
    # Der Block bleibt auch dann stehen, wenn nichts darin steht: das CII-Schema
    # verlangt <ram:ApplicableHeaderTradeDelivery> zwischen Agreement und
    # Settlement. Fehlte er, war die Datei schon am Schema unzulässig, nicht erst
    # an einer Geschäftsregel. Getroffen hat das die Kleinbetragsrechnung ohne
    # Leistungsdatum, die § 33 UStDV ausdrücklich erlaubt (#47).
    delivery_event = ""
    if invoice.delivery_date:
        delivery_event = f"""
            <ram:ActualDeliverySupplyChainEvent>
                <ram:OccurrenceDateTime>
                    <udt:DateTimeString format="102">{_fmt_date(invoice.delivery_date)}</udt:DateTimeString>
                </ram:OccurrenceDateTime>
            </ram:ActualDeliverySupplyChainEvent>"""
    return f"""
        <ram:ApplicableHeaderTradeDelivery>{ship_to}{delivery_event}
        </ram:ApplicableHeaderTradeDelivery>"""


def _reference_xml(invoice: Invoice) -> str:
    """
    P5: BG-3 – Referenz auf die vorausgegangene Rechnung (Stornorechnung/Gutschrift).

    Gem. EN16931 / UN-CEFACT CII trägt die Referenz auf eine vorausgegangene Rechnung
    das Element <ram:InvoiceReferencedDocument> (BT-25 Rechnungsnummer, BT-26 Datum) und
    steht in <ram:ApplicableHeaderTradeSettlement> NACH der Monetary Summation.

    Wichtig: NICHT BuyerOrderReferencedDocument verwenden – das ist BT-13 (Bestellnummer);
    ein konformer Empfänger (DATEV) würde die Originalrechnungsnummer sonst als Bestellnummer
    interpretieren und das Matching Storno↔Original bräche.

    Der TypeCode (BT-3) der Storno-/Gutschriftrechnung wird separat über _get_type_code
    auf 381 gesetzt.
    """
    if not invoice.original_invoice_id:
        return ""

    original = invoice.original_invoice
    if not original:
        return ""

    return f"""
            <ram:InvoiceReferencedDocument>
                <ram:IssuerAssignedID>{_esc(original.invoice_number)}</ram:IssuerAssignedID>
                <ram:FormattedIssueDateTime>
                    <qdt:DateTimeString format="102">{_fmt_date(original.issue_date)}</qdt:DateTimeString>
                </ram:FormattedIssueDateTime>
            </ram:InvoiceReferencedDocument>"""


def _notes_xml(invoice: Invoice) -> str:
    if not invoice.notes:
        return ""
    return f"""
        <ram:IncludedNote>
            <ram:Content>{_esc(invoice.notes)}</ram:Content>
        </ram:IncludedNote>"""


# P7: Zuordnung Rechnungstyp → ZUGFeRD/UN-CEFACT TypeCode. EINZIGE Quelle der Wahrheit,
# von zugferd_xml UND validator genutzt (Konsistenz-Guard).
# 380=Rechnung, 381=Gutschrift/Storno, 384=Rechnungskorrektur, 389=Gutschrift im Gutschriftverfahren.
TYPE_CODE_MAP: dict[str | None, str] = {
    None: "380",  # Standard (kein invoice_type gesetzt)
    "standard": "380",
    "invoice": "380",
    "credit_note": "381",
    "credit": "381",
    "storno": "381",
    "correction": "384",
    "self_billing": "389",
    "self-billing": "389",
}


class UnknownInvoiceTypeError(ValueError):
    """invoice_type ist weder None noch ein bekannter Typ — fail-closed statt stillem
    Fallback auf 380 (Standardrechnung), der einen Storno/Korrektur mislabeln würde."""


def _get_type_code(invoice: Invoice) -> str:
    """Gibt den ZUGFeRD TypeCode (BT-3) für invoice.invoice_type zurück.

    Fail-closed (#98 E10): ein unbekannter Typ wird NICHT still auf 380 gemappt —
    sonst trüge die XML einen falschen Dokumenttyp (z. B. ein vertippter Storno als
    Standardrechnung). None = kein Typ gesetzt = 380 (legitimer Default). Der Validator
    (INVOICE_TYPE_INVALID) blockt zusätzlich die Finalisierung.
    """
    if invoice.invoice_type not in TYPE_CODE_MAP:
        raise UnknownInvoiceTypeError(
            f"Unbekannter Rechnungstyp {invoice.invoice_type!r}. "
            f"Erlaubt: {', '.join(sorted(k for k in TYPE_CODE_MAP if k))} (oder None)."
        )
    return TYPE_CODE_MAP[invoice.invoice_type]


def generate_xml(invoice: Invoice, company: Company) -> str:
    # Fail-closed (#98 E4): ein nicht-EN16931-konformes Profil (MINIMUM, BASIC-WL,
    # Tippfehler) wird NICHT still auf EN16931 gemappt — sonst trüge die XML eine
    # EN16931-Profil-ID über nicht-konformem Inhalt. Kein Codepfad darf eine als
    # E-Rechnung unzulässige XML erzeugen.
    # None/leer = Modell-Default (Spalte `zugferd_profile`: nullable=False, default
    # "EN16931") → als EN16931 behandeln. Nur ein EXPLIZIT nicht-konformes Profil
    # (MINIMUM/BASIC-WL, Tippfehler) wird abgelehnt statt still auf EN16931 gemappt.
    profile = invoice.zugferd_profile or "EN16931"
    if profile not in PROFILE_IDS:
        raise NonCompliantProfileError(
            f"ZUGFeRD-Profil {invoice.zugferd_profile!r} ist als E-Rechnung unzulässig "
            f"(§ 14 UStG verlangt mind. EN16931; MINIMUM/BASIC-WL sind nicht rechtskonform). "
            f"Erlaubt: {', '.join(sorted(PROFILE_IDS))}."
        )
    profile_id = PROFILE_IDS[profile]
    customer = invoice.customer
    inv_cat = getattr(invoice, "tax_category", "S")

    addr2_buyer = (f"\n                    <ram:LineTwo>{_esc(customer.address_line2)}</ram:LineTwo>"
                   if customer and customer.address_line2 else "")
    addr2_seller = (f"\n                    <ram:LineTwo>{_esc(company.address_line2)}</ram:LineTwo>"
                    if company.address_line2 else "")

    # P7: TypeCode dynamisch basierend auf invoice_type
    type_code = _get_type_code(invoice)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rsm:CrossIndustryInvoice
    xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"
    xmlns:qdt="urn:un:unece:uncefact:data:standard:QualifiedDataType:100"
    xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
    xmlns:xs="http://www.w3.org/2001/XMLSchema"
    xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">

    <rsm:ExchangedDocumentContext>
        <ram:GuidelineSpecifiedDocumentContextParameter>
            <ram:ID>{profile_id}</ram:ID>
        </ram:GuidelineSpecifiedDocumentContextParameter>
    </rsm:ExchangedDocumentContext>

    <rsm:ExchangedDocument>
        <ram:ID>{_esc(invoice.invoice_number)}</ram:ID>
        <ram:TypeCode>{type_code}</ram:TypeCode>
        <ram:IssueDateTime>
            <udt:DateTimeString format="102">{_fmt_date(invoice.issue_date)}</udt:DateTimeString>
        </ram:IssueDateTime>{_notes_xml(invoice)}
    </rsm:ExchangedDocument>

    <rsm:SupplyChainTradeTransaction>
{_line_items_xml(invoice)}
        <ram:ApplicableHeaderTradeAgreement>{_buyer_reference_xml(invoice)}
            <ram:SellerTradeParty>{_seller_id_xml(company, inv_cat)}
                <ram:Name>{_esc(company.name)}</ram:Name>{_seller_contact_xml(company)}
                <ram:PostalTradeAddress>
                    <ram:PostcodeCode>{_esc(company.zip_code)}</ram:PostcodeCode>
                    <ram:LineOne>{_esc(company.address_line1)}</ram:LineOne>{addr2_seller}
                    <ram:CityName>{_esc(company.city)}</ram:CityName>
                    <ram:CountryID>{_esc(company.country)}</ram:CountryID>
                </ram:PostalTradeAddress>{_electronic_address_xml(company.email)}{_seller_tax_xml(company, inv_cat)}
            </ram:SellerTradeParty>
            <ram:BuyerTradeParty>
                <ram:Name>{_esc(customer.name if customer else "")}</ram:Name>
                <ram:PostalTradeAddress>
                    <ram:PostcodeCode>{_esc(customer.zip_code if customer else "")}</ram:PostcodeCode>
                    <ram:LineOne>{_esc(customer.address_line1 if customer else "")}</ram:LineOne>{addr2_buyer}
                    <ram:CityName>{_esc(customer.city if customer else "")}</ram:CityName>
                    <ram:CountryID>{_esc(customer.country if customer else "DE")}</ram:CountryID>
                </ram:PostalTradeAddress>{_electronic_address_xml(customer.email if customer else None)}{_buyer_vat_xml(customer, inv_cat)}
            </ram:BuyerTradeParty>
        </ram:ApplicableHeaderTradeAgreement>
{_delivery_xml(invoice)}
        <ram:ApplicableHeaderTradeSettlement>
            <ram:PaymentReference>{_esc(invoice.invoice_number)}</ram:PaymentReference>
            <ram:InvoiceCurrencyCode>{_esc(invoice.currency)}</ram:InvoiceCurrencyCode>
{_settlement_payment_xml(invoice, company)}
{_tax_summaries_xml(invoice)}
{_payment_terms_xml(invoice)}
            <ram:SpecifiedTradeSettlementHeaderMonetarySummation>
                <ram:LineTotalAmount>{_fmt_amount(invoice.net_total)}</ram:LineTotalAmount>
                <ram:TaxBasisTotalAmount>{_fmt_amount(invoice.net_total)}</ram:TaxBasisTotalAmount>
                <ram:TaxTotalAmount currencyID="{_esc(invoice.currency)}">{_fmt_amount(invoice.tax_total)}</ram:TaxTotalAmount>
                <ram:GrandTotalAmount>{_fmt_amount(invoice.gross_total)}</ram:GrandTotalAmount>
                <ram:DuePayableAmount>{_fmt_amount(invoice.gross_total)}</ram:DuePayableAmount>
            </ram:SpecifiedTradeSettlementHeaderMonetarySummation>{_reference_xml(invoice)}
        </ram:ApplicableHeaderTradeSettlement>
    </rsm:SupplyChainTradeTransaction>
</rsm:CrossIndustryInvoice>"""
    return xml
