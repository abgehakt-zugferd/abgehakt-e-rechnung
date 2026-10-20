"""Firmeneinrichtung vor Nummernvergabe und Anlegeformular (#170).

Migration 001 legt die Firmenzeile immer an. Massgeblich ist
`setup_completed_at`, nicht die blosse Existenz der Zeile.
"""
from __future__ import annotations

import pytest

from app.main import app
from app.models.company import Company
from app.models.invoice import Invoice
from app.services.invoice_number import generate_next_invoice_number
from tests.helpers import firma_eingerichtet as _firma


def teardown_function():
    app.dependency_overrides.clear()


def test_nummernvergabe_lehnt_leere_firmenzeile_ab(pg_session):
    """Wie get_company: leere Zeile (setup_completed_at None) stoppt."""
    _firma.leere_firma(pg_session)
    vorher = pg_session.query(Company).filter(Company.id == 1).one().invoice_counter

    with pytest.raises(Exception):
        generate_next_invoice_number(pg_session)
    pg_session.rollback()

    pg_session.expire_all()
    assert pg_session.query(Company).filter(Company.id == 1).one().invoice_counter == vorher


def test_anlegeformular_faengt_leere_firma_vor_der_nummernvergabe(pg_session):
    """POST /invoices/neu laeuft ueber firma_laden/get_company (bereits gruen)."""
    _firma.leere_firma(pg_session)
    vorher = pg_session.query(Company).filter(Company.id == 1).one().invoice_counter
    kunde = _firma.kunde(pg_session)
    pg_session.commit()

    r = _firma.client(pg_session).post("/invoices/neu", data={
        "customer_id": str(kunde.id),
        "issue_date": "2026-05-01",
        "due_date": "2026-05-15",
        "tax_category": "S",
        "items_json": '[{"description":"Leistung","unit":"Stunde",'
                      '"quantity":"1","unit_price":"100","tax_rate":"19"}]',
    })

    assert r.status_code == 400, r.text
    pg_session.expire_all()
    assert pg_session.query(Company).filter(Company.id == 1).one().invoice_counter == vorher
    assert pg_session.query(Invoice).count() == 0
