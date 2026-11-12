"""Seitenleiste (Aufstellungen) und Belegtabelle (#nav-belege-tabelle).

Oeffentliche Grenze: GET /uebergaben (TestClient), gerendertes HTML. Der Menuepunkt
steht nur bei aktivem Beleg-Schalter in base.html, also genuegt diese Seite.
"""

import re

from tests.test_uebergaben_liste_spalten import (  # noqa: F401 (Fixture)
    _kunde_gutschrift,
    _kopfzeile,
    _schalter,
    belegordner,
)
from tests.helpers.uebergabe import beleg


def _seite(client, pg_session, belegordner):
    ordner, signieren = belegordner
    _kunde_gutschrift(pg_session)
    _schalter(pg_session)
    (ordner / "auftrag.json").write_bytes(beleg(signieren))
    return client.get("/uebergaben").text


def _nav_link(html: str, ziel: str) -> str:
    treffer = re.search(
        r'<a href="%s" class="nav-link.*?</a>' % re.escape(ziel), html, re.S,
    )
    assert treffer, f"Menuepunkt {ziel} fehlt"
    return treffer.group(0)


def test_aufstellungen_hat_icon_und_schliesst_seitenleiste_auf_dem_handy(
    client, pg_session, belegordner,
):
    text = _seite(client, pg_session, belegordner)

    link = _nav_link(text, "/aufstellungen")
    assert "<svg" in link
    assert '@click="sidebarOpen = window.innerWidth >= 1024"' in link
    # deutlich verschieden vom BELEGE-Icon
    assert re.search(r"<svg.*?</svg>", link, re.S).group(0) != re.search(
        r"<svg.*?</svg>", _nav_link(text, "/uebergaben"), re.S,
    ).group(0)


def test_belegtabelle_hat_keine_dateispalte_mehr(client, pg_session, belegordner):
    kopf = _kopfzeile(_seite(client, pg_session, belegordner))

    assert "DATEI" not in kopf
    for spalte in ("ERZEUGT", "KUNDE / PROJEKT", "ZEITRAUM", "SUMME", "BEFUND", "AKTION"):
        assert spalte in kopf


def test_dateiname_steht_gedimmt_unter_dem_kunden(client, pg_session, belegordner):
    text = _seite(client, pg_session, belegordner)

    zeile = re.search(r"<tbody>(.*?)</tr>", text, re.S).group(1)
    zellen = re.findall(r"<td[^>]*>(.*?)</td>", zeile, re.S)
    kunde = zellen[1]  # ERZEUGT, KUNDE / PROJEKT, ...
    assert "Probeverlag" in kunde
    assert "auftrag.json" in kunde
    assert kunde.index("Probeverlag") < kunde.index("auftrag.json")
    assert "var(--text-dim)" in kunde
    assert "overflow-wrap:anywhere" in kunde


def test_tabelle_wird_nicht_breiter_als_die_karte(client, pg_session, belegordner):
    text = _seite(client, pg_session, belegordner)

    tabelle = re.search(r'<div class="card"[^>]*>\s*<table([^>]*)>', text, re.S)
    assert tabelle
    assert "max-content" not in tabelle.group(1)
    assert "width:100%" in tabelle.group(1)


def test_nur_summe_und_aktion_sind_unumbrechbar(client, pg_session, belegordner):
    """Damit BEFUND und AKTION bei schmaler Karte ohne Scrollen bleiben, geben
    ERZEUGT und ZEITRAUM nach; SUMME und der Knopf behalten ihre Breite."""
    text = _seite(client, pg_session, belegordner)

    zeile = re.search(r"<tbody>(.*?)</tr>", text, re.S).group(1)
    zellen = re.findall(r"<td([^>]*)>", zeile)
    erzeugt, _kunde, zeitraum, summe, _befund, aktion = zellen
    assert "nowrap" not in erzeugt
    assert "nowrap" not in zeitraum
    assert "nowrap" in summe
    assert "nowrap" in aktion
    assert "max-width:1100px" not in text.split("BELEGE</h1>")[0]


def test_befundzelle_bricht_lange_woerter_um(client, pg_session, belegordner):
    """Lange Befundcodes und JSON-Pfade duerfen die Spalte nicht aufspreizen."""
    text = _seite(client, pg_session, belegordner)

    zeile = re.search(r"<tbody>(.*?)</tr>", text, re.S).group(1)
    befund = re.findall(r"<td([^>]*)>", zeile)[4]
    assert "overflow-wrap:anywhere" in befund


def test_befundcode_bricht_nur_nach_unterstrichen_um(client, pg_session, belegordner):
    """Ohne bekannten Partner steht ein langer Befundcode in der Zelle; er soll
    an den Unterstrichen umbrechen, nicht mitten im Wort."""
    ordner, signieren = belegordner
    _schalter(pg_session)
    (ordner / "auftrag.json").write_bytes(beleg(signieren))

    text = client.get("/uebergaben").text

    assert re.search(r"[A-Z]+_<wbr>[A-Z]+", text), "Befundcode ohne Umbruchstelle"
    assert "<wbr>" in re.search(r"<tbody>(.*?)</tbody>", text, re.S).group(1)
