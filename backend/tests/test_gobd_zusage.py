"""Die Oberfläche darf sich nicht selbst GoBD-Konformität bescheinigen (2026-08-09).

GoBD-Konformität ist eine Eigenschaft des **Verfahrens**, nicht eines Programms:
sie entsteht erst aus Software, Organisation, Verfahrensdokumentation und einer
Sicherung, die auch zurückgespielt wurde. Kein Programm kann sie allein herstellen,
also darf keines sie behaupten.

Bis heute stand `GoBD-KONFORM` als Abzeichen in der Seitenleiste, neben einem grünen
Punkt: wie ein Prüfsiegel, auf jedem Bildschirm. Das widersprach dem eigenen README,
das im Abschnitt „Grenzen" ausdrücklich sagt, dass `storage/` nicht atomar mit der
Datenbank gesichert wird. Wer die eigene Einschränkung in der Doku zugibt und in der
Oberfläche das Gegenteil behauptet, ist wettbewerbsrechtlich angreifbar; wichtiger:
es führt den Nutzer in die Irre, der sich auf das Abzeichen verlässt statt auf ein
Verfahren.

Erlaubt bleiben Funktionsnamen: „GoBD-Export" ist der Name einer Schaltfläche,
„GoBD-Archiv bis" ist ein Datum. Beide behaupten nichts über den Zustand des Betriebs.
"""
from pathlib import Path

import pytest

VORLAGEN = Path(__file__).resolve().parents[1] / "app" / "templates"

# Zusicherungen: Zustandsbehauptungen über den Betrieb.
VERBOTEN = ("GoBD-KONFORM", "GoBD-konform", "GoBD-gesichert", "GoBD-sicher",
            "revisionssicher", "revisionssichere")


def _alle_vorlagen() -> list[Path]:
    return sorted(VORLAGEN.rglob("*.html"))


def test_es_gibt_ueberhaupt_vorlagen_zu_pruefen():
    """Ohne diese Schranke wäre die Suche unten auch dann grün, wenn der Pfad
    falsch ist und gar nichts gelesen wird."""
    assert len(_alle_vorlagen()) >= 10, VORLAGEN


@pytest.mark.parametrize("begriff", VERBOTEN)
def test_keine_vorlage_bescheinigt_sich_gobd_konformitaet(begriff):
    treffer = [f"{p.relative_to(VORLAGEN)}: {zeile.strip()}"
               for p in _alle_vorlagen()
               for zeile in p.read_text(encoding="utf-8").splitlines()
               if begriff in zeile]

    assert not treffer, (
        f"'{begriff}' ist eine Zusicherung, die kein Programm allein einlösen kann. "
        "Funktion benennen (GoBD-Export, Aufbewahrung 8 Jahre) statt Zustand behaupten:\n"
        + "\n".join(treffer)
    )


def test_der_funktionsname_gobd_export_bleibt_erlaubt():
    """Gegenprobe: die Regel oben darf nicht so weit greifen, dass sie die
    Schaltfläche mitverbietet — sonst repariert der Nächste sie, indem er die
    Funktion umbenennt statt die Behauptung zu streichen."""
    texte = "\n".join(p.read_text(encoding="utf-8") for p in _alle_vorlagen())

    assert "GoBD-Export" in texte
