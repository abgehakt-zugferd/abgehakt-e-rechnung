"""
Echte Schema-Validierung der generierten CII-XML über Mustang (nicht String-Matching).

Motivation (Audit-#3): Die ~48 Tests in test_zugferd_xml.py prüfen Substrings im
generierten XML und übersehen daher Element-Reihenfolge, Namespaces und Datentypen.
Der reale PostcodeCode-vor-LineOne-Bug (Mustang type 18) blieb dort unsichtbar und
wurde erst vom EINEN Integrationstest gefangen. Hier validieren wir die BARE XML pro
Adressblock/Struktur gegen das echte EN16931-Schema — die einzige harte Prüfung.

mustang.validate(bare_xml) liefert 'Parsed PDF:absent XML:valid' → is_valid=True,
bei Schemafehlern is_valid=False mit den konkreten Fehlern in ['errors'].
"""
import os
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import mustang, zugferd_xml

pytestmark = pytest.mark.skipif(
    not mustang.jar_available(), reason="Mustang-JAR nicht verfügbar"
)


def _company(**over) -> Company:
    kw = dict(
        id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
        zip_code="12345", city="Musterstadt", email="info@example.de", phone="+49 111",
        vat_id="DE123456789", tax_number="123/456/78901",
        bank_iban="DE00123456780000000000", bank_bic="ABCDDEFF",
        bank_name="Testbank", country="DE",
    )
    kw.update(over)
    return Company(**kw)


def _invoice(customer: Customer, **over) -> Invoice:
    item = InvoiceItem(
        position=1, description="Beratungsleistung", quantity=Decimal("2"),
        unit="Std", unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
        net_amount=Decimal("200.00"), tax_amount=Decimal("38.00"),
        gross_amount=Decimal("238.00"),
    )
    kw = dict(
        invoice_number="RE-2026-778", issue_date=date(2026, 7, 8),
        delivery_date=date(2026, 7, 8), due_date=date(2026, 7, 22), currency="EUR",
        net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
        gross_total=Decimal("238.00"), tax_category="S",
        payment_terms="Zahlbar innerhalb 14 Tagen.", notes="",
    )
    kw.update(over)
    inv = Invoice(**kw)
    inv.customer = customer
    inv.items = [item]
    return inv


def _validate(invoice: Invoice, company: Company) -> dict:
    xml = zugferd_xml.generate_xml(invoice, company)
    fd, name = tempfile.mkstemp(suffix=".xml")
    p = Path(name)
    try:
        os.write(fd, xml.encode("utf-8"))
        os.close(fd)
        return mustang.validate(p)
    finally:
        p.unlink(missing_ok=True)


# ── Adressblöcke: Käufer (BuyerTradeParty) ──────────────────────────────────
# Jede Variante MUSS schema-valide XML erzeugen. Falsche Element-Reihenfolge
# (z. B. LineOne vor PostcodeCode) macht Mustang hier rot.

CUSTOMER_VARIANTS = {
    "de_minimal": dict(name="Muster Kunde GmbH", address_line1="Kundenweg 1",
                       zip_code="10115", city="Berlin", country="DE"),
    "de_with_line2": dict(name="Muster Kunde GmbH", address_line1="Kundenweg 1",
                          address_line2="Hinterhaus, 3. OG", zip_code="10115",
                          city="Berlin", country="DE"),
    "de_b2b_vatid": dict(name="Kunde AG", address_line1="Hauptstr. 5",
                         zip_code="80331", city="München", country="DE",
                         vat_id="DE987654321"),
    "foreign_at": dict(name="Ösi Handels GmbH", address_line1="Ringstraße 12",
                       zip_code="1010", city="Wien", country="AT",
                       vat_id="ATU12345678"),
    "umlauts": dict(name="Müller & Söhne Groß-Handel OHG",
                    address_line1="Grünäckerstraße 8", zip_code="70199",
                    city="Stuttgart-Süd", country="DE"),
    "long_lines": dict(name="Sehr Lange Firmierung mit Zusatzbezeichnung und GmbH & Co. KG",
                       address_line1="Ein ausgesprochen langer Straßenname 12345a",
                       zip_code="99999", city="Musterhausen an der Nebenstrecke",
                       country="DE"),
}


@pytest.mark.parametrize("key", list(CUSTOMER_VARIANTS))
def test_buyer_address_variants_are_schema_valid(key):
    cust = Customer(**CUSTOMER_VARIANTS[key])
    result = _validate(_invoice(cust), _company())
    assert result["is_valid"], (
        f"CII-XML für Käuferadresse {key!r} ist NICHT schema-valide:\n"
        f"{result['errors']}\n{result['raw']}"
    )


# ── Adressblock: Verkäufer (SellerTradeParty) ───────────────────────────────

@pytest.mark.parametrize("company_over", [
    pytest.param({}, id="seller_default"),
    pytest.param({"address_line2": "Gebäude B"}, id="seller_with_line2"),
])
def test_seller_address_variants_are_schema_valid(company_over):
    cust = Customer(**CUSTOMER_VARIANTS["de_minimal"])
    result = _validate(_invoice(cust), _company(**company_over))
    assert result["is_valid"], (
        f"CII-XML für Verkäuferadresse {company_over} ist NICHT schema-valide:\n"
        f"{result['errors']}\n{result['raw']}"
    )


# ── Steuersätze/Summen: schema-valide XML über Sätze und gemischte Positionen ──

def _item(pos, qty, price, rate):
    net = (Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"))
    tax = (net * Decimal(rate) / 100).quantize(Decimal("0.01"))
    return InvoiceItem(position=pos, description="Leistung", unit="Std",
                       quantity=Decimal(qty), unit_price=Decimal(price),
                       tax_rate=Decimal(rate), net_amount=net, tax_amount=tax,
                       gross_amount=net + tax)


def _multi_item_invoice(items):
    net = sum(i.net_amount for i in items)
    tax = sum(i.tax_amount for i in items)
    cust = Customer(**CUSTOMER_VARIANTS["de_minimal"])
    inv = _invoice(cust, net_total=net, tax_total=tax, gross_total=net + tax)
    inv.items = items
    return inv


@pytest.mark.parametrize("rate", ["19", "7"])
def test_single_tax_rate_xml_is_schema_valid(rate):
    inv = _multi_item_invoice([_item(1, "2", "100.00", rate)])
    result = _validate(inv, _company())
    assert result["is_valid"], f"Steuersatz {rate}% XML nicht valide:\n{result['raw']}"


def test_mixed_tax_rates_xml_is_schema_valid():
    inv = _multi_item_invoice([_item(1, "2", "100.00", "19"), _item(2, "1", "50.00", "7")])
    result = _validate(inv, _company())
    assert result["is_valid"], f"Gemischte Sätze XML nicht valide:\n{result['raw']}"


# ── Sonderfälle (Audit #98 P2): Storno/Reverse-Charge/Seller ohne IBAN ────────

def test_credit_note_381_is_schema_valid():
    """Gutschrift/Storno (TypeCode 381) mit InvoiceReferencedDocument auf die
    Originalrechnung muss schema-valide sein."""
    import uuid as _uuid
    cust = Customer(**CUSTOMER_VARIANTS["de_minimal"])
    original = Invoice(invoice_number="RE-2026-100", issue_date=date(2026, 6, 1),
                       due_date=date(2026, 6, 15))
    inv = _invoice(cust, invoice_number="RE-2026-101", invoice_type="credit_note",
                   original_invoice_id=_uuid.uuid4())
    inv.original_invoice = original
    result = _validate(inv, _company())
    assert result["is_valid"], (
        f"credit_note (381) XML nicht valide:\n{result['errors']}\n{result['raw']}"
    )
    xml = zugferd_xml.generate_xml(inv, _company())
    assert "<ram:TypeCode>381</ram:TypeCode>" in xml
    assert "RE-2026-100" in xml  # Referenz auf Original


def test_reverse_charge_ae_is_schema_valid():
    """Reverse Charge (§ 13b, Kategorie AE): 0 %-Position, Käufer mit USt-IdNr.,
    ExemptionReason — muss schema-valide sein."""
    cust = Customer(name="EU Kunde AG", address_line1="Ringstraße 12", zip_code="1010",
                    city="Wien", country="AT", vat_id="ATU12345678")
    inv = _multi_item_invoice([_item(1, "2", "100.00", "0")])
    inv.customer = cust
    inv.tax_category = "AE"
    result = _validate(inv, _company())
    assert result["is_valid"], (
        f"Reverse-Charge (AE) XML nicht valide:\n{result['errors']}\n{result['raw']}"
    )


@pytest.mark.parametrize("category,rate,vat_id,country", [
    ("K", "0", "ATU12345678", "AT"),
    ("O", "0", None, "US"),
    ("E", "0", None, "DE"),
])
def test_steuerfreie_kategorien_sind_schema_valid(category, rate, vat_id, country):
    """#28: Mustang-Schema fuer K, O und E."""
    cust = Customer(name="Kunde GmbH", address_line1="Weg 1", zip_code="10115",
                    city="Wien" if country == "AT" else ("New York" if country == "US" else "Berlin"),
                    country=country, vat_id=vat_id)
    inv = _multi_item_invoice([_item(1, "1", "100.00", rate)])
    inv.customer = cust
    inv.tax_category = category
    inv.tax_total = Decimal("0")
    inv.gross_total = inv.net_total
    result = _validate(inv, _company())
    assert result["is_valid"], (
        f"Kategorie {category} XML nicht valide:\n{result['errors']}\n{result['raw']}"
    )


def test_seller_without_iban_is_schema_valid():
    """Verkäufer ohne Bankverbindung: der PayeePartyCreditor-Block entfällt,
    die XML muss trotzdem schema-valide bleiben."""
    cust = Customer(**CUSTOMER_VARIANTS["de_minimal"])
    result = _validate(_invoice(cust), _company(bank_iban=None, bank_bic=None))
    assert result["is_valid"], (
        f"Seller ohne IBAN XML nicht valide:\n{result['errors']}\n{result['raw']}"
    )


def test_verkaeufer_nur_mit_steuernummer_ist_gueltig():
    """BR-CO-26 (EN 16931): der Verkäufer braucht eine Kennung (BT-29), eine
    Registernummer (BT-30) ODER die USt-IdNr. (BT-31). Die Steuernummer steht als
    BT-32 im Dokument und zählt für diese Regel NICHT.

    Die Einrichtung lässt ausdrücklich „Steuernummer oder USt-IdNr." zu, weil § 14
    UStG das so vorsieht. Ohne diesen Test konnte deshalb jemand alles richtig
    ausfüllen und trotzdem nie eine Rechnung finalisieren — die Firma in den übrigen
    Schema-Tests trägt immer beides, der Fall war unbeobachtet. Gefunden am
    2026-08-09 in der Abnahme, an einer echten Erstinstallation.
    """
    company = _company(vat_id=None, tax_number="123/456/78901")
    customer = Customer(**CUSTOMER_VARIANTS["de_minimal"])
    result = _validate(_invoice(customer), company)

    assert result["is_valid"], result["raw"][-1200:]
    assert "BR-CO-26" not in result["raw"]


# ── Rechnung ohne Leistungsdatum (Kleinbetrag, § 33 UStDV) ──────────────────
# Der Block <ram:ApplicableHeaderTradeDelivery> ist im CII-Schema Pflicht, auch
# wenn nichts darin steht. Er entfiel, sobald weder ein Leistungsdatum noch ein
# Lieferland vorlag; die Datei war dann schon am Schema unzulässig, nicht erst an
# einer Geschäftsregel. Getroffen hat das genau die Kleinbetragsrechnung ohne
# Leistungsdatum, die § 33 UStDV ausdrücklich erlaubt und die das Finalize-Gate
# seit #23/#24 durchlässt.

@pytest.mark.parametrize("category,rate,vat_id,country,city", [
    ("S", "19", None, "DE", "Berlin"),
    ("AE", "0", "ATU12345678", "AT", "Wien"),
    ("O", "0", None, "US", "New York"),
    ("E", "0", None, "DE", "Berlin"),
])
def test_kleinbetrag_ohne_leistungsdatum_ist_schema_valid(category, rate, vat_id, country, city):
    """#47: ohne Leistungsdatum muss die XML trotzdem gültig sein.

    Alle vier Steuertypen stehen hier, weil der fehlende Block keiner Kategorie
    galt: er fehlte immer.
    """
    cust = Customer(name="Kunde GmbH", address_line1="Weg 1", zip_code="10115",
                    city=city, country=country, vat_id=vat_id)
    inv = _invoice(cust, delivery_date=None, tax_category=category)
    if rate == "0":
        inv.items[0].tax_rate = Decimal("0")
        inv.items[0].tax_amount = Decimal("0")
        inv.items[0].gross_amount = inv.items[0].net_amount
        inv.tax_total = Decimal("0")
        inv.gross_total = inv.net_total

    result = _validate(inv, _company())

    assert result["is_valid"], (
        f"Kategorie {category} ohne Leistungsdatum nicht valide:\n{result['raw'][-1500:]}"
    )


def test_innergemeinschaftliche_lieferung_ohne_leistungsdatum_bleibt_unzulaessig():
    """Die Gegenprobe, und zugleich die Begründung der Validator-Regel (#47).

    Für Kategorie K verlangt EN16931 (BR-IC-11) das Lieferdatum oder einen
    Abrechnungszeitraum, unabhängig vom Betrag. Der vollständige Delivery-Block
    allein rettet diesen Fall also nicht; deshalb hält der Validator ihn vorher
    auf, statt den Nutzer in eine Mustang-Meldung laufen zu lassen. Wird die Regel
    hier je grün, gehört die Validator-Regel auf den Prüfstand statt umgekehrt.
    """
    cust = Customer(name="EU Kunde AG", address_line1="Ringstraße 12", zip_code="1010",
                    city="Wien", country="AT", vat_id="ATU12345678")
    inv = _invoice(cust, delivery_date=None, tax_category="K")
    inv.items[0].tax_rate = Decimal("0")
    inv.items[0].tax_amount = Decimal("0")
    inv.items[0].gross_amount = inv.items[0].net_amount
    inv.tax_total = Decimal("0")
    inv.gross_total = inv.net_total

    result = _validate(inv, _company())

    assert not result["is_valid"], (
        "Mustang nimmt die ig. Lieferung ohne Leistungsdatum inzwischen an"
    )
    assert "ActualDeliverySupplyChainEvent" in result["raw"], result["raw"][-1500:]
