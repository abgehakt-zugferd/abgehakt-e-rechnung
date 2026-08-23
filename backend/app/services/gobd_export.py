"""
GoBD-Datenexport (Z3 / Datenträgerüberlassung) für Betriebsprüfungen.

Reine Funktion: bekommt fertige Objektlisten (Queries macht der Router) und
liefert ein ZIP als Bytes. CSV-Konventionen: UTF-8 mit BOM, Semikolon,
ISO-Daten, Dezimalpunkt — beschrieben in dokumentation.txt im ZIP.

Enthält den GDPdU-Beschreibungsstandard (index.xml + gdpdu.dtd, #52), damit die
Prüfsoftware IDEA den Z3-Export einlesen kann. ⚠️ index.xml/DTD sind die lokale
Spec — verbindlich ist erst ein IDEA-Testimport (analog DATEV-Golden-Test);
Encoding UTF-8(-BOM) ist bei IDEA gegen ANSI zu prüfen.
"""
import csv
import io
import json
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Sequence
from xml.sax.saxutils import escape

from app.branding import PRODUCT_NAME
from app.models.customer import Customer
from app.models.invoice import AuditLog, Invoice

# Spaltenspezifikation je Tabelle: (Name, Typ). Typ: "A"=AlphaNumeric,
# "D"=Date (YYYY-MM-DD), ("N", Nachkommastellen)=Numeric. EINZIGE Quelle für
# CSV-Header UND index.xml → beide können nicht auseinanderlaufen (#52).
_RECHNUNGEN_COLS = [
    ("rechnungsnummer", "A"), ("rechnungstyp", "A"), ("status", "A"),
    ("ausstellungsdatum", "D"), ("faelligkeitsdatum", "D"), ("leistungsdatum", "D"),
    ("kundennummer", "A"), ("kundenname", "A"),
    ("nettobetrag", ("N", 2)), ("steuerbetrag", ("N", 2)), ("bruttobetrag", ("N", 2)),
    ("waehrung", "A"), ("steuerkategorie", "A"), ("original_rechnungsnummer", "A"),
    ("aufbewahrung_bis", "D"), ("datev_versendet_am", "A"), ("erstellt_am", "A"),
]
_POSITIONEN_COLS = [
    ("rechnungsnummer", "A"), ("position", ("N", 0)), ("beschreibung", "A"),
    ("einheit", "A"), ("menge", ("N", 4)), ("einzelpreis", ("N", 4)),
    ("steuersatz", ("N", 2)), ("netto", ("N", 2)), ("steuer", ("N", 2)),
    ("brutto", ("N", 2)),
]
_KUNDEN_COLS = [
    ("kundennummer", "A"), ("name", "A"), ("adresszeile1", "A"), ("adresszeile2", "A"),
    ("plz", "A"), ("ort", "A"), ("land", "A"), ("ust_idnr", "A"), ("email", "A"),
    ("geloescht_am", "A"),
]
_AUDIT_COLS = [
    ("geaendert_am", "A"), ("tabelle", "A"), ("datensatz_id", "A"), ("aktion", "A"),
    ("alte_werte", "A"), ("neue_werte", "A"),
]


def _names(cols) -> list[str]:
    return [name for name, _ in cols]


def _csv_bytes(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(header)
    writer.writerows(rows)
    return buf.getvalue()


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _rechnungen_csv(invoices: Sequence[Invoice]) -> str:
    header = _names(_RECHNUNGEN_COLS)
    rows = []
    for inv in invoices:
        original = inv.original_invoice.invoice_number if inv.original_invoice else ""
        rows.append([
            inv.invoice_number, _fmt(inv.invoice_type), inv.status,
            _fmt(inv.issue_date), _fmt(inv.due_date), _fmt(inv.delivery_date),
            inv.customer.customer_number if inv.customer else "",
            inv.customer.name if inv.customer else "",
            _fmt(inv.net_total), _fmt(inv.tax_total), _fmt(inv.gross_total),
            inv.currency, inv.tax_category, original,
            _fmt(inv.archive_until), _fmt(inv.datev_sent_at), _fmt(inv.created_at),
        ])
    return _csv_bytes(header, rows)


def _positionen_csv(invoices: Sequence[Invoice]) -> str:
    header = _names(_POSITIONEN_COLS)
    rows = []
    for inv in invoices:
        for item in inv.items:
            rows.append([
                inv.invoice_number, item.position, item.description, item.unit,
                _fmt(item.quantity), _fmt(item.unit_price), _fmt(item.tax_rate),
                _fmt(item.net_amount), _fmt(item.tax_amount), _fmt(item.gross_amount),
            ])
    return _csv_bytes(header, rows)


def _kunden_csv(customers: Sequence[Customer]) -> str:
    header = _names(_KUNDEN_COLS)
    rows = [[
        c.customer_number, c.name, c.address_line1, _fmt(c.address_line2),
        c.zip_code, c.city, c.country, _fmt(c.vat_id), _fmt(c.email),
        _fmt(c.deleted_at),
    ] for c in customers]
    return _csv_bytes(header, rows)


def _audit_csv(audit_rows: Sequence[AuditLog]) -> str:
    header = _names(_AUDIT_COLS)
    rows = [[
        _fmt(a.changed_at), a.table_name, a.record_id, a.action,
        json.dumps(a.old_values, ensure_ascii=False) if a.old_values else "",
        json.dumps(a.new_values, ensure_ascii=False) if a.new_values else "",
    ] for a in audit_rows]
    return _csv_bytes(header, rows)


def _dokumentation(date_from: date, date_to: date,
                   n_invoices: int, n_customers: int, n_audit: int) -> str:
    return f"""GoBD-Datenexport (Z3 / Datenträgerüberlassung)
================================================

Zeitraum: {date_from.isoformat()} bis {date_to.isoformat()}
Erstellt am: {datetime.now().isoformat(timespec="seconds")}

Konventionen
------------
- Zeichensatz: UTF-8 (mit BOM)
- Trennzeichen: Semikolon (;)
- Datumsformat: ISO-8601 (JJJJ-MM-TT)
- Beträge: Dezimalpunkt, zwei Nachkommastellen, Währung siehe Spalte "waehrung"
- Leere Felder: nicht vorhandener Wert

Enthaltene Tabellen
-------------------
- rechnungen.csv  ({n_invoices} Zeilen): Rechnungskopfdaten aller Belege mit
  Status issued, paid, cancelled oder discarded im Zeitraum (Ausstellungsdatum).
  Gestellte Belege (issued/paid/cancelled) sind Buchungsbelege; verworfene Entwuerfe
  (discarded) stehen mit in der CSV, weil ihre Nummer schon beim Anlegen vergeben
  wurde und die Zeile die Nummernluecke fuer den Pruefer erklaert. Stornos/
  Gutschriften referenzieren das Original in "original_rechnungsnummer".
- positionen.csv: Einzelpositionen, verknüpft über "rechnungsnummer".
- kunden.csv      ({n_customers} Zeilen): Stammdaten der referenzierten Kunden
  (inkl. soft-gelöschter, erkennbar an "geloescht_am").
- audit_log.csv   ({n_audit} Zeilen): Änderungsprotokoll (GoBD-Nachvollziehbarkeit);
  alte/neue Werte als JSON.
- dokumente/: Original-Belege — ZUGFeRD-PDF und E-Rechnungs-XML je Rechnung.
  Fehlende Dateien sind in fehlende_dateien.txt aufgeführt.

Erzeugt mit {PRODUCT_NAME}.
"""


_GDPDU_DTD = """<!-- GDPdU-Beschreibungsstandard (Datentraegerueberlassung Z3, #52).
     Struktur nach dem amtlichen Beschreibungsstandard. Verbindlich ist der
     IDEA-Testimport + Abgleich mit der offiziellen DTD. -->
<!ELEMENT DataSet (Version, DataSupplier?, Media+)>
<!ELEMENT Version (#PCDATA)>
<!ELEMENT DataSupplier (Name?, Location?, Comment?)>
<!ELEMENT Name (#PCDATA)>
<!ELEMENT Location (#PCDATA)>
<!ELEMENT Comment (#PCDATA)>
<!ELEMENT Media (Name, Table+)>
<!ELEMENT Table (URL, Name, Description?, Validity?, DecimalSymbol?, DigitGroupingSymbol?, VariableLength)>
<!ELEMENT URL (File)>
<!ELEMENT File (#PCDATA)>
<!ELEMENT Description (#PCDATA)>
<!ELEMENT Validity (Range)>
<!ELEMENT Range (From, To)>
<!ELEMENT From (#PCDATA)>
<!ELEMENT To (#PCDATA)>
<!ELEMENT DecimalSymbol (#PCDATA)>
<!ELEMENT DigitGroupingSymbol (#PCDATA)>
<!ELEMENT VariableLength (ColumnDelimiter, RecordDelimiter, TextEncapsulator?, VariablePrimaryKey?, VariableColumn+)>
<!ELEMENT ColumnDelimiter (#PCDATA)>
<!ELEMENT RecordDelimiter (#PCDATA)>
<!ELEMENT TextEncapsulator (#PCDATA)>
<!ELEMENT VariablePrimaryKey (Name)>
<!ELEMENT VariableColumn (Name, Description?, (Numeric | AlphaNumeric | Date))>
<!ELEMENT Numeric (Accuracy?)>
<!ELEMENT Accuracy (#PCDATA)>
<!ELEMENT AlphaNumeric EMPTY>
<!ELEMENT Date (Format)>
<!ELEMENT Format (#PCDATA)>
"""

_TABLES = [
    ("rechnungen.csv", "Rechnungen", "Rechnungskopfdaten", _RECHNUNGEN_COLS),
    ("positionen.csv", "Positionen", "Rechnungspositionen", _POSITIONEN_COLS),
    ("kunden.csv", "Kunden", "Debitoren-Stammdaten", _KUNDEN_COLS),
    ("audit_log.csv", "AuditLog", "Aenderungsprotokoll (GoBD)", _AUDIT_COLS),
]


def _column_type_xml(typ) -> str:
    if typ == "A":
        return "<AlphaNumeric/>"
    if typ == "D":
        return "<Date><Format>YYYY-MM-DD</Format></Date>"
    return f"<Numeric><Accuracy>{typ[1]}</Accuracy></Numeric>"  # ("N", accuracy)


def _index_xml(date_from: date, date_to: date, company=None) -> str:
    """GDPdU-Steuerungsdatei: beschreibt Tabellen, Spalten, Typen, Trennzeichen —
    ohne sie kann IDEA den Export nicht einlesen (#52)."""
    frm, to = date_from.isoformat(), date_to.isoformat()
    tables_xml = []
    for fname, tname, desc, cols in _TABLES:
        col_xml = "\n".join(
            f"          <VariableColumn><Name>{name}</Name>"
            f"{_column_type_xml(typ)}</VariableColumn>"
            for name, typ in cols
        )
        tables_xml.append(
            f"""      <Table>
        <URL><File>{fname}</File></URL>
        <Name>{tname}</Name>
        <Description>{escape(desc)}</Description>
        <Validity><Range><From>{frm}</From><To>{to}</To></Range></Validity>
        <DecimalSymbol>.</DecimalSymbol>
        <DigitGroupingSymbol></DigitGroupingSymbol>
        <VariableLength>
          <ColumnDelimiter>;</ColumnDelimiter>
          <RecordDelimiter>&#13;&#10;</RecordDelimiter>
          <TextEncapsulator>"</TextEncapsulator>
{col_xml}
        </VariableLength>
      </Table>"""
        )
    tables = "\n".join(tables_xml)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE DataSet SYSTEM "gdpdu.dtd">\n'
        "<DataSet>\n"
        "  <Version>1.0</Version>\n"
        # GDPdU: DataSupplier ist der STEUERPFLICHTIGE, nicht die Software, die den
        # Datenträger erzeugt hat. Stünde hier der Programmname, bekäme der
        # Betriebsprüfer einen Export, der einen Dritten als Datenlieferanten nennt.
        "  <DataSupplier>\n"
        f"    <Name>{escape(getattr(company, 'name', '') or '')}</Name>\n"
        f"    <Location>{escape(getattr(company, 'city', '') or '')}</Location>\n"
        f"    <Comment>GoBD-Z3-Datenexport {frm} bis {to}</Comment>\n"
        "  </DataSupplier>\n"
        "  <Media>\n"
        f"    <Name>GoBD-Datenexport {frm} bis {to}</Name>\n"
        f"{tables}\n"
        "  </Media>\n"
        "</DataSet>\n"
    )


def build_gobd_export(
    *,
    invoices: Sequence[Invoice],
    customers: Sequence[Customer],
    audit_rows: Sequence[AuditLog],
    storage_path: Path,
    date_from: date,
    date_to: date,
    company=None,
) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        bom = "﻿"  # UTF-8-BOM, damit Excel die Umlaute korrekt öffnet
        zf.writestr("rechnungen.csv", bom + _rechnungen_csv(invoices))
        zf.writestr("positionen.csv", bom + _positionen_csv(invoices))
        zf.writestr("kunden.csv", bom + _kunden_csv(customers))
        zf.writestr("audit_log.csv", bom + _audit_csv(audit_rows))
        # GDPdU-Beschreibungsstandard — ohne index.xml kann IDEA nichts einlesen (#52).
        zf.writestr("index.xml", _index_xml(date_from, date_to, company))
        zf.writestr("gdpdu.dtd", _GDPDU_DTD)
        missing: list[str] = []
        for inv in invoices:
            if inv.pdf_filename:
                pdf_path = storage_path / "pdfs" / inv.pdf_filename
                if pdf_path.exists():
                    zf.writestr(f"dokumente/{inv.pdf_filename}", pdf_path.read_bytes())
                else:
                    missing.append(f"{inv.invoice_number}: PDF fehlt ({inv.pdf_filename})")
            # `discarded` (#145) ist ein verworfener ENTWURF und hat wie `draft` nie
            # ein PDF gehabt — das ist kein fehlender Beleg. Die Zeile bleibt trotzdem
            # im Export: sie ist das, was die Nummernlücke erklärt.
            elif inv.status not in ("draft", "discarded"):
                missing.append(f"{inv.invoice_number}: kein PDF hinterlegt")

            xml_name = f"{inv.invoice_number}.xml"
            xml_path = storage_path / "xml" / xml_name
            if xml_path.exists():
                zf.writestr(f"dokumente/{xml_name}", xml_path.read_bytes())
            elif inv.zugferd_xml:
                # DB ist Primärspeicher der XML (docs/ARCHITEKTUR.md) — Datei nur Zweitablage.
                zf.writestr(f"dokumente/{xml_name}", inv.zugferd_xml)
            elif inv.status not in ("draft", "discarded"):
                missing.append(f"{inv.invoice_number}: XML fehlt ({xml_name})")

        if missing:
            zf.writestr("fehlende_dateien.txt",
                        "Folgende Beleg-Dateien wurden nicht gefunden:\n"
                        + "\n".join(missing) + "\n")
        zf.writestr("dokumentation.txt", _dokumentation(
            date_from, date_to, len(invoices), len(customers), len(audit_rows)))
    return buf.getvalue()
