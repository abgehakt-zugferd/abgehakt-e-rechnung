"""#278 Teil 2: Zahlungsdatum korrigieren, protokolliert, einziger Durchlass im Guard.

GoBD verlangt nicht, dass eine Angabe nie geaendert wird, sondern dass der
urspruengliche Inhalt feststellbar bleibt (Paragraf 146 Abs. 4 AO).
"""
from datetime import date

import pytest

from app.models.invoice import AuditLog, Invoice
from app.services import aenderungsprotokoll
from app.services.invoice_guard import InvoiceStateError
from tests.test_bezahlt_am_vor_rechnung import _beleg


def _bezahlt(pg_session, **over) -> Invoice:
    over.setdefault("bezahlt_am", date(2026, 6, 25))
    return _beleg(pg_session, auftrag=False, status="paid", **over)


def _korrigieren(client, inv, datum, grund):
    return client.post(f"/invoices/{inv.id}/zahlungsdatum-korrigieren",
                       data={"bezahlt_am": datum, "grund": grund})


def test_korrektur_aendert_datum_und_laesst_den_rest_unberuehrt(client, pg_session):
    inv = _bezahlt(pg_session, pdf_filename="x.pdf")
    r = _korrigieren(client, inv, "2026-06-24", "Tippfehler beim Erfassen")
    assert r.status_code == 303
    pg_session.expire_all()
    row = pg_session.get(Invoice, inv.id)
    assert row.bezahlt_am == date(2026, 6, 24)
    assert row.status == "paid"
    assert row.pdf_filename == "x.pdf"


def test_korrektur_steht_im_protokoll_mit_altem_neuem_wert_grund_zeitpunkt(client, pg_session):
    inv = _bezahlt(pg_session)
    _korrigieren(client, inv, "2026-06-24", "Tippfehler beim Erfassen")
    zeile = (
        pg_session.query(AuditLog)
        .filter(AuditLog.record_id == str(inv.id), AuditLog.action == "update")
        .order_by(AuditLog.changed_at.desc()).first()
    )
    assert zeile.old_values["bezahlt_am"] == "2026-06-25"
    assert zeile.new_values["bezahlt_am"] == "2026-06-24"
    assert zeile.new_values["bezahlt_am_grund"] == "Tippfehler beim Erfassen"
    assert zeile.changed_at is not None
    sicht = aenderungsprotokoll.protokoll_fuer(pg_session, inv.id)[0]
    assert sicht.vorgang == "Zahlungsdatum korrigiert"
    assert "25.06.2026" in sicht.detail and "24.06.2026" in sicht.detail
    assert "Tippfehler beim Erfassen" in sicht.detail


@pytest.mark.parametrize("grund", ["", "   "])
def test_korrektur_ohne_grund_wird_abgelehnt(client, pg_session, grund):
    inv = _bezahlt(pg_session)
    assert _korrigieren(client, inv, "2026-06-24", grund).status_code == 400
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).bezahlt_am == date(2026, 6, 25)


def test_korrektur_folgt_den_datumsregeln(client, pg_session):
    inv = _bezahlt(pg_session)
    assert _korrigieren(client, inv, "2026-06-05", "zu frueh").status_code == 400
    assert _korrigieren(client, inv, "2999-01-01", "Zukunft").status_code == 400
    assert _korrigieren(client, inv, "kein-datum", "unlesbar").status_code == 400
    auftrag = _beleg(pg_session, auftrag=True, status="paid",
                     zeitraum_von=date(2026, 6, 1), bezahlt_am=date(2026, 6, 25))
    assert _korrigieren(client, auftrag, "2026-06-05", "Geldeingang").status_code == 303


def test_korrektur_nur_an_bezahlten_belegen(client, pg_session):
    inv = _beleg(pg_session, auftrag=False, status="issued")
    assert _korrigieren(client, inv, "2026-06-24", "Grund").status_code == 400
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).bezahlt_am is None


def test_direkte_aenderung_am_modell_bleibt_gesperrt(pg_session):
    inv = _bezahlt(pg_session)
    inv.bezahlt_am = date(2026, 6, 24)
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


def test_durchlass_schliesst_sich_nach_der_korrektur(client, pg_session):
    inv = _bezahlt(pg_session)
    _korrigieren(client, inv, "2026-06-24", "Tippfehler")
    row = pg_session.get(Invoice, inv.id)
    row.bezahlt_am = date(2026, 6, 23)
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


def test_formular_nur_bei_bezahlten_belegen_mit_regelgerechtem_min(client, pg_session):
    bezahlt = _bezahlt(pg_session)
    offen = _beleg(pg_session, auftrag=False, status="issued")
    seite = client.get(f"/invoices/{bezahlt.id}").text
    assert f"/invoices/{bezahlt.id}/zahlungsdatum-korrigieren" in seite
    assert 'name="grund"' in seite and 'min="2026-06-20"' in seite
    assert "zahlungsdatum-korrigieren" not in client.get(f"/invoices/{offen.id}").text
