"""Abzug auf Belegebene (EN 16931 BG-20) im PDF und im GoBD-Export (#147 Teil B2).

PDF und XML muessen dieselben Betraege zeigen, und die einzige Rechenstelle ist
services/belegsummen.py (das XML liest sie bereits). Ein abweichender
Steuerausweis im PDF waere ein Paragraph-14c-Risiko. Der GoBD-Export ergaenzt
die Kopfdaten um die Abzugsspalten, hinten, damit bestehende Spaltenpositionen
fuer Pruefsoftware gleich bleiben.
"""
import csv
import io
import re
import uuid
import zipfile
from datetime import date
from decimal import Decimal

import defusedxml.ElementTree as DET
from pypdf import PdfReader

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import pdf_generator, zugferd_xml
from app.services.gobd_export import build_gobd_export
from tests.probe_daten import IBAN_FIRMA_PROBE, UST_DE_PROBE

GRUND = "Anrechnung Vorleistung"
RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
NS = {"ram": RAM}


def _company():
    return Company(id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
                   zip_code="12345", city="Musterstadt", country="DE",
                   vat_id=UST_DE_PROBE, tax_number="123/456/78901",
                   bank_iban=IBAN_FIRMA_PROBE)


def _rechnung(mit_abzug=True, document_language="de"):
    """1000.00 netto, 19 Prozent, Abzug 100.00: Basis 900.00, Steuer 171.00, Brutto 1071.00.

    Gespeichertes net_total ist die Steuerbasis NACH Abzug (#147), also ohne
    Abzug 1000.00/190.00/1190.00.
    """
    if mit_abzug:
        net, tax, gross = Decimal("900.00"), Decimal("171.00"), Decimal("1071.00")
    else:
        net, tax, gross = Decimal("1000.00"), Decimal("190.00"), Decimal("1190.00")
    inv = Invoice(
        invoice_number="RE-2026-B20", issue_date=date(2026, 10, 1),
        delivery_date=date(2026, 10, 1), due_date=date(2026, 10, 15), currency="EUR",
        net_total=net, tax_total=tax, gross_total=gross, tax_category="S",
        zugferd_profile="EN16931", payment_terms="Zahlbar in 14 Tagen.",
        document_language=document_language,
    )
    if mit_abzug:
        inv.abzug_betrag = Decimal("100.00")
        inv.abzug_grund = GRUND
    inv.customer = Customer(name="Muster Kunde GmbH", address_line1="Kundenweg 1",
                            zip_code="10115", city="Berlin", country="DE")
    inv.items = [InvoiceItem(
        position=1, description="Beratungsleistung", unit="Stunde",
        quantity=Decimal("10"), unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
        net_amount=Decimal("1000.00"), tax_amount=Decimal("190.00"),
        gross_amount=Decimal("1190.00"),
    )]
    return inv


def _pdf_text(inv, tmp_path) -> str:
    """PDF-Text mit zusammengefuehrten Whitespace: pypdf liefert Zeilenumbrueche
    auch dort, wo nur die schmale Label-Spalte den Absatz umbrechen laesst."""
    out = tmp_path / "invoice.pdf"
    pdf_generator.generate_pdf(inv, _company(), out)
    text = "".join(p.extract_text() or "" for p in PdfReader(str(out)).pages)
    return re.sub(r"\s+", " ", text)


def _pdf_amounts(text: str) -> set:
    """Deutsch formatierte Geldbetraege aus dem PDF-Text als Decimal."""
    out = set()
    for m in re.finditer(r'(?<!\d)(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})(?!\d)', text):
        out.add(Decimal(m.group(1).replace(".", "") + "." + m.group(2)))
    return out


def _xml_total(root, tag) -> Decimal:
    el = root.find(f".//ram:SpecifiedTradeSettlementHeaderMonetarySummation/ram:{tag}", NS)
    assert el is not None, f"{tag} fehlt in der XML"
    return Decimal(el.text)


def test_pdf_mit_abzug_zeigt_positionssumme_abzug_und_reduzierte_summen(tmp_path):
    text = _pdf_text(_rechnung(), tmp_path)
    assert "Positionssumme" in text
    assert "1.000,00" in text
    # Label und Grund getrennt geprueft: in der schmalen Label-Spalte bricht
    # die Abzugszeile bei laengeren Gruenden um.
    assert "Abzug:" in text
    assert GRUND in text
    assert "-100,00" in text
    assert "900,00" in text
    # Steuer nur ein Satz, gerechnet auf der Basis nach Abzug (wie die XML, BG-23)
    assert "auf 900,00" in text
    assert "171,00" in text
    assert "1.071,00" in text


def test_pdf_mit_abzug_englische_beschriftung(tmp_path):
    inv = _rechnung(document_language="en")
    text = _pdf_text(inv, tmp_path)
    assert "Subtotal" in text
    assert "Allowance:" in text
    assert GRUND in text
    assert "1,000.00" in text


def test_pdf_ohne_abzug_zeigt_keine_positionssumme(tmp_path):
    text = _pdf_text(_rechnung(mit_abzug=False), tmp_path)
    assert "Positionssumme" not in text
    assert "Abzug: " not in text
    # Ausgabe wie bisher: Steuerbasis aus den Positionen, Brutto unveraendert
    assert "auf 1.000,00" in text
    assert "1.190,00" in text
    assert "1.071,00" not in text


def test_pdf_und_xml_zeigen_im_abzugsfall_dieselben_betraege(tmp_path):
    """PDF gegen XML (#147): alle fuenf Belegsummen muessen im PDF auftauchen."""
    inv = _rechnung()
    pdf_amounts = _pdf_amounts(_pdf_text(inv, tmp_path))
    root = DET.fromstring(zugferd_xml.generate_xml(inv, _company()).encode("utf-8"))
    for tag, erwartet in [
        ("LineTotalAmount", Decimal("1000.00")),
        ("AllowanceTotalAmount", Decimal("100.00")),
        ("TaxBasisTotalAmount", Decimal("900.00")),
        ("TaxTotalAmount", Decimal("171.00")),
        ("GrandTotalAmount", Decimal("1071.00")),
    ]:
        wert = _xml_total(root, tag)
        assert wert == erwartet, f"{tag}: XML sagt {wert}"
        assert wert in pdf_amounts, f"{tag} {wert} fehlt im PDF: {sorted(pdf_amounts)}"


def _gobd_zip(tmp_path, inv) -> zipfile.ZipFile:
    c = Customer(customer_number="K-2026-B20", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="12345", city="Musterstadt")
    c.id = uuid.uuid4()
    inv.customer = c
    data = build_gobd_export(
        invoices=[inv], customers=[c], audit_rows=[], uebergaben=[],
        storage_path=tmp_path, date_from=date(2026, 1, 1), date_to=date(2026, 12, 31),
    )
    return zipfile.ZipFile(io.BytesIO(data))


def _gobd_zeilen(zf, name):
    text = zf.read(name).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def test_gobd_rechnungen_csv_traegt_abzugspalten_hinten_mit_werten(tmp_path):
    import xml.etree.ElementTree as ET
    inv = _rechnung()
    zf = _gobd_zip(tmp_path, inv)

    kopf = zf.read("rechnungen.csv").decode("utf-8-sig").splitlines()[0].split(";")
    assert kopf[-2:] == ["abzug_betrag", "abzug_grund"]
    assert kopf.index("abzug_betrag") > kopf.index("erstellt_am")

    zeile = _gobd_zeilen(zf, "rechnungen.csv")[0]
    assert zeile["abzug_betrag"] == "100.00"
    assert zeile["abzug_grund"] == GRUND

    # index.xml entsteht aus derselben Spaltenliste (#52): Typ muss mitschwimmen
    root = ET.fromstring(zf.read("index.xml"))
    table = next(t for t in root.iter("Table")
                 if t.find("./URL/File").text == "rechnungen.csv")
    cols = {c.find("Name").text: c for c in table.iter("VariableColumn")}
    assert cols["abzug_betrag"].find("./Numeric/Accuracy").text == "2"
    assert cols["abzug_grund"].find("AlphaNumeric") is not None


def test_gobd_rechnungen_csv_ohne_abzug_leere_spalten(tmp_path):
    inv = _rechnung(mit_abzug=False)
    zf = _gobd_zip(tmp_path, inv)
    zeile = _gobd_zeilen(zf, "rechnungen.csv")[0]
    assert zeile["abzug_betrag"] == ""
    assert zeile["abzug_grund"] == ""
