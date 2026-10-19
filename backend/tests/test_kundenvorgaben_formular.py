"""Kundenvorgaben im Kundenformular (Bauschritt 2a): anzeigen, speichern, validieren.

Fuenf Felder am Kunden: auftrag_steuer, kopftext, fusstext, zahlungshinweis,
belegsprache_vorgabe. Gespeichert wird ueber die echten Routen, denn hier zaehlt
der Write-Pfad: ein Feld, das nur im Template steht, waere unsichtbar gespeichert
und faele erst bei der ersten Rechnung auf.
"""
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.main import app
from app.models.customer import Customer


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


_REQUIRED = {"name": "Muster GmbH", "address_line1": "Weg 1", "zip_code": "10115", "city": "Berlin"}


def _kunde(pg_session, **over):
    kw = dict(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Alt",
              address_line1="Alt 1", zip_code="10115", city="Berlin", country="DE")
    kw.update(over)
    c = Customer(**kw)
    pg_session.add(c)
    pg_session.commit()
    return c


def test_formular_zeigt_die_fuenf_felder_mit_hilfetexten(pg_session):
    html = _client(pg_session).get("/customers/neu").text
    for feld in ("auftrag_steuer", "kopftext", "fusstext", "zahlungshinweis",
                 "belegsprache_vorgabe"):
        assert f'name="{feld}"' in html, f"Feld {feld} fehlt im Anlegeformular"
    # Die Hilfetexte sind Teil des Auftrags: der Platzhalter muss genannt sein,
    # sonst traegt niemand {leistungsmonat} ein und die Vorgabe wirkt nie.
    assert "{leistungsmonat}" in html
    assert "USt-IdNr." in html
    assert "hier nicht wiederholen" in html


def test_anlegen_speichert_die_fuenf_felder(pg_session):
    r = _client(pg_session).post("/customers/neu", data={
        **_REQUIRED,
        "customer_number": "20260901",
        "auftrag_steuer": "AE",
        "kopftext": "Grundlage {leistungsmonat}",
        "fusstext": "Bericht ist Einzelaufstellung",
        "zahlungshinweis": "Zahlung nach Auszahlungsbericht.",
        "belegsprache_vorgabe": "en",
    })
    assert r.status_code == 303
    pg_session.expire_all()
    c = pg_session.query(Customer).filter(
        Customer.customer_number == "20260901").one()
    assert c.auftrag_steuer == "AE"
    assert c.kopftext == "Grundlage {leistungsmonat}"
    assert c.fusstext == "Bericht ist Einzelaufstellung"
    assert c.zahlungshinweis == "Zahlung nach Auszahlungsbericht."
    assert c.belegsprache_vorgabe == "en"


def test_bearbeiten_speichert_und_leert_die_felder(pg_session):
    c = _kunde(pg_session, auftrag_steuer="AE", kopftext="Alt", fusstext="Alt-Fuss",
               zahlungshinweis="Alt-Hinweis", belegsprache_vorgabe="en")
    r = _client(pg_session).post(f"/customers/{c.id}/bearbeiten", data={
        **_REQUIRED,
        "customer_number": c.customer_number,
        "auftrag_steuer": "",
        "kopftext": "Neu",
        "fusstext": "",
        "zahlungshinweis": "Neuer Hinweis",
        "belegsprache_vorgabe": "de",
    })
    assert r.status_code == 303
    pg_session.expire_all()
    c = pg_session.query(Customer).filter(Customer.id == c.id).one()
    assert c.auftrag_steuer is None, "Leere Vorgabe muss NULL sein, kein Leerstring"
    assert c.kopftext == "Neu"
    assert c.fusstext is None
    assert c.zahlungshinweis == "Neuer Hinweis"
    assert c.belegsprache_vorgabe == "de"


def test_unzulaessige_steuervorgabe_ist_formularfehler_kein_500(pg_session):
    r = _client(pg_session).post("/customers/neu", data={
        **_REQUIRED, "customer_number": "20260902", "auftrag_steuer": "XX",
    })
    assert r.status_code == 200, "Formularfehler wird mit dem Formular beantwortet"
    assert "Steuervorgabe" in r.text
    pg_session.expire_all()
    assert pg_session.query(Customer).count() == 0


def test_unzulaessige_belegsprachenvorgabe_ist_formularfehler(pg_session):
    r = _client(pg_session).post("/customers/neu", data={
        **_REQUIRED, "customer_number": "20260903", "belegsprache_vorgabe": "fr",
    })
    assert r.status_code == 200
    assert "Belegsprache" in r.text
    pg_session.expire_all()
    assert pg_session.query(Customer).count() == 0


def test_datenbank_lehnt_werte_ausserhalb_des_vorrats_ab(pg_session):
    """Der DB-CHECK ist die zweite Verteidigungslinie: er greift auch ohne Formular."""
    c = _kunde(pg_session)
    c.auftrag_steuer = "XX"
    with pytest.raises(IntegrityError):
        pg_session.commit()
    pg_session.rollback()


def test_datenbank_lehnt_unzulaessige_belegsprache_ab(pg_session):
    c = _kunde(pg_session)
    c.belegsprache_vorgabe = "fr"
    with pytest.raises(IntegrityError):
        pg_session.commit()
    pg_session.rollback()
