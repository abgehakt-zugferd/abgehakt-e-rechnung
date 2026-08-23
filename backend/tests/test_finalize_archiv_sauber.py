"""
Das Archiv bleibt sauber, solange die Finalisierung läuft (#12, #13, Dateiteil von #6).

`storage/pdfs/` und `storage/xml/` sind zweierlei zugleich: das GoBD-Archiv und das,
was die Archivansicht (`routers/archive.py`) ungefiltert aus dem Dateisystem vorliest.
Die ZUGFeRD-Pipeline legte ihre Zwischenstufen bisher genau dort ab. `_visual.pdf`,
`_pdfa.pdf` und die XML entstanden im Archiv, bevor feststand, ob überhaupt ein Beleg
daraus wird. Drei gemeldete Folgen, eine Ursache:

- Während Ghostscript und Mustang laufen, sind die Zwischenstufen sichtbar und
  herunterladbar (#13). Ein `_visual.pdf` ohne eingebettete XML ist keine gültige
  E-Rechnung, sieht in der Archivliste aber aus wie ein Beleg.
- Scheitert `db.commit()` nach erfolgreicher Pipeline, bleibt das fertige PDF im
  Archiv liegen, während die Datenbank `draft` sagt (#12). Der Fail-Pfad räumt auf,
  der Erfolgspfad hat kein `try`.
- Zwei gleichzeitige Läufe schreiben auf dieselben Zieldateien und löschen sich
  gegenseitig die Zwischenstufen weg (#6, Dateiteil; der fehlende Zeilen-Lock ist
  ein eigener Punkt).

Die Zusage dieser Datei: im Archiv erscheint nichts, was nicht ein fertiger,
committeter Beleg ist. Die Pipeline arbeitet woanders.

`storage/temp/` und nicht das Temp-Verzeichnis des Betriebssystems: nur innerhalb
desselben Dateisystems ist das Veröffentlichen ein atomares Umbenennen. `storage`
ist ein Mount, `/tmp` liegt im Container, ein `os.replace` darüber hinweg scheitert
mit `Invalid cross-device link`.
"""
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import get_settings
from app.main import app
from app.models.invoice import Invoice
from tests.helpers.finalize_pipeline import (
    cleanup,
    client,
    fake_generate_pdf,
    valid_draft,
    valid_mustang,
)

settings = get_settings()


def teardown_function():
    app.dependency_overrides.clear()


def _archiv_spuren(number: str) -> list[str]:
    """Alles, was zu dieser Rechnungsnummer im ARCHIV liegt (`pdfs/`, `xml/`)."""
    treffer = []
    for bereich in ("pdfs", "xml"):
        verzeichnis = settings.storage_path / bereich
        if verzeichnis.is_dir():
            treffer += [f"{bereich}/{p.name}" for p in verzeichnis.iterdir() if number in p.name]
    return sorted(treffer)


def _storage_spuren(number: str) -> list[str]:
    """Alles zu dieser Nummer unterhalb von `storage/`, auch Arbeitsverzeichnisse.

    Fängt den zweiten Fehler mit ab: die Pipeline aus dem Archiv herauszunehmen
    nützt nichts, wenn sie ihre Zwischenstufen stattdessen dauerhaft in `temp/`
    liegen lässt.
    """
    wurzel = settings.storage_path
    return sorted(str(p.relative_to(wurzel)) for p in wurzel.rglob("*")
                  if p.is_file() and number in p.name)


def test_archiv_bleibt_waehrend_der_pipeline_unberuehrt(pg_session):
    """Kein Zwischenprodukt im Archiv, solange Ghostscript und Mustang laufen (#13)."""
    inv = valid_draft(pg_session, prefix="RE-ARCH")
    number = inv.invoice_number
    gesehen: dict[str, list[str]] = {}

    def _pdfa(src, dst, title=None):
        gesehen["to_pdfa3"] = _archiv_spuren(number)
        Path(dst).write_bytes(b"%PDF-pdfa")
        return True

    def _combine(pdf_path, xml_path, out_path, *a, **k):
        gesehen["combine"] = _archiv_spuren(number)
        Path(out_path).write_bytes(b"%PDF-zugferd")
        return True

    try:
        with patch("app.routers.invoices.pdf_generator.generate_pdf", side_effect=fake_generate_pdf), \
             patch("app.routers.invoices.pdfa.gs_available", return_value=True), \
             patch("app.routers.invoices.pdfa.to_pdfa3", side_effect=_pdfa), \
             patch("app.routers.invoices.mustang.jar_available", return_value=True), \
             patch("app.routers.invoices.mustang.combine", side_effect=_combine), \
             patch("app.routers.invoices.mustang.validate", return_value=valid_mustang()):
            r = client(pg_session).post(f"/invoices/{inv.id}/finalisieren")

        assert r.status_code == 303, r.text
        assert gesehen["to_pdfa3"] == [], (
            "Vor dem PDF/A-Schritt lag schon etwas im Archiv: "
            f"{gesehen['to_pdfa3']}. Die Pipeline gehört nach storage/temp/."
        )
        assert gesehen["combine"] == [], (
            "Vor dem Mustang-Schritt lag schon etwas im Archiv: "
            f"{gesehen['combine']}. Die Pipeline gehört nach storage/temp/."
        )
    finally:
        cleanup(number)


def test_nach_erfolg_liegt_genau_der_fertige_beleg_im_archiv(pg_session):
    """Gutfall zum Test darüber: die Umlenkung darf den Beleg nicht verschlucken."""
    inv = valid_draft(pg_session, prefix="RE-ARCH")
    number = inv.invoice_number

    def _combine(pdf_path, xml_path, out_path, *a, **k):
        Path(out_path).write_bytes(b"%PDF-zugferd")
        return True

    def _pdfa(src, dst, title=None):
        Path(dst).write_bytes(b"%PDF-pdfa")
        return True

    try:
        with patch("app.routers.invoices.pdf_generator.generate_pdf", side_effect=fake_generate_pdf), \
             patch("app.routers.invoices.pdfa.gs_available", return_value=True), \
             patch("app.routers.invoices.pdfa.to_pdfa3", side_effect=_pdfa), \
             patch("app.routers.invoices.mustang.jar_available", return_value=True), \
             patch("app.routers.invoices.mustang.combine", side_effect=_combine), \
             patch("app.routers.invoices.mustang.validate", return_value=valid_mustang()):
            r = client(pg_session).post(f"/invoices/{inv.id}/finalisieren")

        assert r.status_code == 303, r.text
        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.status == "issued"
        assert row.pdf_filename == f"{number}.pdf"
        assert _storage_spuren(number) == [f"pdfs/{number}.pdf", f"xml/{number}.xml"], (
            "Nach erfolgreichem Finalisieren gehören genau zwei Dateien in den "
            "Bestand: der Beleg und seine XML. Kein Zwischenprodukt, kein Rest im "
            "Arbeitsverzeichnis."
        )
    finally:
        cleanup(number)


def test_kein_beleg_im_archiv_wenn_der_commit_scheitert(pg_session):
    """Die Pipeline gelingt, `db.commit()` nicht: das Archiv bleibt leer (#12).

    Der bisherige Erfolgspfad setzt `pdf_filename` und `status`, committet danach
    und hat kein `try`. Fällt die Datenbank zwischen Pipeline und Commit aus, liegt
    ein Beleg mit echter Rechnungsnummer im GoBD-Archiv, den die Datenbank nicht
    kennt. Wiederholbar ist das nicht: der zweite Versuch würde ihn überschreiben,
    und bis dahin steht er in der Archivansicht.
    """
    inv = valid_draft(pg_session, prefix="RE-ARCH")
    number = inv.invoice_number
    echter_commit = pg_session.commit

    def _commit_scheitert():
        raise RuntimeError("Verbindung zur Datenbank verloren")

    def _pdfa(src, dst, title=None):
        Path(dst).write_bytes(b"%PDF-pdfa")
        return True

    def _combine(pdf_path, xml_path, out_path, *a, **k):
        Path(out_path).write_bytes(b"%PDF-zugferd")
        return True

    try:
        with patch("app.routers.invoices.pdf_generator.generate_pdf", side_effect=fake_generate_pdf), \
             patch("app.routers.invoices.pdfa.gs_available", return_value=True), \
             patch("app.routers.invoices.pdfa.to_pdfa3", side_effect=_pdfa), \
             patch("app.routers.invoices.mustang.jar_available", return_value=True), \
             patch("app.routers.invoices.mustang.combine", side_effect=_combine), \
             patch("app.routers.invoices.mustang.validate", return_value=valid_mustang()):
            pg_session.commit = _commit_scheitert
            with pytest.raises(RuntimeError):
                client(pg_session).post(f"/invoices/{inv.id}/finalisieren")

        pg_session.commit = echter_commit
        assert _storage_spuren(number) == [], (
            "Nach einem gescheiterten Commit liegen verwaiste Dateien im Bestand: "
            f"{_storage_spuren(number)}. Die Datenbank kennt keinen Beleg dazu."
        )
    finally:
        pg_session.commit = echter_commit
        cleanup(number)
