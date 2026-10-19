"""7d: derselbe SMTP-Baustein, ausschliesslich archiviertes PDF an Upload."""
from datetime import date
from unittest.mock import patch

import pytest

from app.config import get_settings
from app.models.aufstellung_send_log import AufstellungSendLog
from app.services import datev_email
from tests.factories_aufstellung import speichere_aufstellung
from tests.mailtext_fixtures import smtp_doppel
from tests.test_datev_send import _cfg


def _gestellt(db):
    a = speichere_aufstellung(db, status="issued", ausstellungsdatum=date(2026, 10, 1),
                             pdf_filename="AA-versand.pdf")
    pfad = get_settings().storage_path / "aufstellungen" / a.pdf_filename
    pfad.parent.mkdir(exist_ok=True)
    pfad.write_bytes(b"%PDF-archivierte-probe")
    return a, pfad


def test_nur_upload_ein_pdf_erstversand_und_protokoll(client, pg_session):
    a, pfad = _gestellt(pg_session)
    gesendet, smtp = smtp_doppel()
    with patch.object(datev_email, "_get_effective_smtp_config",
                      return_value=_cfg(datev_bcc_email="upload@example.test")), \
         patch.object(datev_email.smtplib, "SMTP", smtp):
        assert client.post(f"/aufstellungen/{a.id}/an-buchhaltung").status_code == 303
        pg_session.refresh(a)
        erster = a.datev_sent_at
        assert erster is not None
        assert client.post(f"/aufstellungen/{a.id}/an-buchhaltung").status_code == 303
    pg_session.refresh(a)
    assert a.datev_sent_at == erster
    msg = gesendet["msg"]
    assert msg["To"] == "upload@example.test"
    assert msg["Cc"] is None and msg["Bcc"] is None
    anlagen = list(msg.iter_attachments())
    assert len(anlagen) == 1
    assert anlagen[0].get_content_type() == "application/pdf"
    assert anlagen[0].get_payload(decode=True) == pfad.read_bytes()
    assert "ZUGFeRD" not in gesendet["body"]
    assert a.nummer in gesendet["subject"]
    logs = pg_session.query(AufstellungSendLog).all()
    assert len(logs) == 2
    assert all(l.success and l.ziel == "buchhaltung" and l.aufstellung_id == a.id
               and l.to_email == "upload@example.test" for l in logs)


def test_ohne_upload_verstaendlicher_fehler(client, pg_session):
    a, _ = _gestellt(pg_session)
    with patch.object(datev_email, "upload_adresse", return_value=None), \
         patch.object(datev_email, "send_invoice") as send:
        r = client.post(f"/aufstellungen/{a.id}/an-buchhaltung")
    assert r.status_code == 400 and "Upload-Adresse" in r.text
    send.assert_not_called()
    assert pg_session.query(AufstellungSendLog).count() == 0


def test_smtp_fehler_bleibt_im_protokoll(client, pg_session):
    a, _ = _gestellt(pg_session)
    with patch.object(datev_email, "upload_adresse", return_value="upload@example.test"), \
         patch.object(datev_email, "send_invoice", side_effect=datev_email.EmailError("SMTP Probe")):
        r = client.post(f"/aufstellungen/{a.id}/an-buchhaltung")
    assert r.status_code == 400
    pg_session.refresh(a)
    assert a.datev_sent_at is None
    log = pg_session.query(AufstellungSendLog).one()
    assert log.success is False and "SMTP Probe" in log.error


@pytest.mark.parametrize("status", ["draft", "discarded", "cancelled"])
def test_versand_nur_gestellt(client, pg_session, status):
    a = speichere_aufstellung(pg_session, status=status)
    with patch.object(datev_email, "send_invoice") as send:
        assert client.post(f"/aufstellungen/{a.id}/an-buchhaltung").status_code == 400
    send.assert_not_called()


def test_versuch_steht_vor_smtp(client, pg_session, pg_engine):
    from sqlalchemy.orm import Session
    a, _ = _gestellt(pg_session)

    def probe(**kwargs):
        with Session(pg_engine) as db:
            log = db.query(AufstellungSendLog).one()
            assert log.success is None and log.aufstellung_id == a.id

    with patch.object(datev_email, "upload_adresse", return_value="upload@example.test"), \
         patch.object(datev_email, "send_invoice", side_effect=probe):
        assert client.post(f"/aufstellungen/{a.id}/an-buchhaltung").status_code == 303


def test_fehlendes_pdf_wird_nicht_neu_erzeugt(client, pg_session):
    a, pfad = _gestellt(pg_session)
    pfad.unlink()
    with patch.object(datev_email, "send_invoice") as send:
        r = client.post(f"/aufstellungen/{a.id}/an-buchhaltung")
    assert r.status_code == 400 and "PDF" in r.text
    send.assert_not_called()


def test_neue_routen_unbekannte_id(client):
    import uuid
    for aktion in ("an-buchhaltung", "stornieren"):
        assert client.post(f"/aufstellungen/{uuid.uuid4()}/{aktion}").status_code == 404


def test_commitfehler_nach_smtp_laesst_ausgang_offen(pg_session, monkeypatch):
    from app.services.aufstellung_versand import senden
    a, _ = _gestellt(pg_session)
    commit = pg_session.commit
    aufrufe = 0

    def commit_probe():
        nonlocal aufrufe
        aufrufe += 1
        if aufrufe == 2:
            raise RuntimeError("Commit nach SMTP Probe")
        commit()

    monkeypatch.setattr(pg_session, "commit", commit_probe)
    with patch.object(datev_email, "upload_adresse", return_value="upload@example.test"), \
         patch.object(datev_email, "send_invoice") as send:
        with pytest.raises(RuntimeError, match="Commit nach SMTP"):
            senden(pg_session, a, get_settings())
    pg_session.rollback()
    send.assert_called_once()
    assert pg_session.query(AufstellungSendLog).one().success is None
    assert a.datev_sent_at is None
