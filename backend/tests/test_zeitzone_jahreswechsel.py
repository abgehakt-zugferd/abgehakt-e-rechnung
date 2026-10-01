"""#129: Kalendergrenzen folgen Europe/Berlin, nicht der Container-UTC."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.company import Company
from app.services.invoice_number import generate_next_invoice_number


def teardown_function():
    app.dependency_overrides.clear()


def _fest_utc(jahr, monat, tag, stunde, minute):
    return datetime(jahr, monat, tag, stunde, minute, tzinfo=timezone.utc)


def _uhr_fest(monkeypatch, fest: datetime):
    import app.zeit as zeit

    monkeypatch.setattr(zeit, "_utc_jetzt", lambda: fest)


def _issued(pg_session, issue: date) -> Invoice:
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Probe Zeitzone GmbH",
        address_line1="Probeweg 1",
        zip_code="80331",
        city="Muenchen",
        country="DE",
    )
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(
        invoice_number=f"RE-{uuid.uuid4().hex[:6]}",
        customer_id=c.id,
        issue_date=issue,
        due_date=issue,
        currency="EUR",
        net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
        status="issued",
    )
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _paid(pg_session, *, bezahlt_am: date, net: str, tax: str, gross: str) -> Invoice:
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Probe Umsatz GmbH",
        address_line1="Probeweg 2",
        zip_code="80331",
        city="Muenchen",
        country="DE",
    )
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(
        invoice_number=f"RE-{uuid.uuid4().hex[:6]}",
        customer_id=c.id,
        issue_date=bezahlt_am,
        due_date=bezahlt_am,
        currency="EUR",
        net_total=Decimal(net),
        tax_total=Decimal(tax),
        gross_total=Decimal(gross),
        status="paid",
        bezahlt_am=bezahlt_am,
    )
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _client(pg_session):
    from fastapi.testclient import TestClient

    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def test_status_paid_ohne_datum_nimmt_berlin_heute_am_jahreswechsel(
    pg_session, monkeypatch,
):
    """Durchstich: 31.12.2026 23:30 UTC ist in Berlin der 01.01.2027."""
    _uhr_fest(monkeypatch, _fest_utc(2026, 12, 31, 23, 30))
    inv = _issued(pg_session, issue=date(2026, 12, 1))
    r = _client(pg_session).post(
        f"/invoices/{inv.id}/status",
        data={"new_status": "paid"},
    )
    assert r.status_code == 303
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).bezahlt_am == date(2027, 1, 1)


def test_status_paid_akzeptiert_berlin_heute_nicht_als_zukunft(
    pg_session, monkeypatch,
):
    """01.01.2027 als Eingabe darf um 00:30 Berlin nicht als Zukunft fallen."""
    _uhr_fest(monkeypatch, _fest_utc(2026, 12, 31, 23, 30))
    inv = _issued(pg_session, issue=date(2026, 12, 1))
    r = _client(pg_session).post(
        f"/invoices/{inv.id}/status",
        data={"new_status": "paid", "bezahlt_am": "2027-01-01"},
    )
    assert r.status_code == 303
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).bezahlt_am == date(2027, 1, 1)


def test_status_paid_ohne_datum_bleibt_2026_vor_mitternacht_berlin(
    pg_session, monkeypatch,
):
    """Gegenrichtung: 31.12.2026 22:30 UTC ist in Berlin noch der 31.12.2026."""
    _uhr_fest(monkeypatch, _fest_utc(2026, 12, 31, 22, 30))
    inv = _issued(pg_session, issue=date(2026, 12, 1))
    r = _client(pg_session).post(
        f"/invoices/{inv.id}/status",
        data={"new_status": "paid"},
    )
    assert r.status_code == 303
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).bezahlt_am == date(2026, 12, 31)


def test_rechnungsnummer_und_vorbelegung_folgen_berlin_am_jahreswechsel(
    pg_session, monkeypatch,
):
    """Nummerjahr und Formular-heute kommen beide aus Berlin-heute."""
    _uhr_fest(monkeypatch, _fest_utc(2026, 12, 31, 23, 30))
    company = pg_session.query(Company).filter(Company.id == 1).first()
    company.invoice_counter = 0
    company.invoice_year_in_number = True
    pg_session.commit()

    nummer = generate_next_invoice_number(pg_session)
    assert nummer == "RE-2027-001"

    r = _client(pg_session).get("/invoices/neu")
    assert r.status_code == 200
    assert 'name="issue_date" value="2027-01-01"' in r.text


def test_rechnungsnummer_bleibt_2026_vor_mitternacht_berlin(
    pg_session, monkeypatch,
):
    _uhr_fest(monkeypatch, _fest_utc(2026, 12, 31, 22, 30))
    company = pg_session.query(Company).filter(Company.id == 1).first()
    company.invoice_counter = 0
    company.invoice_year_in_number = True
    pg_session.commit()

    assert generate_next_invoice_number(pg_session) == "RE-2026-001"


def test_uebersicht_ytd_ab_berlin_neujahr(pg_session, monkeypatch):
    """Uebersicht rechnet das laufende Jahr ab dem 01.01.2027 Berlin."""
    from app.main import dashboard
    from starlette.requests import Request

    _uhr_fest(monkeypatch, _fest_utc(2026, 12, 31, 23, 30))
    _paid(
        pg_session, bezahlt_am=date(2026, 12, 31),
        net="80.00", tax="15.20", gross="95.20",
    )
    _paid(
        pg_session, bezahlt_am=date(2027, 1, 1),
        net="200.00", tax="38.00", gross="238.00",
    )
    scope = {"type": "http", "method": "GET", "path": "/dashboard", "headers": []}
    ctx = dashboard(Request(scope), pg_session).context
    assert Decimal(ctx["revenue_ytd"]) == Decimal("200.00")
    assert ctx["vat_quarter_label"] == "Q1 2027"


def test_uebersicht_ytd_noch_2026_vor_mitternacht_berlin(pg_session, monkeypatch):
    """Gegenrichtung: vor Mitternacht Berlin zaehlt die Uebersicht noch 2026."""
    from app.main import dashboard
    from starlette.requests import Request

    _uhr_fest(monkeypatch, _fest_utc(2026, 12, 31, 22, 30))
    _paid(
        pg_session, bezahlt_am=date(2026, 12, 31),
        net="80.00", tax="15.20", gross="95.20",
    )
    scope = {"type": "http", "method": "GET", "path": "/dashboard", "headers": []}
    ctx = dashboard(Request(scope), pg_session).context
    assert Decimal(ctx["revenue_ytd"]) == Decimal("80.00")
    assert ctx["vat_quarter_label"] == "Q4 2026"
