"""Tests für ZUGFeRD 2.5 / Factur-X 1.09 XML-Generierung (EN16931-Profil).

⚠️ SCOPE (#98 E5): Diese Datei prüft **fachliche WERTE** per XPath (TypeCode 381,
Kategorie Z/AE, BasisAmount == 200.00, schemeID FC/VA, Aggregations-COUNTs …) — Dinge,
die eine Schema-Validierung NICHT abdeckt. Sie prüft bewusst **nicht** die strukturelle
Gültigkeit (Element-REIHENFOLGE, Namespaces, Datentypen): XPath-`find()` ist ordnungs-
blind, ein Substring-Match sieht keine Sequenzfehler. Der reale PostcodeCode-vor-LineOne-
Bug (Mustang type 18) blieb hier unsichtbar. Die **einzige harte Strukturprüfung** ist
`test_zugferd_xml_schema.py` (Mustang/XSD). **Keine neuen Struktur-/Gültigkeits-Tests hier
hinzufügen** — sie geben falsche Sicherheit; Struktur gehört in den Schema-Test.

Abgedeckte Spec-Regeln (Werte):
  BR-2 (Rechnungsnummer), BR-3 (Datum YYYYMMDD), BR-4 (TypeCode),
  BR-10 (Verkäufername), BR-15 (Käufername), BR-16 (Betragsberechnung),
  BR-22 (Menge), BR-25 (Zeilenbetrag), BR-54 (MwSt.-Kategorie-Codes),
  BR-65 (Steuerberechnung), BT-24 (Profile-ID Factur-X 1.09).
"""
import pytest
from decimal import Decimal
from datetime import date
from types import SimpleNamespace
import xml.etree.ElementTree as ET

from app.services.zugferd_xml import (
    generate_xml, PROFILE_IDS, NonCompliantProfileError, UnknownInvoiceTypeError,
)
from tests.factories import (
    company_stub as _company,
    customer_stub as _customer,
    item_stub as _item,
    zugferd_invoice_stub as _invoice,
)

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
    "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
    "qdt": "urn:un:unece:uncefact:data:standard:QualifiedDataType:100",
}


def _parse(xml_str: str) -> ET.Element:
    return ET.fromstring(xml_str)


def _find(root: ET.Element, xpath: str) -> ET.Element | None:
    return root.find(xpath, NS)


def _findall(root: ET.Element, xpath: str) -> list[ET.Element]:
    return root.findall(xpath, NS)


def _text(root: ET.Element, xpath: str) -> str | None:
    el = _find(root, xpath)
    return el.text if el is not None else None


# ── Tests: Grundstruktur ───────────────────────────────────────────────────
# `test_xml_is_valid_and_parseable` (nur `root.tag.endswith("CrossIndustryInvoice")`)
# entfernt (#98 E5): reiner Parse-/Root-Check gibt falsche „ist gültig"-Sicherheit —
# die echte Gültigkeit (XSD/Schematron) beweist `test_zugferd_xml_schema.py`, das die
# Default-Rechnung (Variante `de_minimal`) real gegen Mustang validiert.

def test_profile_id_facturx_1_09_en16931():
    """BT-24: Profile-ID für ZUGFeRD 2.5 / Factur-X 1.09 EN16931 ist 'urn:cen.eu:en16931:2017'."""
    xml = generate_xml(_invoice(), _company())
    root = _parse(xml)
    profile_id = _text(
        root,
        ".//rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID"
    )
    assert profile_id == "urn:cen.eu:en16931:2017", (
        f"Falsche Profile-ID: {profile_id!r}. Seit ZUGFeRD 2.5 ist die EN16931-ID verkürzt."
    )


def test_profile_ids_constant_en16931():
    """Stellt sicher, dass PROFILE_IDS['EN16931'] den ZUGFeRD-2.5-Wert enthält."""
    assert PROFILE_IDS["EN16931"] == "urn:cen.eu:en16931:2017"


def test_invoice_number_bt1():
    """BT-1: Rechnungsnummer muss in ExchangedDocument/ID stehen."""
    xml = generate_xml(_invoice(invoice_number="RE-2026-042"), _company())
    root = _parse(xml)
    assert _text(root, ".//rsm:ExchangedDocument/ram:ID") == "RE-2026-042"


def test_type_code_bt3_standard_invoice():
    """BT-3: Standardrechnung hat TypeCode 380 (Default)."""
    xml = generate_xml(_invoice(), _company())
    root = _parse(xml)
    assert _text(root, ".//rsm:ExchangedDocument/ram:TypeCode") == "380"


def test_type_code_bt3_credit_note():
    """BT-3: Stornorechnung (Gutschrift) hat TypeCode 381."""
    inv = _invoice(invoice_type="credit_note")
    xml = generate_xml(inv, _company())
    root = _parse(xml)
    assert _text(root, ".//rsm:ExchangedDocument/ram:TypeCode") == "381"


def test_type_code_bt3_correction():
    """BT-3: Rechnungskorrektur hat TypeCode 384."""
    inv = _invoice(invoice_type="correction")
    xml = generate_xml(inv, _company())
    root = _parse(xml)
    assert _text(root, ".//rsm:ExchangedDocument/ram:TypeCode") == "384"


def test_type_code_bt3_self_billing():
    """BT-3: Gutschriftverfahren (Self-Billing) hat TypeCode 389."""
    inv = _invoice(invoice_type="self_billing")
    xml = generate_xml(inv, _company())
    root = _parse(xml)
    assert _text(root, ".//rsm:ExchangedDocument/ram:TypeCode") == "389"


def test_generate_xml_rejects_unknown_invoice_type():
    """#98 E10: ein unbekannter invoice_type darf NICHT still als 380 (Standardrechnung)
    durchgehen — sonst trüge die rechtlich maßgebliche XML einen falschen Dokumenttyp
    (z. B. ein vertippter Storno als Standardrechnung). generate_xml lehnt hart ab
    (Defense-in-depth; der Validator blockt zusätzlich, INVOICE_TYPE_INVALID)."""
    inv = _invoice(invoice_type="stornorechnung")  # Tippfehler statt 'storno'
    with pytest.raises(UnknownInvoiceTypeError):
        generate_xml(inv, _company())


def test_standard_invoice_has_no_preceding_invoice_reference():
    """Ohne original_invoice_id darf keine Rechnungsreferenz (BG-3) erzeugt werden."""
    xml = generate_xml(_invoice(), _company())
    root = _parse(xml)
    assert _find(root, ".//ram:InvoiceReferencedDocument") is None
    assert _find(root, ".//ram:BuyerOrderReferencedDocument") is None


def test_credit_note_references_original_via_invoice_referenced_document():
    """BG-3 (BT-25/BT-26): Storno referenziert die Originalrechnung über
    ram:InvoiceReferencedDocument innerhalb von ApplicableHeaderTradeSettlement.

    Das ist der von EN16931/CII vorgesehene Weg (siehe offizielles ZUGFeRD-Beispiel
    X16_Stornogutschrift_zur_Rechnung). Das Element BuyerOrderReferencedDocument ist
    dagegen BT-13 (Bestellnummer) und darf NICHT für die Rechnungsreferenz missbraucht
    werden – sonst liest ein konformer Empfänger (DATEV) die Originalrechnungsnummer als
    Bestellnummer und das automatische Matching Storno↔Original scheitert.
    """
    original = SimpleNamespace(invoice_number="RE-2026-001", issue_date=date(2026, 6, 11))
    inv = _invoice(
        invoice_number="RE-2026-002",
        invoice_type="credit_note",
        original_invoice_id="11111111-1111-1111-1111-111111111111",
        original_invoice=original,
    )
    xml = generate_xml(inv, _company())
    root = _parse(xml)

    # BuyerOrderReferencedDocument darf für die Rechnungsreferenz NICHT verwendet werden
    assert _find(root, ".//ram:BuyerOrderReferencedDocument") is None

    # Korrektes Element im Settlement mit Nummer und Datum der Originalrechnung
    settlement = _find(root, ".//ram:ApplicableHeaderTradeSettlement")
    ref = _find(settlement, "ram:InvoiceReferencedDocument")
    assert ref is not None, "InvoiceReferencedDocument fehlt im ApplicableHeaderTradeSettlement"
    assert _text(ref, "ram:IssuerAssignedID") == "RE-2026-001"
    assert _text(ref, "ram:FormattedIssueDateTime/qdt:DateTimeString") == "20260611"


def test_issue_date_bt2_format():
    """BT-2: Ausstellungsdatum im Format YYYYMMDD (ISO basic date)."""
    xml = generate_xml(_invoice(issue_date=date(2026, 3, 5)), _company())
    root = _parse(xml)
    date_str = _text(root, ".//rsm:ExchangedDocument/ram:IssueDateTime/udt:DateTimeString")
    assert date_str == "20260305"


def test_currency_bt5():
    """BT-5: Währungscode im InvoiceCurrencyCode."""
    xml = generate_xml(_invoice(currency="EUR"), _company())
    root = _parse(xml)
    tx_settlement = ".//ram:ApplicableHeaderTradeSettlement"
    currency_el = _find(_parse(xml), f"{tx_settlement}/ram:InvoiceCurrencyCode")
    assert currency_el is not None and currency_el.text == "EUR"


# ── Tests: Verkäufer / Käufer ──────────────────────────────────────────────

def test_seller_name_bt27():
    """BT-27: Verkäufername in SellerTradeParty/Name."""
    xml = generate_xml(_invoice(), _company(name="Test Verkäufer AG"))
    root = _parse(xml)
    name = _text(root, ".//ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty/ram:Name")
    assert name == "Test Verkäufer AG"


def test_seller_address_fields():
    """BT-35/37/162/40: Vollständige Verkäuferadresse."""
    c = _company(address_line1="Musterweg 5", zip_code="12345", city="Berlin", country="DE")
    root = _parse(generate_xml(_invoice(), c))
    seller_addr = ".//ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty/ram:PostalTradeAddress"
    assert _text(root, f"{seller_addr}/ram:LineOne") == "Musterweg 5"
    assert _text(root, f"{seller_addr}/ram:PostcodeCode") == "12345"
    assert _text(root, f"{seller_addr}/ram:CityName") == "Berlin"
    assert _text(root, f"{seller_addr}/ram:CountryID") == "DE"


def test_seller_address_line2_optional():
    """BT-36: Adresszusatz Verkäufer nur wenn befüllt."""
    c_with = _company(address_line2="Gebäude C")
    c_without = _company(address_line2=None)
    seller_addr = ".//ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty/ram:PostalTradeAddress"

    root_with = _parse(generate_xml(_invoice(), c_with))
    assert _text(root_with, f"{seller_addr}/ram:LineTwo") == "Gebäude C"

    root_without = _parse(generate_xml(_invoice(), c_without))
    assert _find(root_without, f"{seller_addr}/ram:LineTwo") is None


def test_seller_tax_number_only_fc():
    """BT-32: Steuernummer → schemeID='FC'."""
    c = _company(tax_number="12/345/67890", vat_id=None)
    root = _parse(generate_xml(_invoice(), c))
    regs = _findall(root, ".//ram:SellerTradeParty/ram:SpecifiedTaxRegistration")
    assert len(regs) == 1
    assert regs[0].find("ram:ID", NS).get("schemeID") == "FC"
    assert regs[0].find("ram:ID", NS).text == "12/345/67890"


def test_seller_vat_id_only_va():
    """BT-31: USt-IdNr. → schemeID='VA'."""
    c = _company(tax_number=None, vat_id="DE123456789")
    root = _parse(generate_xml(_invoice(), c))
    regs = _findall(root, ".//ram:SellerTradeParty/ram:SpecifiedTaxRegistration")
    assert len(regs) == 1
    assert regs[0].find("ram:ID", NS).get("schemeID") == "VA"
    assert regs[0].find("ram:ID", NS).text == "DE123456789"


def test_seller_both_tax_ids():
    """BT-31 + BT-32: Beide Steuer-IDs → zwei SpecifiedTaxRegistration-Blöcke."""
    c = _company(tax_number="12/345/67890", vat_id="DE123456789")
    root = _parse(generate_xml(_invoice(), c))
    regs = _findall(root, ".//ram:SellerTradeParty/ram:SpecifiedTaxRegistration")
    scheme_ids = {r.find("ram:ID", NS).get("schemeID") for r in regs}
    assert "FC" in scheme_ids
    assert "VA" in scheme_ids
    assert len(regs) == 2


def test_buyer_name_and_address_bt44():
    """BT-44/50/53/52/55: Käuferdaten vollständig."""
    cust = _customer(name="Kunde AG", address_line1="Kundenstr. 1",
                     zip_code="54321", city="Hamburg", country="DE")
    root = _parse(generate_xml(_invoice(customer=cust), _company()))
    buyer = ".//ram:ApplicableHeaderTradeAgreement/ram:BuyerTradeParty"
    assert _text(root, f"{buyer}/ram:Name") == "Kunde AG"
    buyer_addr = f"{buyer}/ram:PostalTradeAddress"
    assert _text(root, f"{buyer_addr}/ram:LineOne") == "Kundenstr. 1"
    assert _text(root, f"{buyer_addr}/ram:PostcodeCode") == "54321"
    assert _text(root, f"{buyer_addr}/ram:CityName") == "Hamburg"
    assert _text(root, f"{buyer_addr}/ram:CountryID") == "DE"


def test_buyer_address_line2_optional():
    """BT-51: Adresszusatz Käufer nur wenn befüllt."""
    cust_with = _customer(address_line2="EG links")
    cust_without = _customer(address_line2=None)
    buyer_addr = ".//ram:BuyerTradeParty/ram:PostalTradeAddress"

    root_with = _parse(generate_xml(_invoice(customer=cust_with), _company()))
    assert _text(root_with, f"{buyer_addr}/ram:LineTwo") == "EG links"

    root_without = _parse(generate_xml(_invoice(customer=cust_without), _company()))
    assert _find(root_without, f"{buyer_addr}/ram:LineTwo") is None


def test_buyer_vat_id_bt48():
    """BT-48: USt-IdNr. des Käufers nur wenn vorhanden."""
    cust_with_vat = _customer(vat_id="DE987654321")
    cust_without_vat = _customer(vat_id=None)

    root_with = _parse(generate_xml(_invoice(customer=cust_with_vat), _company()))
    reg = _find(root_with, ".//ram:BuyerTradeParty/ram:SpecifiedTaxRegistration/ram:ID")
    assert reg is not None
    assert reg.get("schemeID") == "VA"
    assert reg.text == "DE987654321"

    root_without = _parse(generate_xml(_invoice(customer=cust_without_vat), _company()))
    assert _find(root_without, ".//ram:BuyerTradeParty/ram:SpecifiedTaxRegistration") is None


# ── Tests: Zahlungsmittel ──────────────────────────────────────────────────

def test_payment_means_sepa_with_iban_and_bic():
    """BT-81/84/85: SEPA TypeCode 58, IBAN und BIC."""
    c = _company(bank_iban="DE89370400440532013000", bank_bic="COBADEFFXXX")
    root = _parse(generate_xml(_invoice(), c))
    pm = ".//ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradeSettlementPaymentMeans"
    assert _text(root, f"{pm}/ram:TypeCode") == "58"
    assert _text(root, f"{pm}/ram:PayeePartyCreditorFinancialAccount/ram:IBANID") == "DE89370400440532013000"
    assert _text(root, f"{pm}/ram:PayeeSpecifiedCreditorFinancialInstitution/ram:BICID") == "COBADEFFXXX"


def test_payment_means_sepa_iban_only_no_bic():
    """BT-84: Nur IBAN → kein BIC-Block."""
    c = _company(bank_iban="DE89370400440532013000", bank_bic=None)
    root = _parse(generate_xml(_invoice(), c))
    pm = ".//ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradeSettlementPaymentMeans"
    assert _text(root, f"{pm}/ram:IBANID") is None  # korrekt über tiefen Pfad
    iban_el = _find(root, f"{pm}/ram:PayeePartyCreditorFinancialAccount/ram:IBANID")
    assert iban_el is not None
    bic_el = _find(root, f"{pm}/ram:PayeeSpecifiedCreditorFinancialInstitution")
    assert bic_el is None


def test_no_payment_means_without_iban():
    """BT-81: Kein Zahlungsmittel-Block wenn keine IBAN hinterlegt."""
    c = _company(bank_iban=None)
    root = _parse(generate_xml(_invoice(), c))
    pm = ".//ram:ApplicableHeaderTradeSettlement/ram:SpecifiedTradeSettlementPaymentMeans"
    assert _find(root, pm) is None


# ── Tests: Lieferdatum, Notizen, Zahlungsbedingungen ──────────────────────

def test_delivery_date_bt80_included_when_set():
    """BT-80: Lieferdatum in ActualDeliverySupplyChainEvent wenn gesetzt."""
    inv = _invoice(delivery_date=date(2026, 6, 10))
    root = _parse(generate_xml(inv, _company()))
    delivery_date_el = _find(
        root,
        ".//ram:ApplicableHeaderTradeDelivery/ram:ActualDeliverySupplyChainEvent"
        "/ram:OccurrenceDateTime/udt:DateTimeString"
    )
    assert delivery_date_el is not None
    assert delivery_date_el.text == "20260610"


def test_delivery_block_bleibt_leer_statt_zu_fehlen():
    """Ohne Leistungsdatum bleibt der Block stehen, nur ohne Inhalt (#47).

    Dieser Test stand hier bis zum 23.08.2026 mit der umgekehrten Zusicherung: er
    verlangte, dass der Block ganz entfällt. Das war ein Irrtum, den nur ein Blick
    ins CII-Schema oder ein Lauf gegen Mustang aufdeckt, und beides hatte hier
    niemand getan. <ram:ApplicableHeaderTradeDelivery> steht zwischen Agreement und
    Settlement und ist Pflicht, auch leer; ohne ihn wies Mustang jede Rechnung ohne
    Leistungsdatum ab. Der Beweis dafür steht in test_zugferd_xml_schema.py, wo das
    echte Mustang urteilt statt einer Annahme von uns.
    """
    inv = _invoice(delivery_date=None)
    root = _parse(generate_xml(inv, _company()))

    block = _find(root, ".//ram:ApplicableHeaderTradeDelivery")
    assert block is not None
    assert _find(root, ".//ram:ApplicableHeaderTradeDelivery"
                       "/ram:ActualDeliverySupplyChainEvent") is None


def test_notes_bt22_included_when_set():
    """BT-22: Freitext in IncludedNote/Content wenn notes gesetzt."""
    inv = _invoice(notes="Bitte bis 30.06.2026 zahlen.")
    root = _parse(generate_xml(inv, _company()))
    note_el = _find(root, ".//rsm:ExchangedDocument/ram:IncludedNote/ram:Content")
    assert note_el is not None
    assert note_el.text == "Bitte bis 30.06.2026 zahlen."


def test_no_notes_block_when_empty():
    """Kein IncludedNote wenn notes leer."""
    root = _parse(generate_xml(_invoice(notes=None), _company()))
    assert _find(root, ".//rsm:ExchangedDocument/ram:IncludedNote") is None


def test_payment_terms_bt9():
    """BT-9: Zahlungsbedingungen in SpecifiedTradePaymentTerms/Description."""
    inv = _invoice(payment_terms="Zahlbar 30 Tage netto.")
    root = _parse(generate_xml(inv, _company()))
    desc = _text(root, ".//ram:SpecifiedTradePaymentTerms/ram:Description")
    assert desc == "Zahlbar 30 Tage netto."


def test_default_payment_terms_when_none():
    """Fallback-Text wenn payment_terms None."""
    root = _parse(generate_xml(_invoice(payment_terms=None), _company()))
    desc = _text(root, ".//ram:SpecifiedTradePaymentTerms/ram:Description")
    assert desc  # darf nicht leer sein
    assert "Zahlbar" in desc


def test_due_date_format():
    """Fälligkeitsdatum YYYYMMDD in DueDateDateTime."""
    inv = _invoice(due_date=date(2026, 7, 15))
    root = _parse(generate_xml(inv, _company()))
    due = _text(root, ".//ram:SpecifiedTradePaymentTerms/ram:DueDateDateTime/udt:DateTimeString")
    assert due == "20260715"


# ── Tests: Rechnungspositionen ─────────────────────────────────────────────

def test_line_item_basic_fields():
    """BT-126/153/146/129/130/131: Pflichtfelder einer Rechnungsposition."""
    item = _item(position=1, description="Softwareentwicklung", unit="Stunde",
                 quantity=Decimal("5.0000"), unit_price=Decimal("90.00"),
                 net_amount=Decimal("450.00"), tax_rate=Decimal("19.00"))
    root = _parse(generate_xml(_invoice(items=[item]), _company()))
    line = ".//ram:IncludedSupplyChainTradeLineItem"
    assert _text(root, f"{line}/ram:AssociatedDocumentLineDocument/ram:LineID") == "1"
    assert _text(root, f"{line}/ram:SpecifiedTradeProduct/ram:Name") == "Softwareentwicklung"
    assert _text(root, f"{line}/ram:SpecifiedLineTradeAgreement/ram:NetPriceProductTradePrice/ram:ChargeAmount") == "90.00"
    assert _text(root, f"{line}/ram:SpecifiedLineTradeSettlement/ram:SpecifiedTradeSettlementLineMonetarySummation/ram:LineTotalAmount") == "450.00"

    billed_qty = _find(root, f"{line}/ram:SpecifiedLineTradeDelivery/ram:BilledQuantity")
    assert billed_qty is not None
    assert billed_qty.text == "5.0000"
    assert billed_qty.get("unitCode") == "HUR"  # Stunde → HUR


def test_unit_code_mapping():
    """Mengeneinheiten werden korrekt in UN/CEFACT-Codes übersetzt."""
    units = [("Stück", "C62"), ("Stunde", "HUR"), ("Tag", "DAY"),
             ("Monat", "MON"), ("Pauschal", "LS"), ("Kilometer", "KMT")]
    for unit_de, expected_code in units:
        item = _item(unit=unit_de)
        root = _parse(generate_xml(_invoice(items=[item]), _company()))
        qty_el = _find(root, ".//ram:BilledQuantity")
        assert qty_el.get("unitCode") == expected_code, f"{unit_de} → {qty_el.get('unitCode')!r}, erwartet {expected_code!r}"


def test_unknown_unit_falls_back_to_c62():
    """Unbekannte Einheit → Fallback C62 (Stück)."""
    item = _item(unit="Flasche")
    root = _parse(generate_xml(_invoice(items=[item]), _company()))
    qty_el = _find(root, ".//ram:BilledQuantity")
    assert qty_el.get("unitCode") == "C62"


def test_tax_category_s_for_positive_rate():
    """BT-151: Steuersatz > 0% → CategoryCode 'S'."""
    item = _item(tax_rate=Decimal("19.00"))
    root = _parse(generate_xml(_invoice(items=[item]), _company()))
    cat = _text(root, ".//ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode")
    assert cat == "S"


def test_tax_category_z_for_zero_rate():
    """BT-151: Steuersatz 0% → CategoryCode 'Z'."""
    item = _item(tax_rate=Decimal("0.00"), tax_amount=Decimal("0.00"), gross_amount=Decimal("200.00"))
    root = _parse(generate_xml(_invoice(items=[item], tax_total=Decimal("0.00"), gross_total=Decimal("200.00")), _company()))
    cat = _text(root, ".//ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode")
    assert cat == "Z"


def test_7_percent_tax_rate():
    """Steuersatz 7% wird korrekt ausgegeben."""
    item = _item(tax_rate=Decimal("7.00"), net_amount=Decimal("100.00"),
                 tax_amount=Decimal("7.00"), gross_amount=Decimal("107.00"))
    root = _parse(generate_xml(
        _invoice(items=[item], net_total=Decimal("100.00"),
                 tax_total=Decimal("7.00"), gross_total=Decimal("107.00")),
        _company()
    ))
    rate = _text(root, ".//ram:SpecifiedLineTradeSettlement/ram:ApplicableTradeTax/ram:RateApplicablePercent")
    assert rate == "7.00"


# ── Tests: MwSt.-Aufschlüsselung ──────────────────────────────────────────

def test_single_tax_rate_summary():
    """Eine Steuersatzgruppe → ein ApplicableTradeTax-Block auf Dokumentebene."""
    root = _parse(generate_xml(_invoice(), _company()))
    tax_blocks = _findall(root, ".//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax")
    assert len(tax_blocks) == 1
    assert tax_blocks[0].find("ram:RateApplicablePercent", NS).text == "19.00"
    assert tax_blocks[0].find("ram:BasisAmount", NS).text == "200.00"
    assert tax_blocks[0].find("ram:CalculatedAmount", NS).text == "38.00"


def test_multiple_tax_rates_separate_summaries():
    """Zwei Steuersätze → zwei ApplicableTradeTax-Blöcke, korrekt aggregiert."""
    item_19 = _item(position=1, tax_rate=Decimal("19.00"),
                    net_amount=Decimal("100.00"), tax_amount=Decimal("19.00"),
                    gross_amount=Decimal("119.00"))
    item_7 = _item(position=2, description="Buch", tax_rate=Decimal("7.00"),
                   net_amount=Decimal("50.00"), tax_amount=Decimal("3.50"),
                   gross_amount=Decimal("53.50"))
    inv = _invoice(items=[item_19, item_7],
                   net_total=Decimal("150.00"),
                   tax_total=Decimal("22.50"),
                   gross_total=Decimal("172.50"))
    root = _parse(generate_xml(inv, _company()))
    tax_blocks = _findall(root, ".//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax")
    assert len(tax_blocks) == 2
    rates = {b.find("ram:RateApplicablePercent", NS).text for b in tax_blocks}
    assert "19.00" in rates
    assert "7.00" in rates


def test_two_items_same_tax_rate_aggregated():
    """Zwei Positionen gleicher Steuersatz → werden zu einem Block zusammengefasst."""
    item1 = _item(position=1, net_amount=Decimal("100.00"), tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"))
    item2 = _item(position=2, net_amount=Decimal("200.00"), tax_amount=Decimal("38.00"), gross_amount=Decimal("238.00"))
    inv = _invoice(items=[item1, item2],
                   net_total=Decimal("300.00"),
                   tax_total=Decimal("57.00"),
                   gross_total=Decimal("357.00"))
    root = _parse(generate_xml(inv, _company()))
    tax_blocks = _findall(root, ".//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax")
    assert len(tax_blocks) == 1
    assert tax_blocks[0].find("ram:BasisAmount", NS).text == "300.00"
    assert tax_blocks[0].find("ram:CalculatedAmount", NS).text == "57.00"


# ── Tests: Gesamtbeträge ───────────────────────────────────────────────────

def test_monetary_summation_bt106_112():
    """BT-106/109/110/112/115: Monetäre Summen korrekt."""
    inv = _invoice(net_total=Decimal("200.00"),
                   tax_total=Decimal("38.00"),
                   gross_total=Decimal("238.00"))
    root = _parse(generate_xml(inv, _company()))
    summation = ".//ram:SpecifiedTradeSettlementHeaderMonetarySummation"
    assert _text(root, f"{summation}/ram:LineTotalAmount") == "200.00"
    assert _text(root, f"{summation}/ram:TaxBasisTotalAmount") == "200.00"
    assert _text(root, f"{summation}/ram:GrandTotalAmount") == "238.00"
    assert _text(root, f"{summation}/ram:DuePayableAmount") == "238.00"

    tax_total = _find(root, f"{summation}/ram:TaxTotalAmount")
    assert tax_total is not None
    assert tax_total.text == "38.00"
    assert tax_total.get("currencyID") == "EUR"


# ── Tests: Sonderfälle / Sicherheit ───────────────────────────────────────

def test_xml_escaping_special_characters():
    """XML-Sonderzeichen werden korrekt escaped: &, <, >, \"."""
    c = _company(name="Müller & Söhne GmbH <Test>")
    cust = _customer(name='Firma "Schmidt"')
    root = _parse(generate_xml(_invoice(customer=cust), c))
    seller_name = _text(root, ".//ram:SellerTradeParty/ram:Name")
    assert seller_name == "Müller & Söhne GmbH <Test>"
    buyer_name = _text(root, ".//ram:BuyerTradeParty/ram:Name")
    assert buyer_name == 'Firma "Schmidt"'


def test_quantity_formatted_to_4_decimals():
    """Menge immer mit 4 Nachkommastellen (BR-129 Präzision)."""
    item = _item(quantity=Decimal("3"))
    root = _parse(generate_xml(_invoice(items=[item]), _company()))
    qty_el = _find(root, ".//ram:BilledQuantity")
    assert qty_el.text == "3.0000"


def test_amount_formatted_to_2_decimals():
    """Beträge immer mit 2 Nachkommastellen."""
    item = _item(unit_price=Decimal("99.9"), net_amount=Decimal("199.8"))
    inv = _invoice(items=[item], net_total=Decimal("199.80"),
                   tax_total=Decimal("37.96"), gross_total=Decimal("237.76"))
    root = _parse(generate_xml(inv, _company()))
    charge = _text(root, ".//ram:NetPriceProductTradePrice/ram:ChargeAmount")
    assert "." in charge
    assert len(charge.split(".")[1]) == 2


def test_payment_reference_equals_invoice_number():
    """PaymentReference = Rechnungsnummer (für Überweisungszweck)."""
    inv = _invoice(invoice_number="RE-2026-007")
    root = _parse(generate_xml(inv, _company()))
    ref = _text(root, ".//ram:ApplicableHeaderTradeSettlement/ram:PaymentReference")
    assert ref == "RE-2026-007"


def test_generate_xml_rejects_minimum_profile():
    """#98 E4: MINIMUM ist als E-Rechnung unzulässig — generate_xml lehnt hart ab,
    statt still auf EN16931 zu mappen (das trüge eine EN16931-ID über nicht-konformem
    Inhalt). Ersetzt den früheren `test_unknown_profile_falls_back_to_en16931`."""
    inv = _invoice(zugferd_profile="MINIMUM")
    with pytest.raises(NonCompliantProfileError):
        generate_xml(inv, _company())


def test_generate_xml_rejects_basic_wl_profile():
    """BASIC-WL (ohne Positionen) ist ebenfalls nicht rechtskonform → Ablehnung."""
    inv = _invoice(zugferd_profile="BASIC-WL")
    with pytest.raises(NonCompliantProfileError):
        generate_xml(inv, _company())


def test_generate_xml_accepts_basic_compliant_profile():
    """Positivkontrolle: BASIC ist EN16931-konform (Allowlist) und rendert die
    zugehörige Profile-ID — die Ablehnung trifft nur nicht-konforme Profile."""
    inv = _invoice(zugferd_profile="BASIC")
    root = _parse(generate_xml(inv, _company()))
    profile_id = _text(
        root,
        ".//rsm:ExchangedDocumentContext/ram:GuidelineSpecifiedDocumentContextParameter/ram:ID"
    )
    assert profile_id == PROFILE_IDS["BASIC"]


# ── MwSt.-Kategorien im XML ────────────────────────────────────────────────

class TestTaxCategories:

    def _ae_item(self):
        return _item(
            tax_rate=Decimal("0.00"),
            net_amount=Decimal("500.00"),
            tax_amount=Decimal("0.00"),
            gross_amount=Decimal("500.00"),
        )

    def test_ae_category_code_in_line_items(self):
        inv = _invoice(
            tax_category="AE",
            items=[self._ae_item()],
            net_total=Decimal("500.00"),
            tax_total=Decimal("0.00"),
            gross_total=Decimal("500.00"),
        )
        root = ET.fromstring(generate_xml(inv, _company()))
        cat = root.find(
            ".//rsm:SupplyChainTradeTransaction"
            "/ram:IncludedSupplyChainTradeLineItem"
            "/ram:SpecifiedLineTradeSettlement"
            "/ram:ApplicableTradeTax"
            "/ram:CategoryCode",
            NS,
        )
        assert cat is not None and cat.text == "AE"

    def test_ae_exemption_reason_in_line_items(self):
        inv = _invoice(
            tax_category="AE",
            items=[self._ae_item()],
            net_total=Decimal("500.00"),
            tax_total=Decimal("0.00"),
            gross_total=Decimal("500.00"),
        )
        root = ET.fromstring(generate_xml(inv, _company()))
        reason = root.find(
            ".//rsm:SupplyChainTradeTransaction"
            "/ram:IncludedSupplyChainTradeLineItem"
            "/ram:SpecifiedLineTradeSettlement"
            "/ram:ApplicableTradeTax"
            "/ram:ExemptionReason",
            NS,
        )
        assert reason is not None
        assert "13b UStG" in reason.text

    def test_ae_category_code_in_tax_summary(self):
        inv = _invoice(
            tax_category="AE",
            items=[self._ae_item()],
            net_total=Decimal("500.00"),
            tax_total=Decimal("0.00"),
            gross_total=Decimal("500.00"),
        )
        root = ET.fromstring(generate_xml(inv, _company()))
        cat = root.find(
            ".//ram:ApplicableHeaderTradeSettlement"
            "/ram:ApplicableTradeTax"
            "/ram:CategoryCode",
            NS,
        )
        assert cat is not None and cat.text == "AE"

    def test_ae_exemption_reason_in_tax_summary(self):
        inv = _invoice(
            tax_category="AE",
            items=[self._ae_item()],
            net_total=Decimal("500.00"),
            tax_total=Decimal("0.00"),
            gross_total=Decimal("500.00"),
        )
        root = ET.fromstring(generate_xml(inv, _company()))
        reason = root.find(
            ".//ram:ApplicableHeaderTradeSettlement"
            "/ram:ApplicableTradeTax"
            "/ram:ExemptionReason",
            NS,
        )
        assert reason is not None
        assert "13b UStG" in reason.text

    def test_k_category_code_and_exemption_reason(self):
        item = _item(
            tax_rate=Decimal("0.00"),
            net_amount=Decimal("300.00"),
            tax_amount=Decimal("0.00"),
            gross_amount=Decimal("300.00"),
        )
        inv = _invoice(
            tax_category="K",
            items=[item],
            net_total=Decimal("300.00"),
            tax_total=Decimal("0.00"),
            gross_total=Decimal("300.00"),
        )
        root = ET.fromstring(generate_xml(inv, _company()))
        cat = root.find(
            ".//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode",
            NS,
        )
        reason = root.find(
            ".//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/ram:ExemptionReason",
            NS,
        )
        assert cat is not None and cat.text == "K"
        assert reason is not None and "§ 4 Nr. 1b UStG" in reason.text

    def test_o_category_code_and_exemption_reason(self):
        item = _item(
            tax_rate=Decimal("0.00"),
            net_amount=Decimal("100.00"),
            tax_amount=Decimal("0.00"),
            gross_amount=Decimal("100.00"),
        )
        inv = _invoice(
            tax_category="O",
            items=[item],
            net_total=Decimal("100.00"),
            tax_total=Decimal("0.00"),
            gross_total=Decimal("100.00"),
        )
        root = ET.fromstring(generate_xml(inv, _company()))
        cat = root.find(
            ".//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode",
            NS,
        )
        reason = root.find(
            ".//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/ram:ExemptionReason",
            NS,
        )
        assert cat is not None and cat.text == "O"
        assert reason is not None and "§ 3a Abs. 2 UStG" in reason.text

    def test_e_category_code_and_exemption_reason(self):
        """#31: Kleinunternehmer § 19 in XPath-Tests wie K/O."""
        item = _item(
            tax_rate=Decimal("0.00"),
            net_amount=Decimal("500.00"),
            tax_amount=Decimal("0.00"),
            gross_amount=Decimal("500.00"),
        )
        inv = _invoice(
            tax_category="E",
            items=[item],
            net_total=Decimal("500.00"),
            tax_total=Decimal("0.00"),
            gross_total=Decimal("500.00"),
        )
        root = ET.fromstring(generate_xml(inv, _company()))
        cat = root.find(
            ".//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/ram:CategoryCode",
            NS,
        )
        reason = root.find(
            ".//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/ram:ExemptionReason",
            NS,
        )
        assert cat is not None and cat.text == "E"
        assert reason is not None and "§ 19" in reason.text

    def test_inland_zero_rate_uses_z_not_ae(self):
        item = _item(
            tax_rate=Decimal("0.00"),
            net_amount=Decimal("100.00"),
            tax_amount=Decimal("0.00"),
            gross_amount=Decimal("100.00"),
        )
        inv = _invoice(
            tax_category="S",
            items=[item],
            net_total=Decimal("100.00"),
            tax_total=Decimal("0.00"),
            gross_total=Decimal("100.00"),
        )
        root = ET.fromstring(generate_xml(inv, _company()))
        cat = root.find(
            ".//rsm:SupplyChainTradeTransaction"
            "/ram:IncludedSupplyChainTradeLineItem"
            "/ram:SpecifiedLineTradeSettlement"
            "/ram:ApplicableTradeTax"
            "/ram:CategoryCode",
            NS,
        )
        assert cat is not None and cat.text == "Z"

    def test_inland_zero_rate_has_no_exemption_reason(self):
        item = _item(
            tax_rate=Decimal("0.00"),
            net_amount=Decimal("100.00"),
            tax_amount=Decimal("0.00"),
            gross_amount=Decimal("100.00"),
        )
        inv = _invoice(
            tax_category="S",
            items=[item],
            net_total=Decimal("100.00"),
            tax_total=Decimal("0.00"),
            gross_total=Decimal("100.00"),
        )
        root = ET.fromstring(generate_xml(inv, _company()))
        reason = root.find(
            ".//rsm:SupplyChainTradeTransaction"
            "/ram:IncludedSupplyChainTradeLineItem"
            "/ram:SpecifiedLineTradeSettlement"
            "/ram:ApplicableTradeTax"
            "/ram:ExemptionReason",
            NS,
        )
        assert reason is None


def test_type_code_map_is_exposed_and_complete():
    from app.services.zugferd_xml import TYPE_CODE_MAP
    assert TYPE_CODE_MAP[None] == "380"
    assert TYPE_CODE_MAP["standard"] == "380"
    assert TYPE_CODE_MAP["credit_note"] == "381"
    assert TYPE_CODE_MAP["correction"] == "384"
    assert TYPE_CODE_MAP["self_billing"] == "389"


def test_postcode_precedes_lineone_in_all_addresses():
    """CII TradeAddressType-Sequenz: PostcodeCode kommt VOR LineOne.

    Regression: Mustang-Schema-Validierung (type 18) scheiterte, weil LineOne
    vor PostcodeCode ausgegeben wurde. Die 124 String-Match-Tests sahen das nie.
    """
    root = _parse(generate_xml(_invoice(), _company()))
    addrs = _findall(root, ".//ram:PostalTradeAddress")
    assert len(addrs) >= 2  # Verkäufer + Käufer
    for addr in addrs:
        tags = [child.tag.split("}")[-1] for child in addr]
        assert "PostcodeCode" in tags and "LineOne" in tags, tags
        assert tags.index("PostcodeCode") < tags.index("LineOne"), tags


def test_bt29_steht_nur_ohne_ust_idnr():
    """Die Verkäufer-Kennung erfüllt BR-CO-26, wenn die USt-IdNr. fehlt. Liegt sie
    vor, ist die Regel bereits erfüllt und die Steuernummer bliebe eine zweite
    Nennung ohne Zweck."""
    ohne = generate_xml(_invoice(), _company(tax_number="123/456/78901", vat_id=None))
    mit = generate_xml(_invoice(), _company(tax_number="123/456/78901", vat_id="DE123456789"))

    assert "<ram:ID>123/456/78901</ram:ID>" in ohne
    assert "<ram:ID>123/456/78901</ram:ID>" not in mit


def test_bt29_steht_vor_dem_namen():
    """Die CII-Sequenz von `TradeParty` ist geordnet: ID, GlobalID, Name, …. Nach dem
    Namen wäre es ein Schemafehler — und die String-Tests hier sehen Reihenfolge
    nicht, nur der Mustang-Lauf in test_zugferd_xml_schema.py."""
    xml = generate_xml(_invoice(), _company(tax_number="123/456/78901", vat_id=None))
    block = xml.split("<ram:SellerTradeParty>")[1].split("</ram:SellerTradeParty>")[0]

    assert block.index("<ram:ID>123/456/78901</ram:ID>") < block.index("<ram:Name>")
