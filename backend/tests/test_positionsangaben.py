"""Optionale Zusatzangaben einer Position (services/positionsangaben.py).

Artikelnummer (BT-155): eingeben, speichern, beim Bearbeiten und als Vorlage
wiederfinden, beim Storno mitnehmen. Jede dieser Stationen hat ihre eigene
Feldliste; ein neues Feld ging bisher an jeder einzeln verloren.
"""
import json
import uuid

import pytest
from sqlalchemy import text

from app.models.customer import Customer
from app.models.invoice import Invoice


def _kunde(pg_session):
    k = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Probe Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(k)
    pg_session.commit()
    return k


def _position(**extra):
    p = {"description": "Beratung", "unit": "Stunde", "quantity": "2",
         "unit_price": "100", "tax_rate": "19"}
    p.update(extra)
    return p


def _anlegen(client, kunde, positionen):
    return client.post("/invoices/neu", data={
        "customer_id": str(kunde.id), "issue_date": "2026-06-11", "due_date": "2026-06-25",
        "delivery_date": "2026-06-11", "tax_category": "S",
        "items_json": json.dumps(positionen),
    })


def _formular_positionen(html: str) -> list[dict]:
    """Die Positionen, die das Formular in seinen <script>-Block bekommt."""
    marke = 'id="vorhandene-positionen">'
    start = html.index(marke) + len(marke)
    ende = html.index("</script>", start)
    return json.loads(html[start:ende])


def test_artikelnummer_wird_gespeichert_und_beim_bearbeiten_wieder_angeboten(pg_session, client):
    kunde = _kunde(pg_session)

    antwort = _anlegen(client, kunde, [_position(artikelnummer="  00950 "), _position()])

    assert antwort.status_code == 303
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == kunde.id).one()
    assert [i.artikelnummer for i in sorted(inv.items, key=lambda i: i.position)] == ["00950", None]

    formular = _formular_positionen(client.get(f"/invoices/{inv.id}/bearbeiten").text)
    assert [p.get("artikelnummer") for p in formular] == ["00950", ""]


def test_zu_lange_artikelnummer_wird_abgelehnt_ohne_nummer_zu_verbrauchen(pg_session, client):
    kunde = _kunde(pg_session)
    zaehler_vorher = pg_session.execute(text("SELECT invoice_counter FROM company")).scalar()

    antwort = _anlegen(client, kunde, [_position(artikelnummer="9" * 51)])

    assert antwort.status_code == 400
    assert "Position 1: Artikelnummer ist länger als 50 Zeichen" in antwort.text
    pg_session.expire_all()
    assert pg_session.query(Invoice).filter(Invoice.customer_id == kunde.id).count() == 0
    assert pg_session.execute(text("SELECT invoice_counter FROM company")).scalar() == zaehler_vorher


def test_bearbeiten_lehnt_zu_lange_artikelnummer_ab_und_behaelt_den_stand(pg_session, client):
    kunde = _kunde(pg_session)
    _anlegen(client, kunde, [_position(artikelnummer="00950")])
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == kunde.id).one()

    antwort = client.post(f"/invoices/{inv.id}/bearbeiten", data={
        "customer_id": str(kunde.id), "issue_date": "2026-06-11", "due_date": "2026-06-25",
        "delivery_date": "2026-06-11", "tax_category": "S",
        "items_json": json.dumps([_position(artikelnummer="9" * 51)]),
    })

    assert antwort.status_code == 400
    assert "Artikelnummer ist länger als 50 Zeichen" in antwort.text
    pg_session.expire_all()
    assert [i.artikelnummer for i in pg_session.get(Invoice, inv.id).items] == ["00950"]


def test_storno_uebernimmt_die_artikelnummer_je_position():
    from datetime import date

    from app.services.storno import build_storno
    from tests.factories import orm_invoice, orm_item

    mit = orm_item(1, "1", "100.00", "19")
    mit.artikelnummer = "00950"
    original = orm_invoice([mit, orm_item(2, "1", "50.00", "19")], invoice_number="RE-2026-900")

    storno = build_storno(original, "RE-2026-901", date(2026, 7, 1))

    assert [i.artikelnummer for i in storno.items] == ["00950", None]


@pytest.mark.parametrize("sprache, erwartet", [
    ("de", "Art.-Nr. 00<9>&5"),
    ("en", "Item no. 00<9>&5"),
])
def test_pdf_zeigt_die_artikelnummer_unter_der_beschreibung(tmp_path, sprache, erwartet):
    from pypdf import PdfReader

    from app.services import pdf_generator
    from tests.factories import orm_company, orm_invoice, orm_item

    mit = orm_item(1, "1", "100.00", "19", description="Beratung")
    mit.artikelnummer = "00<9>&5"
    inv = orm_invoice([mit, orm_item(2, "1", "50.00", "19", description="Reise")],
                      document_language=sprache, delivery_date=None)
    out = tmp_path / "beleg.pdf"

    pdf_generator.generate_pdf(inv, orm_company(), out)

    text = " ".join("".join(p.extract_text() for p in PdfReader(str(out)).pages).split())
    assert f"Beratung {erwartet}" in text
    assert text.count(erwartet.split(" 00")[0]) == 1


def test_formular_bietet_das_feld_an_und_neue_positionen_kennen_es(pg_session, client):
    seite = client.get("/invoices/neu").text

    assert 'x-model="item.artikelnummer"' in seite
    assert 'maxlength="50"' in seite
    assert "artikelnummer: ''" in seite


def test_detailseite_zeigt_die_artikelnummer(pg_session, client):
    kunde = _kunde(pg_session)
    _anlegen(client, kunde, [_position(artikelnummer="00950")])
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == kunde.id).one()

    seite = client.get(f"/invoices/{inv.id}").text

    assert "Art.-Nr. 00950" in seite


def test_vorlage_uebernimmt_die_artikelnummer(pg_session, client):
    kunde = _kunde(pg_session)
    _anlegen(client, kunde, [_position(artikelnummer="00950")])
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == kunde.id).one()

    formular = _formular_positionen(client.get(f"/invoices/neu?vorlage={inv.id}").text)

    assert [p["artikelnummer"] for p in formular] == ["00950"]
