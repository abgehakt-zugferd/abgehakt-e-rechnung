"""Der Knopf ALS AUFSTELLUNG ANLEGEN (§ 8b, Bauschritt 7b): vom Beleg im
Uebergabeordner zum Entwurf der Abrechnungsaufstellung.

Wie beim rechnungsauftrag (§ 8a) gilt: Der Knopf beurteilt selbst noch
einmal, bewahrt den Beleg auf (§ 12) und wirkt alles oder nichts. Der
Unterschied ist das Ziel - kein /invoices, denn die Aufstellung ist KEINE
Rechnung; bis Bauschritt 7g ihre Seite bringt, kehrt der Knopf mit der
Nummer des Entwurfs zur Liste zurueck.
"""

import hashlib
import uuid
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import get_settings
from app.models.aufstellung import Aufstellung, AufstellungAnlage
from app.models.app_config import AppConfig
from app.models.customer import Customer
from app.models.uebergabe_eingang import UebergabeEingang
from app.services.uebergabe_eingang import DatenbankLage, RICHTUNG
from app.zeit import heute
from tests.factories_aufstellung import orm_aufstellung
from tests.helpers.uebergabe import (
    ANLAGE_ABRECHNUNGSBERICHT,
    ANLAGE_ZAHLUNGSBERICHT,
    PARTNER_A,
    anlagen_ablegen,
    aufstellungsauftrag,
    beleg,
    schluesselpaar,
)

SCHLUESSEL = "plattform:2026-02:kanal-b:x1"


@pytest.fixture
def belegordner(tmp_path):
    """Ein Wegwerf-Belegordner samt Schluessel, an den die Anwendung zeigt.
    Derselbe Aufbau wie in test_uebergaben_router (belegordner), hier als
    eigene Fixture: Die Dateien dieses Tests bleiben bei diesen Tests."""
    ordner = tmp_path / "uebergaben"
    (ordner / RICHTUNG).mkdir(parents=True)
    signieren, schluessel = schluesselpaar(tmp_path / "schluessel")

    einstellungen = get_settings()
    vorher = (einstellungen.uebergaben_ordner, einstellungen.schluessel_pfad)
    einstellungen.uebergaben_ordner = str(ordner)
    einstellungen.schluessel_pfad = str(schluessel)
    yield ordner / RICHTUNG, signieren
    einstellungen.uebergaben_ordner, einstellungen.schluessel_pfad = vorher


def _schalter(pg_session, aktiv=True):
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if cfg is None:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
    cfg.beleg_integration_aktiv = aktiv
    pg_session.commit()


def _kunde(pg_session, kennung=PARTNER_A):
    """Ganz ohne Steuervorgabe: Die Aufstellung ist keine Rechnung, am Kunden
    ist nichts zu pruefen - haette § 8a hier recht, muesste der Knopf
    scheitern."""
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Beispiel Services LLC",
        address_line1="Way 1", zip_code="10001", city="New York", country="US",
    )
    kunde.id = uuid.UUID(str(kennung))
    pg_session.add(kunde)
    pg_session.commit()
    return kunde


def _beleg_ablegen(ordner, signieren, name="aufstellung.json", **aenderungen):
    """Signierter aufstellungsauftrag im Ordner, seine Anlagen daneben (§ 8b:
    der Absender schreibt sie VOR den Beleg)."""
    nutzlast = aufstellungsauftrag(**aenderungen)
    roh = beleg(signieren, nutzlast, nutzlast_art="aufstellungsauftrag")
    (ordner / name).write_bytes(roh)
    anlagen_ablegen(ordner, nutzlast)
    return roh, nutzlast


def _meldung(antwort) -> str:
    return parse_qs(urlparse(antwort.headers["location"]).query)


def test_der_knopf_heisst_aufstellung_anlegen(client, pg_session, belegordner):
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    _beleg_ablegen(ordner, signieren)

    text = client.get("/uebergaben").text

    assert "ANGENOMMEN" in text
    assert "aufstellung-anlegen" in text
    assert "ALS AUFSTELLUNG ANLEGEN" in text
    # Der rechnungsauftrag behaelt seinen eigenen Knopf (getrennte Wirkungen).
    assert "rechnung-anlegen" not in text


def test_der_knopf_legt_den_entwurf_an_und_meldet_die_nummer(
    client, pg_session, belegordner,
):
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    _beleg_ablegen(ordner, signieren)

    antwort = client.post("/uebergaben/aufstellung.json/aufstellung-anlegen")

    assert antwort.status_code == 303
    entwurf = pg_session.query(Aufstellung).one()
    assert entwurf.status == "draft"
    assert entwurf.auftragsschluessel == SCHLUESSEL
    assert entwurf.auftragsschluessel_offen == SCHLUESSEL
    assert sorted(a.quelle for a in entwurf.anlagen) == [
        "abrechnungsbericht", "zahlungsbericht",
    ]
    assert pg_session.query(UebergabeEingang).count() == 1
    # Die Detailseite zeigt die Nummer aus der Annahme unmittelbar an.
    assert antwort.headers["location"] == f"/aufstellungen/{entwurf.id}"
    seite = client.get(antwort.headers["location"])
    assert entwurf.nummer in seite.text



def test_die_anlagen_liegen_danach_im_eigenen_speicher(client, pg_session, belegordner):
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    _, nutzlast = _beleg_ablegen(ordner, signieren)

    client.post("/uebergaben/aufstellung.json/aufstellung-anlegen")

    ordner_im_speicher = (
        get_settings().storage_path / "uebergaben" / RICHTUNG / "anlagen"
    )
    for eintrag in nutzlast["anlagen"]:
        kopie = ordner_im_speicher / f"{eintrag['sha256']}.xlsx"
        assert kopie.read_bytes() == _bestand()[eintrag["sha256"]]
    assert pg_session.query(AufstellungAnlage).count() == 2


def _bestand():
    return {
        hashlib.sha256(b).hexdigest(): b
        for b in (ANLAGE_ABRECHNUNGSBERICHT, ANLAGE_ZAHLUNGSBERICHT)
    }


def test_der_knopf_lehnt_andere_belegarten_ab(client, pg_session, belegordner):
    """Die Adresse gehoert zur Art: Ein abrechnungsauftrag an dieser Stelle
    waere eine veraltete Seite, nicht ein Wirken - es entsteht nichts."""
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    (ordner / "auftrag.json").write_bytes(
        beleg(signieren, nutzlast_art="abrechnungsauftrag")
    )

    antwort = client.post("/uebergaben/auftrag.json/aufstellung-anlegen")

    assert antwort.status_code == 303
    assert "keine Abrechnungsaufstellung" in _meldung(antwort)["fehler"][0]
    assert pg_session.query(Aufstellung).count() == 0


def test_ohne_anlagen_im_ordner_legt_der_knopf_nichts_an(
    client, pg_session, belegordner,
):
    """Der Leser haelt den Beleg gegen die Dateien (§ 8b): Fehlt die Anlage,
    ist der Befund ANLAGE_FEHLT - am Knopf entsteht nichts, und der Beleg
    darf erneut vorgelegt werden, sobald sie liegt."""
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    nutzlast = aufstellungsauftrag()
    (ordner / "aufstellung.json").write_bytes(
        beleg(signieren, nutzlast, nutzlast_art="aufstellungsauftrag")
    )

    antwort = client.post("/uebergaben/aufstellung.json/aufstellung-anlegen")

    assert antwort.status_code == 303
    assert _meldung(antwort)["fehler"][0] == "ANLAGE_FEHLT"
    assert pg_session.query(Aufstellung).count() == 0
    assert pg_session.query(UebergabeEingang).count() == 0


def test_zum_schluessel_gerechnet_gibt_es_keine_zweite_aufstellung(
    client, pg_session, belegordner,
):
    """Festlegung 12: Der Leser lehnt den zweiten Auftrag zum selben
    Schluessel ab; genannt wird, was der Absender wiedererkennt."""
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    roh, _ = _beleg_ablegen(ordner, signieren)
    client.post("/uebergaben/aufstellung.json/aufstellung-anlegen")

    # Ein neuer Beleg zum selben Schluessel: eigene Kennung, eigener Hash,
    # und die Kette haengt am zuletzt ANGENOMMENEN Beleg (§ 5).
    (ordner / "zweiter.json").write_bytes(
        beleg(
            signieren, aufstellungsauftrag(),
            nutzlast_art="aufstellungsauftrag",
            beleg_id="11111111-2222-4333-8444-555555555577",
            vorgaenger_hash=hashlib.sha256(roh).hexdigest(),
        )
    )
    antwort = client.post("/uebergaben/zweiter.json/aufstellung-anlegen")

    assert _meldung(antwort)["fehler"][0] == "AUFTRAG_SCHON_GERECHNET"
    assert pg_session.query(Aufstellung).count() == 1


def test_wettlauf_auf_dem_index_wird_zur_meldung_nicht_zu_500(
    client, pg_session, belegordner, monkeypatch,
):
    """Festlegung 19: Der Leser fragt die Lage ohne Sperre, zwei gleichzeitige
    Annahmen sehen beide 'frei'. Der partielle Unique-Index schlaegt beim
    Commit zu - derselbe Befund wie beim Leser, kein HTTP 500."""
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    pg_session.add(orm_aufstellung(schluessel=SCHLUESSEL))
    pg_session.commit()
    _beleg_ablegen(ordner, signieren)

    fragen = []

    def luegt_bei_der_ersten_frage(self, schluessel):
        fragen.append(schluessel)
        return None

    monkeypatch.setattr(
        DatenbankLage, "dokument_zu_auftragsschluessel", luegt_bei_der_ersten_frage,
    )

    antwort = client.post("/uebergaben/aufstellung.json/aufstellung-anlegen")

    # Genau die Vorabfrage des Lesers ist die Luege (ein Aufruf); die Meldung
    # des Fehlerwegs fragt die eine Stelle fuer die Sperre, die nicht luegt.
    assert fragen == [SCHLUESSEL]
    assert antwort.status_code == 303
    meldung = _meldung(antwort)["fehler"][0]
    assert "AUFTRAG_SCHON_GERECHNET" in meldung
    assert "Entwurf" in meldung
    assert pg_session.query(Aufstellung).count() == 1
    assert pg_session.query(UebergabeEingang).count() == 0
