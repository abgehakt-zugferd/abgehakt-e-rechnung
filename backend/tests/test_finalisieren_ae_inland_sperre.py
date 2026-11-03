"""
Reverse-Charge-Sperre beim Finalisieren (#275): Kategorie AE an einen Kunden
mit Land DE und einer USt-IdNr. eines anderen Landes ist ein Widerspruch, der
sich nach dem Stellen nur per Storno heilen laesst. Der Entwurf wird mit einem
harten Fehler abgelehnt. Inlaendischer Reverse Charge (§ 13b Abs. 2 UStG:
deutsche oder keine USt-IdNr.) bleibt bei der Warnung. Gestellte Belege
werden beim erneuten Pruefen nicht ungueltig.

Naht: POST /invoices/{id}/finalisieren, echtes Postgres, gepatchte PDF-Pipeline.
"""
import html
from decimal import Decimal

import pytest

from app.main import app
from app.models.invoice import Invoice
from app.services.validator import validate_invoice
from tests.helpers.finalize_pipeline import (
    cleanup,
    finalize_with_fake_pipeline,
    valid_draft,
)


def teardown_function():
    app.dependency_overrides.clear()


def _ae_entwurf(pg_session, *, land, ust_id):
    inv = valid_draft(pg_session, prefix="RE-AE")
    inv.tax_category = "AE"
    inv.tax_total = Decimal("0.00")
    inv.gross_total = Decimal("200.00")
    for pos in inv.items:
        pos.tax_rate = Decimal("0")
        pos.tax_amount = Decimal("0.00")
        pos.gross_amount = Decimal("200.00")
    inv.customer.country = land
    inv.customer.vat_id = ust_id
    pg_session.commit()
    return inv


def test_ae_an_kunde_de_mit_auslaendischer_ust_id_wird_abgelehnt(pg_session):
    inv = _ae_entwurf(pg_session, land="DE", ust_id="FR12345678901")
    nummer = inv.invoice_number
    try:
        r = finalize_with_fake_pipeline(pg_session, inv.id)
        assert r.status_code == 400, r.text
        text = html.unescape(r.text)
        assert "Kunden mit Land DE" in text
        assert "beim Kunden prüfen, speichern und die Rechnung neu finalisieren" in text
        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.status == "draft"
        assert row.zugferd_xml is None
    finally:
        cleanup(nummer)


def test_ae_an_auslandskunde_mit_passender_ust_id_geht_durch(pg_session):
    inv = _ae_entwurf(pg_session, land="FR", ust_id="FR12345678901")
    try:
        r = finalize_with_fake_pipeline(pg_session, inv.id)
        assert r.status_code in (200, 303), r.text
        pg_session.expire_all()
        assert pg_session.get(Invoice, inv.id).status == "issued"
    finally:
        cleanup(inv.invoice_number)


def test_ae_an_kunde_de_mit_deutscher_ust_id_geht_durch_mit_warnung(pg_session):
    inv = _ae_entwurf(pg_session, land="DE", ust_id="DE123456789")
    try:
        errors, warnings = validate_invoice(inv, _firma(pg_session))
        assert "TAX_CATEGORY_COUNTRY_MISMATCH" in {w.code for w in warnings}
        assert "TAX_CATEGORY_COUNTRY_MISMATCH" not in {e.code for e in errors}
        r = finalize_with_fake_pipeline(pg_session, inv.id)
        assert r.status_code in (200, 303), r.text
    finally:
        cleanup(inv.invoice_number)


def test_ae_an_kunde_de_ohne_ust_id_loest_die_neue_sperre_nicht_aus(pg_session):
    """Ohne USt-IdNr. sperrt schon BUYER_VAT_ID_REQUIRED (Pflicht bei AE); die
    neue Regel darf dazu nichts beitragen, die Warnung bleibt."""
    inv = _ae_entwurf(pg_session, land="DE", ust_id=None)
    try:
        errors, warnings = validate_invoice(inv, _firma(pg_session))
        codes = {e.code for e in errors}
        assert "AE_DOMESTIC_FOREIGN_VAT_ID" not in codes
        assert "BUYER_VAT_ID_REQUIRED" in codes
        assert "TAX_CATEGORY_COUNTRY_MISMATCH" in {w.code for w in warnings}
    finally:
        cleanup(inv.invoice_number)


def test_griechische_ust_id_el_zu_land_gr_ist_kein_widerspruch(pg_session):
    inv = _ae_entwurf(pg_session, land="GR", ust_id="EL123456789")
    try:
        errors, _ = validate_invoice(inv, _firma(pg_session))
        assert "AE_DOMESTIC_FOREIGN_VAT_ID" not in {e.code for e in errors}
    finally:
        cleanup(inv.invoice_number)


def test_gestellter_beleg_mit_widerspruch_bleibt_nur_warnung(pg_session):
    inv = _ae_entwurf(pg_session, land="DE", ust_id="FR12345678901")
    inv.status = "issued"
    pg_session.commit()
    try:
        errors, warnings = validate_invoice(inv, _firma(pg_session))
        assert "AE_DOMESTIC_FOREIGN_VAT_ID" not in {e.code for e in errors}
        assert "TAX_CATEGORY_COUNTRY_MISMATCH" in {w.code for w in warnings}
    finally:
        cleanup(inv.invoice_number)


def _firma(pg_session):
    from app.services.rechnung.firma import get_company
    return get_company(pg_session)
