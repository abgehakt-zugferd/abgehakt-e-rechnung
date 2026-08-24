"""Archiv-Seite (#148).

Ein Knopf, der den Finder öffnet, ist aus einer Webseite heraus nicht baubar
(Browser navigieren nicht von `http://` auf `file://`), und der Container kennt
den Host-Pfad ohnehin nicht. Also wird die Ablage IN der App sichtbar.

Der sicherheitsrelevante Teil ist der Download: der Dateiname kommt aus der URL.
Ohne Eingrenzung wäre `/archiv/datei/pdfs/../../etc/passwd` ein Leseloch in den
ganzen Container.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice

settings = get_settings()


@pytest.fixture
def dateien(pg_session):
    """Legt je eine Datei in pdfs/, xml/ und temp/ an und räumt sie wieder weg."""
    marke = uuid.uuid4().hex[:8]
    pdf_name = f"RE-ARCHIV-{marke}.pdf"
    xml_name = f"RE-ARCHIV-{marke}.xml"
    namen = {
        "pdf": settings.storage_path / "pdfs" / pdf_name,
        "xml": settings.storage_path / "xml" / xml_name,
        "temp": settings.storage_path / "temp" / f"WEGWERF-{marke}.pdf",
    }
    for pfad in namen.values():
        pfad.parent.mkdir(parents=True, exist_ok=True)
    namen["pdf"].write_bytes(b"%PDF-1.4\n%archiv\n")
    namen["xml"].write_text("<CrossIndustryInvoice/>", encoding="utf-8")
    namen["temp"].write_bytes(b"%PDF-1.4\n%wegwerf\n")

    c = Customer(customer_number=f"K-{marke}", name="Archiv Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"RE-ARCHIV-{marke}", customer_id=c.id,
                  issue_date=date(2026, 7, 1), due_date=date(2026, 7, 15), currency="EUR",
                  net_total=Decimal("100"), tax_total=Decimal("19"), gross_total=Decimal("119"),
                  status="issued", pdf_filename=pdf_name)
    pg_session.add(inv)
    pg_session.commit()

    yield namen
    for pfad in namen.values():
        pfad.unlink(missing_ok=True)


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def teardown_function():
    app.dependency_overrides.clear()


def test_archiv_listet_pdf_und_xml(dateien, pg_session):
    r = _client(pg_session).get("/archiv")
    assert r.status_code == 200
    assert dateien["pdf"].name in r.text
    assert dateien["xml"].name in r.text


def test_archiv_zeigt_keine_waisen_ohne_db_bezug(pg_session):
    """#13: Dateien auf der Platte ohne Beleg in der DB bleiben unsichtbar."""
    marke = uuid.uuid4().hex[:8]
    pdf = settings.storage_path / "pdfs" / f"WAISE-{marke}.pdf"
    pdf.parent.mkdir(parents=True, exist_ok=True)
    pdf.write_bytes(b"%PDF-orphan\n")
    try:
        r = _client(pg_session).get("/archiv")
        assert r.status_code == 200
        assert pdf.name not in r.text
    finally:
        pdf.unlink(missing_ok=True)


def test_archiv_zeigt_keine_wegwerfdateien(dateien, pg_session):
    """`temp/` und `imports/` sind kein Archiv — dort liegen Vorschau-Reste und
    fremde Uploads."""
    r = _client(pg_session).get("/archiv")
    assert dateien["temp"].name not in r.text


def test_filter_grenzt_auf_den_dateinamen_ein(dateien, pg_session):
    client = _client(pg_session)
    r = client.get(f"/archiv?q={dateien['pdf'].stem}")
    assert r.status_code == 200
    assert dateien["pdf"].name in r.text

    r_leer = client.get("/archiv?q=gibtesnicht-xyz")
    assert dateien["pdf"].name not in r_leer.text


def test_download_liefert_die_datei(dateien, pg_session):
    client = _client(pg_session)
    r = client.get(f"/archiv/datei/pdfs/{dateien['pdf'].name}")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")

    r_xml = client.get(f"/archiv/datei/xml/{dateien['xml'].name}")
    assert r.status_code == 200
    assert b"CrossIndustryInvoice" in r_xml.content


def test_download_kennt_nur_pdfs_und_xml(dateien, pg_session):
    """Kein Zugriff auf temp/ — auch nicht über den Bereichsnamen."""
    r = _client(pg_session).get(f"/archiv/datei/temp/{dateien['temp'].name}")
    assert r.status_code == 404
    assert b"wegwerf" not in r.content


@pytest.mark.parametrize("name", [
    "../xml/beliebig.xml",
    "..%2F..%2Fetc%2Fpasswd",
    "/etc/passwd",
    "subdir/geheim.pdf",
])
def test_download_verweigert_pfadwechsel(dateien, pg_session, name):
    r = _client(pg_session).get(f"/archiv/datei/pdfs/{name}")
    assert r.status_code == 404, name
    assert b"root:" not in r.content


def test_download_unbekannter_datei_ist_404(pg_session):
    r = _client(pg_session).get("/archiv/datei/pdfs/gibtesnicht.pdf")
    assert r.status_code == 404


def test_menue_verlinkt_das_archiv(dateien, pg_session):
    r = _client(pg_session).get("/archiv")
    assert 'href="/archiv"' in r.text
