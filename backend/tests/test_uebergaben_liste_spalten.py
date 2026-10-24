"""Belegliste unter Uebergaben: Spalten je Nutzlast, Aktion nicht abgeschnitten (#207).

Oeffentliche Grenze: GET /uebergaben (TestClient), gerendertes HTML.
Die Zuordnung der Werte liegt im Dienst; das Template zeigt nur neutrale Spalten.
"""

import re
import uuid

import pytest

from app.config import get_settings
from app.models.app_config import AppConfig
from app.models.customer import Customer
from tests.helpers.uebergabe import (
    PARTNER_A,
    anlagen_ablegen,
    aufstellungsauftrag,
    beleg,
    rechnungsauftrag,
    schluesselpaar,
)

RICHTUNG = "tantiemen-app-nach-abgehakt"


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


def _schalter(pg_session, aktiv=True):
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if cfg is None:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
    cfg.beleg_integration_aktiv = aktiv
    pg_session.commit()


def _kunde_gutschrift(pg_session, kennung=PARTNER_A):
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Autorin A",
        address_line1="Beispielstrasse 1", zip_code="10115", city="Berlin",
        country="DE", gutschriftempfaenger=True, ust_status="regelbesteuert",
        tax_number="12/345/67890",
    )
    kunde.id = uuid.UUID(kennung)
    pg_session.add(kunde)
    pg_session.commit()
    return kunde


def _kunde_plattform(pg_session, kennung=PARTNER_A):
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Plattform Beispiel GmbH",
        address_line1="Platz 1", zip_code="1015", city="Amsterdam", country="NL",
        auftrag_steuer="AE", vat_id="NL123456789B01",
    )
    kunde.id = uuid.UUID(str(kennung))
    pg_session.add(kunde)
    pg_session.commit()
    return kunde


def _kunde_aufstellung(pg_session, kennung=PARTNER_A):
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Beispiel Services LLC",
        address_line1="Way 1", zip_code="10001", city="New York", country="US",
    )
    kunde.id = uuid.UUID(str(kennung))
    pg_session.add(kunde)
    pg_session.commit()
    return kunde


def _kopfzeile(html: str) -> str:
    treffer = re.search(r"<thead>(.*?)</thead>", html, re.S)
    assert treffer, "Tabelle ohne thead"
    return treffer.group(1)


def test_neutrale_spaltenkoepfe_statt_abrechnungsfelder(client, pg_session, belegordner):
    ordner, signieren = belegordner
    _kunde_gutschrift(pg_session)
    _schalter(pg_session)
    (ordner / "auftrag.json").write_bytes(beleg(signieren))

    kopf = _kopfzeile(client.get("/uebergaben").text)

    assert "KUNDE / PROJEKT" in kopf
    assert "ZEITRAUM" in kopf
    assert "SUMME" in kopf
    assert "QUARTAL" not in kopf
    assert "GUTSCHRIFTEN" not in kopf
    assert re.search(r">\s*PROJEKT\s*<", kopf) is None


def test_abrechnungsauftrag_fuellt_neutrale_spalten(client, pg_session, belegordner):
    ordner, signieren = belegordner
    _kunde_gutschrift(pg_session)
    _schalter(pg_session)
    (ordner / "auftrag.json").write_bytes(beleg(signieren))

    text = client.get("/uebergaben").text

    assert "Probeverlag" in text
    assert "01.04.2026\u201330.06.2026" in text
    assert "174,33" in text


def test_rechnungsauftrag_zeigt_kunde_monat_und_summe(client, pg_session, belegordner):
    ordner, signieren = belegordner
    _kunde_plattform(pg_session)
    _schalter(pg_session)
    (ordner / "rechnung.json").write_bytes(
        beleg(signieren, rechnungsauftrag(), nutzlast_art="rechnungsauftrag")
    )

    text = client.get("/uebergaben").text

    assert "Plattform Beispiel GmbH" in text
    assert "2026-02" in text or "02/2026" in text
    assert "171,34" in text
    assert re.search(r">\s*0\s*<", text) is None
    assert "0,00" not in text


def test_aufstellungsauftrag_zeigt_kunde_monat_summe_mit_waehrung(
    client, pg_session, belegordner,
):
    ordner, signieren = belegordner
    _kunde_aufstellung(pg_session)
    _schalter(pg_session)
    nutzlast = aufstellungsauftrag()
    (ordner / "aufstellung.json").write_bytes(
        beleg(signieren, nutzlast, nutzlast_art="aufstellungsauftrag")
    )
    anlagen_ablegen(ordner, nutzlast)

    text = client.get("/uebergaben").text

    assert "Beispiel Services LLC" in text
    assert "2026-02" in text or "02/2026" in text
    assert "4,84" in text
    assert "USD" in text


def test_unlesbarer_beleg_zeigt_gedankenstrich_in_neutralen_spalten(
    client, pg_session, belegordner,
):
    ordner, signieren = belegordner
    _schalter(pg_session)
    (ordner / "muell.json").write_bytes(b"{ dies ist kein beleg")

    text = client.get("/uebergaben").text
    zeile = re.search(
        r"muell\.json.*?</tr>", text, re.S,
    )
    assert zeile, "Zeile fuer muell.json fehlt"
    assert zeile.group(0).count("–") >= 3


def test_aktionsspalte_schneidet_den_knopf_nicht_ab(client, pg_session, belegordner):
    """Der volle Knopftext steht im HTML; die Aktion-Zelle und die Tabelle
    duerfen ihn nicht durch Quetschen abschneiden (nowrap an der Zelle,
    Tabelle darf ueber die Kartenbreite wachsen)."""
    ordner, signieren = belegordner
    _kunde_plattform(pg_session)
    _schalter(pg_session)
    (ordner / "rechnung.json").write_bytes(
        beleg(signieren, rechnungsauftrag(), nutzlast_art="rechnungsauftrag")
    )

    text = client.get("/uebergaben").text

    assert "ALS RECHNUNG ANLEGEN" in text
    assert "ALS RECH…" not in text
    aktion = re.search(
        r"<td([^>]*)>\s*<form[^>]*>\s*<button[^>]*>ALS RECHNUNG ANLEGEN",
        text, re.S,
    )
    assert aktion, "Aktion-Zelle zum Knopf nicht gefunden"
    assert "white-space:nowrap" in aktion.group(1)
    tabelle = re.search(
        r'<div class="card"[^>]*>\s*<table([^>]*)>', text, re.S,
    )
    assert tabelle
    stil = tabelle.group(1)
    assert "width:100%" not in stil or "max-content" in stil
