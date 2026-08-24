"""GoBD-Z3-Export: reine Funktion Listen→ZIP; Tests entpacken und prüfen CSV-Inhalte."""
import csv
import io
import uuid
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from app.models.customer import Customer
from app.models.invoice import AuditLog, Invoice, InvoiceItem
from app.services.gobd_export import build_gobd_export


def _customer() -> Customer:
    c = Customer(
        customer_number="K-2026-001", name="Export GmbH",
        address_line1="Weg 1", zip_code="12345", city="Musterstadt",
    )
    c.id = uuid.uuid4()
    return c


def _invoice(customer: Customer, number="RE-2026-001") -> Invoice:
    inv = Invoice(
        invoice_number=number, customer_id=customer.id,
        issue_date=date(2026, 3, 15), due_date=date(2026, 3, 29),
        net_total=Decimal("1000.00"), tax_total=Decimal("190.00"),
        gross_total=Decimal("1190.00"), status="issued",
        currency="EUR", tax_category="S",
    )
    inv.id = uuid.uuid4()
    inv.customer = customer
    inv.items = [InvoiceItem(
        position=1, description="Beratung", unit="Stunde",
        quantity=Decimal("10.0000"), unit_price=Decimal("100.0000"),
        tax_rate=Decimal("19.00"), net_amount=Decimal("1000.00"),
        tax_amount=Decimal("190.00"), gross_amount=Decimal("1190.00"),
    )]
    return inv


def _build(tmp_path: Path, **overrides) -> zipfile.ZipFile:
    c = overrides.pop("customer", _customer())
    kwargs = dict(
        invoices=[_invoice(c)], customers=[c], audit_rows=[],
        storage_path=tmp_path, date_from=date(2026, 1, 1), date_to=date(2026, 12, 31),
    )
    kwargs.update(overrides)
    data = build_gobd_export(**kwargs)
    return zipfile.ZipFile(io.BytesIO(data))


def _read_csv(zf: zipfile.ZipFile, name: str) -> list[dict]:
    text = zf.read(name).decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text), delimiter=";"))


def test_zip_contains_all_csv_tables_and_documentation(tmp_path):
    zf = _build(tmp_path)
    names = set(zf.namelist())
    assert {"rechnungen.csv", "positionen.csv", "kunden.csv",
            "audit_log.csv", "dokumentation.txt"} <= names


def test_zip_contains_gdpdu_index_and_dtd(tmp_path):
    """GoBD-Beschreibungsstandard: index.xml + gdpdu.dtd, damit IDEA den Export
    einlesen kann (Z3-Mitwirkungspflicht, #52)."""
    names = set(_build(tmp_path).namelist())
    assert "index.xml" in names
    assert "gdpdu.dtd" in names


def test_index_xml_well_formed_and_references_dtd(tmp_path):
    raw = _build(tmp_path).read("index.xml").decode("utf-8")
    assert 'SYSTEM "gdpdu.dtd"' in raw                 # DOCTYPE verweist auf die DTD
    root = ET.fromstring(raw)                          # well-formed
    assert root.tag == "DataSet"


def test_index_xml_describes_all_four_tables(tmp_path):
    root = ET.fromstring(_build(tmp_path).read("index.xml"))
    files = {f.text for f in root.iter("File")}
    assert files == {"rechnungen.csv", "positionen.csv", "kunden.csv", "audit_log.csv"}


def test_index_xml_types_amount_and_date_columns(tmp_path):
    root = ET.fromstring(_build(tmp_path).read("index.xml"))
    table = next(t for t in root.iter("Table")
                 if t.find("./URL/File").text == "rechnungen.csv")
    cols = {c.find("Name").text: c for c in table.iter("VariableColumn")}
    assert cols["bruttobetrag"].find("./Numeric/Accuracy").text == "2"
    assert cols["ausstellungsdatum"].find("./Date/Format").text == "YYYY-MM-DD"
    assert cols["rechnungsnummer"].find("AlphaNumeric") is not None


def test_index_xml_columns_match_csv_headers_no_drift(tmp_path):
    """Spaltennamen in index.xml müssen exakt den CSV-Headern entsprechen."""
    zf = _build(tmp_path)
    root = ET.fromstring(zf.read("index.xml"))
    for fname in ("rechnungen.csv", "positionen.csv", "kunden.csv", "audit_log.csv"):
        table = next(t for t in root.iter("Table") if t.find("./URL/File").text == fname)
        idx_cols = [c.find("Name").text for c in table.iter("VariableColumn")]
        header = next(csv.reader(io.StringIO(zf.read(fname).decode("utf-8-sig")), delimiter=";"))
        assert idx_cols == header, f"{fname}: index.xml-Spalten ≠ CSV-Header"


def test_rechnungen_csv_has_invoice_row_with_iso_dates_and_totals(tmp_path):
    zf = _build(tmp_path)
    rows = _read_csv(zf, "rechnungen.csv")
    assert len(rows) == 1
    row = rows[0]
    assert row["rechnungsnummer"] == "RE-2026-001"
    assert row["ausstellungsdatum"] == "2026-03-15"
    assert row["bruttobetrag"] == "1190.00"
    assert row["kundennummer"] == "K-2026-001"
    assert row["status"] == "issued"
    assert row["original_rechnungsnummer"] == ""  # keine Storno-Referenz


def test_storno_row_references_original_number(tmp_path):
    c = _customer()
    original = _invoice(c)
    storno = _invoice(c, number="RE-2026-002")
    storno.invoice_type = "credit_note"
    storno.original_invoice_id = original.id
    storno.original_invoice = original
    zf = _build(tmp_path, customer=c, invoices=[original, storno])
    rows = {r["rechnungsnummer"]: r for r in _read_csv(zf, "rechnungen.csv")}
    assert rows["RE-2026-002"]["original_rechnungsnummer"] == "RE-2026-001"
    assert rows["RE-2026-002"]["rechnungstyp"] == "credit_note"


def test_positionen_csv_links_items_to_invoice_number(tmp_path):
    zf = _build(tmp_path)
    rows = _read_csv(zf, "positionen.csv")
    assert len(rows) == 1
    assert rows[0]["rechnungsnummer"] == "RE-2026-001"
    assert rows[0]["beschreibung"] == "Beratung"
    assert rows[0]["steuersatz"] == "19.00"


def test_audit_log_csv_serializes_json_values(tmp_path):
    entry = AuditLog(
        table_name="customers", record_id="abc", action="update",
        old_values={"city": "Musterstadt"}, new_values={"city": "Augsburg"},
    )
    entry.changed_at = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    zf = _build(tmp_path, audit_rows=[entry])
    rows = _read_csv(zf, "audit_log.csv")
    assert len(rows) == 1
    assert rows[0]["tabelle"] == "customers"
    assert '"city": "Augsburg"' in rows[0]["neue_werte"]


def test_dokumentation_names_period_and_conventions(tmp_path):
    zf = _build(tmp_path)
    doc = zf.read("dokumentation.txt").decode("utf-8")
    assert "2026-01-01" in doc and "2026-12-31" in doc
    assert "Semikolon" in doc
    assert "UTF-8" in doc
    assert "discarded" in doc


def test_dokumentation_timestamp_hat_zeitzone(tmp_path):
    """#2: Erstellungszeit im Begleitschreiben mit Zeitzone, nicht naive Lokalzeit."""
    zf = _build(tmp_path)
    doc = zf.read("dokumentation.txt").decode("utf-8")
    zeile = next(l for l in doc.splitlines() if l.startswith("Erstellt am:"))
    assert "+" in zeile or zeile.rstrip().endswith("Z")


def test_dokumente_are_included_from_storage(tmp_path):
    c = _customer()
    inv = _invoice(c)
    inv.pdf_filename = "RE-2026-001_zugferd.pdf"
    (tmp_path / "pdfs").mkdir()
    (tmp_path / "pdfs" / "RE-2026-001_zugferd.pdf").write_bytes(b"%PDF-fake")
    (tmp_path / "xml").mkdir()
    (tmp_path / "xml" / "RE-2026-001.xml").write_text("<xml/>", encoding="utf-8")

    zf = _build(tmp_path, customer=c, invoices=[inv])
    names = set(zf.namelist())
    assert "dokumente/RE-2026-001_zugferd.pdf" in names
    assert "dokumente/RE-2026-001.xml" in names
    assert "fehlende_dateien.txt" not in names  # nichts fehlt


def test_missing_files_are_listed_not_fatal(tmp_path):
    c = _customer()
    inv = _invoice(c)
    inv.pdf_filename = "RE-2026-001_zugferd.pdf"  # Datei existiert NICHT
    zf = _build(tmp_path, customer=c, invoices=[inv])
    missing = zf.read("fehlende_dateien.txt").decode("utf-8")
    assert "RE-2026-001_zugferd.pdf" in missing
    assert "RE-2026-001.xml" in missing


def test_discarded_entwurf_erzeugt_keinen_fehlenden_beleg_eintrag(tmp_path):
    """#29/#11: verworfene Entwuerfe erklaeren Nummernluecken, sind aber keine fehlenden Belege."""
    c = _customer()
    inv = _invoice(c, number="RE-2026-DISC")
    inv.status = "discarded"
    zf = _build(tmp_path, customer=c, invoices=[inv])
    assert "fehlende_dateien.txt" not in zf.namelist()
    rows = _read_csv(zf, "rechnungen.csv")
    assert any(r["rechnungsnummer"] == "RE-2026-DISC" and r["status"] == "discarded" for r in rows)


def test_xml_falls_back_to_db_column_when_file_missing(tmp_path):
    c = _customer()
    inv = _invoice(c)
    inv.zugferd_xml = "<rsm:CrossIndustryInvoice/>"  # nur in DB, Datei fehlt
    zf = _build(tmp_path, customer=c, invoices=[inv])
    assert zf.read("dokumente/RE-2026-001.xml").decode("utf-8") == "<rsm:CrossIndustryInvoice/>"
    missing = zf.read("fehlende_dateien.txt").decode("utf-8")
    assert ".xml" not in missing  # XML gilt als vorhanden (DB-Fallback)


def test_datenlieferant_ist_die_eigene_firma_nicht_die_software(tmp_path):
    """GDPdU: `DataSupplier` ist der Steuerpflichtige, nicht das Programm, das
    den Export erzeugt hat (#99 §4.4). Vorher stand dort fest verdrahtet
    der Name der Software mit ihrem Sitz — der Betriebsprüfer einer fremden Kanzlei
    hätte einen Datenträger mit dem Namen und Sitz eines Dritten bekommen.
    """
    from types import SimpleNamespace

    firma = SimpleNamespace(name="Kanzlei Musterfrau", city="München")
    zf = _build(tmp_path, company=firma)
    index = zf.read("index.xml").decode("utf-8")

    assert "<Name>Kanzlei Musterfrau</Name>" in index
    assert "<Location>München</Location>" in index
    assert "abgehakt" not in index.lower()
    assert "Musterstadt" not in index


def test_ohne_firma_bleibt_der_datenlieferant_leer_statt_falsch(tmp_path):
    zf = _build(tmp_path, company=None)
    index = zf.read("index.xml").decode("utf-8")

    assert "abgehakt" not in index.lower()
    assert "Musterstadt" not in index
