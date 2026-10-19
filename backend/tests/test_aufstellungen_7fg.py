"""Export, Archiv und Bedienwege der Aufstellung, ohne PDF-Erzeugung."""
import csv
import io
import zipfile
from datetime import date

from app.config import get_settings
from app.models.aufstellung import Aufstellung, AufstellungAnlage
from app.services.gobd_export import build_gobd_export
from tests.factories_aufstellung import orm_anlage, orm_aufstellung, speichere_aufstellung


def test_export_alle_felder_dateien_und_geteilte_anlagen(tmp_path):
    a = orm_aufstellung(status="issued", pdf_filename="AA.pdf",
                        anlagen=[orm_anlage(), orm_anlage("zahlungsbericht")])
    (tmp_path / "aufstellungen").mkdir()
    (tmp_path / "aufstellungen" / "AA.pdf").write_bytes(b"pdf")
    ordner = tmp_path / "uebergaben" / "eingang" / "anlagen"
    ordner.mkdir(parents=True)
    (ordner / ("a" * 64 + ".xlsx")).write_bytes(b"xlsx")
    data = build_gobd_export(invoices=[], customers=[], audit_rows=[], uebergaben=[],
                             aufstellungen=[a], storage_path=tmp_path,
                             date_from=date(2026, 1, 1), date_to=date(2026, 12, 31))
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for name, model in [("aufstellungen", Aufstellung), ("aufstellung_anlagen", AufstellungAnlage)]:
            rows = list(csv.DictReader(io.StringIO(z.read(name + ".csv").decode("utf-8-sig")), delimiter=";"))
            assert set(rows[0]) >= set(model.__table__.columns.keys())
            if model is Aufstellung:
                assert rows[0]["kundennummer"] == a.customer.customer_number
            assert name + ".csv" in z.read("index.xml").decode()
            assert name + ".csv" in z.read("dokumentation.txt").decode()
        assert z.read("aufstellungen/AA.pdf") == b"pdf"
        assert len([n for n in z.namelist() if n.endswith(".xlsx")]) == 1
        assert "fehlende_dateien.txt" not in z.namelist()


def test_export_fehlende_aufstellungsdateien(tmp_path):
    a = orm_aufstellung(status="issued", anlagen=[orm_anlage()])
    data = build_gobd_export(invoices=[], customers=[], audit_rows=[], uebergaben=[],
                             aufstellungen=[a], storage_path=tmp_path,
                             date_from=date(2026, 1, 1), date_to=date(2026, 12, 31))
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        text = z.read("fehlende_dateien.txt").decode()
        assert a.nummer in text and "PDF" in text and "a" * 64 in text


def test_liste_detail_verwerfen_zurueckholen(client, pg_session):
    a = speichere_aufstellung(pg_session, schluessel="auftrag-7fg")
    assert a.nummer in client.get("/aufstellungen").text
    detail = client.get(f"/aufstellungen/{a.id}")
    assert detail.status_code == 200
    assert "FINALISIEREN" in detail.text and "a" * 64 in detail.text
    assert client.post(f"/aufstellungen/{a.id}/verwerfen").status_code == 303
    pg_session.refresh(a)
    assert a.status == "discarded" and a.auftragsschluessel_offen is None
    assert a.nummer not in client.get("/aufstellungen?status=draft").text
    assert "ZURÜCKHOLEN" in client.get(f"/aufstellungen/{a.id}").text
    assert client.post(f"/aufstellungen/{a.id}/zurueckholen").status_code == 303
    pg_session.refresh(a)
    assert a.auftragsschluessel_offen == "auftrag-7fg"


def test_zurueckholen_belegter_schluessel(client, pg_session):
    a = speichere_aufstellung(pg_session, schluessel="auftrag-konflikt")
    client.post(f"/aufstellungen/{a.id}/verwerfen")
    speichere_aufstellung(pg_session, schluessel="auftrag-konflikt")
    assert client.post(f"/aufstellungen/{a.id}/zurueckholen").status_code == 400


def test_archiv_zeigt_nur_bekannte_aufstellung(client, pg_session):
    a = speichere_aufstellung(pg_session, status="issued", pdf_filename="AA-archiv.pdf",
                             ausstellungsdatum=date(2026, 10, 1))
    ordner = get_settings().storage_path / "aufstellungen"
    ordner.mkdir(exist_ok=True)
    (ordner / a.pdf_filename).write_bytes(b"pdf")
    (ordner / "waise.pdf").write_bytes(b"waise")
    seite = client.get("/archiv")
    assert a.pdf_filename in seite.text and "waise.pdf" not in seite.text
    assert client.get(f"/archiv/datei/aufstellungen/{a.pdf_filename}").content == b"pdf"
    assert client.get("/archiv/datei/aufstellungen/waise.pdf").status_code == 404


def test_liste_blaettert_nach_gefilterter_anzahl(client, pg_session, monkeypatch):
    from app.routers import aufstellungen

    monkeypatch.setattr(aufstellungen, "SEITENGROESSE", 1)
    a = speichere_aufstellung(pg_session)
    b = speichere_aufstellung(pg_session)
    erste = client.get("/aufstellungen?status=draft")
    zweite = client.get("/aufstellungen?status=draft&seite=99")
    assert "Seite 1 von 2" in erste.text and "Seite 2 von 2" in zweite.text
    assert (a.nummer in erste.text) != (a.nummer in zweite.text)
    assert (b.nummer in erste.text) != (b.nummer in zweite.text)
    assert "status=draft&amp;seite=2" in erste.text


def test_export_zeitraum_und_kunden_der_aufstellungen(client, pg_session):
    for nummer, datum, status in [("AA-vorher", date(2026, 9, 30), "issued"),
                                  ("AA-start", date(2026, 10, 1), "issued"),
                                  ("AA-ende", date(2026, 10, 31), "issued"),
                                  ("AA-nachher", date(2026, 11, 1), "issued"),
                                  ("AA-entwurf", date(2026, 10, 2), "draft"),
                                  ("AA-ohne-datum", None, "discarded")]:
        speichere_aufstellung(pg_session, nummer=nummer, status=status,
                             ausstellungsdatum=datum, pdf_filename=nummer + ".pdf")
    antwort = client.get("/export/gobd?von=2026-10-01&bis=2026-10-31")
    assert antwort.status_code == 200
    with zipfile.ZipFile(io.BytesIO(antwort.content)) as z:
        rows = list(csv.DictReader(io.StringIO(z.read("aufstellungen.csv").decode("utf-8-sig")), delimiter=";"))
        assert {r["nummer"] for r in rows} == {"AA-start", "AA-ende"}
        kunden = list(csv.DictReader(io.StringIO(z.read("kunden.csv").decode("utf-8-sig")), delimiter=";"))
        assert len(kunden) == 2


def test_storno_bezuege_versandprotokoll_und_zurueckholkonflikt(client, pg_session):
    from app.models.aufstellung_send_log import AufstellungSendLog
    from app.services.aufstellung_storno import entwurf_anlegen

    a = speichere_aufstellung(pg_session, status="issued", pdf_filename="AA.pdf",
                             ausstellungsdatum=date(2026, 10, 1))
    s = entwurf_anlegen(pg_session, a)
    pg_session.add(AufstellungSendLog(aufstellung_id=a.id, ziel="buchhaltung",
                                      to_email="buchhaltung@example.test", success=None))
    pg_session.commit()
    detail = client.get(f"/aufstellungen/{a.id}").text
    assert f'/aufstellungen/{s.id}' in detail and "AN BUCHHALTUNG SENDEN" in detail
    assert "Ausgang unbekannt" in detail and "buchhaltung@example.test" in detail
    assert f'/aufstellungen/{a.id}' in client.get(f"/aufstellungen/{s.id}").text
    assert client.post(f"/aufstellungen/{s.id}/verwerfen").status_code == 303
    entwurf_anlegen(pg_session, a)
    pg_session.commit()
    assert client.post(f"/aufstellungen/{s.id}/zurueckholen").status_code == 400


def test_menue_nur_mit_beleg_integration(client, pg_session):
    from tests.test_aufstellungsauftrag_router import _schalter

    _schalter(pg_session, False)
    assert 'href="/aufstellungen"' not in client.get("/invoices/").text
    _schalter(pg_session, True)
    assert 'href="/aufstellungen"' in client.get("/invoices/").text


def test_gestellte_aufstellung_ist_nicht_verwerfbar(client, pg_session):
    a = speichere_aufstellung(pg_session, status="issued", ausstellungsdatum=date(2026, 10, 1))
    assert client.post(f"/aufstellungen/{a.id}/verwerfen").status_code == 400
    assert client.post(f"/aufstellungen/{a.id}/zurueckholen").status_code == 400
    pg_session.refresh(a)
    assert a.status == "issued"
