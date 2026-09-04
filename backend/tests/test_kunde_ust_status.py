"""Der umsatzsteuerliche Status des Kunden (abgehakt#22).

Er entscheidet, welche Steuer auf einer Gutschrift im Gutschriftverfahren
steht. Die Angabe kommt NIE ueber den Draht: wer als Kleinunternehmer
Umsatzsteuer ausgewiesen bekommt, schuldet sie nach § 14c Abs. 2 UStG - auf
einem Beleg, den er selbst nicht geschrieben hat.
"""

import uuid

from app.models.customer import Customer


def _formular(**aenderungen):
    daten = {
        "name": "Autorin A",
        "address_line1": "Weg 1",
        "zip_code": "10115",
        "city": "Berlin",
        "country": "DE",
    }
    daten.update(aenderungen)
    return daten


def _kunde(pg_session, status="regelbesteuert"):
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Autorin A",
        address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE",
        ust_status=status,
    )
    pg_session.add(kunde)
    pg_session.commit()
    return kunde


def test_die_voreinstellung_ist_regelbesteuert(pg_session):
    kunde = Customer(
        customer_number="K-1", name="Autorin A", address_line1="Weg 1",
        zip_code="10115", city="Berlin", country="DE",
    )
    pg_session.add(kunde)
    pg_session.commit()

    assert kunde.ust_status == "regelbesteuert"


def test_das_formular_bietet_den_status_an(client, pg_session):
    kunde = _kunde(pg_session)

    text = client.get(f"/customers/{kunde.id}/bearbeiten").text

    assert "Kleinunternehmer" in text
    assert 'name="ust_status"' in text


def test_der_status_laesst_sich_setzen(client, pg_session):
    kunde = _kunde(pg_session)

    client.post(f"/customers/{kunde.id}/bearbeiten",
                data=_formular(ust_status="kleinunternehmer"))

    pg_session.expire_all()
    assert pg_session.query(Customer).filter(Customer.id == kunde.id).one().ust_status == "kleinunternehmer"


def test_ein_erfundener_status_wird_nicht_uebernommen(client, pg_session):
    """Der Wertevorrat ist geschlossen: aus einem unbekannten Wort wuerde beim
    Anlegen einer Gutschrift eine Ausnahme statt einer Steuer."""
    kunde = _kunde(pg_session)

    client.post(f"/customers/{kunde.id}/bearbeiten",
                data=_formular(ust_status="ausgedacht"))

    pg_session.expire_all()
    assert pg_session.query(Customer).filter(Customer.id == kunde.id).one().ust_status == "regelbesteuert"


def test_ein_neuer_kunde_bekommt_den_gewaehlten_status(client, pg_session):
    client.post("/customers/neu", data=_formular(
        customer_number="K-NEU-1", ust_status="kleinunternehmer",
    ))

    kunde = pg_session.query(Customer).filter(Customer.customer_number == "K-NEU-1").one()
    assert kunde.ust_status == "kleinunternehmer"
