"""
POST /customers/neu und /customers/{id}/bearbeiten als ECHTE Integration.

Follow-up zum Audit-#10-Sweep: test_customers_router.py stellt das Anlegen nur an
einem MagicMock fest (db.add.call_args) — bei fehlendem Commit bliebe es grün — und
für das BEARBEITEN gab es gar keinen Write-Test (nur das GET-Render des Formulars).

Gerade die Speicher-Seite ist heikel: der 2026-07-08-Vorfall („None"-String vergiftet
DB/PDF/ZUGFeRD-XML) entsteht beim SPEICHERN eines leeren nullbaren Feldes. Hier per
pg_session mit Re-Query abgesichert.
"""
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


_REQUIRED = {"name": "Muster GmbH", "address_line1": "Weg 1", "zip_code": "10115", "city": "Berlin"}


def _seed(pg_session, **over):
    kw = dict(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Alt", address_line1="Alt 1",
              zip_code="10115", city="Berlin", country="DE")
    kw.update(over)
    c = Customer(**kw)
    pg_session.add(c)
    pg_session.commit()
    return c


def test_create_persists_customer(pg_session):
    r = _client(pg_session).post("/customers/neu",
                                 data={**_REQUIRED, "customer_number": "20260701"})
    assert r.status_code == 303
    pg_session.expire_all()
    c = pg_session.query(Customer).filter(Customer.customer_number == "20260701").first()
    assert c is not None, "Kunde nicht persistiert (fehlender Commit?)"
    assert c.name == "Muster GmbH"


def test_create_duplicate_number_persists_nothing(pg_session):
    _seed(pg_session, customer_number="20260701", name="Erster")
    r = _client(pg_session).post("/customers/neu",
                                 data={**_REQUIRED, "customer_number": "20260701"})
    assert r.status_code == 200
    assert "bereits vergeben" in r.text
    pg_session.expire_all()
    # nur der geseedete Kunde existiert, kein zweiter mit dieser Nummer
    assert pg_session.query(Customer).filter(
        Customer.customer_number == "20260701").count() == 1


def test_create_integrity_error_zeigt_vergebene_meldung_statt_500(pg_session):
    """#21: Race zwischen _number_taken und commit darf keinen 500er erzeugen."""
    _seed(pg_session, customer_number="20260701", name="Erster")
    with patch("app.routers.customers._number_taken", return_value=False):
        r = _client(pg_session).post("/customers/neu",
                                     data={**_REQUIRED, "customer_number": "20260701"})
    assert r.status_code == 200
    assert "bereits vergeben" in r.text
    pg_session.expire_all()
    assert pg_session.query(Customer).filter(
        Customer.customer_number == "20260701").count() == 1


def test_update_integrity_error_zeigt_vergebene_meldung_statt_500(pg_session):
    """#21: Gleiches fuer manuell eingetippte Nummer beim Bearbeiten."""
    a = _seed(pg_session, customer_number="20260701", name="A")
    b = _seed(pg_session, customer_number="20260702", name="B")
    with patch("app.routers.customers._number_taken", return_value=False):
        r = _client(pg_session).post(f"/customers/{b.id}/bearbeiten", data={
            **_REQUIRED, "customer_number": "20260701", "name": "B umbenannt",
        })
    assert r.status_code == 200
    assert "bereits vergeben" in r.text
    pg_session.expire_all()
    assert pg_session.get(Customer, a.id).customer_number == "20260701"
    assert pg_session.get(Customer, b.id).customer_number == "20260702"


def test_update_persists_changes(pg_session):
    c = _seed(pg_session, customer_number="20260701", name="Alt")
    r = _client(pg_session).post(f"/customers/{c.id}/bearbeiten", data={
        **_REQUIRED, "name": "Neu GmbH", "customer_number": "20260701",
        "city": "Hamburg",
    })
    assert r.status_code == 303
    pg_session.expire_all()
    row = pg_session.get(Customer, c.id)
    assert row.name == "Neu GmbH"
    assert row.city == "Hamburg"


def test_create_empty_number_falls_back_to_suggestion(pg_session):
    """Leere Kundennummer → Vorschlag greift (portiert aus dem gelöschten Mock-Test
    test_customers_router.py, jetzt mit echter DB + Re-Query)."""
    r = _client(pg_session).post("/customers/neu",
                                 data={**_REQUIRED, "customer_number": ""})
    assert r.status_code == 303
    pg_session.expire_all()
    c = pg_session.query(Customer).filter(Customer.name == "Muster GmbH").first()
    assert c is not None
    assert c.customer_number  # nicht leer — vom Generator vergeben


def test_edit_form_renders_null_fields_as_empty_not_none(pg_session):
    """Vorfall 2026-07-08 (Render-Hälfte): ein NULL-Feld darf im Edit-Formular NICHT
    als value="None" ausgegeben werden, sonst schickt der Browser beim nächsten
    Speichern den String 'None' zurück. Das ist die Render-Seite des Bugs, die der
    Persistenz-Test oben NICHT abdeckt (portiert aus test_customers_router.py)."""
    c = _seed(pg_session, customer_number="20260702",
              address_line2=None, vat_id=None, email=None, phone=None, notes=None)
    r = _client(pg_session).get(f"/customers/{c.id}/bearbeiten")
    assert r.status_code == 200
    assert 'value="None"' not in r.text
    assert ">None<" not in r.text


def test_update_empty_nullable_stored_as_null_not_none_string(pg_session):
    """Vorfall 2026-07-08: leeres address_line2 darf NICHT als String 'None' (oder
    'None' aus einem vorbelegten value) gespeichert werden, sondern als echtes NULL."""
    c = _seed(pg_session, customer_number="20260701", address_line2="Hinterhaus")
    r = _client(pg_session).post(f"/customers/{c.id}/bearbeiten", data={
        **_REQUIRED, "customer_number": "20260701",
        "address_line2": "", "vat_id": "", "email": "", "phone": "", "notes": "",
    })
    assert r.status_code == 303
    pg_session.expire_all()
    row = pg_session.get(Customer, c.id)
    for field in ("address_line2", "vat_id", "email", "phone", "notes"):
        val = getattr(row, field)
        assert val is None, f"{field} = {val!r} (erwartet NULL)"
        assert val != "None"
