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
    # --font-label auf Plex statt VT323: VT323 hat bei 15px eine optische
    # Größe von etwa 10px — Beschriftungen, Knöpfe, Navigation, Badges und
    # Tabellenköpfe sind darin unlesbar. VT323 bleibt h1-h3, der Wortmarke
    # und .kpi__wert vorbehalten (alles >= 24px).
    ("--font-label", "--t-schrift-text"),
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


@pytest.fixture(scope="module")
def terminal_css():
    return TERMINAL_CSS.read_text(encoding="utf-8") if TERMINAL_CSS.is_file() else ""


def _terminal_regel(css: str, selektor: str) -> str:
    """Body der ersten Regel, deren Selektor das Muster trifft (terminal-gescoped)."""
    m = re.search(r'html\[data-theme="terminal"\][^{]*' + selektor + r'[^{]*\{([^}]*)\}', css)
    return m.group(1) if m else ""


def test_terminal_kleine_display_schriften_werden_plex(terminal_css):
    """VT323 nur noch ab 24px: .text-lg (20px), .mitteilung__marke (12px) und die
    Wortmarke im mobilen Header (1.25rem = 20px) fallen auf IBM Plex Mono."""
    for selektor in [r'\.text-lg', r'\.mitteilung__marke', r'header \[style\*="var\(--font-display\)"\]']:
        regel = _terminal_regel(terminal_css, selektor)
        assert re.search(r'font-family:\s*var\(--t-schrift-text\) !important', regel), \
            f"{selektor} wird im Terminal-Theme nicht auf Plex umgestellt"


def test_terminal_kpi_wert_in_vt323(terminal_css):
    """Große Kennzahlen (.kpi__wert, 48px) sind VT323 — die eine Ausnahme neben
    h1-h3 und Wortmarke."""
    regel = _terminal_regel(terminal_css, r'\.kpi__wert')
    assert re.search(r'font-family:\s*var\(--t-schrift-anzeige\) !important', regel), \
        ".kpi__wert ist im Terminal-Theme nicht VT323"


def test_terminal_label_semi_fett(terminal_css):
    """Labels in IBM Plex Mono tragen Gewicht 600, damit sie bei 15px nicht zu dünn wirken."""
    regel = _terminal_regel(terminal_css, r'\.label')
    assert re.search(r'font-weight:\s*600 !important', regel), \
        "kein font-weight: 600 für .label im Terminal-Theme"


def test_terminal_color_scheme_dark(client, terminal_css):
    """Native Bedienelemente (Checkbox, Datum, Select, Scrollleiste) müssen dunkel rendern."""
    antwort = client.get("/static/css/terminal.css")
    assert antwort.status_code == 200
    block = _block(antwort.text, "terminal")
    assert block, 'kein html[data-theme="terminal"]-Block in der ausgelieferten terminal.css'
    assert re.search(r'color-scheme:\s*dark', block), "color-scheme: dark fehlt im Terminal-Block"
    assert re.search(r'color-scheme:\s*dark', terminal_css)


def test_terminal_tabellenzellen_17px_badges_ohne_umbruch(terminal_css):
    """Belegliste: Zellen in --t-groesse-tabelle (17px) mit kompakteren Abständen,
    Badges ohne Wortumbruch — sonst wird die Aktionsspalte bei 1440px abgeschnitten."""
    regel = _terminal_regel(terminal_css, r'\btable\b[^{]*\btd\b')
    assert re.search(r'font-size:\s*var\(--t-groesse-tabelle\)', regel), \
        "Tabellenzellen sind nicht auf --t-groesse-tabelle (17px) gesetzt"
    assert re.search(r'padding:\s*[^;]+ !important', regel), \
        "Zellenabstände (inline 10px 14px) werden nicht kompakter überschrieben"
    regel = _terminal_regel(terminal_css, r'\.badge')
    assert re.search(r'white-space:\s*nowrap !important', regel), \
        "Badges dürfen im Terminal-Theme nicht mitten im Wort umbrechen"


def test_terminal_summe_gesamt_ist_groesste_zahl(terminal_block, terminal_css):
    """GESAMTBETRAG / RECHNUNGSBETRAG (BRUTTO): Wert trägt die Klasse .summe__gesamt
    und ist im Terminal-Theme die größte Zahl im Summenblock (mindestens --fs-gross),
    in --t-text-hell mit tabular-nums."""
    m = re.search(r'html\[data-theme="terminal"\][^{]*\.summe__gesamt[^{]*\{([^}]*)\}', terminal_css)
    assert m, "keine .summe__gesamt-Regel in terminal.css"
    regel = m.group(1)
    assert re.search(r'color:\s*var\(--t-text-hell\) !important', regel), \
        "Summenwert nicht in --t-text-hell"
    assert re.search(r'font-variant-numeric:\s*tabular-nums', regel), \
        "Summenwert ohne tabular-nums"
    fs = re.search(r'font-size:\s*var\((--t-[a-z0-9-]+)\)', regel)
    assert fs, "Summenwert ohne Token-Schriftgröße"
    token_map = dict(re.findall(r'(--t-[a-z0-9-]+)\s*:\s*([^;]+);', terminal_css))
    px = float(re.fullmatch(r'([\d.]+)px', token_map[fs.group(1)].strip()).group(1))
    gross = re.search(r'--fs-gross:\s*([\d.]+)px', terminal_block)
    assert gross, "--fs-gross im Terminal-Block nicht in px"
    assert px >= float(gross.group(1)), \
        f"Summenwert {px}px < --fs-gross ({gross.group(1)}px) — nicht die größte Zahl im Summenblock"

    det = (VORLAGEN / "invoices" / "detail_positionen.html").read_text(encoding="utf-8")
    zeile = [z for z in det.splitlines() if "gross_total|euro" in z]
    assert zeile and all("summe__gesamt" in z for z in zeile), \
        "Gesamtbetrag-Wert in detail_positionen.html trägt nicht die Klasse summe__gesamt"
    form = (VORLAGEN / "invoices" / "form.html").read_text(encoding="utf-8")
    zeilen = [z for z in form.splitlines()
              if "formatEur(grossTotal)" in z or "formatEur(bruttoNachAbzug)" in z]
    assert len(zeilen) >= 2 and all("summe__gesamt" in z for z in zeilen), \
        "Summenzeilen in form.html tragen nicht die Klasse summe__gesamt"


def test_terminal_karten_h2_saira_30_hell(terminal_css):
    """Runde 2 (A4): Kartenüberschriften stehen in Saira Condensed 800 kursiv in
    --t-groesse-h2 (30px) und --t-text-hell. Begründet angepasster Nachfolger des
    bisherigen Tests (Plex 600 / --t-groesse-klein / --t-akzent), nicht gelöscht."""
    regel = _terminal_regel(terminal_css, r'\.card h2')
    assert re.search(r'font-family:\s*var\(--t-schrift-marke\) !important', regel), \
        "Karten-h2 nicht in Saira Condensed (--t-schrift-marke)"
    assert re.search(r'font-weight:\s*800 !important', regel), "Karten-h2 ohne Gewicht 800"
    assert re.search(r'font-style:\s*italic !important', regel), "Karten-h2 nicht kursiv"
    assert re.search(r'font-size:\s*var\(--t-groesse-h2\) !important', regel), \
        "Karten-h2 nicht in --t-groesse-h2 (30px)"
    assert re.search(r'color:\s*var\(--t-text-hell\) !important', regel), \
        "Karten-h2 nicht in --t-text-hell"


def test_terminal_aktionsspalte_link_plex_tabelle(terminal_css):
    """Belegliste Aktionsspalte: der „bearbeiten“-Link (letzte Spalte) bekommt im
    Terminal-Theme Plex in --t-groesse-tabelle; die VERSAND-Spalte davor wird
    kompakt (nowrap, kleineres padding), damit die Tabelle bei 1440px passt."""
    regel = _terminal_regel(terminal_css, r'td:last-child a')
    assert re.search(r'font-family:\s*var\(--t-schrift-text\) !important', regel), \
        "Aktions-Link nicht in IBM Plex Mono"
    assert re.search(r'font-size:\s*var\(--t-groesse-tabelle\) !important', regel), \
        "Aktions-Link nicht in --t-groesse-tabelle"
    regel = _terminal_regel(terminal_css, r'td:nth-last-child\(2\)')
    assert re.search(r'white-space:\s*nowrap', regel), "VERSAND-Spalte nicht nowrap"
    assert re.search(r'padding:\s*[^;]+ !important', regel), \
        "VERSAND-Spalte ohne kompakteres padding"


def test_terminal_storno_badge_abstand_am_link(terminal_css):
    """Storno-Badge: als Flex-Item verschwindet das Leerzeichen vor der Belegnummer
    („DURCHRE-2026-007“) — der Abstand kommt per margin-left am Link, nicht im Text."""
    regel = _terminal_regel(terminal_css, r'\[data-storniert-durch\] a')
    assert re.search(r'margin-left:\s*[^;]+', regel), \
        "kein margin-left am Link im Storno-Badge"


def test_terminal_summe_gesamt_in_h2_groesse(terminal_css):
    """Gesamtbetrag: .summe__gesamt in --t-groesse-h2 (30px) — bleibt die größte
    Zahl im Summenblock (mindestens --fs-gross = 20px)."""
    m = re.search(r'html\[data-theme="terminal"\][^{]*\.summe__gesamt[^{]*\{([^}]*)\}', terminal_css)
    assert m, "keine .summe__gesamt-Regel in terminal.css"
    assert re.search(r'font-size:\s*var\(--t-groesse-h2\) !important', m.group(1)), \
        ".summe__gesamt nicht in --t-groesse-h2 (30px)"


# ---------------------------------------------------------------------------
# Feste Schriftgrößen unter 15px: jede font-size-Angabe in px/rem aus dem
# base.html-<style> und aus allen Inline-Styles der Vorlagen muss im
# Terminal-Theme von terminal.css überschrieben werden (rem mal 16).
# ---------------------------------------------------------------------------

_GRENZE_PX = 15.0
_TERMINAL_SCOPE = 'html[data-theme="terminal"]'
_PIXEL_SCOPE = 'html[data-theme="pixel"]'


def _kommentare_neutral(css: str) -> str:
    """CSS-Kommentare durch Leerzeichen ersetzt (Zeilenumbrueche bleiben) —
    Offsets/Zeilennummern bleiben exakt, Klammern in Kommentaren stoeren nicht."""
    return re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), css, flags=re.S)


def _css_regeln(css: str):
    """Flache Regeln (Start-Offset, Selektor, Body) eines CSS-Texts."""
    css = _kommentare_neutral(css)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        yield m.start(), m.group(1).strip(), m.group(2)


def _px(wert: str, einheit: str) -> float:
    return float(wert) * (16.0 if einheit in ("rem", "em") else 1.0)


def _fundstellen_unter_15():
    """Alle font-size-Literale (px/rem) unter 15px: Regeln im <style>-Block von
    base.html plus Inline-Styles (style="…") aller Vorlagen unter app/templates."""
    fundstellen = []
    basis = BASE_HTML.read_text(encoding="utf-8")
    for sm in re.finditer(r"<style[^>]*>(.*?)</style>", basis, re.S):
        for start, sel, body in _css_regeln(sm.group(1)):
            for fm in re.finditer(r"font-size\s*:\s*([\d.]+)\s*(px|rem)\b", body):
                px = _px(fm.group(1), fm.group(2))
                if px < _GRENZE_PX - 1e-9:
                    zeile = basis.count("\n", 0, sm.start(1) + start) + 1
                    fundstellen.append({
                        "art": "regel",
                        "ort": f"base.html:{zeile} <style>, Selektor {sel!r}",
                        "selektor": sel,
                        "decl": fm.group(0).strip(),
                        "px": px,
                    })
    for pfad in sorted(VORLAGEN.rglob("*.html")):
        text = pfad.read_text(encoding="utf-8")
        for m in re.finditer(r'<(\w+)([^>]*?)style="([^"]*)"', text, re.S):
            tag, style = m.group(1), m.group(3)
            zeile = text.count("\n", 0, m.start()) + 1
            for decl in style.split(";"):
                fm = re.match(r"\s*font-size\s*:\s*([\d.]+)\s*(px|rem)\s*$", decl)
                if fm:
                    px = _px(fm.group(1), fm.group(2))
                    if px < _GRENZE_PX - 1e-9:
                        fundstellen.append({
                            "art": "inline",
                            "ort": f"{pfad}:{zeile} <{tag} style=…>",
                            "tag": tag,
                            "decl": decl.strip(),
                            "px": px,
                        })
    return fundstellen


def _ist_pixel_only(f) -> bool:
    """Pixel-only-Regel: Selektor beginnt mit html[data-theme=\"pixel\"] —
    die greift unter data-theme=\"terminal\" nie."""
    return f["art"] == "regel" and all(
        p.strip().startswith(_PIXEL_SCOPE) for p in f["selektor"].split(",")
    )


def _terminal_ueberschreibt(terminal_css: str, f) -> bool:
    """Beleg je Fundstelle: terminal.css hat eine Regel, die unter
    html[data-theme=\"terminal\"] genau diesen Selektor (bei <style>-Regeln)
    bzw. blanket dieses Tag (bei Inline-Styles, dort mit !important gegen das
    Inline-Style) auf font-size: var(--t-groesse-klein) setzt."""
    for _, sel, body in _css_regeln(terminal_css):
        teile = [p.strip() for p in sel.split(",")]
        if f["art"] == "regel":
            for s in f["selektor"].split(","):
                s = s.strip()
                if s and any(t.startswith(_TERMINAL_SCOPE) and s in t for t in teile) \
                        and re.search(r"font-size\s*:\s*var\(--t-groesse-klein\)", body):
                    return True
        else:
            if any(t == f"{_TERMINAL_SCOPE} {f['tag']}" for t in teile) \
                    and re.search(r"font-size\s*:\s*var\(--t-groesse-klein\)\s*!important", body):
                return True
    return False


def test_terminal_keine_feste_schrift_unter_15(terminal_css):
    """Keine feste Schrift unter 15px im Terminal-Theme: JEDE font-size-Angabe
    in px/rem (rem mal 16) unter 15px aus dem base.html-<style> und aus allen
    Vorlagen-Inline-Styles muss terminal.css im Terminal-Theme auf mindestens
    var(--t-groesse-klein) heben.

    Ausgenommen sind ausdrücklich Pixel-only-Regeln (Selektor beginnt mit
    html[data-theme=\"pixel\"]): der 8px-Pfeil der Pixel-Navigation
    (content:'▶' in html[data-theme=\"pixel\"] .nav-link.active::before) steht
    nur in der pixel-gescopten Regel — unter data-theme=\"terminal\" bekommt
    das ::before kein content und rendert nichts, die 8px erscheinen dort nie.
    """
    token_map = dict(re.findall(r"(--t-[a-z0-9-]+)\s*:\s*([^;]+);", terminal_css))
    assert "--t-groesse-klein" in token_map, "--t-groesse-klein fehlt in terminal.css"
    m = re.fullmatch(r"([\d.]+)px", token_map["--t-groesse-klein"].strip())
    assert m and float(m.group(1)) >= _GRENZE_PX, \
        f"--t-groesse-klein = {token_map['--t-groesse-klein']!r} ist unter 15px"

    fundstellen = _fundstellen_unter_15()
    assert fundstellen, "keine Fundstelle unter 15px gefunden — scannt der Test noch?"

    basis = BASE_HTML.read_text(encoding="utf-8")
    basis_style = "".join(re.findall(r"<style[^>]*>(.*?)</style>", basis, re.S))
    pfeil = [sel for _, sel, _ in _css_regeln(basis_style) if "nav-link" in sel and "::before" in sel]
    assert pfeil, "die ::before-Regel am nav-link wurde nicht gefunden"
    assert all(sel.startswith(_PIXEL_SCOPE) for sel in pfeil), \
        "ein ::before am nav-link ist nicht pixel-only — dann muesste terminal.css es ueberschreiben"

    pixel_only = [f for f in fundstellen if _ist_pixel_only(f)]
    assert pixel_only, "die pixel-only Fundstelle (8px-▶) wurde nicht als solche erkannt"
    luecken = [f for f in fundstellen
               if not _ist_pixel_only(f) and not _terminal_ueberschreibt(terminal_css, f)]
    assert not luecken, (
        f"{len(luecken)} font-size-Fundstellen unter 15px ohne Override in terminal.css: "
        + "; ".join(f"{f['ort']} ({f['decl']} = {f['px']}px)" for f in luecken)
    )


# ---------------------------------------------------------------------------
# Zustandslampen: jede .t-lampe--<name>-Regel in terminal.css muss eine
# Zustandfarbe tragen — Schmuckfarben wie --t-linie reichen auf --t-grund
# nicht (Kontrast dort nur ~1,7:1, Pflicht mindestens 4,5:1).
# ---------------------------------------------------------------------------

_ERLAUBTE_LAMPENFARBEN = [
    "var(--t-ok)",
    "var(--t-warnung)",
    "var(--t-fehler)",
    "var(--t-info)",
    "var(--t-text-matt)",
]
_ERWARTETE_LAMPEN = {"ok", "warnung", "fehler", "info", "aus"}


def _lampen_farben(terminal_css: str):
    """Name -> Farbe jeder terminal-gescopten .t-lampe--<name>-Regel."""
    lampen = {}
    for _, sel, body in _css_regeln(terminal_css):
        for teil in sel.split(","):
            m = re.fullmatch(r'html\[data-theme="terminal"\]\s+\.t-lampe--([a-z]+)', teil.strip())
            if m:
                farbe = re.search(r"color\s*:\s*([^;]+);", body)
                lampen[m.group(1)] = farbe.group(1).strip() if farbe else ""
    return lampen


@pytest.mark.parametrize("name", sorted(_ERWARTETE_LAMPEN))
def test_lampen_farben_sind_zustandsfarben(terminal_css, name):
    """Je Lampe ein Parametrisierungsfall: die Menge der .t-lampe--<name>-Regeln
    in terminal.css ist genau {ok, warnung, fehler, info, aus}, und jede Farbe
    ist eine der Zustandsfarben (--t-ok/--t-warnung/--t-fehler/--t-info/--t-text-matt)."""
    lampen = _lampen_farben(terminal_css)
    assert set(lampen) == _ERWARTETE_LAMPEN, \
        f"gefundene Lampen {sorted(lampen)} != {sorted(_ERWARTETE_LAMPEN)}"
    farbe = lampen.get(name)
    assert farbe in _ERLAUBTE_LAMPENFARBEN, \
        f".t-lampe--{name} traegt {farbe!r} — keine Zustandsfarbe aus {_ERLAUBTE_LAMPENFARBEN}"


# ---------------------------------------------------------------------------
# Runde 2: Stahlleiste mit Nieten und Wortmarke, Glas-Karten, Bühne,
# Saira Condensed als dritte Schrift, Zustandsformen an Badges, Kennzahlen
# in Zustandsfarben. Jede Zeile der Abnahmeliste A1-A12 hat hier mindestens
# einen Test; alle Regeln liegen nur unter html[data-theme="terminal"].
# ---------------------------------------------------------------------------

def _teil_bodies(css: str, teil_exakt: str):
    """Bodies aller Regelteile (Selektor nach Komma gesplittet), die exakt
    `teil_exakt` lauten — so lassen sich gruppierte Selektoren prüfen."""
    bodies = []
    for _, sel, body in _css_regeln(css):
        for teil in sel.split(","):
            if teil.strip() == teil_exakt:
                bodies.append(body)
    return bodies


SAIRA_DATEIEN = [
    "/static/fonts/saira-condensed-latin-800-normal.woff2",
    "/static/fonts/saira-condensed-latin-ext-800-normal.woff2",
]


def test_a1_saira_condensed_font_face_paare(basis_html):
    """A1: zwei @font-face für Saira Condensed, weight 800, latin + latin-ext mit
    dem unicode-range der vorhandenen latin-/latin-ext-Paare; Dateien im Image.
    Die Kursive wird synthetisch erzeugt (font-style: italic ohne Italic-Schnitt)."""
    faces = re.findall(r"@font-face\s*\{([^}]*)\}", basis_html)
    saira = [f for f in faces if "font-family: 'Saira Condensed'" in f]
    assert len(saira) == 2, f"erwartet 2 @font-face für Saira Condensed, gefunden {len(saira)}"
    for f in saira:
        assert "font-weight: 800" in f, "Saira Condensed ohne weight 800"
        assert "font-style: normal" in f, "Saira-@font-face nicht normal — Kursiv ist synthetisch"
    srcs = sorted(re.search(r"url\(([^)]+)\)", f).group(1) for f in saira)
    assert srcs == sorted(SAIRA_DATEIEN), f"Quellen falsch: {srcs}"
    ur_saira = sorted(re.search(r"unicode-range:\s*([^;]+);", f).group(1).strip() for f in saira)
    vt = [f for f in faces if "font-family: 'VT323'" in f]
    assert len(vt) == 2, "die VT323-Vergleichspaare wurden nicht gefunden"
    ur_vt = sorted(re.search(r"unicode-range:\s*([^;]+);", f).group(1).strip() for f in vt)
    assert ur_saira == ur_vt, "unicode-range der Saira-Paare weicht von den VT323-Paaren ab"
    for quelle in SAIRA_DATEIEN:
        pfad = Path("app") / quelle.lstrip("/")
        assert pfad.is_file(), f"{quelle} fehlt im Image"
        assert pfad.read_bytes()[:4] == b"wOF2", f"{quelle} ist keine WOFF2-Datei"


def test_a1_token_schrift_marke(terminal_css):
    """A1: neues Token --t-schrift-marke in terminal.css."""
    assert re.search(r"--t-schrift-marke\s*:\s*'Saira Condensed',\s*sans-serif\s*;", terminal_css), \
        "--t-schrift-marke fehlt in terminal.css"


def test_a2_kopfleiste_traegt_daten_attribute(basis_html):
    assert re.search(r'<header[^>]*\bdata-kopfleiste\b', basis_html), \
        "die Kopfleiste (☰ + Wortmarke) trägt kein data-kopfleiste"
    assert re.search(r'\bdata-kopf-marke\b', basis_html), \
        "die Wortmarke in der Kopfleiste trägt kein data-kopf-marke"


def test_a2_stahlleiste_chromverlauf_und_nieten(terminal_css):
    """A2: die Kopfleiste wird zur Stahlleiste — senkrechter Chromverlauf,
    je eine Niete links und rechts per ::before/::after."""
    bodies = _teil_bodies(terminal_css, 'html[data-theme="terminal"] header[data-kopfleiste]')
    assert bodies, "keine Stahlleisten-Regel für die Kopfleiste"
    regel = " ".join(bodies)
    assert re.search(r"background:\s*linear-gradient\(180deg", regel), \
        "kein senkrechter Chromverlauf auf der Stahlleiste"
    for pseudo in ("::before", "::after"):
        niete = _teil_bodies(terminal_css, f'html[data-theme="terminal"] header[data-kopfleiste]{pseudo}')
        assert niete, f"keine Niete per {pseudo}"
        n = " ".join(niete)
        assert re.search(r"content:\s*['\"]", n), f"Niete {pseudo} ohne content"
        assert re.search(r"border-radius:\s*50%", n), f"Niete {pseudo} nicht rund"
        assert re.search(r"radial-gradient", n), f"Niete {pseudo} ohne radialen Chromverlauf"


def test_a2_marke_in_der_stahlleiste(terminal_css):
    """A2: die Wortmarke in der Leiste bekommt den Chromverlauf in der Schrift —
    background-clip:text, Saira Condensed 800 kursiv, 40-54px."""
    bodies = _teil_bodies(terminal_css, 'html[data-theme="terminal"] header[data-kopfleiste] [data-kopf-marke]')
    assert bodies, "keine Marke-Regel in der Kopfleiste"
    regel = " ".join(bodies)
    assert re.search(r"font-family:\s*var\(--t-schrift-marke\)\s*!important", regel)
    assert re.search(r"font-weight:\s*800\s*!important", regel)
    assert re.search(r"font-style:\s*italic\s*!important", regel)
    m = re.search(r"font-size:\s*(\d+)px\s*!important", regel)
    assert m and 40 <= int(m.group(1)) <= 54, f"Marke nicht in 40-54px: {m.group(0) if m else '?' }"
    assert re.search(r"background:\s*linear-gradient\(180deg", regel), "kein Chromverlauf in der Schrift"
    assert re.search(r"background-clip:\s*text", regel), "kein background-clip:text"
    assert re.search(r"color:\s*transparent\s*!important", regel), "Schriftfarbe nicht transparent"


def test_a2_stahlleiste_auch_bei_breitem_fenster_sichtbar(basis_html, terminal_css):
    """A2: die Kopfleiste trägt lg:hidden — im Terminal-Theme muss sie auch bei
    breitem Fenster (Desktop) als Stahlleiste sichtbar bleiben."""
    assert re.search(r'<header[^>]*class="[^"]*lg:hidden[^"]*"', basis_html), \
        "die Kopfleiste mit lg:hidden wurde in base.html nicht gefunden"
    bodies = _teil_bodies(terminal_css, 'html[data-theme="terminal"] header[data-kopfleiste].lg\\:hidden')
    assert bodies, "keine Regel, die lg:hidden der Kopfleiste im Terminal-Theme aufhebt"
    assert any(re.search(r"display:\s*flex\s*!important", b) for b in bodies), \
        "Kopfleiste im Terminal-Theme nicht per display:flex !important sichtbar"


def test_a2_tagzeile_in_der_stahlleiste(terminal_css):
    """A3: die Zeile RECHNUNGEN · GOBD · DATEV steht als Text in der Stahlleiste,
    dunkel wie auf dem Stahl."""
    bodies = _teil_bodies(terminal_css, 'html[data-theme="terminal"] header[data-kopfleiste] [data-kopf-marke]::after')
    assert bodies, "die Tagzeile steht nirgends in der Stahlleiste"
    regel = " ".join(bodies)
    assert "RECHNUNGEN · GOBD · DATEV" in regel, "Tagzeile fehlt im content"
    assert re.search(r"color:\s*var\(--t-grund\)", regel), "Tagzeile nicht dunkel"


def test_a3_seitenleisten_marke_wird_ausgeblendet(basis_html, terminal_css):
    """A3: der Wortmarken-Block oben in der Seitenleiste ist im Terminal-Theme aus."""
    assert re.search(r'\bdata-seitenleiste-marke\b', basis_html), \
        "Wortmarken-Block in der Seitenleiste ohne data-Attribut"
    bodies = _teil_bodies(terminal_css, 'html[data-theme="terminal"] [data-seitenleiste-marke]')
    assert bodies and any(re.search(r"display:\s*none\s*!important", b) for b in bodies), \
        "Seitenleisten-Wortmarke im Terminal-Theme nicht ausgeblendet"


def test_a4_seitentitel_h1_saira_kursiv_chrom(terminal_css):
    """A4: die erste Überschrift im Hauptbereich (main h1) in Saira Condensed
    800 kursiv, 44-48px, mit Chromverlauf in der Schrift."""
    bodies = _teil_bodies(terminal_css, 'html[data-theme="terminal"] main h1')
    assert bodies, "keine Regel für die erste Überschrift im Hauptbereich (main h1)"
    regel = " ".join(bodies)
    assert re.search(r"font-family:\s*var\(--t-schrift-marke\)\s*!important", regel)
    assert re.search(r"font-weight:\s*800\s*!important", regel)
    assert re.search(r"font-style:\s*italic\s*!important", regel)
    m = re.search(r"font-size:\s*(\d+)px\s*!important", regel)
    assert m and 44 <= int(m.group(1)) <= 48, f"Seitentitel nicht in 44-48px: {m.group(0) if m else '?'}"
    assert re.search(r"background:\s*linear-gradient\(180deg", regel), "kein Chromverlauf"
    assert re.search(r"background-clip:\s*text", regel), "kein background-clip:text"
    assert re.search(r"color:\s*transparent\s*!important", regel), "Schriftfarbe nicht transparent"
    # h1 bleibt global unangetastet — nur innerhalb von main bekommt sie die Marke:
    assert not re.search(r'html\[data-theme="terminal"\]\s+h1\b', terminal_css), \
        "h1 darf nur innerhalb von main umgestellt werden"


def test_a5_card_glas(terminal_css):
    """A5: .card wird Glas — Rundung 14px, Verlauf aus Token per color-mix (kein Hex
    außer Weiß/Schwarz-Transparenz), 1px Rahmen in Chrom 35%, Glanz-::before oben
    links in Weiß höchstens 8%, weicher Schatten nach unten."""
    bodies = _teil_bodies(terminal_css, 'html[data-theme="terminal"] .card')
    assert bodies, "keine .card-Regel im Terminal-Theme"
    regel = " ".join(bodies)
    assert re.search(r"border-radius:\s*14px\s*!important", regel), "Rundung nicht 14px"
    bg = re.search(r"background:\s*([^;]+);", regel)
    assert bg and "linear-gradient" in bg.group(1), "kein Verlauf auf der Karte"
    assert "color-mix" in bg.group(1), "Glas-Verlauf nicht aus Token per color-mix gebaut"
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", bg.group(1)), \
        "Hex im Glas-Verlauf — nur Weiß/Schwarz-Transparenz ist erlaubt"
    assert re.search(r"border:\s*1px solid\s+color-mix\(in srgb,\s*var\(--t-chrom\)\s+35%", regel), \
        "Rahmen nicht 1px Chrom mit 35% Deckkraft"
    schatten = re.search(r"box-shadow:\s*([^;]+);", regel)
    assert schatten and re.search(r"0\s+10px\s+30px\s+rgba\(0,0,0,", schatten.group(1)), \
        "kein weicher Schatten nach unten"
    glanz = _teil_bodies(terminal_css, 'html[data-theme="terminal"] .card::before')
    assert glanz, "kein Glanz-::before auf der Karte"
    g = " ".join(glanz)
    assert re.search(r"content:", g), "Glanz-::before ohne content"
    m = re.search(r"rgba\(255,255,255,\s*0?\.(\d+)\)", g)
    assert m and int(m.group(1)) <= 8, f"Glanz über 8% Deckkraft: {m.group(0) if m else 'nichts gefunden'}"
    assert re.search(r"linear-gradient\(115deg", g), "Glanz nicht oben links (115deg)"


def test_a5_card_pseudo_ueberlappt_nicht_mit_pixel(basis_html):
    """A5: base.html nutzt .card::before/::after nur pixel-gescoped — im
    Terminal-Theme belegen die Glas-Regeln die Pseudoklassen frei."""
    basis_style = "".join(re.findall(r"<style[^>]*>(.*?)</style>", basis_html, re.S))
    treffer = [sel for _, sel, _ in _css_regeln(basis_style)
               if ".card::before" in sel or ".card::after" in sel]
    assert treffer, "die .card::before/::after-Regeln in base.html wurden nicht gefunden"
    for sel in treffer:
        assert all(p.strip().startswith('html[data-theme="pixel"]') for p in sel.split(",")), \
            f"card-Pseudo nicht pixel-only: {sel!r}"


def test_a6_buehne_lichtkegel_von_oben(terminal_css):
    """A6: Seitenhintergrund mit Lichtkegel von oben — Rosé höchstens 18% Deckkraft
    über radialem Verlauf aus --t-flaeche, --t-tafel, --t-grund. Fließtext ohne Sperrung."""
    bodies = _teil_bodies(terminal_css, 'html[data-theme="terminal"] body')
    assert bodies, "keine body-Regel im Terminal-Theme"
    regel = " ".join(bodies)
    bg = re.search(r"background(?:-image)?:\s*([^;]+);", regel)
    assert bg and "radial-gradient" in bg.group(1), "kein radialer Verlauf auf der Bühne"
    rose = re.search(r"color-mix\(in srgb,\s*var\(--t-[a-z-]+\)\s+(\d+)%", bg.group(1))
    assert rose and int(rose.group(1)) <= 18, "Lichtkegel Rosé über 18% oder nicht aus Token gebaut"
    for tok in ("--t-flaeche", "--t-tafel", "--t-grund"):
        assert f"var({tok})" in bg.group(1), f"{tok} fehlt im Bühnenverlauf"
    assert re.search(r"letter-spacing:\s*normal", regel), "Fließtext trägt Sperrung"


def test_a7_nav_active_gefuellt_mint(terminal_css):
    """A7: aktiver Navigationspunkt gefüllt mit --t-akzent, Schrift --t-auf-akzent, Rundung 8px."""
    bodies = _teil_bodies(terminal_css, 'html[data-theme="terminal"] .nav-link.active')
    assert bodies, "keine .nav-link.active-Regel im Terminal-Theme"
    regel = " ".join(bodies)
    assert re.search(r"background:\s*var\(--t-akzent\)", regel), "active nicht gefüllt mit --t-akzent"
    assert re.search(r"color:\s*var\(--t-auf-akzent\)", regel), "Schrift nicht --t-auf-akzent"
    assert re.search(r"border-radius:\s*8px", regel), "Rundung nicht 8px"


def test_a7_primaerknopf_verlauf_sekundaer_rahmen(terminal_css):
    """A7: Primärknopf mit senkrechtem Verlauf aus --t-akzent auf --t-auf-akzent,
    Rundung 8px; Sekundärknopf Rundung 8px mit Rahmen in --t-text."""
    bodies = _teil_bodies(terminal_css, 'html[data-theme="terminal"] .btn-primary')
    assert bodies, "keine .btn-primary-Regel im Terminal-Theme"
    regel = " ".join(bodies)
    assert re.search(r"background:\s*linear-gradient\(180deg", regel), "Primärknopf ohne senkrechten Verlauf"
    assert "var(--t-akzent)" in regel, "Verlauf nicht aus --t-akzent gebaut"
    assert re.search(r"color:\s*var\(--t-auf-akzent\)\s*!important", regel)
    assert re.search(r"border-radius:\s*8px", regel)
    bodies = _teil_bodies(terminal_css, 'html[data-theme="terminal"] .btn-secondary')
    assert bodies, "keine .btn-secondary-Regel im Terminal-Theme"
    regel = " ".join(bodies)
    assert re.search(r"border-radius:\s*8px", regel), "Sekundärknopf nicht gerundet 8px"
    assert re.search(r"border-color:\s*var\(--t-text\)", regel), "Sekundärknopf-Rahmen nicht in --t-text"


# A8: Klasse -> Zustand -> Farbe -> Form. Jede badge-*-Klasse, die in den
# Vorlagen vorkommt, muss in dieser Tabelle zugeordnet sein (Scan unten).
# Storno ist KEIN Fehler: cancelled/○ in --t-text-matt.
BADGE_ZUSTAENDE = [
    ("badge-paid", "ok", "var(--t-ok)", "●"),
    ("badge-sent", "ok", "var(--t-ok)", "●"),
    ("badge-issued", "warnung", "var(--t-warnung)", "▲"),
    ("badge-offen", "warnung", "var(--t-warnung)", "▲"),
    ("badge-ueberfaellig", "fehler", "var(--t-fehler)", "■"),
    ("badge-draft", "info", "var(--t-info)", "◆"),
    ("badge-cancelled", "text-matt", "var(--t-text-matt)", "○"),
    ("badge-discarded", "text-matt", "var(--t-text-matt)", "○"),
]


@pytest.mark.parametrize("klasse,zustand,farbe,form", BADGE_ZUSTAENDE)
def test_a8_badge_klasse_zustand_farbe_form(terminal_css, klasse, zustand, farbe, form):
    """A8: je Klasse ein Fall — Farbe in der Zustandsfarbe, Form per ::before-content."""
    farben = _teil_bodies(terminal_css, f'html[data-theme="terminal"] .{klasse}')
    assert farben and any(re.search(rf"color:\s*{re.escape(farbe)}\s*!important", b) for b in farben), \
        f".{klasse} nicht in {farbe} (Zustand {zustand})"
    formen = _teil_bodies(terminal_css, f'html[data-theme="terminal"] .{klasse}::before')
    assert formen and any(re.search(rf"content:\s*'{re.escape(form)}'", b) for b in formen), \
        f".{klasse}::before ohne content '{form}'"


def test_a8_jede_badge_klasse_der_vorlagen_ist_zugeordnet():
    """A8: jede badge-*-Klasse, die in irgendeiner Vorlage vorkommt, ist in der
    Tabelle BADGE_ZUSTAENDE zugeordnet. Der Vorlagen-Scan ist die eine Quelle."""
    klassen = set()
    for pfad in sorted(VORLAGEN.rglob("*.html")):
        klassen |= {"badge-" + m for m in re.findall(r"badge-([a-z]+)", pfad.read_text(encoding="utf-8"))}
    assert klassen, "keine badge-Klassen in den Vorlagen gefunden — scannt der Test noch?"
    tabelliert = {k for k, *_ in BADGE_ZUSTAENDE}
    assert klassen <= tabelliert, \
        f"badge-Klassen ohne Zuordnung: {sorted(klassen - tabelliert)}"


def test_a8_badges_ohne_rahmen_und_hintergrund(terminal_css):
    """A8: Badges im Terminal-Theme ohne Rahmen und ohne Hintergrund — die Form
    kommt allein aus ::before und Farbe."""
    bodies = _teil_bodies(terminal_css, 'html[data-theme="terminal"] .badge')
    assert bodies, "keine .badge-Regel im Terminal-Theme"
    assert any(re.search(r"border:\s*none\s*!important", b) for b in bodies), "Badges noch mit Rahmen"
    assert any(re.search(r"background:\s*(none|transparent)\s*!important", b) for b in bodies), \
        "Badges noch mit Hintergrund"


def test_a9_fliesstext_und_tabellenzellen_in_text(terminal_css):
    """A9: Fließtext und Tabellenzellen in --t-text."""
    bodies = _teil_bodies(terminal_css, 'html[data-theme="terminal"] table td')
    assert bodies, "keine table-td-Regel im Terminal-Theme"
    assert any(re.search(r"color:\s*var\(--t-text\)(\s*!important)?;", b) for b in bodies), \
        "Tabellenzellen nicht in --t-text"


def test_a9_labels_matt_mit_2px_laufweite(terminal_css):
    """A9: .label, .kpi__beschriftung und Tabellenköpfe in --t-text-matt mit 2px Laufweite."""
    for teil in ('html[data-theme="terminal"] .label',
                 'html[data-theme="terminal"] .kpi__beschriftung',
                 'html[data-theme="terminal"] .table-header'):
        bodies = _teil_bodies(terminal_css, teil)
        assert bodies, f"{teil} nicht gestylt"
        assert any(re.search(r"color:\s*var\(--t-text-matt\)", b) for b in bodies), \
            f"{teil} nicht in --t-text-matt"
        assert any(re.search(r"letter-spacing:\s*2px", b) for b in bodies), \
            f"{teil} ohne 2px Laufweite"


def test_a9_kpi_wert_in_text_hell(terminal_css):
    """A9: Beträge und große Zahlen (.kpi__wert) in --t-text-hell (Zustände in A10)."""
    bodies = _teil_bodies(terminal_css, 'html[data-theme="terminal"] .kpi__wert')
    assert bodies and any(re.search(r"color:\s*var\(--t-text-hell\)", b) for b in bodies), \
        "große Zahlen nicht in --t-text-hell"


def test_a9_kleine_gold_ueberschriften_werden_matt(terminal_css):
    """A9: kleine Überschriften, die heute inline in --gold/Akzent stehen, nehmen
    --t-text-matt (Mint-Labels fallen weg)."""
    regel = _terminal_regel(terminal_css, r'\[style\*="color:var\(--gold\)"\]')
    assert regel, "keine Regel für kleine gold-farbene Überschriften"
    assert re.search(r"color:\s*var\(--t-text-matt\)\s*!important", regel), \
        "kleine Gold-Überschriften nicht in --t-text-matt"


def test_a9_hinweiskasten_in_text_nicht_pfirsich(terminal_css):
    """A9: Hinweiskasten (z. B. „n gestellte Rechnungen ohne Zustellung“,
    data-kpi=hinweis-versand): Fließtext in --t-text, nicht in Pfirsich."""
    regel = _terminal_regel(terminal_css, r'\[data-kpi="hinweis-versand"\]')
    assert regel, "Hinweiskasten (data-kpi=hinweis-versand) nicht gefasst"
    assert re.search(r"color:\s*var\(--t-text\)\s*!important", regel), \
        "Hinweiskasten-Fließtext nicht in --t-text"


def test_a10_symbolkaesten_der_kpi_karten_ausgeblendet(terminal_css):
    """A10: die farbigen Symbolkästen rechts in den Kennzahl-Karten (40px-Boxen
    im .card) werden im Terminal-Theme ausgeblendet."""
    regel = _terminal_regel(terminal_css, r'\.card\s+div\[style\*="width:40px"\]')
    assert regel and re.search(r"display:\s*none\s*!important", regel), \
        "Symbolkästen der Kennzahl-Karten nicht ausgeblendet"


def test_a10_kpi_wert_vt323_58px(terminal_css):
    """A10: .kpi__wert in VT323, etwa 58px (--t-groesse-kpi)."""
    bodies = _teil_bodies(terminal_css, 'html[data-theme="terminal"] .kpi__wert')
    assert any(re.search(r"font-family:\s*var\(--t-schrift-anzeige\)", b) for b in bodies), \
        ".kpi__wert nicht in VT323"
    assert any(re.search(r"font-size:\s*var\(--t-groesse-kpi\)", b) for b in bodies), \
        ".kpi__wert nicht in --t-groesse-kpi"
    token_map = dict(re.findall(r"(--t-[a-z0-9-]+)\s*:\s*([^;]+);", terminal_css))
    assert "--t-groesse-kpi" in token_map, "--t-groesse-kpi fehlt in terminal.css"
    m = re.fullmatch(r"([\d.]+)px", token_map["--t-groesse-kpi"].strip())
    assert m and 56 <= float(m.group(1)) <= 60, \
        f"--t-groesse-kpi nicht etwa 58px: {token_map.get('--t-groesse-kpi')!r}"


def test_a10_kpi_zustandsfarben_und_rahmen(terminal_css):
    """A10: Kachel mit Zustand — Zahl in der Zustandsfarbe, Rahmen derselben Farbe
    mit 70%. offen -> warnung, ueberfaellig -> fehler."""
    for kpi, farbe in (("offen", "var(--t-warnung)"), ("ueberfaellig", "var(--t-fehler)")):
        wert = _teil_bodies(terminal_css, f'html[data-theme="terminal"] [data-kpi="{kpi}"] .kpi__wert')
        assert wert and any(re.search(rf"color:\s*{re.escape(farbe)}\s*!important", b) for b in wert), \
            f"KPI {kpi}: Zahl nicht in {farbe}"
        rahmen = _teil_bodies(terminal_css, f'html[data-theme="terminal"] .card[data-kpi="{kpi}"]')
        assert rahmen and any(
            re.search(rf"border-color:[^;]*color-mix\(in srgb,\s*{re.escape(farbe)}\s+70%", b) for b in rahmen), \
            f"KPI {kpi}: Rahmen nicht in {farbe} mit 70% Deckkraft"


def test_a11_tabellenkopf_chrom_zeilenlinien(terminal_css):
    """A11: Tabellenkopf mit 1px-Unterlinie in --t-chrom 35%, Zeilenlinien in
    --t-rahmen 40% (wie im Entwurf)."""
    kopf = _teil_bodies(terminal_css, 'html[data-theme="terminal"] table th')
    assert kopf and any(
        re.search(r"border-bottom:\s*1px solid\s+color-mix\(in srgb,\s*var\(--t-chrom\)\s+35%", b) for b in kopf), \
        "Tabellenkopf ohne 1px-Unterlinie in --t-chrom 35%"
    zeilen = _teil_bodies(terminal_css, 'html[data-theme="terminal"] table td')
    assert zeilen and any(
        re.search(r"border-bottom:\s*1px solid\s+color-mix\(in srgb,\s*var\(--t-rahmen\)\s+40%", b) for b in zeilen), \
        "Zeilenlinien nicht in --t-rahmen 40%"


def test_a11_betraege_rechts_tabular_hell(terminal_css):
    """A11: Beträge rechtsbündig, tabular-nums, in --t-text-hell."""
    regel = _terminal_regel(terminal_css, r'td\[style\*="text-align:right"\]')
    assert regel, "Betrags-Zellen (inline text-align:right) nicht gefasst"
    assert re.search(r"text-align:\s*right", regel), "Beträge nicht rechtsbündig"
    assert re.search(r"font-variant-numeric:\s*tabular-nums", regel), "keine tabular-nums"
    assert re.search(r"color:\s*var\(--t-text-hell\)", regel), "Beträge nicht in --t-text-hell"


def test_a12_keine_scanlines_im_terminal_theme(terminal_css):
    """A12: Rasterlinien (Scanlines) bleiben aus — kein repeating-linear-gradient
    im Terminal-Theme."""
    assert "repeating-linear-gradient" not in terminal_css, \
        "Scanlines (repeating-linear-gradient) im Terminal-Theme gefunden"
