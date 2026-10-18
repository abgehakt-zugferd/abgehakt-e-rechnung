"""7e: Storno bleibt Entwurf; erst sein Stellen hebt das Original auf."""
from datetime import date

import pytest
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.models.aufstellung import Aufstellung
from app.services import aufstellung_finalisieren as stellen
from app.services.aufstellung_guard import AufstellungStateError, register_aufstellung_guard
from app.services.aufstellung_storno import entwurf_anlegen, StornoFehler
from app.services.auftragsschluessel import dokument_zu
from tests.factories_aufstellung import speichere_aufstellung, orm_anlage
from tests.test_aufstellungsauftrag_wirkung import _entwurf
from tests.helpers.uebergabe import aufstellungsauftrag

register_aufstellung_guard()
SCHLUESSEL = "bericht:2026-09:probe"


def _original(db):
    return speichere_aufstellung(db, status="issued", ausstellungsdatum=date(2026, 10, 1),
                                schluessel=SCHLUESSEL)


def _archiv_attrappe(a, company, temp, settings):
    ziel = settings.storage_path / "aufstellungen" / f"{a.nummer}.pdf"
    ziel.parent.mkdir(exist_ok=True)
    ziel.write_bytes(b"%PDF-Probe")
    return ziel


def test_storno_entwurf_kopiert_ohne_anlagen_oder_sperre(pg_session):
    original = _original(pg_session)
    s = entwurf_anlegen(pg_session, original)
    pg_session.commit()
    assert s.status == "draft" and s.storniert_id == original.id
    assert s.nummer != original.nummer and s.nummer.startswith("AA-")
    for feld in ("customer_id", "leistung_von", "leistung_bis", "waehrung", "brutto",
                 "quellensteuer", "netto", "kurs", "zahlbetrag_eur", "zahlungsdatum",
                 "zahlungsnummer"):
        assert getattr(s, feld) == getattr(original, feld)
    assert s.anlagen == [] and s.auftragsschluessel_offen is None
    assert s.ausstellungsdatum is None and s.datev_sent_at is None
    assert original.status == "issued" and dokument_zu(pg_session, SCHLUESSEL) == original.nummer


def test_finalisieren_gibt_schluessel_fuer_neuen_auftrag_frei(pg_session, monkeypatch):
    pg_session.autoflush = True
    original = _original(pg_session)
    s = entwurf_anlegen(pg_session, original)
    pg_session.commit()
    monkeypatch.setattr(stellen, "_archivieren", _archiv_attrappe)
    stellen.finalisieren(pg_session, s, get_settings())
    assert s.status == "issued" and original.status == "cancelled"
    assert original.auftragsschluessel == SCHLUESSEL
    assert dokument_zu(pg_session, SCHLUESSEL) is None
    nutzlast = aufstellungsauftrag()
    nutzlast["auftragsschluessel"] = SCHLUESSEL
    nutzlast["kunde"]["partner_id"] = str(original.customer_id)
    neuer = _entwurf(pg_session, nutzlast)
    pg_session.commit()
    assert neuer.auftragsschluessel_offen == SCHLUESSEL


def test_pdf_fehler_laesst_original_und_sperre_stehen(pg_session, monkeypatch):
    original = _original(pg_session)
    s = entwurf_anlegen(pg_session, original)
    pg_session.commit()

    def fehler(*args):
        raise stellen.FinalisierenFehler("PDF Probe")

    monkeypatch.setattr(stellen, "_archivieren", fehler)
    with pytest.raises(stellen.FinalisierenFehler):
        stellen.finalisieren(pg_session, s, get_settings())
    assert original.status == "issued" and s.status == "draft"
    assert dokument_zu(pg_session, SCHLUESSEL) == original.nummer


def test_direktes_cancelled_auch_mit_stornoentwurf_verboten(pg_session):
    original = _original(pg_session)
    entwurf_anlegen(pg_session, original)
    pg_session.commit()
    original.status = "cancelled"
    original.auftragsschluessel_offen = None
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()


def test_hoechstens_ein_aktives_storno_auch_beim_zurueckholen(pg_session):
    original = _original(pg_session)
    erstes = entwurf_anlegen(pg_session, original)
    pg_session.commit()
    with pytest.raises(StornoFehler):
        entwurf_anlegen(pg_session, original)
    erstes.status = "discarded"
    pg_session.commit()
    zweites = entwurf_anlegen(pg_session, original)
    pg_session.commit()
    assert zweites.id != erstes.id
    erstes.status = "draft"
    with pytest.raises(IntegrityError):
        pg_session.commit()
    pg_session.rollback()


@pytest.mark.parametrize("status", ["draft", "discarded", "cancelled"])
def test_nur_gestelltes_original(pg_session, status):
    a = speichere_aufstellung(pg_session, status=status)
    with pytest.raises(StornoFehler):
        entwurf_anlegen(pg_session, a)


def test_storno_kann_nicht_storniert_werden(pg_session, monkeypatch):
    s = entwurf_anlegen(pg_session, _original(pg_session))
    pg_session.commit()
    monkeypatch.setattr(stellen, "_archivieren", _archiv_attrappe)
    stellen.finalisieren(pg_session, s, get_settings())
    with pytest.raises(StornoFehler):
        entwurf_anlegen(pg_session, s)


def test_storno_hat_auch_im_entwurf_keine_eigenen_anlagen(pg_session):
    s = entwurf_anlegen(pg_session, _original(pg_session))
    pg_session.commit()
    s.anlagen.append(orm_anlage())
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()


def test_storno_route(client, pg_session):
    a = _original(pg_session)
    r = client.post(f"/aufstellungen/{a.id}/stornieren")
    assert r.status_code == 303
    s = pg_session.query(Aufstellung).filter(Aufstellung.storniert_id == a.id).one()
    assert r.headers["location"] == f"/aufstellungen/{s.id}"
    assert client.post(f"/aufstellungen/{a.id}/stornieren").status_code == 400


@pytest.mark.parametrize("feld,wert", [("netto", 12), ("storniert_id", None),
                                       ("original", None)])
def test_storno_entwurf_bleibt_ans_original_gebunden(pg_session, feld, wert):
    s = entwurf_anlegen(pg_session, _original(pg_session))
    pg_session.commit()
    setattr(s, feld, wert)
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()


def test_commitfehler_nimmt_storno_pdf_und_aufhebung_zurueck(pg_session, monkeypatch):
    original = _original(pg_session)
    s = entwurf_anlegen(pg_session, original)
    pg_session.commit()
    nummer = s.nummer
    monkeypatch.setattr(stellen, "_archivieren", _archiv_attrappe)

    def fehler():
        pg_session.flush()
        raise RuntimeError("Commit Probe")

    monkeypatch.setattr(pg_session, "commit", fehler)
    with pytest.raises(RuntimeError, match="Commit Probe"):
        stellen.finalisieren(pg_session, s, get_settings())
    assert original.status == "issued" and s.status == "draft"
    assert dokument_zu(pg_session, SCHLUESSEL) == original.nummer
    assert not (get_settings().storage_path / "aufstellungen" / f"{nummer}.pdf").exists()


def test_storno_durch_finalisieren_und_versandroute(client, pg_session, monkeypatch):
    from unittest.mock import patch
    from app.services import datev_email
    original = _original(pg_session)
    s = entwurf_anlegen(pg_session, original)
    pg_session.commit()
    monkeypatch.setattr(stellen, "_archivieren", _archiv_attrappe)
    assert client.post(f"/aufstellungen/{s.id}/finalisieren").status_code == 303
    with patch.object(datev_email, "upload_adresse", return_value="upload@example.test"), \
         patch.object(datev_email, "send_invoice") as send:
        assert client.post(f"/aufstellungen/{s.id}/an-buchhaltung").status_code == 303
    assert send.call_args.kwargs["pdf_path"].name == f"{s.nummer}.pdf"
    pg_session.refresh(original)
    pg_session.refresh(s)
    assert original.status == "cancelled" and s.datev_sent_at is not None
