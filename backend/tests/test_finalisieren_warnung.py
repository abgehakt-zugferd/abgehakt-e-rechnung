"""Eine Mustang-Warnung beim Finalisieren sperrt, bis der Nutzer sie bestätigt (#299).

Naht: POST /invoices/{id}/finalisieren (TestClient, echtes Postgres). Die PDF-
Pipeline ist gepatcht, nur der Mustang-Bericht ist vorgegeben; ein Test läuft mit
echtem Mustang und Ghostscript. Entwurf bleibt Entwurf: keine Nummer verbraucht,
keine Dateien, kein Prüfergebnis.
"""
import hashlib
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.company import Company
from app.models.invoice import Invoice, ValidationResult
from app.services import mustang, pdfa
from tests.helpers.finalize_pipeline import (
    cleanup,
    client,
    patched_success_pipeline,
    valid_draft,
)
from tests.test_lieferblock_leer import BERICHT_WARNUNG

R008 = "PEPPOL-EN16931-R008"
LEERER_BLOCK = ("\n        <ram:ApplicableHeaderTradeDelivery>\n"
                "        </ram:ApplicableHeaderTradeDelivery>")


def _warnend():
    return {"is_valid": True, "nicht_ausfuehrbar": False, "raw": BERICHT_WARNUNG,
            "errors": [], "warnings": []}


def _sauber():
    return {"is_valid": True, "nicht_ausfuehrbar": False, "errors": [], "warnings": [],
            "raw": "Parsed PDF:valid\nXML:valid\n"}


def _finalisieren(pg_session, inv, ergebnis, bestaetigt=()):
    with patched_success_pipeline(validate=ergebnis):
        return client(pg_session).post(
            f"/invoices/{inv.id}/finalisieren", data={"bestaetigt": list(bestaetigt)})


def _frisch(pg_session, inv):
    pg_session.expire_all()
    return pg_session.get(Invoice, inv.id)


def _protokolle(pg_session, inv):
    return pg_session.query(ValidationResult).filter(ValidationResult.invoice_id == inv.id).all()


@pytest.fixture
def entwurf(pg_session):
    inv = valid_draft(pg_session, prefix="RE-WARN")
    yield inv
    cleanup(inv.invoice_number)


def test_warnung_haelt_die_finalisierung_an_und_zeigt_regel_und_text(pg_session, entwurf):
    nummer = entwurf.invoice_number
    zaehler = pg_session.query(Company).one().invoice_counter

    r = _finalisieren(pg_session, entwurf, _warnend())

    assert r.status_code == 409
    assert R008 in r.text
    assert "Document MUST not contain empty elements" in r.text
    assert "TROTZ WARNUNG FINALISIEREN" in r.text
    assert f'data-warnung-regel="{R008}"' in r.text
    assert "[ID" not in r.text and "xslt" not in r.text   # kein Schematron-Anhang
    row = _frisch(pg_session, entwurf)
    assert row.status == "draft"
    assert row.zugferd_xml is None and row.pdf_filename is None
    assert row.invoice_number == nummer
    assert pg_session.query(Company).one().invoice_counter == zaehler
    assert _protokolle(pg_session, entwurf) == []


def test_abgewiesene_finalisierung_gibt_die_zeilensperre_frei(pg_session, pg_engine, entwurf):
    """Rollback wie bei einem Fehler: Die Sperre auf dem Entwurf (FOR UPDATE) ist
    danach frei, eine zweite Verbindung kommt sofort heran."""
    from sqlalchemy import text

    _finalisieren(pg_session, entwurf, _warnend())

    with pg_engine.connect() as zweite:
        zweite.execute(text("SELECT id FROM invoices WHERE id = :i FOR UPDATE NOWAIT"),
                       {"i": entwurf.id})


def test_bestaetigung_derselben_warnung_finalisiert_und_protokolliert(pg_session, entwurf):
    r = _finalisieren(pg_session, entwurf, _warnend(), bestaetigt=[R008])

    assert r.status_code == 303
    row = _frisch(pg_session, entwurf)
    assert row.status == "issued"
    (vr,) = _protokolle(pg_session, entwurf)
    assert vr.anlass == "finalisierung"
    assert vr.is_valid is True
    assert vr.bestaetigte_regeln == [R008]
    assert vr.bestaetigt_am is not None
    assert vr.xml_sha256 == hashlib.sha256(row.zugferd_xml.encode("utf-8")).hexdigest()
    codes = [w["code"] for w in vr.warnings]
    assert f"MUSTANG_{R008}" in codes and "MUSTANG_WARNUNG_BESTAETIGT" in codes


def test_bestaetigung_einer_anderen_regel_genuegt_nicht(pg_session, entwurf):
    r = _finalisieren(pg_session, entwurf, _warnend(), bestaetigt=["BR-ANDERE-1"])

    assert r.status_code == 409
    assert _frisch(pg_session, entwurf).status == "draft"
    assert _protokolle(pg_session, entwurf) == []


def test_bestaetigung_von_mehr_regeln_als_gemeldet_fragt_erneut(pg_session, entwurf):
    r = _finalisieren(pg_session, entwurf, _warnend(), bestaetigt=[R008, "BR-ANDERE-1"])

    assert r.status_code == 409
    assert _frisch(pg_session, entwurf).status == "draft"


def test_finalisierung_ohne_warnung_speichert_trotzdem_ein_pruefergebnis(pg_session, entwurf):
    r = _finalisieren(pg_session, entwurf, _sauber())

    assert r.status_code == 303
    (vr,) = _protokolle(pg_session, entwurf)
    assert vr.anlass == "finalisierung"
    assert vr.bestaetigte_regeln is None and vr.bestaetigt_am is None
    assert not [w for w in vr.warnings if w["code"].startswith("MUSTANG_")]


def test_fehlerelement_im_bericht_sperrt_auch_wenn_is_valid_wahr_gemeldet_wird(pg_session, entwurf):
    """Ein Fehler in den Befunden blockiert, egal was is_valid behauptet."""
    ergebnis = {"is_valid": True, "nicht_ausfuehrbar": False, "errors": [], "warnings": [],
                "raw": '<error type="4">[BR-07]-Kaputt [ID BR-07] from x.xslt)</error>\nXML:valid\n'}

    r = _finalisieren(pg_session, entwurf, ergebnis)

    assert r.status_code == 400
    assert _frisch(pg_session, entwurf).status == "draft"


def test_mustang_fehler_sperren_weiter_hart(pg_session, entwurf):
    fehler = {"is_valid": False, "nicht_ausfuehrbar": False, "errors": [],
              "warnings": [], "raw": "<error>[BR-07]-Kaputt [ID BR-07] from x.xslt)</error>"}

    r = _finalisieren(pg_session, entwurf, fehler, bestaetigt=["BR-07"])

    assert r.status_code == 400
    assert _frisch(pg_session, entwurf).status == "draft"


# -- Anzeige ----------------------------------------------------------------

def test_protokoll_der_finalisierten_rechnung_zeigt_warnung_ohne_erneut_pruefen(pg_session, entwurf):
    _finalisieren(pg_session, entwurf, _warnend(), bestaetigt=[R008])

    seite = client(pg_session).get(f"/invoices/{entwurf.id}").text

    assert "Prüfung beim Finalisieren am" in seite
    assert f'data-mustang-regel="{R008}"' in seite
    assert "Trotz Warnung finalisiert am" in seite
    assert "data-pruefung-veraltet" not in seite


def test_ergebnis_zu_anderem_xml_wird_nicht_als_aktuell_ausgegeben(pg_session, entwurf):
    _finalisieren(pg_session, entwurf, _sauber())
    pg_session.add(ValidationResult(invoice_id=entwurf.id, is_valid=True, errors=[], warnings=[],
                                    xml_sha256="0" * 64, anlass="pruefung"))
    pg_session.commit()

    seite = client(pg_session).get(f"/invoices/{entwurf.id}").text

    assert "data-pruefung-veraltet" in seite


# -- Echter Mustang ----------------------------------------------------------

@pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)
def test_echte_mustang_warnung_haelt_an_und_wird_bestaetigt(pg_session):
    # Ein leerer Lieferblock ist eine echte R008-Warnung; er wird hier erzwungen,
    # damit der Test nicht an der Lieferblock-Logik hängt.
    inv = valid_draft(pg_session, prefix="RE-REAL")
    try:
        with patch("app.services.zugferd_xml.erzeugen.delivery_xml", return_value=LEERER_BLOCK):
            erste = client(pg_session).post(f"/invoices/{inv.id}/finalisieren")
            assert erste.status_code == 409, erste.text[-800:]
            assert R008 in erste.text
            assert _frisch(pg_session, inv).status == "draft"

            zweite = client(pg_session).post(
                f"/invoices/{inv.id}/finalisieren", data={"bestaetigt": [R008]})
        assert zweite.status_code == 303
        assert _frisch(pg_session, inv).status == "issued"
        (vr,) = _protokolle(pg_session, inv)
        assert vr.bestaetigte_regeln == [R008]
        assert f"MUSTANG_{R008}" in [w["code"] for w in vr.warnings]
    finally:
        cleanup(inv.invoice_number)
