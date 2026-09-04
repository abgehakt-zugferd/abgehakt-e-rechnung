"""Das Verarbeitungsgedaechtnis (abgehakt#22, § 11).

Gemerkt wird NUR, was angenommen wurde. Ein abgelehnter Beleg wird nicht
gemerkt und darf erneut vorgelegt werden: ein mangels abgelegtem Schluessel
abgelehnter Beleg muss durchgehen, sobald der Schluessel liegt. Wer
"verarbeitet" weiter fasst, friert die erste Ablehnung ein und macht einen
behebbaren Fehler unbehebbar.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.customer import Customer
from app.models.uebergabe_eingang import UebergabeEingang
from app.services.uebergabe_befund import Belegurteil, Feststellung
from app.services.uebergabe_eingang import DatenbankLage, merken

ABSENDER = "tantiemen-app"
ZEIT = datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)


def _urteil(kennung="a" * 36, sha="1" * 64, zeit=ZEIT, angenommen=True):
    return Belegurteil(
        beleg_sha256=sha, beleg_id=kennung, angenommen=angenommen,
        absender=ABSENDER, nutzlast_art="abrechnungsauftrag", erzeugt_am=zeit,
    )


def _kunde(pg_session, kennung=None, geloescht=False):
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Autorin A",
        address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE",
        deleted_at=datetime.now(timezone.utc) if geloescht else None,
    )
    if kennung:
        kunde.id = kennung
    pg_session.add(kunde)
    pg_session.flush()
    return kunde


def test_ein_angenommener_beleg_wird_gemerkt(pg_session):
    merken(pg_session, _urteil(), dateiname="auftrag-2026-Q2.json")
    pg_session.flush()

    zeile = pg_session.query(UebergabeEingang).one()
    assert zeile.beleg_id == "a" * 36
    assert zeile.beleg_sha256 == "1" * 64
    assert zeile.absender == ABSENDER
    assert zeile.dateiname == "auftrag-2026-Q2.json"
    assert zeile.erzeugt_am == ZEIT


def test_ein_abgelehnter_beleg_wird_nicht_gemerkt(pg_session):
    urteil = Belegurteil(
        beleg_sha256="2" * 64, beleg_id="b" * 36, angenommen=False,
        feststellungen=(Feststellung("SIGNATUR_UNGUELTIG", "$.signatur.wert"),),
        absender=ABSENDER, nutzlast_art="abrechnungsauftrag", erzeugt_am=ZEIT,
    )

    with pytest.raises(ValueError):
        merken(pg_session, urteil, dateiname="kaputt.json")

    assert pg_session.query(UebergabeEingang).count() == 0


def test_derselbe_beleg_zweimal_merken_legt_keine_zweite_zeile_an(pg_session):
    merken(pg_session, _urteil(), dateiname="a.json")
    pg_session.flush()
    merken(pg_session, _urteil(), dateiname="a.json")
    pg_session.flush()

    assert pg_session.query(UebergabeEingang).count() == 1


def test_die_lage_findet_die_kennung_wieder(pg_session):
    merken(pg_session, _urteil(), dateiname="a.json")
    pg_session.flush()

    lage = DatenbankLage(pg_session)
    assert lage.sha_zu_beleg_id("a" * 36) == "1" * 64
    assert lage.sha_zu_beleg_id("c" * 36) is None


def test_die_lage_nennt_den_zuletzt_angenommenen(pg_session):
    merken(pg_session, _urteil(kennung="a" * 36, sha="1" * 64), dateiname="a.json")
    pg_session.flush()
    merken(
        pg_session,
        _urteil(kennung="b" * 36, sha="2" * 64, zeit=ZEIT + timedelta(hours=1)),
        dateiname="b.json",
    )
    pg_session.flush()

    hash_, zeit = DatenbankLage(pg_session).zuletzt_angenommen(ABSENDER)
    assert hash_ == "2" * 64
    assert zeit == ZEIT + timedelta(hours=1)


def test_ohne_vorgeschichte_kennt_die_lage_keinen_vorgaenger(pg_session):
    assert DatenbankLage(pg_session).zuletzt_angenommen(ABSENDER) is None


def test_die_lage_kennt_nur_den_eigenen_absender(pg_session):
    merken(pg_session, _urteil(), dateiname="a.json")
    pg_session.flush()

    assert DatenbankLage(pg_session).zuletzt_angenommen("feiyr-konto") is None


def test_partner_bekannt_ist_der_kundenstamm(pg_session):
    kunde = _kunde(pg_session)

    lage = DatenbankLage(pg_session)
    assert lage.partner_bekannt(str(kunde.id))
    assert not lage.partner_bekannt(str(uuid.uuid4()))


def test_ein_geloeschter_kunde_ist_kein_beteiligter(pg_session):
    kunde = _kunde(pg_session, geloescht=True)

    assert not DatenbankLage(pg_session).partner_bekannt(str(kunde.id))


def test_eine_partner_id_die_keine_uuid_ist(pg_session):
    """Kein Absturz, kein Anlegen: sie ist schlicht unbekannt."""
    assert not DatenbankLage(pg_session).partner_bekannt("nicht-mal-eine-uuid")
