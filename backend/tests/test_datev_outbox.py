"""Der Versandnachweis entsteht vor der Mail, nicht danach (#10).

Bisher lief die Reihenfolge andersherum: erst `send_invoice`, dann die
Protokollzeile, dann `db.commit()`. Scheitert der Commit, ist die Mail beim
Kunden und beim Steuerbuero, und die Datenbank weiss nichts davon. Die Nutzerin
sieht eine Fehlerseite, klickt erneut, und der Beleg geht ein zweites Mal raus.

Der in #10 genannte Nachstellweg (Guard-Fehler beim zweiten Versand) ist seit
#146 zu, weil `datev_sent_at` nur noch beim Erstversand gesetzt wird. Die Luecke
dahinter ist es nicht: jeder echte Commit-Fehler nach erfolgreichem SMTP
hinterlaesst dieselbe Leerstelle.

Die Zusage dieser Datei: bevor SMTP angesprochen wird, steht der Versuch
committet in der Datenbank. Sein Ausgang ist dann noch offen (`success is None`),
und genau so wird er auch angezeigt. Ein Versuch mit offenem Ausgang ist eine
unbequeme, aber ehrliche Auskunft: die Mail koennte drausssen sein. Ein stilles
Nichts an derselben Stelle war eine falsche.

Warum nicht einfach `success = False` vorschreiben und spaeter berichtigen: eine
Zeile, die „fehlgeschlagen" sagt, obwohl niemand das weiss, ist genau die Auskunft,
auf die hin jemand erneut sendet.
"""
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceSendLog
from app.services import datev_email


def teardown_function():
    app.dependency_overrides.clear()


def _valid_mustang():
    return {"is_valid": True, "raw": "Parsed PDF:valid\nXML:valid",
            "errors": [], "warnings": []}


def _seed(pg_session):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="80331", city="München",
                 country="DE", email="kunde@example.de")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"RE-OUT-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=date(2026, 6, 1), due_date=date(2026, 6, 15), currency="EUR",
                  net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
                  gross_total=Decimal("119.00"), status="issued", pdf_filename="RE.pdf")
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _logs(session, invoice_id):
    return (session.query(InvoiceSendLog)
            .filter(InvoiceSendLog.invoice_id == invoice_id)
            .order_by(InvoiceSendLog.sent_at).all())


def _mustang_patches():
    return (patch("app.routers.invoices.mustang.jar_available", return_value=True),
            patch("app.routers.invoices.mustang.validate", return_value=_valid_mustang()))


def test_der_versuch_ist_committet_bevor_smtp_angesprochen_wird(pg_session, pg_engine):
    """Der Kern von #10.

    Gemessen wird von einer ZWEITEN Verbindung aus, waehrend `send_invoice` laeuft:
    sie sieht nur, was wirklich committet ist. Eine Zeile, die bloss `db.add`
    gesagt bekam, ist von dort unsichtbar.
    """
    inv = _seed(pg_session)
    gesehen = {}

    def waehrend_des_versands(**kwargs):
        beobachter = sessionmaker(bind=pg_engine)()
        try:
            zeilen = _logs(beobachter, inv.id)
            gesehen["anzahl"] = len(zeilen)
            gesehen["ausgang"] = [z.success for z in zeilen]
            gesehen["empfaenger"] = [z.to_email for z in zeilen]
        finally:
            beobachter.close()

    jar, val = _mustang_patches()
    with patch.object(datev_email, "send_invoice", side_effect=waehrend_des_versands), jar, val:
        r = _client(pg_session).post(f"/invoices/{inv.id}/datev-senden")

    assert r.status_code == 303
    assert gesehen["anzahl"] == 1, "Der Versuch stand beim Senden nicht in der Datenbank"
    assert gesehen["ausgang"] == [None], "Der Ausgang war beim Senden noch nicht offen"
    assert gesehen["empfaenger"] == ["kunde@example.de"]

    pg_session.expire_all()
    zeilen = _logs(pg_session, inv.id)
    assert len(zeilen) == 1, "Der Versuch wurde ein zweites Mal protokolliert"
    assert zeilen[0].success is True


def test_scheitert_der_commit_nach_dem_versand_bleibt_der_versuch_stehen(pg_session, pg_engine):
    """Der gemeldete Fall: die Mail ist raus, der Commit danach faellt um."""
    inv = _seed(pg_session)
    echt = pg_session.commit
    zaehler = {"n": 0}

    def commit_mit_ausfall():
        zaehler["n"] += 1
        if zaehler["n"] == 1:
            return echt()
        raise RuntimeError("Verbindung zur Datenbank verloren")

    jar, val = _mustang_patches()
    with patch.object(datev_email, "send_invoice") as gesendet, jar, val, \
            patch.object(pg_session, "commit", commit_mit_ausfall):
        with pytest.raises(RuntimeError):
            _client(pg_session).post(f"/invoices/{inv.id}/datev-senden")

    gesendet.assert_called_once()
    pg_session.rollback()
    beobachter = sessionmaker(bind=pg_engine)()
    try:
        zeilen = _logs(beobachter, inv.id)
        assert len(zeilen) == 1, "Von der Mail blieb keine Spur"
        assert zeilen[0].success is None, "Ein unbekannter Ausgang wurde als Ergebnis ausgegeben"
        rechnung = beobachter.query(Invoice).filter(Invoice.id == inv.id).first()
        assert rechnung.datev_sent_at is None
    finally:
        beobachter.close()


def test_ein_offener_ausgang_wird_als_offen_angezeigt(pg_session):
    """Ein „✗" an dieser Stelle waere die Auskunft, die zum Doppelversand fuehrt."""
    inv = _seed(pg_session)
    pg_session.add(InvoiceSendLog(invoice_id=inv.id, to_email="kunde@example.de",
                                  datev_bcc=True, success=None))
    pg_session.commit()

    r = _client(pg_session).get(f"/invoices/{inv.id}")

    assert r.status_code == 200
    assert "AUSGANG UNBEKANNT" in r.text
    assert "kunde@example.de" in r.text
    # Auch das Zeichen davor darf nicht luegen: ein Kreuz liest sich als
    # „nicht rausgegangen", und dann klickt jemand noch einmal.
    assert ">✗</span>" not in r.text


def test_ein_fehlversuch_bleibt_ein_fehlversuch(pg_session):
    """Gutfall der Anzeige: die drei Ausgaenge duerfen nicht zusammenfallen."""
    inv = _seed(pg_session)
    jar, val = _mustang_patches()
    with patch.object(datev_email, "send_invoice",
                      side_effect=datev_email.EmailError("SMTP-Fehler: 550 blocked")), jar, val:
        r = _client(pg_session).post(f"/invoices/{inv.id}/datev-senden")

    assert r.status_code == 400
    pg_session.expire_all()
    zeilen = _logs(pg_session, inv.id)
    assert len(zeilen) == 1, "Aus einem Versuch wurden zwei Zeilen"
    assert zeilen[0].success is False
    assert "550 blocked" in zeilen[0].error

    seite = _client(pg_session).get(f"/invoices/{inv.id}")
    assert "AUSGANG UNBEKANNT" not in seite.text
    assert ">✗</span>" in seite.text
