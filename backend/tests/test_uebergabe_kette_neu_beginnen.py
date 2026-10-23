"""Wartungsskript: Uebergabekette eines Absenders in der Testinstanz neu beginnen (#214).

Nur Testinstanz, nur Eingaenge eines Absenders. Rechnungen und andere Daten bleiben.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.config import get_settings
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.uebergabe_eingang import UebergabeEingang
from app.services.uebergabe_eingang import DatenbankLage
from scripts.uebergabe_kette_neu_beginnen import main


ZEIT = datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)


@pytest.fixture
def als_testinstanz(monkeypatch):
    monkeypatch.setattr(get_settings(), "installation_mode", "testinstanz")


def _eingang(pg_session, absender: str, *, sha: str, beleg_id: str) -> UebergabeEingang:
    zeile = UebergabeEingang(
        beleg_id=beleg_id,
        beleg_sha256=sha,
        absender=absender,
        nutzlast_art="abrechnungsauftrag",
        erzeugt_am=ZEIT,
    )
    pg_session.add(zeile)
    pg_session.flush()
    return zeile


def _rechnung(pg_session, *, sha: str) -> Invoice:
    kunde = Customer(
        customer_number=f"K-{uuid4().hex[:8]}",
        name="Probe Autorin",
        address_line1="Weg 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
    )
    pg_session.add(kunde)
    pg_session.flush()
    inv = Invoice(
        invoice_number=f"RE-PROBE-{uuid4().hex[:6]}",
        customer_id=kunde.id,
        issue_date=date(2026, 9, 1),
        due_date=date(2026, 9, 15),
        currency="EUR",
        net_total=Decimal("100.00"),
        tax_total=Decimal("7.00"),
        gross_total=Decimal("107.00"),
        status="draft",
        uebergabe_beleg_sha256=sha,
        uebergabe_beleg_id="b" * 36,
    )
    pg_session.add(inv)
    pg_session.flush()
    return inv


def test_entfernt_nur_eingaenge_des_genannten_absenders(
    pg_session, als_testinstanz, capsys,
):
    _eingang(pg_session, "absender-a", sha="1" * 64, beleg_id="a" * 36)
    _eingang(pg_session, "absender-a", sha="2" * 64, beleg_id="b" * 36)
    _eingang(pg_session, "absender-b", sha="3" * 64, beleg_id="c" * 36)
    rechnung = _rechnung(pg_session, sha="1" * 64)
    pg_session.commit()
    rechnung_id = rechnung.id

    code = main(["absender-a"], db=pg_session)
    out = capsys.readouterr()

    assert code == 0
    assert "2" in out.out
    pg_session.expire_all()
    rest = pg_session.query(UebergabeEingang).all()
    assert len(rest) == 1
    assert rest[0].absender == "absender-b"
    assert DatenbankLage(pg_session).zuletzt_angenommen("absender-a") is None
    assert DatenbankLage(pg_session).zuletzt_angenommen("absender-b") is not None
    assert pg_session.get(Invoice, rechnung_id) is not None


def test_ohne_testinstanz_verweigert_und_laesst_eingaenge(
    pg_session, monkeypatch, capsys,
):
    monkeypatch.setattr(get_settings(), "installation_mode", "production")
    _eingang(pg_session, "absender-a", sha="1" * 64, beleg_id="a" * 36)
    pg_session.commit()
    vorher = pg_session.query(UebergabeEingang).count()

    def boom():
        raise AssertionError("SessionLocal darf vor der Pruefung nicht greifen")

    monkeypatch.setattr(
        "scripts.uebergabe_kette_neu_beginnen.SessionLocal", boom,
    )

    code = main(["absender-a"])
    err = capsys.readouterr().err

    assert code != 0
    assert "Testinstanz" in err
    assert pg_session.query(UebergabeEingang).count() == vorher


def test_null_eingaenge_eigene_meldung(pg_session, als_testinstanz, capsys):
    code = main(["absender-ohne-eingang"], db=pg_session)
    out = capsys.readouterr()

    assert code == 0
    text = out.out + out.err
    assert "Keine Eingänge" in text
    assert "absender-ohne-eingang" in text


def test_fehlender_absender_bricht_ab(als_testinstanz, capsys):
    code = main([])
    err = capsys.readouterr().err

    assert code != 0
    assert err.strip()
