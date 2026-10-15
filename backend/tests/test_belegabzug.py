"""Abzug auf Belegebene (EN 16931 BG-20, Issue #147 Teilschritt A2).

Router, Validator und Storno gegen dieselben Regeln: Betrag und Grund sind ein
Paar, die Steuer entsteht auf der verminderten Basis, und alle Summen kommen aus
services/belegsummen.py (eine Quelle, nichts wird daneben nachgerechnet).
"""
import json
import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services.storno import build_storno
from app.services.validator import validate_invoice
from tests.factories import (
    company_stub as _company,
    item_stub as _item,
    validator_invoice_stub as _invoice,
)

GRUND = "Anrechnung Vorleistung"


def teardown_function():
    app.dependency_overrides.clear()


def _kunde(pg_session):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.commit()
    return c


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _stammdaten(kunde):
    return {
        "customer_id": str(kunde.id),
        "issue_date": "2026-10-01",
        "due_date": "2026-10-15",
        "tax_category": "S",
    }


def _positionen_netto_1000():
    # 10 Stunden zu 100,00 netto, 19 Prozent: Positionssumme 1000,00.
    return json.dumps([{"description": "Beratung", "unit": "Stunde",
                        "quantity": "10", "unit_price": "100", "tax_rate": "19"}])


def _codes(issues):
    return {i.code for i in issues}


# ── Router: POST /invoices/neu ──────────────────────────────────────────────

def test_router_speichert_abzug_in_den_summen(pg_session):
    kunde = _kunde(pg_session)
    r = _client(pg_session).post("/invoices/neu", data={
        **_stammdaten(kunde),
        "items_json": _positionen_netto_1000(),
        "abzug_betrag": "100,00",  # Komma als Dezimaltrenner
        "abzug_grund": GRUND,
    })
    assert r.status_code == 303

    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == kunde.id).one()
    assert inv.abzug_betrag == Decimal("100.00")
    assert inv.abzug_grund == GRUND
    assert inv.net_total == Decimal("900.00")
    assert inv.tax_total == Decimal("171.00")
    assert inv.gross_total == Decimal("1071.00")


def test_router_ohne_abzug_speichert_wie_bisher(pg_session):
    kunde = _kunde(pg_session)
    r = _client(pg_session).post("/invoices/neu", data={
        **_stammdaten(kunde),
        "items_json": _positionen_netto_1000(),
    })
    assert r.status_code == 303

    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == kunde.id).one()
    assert inv.abzug_betrag is None
    assert inv.abzug_grund is None
    assert inv.net_total == Decimal("1000.00")
    assert inv.tax_total == Decimal("190.00")
    assert inv.gross_total == Decimal("1190.00")


def test_router_lehnt_betrag_ohne_grund_ab_und_zaehler_bleibt(pg_session):
    kunde = _kunde(pg_session)
    zaehler_vor = pg_session.query(Company).filter(Company.id == 1).one().invoice_counter
    r = _client(pg_session).post("/invoices/neu", data={
        **_stammdaten(kunde),
        "items_json": _positionen_netto_1000(),
        "abzug_betrag": "50,00",
    })
    assert r.status_code == 400

    pg_session.expire_all()
    assert pg_session.query(Company).filter(Company.id == 1).one().invoice_counter == zaehler_vor
    assert pg_session.query(Invoice).count() == 0, "keine Zeile, keine Nummernluecke"


def test_router_lehnt_unparsebaren_betrag_ab(pg_session):
    kunde = _kunde(pg_session)
    r = _client(pg_session).post("/invoices/neu", data={
        **_stammdaten(kunde),
        "items_json": _positionen_netto_1000(),
        "abzug_betrag": "fünfzig",
        "abzug_grund": GRUND,
    })
    assert r.status_code == 400
    assert pg_session.query(Invoice).count() == 0


# ── Router: POST /invoices/{id}/bearbeiten ──────────────────────────────────

def test_bearbeiten_setzt_abzug_nach(pg_session):
    kunde = _kunde(pg_session)
    client = _client(pg_session)
    r = client.post("/invoices/neu", data={
        **_stammdaten(kunde),
        "items_json": _positionen_netto_1000(),
    })
    assert r.status_code == 303
    inv_id = r.headers["location"].rsplit("/", 1)[-1]

    r2 = client.post(f"/invoices/{inv_id}/bearbeiten", data={
        **_stammdaten(kunde),
        "items_json": _positionen_netto_1000(),
        "abzug_betrag": "200.00",  # Punkt als Dezimaltrenner
        "abzug_grund": GRUND,
    })
    assert r2.status_code == 303

    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.id == uuid.UUID(inv_id)).one()
    assert inv.abzug_betrag == Decimal("200.00")
    assert inv.abzug_grund == GRUND
    assert inv.net_total == Decimal("800.00")
    assert inv.tax_total == Decimal("152.00")
    assert inv.gross_total == Decimal("952.00")


# ── Validator: je ein Test pro neuem Fehlercode ─────────────────────────────

def test_validator_abzug_unvollstaendig_ohne_grund():
    errors, _ = validate_invoice(_invoice(abzug_betrag=Decimal("50.00")), _company())
    assert "ABZUG_UNVOLLSTAENDIG" in _codes(errors)


def test_validator_abzug_unvollstaendig_ohne_betrag():
    errors, _ = validate_invoice(_invoice(abzug_grund=GRUND), _company())
    assert "ABZUG_UNVOLLSTAENDIG" in _codes(errors)


def test_validator_abzug_nicht_positiv():
    errors, _ = validate_invoice(
        _invoice(abzug_betrag=Decimal("0.00"), abzug_grund=GRUND), _company())
    assert "ABZUG_NICHT_POSITIV" in _codes(errors)


def test_validator_abzug_zu_hoch():
    # Positionssumme ist 200,00: ein Abzug in gleicher Hoehe ist keine Minderung mehr.
    errors, _ = validate_invoice(
        _invoice(abzug_betrag=Decimal("200.00"), abzug_grund=GRUND), _company())
    assert "ABZUG_ZU_HOCH" in _codes(errors)


def test_validator_abzug_satz_uneindeutig():
    inv = _invoice(
        abzug_betrag=Decimal("50.00"), abzug_grund=GRUND,
        items=[_item(),
               _item(position=2, tax_rate=Decimal("7.00"),
                     net_amount=Decimal("100.00"), tax_amount=Decimal("7.00"),
                     gross_amount=Decimal("107.00"))],
    )
    errors, _ = validate_invoice(inv, _company())
    assert "ABZUG_SATZ_UNEINDEUTIG" in _codes(errors)


def test_validator_abzug_belegart_verboten():
    inv = _invoice(
        invoice_type="prepayment",
        delivery_date=None,
        service_period_start=date(2026, 6, 1),
        service_period_end=date(2026, 6, 30),
        abzug_betrag=Decimal("50.00"), abzug_grund=GRUND,
    )
    errors, _ = validate_invoice(inv, _company())
    assert "ABZUG_BELEGART" in _codes(errors)


def test_validator_akzeptiert_konsistenten_abzug():
    inv = _invoice(
        abzug_betrag=Decimal("50.00"), abzug_grund=GRUND,
        net_total=Decimal("150.00"), tax_total=Decimal("28.50"),
        gross_total=Decimal("178.50"),
    )
    errors, _ = validate_invoice(inv, _company())
    assert errors == []


def test_validator_ueberspringt_summenvergleich_nach_abzugfehler():
    """Nach einem ABZUG-Fehler ist die Basis unklar: kein MISMATCH-Doppel-Fehler."""
    inv = _invoice(abzug_betrag=Decimal("200.00"), abzug_grund=GRUND)
    errors, _ = validate_invoice(inv, _company())
    codes = _codes(errors)
    assert "ABZUG_ZU_HOCH" in codes
    assert "NET_TOTAL_MISMATCH" not in codes
    assert "TAX_TOTAL_MISMATCH" not in codes
    assert "GROSS_TOTAL_MISMATCH" not in codes


# ── Storno: Abzug 1:1 ────────────────────────────────────────────────────────

def test_storno_uebernimmt_abzug_und_summen():
    original = Invoice(
        invoice_number="RE-2026-001",
        customer_id=uuid.uuid4(),
        issue_date=date(2026, 10, 1),
        due_date=date(2026, 10, 15),
        delivery_date=date(2026, 9, 30),
        currency="EUR",
        tax_category="S",
        net_total=Decimal("900.00"),
        tax_total=Decimal("171.00"),
        gross_total=Decimal("1071.00"),
        abzug_betrag=Decimal("100.00"),
        abzug_grund=GRUND,
        status="issued",
    )
    original.id = uuid.uuid4()
    original.items = [InvoiceItem(
        position=1, description="Beratung", unit="Stunde",
        quantity=Decimal("10.0000"), unit_price=Decimal("100.0000"),
        tax_rate=Decimal("19.00"), net_amount=Decimal("1000.00"),
        tax_amount=Decimal("190.00"), gross_amount=Decimal("1190.00"),
    )]

    storno = build_storno(original, "RE-2026-002", date(2026, 10, 15))
    assert storno.abzug_betrag == Decimal("100.00")
    assert storno.abzug_grund == GRUND
    assert storno.net_total == Decimal("900.00")
    assert storno.tax_total == Decimal("171.00")
    assert storno.gross_total == Decimal("1071.00")
