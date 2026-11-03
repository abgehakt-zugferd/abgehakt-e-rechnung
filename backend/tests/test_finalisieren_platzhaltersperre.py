"""
Platzhaltersperre beim Finalisieren (#270): Ein Entwurf, dessen Kopf- oder
Fusstext noch einen Platzhalter zum Ersetzen traegt (<M>, <MM/JJJJ>, <nr>),
darf nicht finalisiert werden. Sonst stuende der Platzhalter woertlich in PDF
und XML, Heilung nur per Storno. Der Entwurf bleibt unveraendert.

Naht: POST /invoices/{id}/finalisieren, echtes Postgres, gepatchte PDF-Pipeline.
"""
import html

import pytest

from app.main import app
from app.models.invoice import Invoice
from tests.helpers.finalize_pipeline import (
    cleanup,
    finalize_with_fake_pipeline,
    valid_draft,
)


def teardown_function():
    app.dependency_overrides.clear()


def _entwurf(pg_session, **felder):
    inv = valid_draft(pg_session, prefix="RE-PH")
    for name, wert in felder.items():
        setattr(inv, name, wert)
    pg_session.commit()
    return inv


def test_kopftext_mit_platzhalter_wird_abgelehnt(pg_session):
    inv = _entwurf(pg_session, kopftext="Angabe nach Vorschrift: <M>")
    nummer = inv.invoice_number
    try:
        r = finalize_with_fake_pipeline(pg_session, inv.id)
        assert r.status_code == 400
        assert html.escape("Kopftext enthält noch den Platzhalter <M>") in r.text
        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.status == "draft"
        assert row.kopftext == "Angabe nach Vorschrift: <M>"
        assert row.zugferd_xml is None
    finally:
        cleanup(nummer)


def test_ersetzter_platzhalter_geht_durch(pg_session):
    inv = _entwurf(pg_session, kopftext="Angabe nach Vorschrift: erledigt")
    try:
        r = finalize_with_fake_pipeline(pg_session, inv.id)
        assert r.status_code in (200, 303), r.text
        pg_session.expire_all()
        assert pg_session.get(Invoice, inv.id).status == "issued"
    finally:
        cleanup(inv.invoice_number)


@pytest.mark.parametrize("platzhalter", ["<M>", "<MM/JJJJ>", "<nr>"])
def test_fusstext_mit_platzhalter_wird_abgelehnt(pg_session, platzhalter):
    inv = _entwurf(pg_session, fusstext=f"Leistungsmonat {platzhalter}")
    try:
        r = finalize_with_fake_pipeline(pg_session, inv.id)
        assert r.status_code == 400
        meldung = f"Fußtext enthält noch den Platzhalter {platzhalter}"
        assert html.escape(meldung) in r.text
        pg_session.expire_all()
        assert pg_session.get(Invoice, inv.id).status == "draft"
    finally:
        cleanup(inv.invoice_number)


@pytest.mark.parametrize("text", [
    "Menge < 5 und Preis > 3",
    "a > b",
    "weniger als <10 €",
    "a < b > c",
    "Leerer Winkel <> bleibt",
])
def test_klartext_mit_spitzen_klammern_sperrt_nicht(pg_session, text):
    inv = _entwurf(pg_session, kopftext=text, fusstext=text)
    try:
        r = finalize_with_fake_pipeline(pg_session, inv.id)
        assert r.status_code in (200, 303), r.text
    finally:
        cleanup(inv.invoice_number)
