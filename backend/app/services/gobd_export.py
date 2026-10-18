"""GoBD-Z3-Export: fertige Objektlisten als ZIP zusammenstellen."""
import io
import zipfile
from datetime import date
from pathlib import Path
from typing import Sequence

from app.models.customer import Customer
from app.models.invoice import AuditLog, Invoice
from app.models.uebergabe_eingang import UebergabeEingang
from app.services.gobd_export_format import (
    _rechnungen_csv, _positionen_csv, _kunden_csv, _audit_csv,
    _index_xml, _GDPDU_DTD, _dokumentation,
)
from app.services.gobd_export_dateien import rechnungsdateien, uebergabedateien
from app.services.gobd_export_aufstellungen import schreiben, dokumentation


def build_gobd_export(
    *,
    invoices: Sequence[Invoice],
    customers: Sequence[Customer],
    audit_rows: Sequence[AuditLog],
    uebergaben: Sequence[UebergabeEingang],
    storage_path: Path,
    date_from: date,
    date_to: date,
    company=None,
    aufstellungen=(),
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
        rechnungsdateien(zf, invoices, storage_path, missing)
        uebergabedateien(zf, uebergaben, storage_path, missing)
        schreiben(zf, aufstellungen, storage_path, missing)
        if missing:
            zf.writestr("fehlende_dateien.txt",
                        "Folgende Beleg-Dateien wurden nicht gefunden:\n"
                        + "\n".join(missing) + "\n")
        zf.writestr("dokumentation.txt", _dokumentation(
            date_from, date_to, len(invoices), len(customers), len(audit_rows)) + dokumentation(len(aufstellungen)))
    return buf.getvalue()
