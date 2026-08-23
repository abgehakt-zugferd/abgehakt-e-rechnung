"""Isolation der pg_session-Fixture: Insert und Truncate zwischen Tests."""
from app.models.customer import Customer

_eingefuegt_in_vorgaenger = False


def test_pg_session_can_insert_and_query(pg_session):
    global _eingefuegt_in_vorgaenger
    c = Customer(
        customer_number="K-FIXTURE-1", name="Fixture GmbH",
        address_line1="Weg 1", zip_code="12345", city="Musterstadt",
    )
    pg_session.add(c)
    pg_session.commit()
    found = pg_session.query(Customer).filter_by(customer_number="K-FIXTURE-1").one()
    assert found.id is not None
    assert found.country == "DE"  # Spalten-Default greift
    _eingefuegt_in_vorgaenger = True


def test_pg_session_isolated_between_tests(pg_session):
    global _eingefuegt_in_vorgaenger
    if not _eingefuegt_in_vorgaenger:
        raise AssertionError(
            "Isolation nur pruefbar nach test_pg_session_can_insert_and_query — "
            "gesamte Datei ausfuehren, nicht einzeln filtern."
        )
    assert pg_session.query(Customer).count() == 0
