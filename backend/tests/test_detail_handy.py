"""Rechnungsansicht in Handybreite: Positionen als Blöcke, Kopfleiste und Raster ohne Überlauf.

Verhalten: die gerenderte Seite trägt je Zahlzelle eine Beschriftung. Die reinen
CSS-Regeln sind ein Architektur-Lint (der Text ist die Regel); Kommentare zählen nicht.
"""
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from tests.helpers.ersatzrechnung import beleg as _beleg, kunde as _kunde

CSS = Path(__file__).resolve().parent.parent / "app" / "static" / "css"


@pytest.fixture
def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


class _Zellen(HTMLParser):
    def __init__(self):
        super().__init__()
        self.zellen = []  # (data-label, klassen)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "td" and "pos-zahl" in (a.get("class") or "").split():
            self.zellen.append((a.get("data-label"), a.get("class")))


def _css(name):
    text = (CSS / name).read_text(encoding="utf-8")
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _schmal_bloecke(name):
    """Inhalte aller @media (max-width: ...)-Blöcke einer Datei, ohne Kommentare."""
    text = _css(name)
    out = []
    for m in re.finditer(r"@media[^{]*max-width:\s*(\d+)px[^{]*\{", text):
        tiefe, i = 1, m.end()
        while tiefe and i < len(text):
            tiefe += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        out.append((int(m.group(1)), text[m.end():i - 1]))
    return out


def test_jede_zahlzelle_der_position_traegt_eine_beschriftung(pg_session, client):
    beleg = _beleg(pg_session, _kunde(pg_session))
    p = _Zellen()
    p.feed(client.get(f"/invoices/{beleg.id}").text)
    labels = [l for l, _ in p.zellen if l]
    assert labels == ["Pos.", "Menge", "Preis", "MwSt.", "Netto"]


def test_lesbarkeit_stellt_positionen_schmal_als_bloecke_dar():
    bloecke = [(b, t) for b, t in _schmal_bloecke("lesbarkeit.css") if 600 <= b <= 700]
    assert bloecke, "kein @media (max-width: 6xx px) in lesbarkeit.css"
    text = " ".join(t for _, t in bloecke)
    assert "attr(data-label)" in text
    assert re.search(r"td\.pos-zahl[^{]*::before", text)
    assert re.search(r"tr\.table-row[^{]*\{[^}]*display:\s*(block|flex)", text)
    assert re.search(r"thead[^{]*\{[^}]*display:\s*none", text)


def test_terminal_kopfleiste_laeuft_schmal_nicht_ueber():
    text = " ".join(t for b, t in _schmal_bloecke("terminal.css") if b <= 520)
    assert re.search(r"\[data-kopf-marke\]::after[^{]*\{[^}]*display:\s*none", text)


def test_terminal_beschriftungen_stossen_schmal_nicht_aneinander():
    text = " ".join(t for b, t in _schmal_bloecke("terminal.css") if b <= 520)
    assert re.search(r"\.label[^{]*\{[^}]*letter-spacing:\s*[01](\.\d+)?px", text)


def test_rechnungsdaten_raster_ist_schmal_einspaltig(pg_session, client):
    beleg = _beleg(pg_session, _kunde(pg_session))
    html = client.get(f"/invoices/{beleg.id}").text
    i = html.index("Rechnungsdatum")
    raster = html[html.rindex('class="grid', 0, i):i]
    assert "grid-cols-1" in raster and "sm:grid-cols-2" in raster


def test_schmal_brechen_ueberschriften_um_und_der_gesamtbetrag_bleibt_einzeilig():
    text = " ".join(t for b, t in _schmal_bloecke("lesbarkeit.css") if 600 <= b <= 700)
    assert re.search(r"\.card h2[^{]*\{[^}]*overflow-wrap:\s*anywhere", text)
    assert re.search(r"\.summe__gesamt[^{]*\{[^}]*white-space:\s*nowrap", text)
