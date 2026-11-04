"""Drittes wählbares Oberflächen-Theme `terminal` (Palette Pastell dunkel).

Alle Seiten erben von `base.html`, deshalb genügt ein Token-Block unter
`html[data-theme="terminal"]` plus der Eintrag im Frühskript und im
Umschalter. Die Farbwerte selbst kommen aus einer einzigen Quelle:
`app/static/css/terminal.css` (Token `--t-*`), die `base.html` per lokalem
`<link>` einbindet. Dieser Test liest die Datei und die Vorlage als
Architektur-Lint und holt die ausgelieferte CSS-Datei und eine gerenderte
Seite über den TestClient.
"""
import re
from pathlib import Path

import pytest

VORLAGEN = Path("app/templates")
BASE_HTML = VORLAGEN / "base.html"
TERMINAL_CSS = Path("app/static/css/terminal.css")

# Erste Zeile der terminal.css — wörtlicher Quellvermerk der Kopie.
QUELLVERMERK = (
    "/* Quelle: Terminal-Werkzeug, Palette pastell_dunkel (Stand 2026-11-04). "
    "Wird durch die Kopie aus dem Werkzeug ersetzt. */"
)

# Verbindliche Abbildung Terminal-Block -> Token aus terminal.css.
ABBILDUNG = [
    ("--void", "--t-grund"),
    ("--panel", "--t-tafel"),
    ("--surface", "--t-flaeche"),
    ("--surface2", "--t-flaeche"),
    ("--border", "--t-linie"),
    ("--border-hi", "--t-rahmen"),
    ("--gold", "--t-akzent"),
    ("--gold-hi", "--t-akzent"),
    ("--green", "--t-ok"),
    ("--green-hi", "--t-ok"),
    ("--amber", "--t-warnung"),
    ("--red", "--t-fehler"),
    ("--pink", "--t-fehler"),
    ("--cyan", "--t-info"),
    ("--text", "--t-text"),
    ("--text-hi", "--t-text-hell"),
    ("--text-dim", "--t-text-matt"),
    ("--text-faint", "--t-text-matt"),
    ("--font-display", "--t-schrift-anzeige"),
    ("--font-label", "--t-schrift-anzeige"),
    ("--font-body", "--t-schrift-text"),
    ("--font-num", "--t-schrift-text"),
]


def _block(html: str, theme: str) -> str:
    """Inhalt des Token-Blocks `html[data-theme="<theme>"] { … }` (Klammern balanciert).

    Fehlt der Block, kommt ein leerer String zurück — die abhängigen Tests
    schlagen dann als fehlgeschlagen um, nicht als Fehler im Fixture.
    """
    marker = f'html[data-theme="{theme}"] {{'
    start = html.find(marker)
    if start == -1:
        return ""
    i = html.index("{", start)
    depth = 0
    for j in range(i, len(html)):
        if html[j] == "{":
            depth += 1
        elif html[j] == "}":
            depth -= 1
            if depth == 0:
                return html[i:j + 1]
    return ""


def _fruehskript(html: str) -> str:
    """Das erste `<script>` ohne src im head — setzt data-theme vor dem ersten Paint."""
    m = re.search(r"<script>(.*?)</script>", html, re.S)
    assert m, "Frühskript im head fehlt"
    return m.group(1)


def _deklarierte_variablen(block: str):
    return sorted(set(re.findall(r"(--[a-z0-9-]+)\s*:", block)))


_BASIS = BASE_HTML.read_text(encoding="utf-8")
ABGEHAKT_VARIABLEN = _deklarierte_variablen(_block(_BASIS, "abgehakt"))


@pytest.fixture(scope="module")
def basis_html():
    return BASE_HTML.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def terminal_block(basis_html):
    return _block(basis_html, "terminal")


def test_terminal_css_wird_ausgeliefert(client):
    """Durchstich: die CSS-Datei kommt vom eigenen Server, eine gerenderte
    Seite bindet sie lokal ein."""
    antwort = client.get("/static/css/terminal.css")
    assert antwort.status_code == 200, f"/static/css/terminal.css → {antwort.status_code}"
    assert "--t-grund:#14151c" in antwort.text
    seite = client.get("/dashboard")
    assert seite.status_code == 200
    assert 'href="/static/css/terminal.css"' in seite.text


def test_kopie_traegt_quellvermerk(client):
    antwort = client.get("/static/css/terminal.css")
    assert antwort.status_code == 200
    erste_zeile = antwort.text.splitlines()[0]
    assert erste_zeile == QUELLVERMERK
    assert TERMINAL_CSS.is_file()
    assert TERMINAL_CSS.read_text(encoding="utf-8").splitlines()[0] == QUELLVERMERK


def test_terminal_ist_erlaubter_wert_im_fruehskript(basis_html):
    skript = _fruehskript(basis_html)
    assert "!== 'terminal'" in skript, \
        "das Frühskript lässt 'terminal' nicht als data-theme zu"


def test_vorgabe_bleibt_abgehakt(basis_html):
    """Unbekannte Werte müssen auf 'abgehakt' zurückfallen — das bleibt so."""
    skript = _fruehskript(basis_html)
    assert "var t = 'abgehakt';" in skript
    assert "|| 'abgehakt'" in skript
    assert "{ t = 'abgehakt'; }" in skript


def test_umschalter_reihum(basis_html):
    """Reihenfolge abgehakt → pixel → terminal → abgehakt, Beschriftung 'Terminal'."""
    assert "var reihe = ['abgehakt', 'pixel', 'terminal'];" in basis_html
    assert "% reihe.length" in basis_html, "kein Umlauf: nach terminal käme nicht abgehakt"
    assert "abgehakt: 'Abgehakt'" in basis_html
    assert "pixel: 'Pixel'" in basis_html
    assert "terminal: 'Terminal'" in basis_html


@pytest.mark.parametrize("theme_var, token", ABBILDUNG)
def test_terminal_block_bildet_alle_farben_ab(terminal_block, theme_var, token):
    assert terminal_block, "kein html[data-theme=\"terminal\"]-Block in base.html"
    assert re.search(rf"{re.escape(theme_var)}\s*:\s*var\({re.escape(token)}\)", terminal_block), \
        f"{theme_var} wird nicht auf var({token}) abgebildet"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", terminal_block), \
        "Hex-Wert im Terminal-Block — nur var(--t-…) ist erlaubt"


@pytest.mark.parametrize("variable", ABGEHAKT_VARIABLEN)
def test_terminal_block_setzt_jede_variable_des_abgehakt_blocks(terminal_block, variable):
    assert terminal_block, "kein html[data-theme=\"terminal\"]-Block in base.html"
    assert re.search(rf"{re.escape(variable)}\s*:", terminal_block), \
        f"{variable} wird im Terminal-Block nicht gesetzt (erbt sonst nichts Sinnvolles)"


def test_terminal_keine_schrift_unter_15(terminal_block):
    """Jeder --fs-*-Wert im Terminal-Block muss mindestens 15px sein.

    var(--t-…)-Verweise werden gegen die eine Quelle (terminal.css) aufgelöst;
    rem/em werden mit 16px umgerechnet, andere Einheiten sind verboten.
    """
    css = TERMINAL_CSS.read_text(encoding="utf-8") if TERMINAL_CSS.is_file() else ""
    token_map = dict(re.findall(r"(--t-[a-z0-9-]+)\s*:\s*([^;]+);", css))
    werte = re.findall(r"--fs-[a-z0-9-]+\s*:\s*([^;]+);", terminal_block)
    assert werte, "keine --fs-*-Deklaration im Terminal-Block gefunden"
    for wert in werte:
        wert = wert.strip()
        m = re.fullmatch(r"var\((--t-[a-z0-9-]+)\)", wert)
        if m:
            assert m.group(1) in token_map, f"{m.group(1)} fehlt in terminal.css"
            wert = token_map[m.group(1)].strip()
        m = re.fullmatch(r"([\d.]+)px", wert)
        if m:
            px = float(m.group(1))
        else:
            m = re.fullmatch(r"([\d.]+)(rem|em)", wert)
            assert m, f"unbekannte Einheit in --fs-*: {wert!r}"
            px = float(m.group(1)) * 16
        assert px >= 15, f"--fs-Wert unter 15px: {wert!r} = {px}px"


def test_terminal_ersetzt_inline_schriften(basis_html):
    """Dieselben zwei Attributselektoren wie im Abgehakt-Theme: inline gesetzte
    Pixel-Schriften werden auf die Theme-Schriften abgebildet."""
    assert re.search(
        r'html\[data-theme="terminal"\] \[style\*="Press Start 2P"\]\s*\{[^}]*font-family:\s*var\(--font-label\) !important',
        basis_html), "Press-Start-2P-Inline-Schrift wird im Terminal-Theme nicht ersetzt"
    assert re.search(
        r'html\[data-theme="terminal"\] \[style\*="VT323"\]\s*\{[^}]*font-family:\s*var\(--font-body\) !important',
        basis_html), "VT323-Inline-Schrift wird im Terminal-Theme nicht ersetzt"


def test_terminal_neutralisiert_inline_schatten_und_laufweite(basis_html):
    assert re.search(
        r'html\[data-theme="terminal"\] \[style\*="text-shadow"\]\s*\{[^}]*text-shadow:\s*none !important',
        basis_html), "Inline-text-shadow wird im Terminal-Theme nicht neutralisiert"
    assert re.search(
        r'html\[data-theme="terminal"\] \[style\*="letter-spacing:2px"\],\s*'
        r'html\[data-theme="terminal"\] \[style\*="letter-spacing:3px"\]\s*\{[^}]*letter-spacing:[^;}]+ !important',
        basis_html), "Inline-letter-spacing 2px/3px wird im Terminal-Theme nicht neutralisiert"


def test_retro_regel_entfernt(basis_html):
    """Die tote Regel html[data-theme="retro"] .kpi__wert ist aus base.html raus."""
    assert 'data-theme="retro"' not in basis_html
