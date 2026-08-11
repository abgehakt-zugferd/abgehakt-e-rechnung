"""Ersteinrichtung `/setup` (#4, #99 §4.1 / S4).

Drei Zusagen:
1. Solange nicht eingerichtet ist, landet die Nutzerin auf `/setup` — nicht auf
   einem Dashboard, das ihr einen Hinweis vorhält, den sie wegklicken kann.
2. `/setup` schließt die Einrichtung ab (Flag gesetzt) und lässt sie nicht mit
   halben Firmendaten weiterlaufen: ohne Steuernummer ODER USt-IdNr. wäre jede
   Rechnung nach § 14 UStG fehlerhaft.
3. Bis dahin entsteht keine Rechnung. Vorher prüfte `_get_company` nur, ob die
   Zeile existiert — auf einer frischen Installation existiert sie IMMER (leer),
   und die Rechnung hätte einen leeren Verkäufer in PDF und ZUGFeRD-XML.
"""
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _uneingerichtet(pg_session):
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    firma.setup_completed_at = None
    firma.name = ""
    firma.address_line1 = ""
    firma.zip_code = ""
    firma.city = ""
    firma.tax_number = None
    firma.vat_id = None
    pg_session.commit()


def _eingerichtet(pg_session):
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    firma.setup_completed_at = datetime(2026, 7, 1, tzinfo=timezone.utc)
    pg_session.commit()


FORMULAR = {
    "name": "Kanzlei Musterfrau",
    "address_line1": "Musterweg 3",
    "zip_code": "80331",
    "city": "München",
    "country": "DE",
    "tax_number": "143/123/45678",
    "vat_id": "",
}


def test_uneingerichtet_landet_die_nutzerin_auf_setup(pg_session):
    _uneingerichtet(pg_session)
    try:
        r = _client(pg_session).get("/dashboard")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 303
    assert r.headers["location"] == "/setup"


def test_eingerichtet_bleibt_das_dashboard_erreichbar(pg_session):
    _eingerichtet(pg_session)
    try:
        r = _client(pg_session).get("/dashboard")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200


def test_setup_seite_ist_ohne_einrichtung_erreichbar(pg_session):
    """Sonst wäre die Weiterleitung eine Schleife."""
    _uneingerichtet(pg_session)
    try:
        r = _client(pg_session).get("/setup")
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 200
    assert "name" in r.text


def test_absenden_speichert_die_firma_und_schliesst_die_einrichtung_ab(pg_session):
    _uneingerichtet(pg_session)
    try:
        r = _client(pg_session).post("/setup", data=FORMULAR)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"

    pg_session.expire_all()
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    assert firma.name == "Kanzlei Musterfrau"
    assert firma.city == "München"
    assert firma.setup_completed_at is not None


def test_ohne_steuernummer_und_ohne_ust_id_bleibt_die_einrichtung_offen(pg_session):
    """§ 14 UStG verlangt eine der beiden Nummern — sonst ist jede spätere
    Rechnung fehlerhaft, und zwar unbemerkt."""
    _uneingerichtet(pg_session)
    ohne = dict(FORMULAR, tax_number="", vat_id="")
    try:
        r = _client(pg_session).post("/setup", data=ohne)
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 400

    pg_session.expire_all()
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    assert firma.setup_completed_at is None


def test_ohne_einrichtung_entsteht_keine_rechnung(pg_session):
    """Die Zeile `company` existiert auf einer frischen Installation immer — nur
    eben leer. Ein Existenz-Check allein hätte eine Rechnung ohne Verkäufer
    durchgelassen."""
    _uneingerichtet(pg_session)
    try:
        r = _client(pg_session).post("/invoices/neu", data={
            "customer_id": "00000000-0000-0000-0000-000000000000",
            "issue_date": "2026-07-01", "due_date": "2026-07-15",
            "items_json": "[]",
        })
    finally:
        app.dependency_overrides.clear()

    assert r.status_code == 400
