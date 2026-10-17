"""
GoBD-Export-Router (/export/) als ECHTE Integration (#98 P1).

Ersetzt die frühere _FakeDB/_FakeQuery-Fassung, die SQLAlchemy-Filter in Python
nachbaute und bei unpassender Struktur per `except: pass` still durchwinkte
(False-Green — u. a. beim Draft-Ausschluss, der so gar nicht wirklich geprüft war).
Hier gegen pg_session: die Query-Filter (status != draft, Datumsbereich) laufen echt.
Die reine Listen→ZIP-Funktion ist in test_gobd_export.py abgedeckt.
"""
import io
import uuid
import zipfile
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _invoice(pg_session, number, status):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Router GmbH",
                 address_line1="Weg 1", zip_code="12345", city="Musterstadt", country="DE")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=number, customer_id=c.id,
                  issue_date=date(2026, 5, 1), due_date=date(2026, 5, 15), currency="EUR",
                  tax_category="S", status=status,
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"))
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Stunde",
                             quantity=Decimal("1"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
                             tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"))]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_export_page_renders_with_branding(pg_session):
    r = _client(pg_session).get("/export/")
    assert r.status_code == 200
    assert "GoBD" in r.text
    assert "Powered by" in r.text and "Quellcode" in r.text


def test_gobd_download_returns_zip_with_issued_invoice(pg_session):
    _invoice(pg_session, "RE-2026-042", "issued")
    r = _client(pg_session).get("/export/gobd?von=2026-01-01&bis=2026-12-31")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "gobd-export_2026-01-01_2026-12-31.zip" in r.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert "rechnungen.csv" in zf.namelist()
    assert b"RE-2026-042" in zf.read("rechnungen.csv")


def test_gobd_download_rejects_inverted_period(pg_session):
    r = _client(pg_session).get("/export/gobd?von=2026-12-31&bis=2026-01-01")
    assert r.status_code == 400


def test_gobd_download_excludes_draft_invoices(pg_session):
    """Entwürfe (draft) sind nicht buchungsreif und dürfen im GoBD-Export fehlen —
    mit echter DB-Query hat der status!=draft-Filter jetzt Zähne."""
    _invoice(pg_session, "RE-2026-001", "draft")
    _invoice(pg_session, "RE-2026-042", "issued")
    r = _client(pg_session).get("/export/gobd?von=2026-01-01&bis=2026-12-31")
    assert r.status_code == 200
    csv_content = zipfile.ZipFile(io.BytesIO(r.content)).read("rechnungen.csv").decode("utf-8")
    assert "RE-2026-001" not in csv_content   # Entwurf ausgeschlossen
    assert "RE-2026-042" in csv_content


def test_gobd_download_filtert_uebergabekopien_nach_annahmezeitpunkt(pg_session):
    """#160: Der Datentraeger eines Pruefzeitraums fuehrt nur die Uebergabekopien,
    die in IHM angenommen wurden. Massgeblich ist das Datum der ANNAHME
    (uebergabe_eingaenge.angenommen_am), nicht alles, was je im Ordner liegt."""
    import hashlib
    from datetime import datetime, timezone

    from app.config import get_settings
    from app.models.uebergabe_eingang import UebergabeEingang

    richtung = "tantiemen-app-nach-abgehakt"
    wurzel = get_settings().storage_path / "uebergaben" / richtung
    wurzel.mkdir(parents=True)
    innen, draussen = b'{"beleg": "innen"}', b'{"beleg": "draussen"}'
    (wurzel / f"{hashlib.sha256(innen).hexdigest()}.json").write_bytes(innen)
    (wurzel / f"{hashlib.sha256(draussen).hexdigest()}.json").write_bytes(draussen)
    for roh, angenommen_am in (
        (innen, datetime(2026, 5, 10, tzinfo=timezone.utc)),
        (draussen, datetime(2027, 1, 5, tzinfo=timezone.utc)),
    ):
        pg_session.add(UebergabeEingang(
            beleg_id=hashlib.sha256(roh).hexdigest()[:16],
            beleg_sha256=hashlib.sha256(roh).hexdigest(), absender="tantiemen-app",
            nutzlast_art="abrechnungsauftrag",
            erzeugt_am=datetime(2026, 5, 1, tzinfo=timezone.utc),
            angenommen_am=angenommen_am,
        ))
    pg_session.commit()

    r = _client(pg_session).get("/export/gobd?von=2026-01-01&bis=2026-12-31")

    namen = [
        n for n in zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        if n.startswith("uebergaben/")
    ]
    assert namen == [f"uebergaben/{richtung}/{hashlib.sha256(innen).hexdigest()}.json"]
