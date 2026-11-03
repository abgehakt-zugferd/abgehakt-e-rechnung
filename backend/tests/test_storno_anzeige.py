"""Belegansicht und Liste zeigen „storniert durch“ (#269) und den Hinweis zum Storno
einer 389 (#267).

Die Anzeige ist abgeleitet, nicht gesetzt: der Status des Originals bleibt, wie er
ist (docs/ANWENDUNG.md, „Warum das Original nicht von selbst auf storniert springt“).
Die Regel, wann ein Storno wirkt, steht in `storno_wirkung`; die Tests pruefen, was
die Seiten daraus machen.
"""
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

from app.database import get_db
from app.main import app
from tests.helpers.ersatzrechnung import beleg, kunde

KNOPF = 'name="new_status" value="cancelled"'
HINWEIS = 'data-hinweis="gutschrift-endgueltig"'


@pytest.fixture
def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


def _storniert_durch(text: str, storno) -> bool:
    muster = (rf'storniert durch\s*<a href="/invoices/{storno.id}"[^>]*>\s*'
              rf'{re.escape(storno.invoice_number)}\s*</a>')
    return re.search(muster, text) is not None


def _original_mit_storno(pg_session, *, original_typ=None, storno_typ="credit_note",
                         original_status="issued", storno_status="issued", sprache="de"):
    original = beleg(pg_session, kunde(pg_session), status=original_status,
                     invoice_type=original_typ)
    storno = beleg(pg_session, original.customer, status=storno_status,
                   invoice_type=storno_typ, original=original, sprache=sprache)
    return original, storno


def _389_mit_storno(pg_session, **kw):
    return _original_mit_storno(
        pg_session, original_typ="self_billing", storno_typ="self_billing_storno", **kw)


def test_original_mit_gestelltem_storno_zeigt_storniert_durch_in_der_ansicht(pg_session, client):
    original, storno = _original_mit_storno(pg_session)

    text = client.get(f"/invoices/{original.id}").text

    assert _storniert_durch(text, storno)
    assert original.status == "issued"


def test_original_mit_gestelltem_storno_zeigt_storniert_durch_in_der_liste(pg_session, client):
    _, storno = _original_mit_storno(pg_session)

    assert _storniert_durch(client.get("/invoices/").text, storno)


def test_storno_einer_389_markiert_auch_dieses_original(pg_session, client):
    original, storno = _389_mit_storno(pg_session)

    assert _storniert_durch(client.get(f"/invoices/{original.id}").text, storno)
    assert _storniert_durch(client.get("/invoices/").text, storno)


def test_bezahlt_und_storniert_zeigt_beides(pg_session, client):
    original, storno = _original_mit_storno(pg_session, original_status="paid",
                                            storno_status="paid")

    text = client.get(f"/invoices/{original.id}").text

    assert _storniert_durch(text, storno)
    assert "BEZAHLT" in text.upper()


def test_storno_nur_als_entwurf_zeigt_nichts_und_laesst_den_knopf(pg_session, client):
    original, _ = _original_mit_storno(pg_session, storno_status="draft")

    ansicht = client.get(f"/invoices/{original.id}").text

    assert "storniert durch" not in ansicht
    assert "storniert durch" not in client.get("/invoices/").text
    assert KNOPF in ansicht


def test_knopf_als_storniert_markieren_fehlt_bei_wirksamem_storno(pg_session, client):
    original, _ = _original_mit_storno(pg_session)

    assert KNOPF not in client.get(f"/invoices/{original.id}").text


def test_knopf_fehlt_auch_bei_bezahltem_storno(pg_session, client):
    original, _ = _original_mit_storno(pg_session, storno_status="paid")

    assert KNOPF not in client.get(f"/invoices/{original.id}").text


def _abfragen_der_liste(pg_session, client) -> int:
    anfragen: list[str] = []

    def merken(conn, cursor, statement, *rest):
        anfragen.append(statement)

    engine = pg_session.get_bind()
    event.listen(engine, "before_cursor_execute", merken)
    try:
        client.get("/invoices/")
    finally:
        event.remove(engine, "before_cursor_execute", merken)
    return len(anfragen)


def test_liste_fragt_die_stornos_nicht_je_zeile_ab(pg_session, client):
    """Die Zahl der Abfragen haengt nicht an der Zahl der Zeilen (kein N+1)."""
    for _ in range(2):
        _original_mit_storno(pg_session)
    wenige = _abfragen_der_liste(pg_session, client)
    for _ in range(4):
        _original_mit_storno(pg_session)

    assert _abfragen_der_liste(pg_session, client) == wenige


def test_hinweis_beim_storno_einer_389_nennt_den_weg_und_verlinkt_das_original(
        pg_session, client):
    original, storno = _389_mit_storno(pg_session)

    text = client.get(f"/invoices/{storno.id}").text

    assert HINWEIS in text
    assert "endgültig" in text
    assert f'href="/invoices/{original.id}"' in text
    assert "neue Gutschrift" in text


def test_hinweis_beim_storno_einer_389_folgt_der_belegsprache(pg_session, client):
    _, storno = _389_mit_storno(pg_session, sprache="en")

    text = client.get(f"/invoices/{storno.id}").text

    assert HINWEIS in text
    assert "final" in text
    assert "new credit note" in text
    assert "neue Gutschrift" not in text


def test_hinweis_fehlt_beim_entwurf_eines_storno_einer_389(pg_session, client):
    _, storno = _389_mit_storno(pg_session, storno_status="draft")

    assert HINWEIS not in client.get(f"/invoices/{storno.id}").text
