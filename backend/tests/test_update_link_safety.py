"""Link-Prüfung (#120). Die Antwort kommt von UNSEREM Server, ist fuer das Tool
aber fremde Eingabe — ungeprueft gerendert waere der eigene Update-Endpunkt ein
Einschleusungsweg in jede Installation im Feld."""
import pytest

from app.services.update_check import ENDPOINT, safe_link

GUT = "https://abgehakt.app/changelog"


@pytest.mark.parametrize("boese", [
    "http://abgehakt.app/x",                    # kein https
    "javascript:alert(1)",                     # Schema-Angriff
    "data:text/html,<script>alert(1)</script>",
    "//evil.com/x",                            # schema-relativ, hat gar kein Schema
    "https://abgehakt.app@evil.com/x",          # Benutzerinfo-Trick
    "https://evil.abgehakt.app/x",              # Subdomain ist NICHT unser Host
    "https://abgehakt.app.angreifer.com/x",     # 'endet auf' waere hier durchgerutscht
    "https://abgehakt.app./x",                  # abschliessender Punkt
    "",
])
def test_boese_links_werden_verworfen(boese):
    assert safe_link(boese, endpoint="https://abgehakt.app/api/updates") == ""


def test_guter_link_bleibt():
    assert safe_link(GUT, endpoint="https://abgehakt.app/api/updates") == GUT


def test_ausgegeben_wird_die_neu_zusammengesetzte_url():
    """urlparse entfernt Steuerzeichen STILL — geprueft wuerde sonst das eine,
    ins href geschrieben das andere. Deshalb nie die Rohzeichenkette ausgeben."""
    roh = "https://abgehakt.app\n/changelog"
    ergebnis = safe_link(roh, endpoint="https://abgehakt.app/api/updates")
    assert "\n" not in ergebnis
    assert ergebnis == "https://abgehakt.app/changelog"


def test_homograph_wird_verworfen():
    # kyrillisches 'а' in 'аbgehakt.app'
    assert safe_link("https://аbgehakt.app/x", endpoint="https://abgehakt.app/api/updates") == ""


def test_endpunkt_ist_eine_konstante_und_kein_setting():
    """Ein per .env umbiegbarer Endpunkt waere in einer ausgelieferten
    Installation eine Einladung, das Tool auf einen fremden Server zeigen zu lassen."""
    from app.config import Settings
    assert ENDPOINT.startswith("https://")
    assert not hasattr(Settings(_env_file=None), "update_check_url")
