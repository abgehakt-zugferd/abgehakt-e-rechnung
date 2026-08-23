"""
Entwürfe bearbeiten (#141, Spec 2026-07-31).

Aufhebung der alten Entscheidung „Korrektur durch Neuanlage" (#98 P3) — Freigabe am
2026-07-31. Die Grenze bleibt hart: NUR `draft`. Finalisierte Rechnungen
(`issued`/`paid`/`cancelled`) sind unveränderlich, Korrektur weiterhin nur per Storno.

Die Statusprüfung im Router ist die freundliche Fehlermeldung; die verbindliche Linie
ist der `invoice_guard` auf Session-Ebene. Darum echte Persistenz (`pg_session`) statt
Mock-DB — nach docs/ARCHITEKTUR.md („Zwei Schichten") gehört alles mit DB-Wirkung hierher.
Gegen die eigene Zuweisung abgesichert mit `expunge_all()` statt `expire_all()`
(DEV-DOCU: expire allein beweist keine Persistenz).
"""
import json
import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem, ValidationResult


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _customer(pg_session, name="Kunde GmbH"):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name=name,
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.commit()
    return c


def _invoice(pg_session, customer, status="draft", issue=date(2026, 6, 11)):
    inv = Invoice(
        invoice_number=f"RE-{uuid.uuid4().hex[:8]}",
        customer_id=customer.id,
        issue_date=issue,
        due_date=date(2026, 6, 25),
        status=status,
        currency="EUR",
        zugferd_profile="EN16931",
        tax_category="S",
        notes="Ursprungsnotiz",
        net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
        archive_until=date(issue.year + 8, 12, 31),
    )
    pg_session.add(inv)
    pg_session.flush()
    pg_session.add(InvoiceItem(
        invoice_id=inv.id, position=1, description="Beratung", unit="Stunde",
        quantity=Decimal("1"), unit_price=Decimal("100"), tax_rate=Decimal("19"),
        net_amount=Decimal("100.00"), tax_amount=Decimal("19.00"),
        gross_amount=Decimal("119.00"),
    ))
    pg_session.commit()
    return inv


def _payload(customer, items, issue="2026-06-11", notes="Ursprungsnotiz"):
    return {
        "customer_id": str(customer.id),
        "issue_date": issue,
        "due_date": "2026-06-25",
        "tax_category": "S",
        "notes": notes,
        "items_json": json.dumps(items),
    }


def _item(desc="Beratung", qty="1", price="100", rate="19"):
    return {"description": desc, "unit": "Stunde", "quantity": qty,
            "unit_price": price, "tax_rate": rate}


def _frisch(pg_session, inv_id):
    """Objekt wirklich neu aus der DB laden (nicht aus der Identity Map)."""
    pg_session.expunge_all()
    return pg_session.query(Invoice).filter(Invoice.id == inv_id).first()


# --------------------------------------------------------------------------- GET

def test_edit_formular_zeigt_gespeicherte_werte(pg_session):
    cust = _customer(pg_session)
    inv = _invoice(pg_session, cust)
    r = _client(pg_session).get(f"/invoices/{inv.id}/bearbeiten")
    assert r.status_code == 200
    assert inv.invoice_number in r.text
    assert "Beratung" in r.text
    assert "Ursprungsnotiz" in r.text


def test_edit_formular_fuer_finalisierte_rechnung_ist_400(pg_session):
    cust = _customer(pg_session)
    inv = _invoice(pg_session, cust, status="issued")
    r = _client(pg_session).get(f"/invoices/{inv.id}/bearbeiten")
    assert r.status_code == 400


def test_edit_formular_unbekannte_rechnung_ist_404(pg_session):
    r = _client(pg_session).get(f"/invoices/{uuid.uuid4()}/bearbeiten")
    assert r.status_code == 404


def test_edit_formular_rendert_null_felder_nicht_als_none(pg_session):
    """Jinja rendert Python-None als String 'None' (docs/DEV-DOCU.md, „Jinja rendert Python-None als String")."""
    cust = _customer(pg_session)
    inv = _invoice(pg_session, cust)
    inv.notes = None
    inv.payment_terms = None
    inv.delivery_date = None
    pg_session.commit()
    r = _client(pg_session).get(f"/invoices/{inv.id}/bearbeiten")
    assert r.status_code == 200
    assert 'value="None"' not in r.text
    assert ">None<" not in r.text


# -------------------------------------------------------------------------- POST

def test_post_aendert_kunde_daten_und_notizen(pg_session):
    cust = _customer(pg_session)
    neuer = _customer(pg_session, name="Anderer Kunde")
    inv = _invoice(pg_session, cust)
    # IDs vor dem expunge_all() festhalten — danach sind die Objekte abgeloest.
    inv_id, neuer_id = inv.id, neuer.id

    r = _client(pg_session).post(
        f"/invoices/{inv_id}/bearbeiten",
        data=_payload(neuer, [_item()], issue="2026-07-01", notes="Geändert"))
    assert r.status_code == 303

    frisch = _frisch(pg_session, inv_id)
    assert frisch.customer_id == neuer_id
    assert frisch.issue_date == date(2026, 7, 1)
    assert frisch.notes == "Geändert"


def test_rechnungsnummer_und_status_bleiben_unveraendert(pg_session):
    cust = _customer(pg_session)
    inv = _invoice(pg_session, cust)
    nummer = inv.invoice_number

    _client(pg_session).post(f"/invoices/{inv.id}/bearbeiten",
                             data=_payload(cust, [_item()]))

    frisch = _frisch(pg_session, inv.id)
    assert frisch.invoice_number == nummer
    assert frisch.status == "draft"


def test_weniger_positionen_alte_zeilen_weg_positionen_lueckenlos(pg_session):
    cust = _customer(pg_session)
    inv = _invoice(pg_session, cust)
    inv_id = inv.id
    # erst auf drei Positionen erweitern …
    _client(pg_session).post(f"/invoices/{inv_id}/bearbeiten", data=_payload(
        cust, [_item(desc="A"), _item(desc="B"), _item(desc="C")]))
    # … dann auf eine reduzieren
    _client(pg_session).post(f"/invoices/{inv_id}/bearbeiten",
                             data=_payload(cust, [_item(desc="Nur diese")]))

    pg_session.expunge_all()
    items = (pg_session.query(InvoiceItem)
             .filter(InvoiceItem.invoice_id == inv_id)
             .order_by(InvoiceItem.position).all())
    assert [i.description for i in items] == ["Nur diese"]
    assert [i.position for i in items] == [1]


def test_mehr_positionen_summen_stimmen(pg_session):
    cust = _customer(pg_session)
    inv = _invoice(pg_session, cust)

    _client(pg_session).post(f"/invoices/{inv.id}/bearbeiten", data=_payload(cust, [
        _item(desc="Beratung", qty="2", price="100", rate="19"),   # 200,00 + 38,00
        _item(desc="Lizenz", qty="1", price="50", rate="7"),       #  50,00 +  3,50
    ]))

    frisch = _frisch(pg_session, inv.id)
    assert frisch.net_total == Decimal("250.00")
    assert frisch.tax_total == Decimal("41.50")
    assert frisch.gross_total == Decimal("291.50")
    assert [i.position for i in sorted(frisch.items, key=lambda i: i.position)] == [1, 2]


def test_geaendertes_rechnungsdatum_zieht_archive_until_nach(pg_session):
    """GoBD: archive_until folgt dem Jahresendprinzip zum Ausstellungsdatum."""
    cust = _customer(pg_session)
    inv = _invoice(pg_session, cust, issue=date(2026, 6, 11))

    _client(pg_session).post(f"/invoices/{inv.id}/bearbeiten",
                             data=_payload(cust, [_item()], issue="2027-03-05"))

    frisch = _frisch(pg_session, inv.id)
    assert frisch.issue_date == date(2027, 3, 5)
    assert frisch.archive_until == date(2035, 12, 31), (
        "archive_until driftet gegen den Beleg — Aufbewahrungsfrist falsch."
    )


def test_post_auf_finalisierte_rechnung_ist_400_und_aendert_nichts(pg_session):
    cust = _customer(pg_session)
    fremder = _customer(pg_session, name="Fremd")
    inv = _invoice(pg_session, cust, status="issued")
    inv_id, cust_id = inv.id, cust.id

    r = _client(pg_session).post(
        f"/invoices/{inv_id}/bearbeiten",
        data=_payload(fremder, [_item(desc="Manipuliert")], notes="Manipuliert"))
    assert r.status_code == 400

    frisch = _frisch(pg_session, inv_id)
    assert frisch.customer_id == cust_id
    assert frisch.notes == "Ursprungsnotiz"
    assert frisch.status == "issued"
    assert [i.description for i in frisch.items] == ["Beratung"]


def test_nach_post_gibt_es_ein_neues_validation_result_alte_bleiben(pg_session):
    cust = _customer(pg_session)
    inv = _invoice(pg_session, cust)
    alt = ValidationResult(invoice_id=inv.id, is_valid=False, errors=[], warnings=[])
    pg_session.add(alt)
    pg_session.commit()
    alt_id, inv_id = alt.id, inv.id

    _client(pg_session).post(f"/invoices/{inv_id}/bearbeiten",
                             data=_payload(cust, [_item()]))

    pg_session.expunge_all()
    ergebnisse = (pg_session.query(ValidationResult)
                  .filter(ValidationResult.invoice_id == inv_id).all())
    assert len(ergebnisse) == 2, "Nachprüfung fehlt oder altes Protokoll gelöscht"
    assert alt_id in [e.id for e in ergebnisse], "Altes Protokoll wurde gelöscht"


# ---------------------------------------------------------------------- Einstiege

def test_detailseite_bietet_bearbeiten_nur_fuer_entwuerfe(pg_session):
    cust = _customer(pg_session)
    entwurf = _invoice(pg_session, cust)
    final = _invoice(pg_session, cust, status="issued")
    client = _client(pg_session)

    assert f"/invoices/{entwurf.id}/bearbeiten" in client.get(f"/invoices/{entwurf.id}").text
    assert f"/invoices/{final.id}/bearbeiten" not in client.get(f"/invoices/{final.id}").text, (
        "Bearbeiten-Einstieg bei einer finalisierten Rechnung — sie ist unveränderlich."
    )


def test_liste_bietet_bearbeiten_nur_in_entwurfszeilen(pg_session):
    cust = _customer(pg_session)
    entwurf = _invoice(pg_session, cust)
    final = _invoice(pg_session, cust, status="issued")

    html = _client(pg_session).get("/invoices/").text
    assert f"/invoices/{entwurf.id}/bearbeiten" in html
    assert f"/invoices/{final.id}/bearbeiten" not in html
