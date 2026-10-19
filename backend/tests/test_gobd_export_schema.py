"""GDPdU-Spaltenvertrag für alle sechs Exporttabellen."""
import csv
import io
import xml.etree.ElementTree as ET

from tests.test_gobd_export import _build


def test_index_xml_well_formed_and_references_dtd(tmp_path):
    raw = _build(tmp_path).read("index.xml").decode("utf-8")
    assert 'SYSTEM "gdpdu.dtd"' in raw                 # DOCTYPE verweist auf die DTD
    root = ET.fromstring(raw)                          # well-formed
    assert root.tag == "DataSet"


def test_index_xml_describes_all_six_tables(tmp_path):
    root = ET.fromstring(_build(tmp_path).read("index.xml"))
    files = {f.text for f in root.iter("File")}
    assert files == {"rechnungen.csv", "positionen.csv", "kunden.csv", "audit_log.csv",
                     "aufstellungen.csv", "aufstellung_anlagen.csv"}


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
    for fname in ("rechnungen.csv", "positionen.csv", "kunden.csv", "audit_log.csv",
                  "aufstellungen.csv", "aufstellung_anlagen.csv"):
        table = next(t for t in root.iter("Table") if t.find("./URL/File").text == fname)
        idx_cols = [c.find("Name").text for c in table.iter("VariableColumn")]
        header = next(csv.reader(io.StringIO(zf.read(fname).decode("utf-8-sig")), delimiter=";"))
        assert idx_cols == header, f"{fname}: index.xml-Spalten ≠ CSV-Header"


