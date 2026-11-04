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


def test_terminal_karten_h2_plex_600_klein_akzent(terminal_css):
    """Karten-h2: preflight (tailwind-play hängt sein Style ans Ende des head)
    setzt h1-h6 auf font-size:inherit — wirksam ist die geerbte Körpergröße
    (18px, in VT323 optisch ~15px). h2 unter 24px nimmt Plex 600 in
    --t-groesse-klein und --t-akzent. Die Seitenüberschrift h1 bleibt VT323."""
    regel = _terminal_regel(terminal_css, r'\.card h2')
    assert re.search(r'font-family:\s*var\(--t-schrift-text\) !important', regel), \
        "Karten-h2 nicht in IBM Plex Mono"
    assert re.search(r'font-weight:\s*600 !important', regel), "Karten-h2 ohne Gewicht 600"
    assert re.search(r'font-size:\s*var\(--t-groesse-klein\) !important', regel), \
        "Karten-h2 nicht in --t-groesse-klein"
    assert re.search(r'color:\s*var\(--t-akzent\) !important', regel), \
        "Karten-h2 nicht in --t-akzent"
    assert not re.search(r'html\[data-theme="terminal"\][^{]*\bh1\b[^{]*\{', terminal_css), \
        "h1 darf im Terminal-Theme nicht umgestellt werden"


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
