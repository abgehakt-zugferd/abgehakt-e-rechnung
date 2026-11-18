"""Das Land ist im Formularweg Pflicht: ohne Angabe wird nichts gespeichert, kein stilles DE.

Naht: POST /customers/neu, /customers/{id}/bearbeiten, /settings/firma. Fehlt das Feld,
antwortet der Server 422 (wie bei den anderen Pflichtfeldern, auch bei ganz leerem Wert); nur Leerraum zeigt das
Formular mit Fehlermeldung. Die Vorbelegung „DE“ im HTML-Formular bleibt, die sieht der
Nutzer.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from tests.test_cc_mehrere_empfaenger import _kundendaten

# Ein ganz leeres Pflichtfeld weist FastAPI selbst mit 422 ab; nur Leerraum erreicht die
# eigene Prüfung und zeigt das Formular mit Fehlermeldung.
LEER = ["   ", "\t"]
GANZ_LEER = ""


@pytest.fixture
def web(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def _ohne_land(**daten):
    d = _kundendaten(**daten)
    d.pop("country")
    return d


def _kunden(pg_session, name):
    pg_session.expire_all()
    return pg_session.query(Customer).filter(Customer.name == name).all()


def test_neuer_kunde_ohne_landfeld_gibt_422_und_speichert_nichts(web, pg_session):
    r = web.post("/customers/neu", data=_ohne_land(name="Pflicht Kunde A"))

    assert r.status_code == 422
    assert _kunden(pg_session, "Pflicht Kunde A") == []


@pytest.mark.parametrize("leer", LEER)
def test_neuer_kunde_mit_leerem_land_wird_abgewiesen(web, pg_session, leer):
    r = web.post("/customers/neu", data=_kundendaten(name="Pflicht Kunde B", country=leer))

    assert r.status_code == 200 and "Bitte ein Land wählen" in r.text
    assert _kunden(pg_session, "Pflicht Kunde B") == []


def _bestandskunde(pg_session, name):
    c = Customer(customer_number=f"K-PF-{name[-1]}", **_kundendaten(name=name, country="AT"))
    pg_session.add(c)
    pg_session.commit()
    return c


def test_bearbeiten_ohne_landfeld_gibt_422_und_laesst_das_land(web, pg_session):
    c = _bestandskunde(pg_session, "Pflicht Kunde C")

    r = web.post(f"/customers/{c.id}/bearbeiten", data=_ohne_land(name="Pflicht Kunde C"))

    assert r.status_code == 422
    assert _kunden(pg_session, "Pflicht Kunde C")[0].country == "AT"


@pytest.mark.parametrize("leer", LEER)
def test_bearbeiten_mit_leerem_land_wird_abgewiesen(web, pg_session, leer):
    c = _bestandskunde(pg_session, "Pflicht Kunde D")

    r = web.post(f"/customers/{c.id}/bearbeiten",
                 data=_kundendaten(name="Pflicht Kunde D", country=leer))

    assert r.status_code == 200 and "Bitte ein Land wählen" in r.text
    assert _kunden(pg_session, "Pflicht Kunde D")[0].country == "AT"


def _firmenformular(firma, **abweichung):
    daten = {
        "name": firma.name, "address_line1": firma.address_line1, "address_line2": "",
        "zip_code": firma.zip_code, "city": firma.city, "country": "AT",
        "tax_number": firma.tax_number or "", "vat_id": firma.vat_id or "",
        "invoice_prefix": firma.invoice_prefix or "RE", "rechtsform": firma.rechtsform,
        "payment_terms_default": firma.payment_terms_default or "Zahlbar.",
        "payment_terms_default_en": "Payable within 14 days without deduction.",
    }
    daten.update(abweichung)
    return {k: v for k, v in daten.items() if v is not None}


def _firmenland(pg_session):
    pg_session.expire_all()
    return pg_session.get(Company, 1).country


def test_firma_ohne_landfeld_gibt_422_und_laesst_das_land(web, pg_session):
    firma = pg_session.get(Company, 1)
    vorher = firma.country

    r = web.post("/settings/firma", data=_firmenformular(firma, country=None))

    assert r.status_code == 422
    assert _firmenland(pg_session) == vorher


@pytest.mark.parametrize("leer", LEER)
def test_firma_mit_leerem_land_wird_abgewiesen(web, pg_session, leer):
    firma = pg_session.get(Company, 1)
    firma.country = "AT"
    pg_session.commit()

    r = web.post("/settings/firma", data=_firmenformular(firma, country=leer))

    assert r.status_code == 200 and "Bitte ein Land wählen" in r.text
    assert _firmenland(pg_session) == "AT"


def test_ganz_leeres_land_wird_wie_ein_fehlendes_mit_422_abgewiesen(web, pg_session):
    r = web.post("/customers/neu", data=_kundendaten(name="Pflicht Kunde E", country=GANZ_LEER))

    assert r.status_code == 422
    assert _kunden(pg_session, "Pflicht Kunde E") == []
