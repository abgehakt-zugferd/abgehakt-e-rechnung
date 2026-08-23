"""
Router-Tests für POST /invoices/neu — ECHTE Persistenz (pg_session).

Ursprünglich (2026-07-08) gegen _FakeDB: prüfte nur db.added und wäre bei fehlendem
Commit grün geblieben. Jetzt Re-Query nach dem Commit — beweist, dass die Rechnung
mit Positionen, berechneten Summen und der GoBD-Aufbewahrungsfrist (issue_date + 8
Jahre, §14b UStG) tatsächlich in der DB landet.
"""
import json
import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice


def teardown_function():
    app.dependency_overrides.clear()


def _customer(pg_session):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.commit()
    return c


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def test_create_persists_invoice_items_totals_and_archive_until(pg_session):
    cust = _customer(pg_session)
    r = _client(pg_session).post("/invoices/neu", data={
        "customer_id": str(cust.id),
        "issue_date": "2026-06-11",
        "due_date": "2026-06-25",
        "tax_category": "S",
        "items_json": json.dumps([
            {"description": "Beratung", "unit": "Stunde", "quantity": "2",
             "unit_price": "100", "tax_rate": "19"},
            {"description": "Lizenz", "unit": "Stück", "quantity": "1",
             "unit_price": "50", "tax_rate": "7"},
        ]),
    })
    assert r.status_code == 303

    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == cust.id).first()
    assert inv is not None, "Rechnung wurde nicht persistiert (fehlender Commit?)"
    assert inv.status == "draft"
    assert len(inv.items) == 2
    # Summen aus den Positionen berechnet: net 200+50=250, tax 38+3.50=41.50
    assert inv.net_total == Decimal("250.00")
    assert inv.tax_total == Decimal("41.50")
    assert inv.gross_total == Decimal("291.50")
    # GoBD/§14b UStG: Fristende am 31.12. des (Ausstellungsjahr + 8)
    assert inv.archive_until == date(2034, 12, 31)


def test_schalttag_sprengt_die_aufbewahrungsfrist_nicht(pg_session):
    """Den 29. Februar ist als Ausstellungsdatum erlaubt; die Frist endet am Jahresende."""
    cust = _customer(pg_session)
    r = _client(pg_session).post("/invoices/neu", data={
        "customer_id": str(cust.id),
        "issue_date": "2092-02-29",
        "due_date": "2092-03-14",
        "tax_category": "S",
        "items_json": json.dumps([
            {"description": "Beratung", "unit": "Stunde", "quantity": "1",
             "unit_price": "100", "tax_rate": "19"},
        ]),
    })
    assert r.status_code == 303, f"Anlegen scheiterte: {r.status_code}"

    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == cust.id).first()
    assert inv is not None
    assert inv.archive_until == date(2100, 12, 31)


def test_create_assigns_sequential_invoice_number(pg_session):
    cust = _customer(pg_session)
    client = _client(pg_session)
    data = {
        "customer_id": str(cust.id), "issue_date": "2026-06-11",
        "due_date": "2026-06-25", "tax_category": "S",
        "items_json": json.dumps([{"description": "X", "unit": "Stk",
                                   "quantity": "1", "unit_price": "10", "tax_rate": "19"}]),
    }
    client.post("/invoices/neu", data=data)
    client.post("/invoices/neu", data=data)

    pg_session.expire_all()
    numbers = [n for (n,) in pg_session.query(Invoice.invoice_number)
               .filter(Invoice.customer_id == cust.id).all()]
    assert len(numbers) == 2
    assert len(set(numbers)) == 2   # fortlaufend/eindeutig


def test_rechnungsnummer_jahr_aus_ausstellungsdatum_beim_anlegen(pg_session):
    """#19: Beim Anlegen zaehlt issue_date, nicht date.today()."""
    cust = _customer(pg_session)
    r = _client(pg_session).post("/invoices/neu", data={
        "customer_id": str(cust.id),
        "issue_date": "2027-01-02",
        "due_date": "2027-01-16",
        "tax_category": "S",
        "items_json": json.dumps([{"description": "X", "unit": "Stk",
                                   "quantity": "1", "unit_price": "10", "tax_rate": "19"}]),
    })
    assert r.status_code == 303
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == cust.id).one()
    assert inv.invoice_number.startswith("RE-2027-")


def test_rechnungsnummer_bleibt_nach_umdatieren_des_ausstellungsdatums(pg_session):
    """#19/#145: Nummer ist beim Anlegen vergeben und danach unveraenderlich."""
    cust = _customer(pg_session)
    client = _client(pg_session)
    r = client.post("/invoices/neu", data={
        "customer_id": str(cust.id),
        "issue_date": "2027-01-02",
        "due_date": "2027-01-16",
        "tax_category": "S",
        "items_json": json.dumps([{"description": "X", "unit": "Stk",
                                   "quantity": "1", "unit_price": "10", "tax_rate": "19"}]),
    })
    assert r.status_code == 303
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == cust.id).one()
    nummer = inv.invoice_number
    assert nummer.startswith("RE-2027-")

    r2 = client.post(f"/invoices/{inv.id}/bearbeiten", data={
        "customer_id": str(cust.id),
        "issue_date": "2026-06-11",
        "due_date": "2026-06-25",
        "tax_category": "S",
        "items_json": json.dumps([{"description": "X", "unit": "Stk",
                                   "quantity": "1", "unit_price": "10", "tax_rate": "19"}]),
    })
    assert r2.status_code == 303
    pg_session.expire_all()
    frisch = pg_session.query(Invoice).filter(Invoice.id == inv.id).one()
    assert frisch.issue_date == date(2026, 6, 11)
    assert frisch.invoice_number == nummer, (
        "Bekannte Luecke (#145): Nummer folgt nicht dem nachtraeglich geaenderten Ausstellungsdatum."
    )
