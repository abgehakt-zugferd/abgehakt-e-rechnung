"""Download, Archiv und GoBD-Export liefern gespeicherte Belege byte-gleich aus.

Zusage: ein finalisierter Beleg ist unveränderlich. Diese Wege lesen die beim
Finalisieren geprüften und abgelegten Bytes und erzeugen oder prüfen nichts neu; eine
Neuprüfung mit einer neueren Mustang-Fassung dürfte einen festgeschriebenen Beleg nicht
nachträglich sperren.

Die Abrufwege (PDF-Download, Archivdatei, GoBD) lesen nur Storage bzw. die DB-Spalte
`zugferd_xml` — sie importieren keine Erzeuger. Markerbytes in den Fixtures beweisen
die Bytegleichheit; dekorative Patches auf unimportierte Module fehlen deshalb absichtlich.
"""
import io
import zipfile

import pytest

from app.config import get_settings
from tests.helpers.finalize_pipeline import cleanup, client, valid_draft

PDF = b"%PDF-1.7 gespeicherte Bytes \x00\xff\x10 Ende"
XML = b"<?xml version='1.0'?><gespeichert>\xc3\xa4</gespeichert>"


@pytest.fixture
def beleg(pg_session):
    inv = valid_draft(pg_session, prefix="RE-BYTES")
    nummer = inv.invoice_number
    pfade = get_settings().storage_path
    (pfade / "pdfs").mkdir(parents=True, exist_ok=True)
    (pfade / "xml").mkdir(parents=True, exist_ok=True)
    (pfade / "pdfs" / f"{nummer}.pdf").write_bytes(PDF)
    (pfade / "xml" / f"{nummer}.xml").write_bytes(XML)
    inv.status = "issued"
    inv.pdf_filename = f"{nummer}.pdf"
    inv.zugferd_xml = XML.decode("utf-8")
    pg_session.commit()
    yield inv
    cleanup(nummer)


def test_pdf_download_liefert_die_gespeicherten_bytes(pg_session, beleg):
    r = client(pg_session).get(f"/invoices/{beleg.id}/pdf")

    assert r.status_code == 200
    assert r.content == PDF


def test_archivdatei_liefert_die_gespeicherten_bytes(pg_session, beleg):
    c = client(pg_session)

    assert c.get(f"/archiv/datei/pdfs/{beleg.invoice_number}.pdf").content == PDF
    assert c.get(f"/archiv/datei/xml/{beleg.invoice_number}.xml").content == XML


def test_gobd_export_enthaelt_die_gespeicherten_bytes(pg_session, beleg):
    jahr = beleg.issue_date.isoformat()
    r = client(pg_session).get(f"/export/gobd?von={jahr}&bis={jahr}")

    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.read(f"dokumente/{beleg.invoice_number}.pdf") == PDF
        assert zf.read(f"dokumente/{beleg.invoice_number}.xml") == XML


def test_gobd_export_nimmt_xml_aus_db_wenn_datei_fehlt(pg_session, beleg):
    """GoBD-Ersatzzweig: fehlt die XML-Datei, kommen die DB-Bytes unverändert.

    Kein Erzeuger auf diesem Weg: der Export liest nur Storage/DB (siehe
    app/services/gobd_export_dateien.py). Die Markerbytes (`gespeichert` inkl.
    Nicht-ASCII) wären kein Generator-Output — Bytegleichheit belegt den Ersatzzweig.
    """
    xml_pfad = get_settings().storage_path / "xml" / f"{beleg.invoice_number}.xml"
    xml_pfad.unlink()
    assert not xml_pfad.exists()

    jahr = beleg.issue_date.isoformat()
    r = client(pg_session).get(f"/export/gobd?von={jahr}&bis={jahr}")

    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.read(f"dokumente/{beleg.invoice_number}.xml") == XML
        assert zf.read(f"dokumente/{beleg.invoice_number}.pdf") == PDF
