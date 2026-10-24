"""Szenario-Folgen: Monat 2 zu frueh, gemischte Nutzlastarten in einer Kette (#226).

Gemeinsame Kette je Absender (nicht je nutzlast_art): DatenbankLage.zuletzt_angenommen
filtert nur nach absender (uebergabe_eingang.py); beleg_beurteilen knuepft daran
ohne Artfilter (uebergabe_befund.py, Block nach Signaturpruefung).
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
    abrechnungs_beleg,
    anlegen,
    fehler_aus,
    plattform_kunde,
    rechnungs_beleg,
    schalter,
    sha_von,
)

M1_A = "markt:2026-09:kanal-b:teil-1"
M1_B = "markt:2026-09:kanal-b:teil-2"
M2_A = "markt:2026-10:kanal-b:teil-1"
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


def test_monat2_zu_frueh_ist_kette_springt_bis_monat1_fertig(
    client, pg_session, belegordner,
):
    """Monat 1 nur teilweise angelegt: Monat-2-Beleg auf m1b -> KETTE_SPRINGT,
    nach Anlegen von m1b wird Monat 2 angenommen (heutiges Verhalten)."""
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
    # m1b liegt und ist annehmbar, wird aber bewusst noch nicht angelegt.

    m2a = rechnungs_beleg(
        signieren,
        auftragsschluessel=M2_A,
        erzeugt_am=T_M2,
        vorgaenger_hash=sha_von(m1b),
        netto="110.00",
    )
    ablegen(ordner, "m2a.json", m2a)
    liste = client.get("/uebergaben").text
    assert "KETTE_SPRINGT" in liste

    antwort = anlegen(client, "m2a.json")
    assert antwort.status_code == 303
    assert fehler_aus(antwort) == "KETTE_SPRINGT"
    assert pg_session.query(Invoice).count() == 1
    assert pg_session.query(UebergabeEingang).count() == 1

    _anlegen_ok(client, "m1b.json")
    assert "ANGENOMMEN" in client.get("/uebergaben").text
    _anlegen_ok(client, "m2a.json")

    pg_session.expire_all()
    assert pg_session.query(Invoice).count() == 3
    assert pg_session.query(UebergabeEingang).count() == 3


def test_rechnungsauftrag_dann_abrechnungsauftrag_in_einer_kette(
    client, pg_session, belegordner,
):
    """Gemischte Arten in derselben Absender-Kette: angenommen und anlegbar."""
    ordner, signieren = belegordner
    plattform_kunde(pg_session)
    schalter(pg_session)

    erster = rechnungs_beleg(
        signieren,
        auftragsschluessel=M1_A,
        erzeugt_am=T_M1,
        netto="100.00",
    )
    ablegen(ordner, "rechnung.json", erster)
    _anlegen_ok(client, "rechnung.json")

    zweiter = abrechnungs_beleg(
        signieren,
        erzeugt_am=T_M2,
        vorgaenger_hash=sha_von(erster),
    )
    ablegen(ordner, "abrechnung.json", zweiter)
    assert "ANGENOMMEN" in client.get("/uebergaben").text
    assert "KETTE_SPRINGT" not in client.get("/uebergaben").text
    _anlegen_ok(client, "abrechnung.json")

    pg_session.expire_all()
    assert pg_session.query(Invoice).count() == 2
    assert pg_session.query(UebergabeEingang).count() == 2
    arten = {z.nutzlast_art for z in pg_session.query(UebergabeEingang).all()}
    assert arten == {"rechnungsauftrag", "abrechnungsauftrag"}
