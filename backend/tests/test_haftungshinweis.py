"""Der Haftungshinweis steht dort, wo er gelesen wird: in der Ersteinrichtung.

Bisher stand er ausschließlich in README und CONTRIBUTING. Wer die Anwendung
benutzt, ohne je eine Markdown-Datei geöffnet zu haben — also der Normalfall —,
sah keinen einzigen Hinweis darauf, dass das Programm weder Korrektheit zusagt
noch Steuerberatung ersetzt.

`/setup` ist die einzige Seite, die JEDE Installation zwingend einmal durchläuft
(`test_setup_wizard.py`: uneingerichtet ⇒ Weiterleitung dorthin). Der Seitenfuß
wäre die falsche Stelle: was überall steht, wird nirgends gelesen — dieselbe
Überlegung, aus der der Pro-Hinweis nicht ins Compliance-Banner darf.

Zwei Hälften, die nicht auseinanderfallen dürfen:
  1. keine Zusage auf fehlerfreie Arbeit des Programms,
  2. kein Ersatz für Steuerberatung.
Ein Hinweis, der nur eine davon nennt, ist der wahrscheinliche Rückschritt —
deshalb prüft der zweite Test beide einzeln.
"""
import re

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company


def _uneingerichtet(pg_session):
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    firma.setup_completed_at = None
    pg_session.commit()


def _setup_seite(pg_session) -> str:
    _uneingerichtet(pg_session)
    app.dependency_overrides[get_db] = lambda: pg_session
    try:
        antwort = TestClient(app, follow_redirects=False).get("/setup")
        assert antwort.status_code == 200
        return antwort.text
    finally:
        app.dependency_overrides.clear()


def _hinweisblock(html: str) -> str:
    """Nur der markierte Block — nicht die restliche Seite.

    Sonst würde der Test auch dann bestehen, wenn die Begriffe zufällig
    woanders auf der Seite stehen.
    """
    treffer = re.search(
        r"<(?P<tag>[a-z]+)[^>]*\sdata-haftungshinweis[^>]*>(?P<inhalt>.*?)</(?P=tag)>",
        html,
        re.S | re.I,
    )
    assert treffer, "Kein Block mit data-haftungshinweis auf /setup gefunden."
    return treffer.group("inhalt")


def test_ersteinrichtung_zeigt_den_haftungshinweis(pg_session):
    assert _hinweisblock(_setup_seite(pg_session)).strip()


def test_hinweis_nennt_beide_haelften(pg_session):
    block = _hinweisblock(_setup_seite(pg_session)).lower()

    assert "steuerberatung" in block, (
        "Der Hinweis muss sagen, dass das Programm keine Steuerberatung ersetzt."
    )
    assert "gewähr" in block or "gewaehr" in block, (
        "Der Hinweis muss sagen, dass für die Richtigkeit der Ergebnisse nicht "
        "eingestanden wird."
    )


def test_hinweis_ist_nicht_wegklickbar(pg_session):
    """Kein Schließen-Knopf, kein Formular: er soll bei jedem Aufruf der
    Ersteinrichtung dastehen, auch beim zweiten."""
    block = _hinweisblock(_setup_seite(pg_session)).lower()

    assert "<form" not in block
    assert "<button" not in block
