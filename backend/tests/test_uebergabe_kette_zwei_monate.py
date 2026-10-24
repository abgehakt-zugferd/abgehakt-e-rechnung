"""Szenario: Uebergabekette ueber zwei Monatslieferungen (#226).

Die Kette laeuft erst weiter, wenn ein angenommener Beleg per Knopf angelegt
und damit gemerkt wird (uebergabe_eingang.merken; DatenbankLage.zuletzt_angenommen).
Gleiche erzeugt_am-Zeitstempel sind erlaubt (uebergabe_befund: erzeugt_am < letzte_zeit).
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.models.invoice import Invoice
from app.models.uebergabe_eingang import UebergabeEingang
from tests.helpers.uebergabe import schluesselpaar
from tests.helpers.uebergabe_monatskette import (
    RICHTUNG,
    ablegen,
    anlegen,
    entwurf_merkmal,
    fehler_aus,
    plattform_kunde,
    rechnungs_beleg,
    schalter,
    sha_von,
)

M1_A = "markt:2026-09:kanal-a:teil-1"
M1_B = "markt:2026-09:kanal-a:teil-2"
M2_A = "markt:2026-10:kanal-a:teil-1"
M2_B = "markt:2026-10:kanal-a:teil-2"
# Nach gueltig_von des Probeschluessels; gleicher Stempel je Monat erlaubt.
T_M1 = "2026-09-03T11:00:00Z"
T_M2 = "2026-10-03T11:00:00Z"


@pytest.fixture
def belegordner(tmp_path):
    ordner = tmp_path / "uebergaben"
    (ordner / RICHTUNG).mkdir(parents=True)
    signieren, schluessel = schluesselpaar(tmp_path / "schluessel")
    einstellungen = get_settings()
    vorher = (einstellungen.uebergaben_ordner, einstellungen.schluessel_pfad)
    einstellungen.uebergaben_ordner = str(ordner)
    einstellungen.schluessel_pfad = str(schluessel)
    yield ordner / RICHTUNG, signieren
    einstellungen.uebergaben_ordner, einstellungen.schluessel_pfad = vorher


def _anlegen_ok(client, name: str):
    antwort = anlegen(client, name)
    assert antwort.status_code == 303
    assert fehler_aus(antwort) == ""
    return antwort


def test_zwei_monatslieferungen_verkettet_behalten_monat1_entwuerfe(
    client, pg_session, belegordner,
):
    """Monat 1 und Monat 2 regulaer: vier Entwuerfe; Monat-1-Merkmale unveraendert."""
    ordner, signieren = belegordner
    plattform_kunde(pg_session)
    schalter(pg_session)

    m1a = rechnungs_beleg(
        signieren, auftragsschluessel=M1_A, erzeugt_am=T_M1, netto="100.00",
    )
    ablegen(ordner, "m1a.json", m1a)
    assert "ANGENOMMEN" in client.get("/uebergaben").text
    _anlegen_ok(client, "m1a.json")

    m1b = rechnungs_beleg(
        signieren,
        auftragsschluessel=M1_B,
        erzeugt_am=T_M1,
        vorgaenger_hash=sha_von(m1a),
        netto="200.00",
    )
    ablegen(ordner, "m1b.json", m1b)
    assert "ANGENOMMEN" in client.get("/uebergaben").text
    _anlegen_ok(client, "m1b.json")

    assert pg_session.query(Invoice).count() == 2
    assert pg_session.query(UebergabeEingang).count() == 2
    stand_m1 = {
        inv.auftragsschluessel: entwurf_merkmal(inv)
        for inv in pg_session.query(Invoice).all()
    }
    assert set(stand_m1) == {M1_A, M1_B}

    m2a = rechnungs_beleg(
        signieren,
        auftragsschluessel=M2_A,
        erzeugt_am=T_M2,
        vorgaenger_hash=sha_von(m1b),
        netto="110.00",
    )
    ablegen(ordner, "m2a.json", m2a)
    assert "KETTE_SPRINGT" not in client.get("/uebergaben").text
    _anlegen_ok(client, "m2a.json")

    m2b = rechnungs_beleg(
        signieren,
        auftragsschluessel=M2_B,
        erzeugt_am=T_M2,
        vorgaenger_hash=sha_von(m2a),
        netto="220.00",
    )
    ablegen(ordner, "m2b.json", m2b)
    _anlegen_ok(client, "m2b.json")

    pg_session.expire_all()
    assert pg_session.query(Invoice).count() == 4
    assert pg_session.query(UebergabeEingang).count() == 4
    for schluessel, merkmal in stand_m1.items():
        inv = (
            pg_session.query(Invoice)
            .filter(Invoice.auftragsschluessel == schluessel)
            .one()
        )
        assert entwurf_merkmal(inv) == merkmal


def test_wiederholter_auftragsschluessel_ist_schon_gerechnet(
    client, pg_session, belegordner,
):
    """Auftragsschluessel aus Monat 1 kommt in Monat 2 korrekt verkettet wieder."""
    ordner, signieren = belegordner
    plattform_kunde(pg_session)
    schalter(pg_session)

    m1a = rechnungs_beleg(
        signieren, auftragsschluessel=M1_A, erzeugt_am=T_M1, netto="100.00",
    )
    ablegen(ordner, "m1a.json", m1a)
    _anlegen_ok(client, "m1a.json")
    m1b = rechnungs_beleg(
        signieren,
        auftragsschluessel=M1_B,
        erzeugt_am=T_M1,
        vorgaenger_hash=sha_von(m1a),
        netto="200.00",
    )
    ablegen(ordner, "m1b.json", m1b)
    _anlegen_ok(client, "m1b.json")

    wiederholung = rechnungs_beleg(
        signieren,
        auftragsschluessel=M1_A,
        erzeugt_am=T_M2,
        vorgaenger_hash=sha_von(m1b),
        netto="100.00",
    )
    ablegen(ordner, "wieder.json", wiederholung)
    antwort = anlegen(client, "wieder.json")

    assert antwort.status_code == 303
    assert fehler_aus(antwort) == "AUFTRAG_SCHON_GERECHNET"
    assert pg_session.query(Invoice).count() == 2
    assert pg_session.query(UebergabeEingang).count() == 2
