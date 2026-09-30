"""Der umsatzsteuerliche Status des Kunden (abgehakt#22).

Er entscheidet, welche Steuer auf einer Gutschrift im Gutschriftverfahren
steht. Die Angabe kommt NIE ueber den Draht: wer als Kleinunternehmer
Umsatzsteuer ausgewiesen bekommt, schuldet sie nach § 14c Abs. 2 UStG - auf
einem Beleg, den er selbst nicht geschrieben hat.
"""

import uuid
from datetime import date

from app.models.customer import Customer


def _formular(**aenderungen):
    daten = {
        "name": "Jürgen Weiß",
        "address_line1": "Weg 1",
        "zip_code": "10115",
        "city": "Berlin",
        "country": "DE",
    }
    daten.update(aenderungen)
    return daten


def _kunde(pg_session, status="ungeklaert", **over):
    kw = dict(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Jürgen Weiß",
        address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE",
        ust_status=status,
    )
    kw.update(over)
    kunde = Customer(**kw)
    pg_session.add(kunde)
    pg_session.commit()
    return kunde


def test_die_voreinstellung_ist_ungeklaert(pg_session):
    kunde = Customer(
        customer_number="K-1", name="Jürgen Weiß", address_line1="Weg 1",
        zip_code="10115", city="Berlin", country="DE",
    )
    pg_session.add(kunde)
    pg_session.commit()

    assert kunde.ust_status == "ungeklaert"
    assert kunde.gutschriftempfaenger is False


def test_das_formular_bietet_schalter_status_und_steuernummer(client, pg_session):
    kunde = _kunde(pg_session)

    text = client.get(f"/customers/{kunde.id}/bearbeiten").text

    assert "Kleinunternehmer" in text
    assert 'name="ust_status"' in text
    assert 'value="ungeklaert"' in text
    assert 'name="gutschriftempfaenger"' in text
    assert 'name="tax_number"' in text


def test_der_status_laesst_sich_setzen(client, pg_session):
    kunde = _kunde(pg_session)

    client.post(f"/customers/{kunde.id}/bearbeiten",
                data=_formular(
                    ust_status="kleinunternehmer",
                    gutschriftempfaenger="1",
                ))

    pg_session.expire_all()
    frisch = pg_session.query(Customer).filter(Customer.id == kunde.id).one()
    assert frisch.ust_status == "kleinunternehmer"
    assert frisch.gutschriftempfaenger is True
    assert frisch.ust_status_bestaetigt_am == date.today()


def test_ein_erfundener_status_wird_nicht_uebernommen(client, pg_session):
    """Der Wertevorrat ist geschlossen: Unbekanntes faellt auf ungeklaert."""
    kunde = _kunde(pg_session, status="regelbesteuert",
                   ust_status_bestaetigt_am=date(2026, 1, 15))

    client.post(f"/customers/{kunde.id}/bearbeiten",
                data=_formular(ust_status="ausgedacht", gutschriftempfaenger="1"))

    pg_session.expire_all()
    frisch = pg_session.query(Customer).filter(Customer.id == kunde.id).one()
    assert frisch.ust_status == "ungeklaert"
    assert frisch.ust_status_bestaetigt_am is None


def test_ein_neuer_kunde_bekommt_den_gewaehlten_status(client, pg_session):
    client.post("/customers/neu", data=_formular(
        customer_number="K-NEU-1",
        ust_status="kleinunternehmer",
        gutschriftempfaenger="1",
        name="Jürgen Weiß",
    ))

    kunde = pg_session.query(Customer).filter(Customer.customer_number == "K-NEU-1").one()
    assert kunde.ust_status == "kleinunternehmer"
    assert kunde.gutschriftempfaenger is True
    assert kunde.name == "Jürgen Weiß"


def test_ungeklaerter_status_blockiert_das_speichern_nicht(client, pg_session):
    kunde = _kunde(pg_session, status="regelbesteuert", gutschriftempfaenger=True)

    antwort = client.post(f"/customers/{kunde.id}/bearbeiten",
                          data=_formular(
                              ust_status="ungeklaert",
                              gutschriftempfaenger="1",
                          ))

    assert antwort.status_code == 303
    pg_session.expire_all()
    frisch = pg_session.query(Customer).filter(Customer.id == kunde.id).one()
    assert frisch.ust_status == "ungeklaert"
    assert frisch.ust_status_bestaetigt_am is None


def test_statuswechsel_setzt_bestaetigungsdatum(client, pg_session):
    kunde = _kunde(pg_session, status="ungeklaert", gutschriftempfaenger=True)

    client.post(f"/customers/{kunde.id}/bearbeiten",
                data=_formular(ust_status="regelbesteuert", gutschriftempfaenger="1"))

    pg_session.expire_all()
    assert pg_session.get(Customer, kunde.id).ust_status_bestaetigt_am == date.today()


def test_gleicher_status_laesst_bestaetigungsdatum_stehen(client, pg_session):
    alt = date(2026, 3, 1)
    kunde = _kunde(
        pg_session, status="regelbesteuert", gutschriftempfaenger=True,
        ust_status_bestaetigt_am=alt,
    )

    client.post(f"/customers/{kunde.id}/bearbeiten",
                data=_formular(ust_status="regelbesteuert", gutschriftempfaenger="1"))

    pg_session.expire_all()
    assert pg_session.get(Customer, kunde.id).ust_status_bestaetigt_am == alt


def test_steuernummer_laesst_sich_speichern(client, pg_session):
    kunde = _kunde(pg_session)

    client.post(f"/customers/{kunde.id}/bearbeiten",
                data=_formular(tax_number="23/456/78901"))

    pg_session.expire_all()
    assert pg_session.get(Customer, kunde.id).tax_number == "23/456/78901"


_HINWEIS_QR = "Ohne IBAN bekommt die Honorargutschrift keinen QR-Code zum Überweisen"


def test_iban_hinweis_erscheint_fuer_gutschriftempfaenger(client, pg_session):
    """Mit Schalter: Hinweis an den bestehenden Bankfeldern, nicht als Pflicht."""
    kunde = _kunde(pg_session, gutschriftempfaenger=True, bank_iban=None)

    text = client.get(f"/customers/{kunde.id}/bearbeiten").text

    assert _HINWEIS_QR in text
    assert "empfohlen" in text.lower()


def test_iban_hinweis_ist_an_x_show_des_schalters_gebunden(client, pg_session):
    """Der Hinweisabsatz selbst traegt x-show=\"gutschrift\", nicht nur ein Nachbar.

    Alpine laesst den Text im HTML; die Zusicherung greift am <p> mit dem
    Hinweistext. Ein bedingungslos gerenderter Absatz (ohne x-show am Element)
    macht den Test rot; x-show nur am Label \"empfohlen\" genuegt nicht.
    """
    import re

    kunde = _kunde(pg_session, gutschriftempfaenger=False)
    text = client.get(f"/customers/{kunde.id}/bearbeiten").text

    assert re.search(
        r'<p[^>]*\bx-show="gutschrift"[^>]*>[\s\S]*?' + re.escape(_HINWEIS_QR),
        text,
    ), "Hinweisabsatz ohne x-show=\"gutschrift\" am Element selbst"
