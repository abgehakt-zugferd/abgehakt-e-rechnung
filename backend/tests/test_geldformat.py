"""Geldbeträge und Mengen erscheinen in deutscher Schreibweise — überall.

Der Fehler, der zu diesen Tests führte (2026-08-12, beim Erstellen der
Bildschirmfotos für die Website): Die Oberfläche zeigte `2501.38 €` statt
`2.501,38 €` und `14.0000 Stunden` statt `14 Stunden`. Das erzeugte **PDF war
die ganze Zeit korrekt** — `pdf_generator._money` macht die Umwandlung seit
jeher richtig.

Genau darin liegt die Lehre: Die Regel „so schreibt man einen Betrag" stand
**zweimal** im Programm — einmal ausformuliert im PDF-Generator und einmal als
`{{ "%.2f"|format(...) }}` in vier Vorlagen. Zwei Kopien einer Regel driften,
und hier war die zweite von Anfang an falsch. Es gibt deshalb ab jetzt genau
eine Quelle (`app/darstellung.py`), die beide Wege benutzen.

Warum das mehr ist als Kosmetik: Ein Rechnungsprogramm wird an solchen Stellen
beurteilt. Wer beruflich mit Belegen zu tun hat, liest `2501.38` als Fehler,
bevor er die erste Funktion ausprobiert hat — und bei einem Betrag wie `1.250`
ist die englische Schreibweise nicht nur ungewohnt, sondern **mehrdeutig**:
tausendzweihundertfünfzig oder eins Komma zwei fünf?

Die drei Tests unten decken drei verschiedene Fehlerarten ab:
  * die Umwandlung selbst (Einheitstest),
  * das Vergessen der Registrierung in EINEM der acht Jinja-Environments
    (Drift-Wache — jeder Router hält in diesem Projekt sein eigenes),
  * den Rückfall auf `"%.2f"|format` in einer Vorlage (Quell-Wache).
"""
import re
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.templating import Jinja2Templates

from app.darstellung import betrag, euro, menge, registriere_darstellungsfilter

VORLAGEN = Path("app/templates")


# ---------------------------------------------------------------- Umwandlung

@pytest.mark.parametrize("wert, erwartet", [
    (Decimal("2501.38"), "2.501,38 €"),      # Tausenderpunkt UND Dezimalkomma
    (Decimal("72.00"), "72,00 €"),           # unter tausend: kein Punkt
    (Decimal("1250"), "1.250,00 €"),         # ganze Zahl bekommt Nachkommastellen
    (Decimal("0"), "0,00 €"),
    (Decimal("1234567.5"), "1.234.567,50 €"),  # zwei Tausendertrenner
    (Decimal("-49.9"), "-49,90 €"),          # Gutschrift/Storno
])
def test_euro_schreibt_deutsch(wert, erwartet):
    assert euro(wert) == erwartet


@pytest.mark.parametrize("wert, stellen, erwartet", [
    (Decimal("2501.38"), 2, "2.501,38"),
    (Decimal("6221.38"), 0, "6.221"),    # Kennzahl-Kachel: Cent wären Lärm
    (Decimal("6221.62"), 0, "6.222"),    # und wird dabei gerundet, nicht abgeschnitten
    (Decimal("999"), 0, "999"),
])
def test_betrag_ohne_waehrungszeichen(wert, stellen, erwartet):
    """Für Stellen, an denen das € gestalterisch getrennt steht.

    Auf den Kennzahl-Kacheln der Übersicht steht die Zahl groß und das €
    klein daneben. Gäbe `euro` dort sein € mit aus, stünde es zweimal da.
    """
    assert betrag(wert, stellen) == erwartet


def test_euro_ist_betrag_plus_waehrungszeichen():
    """Eine Regel, zwei Ausgaben — nicht zwei Regeln."""
    assert euro(Decimal("2501.38")) == betrag(Decimal("2501.38")) + " €"


def test_euro_rechnet_nicht_ueber_float():
    """`Decimal` darf nicht durch `float` laufen.

    Die Vorlagen taten genau das (`|float`). Bei Geld ist das die Sorte
    Abkürzung, die irgendwann einen Cent verschluckt.
    """
    assert euro(Decimal("0.145")) == "0,15 €"   # kaufmännisch, nicht bankers rounding
    assert euro(Decimal("1.005")) == "1,01 €"


@pytest.mark.parametrize("wert, erwartet", [
    (Decimal("14.0000"), "14"),      # der eigentliche Anlass
    (Decimal("1.0000"), "1"),
    (Decimal("2.5000"), "2,5"),      # gebrochene Menge bleibt, mit Komma
    (Decimal("0.7500"), "0,75"),
    (Decimal("12"), "12"),
    # Ohne Tausendertrenner: "1000 Stück" ist auf einer Rechnung üblich,
    # "1.000 Stück" wirkt neben der Betragsspalte wie ein Geldbetrag.
    (Decimal("1000.0000"), "1000"),
])
def test_menge_ohne_schleppende_nullen(wert, erwartet):
    assert menge(wert) == erwartet


@pytest.mark.parametrize("wert, erwartet", [
    (Decimal("120.0000"), "120"),
    (Decimal("20.0000"), "20"),
    (Decimal("1500.0000"), "1500"),
])
def test_menge_kippt_nicht_in_die_exponentialschreibweise(wert, erwartet):
    """Die Falle, die im PDF an den Kunden stand.

    `Decimal.normalize()` streicht schleppende Nullen — auch VOR dem Komma —
    und schaltet dann in die Exponentialform: `Decimal("120.0000").normalize()`
    ist `1.2E+2`. Der PDF-Generator gab genau das über `str()` aus. Auffallen
    konnte es kaum: Es trifft nur Mengen, die durch zehn teilbar sind. Eine
    Position über 14 Stunden war unauffällig, eine über 120 Stunden hätte
    „1.2E+2 Stunden" auf der Rechnung an den Kunden gezeigt.
    """
    assert menge(wert) == erwartet


def test_pdf_gibt_mengen_nicht_mit_str_normalize_aus():
    """Quell-Wache gegen den Rückfall.

    `str(x.normalize())` ist die Schreibweise, die die Exponentialform
    erzeugt hat. Sie darf im PDF-Generator nicht wiederkehren.
    """
    quelle = Path("app/services/pdf_generator.py").read_text(encoding="utf-8")
    assert "quantity.normalize()" not in quelle, (
        "Mengen im PDF wieder über str(.normalize()) — das kippt bei 120 in 1.2E+2"
    )


def test_pdf_und_oberflaeche_teilen_dieselbe_funktion():
    """Der PDF-Generator darf keine zweite Kopie der Regel halten.

    Bricht dieser Test, ist die Doppelung zurück — und mit ihr die Möglichkeit,
    dass Bildschirm und Beleg denselben Betrag verschieden schreiben.
    """
    from app.services import pdf_generator

    assert pdf_generator._money is euro


# --------------------------------------------------------------- Drift-Wache

def _alle_template_instanzen() -> dict[str, Jinja2Templates]:
    """Jede Jinja2Templates-Instanz der Anwendung, nach Modul benannt.

    In diesem Projekt erzeugt JEDER Router sein eigenes Environment (siehe
    `branding.register_branding_globals`). Ein Filter, der nur in einem davon
    registriert ist, fällt genau in den Vorlagen der anderen aus — und zwar
    als `TemplateAssertionError` erst beim Aufruf der Seite, nicht beim Start.
    """
    import app.main  # noqa: F401  — importiert alle Router

    gefunden = {}
    for name, modul in list(sys.modules.items()):
        if not name.startswith("app."):
            continue
        for attribut in vars(modul).values() if hasattr(modul, "__dict__") else []:
            if isinstance(attribut, Jinja2Templates):
                gefunden[name] = attribut
    return gefunden


def test_jede_jinja_umgebung_kennt_die_filter():
    instanzen = _alle_template_instanzen()
    # Wenn hier nichts gefunden wird, prüft der Test nichts — das wäre grün
    # aus dem falschen Grund.
    assert len(instanzen) >= 5, f"zu wenige Environments gefunden: {list(instanzen)}"

    ohne = {
        name: sorted({"euro", "menge", "betrag", "beleg_etikett", "beleg_badge"} - set(t.env.filters))
        for name, t in instanzen.items()
        if not {"euro", "menge", "betrag", "beleg_etikett", "beleg_badge"} <= set(t.env.filters)
    }
    assert not ohne, f"Filter fehlen in: {ohne}"


def test_registrierung_ist_wiederholbar():
    """Zweimal registrieren darf nicht scheitern — die Router importieren sich
    gegenseitig, die Reihenfolge ist nicht garantiert."""
    t = Jinja2Templates(directory=str(VORLAGEN))
    registriere_darstellungsfilter(t)
    registriere_darstellungsfilter(t)
    assert t.env.filters["euro"] is euro


# --------------------------------------------------------------- Quell-Wache

# `{{ "%.2f"|format(x) }}` ist die Schreibweise, die den Fehler verursacht hat:
# C-Formatierung kennt weder Dezimalkomma noch Tausenderpunkt.
C_FORMAT = re.compile(r'"%\.\d+f"\s*\|\s*format')


def test_keine_vorlage_formatiert_geld_mit_c_syntax():
    """Gesucht sind GELDbeträge, nicht jede Zahl.

    Die Dateigröße im Archiv („48 KB") läuft ebenfalls über `%.0f` und ist
    dort richtig — eine Größenangabe braucht keinen Tausenderpunkt und schon
    gar kein Komma. Erkennungsmerkmal für Geld ist deshalb das € in derselben
    Zeile. Wer eine Betragsspalte ohne € in der Zeile baut, umgeht diese Wache;
    dagegen steht die Drift-Wache oben, nicht diese hier.
    """
    treffer = [
        f"{pfad}:{i}"
        for pfad in sorted(VORLAGEN.rglob("*.html"))
        for i, zeile in enumerate(pfad.read_text(encoding="utf-8").splitlines(), 1)
        if C_FORMAT.search(zeile) and "€" in zeile
    ]
    assert not treffer, (
        "Geldbeträge mit C-Formatierung statt mit dem Filter |euro:\n  "
        + "\n  ".join(treffer)
    )


def test_positionszellen_brechen_nicht_mitten_im_wert_um():
    """In der Positionstabelle darf kein Wert über zwei Zeilen laufen.

    Vor der Korrektur stand dort „145,00" und darunter allein das „€", weil die
    Spalte zu schmal war. Zwei Zeilen für einen Betrag liest niemand als einen
    Betrag. Behoben wurde die Ursache (die Seite war auf 900 px gedeckelt, die
    Tabelle bekam davon zwei Drittel); `nowrap` ist die Absicherung dagegen,
    dass eine künftige, engere Spalte denselben Effekt wieder erzeugt.
    """
    zeilen = (VORLAGEN / "invoices/detail.html").read_text(encoding="utf-8").splitlines()
    ohne = [
        f"{i}: {z.strip()[:70]}"
        for i, z in enumerate(zeilen, 1)
        if z.lstrip().startswith("<td")
        and ("|euro" in z or "|menge" in z)
        and "white-space:nowrap" not in z
    ]
    assert not ohne, "Zellen der Positionstabelle ohne nowrap:\n  " + "\n  ".join(ohne)
