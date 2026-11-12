"""Zeitstempel erscheinen in Ortszeit Europe/Berlin, nicht in UTC.

Naht: die gerenderten Seiten (TestClient) und die beiden Darstellungsfilter.
Bezugspunkt ist immer 23:30 UTC am 11.11.2026; in Berlin (UTC+1) ist das der
12.11.2026, 00:30 Uhr. Wer UTC ausgibt, zeigt den falschen Tag.
"""
import os
import time
from datetime import datetime, timezone

from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.darstellung import datum_de, zeitpunkt_de
from app.main import app
from app.models.app_config import AppConfig
from app.models.invoice import InvoiceSendLog
from app.models.invoice_nebenmodelle import ValidationResult
from tests.factories_aufstellung import speichere_aufstellung
from tests.helpers.ersatzrechnung import beleg, kunde
from tests.test_archive_router import dateien  # noqa: F401 (Fixture)

NACHTS = datetime(2026, 11, 11, 23, 30, 5, tzinfo=timezone.utc)


@pytest.fixture
def web(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def _smtp(pg_session):
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first() or AppConfig(id=1)
    cfg.smtp_host = "smtp.example.de"
    pg_session.add(cfg)
    pg_session.commit()


def _versendete_rechnung(pg_session):
    inv = beleg(pg_session, kunde(pg_session))
    inv.datev_sent_at = NACHTS
    pg_session.commit()
    return inv


# -- Filter ---------------------------------------------------------------

def test_filter_nehmen_naive_zeitstempel_als_utc():
    naiv = datetime(2026, 11, 11, 23, 30)
    assert zeitpunkt_de(naiv) == "12.11.2026 00:30"
    assert datum_de(naiv) == "12.11.2026"


def test_datum_de_kann_die_kurzform():
    assert datum_de(NACHTS, kurz=True) == "12.11.26"


def test_sommerzeit_ist_zwei_stunden_vor_utc():
    sommer = datetime(2026, 7, 1, 22, 30, tzinfo=timezone.utc)
    assert zeitpunkt_de(sommer) == "02.07.2026 00:30"


# -- Rechnung -------------------------------------------------------------

def test_rechnungsdetail_zeigt_buchhaltung_am_berliner_tag(pg_session, web):
    inv = _versendete_rechnung(pg_session)
    text = web.get(f"/invoices/{inv.id}").text
    assert "Buchhaltung: versendet am 12.11.2026" in text
    assert "11.11.2026" not in text


def test_rueckfrage_beim_erneuten_senden_nennt_ortszeit(pg_session, web):
    inv = _versendete_rechnung(pg_session)
    _smtp(pg_session)
    text = web.get(f"/invoices/{inv.id}").text
    assert "bereits versendet" in text
    assert "wurde am 12.11.2026 um 00:30 bereits versendet" in text


def test_pruefprotokoll_zeigt_ortszeit(pg_session, web):
    inv = beleg(pg_session, kunde(pg_session))
    pg_session.add(ValidationResult(invoice_id=inv.id, is_valid=True, validated_at=NACHTS,
                                    errors=[], warnings=[]))
    pg_session.commit()
    text = web.get(f"/invoices/{inv.id}").text
    assert "12.11.2026 00:30" in text


def test_versandprotokoll_zeigt_ortszeit(pg_session, web):
    inv = beleg(pg_session, kunde(pg_session))
    pg_session.add(InvoiceSendLog(invoice_id=inv.id, sent_at=NACHTS, to_email="a@example.de",
                                  ziel="buchhaltung", success=True))
    pg_session.commit()
    text = web.get(f"/invoices/{inv.id}").text
    assert "12.11.2026 00:30" in text


def test_rechnungsliste_zeigt_kurzdatum_in_ortszeit(pg_session, web):
    _versendete_rechnung(pg_session)
    text = web.get("/invoices/").text
    assert "12.11.26" in text
    assert "11.11.26" not in text


# -- Aufstellung ----------------------------------------------------------

def test_aufstellungsliste_zeigt_ortszeit(pg_session, web):
    speichere_aufstellung(pg_session, status="issued", datev_sent_at=NACHTS)
    text = web.get("/aufstellungen").text
    assert "12.11.2026 00:30" in text
    assert "11.11.2026" not in text


def test_aufstellung_fragt_beim_erneuten_senden_nach(pg_session, web):
    a = speichere_aufstellung(pg_session, status="issued", datev_sent_at=NACHTS)
    text = web.get(f"/aufstellungen/{a.id}").text
    assert ("onsubmit=\"return confirm('Diese Aufstellung wurde am 12.11.2026 um 00:30 "
            "bereits versendet. Erneut senden?')\"") in text


def test_aufstellung_ohne_versand_fragt_nicht(pg_session, web):
    a = speichere_aufstellung(pg_session, status="issued")
    text = web.get(f"/aufstellungen/{a.id}").text
    assert "confirm(" not in text


# -- Archiv ---------------------------------------------------------------

def test_archiv_zeigt_aenderungszeit_in_ortszeit(dateien, pg_session, web, monkeypatch):  # noqa: F811
    # Der Container laeuft in UTC; auf einem Host mit anderer Zone darf die
    # Anzeige trotzdem nicht der Systemzone folgen.
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    time.tzset()
    try:
        os.utime(dateien["pdf"], (NACHTS.timestamp(), NACHTS.timestamp()))
        text = web.get("/archiv").text
    finally:
        # Auch bei Fehlschlag zuruecksetzen, sonst laeuft der Rest der Suite in Tokio.
        monkeypatch.undo()
        time.tzset()
    assert "12.11.2026 00:30" in text


def test_aenderungsprotokoll_zeigt_ortszeit(pg_session, web):
    from app.models.invoice_nebenmodelle import AuditLog
    inv = beleg(pg_session, kunde(pg_session))
    eintrag = (pg_session.query(AuditLog).filter(AuditLog.record_id == str(inv.id))
               .order_by(AuditLog.changed_at).first())
    assert eintrag is not None, "kein Protokolleintrag zur Rechnung"
    erwartet = eintrag.changed_at.astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M")
    text = web.get(f"/invoices/{inv.id}").text
    assert f'class="protokoll__zeit">{erwartet}<' in text
