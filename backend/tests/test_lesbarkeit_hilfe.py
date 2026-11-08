"""Lesbarkeit: Hilfetexte klappen ein, Protokoll bricht um, Tabelle gibt der Beschreibung Platz.

Architektur-Lint: der Text der Vorlagen ist hier die Regel selbst (Klasse am
Absatz, ein Mechanismus in base.html, Terminal-Regeln mit Token). Das
Laufzeitverhalten (Kuerzung ab drei Zeilen) misst die Sichtpruefung per
Browser, nicht dieser Test.
"""
import re
from pathlib import Path

import pytest

VORLAGEN = Path("app/templates")
BASE = VORLAGEN / "base.html"
LESBARKEIT_CSS = Path("app/static/css/lesbarkeit.css")
HILFE_JS = Path("app/static/js/hilfe-1.0.0.js")
TERMINAL_CSS = Path("app/static/css/terminal.css")

ALT = re.compile(
    r"font-family:'VT323',monospace;\s*font-size:var\(--fs-(?:text|gross)\);\s*color:var\(--text-dim\)")

# Vorlagen, in denen JEDER gedaempfte Hilfeabsatz die Klasse tragen muss.
VOLLSTAENDIG = [
    "invoices/form.html",
    "customers/form.html",
    "invoices/detail_aktionen.html",
    "partials/schnittstellen_id.html",
    "partials/ust_id_vies_status.html",
]
# Dort sind kurze Untertitel und Kennzahl-Zeilen bewusst ausgenommen.
TEILWEISE = {"dashboard.html": 4, "settings/index.html": 8}


def _tags(text: str):
    return re.findall(r"<(?:p|div)\b[^>]*>", text, flags=re.S)


def _lies(rel: str) -> str:
    return (VORLAGEN / rel).read_text(encoding="utf-8")


@pytest.mark.parametrize("rel", VOLLSTAENDIG)
def test_gedaempfte_hilfen_tragen_die_klasse(rel):
    rest = [t for t in _tags(_lies(rel))
            if ALT.search(t) and "flex" not in t and "hilfe" not in t]
    assert rest == [], f"{rel}: gedaempfter Hilfetext ohne Klasse hilfe: {rest[:1]}"
    assert re.search(r'class="[^"]*\bhilfe\b', _lies(rel)), f"{rel}: keine Klasse hilfe"


@pytest.mark.parametrize("rel,mind", TEILWEISE.items())
def test_teilweise_vorlagen_tragen_die_klasse(rel, mind):
    n = len(re.findall(r'class="[^"]*\bhilfe\b', _lies(rel)))
    assert n >= mind, f"{rel}: nur {n} Hilfeabsaetze mit Klasse, erwartet >= {mind}"


def test_fehler_und_warnhinweise_nicht_eingeklappt():
    """Farbige Hinweise (amber/red) tragen nie die Klasse hilfe."""
    for rel in VOLLSTAENDIG + list(TEILWEISE):
        for t in _tags(_lies(rel)):
            if re.search(r'\bhilfe\b', t):
                assert "var(--amber)" not in t and "var(--red)" not in t, (rel, t)


def test_ein_mechanismus_ohne_js_fallback():
    base = BASE.read_text(encoding="utf-8")
    assert "/static/css/lesbarkeit.css" in base and "/static/js/hilfe-1.0.0.js" in base
    css = LESBARKEIT_CSS.read_text(encoding="utf-8")
    js = HILFE_JS.read_text(encoding="utf-8")
    assert re.search(r"\.hilfe\s*\{", css)
    # Kuerzung haengt an einer Klasse, die nur das Skript setzt
    m = re.search(r"\.hilfe--gekuerzt\s*\{([^}]*)\}", css)
    assert m and "-webkit-line-clamp: 2" in m.group(1), "Kuerzung auf zwei Zeilen fehlt"
    assert not re.search(r"\.hilfe\s*\{[^}]*line-clamp", css), "ohne JS wuerde gekuerzt"
    assert "hilfe--gekuerzt" in js and "'mehr'" in js and "'weniger'" in js
    assert "aria-expanded" in js
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", css), "Hex-Wert in lesbarkeit.css"


def test_terminal_hilfe_plex_15_matt(  ):
    css = TERMINAL_CSS.read_text(encoding="utf-8")
    m = re.search(r'html\[data-theme="terminal"\]\s*\.hilfe[^{]*\{([^}]*)\}', css)
    assert m, "keine Terminal-Regel fuer .hilfe"
    r = m.group(1)
    assert re.search(r"font-family:\s*var\(--t-schrift-text\) !important", r)
    assert re.search(r"font-size:\s*var\(--t-groesse-klein\) !important", r)
    assert re.search(r"color:\s*var\(--t-text-matt\) !important", r)
    assert re.search(r"line-height:\s*1\.45 !important", r)


def test_protokollzeile_laeuft_nicht_aus_der_karte():
    d = _lies("invoices/detail.html")
    block = d.split("ÄNDERUNGSPROTOKOLL", 1)[1].split("ZUGFeRD XML", 1)[0]
    assert 'class="protokoll"' in block and "protokoll__text" in block
    b = LESBARKEIT_CSS.read_text(encoding="utf-8")
    m = re.search(r"\.protokoll__text\s*\{([^}]*)\}", b)
    assert m and "min-width: 0" in m.group(1) and "overflow-wrap: anywhere" in m.group(1)
    css = TERMINAL_CSS.read_text(encoding="utf-8")
    t = re.search(r'html\[data-theme="terminal"\]\s*\.protokoll[^{]*\{([^}]*)\}', css)
    assert t and "var(--t-schrift-text)" in t.group(1) and "var(--t-groesse-klein)" in t.group(1)


def test_positionstabelle_gibt_beschreibung_den_rest():
    p = _lies("invoices/detail_positionen.html")
    assert "pos-beschreibung" in p
    b = LESBARKEIT_CSS.read_text(encoding="utf-8")
    m = re.search(r"\.pos-beschreibung\s*\{([^}]*)\}", b)
    assert m and "width: 100%" in m.group(1) and "overflow-wrap" in m.group(1)
    # Zahlenspalten bleiben einzeilig und rechtsbuendig
    assert p.count("white-space:nowrap") >= 4


def test_zahlenspalten_der_positionstabelle_sind_so_schmal_wie_ihr_inhalt():
    """Kopf- und Datenzellen der Zahlenspalten tragen `pos-zahl` (width:1%,
    nowrap), die Laufweite des Kopfes ist dort klein, auch im Terminal."""
    p = _lies("invoices/detail_positionen.html")
    kopf = re.findall(r"<th\b[^>]*>", p)
    assert len(kopf) == 6
    # POS., MENGE, PREIS, MWST., NETTO: alle ausser BESCHREIBUNG
    assert sum("pos-zahl" in t for t in kopf) == 5
    assert "pos-zahl" not in kopf[1], "Beschreibungskopf darf nicht schmal sein"
    zeile = p.split("{% for item in invoice.items %}", 1)[1].split("{% endfor %}", 1)[0]
    zellen = re.findall(r"<td\b[^>]*>", zeile)
    assert len(zellen) == 6 and sum("pos-zahl" in t for t in zellen) == 5
    css = LESBARKEIT_CSS.read_text(encoding="utf-8")
    m = re.search(r"\.pos-zahl\s*\{([^}]*)\}", css)
    assert m and "width: 1%" in m.group(1) and "white-space: nowrap" in m.group(1)
    t = TERMINAL_CSS.read_text(encoding="utf-8")
    r = re.search(r'html\[data-theme="terminal"\]\s*\.table-header\.pos-zahl[^{]*\{([^}]*)\}', t)
    assert r, "Terminal: Laufweite der Zahlenkoepfe nicht gesenkt"
    ls = re.search(r"letter-spacing:\s*([\d.]+)px !important", r.group(1))
    assert ls and float(ls.group(1)) <= 1, "Laufweite im Terminal zu gross"


def test_terminal_zahlenzellen_der_positionstabelle_in_kleingroesse():
    """Inline stehen die Preise in --fs-text (18px); im Terminal belegen zehn
    Zeichen Plex Mono dann ~110px je Spalte. Kleingroesse (15px) gibt der
    Beschreibung Platz."""
    t = TERMINAL_CSS.read_text(encoding="utf-8")
    r = re.search(r'html\[data-theme="terminal"\]\s*td\.pos-zahl[^{]*\{([^}]*)\}', t)
    assert r and re.search(r"font-size:\s*var\(--t-groesse-klein\) !important", r.group(1))
