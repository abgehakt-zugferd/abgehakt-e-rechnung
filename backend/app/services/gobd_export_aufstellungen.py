"""Z3-Tabellen und Archivkopien der eigenständigen Aufstellungen."""
from sqlalchemy import Date, Numeric

from app.models.aufstellung import Aufstellung, AufstellungAnlage


def _spalten(model):
    # Kurs hat absichtlich keine feste Genauigkeit: als Text verlustfrei
    # exportieren, statt dem Importprogramm eine Rundung vorzuschreiben.
    return [(c.name, "D" if isinstance(c.type, Date) else
             ("N", c.type.scale) if isinstance(c.type, Numeric) and c.type.scale is not None
             else "A") for c in model.__table__.columns]


TABLES = [
    ("aufstellungen.csv", "Aufstellungen", "Abrechnungsaufstellungen", _spalten(Aufstellung) + [("kundennummer", "A"), ("kundenname", "A")]),
    ("aufstellung_anlagen.csv", "AufstellungAnlagen", "Anlagen der Aufstellungen", _spalten(AufstellungAnlage)),
]


def auswahl(db, von, bis):
    return (db.query(Aufstellung).filter(
        Aufstellung.status != "draft", Aufstellung.ausstellungsdatum >= von,
        Aufstellung.ausstellungsdatum <= bis,
    ).order_by(Aufstellung.nummer).all())


def _wert(row, feld, fmt):
    if feld in ("kundennummer", "kundenname"):
        return getattr(row.customer, "customer_number" if feld == "kundennummer" else "name", "")
    return fmt(getattr(row, feld))


def schreiben(zf, aufstellungen, storage_path, missing):
    from app.services.gobd_export_format import _csv_bytes, _fmt

    for (name, _, _, cols), rows in zip(TABLES, (
        aufstellungen, [anlage for a in aufstellungen for anlage in a.anlagen],
    )):
        header = [name for name, _ in cols]
        zf.writestr(name, "\ufeff" + _csv_bytes(header, [
            [_wert(row, feld, _fmt) for feld in header] for row in rows
        ]))
    for a in aufstellungen:
        pfad = storage_path / "aufstellungen" / (a.pdf_filename or "")
        if a.pdf_filename and pfad.is_file():
            zf.writestr("aufstellungen/" + a.pdf_filename, pfad.read_bytes())
        elif a.pdf_filename or a.status not in ("draft", "discarded"):
            missing.append(f"{a.nummer}: PDF fehlt ({a.pdf_filename or 'kein PDF hinterlegt'})")
    # Auswahl über die Anlagen der Aufstellungen, NICHT über das Annahmedatum:
    # Die Übergabe kann in einem früheren Prüfzeitraum angenommen worden sein.
    hashes = {anlage.sha256 for a in aufstellungen for anlage in a.anlagen}
    for sha in sorted(hashes):
        dateien = sorted((storage_path / "uebergaben").glob(f"*/anlagen/{sha}.xlsx"))
        datei = next((p for p in dateien if p.is_file()), None)
        if datei is None:
            missing.append(f"Aufstellungsanlage fehlt ({sha}.xlsx)")
        else:
            zf.writestr(f"aufstellung_anlagen/{sha}.xlsx", datei.read_bytes())


def dokumentation(anzahl):
    return f"""
- aufstellungen.csv ({anzahl} Zeilen): alle gespeicherten Felder der Aufstellungen,
  außer Entwürfen, nach Ausstellungsdatum einschließlich der Zeitraumgrenzen.
  Ohne Ausstellungsdatum erfolgt keine Zuordnung zum Zeitraum.
  kundennummer verknüpft kunden.csv; customer_id bleibt als Datenbank-ID erhalten.
  storniert_id verweist auf das Original (id), auch außerhalb des Zeitraums.
  Bei EUR sind kurs und zahlbetrag_eur leer, der Zahlbetrag entspricht netto.
  kurs ist verlustfreier Dezimaltext ohne vorgegebene Nachkommastellen.
- aufstellung_anlagen.csv: alle Anlagenfelder, aufstellung_id verweist auf id
  in aufstellungen.csv; sha256 identifiziert die unveränderte Archivkopie.
- aufstellungen/: archivierte PDFs der ausgewählten Aufstellungen.
- aufstellung_anlagen/: xlsx-Kopien, je SHA-256 einmal; fehlende PDFs und
  Anlagen stehen in fehlende_dateien.txt. Keine Berechnung von Eurobeträgen.
"""
