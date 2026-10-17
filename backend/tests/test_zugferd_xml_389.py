"""Rollen in der XML einer Honorargutschrift (Spec #156, Kriterien 2, 3, 4).

Bei 389 ist der Kunde der Verkäufer (BG-4) und die eigene Firma der Erwerber
(BG-7). Die Testdaten beider Parteien sind in JEDEM Feld verschieden, damit
nicht zufällig ein Feld zur falschen Partei passt und der Test trotzdem grün
wird. 380, 386, 381 und 384 laufen dieselben Proben als Regression mit
umgekehrter Erwartung.

Struktur (Elementfolge, Schema) beweist test_zugferd_xml_schema.py; hier sind
nur fachliche Werte per XPath Gegenstand.
"""
from decimal import Decimal

import pytest

from app.services.zugferd_xml import generate_xml
from tests.factories import (
    company_stub,
    customer_stub,
    item_stub,
    zugferd_invoice_stub,
)
from tests.test_zugferd_xml import NS, _parse


def _firma():
    """Absender/Erwerber bei 389, Verkäufer sonst. Konstruierte Probe-Nummern,
    die die Datenwache durchlässt (aufsteigende Ziffernfolgen)."""
    return company_stub(
        name="Musterfirma GmbH",
        address_line1="Firmenweg 5",
        address_line2="Gebäude Nord",
        zip_code="01234",
        city="Musterstadt",
        country="DE",
        email="buero@example.de",
        phone="+49 30 000000",
        contact_name="Erika Beispiel",
        tax_number="123/456/78901",
        vat_id="DE123456789",
    )


def _kunde(**over):
    """Leistender/Verkäufer bei 389, Erwerber sonst. In jedem Feld verschieden
    von _firma()."""
    return customer_stub(
        name="Probe Kunde AG",
        address_line1="Kundenstraße 99",
        address_line2="Hinterhof",
        zip_code="98765",
        city="Beispielheim",
        country="AT",
        email="kunde@example.org",
        customer_number="K-389",
        tax_number="98/765/43210",
        vat_id="ATU98765432",
        **over,
    )


def _beleg(art, *, kunde=None, notes=None):
    return zugferd_invoice_stub(
        invoice_type=art,
        customer=kunde if kunde is not None else _kunde(),
        notes=notes,
        tax_category="S",
        items=[item_stub(
            quantity=Decimal("1"), unit_price=Decimal("100.00"),
            tax_rate=Decimal("7"), net_amount=Decimal("100.00"),
            tax_amount=Decimal("7.00"), gross_amount=Decimal("107.00"),
        )],
        net_total=Decimal("100.00"),
        tax_total=Decimal("7.00"),
        gross_total=Decimal("107.00"),
    )


def _wurzel(art, *, kunde=None, notes=None):
    return _parse(generate_xml(_beleg(art, kunde=kunde, notes=notes), _firma()))


def _verkaeufer(root):
    return root.find(".//ram:ApplicableHeaderTradeAgreement/ram:SellerTradeParty", NS)


def _erwerber(root):
    return root.find(".//ram:ApplicableHeaderTradeAgreement/ram:BuyerTradeParty", NS)


def _text(el, xpath):
    found = el.find(xpath, NS) if el is not None else None
    return found.text if found is not None else None


def _steuer_ids(partei):
    """{(schemeID, wert)} der SpecifiedTaxRegistration-Elemente einer Partei."""
    return {
        (reg.find("ram:ID", NS).get("schemeID"), reg.find("ram:ID", NS).text)
        for reg in partei.findall("ram:SpecifiedTaxRegistration", NS)
    }


def _notizen(root):
    return [el.text for el in
            root.findall(".//rsm:ExchangedDocument/ram:IncludedNote/ram:Content", NS)]


# ── Kriterium 2: Verkäufer- und Erwerberblock tragen die richtige Partei ────

class TestVerkaeuferUndErwerberBei389:
    def test_verkaeuferblock_traegt_den_kunden(self):
        root = _wurzel("self_billing")
        seller = _verkaeufer(root)
        assert _text(seller, "ram:Name") == "Probe Kunde AG"
        assert _text(seller, "ram:PostalTradeAddress/ram:PostcodeCode") == "98765"
        assert _text(seller, "ram:PostalTradeAddress/ram:LineOne") == "Kundenstraße 99"
        assert _text(seller, "ram:PostalTradeAddress/ram:LineTwo") == "Hinterhof"
        assert _text(seller, "ram:PostalTradeAddress/ram:CityName") == "Beispielheim"
        assert _text(seller, "ram:PostalTradeAddress/ram:CountryID") == "AT"
        assert _text(seller, "ram:URIUniversalCommunication/ram:URIID") == "kunde@example.org"
        # Verkäuferkennung (BT-29) entfällt: die USt-IdNr. (BT-31) erfüllt
        # BR-CO-26 bereits, eine zweite Nennung derselben Nummer wäre Beiwerk.
        assert seller.find("ram:ID", NS) is None

    def test_erwerberblock_traegt_die_firma(self):
        root = _wurzel("self_billing")
        buyer = _erwerber(root)
        assert _text(buyer, "ram:Name") == "Musterfirma GmbH"
        assert _text(buyer, "ram:PostalTradeAddress/ram:PostcodeCode") == "01234"
        assert _text(buyer, "ram:PostalTradeAddress/ram:LineOne") == "Firmenweg 5"
        assert _text(buyer, "ram:PostalTradeAddress/ram:LineTwo") == "Gebäude Nord"
        assert _text(buyer, "ram:PostalTradeAddress/ram:CityName") == "Musterstadt"
        assert _text(buyer, "ram:PostalTradeAddress/ram:CountryID") == "DE"
        assert _text(buyer, "ram:URIUniversalCommunication/ram:URIID") == "buero@example.de"
        # BT-46: die Firma hat keine Kundennummer, also kein leeres Element.
        assert buyer.find("ram:ID", NS) is None
        assert _steuer_ids(buyer) == {("VA", "DE123456789")}

    def test_kein_verkaeuferkontakt_ohne_kontaktnamen(self):
        """Der Kunde bekommt kein Feld für einen Kontaktnamen; BG-6 ist
        optional und entfällt sauber (EN 16931 R74: keine leeren Elemente)."""
        root = _wurzel("self_billing")
        seller = _verkaeufer(root)
        assert seller.find("ram:DefinedTradeContact", NS) is None
        assert "DefinedTradeContact" not in generate_xml(
            _beleg("self_billing"), _firma())


# ── Kriterium 2, Regression: alle übrigen Arten bleiben wie heute ───────────

class TestBesetzungRegression:
    @pytest.mark.parametrize("art", [None, "prepayment", "credit_note", "correction"])
    def test_verkaeufer_ist_die_firma(self, art):
        root = _wurzel(art)
        seller = _verkaeufer(root)
        assert _text(seller, "ram:Name") == "Musterfirma GmbH"
        assert _text(seller, "ram:PostalTradeAddress/ram:LineOne") == "Firmenweg 5"
        assert _text(seller, "ram:PostalTradeAddress/ram:LineTwo") == "Gebäude Nord"
        assert _text(seller, "ram:PostalTradeAddress/ram:CountryID") == "DE"
        assert _text(seller, "ram:URIUniversalCommunication/ram:URIID") == "buero@example.de"
        assert _steuer_ids(seller) == {("FC", "123/456/78901"), ("VA", "DE123456789")}
        assert _text(seller, "ram:DefinedTradeContact/ram:PersonName") == "Erika Beispiel"

    @pytest.mark.parametrize("art", [None, "prepayment", "credit_note", "correction"])
    def test_erwerber_ist_der_kunde(self, art):
        root = _wurzel(art)
        buyer = _erwerber(root)
        assert _text(buyer, "ram:Name") == "Probe Kunde AG"
        assert _text(buyer, "ram:PostalTradeAddress/ram:LineOne") == "Kundenstraße 99"
        assert _text(buyer, "ram:PostalTradeAddress/ram:LineTwo") == "Hinterhof"
        assert _text(buyer, "ram:PostalTradeAddress/ram:CountryID") == "AT"
        assert _text(buyer, "ram:URIUniversalCommunication/ram:URIID") == "kunde@example.org"
        assert _text(buyer, "ram:ID") == "K-389"
        assert _steuer_ids(buyer) == {("VA", "ATU98765432")}


# ── Kriterium 3: Steuerkennung des Verkäufers bei 389 ist die des Kunden ────

class TestVerkaeuferSteuerkennung:
    def test_nur_steuernummer(self):
        """FC-Registrierung trägt die Steuernummer des Kunden; BT-29 trägt sie
        zusätzlich, weil ohne USt-IdNr. sonst BR-CO-26 offen bliebe."""
        root = _wurzel("self_billing", kunde=_kunde(vat_id=None))
        seller = _verkaeufer(root)
        assert _steuer_ids(seller) == {("FC", "98/765/43210")}
        assert _text(seller, "ram:ID") == "98/765/43210"

    def test_nur_ust_id(self):
        root = _wurzel("self_billing", kunde=_kunde(tax_number=None))
        seller = _verkaeufer(root)
        assert _steuer_ids(seller) == {("VA", "ATU98765432")}
        # BT-31 erfüllt BR-CO-26, BT-29 bleibt weg.
        assert seller.find("ram:ID", NS) is None

    def test_beides(self):
        root = _wurzel("self_billing")
        seller = _verkaeufer(root)
        assert _steuer_ids(seller) == {("FC", "98/765/43210"), ("VA", "ATU98765432")}
        assert seller.find("ram:ID", NS) is None


# ── Kriterium 4: Pflichtangabe „Gutschrift" als BT-22-Note ───────────────────

class TestPflichtangabeGutschrift:
    def test_389_traegt_die_note_auch_ohne_nutzernotiz(self):
        assert "Gutschrift" in _notizen(_wurzel("self_billing"))

    def test_389_traegt_die_note_neben_einer_anderen_nutzernotiz(self):
        notizen = _notizen(_wurzel("self_billing", notes="Vielen Dank."))
        assert "Gutschrift" in notizen
        assert "Vielen Dank." in notizen
        assert notizen.count("Gutschrift") == 1

    @pytest.mark.parametrize("art", [None, "prepayment", "credit_note", "correction"])
    def test_andere_arten_bekommen_keine_pflichtnote(self, art):
        assert "Gutschrift" not in _notizen(_wurzel(art, notes="Vielen Dank."))
        assert _notizen(_wurzel(art, notes="Vielen Dank.")) == ["Vielen Dank."]

    def test_ohne_notizen_und_ohne_389_gibt_es_keine_note(self):
        assert _notizen(_wurzel(None)) == []
