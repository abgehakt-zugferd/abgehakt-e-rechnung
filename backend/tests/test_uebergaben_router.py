"""Die Belegansicht (abgehakt#22, Punkte 3 und 4).

Das Lesen ist TRANSIENT: nach dem Ansehen ist die Datenbank unveraendert, und
in den Belegordner wird nie geschrieben (§ 12: der Ordner ist Archiv nach
§ 147 AO, und was dort liegt, hat ein Absender hingelegt).

Erst der Knopf "Als Rechnung anlegen" schreibt fest.
"""

import base64
import hashlib
import html
import json
import logging
import uuid
from urllib.parse import parse_qs, urlparse

import pytest

from app.config import get_settings
from app.models.app_config import AppConfig
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.uebergabe_eingang import UebergabeEingang
from app.services.uebergabebeleg import kanonisch
from tests.helpers.uebergabe import (
    PARTNER_A,
    auftrag,
    beleg,
    gutschrift,
    schluesselpaar,
)

RICHTUNG = "tantiemen-app-nach-abgehakt"


@pytest.fixture
def belegordner(tmp_path):
    """Ein Wegwerf-Belegordner samt Schluessel, an den die Anwendung zeigt."""
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


def _kunde(pg_session, kennung=PARTNER_A, name="Autorin A", nummer=None,
           gutschriftempfaenger=True):
    kunde = Customer(
        customer_number=nummer or f"K-{uuid.uuid4().hex[:8]}", name=name,
        address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE",
        gutschriftempfaenger=gutschriftempfaenger,
        ust_status="regelbesteuert",
        tax_number="12/345/67890",
    )
    kunde.id = uuid.UUID(kennung)
    pg_session.add(kunde)
    pg_session.commit()
    return kunde


def _abzug(ordner):
    """Name, Bytes und Zeitstempel jeder Datei - der Beweis, dass nichts angefasst wurde."""
    return {
        p.name: (p.read_bytes(), p.stat().st_mtime_ns)
        for p in sorted(ordner.iterdir())
    }


def test_ohne_schalter_gibt_es_die_seite_nicht(client, pg_session, belegordner):
    _schalter(pg_session, False)

    assert client.get("/uebergaben").status_code == 404


def test_die_tabelle_zeigt_die_belege_des_ordners(client, pg_session, belegordner):
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    (ordner / "auftrag-2026-Q2.json").write_bytes(beleg(signieren))

    text = client.get("/uebergaben").text

    assert "auftrag-2026-Q2.json" in text
    assert "2026-Q2" in text
    assert "Probeverlag" in text
    assert "174,33" in text or "174.33" in text


def test_nach_dem_ansehen_ist_die_datenbank_unveraendert(client, pg_session, belegordner):
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    (ordner / "auftrag.json").write_bytes(beleg(signieren))

    client.get("/uebergaben")

    assert pg_session.query(Invoice).count() == 0
    assert pg_session.query(UebergabeEingang).count() == 0


def test_in_den_belegordner_wird_nie_geschrieben(client, pg_session, belegordner):
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    (ordner / "auftrag.json").write_bytes(beleg(signieren))
    vorher = _abzug(ordner)

    client.get("/uebergaben")
    client.post("/uebergaben/auftrag.json/rechnung-anlegen")

    assert _abzug(ordner) == vorher


def test_ein_abgelehnter_beleg_zeigt_seinen_befund(client, pg_session, belegordner):
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    verdreht = json.loads(beleg(signieren))
    roh = bytearray(base64.b64decode(verdreht["signatur"]["wert"]))
    roh[0] ^= 0x01
    verdreht["signatur"]["wert"] = base64.b64encode(bytes(roh)).decode("ascii")
    (ordner / "kaputt.json").write_bytes(kanonisch(verdreht))

    text = client.get("/uebergaben").text

    assert "SIGNATUR_UNGUELTIG" in text


def test_ein_beleg_ohne_kunden_zeigt_partner_id_unbekannt(client, pg_session, belegordner):
    ordner, signieren = belegordner
    _schalter(pg_session)
    (ordner / "auftrag.json").write_bytes(beleg(signieren))

    text = client.get("/uebergaben").text

    assert "PARTNER_ID_UNBEKANNT" in text


def test_der_knopf_legt_den_entwurf_an_und_fuehrt_zur_vorschau(client, pg_session, belegordner):
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    (ordner / "auftrag.json").write_bytes(beleg(signieren))

    antwort = client.post("/uebergaben/auftrag.json/rechnung-anlegen")

    assert antwort.status_code == 303
    entwurf = pg_session.query(Invoice).one()
    assert entwurf.status == "draft"
    assert antwort.headers["location"] == f"/invoices/{entwurf.id}/vorschau"
    assert pg_session.query(UebergabeEingang).count() == 1


def test_ein_abgelehnter_beleg_legt_nichts_an(client, pg_session, belegordner):
    ordner, signieren = belegordner
    _schalter(pg_session)
    (ordner / "auftrag.json").write_bytes(beleg(signieren))   # kein Kunde im Stamm

    antwort = client.post("/uebergaben/auftrag.json/rechnung-anlegen")

    assert antwort.status_code == 303
    assert pg_session.query(Invoice).count() == 0
    assert pg_session.query(UebergabeEingang).count() == 0


def test_zwei_beteiligte_ohne_beide_kunden_legen_keine_einzige_rechnung_an(
    client, pg_session, belegordner,
):
    """Nie teilweise (§ 11)."""
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    nutzlast = auftrag(gutschriften=[
        gutschrift(),
        gutschrift(partner_id="00000000-dead-4000-8000-000000000000", netto="265.77"),
    ])
    (ordner / "zwei.json").write_bytes(beleg(signieren, nutzlast))

    client.post("/uebergaben/zwei.json/rechnung-anlegen")

    assert pg_session.query(Invoice).count() == 0


def test_derselbe_beleg_ein_zweites_mal_wirkt_nicht_noch_einmal(client, pg_session, belegordner):
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    (ordner / "auftrag.json").write_bytes(beleg(signieren))

    client.post("/uebergaben/auftrag.json/rechnung-anlegen")
    client.post("/uebergaben/auftrag.json/rechnung-anlegen")

    assert pg_session.query(Invoice).count() == 1
    assert pg_session.query(UebergabeEingang).count() == 1


def test_ein_verarbeiteter_beleg_traegt_keinen_knopf_mehr(client, pg_session, belegordner):
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    (ordner / "auftrag.json").write_bytes(beleg(signieren))
    client.post("/uebergaben/auftrag.json/rechnung-anlegen")

    text = client.get("/uebergaben").text

    assert "rechnung-anlegen" not in text
    assert "BEREITS VERARBEITET" in text.upper()


@pytest.mark.parametrize("name", ["../../etc/passwd", "..%2Fauftrag.json", "unbekannt.json"])
def test_ein_dateiname_ausserhalb_des_ordners_fuehrt_nirgendwohin(
    client, pg_session, belegordner, name,
):
    _schalter(pg_session)

    antwort = client.post(f"/uebergaben/{name}/rechnung-anlegen")

    assert antwort.status_code == 404
    assert pg_session.query(Invoice).count() == 0


def test_ohne_eingerichteten_ordner_bleibt_die_seite_ruhig(client, pg_session, belegordner):
    _schalter(pg_session)
    get_settings().uebergaben_ordner = ""

    antwort = client.get("/uebergaben")

    assert antwort.status_code == 200
    assert "kein Belegordner" in antwort.text


def test_eine_kaputte_datei_legt_die_belegliste_nicht_lahm(client, pg_session, belegordner):
    """Eine kaputte Datei neben einer guten: Die Liste antwortet 200, zeigt
    den guten Beleg und fuer die kaputte den Befund - nicht HTTP 500 fuer
    die ganze Liste (abgehakt#164). Die Bytes der kaputten Datei werden
    direkt geschrieben, signieren liess sie sich ohnehin nicht."""
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    (ordner / "auftrag.json").write_bytes(beleg(signieren))
    kaputt = json.loads(beleg(signieren))
    kaputt["nutzlast"]["bemessung"]["erloes_netto"] = 797.30   # Gleitkommazahl
    (ordner / "kaputt.json").write_bytes(json.dumps(kaputt).encode("utf-8"))

    antwort = client.get("/uebergaben")

    assert antwort.status_code == 200
    assert "Probeverlag" in antwort.text
    assert "WERT_UNBRAUCHBAR" in antwort.text


def test_eine_unbekannte_kaputtheit_kostet_nur_die_eine_zeile(
    client, pg_session, belegordner, monkeypatch, caplog,
):
    """Sicherheitsnetz des Routers: Jede unerwartete Ausnahme der Beurteilung
    wird je Datei als BELEG_UNLESBAR gezeigt und geloggt - die Liste bleibt
    200. Das ersetzt nicht die gezielten Befunde des Lesers."""
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    (ordner / "auftrag.json").write_bytes(beleg(signieren))

    def unbekannt(roh, lage, **kwargs):
        raise RuntimeError("eine noch unbekannte Kaputtheit")

    monkeypatch.setattr("app.routers.uebergaben.beleg_beurteilen", unbekannt)
    with caplog.at_level(logging.ERROR):
        antwort = client.get("/uebergaben")

    assert antwort.status_code == 200
    assert "BELEG_UNLESBAR" in antwort.text
    assert any("auftrag.json" in eintrag.message for eintrag in caplog.records)


# --- Die eigene Aufbewahrungskopie (§ 12: unveraendert, auch beim Empfaenger) ---

def test_der_knopf_bewahrt_den_beleg_auf_und_die_kopie_ueberlebt_die_quelle(
    client, pg_session, belegordner,
):
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    roh = beleg(signieren)
    (ordner / "auftrag.json").write_bytes(roh)
    sha = hashlib.sha256(roh).hexdigest()

    client.post("/uebergaben/auftrag.json/rechnung-anlegen")

    kopie = get_settings().storage_path / "uebergaben" / RICHTUNG / f"{sha}.json"
    assert kopie.read_bytes() == roh
    assert hashlib.sha256(kopie.read_bytes()).hexdigest() == sha
    assert pg_session.query(UebergabeEingang).one().beleg_sha256 == sha

    # Der Absender kann seinen Ordner leeren: die eigene Kopie bleibt (§ 12).
    (ordner / "auftrag.json").unlink()
    assert kopie.read_bytes() == roh


def test_scheitert_die_kopie_wird_der_beleg_nicht_angenommen(
    client, pg_session, belegordner,
):
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    (ordner / "auftrag.json").write_bytes(beleg(signieren))
    zielordner = get_settings().storage_path / "uebergaben" / RICHTUNG
    zielordner.mkdir(parents=True, exist_ok=True)
    zielordner.chmod(0o500)

    try:
        antwort = client.post("/uebergaben/auftrag.json/rechnung-anlegen")
    finally:
        zielordner.chmod(0o700)

    assert antwort.status_code == 303
    meldung = parse_qs(urlparse(antwort.headers["location"]).query)["fehler"][0]
    assert "Aufbewahrungskopie" in meldung
    assert pg_session.query(Invoice).count() == 0
    assert pg_session.query(UebergabeEingang).count() == 0


def test_der_fehlertext_steht_url_kodiert_in_der_weiterleitung(
    client, pg_session, belegordner,
):
    """Ein Fehlertext in einer Redirect-URL ist ein Query-Parameter: Leerzeichen,
    & und Umlaute sind dort Sonderzeichen. Unkodiert schnitt das & die Query,
    und die Zielseite zeigte den Text abgeschnitten. Der Weg dorthin ist echt:
    Ein Kunde ohne Gutschriftempfaenger-Eigenschaft laesst die Wirkung am
    Knopf scheitern, und seine Nummer geraet in die Meldung."""
    ordner, signieren = belegordner
    _schalter(pg_session)
    _kunde(pg_session, nummer="K-Ü & 1", gutschriftempfaenger=False)
    (ordner / "auftrag.json").write_bytes(beleg(signieren))

    antwort = client.post("/uebergaben/auftrag.json/rechnung-anlegen")

    assert antwort.status_code == 303
    ort = antwort.headers["location"]
    assert "K-Ü" not in ort
    assert "&" not in ort
    meldung = parse_qs(urlparse(ort).query)["fehler"][0]
    assert meldung == "Kunde K-Ü & 1 ist kein Gutschriftempfaenger"

    seite = client.get(ort)
    assert seite.status_code == 200
    assert "Kunde K-Ü & 1 ist kein Gutschriftempfaenger" in html.unescape(seite.text)


def test_der_zweite_knopfdruck_laesst_die_kopie_unveraendert(
    client, pg_session, belegordner,
):
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    roh = beleg(signieren)
    (ordner / "auftrag.json").write_bytes(roh)
    sha = hashlib.sha256(roh).hexdigest()

    client.post("/uebergaben/auftrag.json/rechnung-anlegen")
    kopie = get_settings().storage_path / "uebergaben" / RICHTUNG / f"{sha}.json"
    # Der Speicher ist Sitzungseigentum: gezaehlt wird der Zuwachs, nicht der Bestand.
    vorher = {p.name for p in kopie.parent.iterdir()}

    client.post("/uebergaben/auftrag.json/rechnung-anlegen")

    assert {p.name for p in kopie.parent.iterdir()} == vorher
    assert kopie.read_bytes() == roh
