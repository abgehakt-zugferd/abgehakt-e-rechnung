"""Archiv-Seite (#148).

Ein Knopf, der den Finder öffnet, ist aus einer Webseite heraus nicht baubar
(Browser navigieren nicht von `http://` auf `file://`), und der Container kennt
den Host-Pfad ohnehin nicht. Also wird die Ablage IN der App sichtbar.

Der sicherheitsrelevante Teil ist der Download: der Dateiname kommt aus der URL.
Ohne Eingrenzung wäre `/archiv/datei/pdfs/../../etc/passwd` ein Leseloch in den
ganzen Container.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

settings = get_settings()


@pytest.fixture
def dateien():
    """Legt je eine Datei in pdfs/, xml/ und temp/ an und räumt sie wieder weg."""
    marke = uuid.uuid4().hex[:8]
    namen = {
        "pdf": settings.storage_path / "pdfs" / f"RE-ARCHIV-{marke}.pdf",
        "xml": settings.storage_path / "xml" / f"RE-ARCHIV-{marke}.xml",
        "temp": settings.storage_path / "temp" / f"WEGWERF-{marke}.pdf",
    }
    for pfad in namen.values():
        pfad.parent.mkdir(parents=True, exist_ok=True)
    namen["pdf"].write_bytes(b"%PDF-1.4\n%archiv\n")
    namen["xml"].write_text("<CrossIndustryInvoice/>", encoding="utf-8")
    namen["temp"].write_bytes(b"%PDF-1.4\n%wegwerf\n")
    yield namen
    for pfad in namen.values():
        pfad.unlink(missing_ok=True)


def _client():
    return TestClient(app, follow_redirects=False)


def test_archiv_listet_pdf_und_xml(dateien):
    r = _client().get("/archiv")
    assert r.status_code == 200
    assert dateien["pdf"].name in r.text
    assert dateien["xml"].name in r.text


def test_archiv_zeigt_keine_wegwerfdateien(dateien):
    """`temp/` und `imports/` sind kein Archiv — dort liegen Vorschau-Reste und
    fremde Uploads."""
    r = _client().get("/archiv")
    assert dateien["temp"].name not in r.text


def test_filter_grenzt_auf_den_dateinamen_ein(dateien):
    r = _client().get(f"/archiv?q={dateien['pdf'].stem}")
    assert r.status_code == 200
    assert dateien["pdf"].name in r.text

    r_leer = _client().get("/archiv?q=gibtesnicht-xyz")
    assert dateien["pdf"].name not in r_leer.text


def test_download_liefert_die_datei(dateien):
    r = _client().get(f"/archiv/datei/pdfs/{dateien['pdf'].name}")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")

    r_xml = _client().get(f"/archiv/datei/xml/{dateien['xml'].name}")
    assert r_xml.status_code == 200
    assert b"CrossIndustryInvoice" in r_xml.content


def test_download_kennt_nur_pdfs_und_xml(dateien):
    """Kein Zugriff auf temp/ — auch nicht über den Bereichsnamen."""
    r = _client().get(f"/archiv/datei/temp/{dateien['temp'].name}")
    assert r.status_code == 404
    assert b"wegwerf" not in r.content


@pytest.mark.parametrize("name", [
    "../xml/beliebig.xml",
    "..%2F..%2Fetc%2Fpasswd",
    "/etc/passwd",
    "subdir/geheim.pdf",
])
def test_download_verweigert_pfadwechsel(dateien, name):
    r = _client().get(f"/archiv/datei/pdfs/{name}")
    assert r.status_code == 404, name
    assert b"root:" not in r.content


def test_download_unbekannter_datei_ist_404():
    r = _client().get("/archiv/datei/pdfs/gibtesnicht.pdf")
    assert r.status_code == 404


def test_menue_verlinkt_das_archiv(dateien):
    r = _client().get("/archiv")
    assert 'href="/archiv"' in r.text
