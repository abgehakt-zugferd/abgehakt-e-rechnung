"""Die Oberfläche laedt nichts aus dem Netz nach. Alles liegt im Image.

Vorher holte `base.html` beim Aufbau jeder Seite vier Schriften von Google, das
CSS-Werkzeug von einem CDN und Alpine.js von einem zweiten. Das ist aus drei
Gründen falsch:

  1. **Es ist eine Datenübertragung an Dritte.** Jeder Seitenaufruf schickt die
     IP-Adresse des Nutzers an drei fremde Betreiber. Der Datenschutz-Abschnitt
     im README nennt genau drei Stellen, an denen Daten den Rechner verlassen,
     und alle drei stößt der Nutzer selbst an. Ein Nachladen bei jedem Klick
     gehört nicht dazu. Ein Programm, das mit „läuft auf Ihrem Rechner" wirbt,
     darf diese Zusage nicht in der ersten Zeile seines `<head>` brechen.
  2. **Ohne Internet sah die Anwendung anders aus.** Beim Schriftabruf hiess das
     Ersatzschrift, beim CSS-Werkzeug ein unformatiertes Gerippe. Eine
     Rechnungssoftware muss im Zug, im Keller und beim Kunden ohne WLAN dasselbe
     Bild zeigen.
  3. **Die Gegenstelle ist nicht unser Vertrag.** Ändert sie Auslieferung oder
     Verfügbarkeit, ändert sich unsere Oberfläche, ohne dass jemand etwas
     released hat. Alpine.js hing zusätzlich an einem gleitenden Stand
     (`3.x.x`): jeder Aufruf konnte eine andere Fassung liefern als der letzte.

Bezugsquellen beim Einpflegen: **Bunny Fonts** (OFL-Bestand, schnittgleich mit
Google Fonts) für die Schriften, die jeweiligen Projekte für die beiden
JavaScript-Bündel. Im Betrieb liegt alles unter `app/static/` und wird von der
Anwendung selbst ausgeliefert.
"""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

VORLAGEN = Path("app/templates")
SCHRIFTEN = Path("app/static/fonts")
SKRIPTE = Path("app/static/js")

# Jeder Host, der Teile der Oberfläche ausliefert, ist derselbe Fehler.
# Bunny und jsDelivr stehen bewusst mit drin: sie sind Bezugsquelle beim
# Einpflegen, nicht Laufzeitquelle.
FREMDE_HOSTS = [
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "fonts.bunny.net",
    "use.typekit.net",
    "fonts.cdnfonts.com",
    "cdn.tailwindcss.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
    "cdnjs.cloudflare.com",
]

# Die vier Schnitte, die die beiden Themes in `--font-*` benennen.
FAMILIEN = ["Press Start 2P", "VT323", "Share Tech Mono", "Staatliches"]


def _alle_vorlagen():
    return sorted(VORLAGEN.rglob("*.html"))


@pytest.fixture(scope="module")
def basis_html():
    return (VORLAGEN / "base.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("host", FREMDE_HOSTS)
def test_keine_vorlage_laedt_von_fremden_hosts(host):
    treffer = [str(p) for p in _alle_vorlagen() if host in p.read_text(encoding="utf-8")]
    assert treffer == [], f"{host} steht noch in: {treffer}"


def test_es_gibt_ueberhaupt_vorlagen_zu_pruefen():
    """Sonst wäre der Test oben grün, weil er nichts liest."""
    assert len(_alle_vorlagen()) >= 10


@pytest.mark.parametrize("familie", FAMILIEN)
def test_jede_benannte_schrift_hat_eine_font_face_regel(basis_html, familie):
    """Eine Schrift, die in `--font-display` steht, aber nirgends deklariert ist,
    fällt still auf die Ersatzschrift zurück — das Layout sieht dann falsch aus,
    ohne dass irgendetwas fehlschlägt."""
    assert f"font-family: '{familie}'" in basis_html, \
        f"{familie} wird benutzt, aber nicht per @font-face bereitgestellt"


def test_font_face_quellen_zeigen_ausschliesslich_auf_die_eigene_anwendung(basis_html):
    """Ein einzelnes vergessenes `url(https://…)` reicht, um die Zusage zu brechen."""
    quellen = re.findall(r"url\(([^)]+)\)", basis_html)
    assert quellen, "keine @font-face-Quellen gefunden — der Test prüft sonst nichts"
    fremd = [q for q in quellen if not q.strip("\"'").startswith("/static/")]
    assert fremd == [], f"Quellen außerhalb der eigenen Anwendung: {fremd}"


def test_jede_referenzierte_schriftdatei_liegt_wirklich_im_image(basis_html):
    for quelle in re.findall(r"url\(([^)]+)\)", basis_html):
        pfad = Path("app") / quelle.strip("\"'").lstrip("/")
        assert pfad.is_file(), f"{quelle} ist deklariert, aber nicht vorhanden"
        assert pfad.read_bytes()[:4] == b"wOF2", f"{quelle} ist keine gültige WOFF2-Datei"


def test_die_anwendung_liefert_die_schriften_selbst_aus(basis_html):
    """Ohne eingehängtes Verzeichnis wären die Dateien zwar im Image, aber der
    Browser bekäme 404 und zeigte die Ersatzschrift — genau der Zustand, den der
    Umbau beseitigen sollte."""
    with TestClient(app) as client:
        for quelle in re.findall(r"url\(([^)]+)\)", basis_html):
            pfad = quelle.strip("\"'")
            antwort = client.get(pfad)
            assert antwort.status_code == 200, f"{pfad} → {antwort.status_code}"
            assert antwort.content[:4] == b"wOF2"
            # Ohne registrierten Typ liefert Starlette `text/plain`. Browser
            # nehmen die Schrift trotzdem, aber eine als Text deklarierte
            # Binaerdatei ist eine Falle fuer alles, was dazwischenhaengt
            # (Proxy, Kompression, Zwischenspeicher).
            assert antwort.headers["content-type"].startswith("font/woff2"), \
                f"{pfad} wird als {antwort.headers['content-type']} ausgeliefert"


# --- Skripte und Stylesheets -------------------------------------------


def _externe_verweise(html: str):
    """Alle `src=`/`href=`-Ziele, die nicht auf die eigene Anwendung zeigen.

    Interne Links (`/invoices`, `#`) und `mailto:` sind kein Nachladen — gesucht
    wird nur, was der Browser beim Aufbau der Seite von woanders holt.
    """
    ziele = re.findall(r"<(?:script|link)\b[^>]*?(?:src|href)=[\"']([^\"']+)[\"']", html)
    return [z for z in ziele if z.startswith(("http://", "https://", "//"))]


def test_keine_vorlage_zieht_skripte_oder_stylesheets_aus_dem_netz():
    fundstellen = {
        str(p): _externe_verweise(p.read_text(encoding="utf-8"))
        for p in _alle_vorlagen()
    }
    offen = {k: v for k, v in fundstellen.items() if v}
    assert offen == {}, f"laedt beim Seitenaufbau von aussen nach: {offen}"


def test_base_html_bindet_ueberhaupt_skripte_ein(basis_html):
    """Sonst waere der Test oben grün, weil die Seite gar kein Skript nutzt."""
    assert re.search(r"<script\b[^>]*\bsrc=", basis_html)


@pytest.mark.parametrize("datei", [
    "tailwind-play-3.4.17.js",
    "alpine-3.15.12.min.js",
])
def test_die_mitgelieferten_skripte_werden_ausgeliefert(datei):
    pfad = SKRIPTE / datei
    assert pfad.is_file(), f"{datei} fehlt im Image"
    assert pfad.stat().st_size > 10_000, f"{datei} ist verdaechtig klein"
    with TestClient(app) as client:
        antwort = client.get(f"/static/js/{datei}")
    assert antwort.status_code == 200


def test_die_skriptstaende_sind_festgenagelt(basis_html):
    """Vorher hing Alpine an `alpinejs@3.x.x`: ein gleitender Stand, bei dem jeder
    Aufruf eine andere Fassung liefern konnte. Was im Image liegt, traegt seine
    Version im Dateinamen — und die Vorlage nennt genau diese."""
    for datei in SKRIPTE.glob("*.js"):
        assert re.search(r"\d+\.\d+\.\d+", datei.name), \
            f"{datei.name} nennt keine Version"
    assert "alpine-3.15.12.min.js" in basis_html
    assert "3.x.x" not in basis_html


def test_der_lizenztext_der_skripte_wird_mit_ausgeliefert():
    """MIT verlangt wie die OFL, dass Lizenz und Urhebervermerk jeder Kopie
    beiliegen. Wer die Buendel ins Image legt, verteilt sie."""
    text = (SKRIPTE / "LIZENZEN.txt").read_text(encoding="utf-8")
    for wer in ["Tailwind", "Alpine", "MIT"]:
        assert wer in text


def test_der_lizenztext_wird_mit_ausgeliefert():
    """Die OFL verlangt, dass die Lizenz jeder Kopie der Schrift beiliegt. Wer die
    Dateien ins Image legt, verteilt sie — der Text muss daneben liegen."""
    lizenz = SCHRIFTEN / "OFL.txt"
    assert lizenz.is_file()
    text = lizenz.read_text(encoding="utf-8")
    for familie in FAMILIEN:
        assert familie in text, f"{familie} ist im Lizenztext nicht abgedeckt"
