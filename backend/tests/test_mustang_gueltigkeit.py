"""Mustang-Gültigkeit: Prüfseite, Finalisieren und Versand werten gleich.

Die Prüfseite validiert die reine XML (nicht das kombinierte PDF). Mustang
meldet dabei bei schema-valider XML ebenfalls „XML:valid“ (siehe
test_invoices_pruefen). Deshalb gilt dieselbe Schwelle wie beim kombinierten
PDF: is_valid und „XML:valid“ im Rohbericht.
"""
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem, ValidationResult
from app.services.invoice_guard import register_invoice_guard

register_invoice_guard()


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _kunde(pg_session):
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Probe Kunde",
        address_line1="Weg 1",
        zip_code="80331",
        city="Muenchen",
        country="DE",
        email="kunde@example.test",
    )
    pg_session.add(c)
    pg_session.flush()
    return c


def _rechnung(pg_session, *, status="draft", pdf=None):
    c = _kunde(pg_session)
    netto, steuer = Decimal("100.00"), Decimal("19.00")
    inv = Invoice(
        invoice_number=f"RE-MG-{uuid.uuid4().hex[:6]}",
        customer_id=c.id,
        issue_date=date(2026, 9, 1),
        due_date=date(2026, 9, 15),
        currency="EUR",
        net_total=netto,
        tax_total=steuer,
        gross_total=netto + steuer,
        status=status,
        pdf_filename=pdf,
        zugferd_profile="EN16931",
        tax_category="S",
    )
    inv.items = [
        InvoiceItem(
            position=1,
            description="Beratung",
            unit="Stunde",
            quantity=Decimal("1"),
            unit_price=netto,
            tax_rate=Decimal("19"),
            net_amount=netto,
            tax_amount=steuer,
            gross_amount=netto + steuer,
        )
    ]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _mustang_ohne_xml_valid():
    """Attrappe im echten Ausgabeformat von mustang.validate (Dict-Schluessel).

    is_valid=True ohne „XML:valid“ im raw: PDF/A-konform oder sonstiger
    Teilerfolg, aber keine bestaetigte XML-Schicht.
    """
    return {
        "is_valid": True,
        "raw": "Parsed PDF:valid\nSummary: 0 errors",
        "errors": [],
        "warnings": [],
    }


def test_ist_gueltige_e_rechnung_braucht_xml_valid():
    from app.services.mustang import ist_gueltige_e_rechnung

    assert ist_gueltige_e_rechnung({
        "is_valid": True,
        "raw": "Parsed PDF:valid\nXML:valid",
        "errors": [],
        "warnings": [],
    }) is True
    assert ist_gueltige_e_rechnung(_mustang_ohne_xml_valid()) is False
    assert ist_gueltige_e_rechnung({
        "is_valid": False,
        "raw": "Parsed PDF:absent XML:valid",
        "errors": ["[error] Probe"],
        "warnings": [],
    }) is False


def test_pruefung_verlangt_xml_valid_wie_finalisieren(pg_session):
    """Prüfseite und Finalisieren sollen dasselbe Mustang-Ergebnis gleich werten.

    Gewünscht: is_valid=True ohne „XML:valid“ im Rohbericht zählt auf der
    Prüfseite nicht als gültig (gleiche Schwelle wie Finalisieren/Versand).
    """
    inv = _rechnung(pg_session, status="draft", pdf=None)
    inv.zugferd_xml = "<Invoice xmlns='urn:probe:mustang-gueltigkeit'/>"
    pg_session.commit()

    with patch(
        "app.services.mustang.validate",
        return_value=_mustang_ohne_xml_valid(),
    ):
        r = _client(pg_session).post(f"/invoices/{inv.id}/pruefen")
    assert r.status_code == 303, r.text

    ergebnis = (
        pg_session.query(ValidationResult)
        .filter(ValidationResult.invoice_id == inv.id)
        .order_by(ValidationResult.validated_at.desc())
        .first()
    )
    assert ergebnis is not None
    assert ergebnis.is_valid is False
