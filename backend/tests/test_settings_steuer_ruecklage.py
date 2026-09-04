"""Steuer-Ruecklage in den Firmeneinstellungen."""

from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company


def _firma_form(**extra):
    data = {
        "name": "Muster Handwerk GmbH",
        "address_line1": "Musterstraße 1",
        "zip_code": "12345",
        "city": "Musterstadt",
        "country": "DE",
        # Ohne Steuernummer: das Formular verlangt serverseitig keine, und jede
        # neu hinzukommende Zeile im Format NNN/NNN/NNNNN haelt die Datenwache
        # im Pre-Push-Hook an, gleich ob die Nummer erfunden ist oder nicht.
        "invoice_prefix": "RE",
        "kst_satz_percent": "15",
        "soli_auf_kst_percent": "5,5",
        "gewerbe_hebesatz": "490",
    }
    data.update(extra)
    return data


def test_steuer_ruecklage_wird_mit_firmendaten_gespeichert(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    client = TestClient(app, follow_redirects=False)

    antwort = client.post("/settings/firma", data=_firma_form())
    assert antwort.status_code == 303

    pg_session.expire_all()
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    assert firma.kst_satz_percent == Decimal("15.00")
    assert firma.soli_auf_kst_percent == Decimal("5.50")
    assert firma.gewerbe_hebesatz == 490

    app.dependency_overrides.clear()


def test_steuer_ruecklage_lehnt_hebesatz_ab(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    client = TestClient(app, follow_redirects=False)
    vorher = pg_session.query(Company).filter(Company.id == 1).first().gewerbe_hebesatz

    antwort = client.post("/settings/firma", data=_firma_form(gewerbe_hebesatz="50"))
    assert antwort.status_code == 200

    pg_session.expire_all()
    nachher = pg_session.query(Company).filter(Company.id == 1).first().gewerbe_hebesatz
    assert nachher == vorher

    app.dependency_overrides.clear()


# ── Anzeige: Firmenzeile ohne Saetze sprengt die Seite nicht ────────────────

def test_einstellungsseite_zeigt_die_vorgaben_wenn_die_firma_keine_saetze_hat():
    """Eine Firma ohne gesetzte Ruecklage-Saetze darf die Seite nicht sprengen.

    `betrag(None)` wirft `InvalidOperation` und macht aus den Einstellungen
    einen 500er, also aus der Seite, auf der man die Saetze eintragen wuerde.
    Angezeigt wird dann dieselbe Vorgabe, mit der die Uebersicht rechnet.
    """
    from tests.test_settings_config import _FakeDB
    from app.database import get_db
    from app.models.app_config import AppConfig

    firma = Company(id=1)  # kst_satz_percent, soli_auf_kst_percent, gewerbe_hebesatz sind None
    db = _FakeDB({Company: firma, AppConfig: AppConfig(id=1)})
    app.dependency_overrides[get_db] = lambda: db
    try:
        antwort = TestClient(app).get("/settings/")
        assert antwort.status_code == 200
        seite = antwort.text
        assert 'name="kst_satz_percent" value="15,0"' in seite
        assert 'name="soli_auf_kst_percent" value="5,5"' in seite
        assert 'name="gewerbe_hebesatz" value="400"' in seite
    finally:
        app.dependency_overrides.clear()
