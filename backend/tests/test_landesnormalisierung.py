"""Ländercode: eine Normalisierung für Kunden, Ersteinrichtung und Firmenstammdaten.

Strip, Großschreibung, Vorgabe „DE“. Nähte: die Funktion `normalisiere_land` und die
drei Formularwege (POST /customers/neu, POST /setup, POST /settings/firma).
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.laender import normalisiere_land
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from tests.test_cc_mehrere_empfaenger import _kundendaten
from tests.test_setup_wizard import FORMULAR, _uneingerichtet


@pytest.fixture
def web(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


@pytest.mark.parametrize("roh,erwartet", [
    ("de", "DE"), (" at ", "AT"), ("Fr", "FR"), ("", "DE"), ("   ", "DE"), (None, "DE"), ("NL", "NL"),
])
def test_normalisiere_land(roh, erwartet):
    assert normalisiere_land(roh) == erwartet


def test_kunde_speichert_das_normalisierte_land(web, pg_session):
    r = web.post("/customers/neu", data=_kundendaten(country=" at ", name="Land Kunde A"))

    assert r.status_code == 303
    assert pg_session.query(Customer).filter(Customer.name == "Land Kunde A").one().country == "AT"


def test_kunde_ohne_land_bekommt_de(web, pg_session):
    web.post("/customers/neu", data=_kundendaten(country="   ", name="Land Kunde B"))

    assert pg_session.query(Customer).filter(Customer.name == "Land Kunde B").one().country == "DE"


@pytest.mark.parametrize("roh,erwartet", [(" at ", "AT"), ("   ", "DE"), ("nl", "NL")])
def test_ersteinrichtung_speichert_das_normalisierte_land(web, pg_session, roh, erwartet):
    _uneingerichtet(pg_session)

    r = web.post("/setup", data={**FORMULAR, "country": roh})

    assert r.status_code == 303
    pg_session.expire_all()
    assert pg_session.get(Company, 1).country == erwartet


@pytest.mark.parametrize("roh,erwartet", [(" fr ", "FR"), ("   ", "DE"), ("it", "IT")])
def test_firmenstammdaten_speichern_das_normalisierte_land(web, pg_session, roh, erwartet):
    firma = pg_session.get(Company, 1)
    r = web.post("/settings/firma", data={
        "name": firma.name, "address_line1": firma.address_line1, "address_line2": "",
        "zip_code": firma.zip_code, "city": firma.city, "country": roh,
        "tax_number": firma.tax_number or "", "vat_id": firma.vat_id or "",
        "invoice_prefix": firma.invoice_prefix or "RE", "rechtsform": firma.rechtsform,
        "payment_terms_default": firma.payment_terms_default or "Zahlbar.",
        "payment_terms_default_en": "Payable within 14 days without deduction.",
    })

    assert r.status_code == 303
    pg_session.expire_all()
    assert pg_session.get(Company, 1).country == erwartet


# -- DB-Absicherung --------------------------------------------------------

def test_leeres_kundenland_wird_von_der_datenbank_abgewiesen(pg_session):
    pg_session.add(Customer(customer_number="K-LEER-1", name="Kunde GmbH", address_line1="Weg 1",
                            zip_code="10115", city="Berlin", country=""))

    with pytest.raises(IntegrityError):
        pg_session.commit()
    pg_session.rollback()
