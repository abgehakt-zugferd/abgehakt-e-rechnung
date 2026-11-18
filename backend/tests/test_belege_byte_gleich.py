"""Download, Archiv und GoBD-Export liefern gespeicherte Belege byte-gleich aus.

Zusage: ein finalisierter Beleg ist unveränderlich. Diese Wege lesen die beim
Finalisieren geprüften und abgelegten Bytes und erzeugen oder prüfen nichts neu; eine
Neuprüfung mit einer neueren Mustang-Fassung dürfte einen festgeschriebenen Beleg nicht
nachträglich sperren. Der Test lässt Erzeugung und Mustang beim Abruf scheitern, damit
ein Neuerzeugen nicht unbemerkt durchgeht.
"""
import io
import zipfile
from unittest.mock import patch

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


@pytest.fixture
def nichts_neu():
    with patch("app.services.zugferd_xml.generate_xml", side_effect=AssertionError("neu erzeugt")), \
         patch("app.services.pdf_generator.generate_pdf", side_effect=AssertionError("neu erzeugt")), \
         patch("app.services.mustang.validate", side_effect=AssertionError("neu geprüft")), \
         patch("app.services.mustang.combine", side_effect=AssertionError("neu eingebettet")):
        yield


def test_pdf_download_liefert_die_gespeicherten_bytes(pg_session, beleg, nichts_neu):
    r = client(pg_session).get(f"/invoices/{beleg.id}/pdf")

    assert r.status_code == 200
    assert r.content == PDF


def test_archivdatei_liefert_die_gespeicherten_bytes(pg_session, beleg, nichts_neu):
    c = client(pg_session)

    assert c.get(f"/archiv/datei/pdfs/{beleg.invoice_number}.pdf").content == PDF
    assert c.get(f"/archiv/datei/xml/{beleg.invoice_number}.xml").content == XML


def test_gobd_export_enthaelt_die_gespeicherten_bytes(pg_session, beleg, nichts_neu):
    jahr = beleg.issue_date.isoformat()
    r = client(pg_session).get(f"/export/gobd?von={jahr}&bis={jahr}")

    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert zf.read(f"dokumente/{beleg.invoice_number}.pdf") == PDF
        assert zf.read(f"dokumente/{beleg.invoice_number}.xml") == XML
