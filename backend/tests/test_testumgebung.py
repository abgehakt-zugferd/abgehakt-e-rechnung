"""
Die Testsuite darf nicht in das echte Archiv schreiben.

`docker-compose.yml` hängt `./storage` in den Container. Wer der Anleitung folgt
und die Tests gegen den Entwicklungsstack laufen lässt (CONTRIBUTING.md), hatte
danach erfundene Rechnungsnummern zwischen seinen echten Belegen liegen:
`RE-E2E-…`, `RE-SEND-…`, dazu liegengebliebene Zwischenstufen `_visual.pdf` und
`_pdfa.pdf`, die kein Aufräumen erwischt hat.

Das ist dieselbe Regel, aus der ein Vorschau-PDF dort nichts zu suchen hat:
`storage/pdfs/` ist das GoBD-Archiv. Was dort liegt, ist später von einem echten
Beleg nicht mehr zu unterscheiden — und gestellte Rechnungen lassen sich nicht
löschen, auch die erfundenen nicht.

Durchgesetzt wird das von der Fixture `test_archiv` in `conftest.py`. Dieser
Test ist ihr Wächter: verschwindet sie, wird er rot.
"""
from pathlib import Path

from app.config import get_settings

ECHTES_ARCHIV = Path("/app/storage")


def test_die_suite_schreibt_nicht_in_das_echte_archiv():
    pfad = get_settings().storage_path

    assert pfad != ECHTES_ARCHIV, (
        "Die Tests schreiben in das Archivverzeichnis der Installation. "
        "Erwartet wird ein Wegwerf-Verzeichnis (Fixture `test_archiv`)."
    )
    assert ECHTES_ARCHIV not in pfad.parents, (
        f"Das Testarchiv {pfad} liegt innerhalb des echten Archivs."
    )


def test_das_testarchiv_hat_die_erwarteten_unterverzeichnisse():
    """Ohne `pdfs/` und `xml/` scheitern die Tests, die einen Beleg erzeugen —
    im echten Archiv gibt es beide, im Wegwerf-Verzeichnis muss die Fixture sie
    anlegen."""
    pfad = get_settings().storage_path

    assert (pfad / "pdfs").is_dir()
    assert (pfad / "xml").is_dir()
