"""Die Update-Prüfung fragt die GitHub-Releases des eigenen Repos (#120, Nachtrag).

Vorher zeigte `ENDPOINT` auf `https://abgehakt.app/api/updates` — eine Gegenstelle,
die es nicht gibt und für die jemand dauerhaft einen Server betreiben müsste. Die
Releases-API liefert dasselbe, ohne Server: wer einen Release veröffentlicht, hat die
Prüfung bedient.

Zwei Dinge, die dabei nicht verloren gehen durften:
  1. **Eskalation.** Ein Sicherheits- oder Rechtshinweis muss weiter ein nicht
     wegklickbares Banner erzeugen können. GitHub kennt kein solches Feld, deshalb
     kommt es aus einer Zeile im Release-Text (`severity: security`).
  2. **Kein Verhalten aus der Antwort.** Auch die GitHub-Antwort ist fremde Eingabe:
     Links werden weiter neu zusammengesetzt und gegen eine Liste erlaubter Hosts
     geprüft.

Neu dazugekommen ist eine Eigenschaft, die vorher nicht ging: die Prüfung überträgt
**nichts** über die Installation mehr. Die alte Fassung hängte Version und Ausgabe als
Abfrageparameter an; eine statische Releases-Abfrage braucht das nicht.
"""
import json
from urllib.parse import urlparse

import httpx
import pytest

from app.services.update_check import (
    ENDPOINT,
    UpdateCheckError,
    fetch_update_info,
    safe_link,
)

REPO = "abgehakt-zugferd/abgehakt-e-rechnung"

RELEASE = {
    "tag_name": "v1.2.0",
    "name": "Version 1.2.0",
    "html_url": f"https://github.com/{REPO}/releases/tag/v1.2.0",
    "body": "Kleinunternehmer-Rechnungen sind jetzt möglich.",
    "prerelease": False,
    "draft": False,
}


def _transport(payload, status=200):
    def handler(request):
        handler.letzte_anfrage = request
        # content=iter([...]) ist Pflicht: eine MockTransport-Antwort mit fertigem
        # Inhalt wirft bei iter_raw() ein StreamConsumed (siehe test_update_fetch.py).
        return httpx.Response(
            status,
            content=iter([json.dumps(payload).encode("utf-8")]),
            headers={"content-type": "application/json"},
        )

    handler.letzte_anfrage = None
    return httpx.MockTransport(handler), handler


def _hole(payload, **kwargs):
    transport, handler = _transport(payload)
    return fetch_update_info("1.0.0", "frei", transport=transport, **kwargs), handler


def test_endpunkt_ist_die_releases_api_des_eigenen_repos():
    assert urlparse(ENDPOINT).hostname == "api.github.com"
    assert REPO in ENDPOINT
    assert "abgehakt.app" not in ENDPOINT


def test_release_wird_auf_die_felder_der_anwendung_abgebildet():
    info, _ = _hole(RELEASE)

    assert info.latest_version == "v1.2.0"
    assert info.url == RELEASE["html_url"]
    assert "1.2.0" in info.notice


def test_ohne_namen_traegt_der_hinweis_die_versionsnummer():
    info, _ = _hole({**RELEASE, "name": ""})

    assert info.notice


def test_dringlichkeit_kommt_aus_dem_release_text():
    info, _ = _hole({**RELEASE, "body": "severity: security\n\nLücke geschlossen."})

    assert info.severity == "security"


def test_unbekannte_dringlichkeit_faellt_auf_normal_zurueck():
    """Sonst entscheidet die Serverantwort über das Verhalten des Banners."""
    info, _ = _hole({**RELEASE, "body": "severity: weltuntergang"})

    assert info.severity == "normal"


def test_ohne_angabe_ist_die_dringlichkeit_normal():
    info, _ = _hole(RELEASE)

    assert info.severity == "normal"


def test_vorabversion_loest_keinen_hinweis_aus():
    """`/releases/latest` überspringt Vorabversionen bereits — verlassen wird sich
    darauf nicht, sonst hängt das Verhalten an einer fremden API-Zusage."""
    info, _ = _hole({**RELEASE, "prerelease": True})

    assert info.latest_version == ""


def test_freier_hinweis_kommt_aus_dem_release_text():
    """Die zweite Zone (eigener, immer schließbarer Hinweis) hätte mit GitHub als
    Quelle keine Herkunft mehr — sie bekommt sie aus derselben Kopfzeile wie die
    Dringlichkeit."""
    info, _ = _hole({
        **RELEASE,
        "body": f"hinweis: Es gibt jetzt eine begleitete Einrichtung.\n"
                f"hinweis-url: https://github.com/{REPO}/blob/main/SERVICES.md",
    })

    assert info.mitteilung == "Es gibt jetzt eine begleitete Einrichtung."
    assert info.mitteilung_url.endswith("SERVICES.md")


def test_hinweis_url_auf_fremdem_host_wird_verworfen():
    info, _ = _hole({
        **RELEASE,
        "body": "hinweis: Klick mich\nhinweis-url: https://evil.com/x",
    })

    assert info.mitteilung == "Klick mich"
    assert info.mitteilung_url == ""


def test_version_und_ausgabe_werden_nicht_uebertragen():
    """Der Datenschutz-Abschnitt im README steht und fällt damit."""
    _, handler = _hole(RELEASE)

    assert handler.letzte_anfrage.url.query == b""


def test_fehlende_felder_sind_kein_absturz():
    info, _ = _hole({})

    assert info.latest_version == ""


def test_antwort_die_kein_objekt_ist_wird_abgelehnt():
    transport, _ = _transport([1, 2, 3])
    with pytest.raises(UpdateCheckError):
        fetch_update_info("1.0.0", "frei", transport=transport)


def test_link_auf_die_release_seite_ueberlebt():
    """Die Releases liegen auf github.com, abgerufen wird von api.github.com —
    ein Vergleich nur gegen den Endpunkt-Host würde jeden Link verwerfen."""
    ziel = f"https://github.com/{REPO}/releases/tag/v1.2.0"

    assert safe_link(ziel) == ziel


@pytest.mark.parametrize("boese", [
    "https://evil.com/x",
    "https://github.com.angreifer.com/x",
    "https://evil.github.com.x.de/y",
    "http://github.com/x",
    "https://github.com@evil.com/x",
])
def test_fremde_hosts_werden_weiter_verworfen(boese):
    assert safe_link(boese) == ""
