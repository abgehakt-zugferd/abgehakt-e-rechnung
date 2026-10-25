"""Belegliste: KETTE_SPRINGT als „wartet auf Vorgänger“, wenn der Vorgänger
im Ordner annehmbar und noch nicht angelegt ist (#233).

Oeffentliche Grenze: GET /uebergaben (gerendertes HTML). Der Leser-Befund
bleibt KETTE_SPRINGT (POST-Fehler); nur die Listenanzeige wird neutral.
"""

from __future__ import annotations

import re

import pytest

from app.config import get_settings
from tests.helpers.uebergabe import schluesselpaar
from tests.helpers.uebergabe_monatskette import (
    RICHTUNG,
    ablegen,
    anlegen,
    fehler_aus,
    plattform_kunde,
    rechnungs_beleg,
    schalter,
    sha_von,
)

T = "2026-09-03T11:00:00Z"
S1 = "markt:2026-09:warte:teil-1"
S2 = "markt:2026-09:warte:teil-2"
S3 = "markt:2026-09:warte:teil-3"


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


def _zeilen_html(seite: str) -> list[str]:
    """tbody-Zeilen in Listenreihenfolge (eine <tr> je Beleg)."""
    tbody = re.search(r"<tbody>(.*?)</tbody>", seite, re.S)
    assert tbody, "Belegtabelle ohne tbody"
    return re.findall(r"<tr\b.*?</tr>", tbody.group(1), re.S)


def _dateiname_in_zeile(zeile: str) -> str:
    m = re.search(
        r"font-family:'Share Tech Mono'[^>]*>\s*([^<]+?\.json)\s*<",
        zeile,
    )
    assert m, f"kein Dateiname in Zeile: {zeile[:120]}"
    return m.group(1).strip()


def test_folgebeleg_zeigt_wartet_auf_vorgaenger_neutral(
    client, pg_session, belegordner,
):
    """Vorgaenger im Ordner angenommen, noch nicht angelegt: neutrale Anzeige."""
    ordner, signieren = belegordner
    plattform_kunde(pg_session)
    schalter(pg_session)

    erster = rechnungs_beleg(
        signieren, auftragsschluessel=S1, erzeugt_am=T, netto="100.00",
    )
    ablegen(ordner, "erster.json", erster)
    zweiter = rechnungs_beleg(
        signieren,
        auftragsschluessel=S2,
        erzeugt_am=T,
        vorgaenger_hash=sha_von(erster),
        netto="200.00",
    )
    ablegen(ordner, "zweiter.json", zweiter)

    seite = client.get("/uebergaben").text

    assert "wartet auf Vorgänger erster.json" in seite
    assert "KETTE_SPRINGT" not in seite
    assert 'color:var(--pink);">wartet auf Vorgänger' not in seite
    assert 'color:var(--green);">wartet auf Vorgänger' not in seite
    assert 'action="/uebergaben/erster.json/rechnung-anlegen"' in seite
    assert 'action="/uebergaben/zweiter.json/rechnung-anlegen"' not in seite

    antwort = anlegen(client, "zweiter.json")
    assert antwort.status_code == 303
    assert fehler_aus(antwort) == "KETTE_SPRINGT"


def test_echter_sprung_bleibt_kette_springt_rot(
    client, pg_session, belegordner,
):
    """Genannter Vorgaenger fehlt im Ordner: KETTE_SPRINGT bleibt rot."""
    ordner, signieren = belegordner
    plattform_kunde(pg_session)
    schalter(pg_session)

    allein = rechnungs_beleg(
        signieren,
        auftragsschluessel=S1,
        erzeugt_am=T,
        vorgaenger_hash="ab" * 32,
        netto="100.00",
    )
    ablegen(ordner, "sprung.json", allein)

    seite = client.get("/uebergaben").text

    assert "wartet auf Vorgänger" not in seite
    assert "KETTE_SPRINGT" in seite
    assert 'color:var(--pink);">KETTE_SPRINGT</span>' in seite


def test_mehrstufig_beide_warten_auf_vorgaenger(
    client, pg_session, belegordner,
):
    """Beleg 3 wartet auf 2, 2 auf 1: beide neutral „wartet“, Knopf nur bei 1."""
    ordner, signieren = belegordner
    plattform_kunde(pg_session)
    schalter(pg_session)

    b1 = rechnungs_beleg(
        signieren, auftragsschluessel=S1, erzeugt_am=T, netto="100.00",
    )
    ablegen(ordner, "eins.json", b1)
    b2 = rechnungs_beleg(
        signieren,
        auftragsschluessel=S2,
        erzeugt_am=T,
        vorgaenger_hash=sha_von(b1),
        netto="200.00",
    )
    ablegen(ordner, "zwei.json", b2)
    b3 = rechnungs_beleg(
        signieren,
        auftragsschluessel=S3,
        erzeugt_am=T,
        vorgaenger_hash=sha_von(b2),
        netto="300.00",
    )
    ablegen(ordner, "drei.json", b3)

    seite = client.get("/uebergaben").text

    assert "wartet auf Vorgänger eins.json" in seite
    assert "wartet auf Vorgänger zwei.json" in seite
    assert "KETTE_SPRINGT" not in seite
    assert 'action="/uebergaben/eins.json/rechnung-anlegen"' in seite
    assert 'action="/uebergaben/zwei.json/rechnung-anlegen"' not in seite
    assert 'action="/uebergaben/drei.json/rechnung-anlegen"' not in seite


def test_liste_folgt_kettenreihenfolge_nicht_dateiname(
    client, pg_session, belegordner,
):
    """Alphabetisch waere a, m, z; die Hashes verlangen z -> m -> a."""
    ordner, signieren = belegordner
    plattform_kunde(pg_session)
    schalter(pg_session)

    z = rechnungs_beleg(
        signieren, auftragsschluessel=S1, erzeugt_am=T, netto="100.00",
    )
    ablegen(ordner, "z.json", z)
    m = rechnungs_beleg(
        signieren,
        auftragsschluessel=S2,
        erzeugt_am=T,
        vorgaenger_hash=sha_von(z),
        netto="200.00",
    )
    ablegen(ordner, "m.json", m)
    a = rechnungs_beleg(
        signieren,
        auftragsschluessel=S3,
        erzeugt_am=T,
        vorgaenger_hash=sha_von(m),
        netto="300.00",
    )
    ablegen(ordner, "a.json", a)

    namen = [_dateiname_in_zeile(z) for z in _zeilen_html(client.get("/uebergaben").text)]

    assert namen == ["z.json", "m.json", "a.json"]
