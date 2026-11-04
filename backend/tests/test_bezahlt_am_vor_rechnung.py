"""#278 Teil 1: Zahlung vor dem Rechnungsdatum bei Belegen aus einem Rechnungsauftrag.

Der Beleg entsteht nach dem Geldeingang. Das Zahlungsdatum darf deshalb vor dem
Rechnungsdatum liegen, aber nicht vor dem Leistungsbeginn und nicht in der Zukunft.
Alle anderen Belege behalten die Untergrenze Rechnungsdatum.
"""
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.customer import Customer
from app.models.invoice import Invoice
from app.zeit import heute

ISSUE = date(2026, 6, 20)


def _beleg(pg_session, *, auftrag: bool, zeitraum_von=None, leistung=None,
           status="issued", **over) -> Invoice:
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Probe Vorzahlung GmbH",
        address_line1="Probeweg 7", zip_code="80331", city="Muenchen", country="DE",
    )
    pg_session.add(c)
    pg_session.flush()
    kw = dict(
        invoice_number=f"RE-{uuid.uuid4().hex[:6]}", customer_id=c.id,
        issue_date=ISSUE, due_date=ISSUE, currency="EUR",
        net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"), status=status,
        service_period_start=zeitraum_von,
        service_period_end=ISSUE if zeitraum_von else None,
        delivery_date=leistung,
    )
    if auftrag:
        kw.update(auftragsschluessel=f"AS-{uuid.uuid4().hex[:8]}",
                  uebergabe_beleg_sha256="a" * 64)
    kw.update(over)
    inv = Invoice(**kw)
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _bezahlen(client, inv, datum):
    return client.post(f"/invoices/{inv.id}/status",
                       data={"new_status": "paid", "bezahlt_am": datum})


def test_auftragsbeleg_nimmt_zahlung_vor_rechnungsdatum_ab_leistungsbeginn(client, pg_session):
    inv = _beleg(pg_session, auftrag=True, zeitraum_von=date(2026, 6, 1))
    r = _bezahlen(client, inv, "2026-06-05")
    assert r.status_code == 303
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).bezahlt_am == date(2026, 6, 5)


def test_auftragsbeleg_lehnt_zahlung_vor_leistungsbeginn_ab(client, pg_session):
    inv = _beleg(pg_session, auftrag=True, zeitraum_von=date(2026, 6, 1))
    r = _bezahlen(client, inv, "2026-05-31")
    assert r.status_code == 400
    assert "Beginn der Leistung" in r.text
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).status == "issued"


def test_auftragsbeleg_ohne_zeitraum_nimmt_leistungsdatum(client, pg_session):
    inv = _beleg(pg_session, auftrag=True, leistung=date(2026, 6, 10))
    assert _bezahlen(client, inv, "2026-06-09").status_code == 400
    assert _bezahlen(client, inv, "2026-06-10").status_code == 303


def test_auftragsbeleg_ohne_zeitraum_und_leistungsdatum_bleibt_beim_rechnungsdatum(client, pg_session):
    inv = _beleg(pg_session, auftrag=True)
    assert _bezahlen(client, inv, "2026-06-19").status_code == 400


def test_auftragsbeleg_lehnt_zukunft_ab(client, pg_session):
    inv = _beleg(pg_session, auftrag=True, zeitraum_von=date(2026, 6, 1))
    zukunft = (heute() + timedelta(days=1)).isoformat()
    assert _bezahlen(client, inv, zukunft).status_code == 400


def test_normaler_beleg_lehnt_zahlung_vor_rechnungsdatum_weiter_ab(client, pg_session):
    inv = _beleg(pg_session, auftrag=False, zeitraum_von=date(2026, 6, 1))
    r = _bezahlen(client, inv, "2026-06-05")
    assert r.status_code == 400
    assert "Rechnungsdatum" in r.text


def test_guard_laesst_auftragsbeleg_vor_rechnungsdatum_zu_normalen_nicht(pg_session):
    ok = _beleg(pg_session, auftrag=True, zeitraum_von=date(2026, 6, 1))
    ok.status, ok.bezahlt_am = "paid", date(2026, 6, 5)
    pg_session.commit()
    assert ok.bezahlt_am == date(2026, 6, 5)
    nein = _beleg(pg_session, auftrag=False, zeitraum_von=date(2026, 6, 1))
    nein.status, nein.bezahlt_am = "paid", date(2026, 6, 5)
    with pytest.raises(Exception, match="Rechnungsdatum"):
        pg_session.commit()
    pg_session.rollback()


def test_formular_min_folgt_der_regel(client, pg_session):
    auftrag = _beleg(pg_session, auftrag=True, zeitraum_von=date(2026, 6, 1))
    normal = _beleg(pg_session, auftrag=False, zeitraum_von=date(2026, 6, 1))
    assert 'min="2026-06-01"' in client.get(f"/invoices/{auftrag.id}").text
    assert 'min="2026-06-20"' in client.get(f"/invoices/{normal.id}").text
