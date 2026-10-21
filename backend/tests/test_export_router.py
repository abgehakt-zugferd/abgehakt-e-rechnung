"""
GoBD-Export-Router (/export/) als ECHTE Integration (#98 P1).

Ersetzt die frühere _FakeDB/_FakeQuery-Fassung, die SQLAlchemy-Filter in Python
nachbaute und bei unpassender Struktur per `except: pass` still durchwinkte
(False-Green — u. a. beim Draft-Ausschluss, der so gar nicht wirklich geprüft war).
Hier gegen pg_session: die Query-Filter (status != draft, Datumsbereich) laufen echt.
Die reine Listen→ZIP-Funktion ist in test_gobd_export.py abgedeckt.
"""
import hashlib
import io
import json
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import AuditLog, Invoice, InvoiceItem
from app.models.uebergabe_eingang import UebergabeEingang
from app.zeit import ZEITZONE


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
    # exist_ok: Der Wegwerf-Speicher der Sitzung ist gemeinsam; wer vor diesem
    # Test uebergaben kopiert hat (z. B. der Knopf eines Uebergabe-Tests), hat
    # das Verzeichnis schon angelegt. Der Befund unten zaehlt nur die Zeilen
    # mit Annahme im Zeitraum - Bestand aus anderen Tests faellt nicht auf.
    wurzel.mkdir(parents=True, exist_ok=True)
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


def _berlin(tag: date, stunde: int, minute: int) -> datetime:
    """Berliner Uhrzeit eines Kalendertags als aware Zeitstempel — so steht der
    Wert in einer timestamptz-Spalte; Postgres rechnet beim Speichern selbst um."""
    return datetime(tag.year, tag.month, tag.day, stunde, minute, tzinfo=ZEITZONE)


def _audit_eintrag(pg_session, schluessel: str, changed_at: datetime):
    pg_session.add(AuditLog(
        table_name="invoices", record_id=f"PROBE-{schluessel}", action="update",
        changed_at=changed_at,
        old_values={"status": "entwurf"}, new_values={"status": "ausgestellt"},
    ))


def _uebergabe_eintrag(pg_session, wurzel, schluessel: str, angenommen_am: datetime) -> str:
    """Annahme-Zeile plus ihre Aufbewahrungskopie im Speicher; gibt den Hash
    zurueck, unter dem die Kopie im ZIP zu finden sein muss."""
    roh = json.dumps({"beleg": schluessel}).encode()
    sha = hashlib.sha256(roh).hexdigest()
    (wurzel / f"{sha}.json").write_bytes(roh)
    pg_session.add(UebergabeEingang(
        beleg_id=f"probe-{schluessel}", beleg_sha256=sha,
        absender="beispiel-app", nutzlast_art="abrechnungsauftrag",
        erzeugt_am=datetime(2026, 1, 1, tzinfo=timezone.utc),
        angenommen_am=angenommen_am,
    ))
    return sha


@pytest.mark.parametrize("von,bis", [
    (date(2026, 1, 10), date(2026, 1, 20)),   # Winter: Berlin = UTC+1
    (date(2026, 6, 10), date(2026, 6, 20)),   # Sommer: Berlin = UTC+2
], ids=["winter", "sommer"])
def test_gobd_zeitstempelfilter_folgen_berlin_statt_sitzungszone(pg_session, von, bis):
    """#179: Protokoll- und Uebergabezeilen zaehlen zum Kalendertag in
    Europe/Berlin. Die Test-DB laeuft mit Sitzungszone UTC: ein Vergleich des
    date-Parameters mit timestamptz setzte die Grenze auf UTC-Mitternacht und
    verschoebe den Berliner Tagesrand um eine Stunde (Winter) bzw. zwei
    (Sommer). Zugesichert wird auf den ZIP-Inhalt, nicht auf Zaehler."""
    randzeiten = {
        "vortag":    _berlin(von - timedelta(days=1), 23, 30),  # draussen
        "anfang":    _berlin(von, 0, 30),                       # drin
        "ende":      _berlin(bis, 23, 30),                      # drin
        "folgetag":  _berlin(bis + timedelta(days=1), 0, 30),   # draussen
    }
    wurzel = get_settings().storage_path / "uebergaben" / "beispiel-app-nach-abgehakt"
    # exist_ok wie oben: der Wegwerf-Speicher der Sitzung ist gemeinsam; die
    # Zusicherung unten fragt gezielt die Hashes DIESER Zeilen ab.
    wurzel.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for schluessel, zeitpunkt in randzeiten.items():
        _audit_eintrag(pg_session, schluessel, zeitpunkt)
        hashes[schluessel] = _uebergabe_eintrag(pg_session, wurzel, schluessel, zeitpunkt)
    pg_session.commit()

    r = _client(pg_session).get(f"/export/gobd?von={von.isoformat()}&bis={bis.isoformat()}")

    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    protokoll = zf.read("audit_log.csv").decode("utf-8")
    for schluessel in ("anfang", "ende"):
        assert f"PROBE-{schluessel}" in protokoll, (
            f"{schluessel}-Eintrag fehlt im Pruefprotokoll")
    for schluessel in ("vortag", "folgetag"):
        assert f"PROBE-{schluessel}" not in protokoll, (
            f"{schluessel}-Eintrag gehoert nicht in den Zeitraum")
    namen = [n for n in zf.namelist() if n.startswith("uebergaben/")]
    for schluessel in ("anfang", "ende"):
        assert any(hashes[schluessel] in n for n in namen), (
            f"{schluessel}-Uebergabekopie fehlt im ZIP")
    for schluessel in ("vortag", "folgetag"):
        assert not any(hashes[schluessel] in n for n in namen), (
            f"{schluessel}-Uebergabekopie gehoert nicht in den Zeitraum")
