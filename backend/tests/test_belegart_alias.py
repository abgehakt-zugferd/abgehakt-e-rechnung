"""Belegart-Aliase: Vergleiche loesen ueber belegart auf (Issue #172).

Rot = Rohvergleich ohne Alias; gruen = aufgeloeste Belegart bzw. Rohwertmenge.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.routers.invoices.ansicht import _ersetzbarkeit
from app.services import validator
from app.services.dashboard_kennzahlen import (
    nettoumsatz_ytd,
    offene_forderungen,
    schuldige_umsatzsteuer,
)
from app.services.invoice_guard import InvoiceStateError, register_invoice_guard
from app.services.rechnung.finalisieren import als_gestellt_markieren
from app.services.rechnungsliste_filter import filtere_rechnungsliste
from app.services.storno_wirkung import summe_gutschriften
from app.services.zugferd_xml.zahlung_summen import payment_terms_xml
from tests.helpers import belegart_alias as _ba

register_invoice_guard()

JAHRESBEGINN = date(2026, 1, 1)


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _kunde_a(pg_session):
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Beispiel GmbH",
        address_line1="Beispielweg 1",
        zip_code="80331",
        city="Muenchen",
        country="DE",
    )
    pg_session.add(c)
    pg_session.flush()
    return c


def _positionen():
    return [InvoiceItem(
        position=1, description="Beratung", unit="Stunde",
        quantity=Decimal("1"), unit_price=Decimal("100.00"),
        tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
        tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"),
    )]


def _beleg_a(pg_session, kunde, *, status="issued", invoice_type=None, original=None):
    inv = Invoice(
        invoice_number=f"RE-BA-{uuid.uuid4().hex[:6]}",
        customer_id=kunde.id,
        issue_date=date(2026, 6, 1),
        due_date=date(2026, 6, 15),
        delivery_date=date(2026, 6, 1),
        currency="EUR",
        tax_category="S",
        status=status,
        invoice_type=invoice_type,
        original_invoice_id=original.id if original else None,
        net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
        payment_terms="Zahlbar in 14 Tagen.",
    )
    inv.items = _positionen()
    pg_session.add(inv)
    pg_session.commit()
    return inv


# --- a: Alias-Loch im Storno-Schutz ------------------------------------------


@pytest.mark.parametrize("alias", ["credit", "storno"])
def test_a_storno_weg_lehnt_gestellte_alias_gutschrift_ab(pg_session, alias):
    """Gewuenscht: POST /storno auf Alias-Gutschrift scheitert (wie credit_note)."""
    kunde = _kunde_a(pg_session)
    original = _beleg_a(pg_session, kunde)
    gs = _beleg_a(pg_session, kunde, invoice_type=alias, original=original)

    r = _client(pg_session).post(f"/invoices/{gs.id}/storno")

    assert r.status_code == 400, (
        f"Alias {alias!r}: Storno-Weg legte an (HTTP {r.status_code}); "
        "erwartet Absage wie bei credit_note (_original_laden roh)"
    )
    pg_session.expire_all()
    folge = (
        pg_session.query(Invoice)
        .filter(Invoice.original_invoice_id == gs.id, Invoice.status != "discarded")
        .count()
    )
    assert folge == 0


@pytest.mark.parametrize("alias", ["credit", "storno"])
def test_a_waechter_sperrt_cancelled_bei_alias_gutschrift(pg_session, alias):
    """Gewuenscht: invoice_guard sperrt issued→cancelled auch fuer Aliase."""
    kunde = _kunde_a(pg_session)
    original = _beleg_a(pg_session, kunde)
    gs = _beleg_a(pg_session, kunde, invoice_type=alias, original=original)

    gs.status = "cancelled"
    with pytest.raises(InvoiceStateError, match="Gutschrift"):
        pg_session.flush()
    pg_session.rollback()


@pytest.mark.parametrize("alias", ["credit", "storno"])
def test_a_status_route_lehnt_cancelled_bei_alias_gutschrift_ab(pg_session, alias):
    """Gewuenscht: Route cancelled bei Alias-Gutschrift → 400 (pruefe_stornierbar)."""
    kunde = _kunde_a(pg_session)
    original = _beleg_a(pg_session, kunde)
    gs = _beleg_a(pg_session, kunde, invoice_type=alias, original=original)

    r = _client(pg_session).post(
        f"/invoices/{gs.id}/status", data={"new_status": "cancelled"},
    )

    assert r.status_code == 400, r.text
    assert "GUTSCHRIFT" in r.text.upper() or "Gutschrift" in r.text
    pg_session.expire_all()
    assert pg_session.get(Invoice, gs.id).status == "issued"


# --- Rohvergleiche der Storno-Belegart (Python) ------------------------------


def test_gutschrift_entwurf_mit_alias_storno_ist_nicht_bearbeitbar(pg_session):
    """formular_schreiben: Alias 'storno' sperrt wie 'credit_note'."""
    gs = _ba.gutschrift(pg_session, _ba.beleg(pg_session), art="storno", status="draft")
    r = _ba.client(pg_session).get(f"/invoices/{gs.id}/bearbeiten")
    assert r.status_code == 400, r.text


def test_detail_gutschrift_mit_alias_bietet_ersatzrechnung(pg_session):
    """ansicht._ersetzbarkeit: Alias 'storno' erkennt Original als ersetzbar."""
    original = _ba.beleg(pg_session)
    gs = _ba.gutschrift(pg_session, original, art="storno", status="issued")
    _, original_ersetzbar = _ersetzbarkeit(pg_session, gs)
    assert original_ersetzbar is True


def test_gestellte_alias_gutschrift_gibt_auftragsschluessel_frei(pg_session):
    """finalisieren.als_gestellt_markieren: Alias 'credit' hebt die Sperre."""
    schluessel = f"probe:{uuid.uuid4().hex[:8]}"
    original = _ba.beleg(pg_session, schluessel=schluessel)
    assert original.auftragsschluessel_offen == schluessel
    gs = _ba.gutschrift(pg_session, original, art="credit", status="draft")
    gs.original_invoice = original

    als_gestellt_markieren(gs, Path("RE-BA-probe.pdf"))

    assert gs.status == "issued"
    assert original.auftragsschluessel_offen is None


def test_alias_gutschrift_mit_abweichendem_betrag_faellt_im_spiegel(pg_session):
    """pruefregeln/belegbezug: Alias 'storno' unterliegt STORNO_AMOUNT_MISMATCH."""
    from app.models.company import Company
    firma = pg_session.query(Company).filter(Company.id == 1).one()
    original = _ba.beleg(pg_session)
    gs = _ba.gutschrift(pg_session, original, art="storno", status="draft")
    gs.gross_total = original.gross_total - Decimal("0.01")
    gs.original_invoice = original

    fehler, _ = validator.validate_invoice(gs, firma)
    assert "STORNO_AMOUNT_MISMATCH" in {f.code for f in fehler}


def test_alias_gutschrift_ohne_faelligkeitsdatum_in_der_xml():
    """zahlung_summen.payment_terms_xml: Alias 'storno' ohne BT-9 trotz due_date."""
    inv = SimpleNamespace(
        invoice_type="storno",
        due_date=date(2026, 5, 15),
        payment_terms="Zahlbar ohne Abzug.",
    )
    assert "DueDateDateTime" not in payment_terms_xml(inv)


# --- Alias in SQL-Filtern ----------------------------------------------------


def test_alias_gutschrift_mindert_umsatz_und_ust(pg_session):
    """dashboard/storno_wirkung: gestellte Alias-Gutschrift zaehlt wie credit_note."""
    original = _ba.beleg(pg_session)
    _ba.gutschrift(pg_session, original, art="storno", status="issued")
    assert nettoumsatz_ytd(pg_session, JAHRESBEGINN) == Decimal("0.00")
    assert schuldige_umsatzsteuer(pg_session, JAHRESBEGINN) == Decimal("0.00")


def test_listenfilter_gutschrift_findet_alias(pg_session):
    """rechnungsliste_filter art=gutschrift: Alias 'credit' erscheint in der Menge."""
    gs = _ba.gutschrift(pg_session, _ba.beleg(pg_session), art="credit", status="issued")
    query, _ = filtere_rechnungsliste(pg_session.query(Invoice), art="gutschrift")
    assert gs.id in {row.id for row in query.all()}


def test_alias_gutschrift_hebt_offene_forderung_auf(pg_session):
    """WIRKSAM_STORNIERT kennt Alias: Original ist nicht mehr offene Forderung."""
    original = _ba.beleg(pg_session)
    _ba.gutschrift(pg_session, original, art="storno", status="issued")
    offen = offene_forderungen(pg_session)
    assert (offen.anzahl, offen.betrag) == (0, Decimal("0"))


# --- Standardrechnung-Aliase "standard" / "invoice" (intern=None) -------------


@pytest.mark.parametrize("alias", ["standard", "invoice"])
def test_standard_alias_zaehlt_in_umsatz_und_ust(pg_session, alias):
    """Kennzahlen: gespeichertes 'standard'/'invoice' wie invoice_type None."""
    _ba.beleg(pg_session, art=alias, status="issued")
    assert nettoumsatz_ytd(pg_session, JAHRESBEGINN) == Decimal("100.00")
    assert schuldige_umsatzsteuer(pg_session, JAHRESBEGINN) == Decimal("19.00")


@pytest.mark.parametrize("alias", ["standard", "invoice"])
def test_standard_alias_ist_offene_forderung(pg_session, alias):
    """offene_forderungen: Alias der Standardrechnung erscheint in der Menge."""
    beleg = _ba.beleg(pg_session, art=alias, status="issued")
    offen = offene_forderungen(pg_session)
    assert offen.anzahl == 1
    assert offen.betrag == beleg.gross_total


@pytest.mark.parametrize("alias", ["standard", "invoice"])
def test_listenfilter_rechnung_findet_standard_alias(pg_session, alias):
    """rechnungsliste_filter art=rechnung: Alias wie None in der Umsatzmenge."""
    beleg = _ba.beleg(pg_session, art=alias, status="issued")
    query, _ = filtere_rechnungsliste(pg_session.query(Invoice), art="rechnung")
    assert beleg.id in {row.id for row in query.all()}


@pytest.mark.parametrize("alias", ["standard", "invoice"])
def test_gutschrift_zu_standard_alias_zaehlt_im_standard_topf(pg_session, alias):
    """summe_gutschriften(topf=None): Alias-Original gehoert zum Standard-Topf.

    Bewusst nicht nur nettoumsatz_ytd: ohne Alias-Filter sind Original und
    Abzug beide 0 (0-0), das wuerde den Topf-Pfad maskieren (L34).
    """
    original = _ba.beleg(pg_session, art=alias, status="issued")
    _ba.gutschrift(pg_session, original, art="credit_note", status="issued")
    abzug = summe_gutschriften(
        pg_session, Invoice.net_total, JAHRESBEGINN, topf=None,
    )
    assert abzug == Decimal("100.00"), (
        f"Gutschrift zu {alias!r}-Original nicht im Standard-Topf (abzug={abzug})"
    )
    assert nettoumsatz_ytd(pg_session, JAHRESBEGINN) == Decimal("0.00")
