"""Smoke-Test für die Postgres-Test-Fixture: echte DB, echte Inserts, Isolation."""
from app.models.customer import Customer


def test_pg_session_can_insert_and_query(pg_session):
    c = Customer(
        customer_number="K-FIXTURE-1", name="Fixture GmbH",
        address_line1="Weg 1", zip_code="12345", city="Musterstadt",
    )
    pg_session.add(c)
    pg_session.commit()
    found = pg_session.query(Customer).filter_by(customer_number="K-FIXTURE-1").one()
    assert found.id is not None
    assert found.country == "DE"  # Spalten-Default greift


def test_pg_session_is_isolated_between_tests(pg_session):
    # Der Kunde aus dem vorherigen Test darf nicht mehr existieren (Truncate pro Test).
    assert pg_session.query(Customer).count() == 0
