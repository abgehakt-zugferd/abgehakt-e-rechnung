"""Auf einer steuerfreien Rechnung hat keine Steuerzeile etwas zu suchen (10.08.2026).

Gefunden in der Abnahme, nicht in der Suite: Das PDF einer Kleinunternehmer-Rechnung
zeigte eine Spalte "MwSt." mit "0 %" je Position und darunter die Zeile
"zzgl. 0 % MwSt. auf 510,00 EUR -- 0,00 EUR". Der Beleg sagt damit zweierlei
gleichzeitig: oben "hier wird keine Umsatzsteuer ausgewiesen" (§ 19 UStG), unten
rechnet er eine vor, wenn auch null.

Rechtlich ist das unbedenklich, ein Betrag von null ist kein unrichtiger Steuerausweis
nach § 14c. Es geht um etwas anderes: Der Empfänger einer Reverse-Charge-Rechnung muss
erkennen, dass ER die Steuer schuldet. Eine Zeile "zzgl. 0 % MwSt." legt das Gegenteil
nahe, nämlich einen Vorgang, bei dem Steuer anfiel und zufällig null betrug.

Betroffen sind alle vier steuerfreien Kategorien, nicht nur § 19: AE (Reverse Charge),
K (innergemeinschaftliche Lieferung), O (nicht steuerbar), E (Kleinunternehmer). Was
den Grund erklärt, ist der Hinweistext, der ohnehin schon auf dem Blatt steht.

Beim normalen Inlandsbeleg (S) bleibt beides, dort ist die Steuer die Aussage.
"""
from datetime import date
from decimal import Decimal

from pypdf import PdfReader

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import pdf_generator

STEUERFREI = ("E", "AE", "K", "O")


def _company():
    return Company(id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
                   zip_code="12345", city="Musterstadt", country="DE",
                   vat_id="DE123456789", tax_number="123/456/78901",
                   bank_iban="DE00123456780000000000")


def _invoice(kategorie: str, satz: str):
    netto = Decimal("510.00")
    steuer = (netto * Decimal(satz) / Decimal("100")).quantize(Decimal("0.01"))
    inv = Invoice(
        invoice_number="RE-2026-0815", issue_date=date(2026, 8, 10),
        delivery_date=date(2026, 8, 5), due_date=date(2026, 8, 24), currency="EUR",
        net_total=netto, tax_total=steuer, gross_total=netto + steuer,
        tax_category=kategorie, zugferd_profile="EN16931",
    )
    inv.customer = Customer(name="Kirchner Immobilien GmbH", address_line1="Hauptstraße 12",
                            zip_code="12345", city="Musterstadt", country="DE")
    inv.items = [InvoiceItem(position=1, description="Beratung Bauantrag", unit="Std",
                             quantity=Decimal("6"), unit_price=Decimal("85.00"),
                             tax_rate=Decimal(satz), net_amount=netto,
                             tax_amount=steuer, gross_amount=netto + steuer)]
    return inv


def _text(inv, tmp_path) -> str:
    out = tmp_path / "rechnung.pdf"
    pdf_generator.generate_pdf(inv, _company(), out)
    return "".join(p.extract_text() or "" for p in PdfReader(str(out)).pages)


def test_steuerfrei_ohne_steuerzeile(tmp_path):
    for kategorie in STEUERFREI:
        text = _text(_invoice(kategorie, "0"), tmp_path)

        assert "zzgl." not in text, f"{kategorie}: rechnet Steuer vor, die es nicht gibt"
        assert "MwSt." not in text, f"{kategorie}: Steuerspalte trotz Steuerfreiheit"


def test_steuerfrei_zeigt_weiter_den_grund(tmp_path):
    """Die Zeile faellt weg, die Begruendung nicht: sonst stuende auf dem Beleg
    ueberhaupt nichts mehr zur Steuer, und das waere schlimmer als zu viel."""
    text = _text(_invoice("E", "0"), tmp_path)

    assert "§ 19 UStG" in text
    assert "510,00" in text


def test_inland_behaelt_die_steuerzeile(tmp_path):
    """Die Gegenprobe. Ohne sie koennte die Steueraufstellung ueberall verschwinden
    und beide Tests oben blieben gruen."""
    text = _text(_invoice("S", "19"), tmp_path)

    assert "MwSt." in text, "Die Steuerspalte fehlt beim Inlandsbeleg"
    assert "zzgl." in text, "Die Steueraufstellung fehlt beim Inlandsbeleg"
    assert "96,90" in text, "Der Steuerbetrag fehlt"
