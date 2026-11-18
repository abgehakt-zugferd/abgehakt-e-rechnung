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


@pytest.mark.parametrize("roh,erwartet", [(" at ", "AT"), ("   ", "DE"), ("nl", "NL")])
def test_ersteinrichtung_speichert_das_normalisierte_land(web, pg_session, roh, erwartet):
    _uneingerichtet(pg_session)

    r = web.post("/setup", data={**FORMULAR, "country": roh})

    assert r.status_code == 303
    pg_session.expire_all()
    assert pg_session.get(Company, 1).country == erwartet


@pytest.mark.parametrize("roh,erwartet", [(" fr ", "FR"), ("it", "IT")])
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


def test_rueckfall_auf_de_steht_nur_in_laender_py():
    """Eine Quelle für den Rückfall: `normalisiere_land`. Andere Stellen rufen sie auf,
    statt „DE“ als Ersatzwert selbst zu schreiben (`or "DE"`, `else "DE"`, Vorgabe am Feld).
    Gelesene Länder (`bereinige_land`) bekommen keinen Ersatz."""
    import re
    from pathlib import Path

    app = Path(__file__).resolve().parent.parent / "app"
    muster = re.compile(r"""(?:\bor|\belse)\s+["']DE["']|country\s*:\s*str\s*=\s*["']DE["']""")
    treffer = [f"{p.relative_to(app)}:{n}"
               for p in app.rglob("*.py") if p.name != "laender.py"
               for n, zeile in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
               if muster.search(zeile)]
    assert treffer == []


def test_partei_vorgabe_und_fehlender_kunde_laufen_ueber_normalisiere_land():
    from app.services.belegrollen import Partei
    from app.services.zugferd_xml.parteien import buyer_trade_party_xml

    assert Partei().country == normalisiere_land(None) == "DE"
    assert "<ram:CountryID>DE</ram:CountryID>" in buyer_trade_party_xml(None, "S")


# Vorbelegungen, die der Nutzer im Formular sieht und ändern kann (kein stiller Rückfall).
_SICHTBARE_VORBELEGUNG = {
    "customers/form.html": "values.get('country') or 'DE'",
    "setup/index.html": "wert('country') or 'DE'",
}


def test_templates_haben_nur_die_benannten_de_vorbelegungen():
    """Der Lint zu `normalisiere_land` sucht in `*.py`; Templates dürfen `or 'DE'` nur
    als sichtbare Formular-Vorbelegung führen, und zwar genau an den benannten Stellen."""
    import re
    from pathlib import Path

    templates = Path(__file__).resolve().parent.parent / "app" / "templates"
    muster = re.compile(r"""\bor\s+['"]DE['"]""")
    treffer = {}
    for p in templates.rglob("*.html"):
        zeilen = [z for z in p.read_text(encoding="utf-8").splitlines() if muster.search(z)]
        if zeilen:
            treffer[p.relative_to(templates).as_posix()] = zeilen
    assert set(treffer) == set(_SICHTBARE_VORBELEGUNG)
    for datei, zeilen in treffer.items():
        assert all(_SICHTBARE_VORBELEGUNG[datei] in z for z in zeilen)
