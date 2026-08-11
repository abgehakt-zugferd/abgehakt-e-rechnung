"""Abruf (#120). KEINE echten Netzverbindungen — immer MockTransport."""
import gzip
import json

import httpx
import pytest

from app.services.update_check import (
    ENDPOINT,
    MAX_BYTES,
    REPO,
    UpdateCheckError,
    fetch_update_info,
)

EP = ENDPOINT

# Quelle ist seit dem Wechsel auf GitHub ein Release-Objekt, kein flaches
# Versions-JSON mehr. Wer hier ein altes `{"latest_version": …}` einsetzt, testet
# nichts: die Abbildung ignoriert es und liefert leere Felder — der Test wäre grün
# aus dem falschen Grund. Deshalb baut jeder Fall auf RELEASE auf.
RELEASE = {
    "tag_name": "1.1.0",
    "name": "Version 1.1.0",
    "html_url": f"https://github.com/{REPO}/releases/tag/1.1.0",
    "body": "",
    "prerelease": False,
    "draft": False,
}


def _client(handler):
    return httpx.MockTransport(handler)


def _stream(data: bytes, headers: dict | None = None) -> httpx.Response:
    """Antwort, die sich wirklich streamen laesst.

    WICHTIG: `content=iter([...])`, NICHT `content=`/`json=`. Eine
    MockTransport-Antwort mit bereits fertigem Inhalt wirft bei `iter_raw()`
    ein `StreamConsumed` — der Test waere dann rot aus dem falschen Grund.
    Gemessen: nur die Iterator-Form ist streambar.
    """
    return httpx.Response(200, content=iter([data]), headers=headers or {})


def _ok(payload: dict):
    def handler(request):
        return _stream(json.dumps(payload).encode())
    return _client(handler)


def test_abruf_verraet_nichts_ueber_die_installation():
    """Früher hingen Version und Ausgabe als Abfrageparameter dran. Die
    Releases-Antwort hängt nicht davon ab — und was nicht gesendet wird, kann auch
    nicht ausgewertet werden."""
    gesehen = {}

    def handler(request):
        gesehen["query"] = request.url.query
        gesehen["accept_encoding"] = request.headers.get("accept-encoding")
        return _stream(json.dumps(RELEASE).encode())

    fetch_update_info("1.0.0", "free", endpoint=EP, transport=_client(handler))
    assert gesehen["query"] == b""
    # identity: wir laden die Gegenseite gar nicht erst zum Komprimieren ein
    assert gesehen["accept_encoding"] == "identity"


def test_gzip_bombe_wird_abgewiesen():
    """48 KB gzip wurden im Versuch zu 50 MB in EINEM Chunk. Wer entpackte Bytes
    zaehlt, kommt immer zu spaet — deshalb zaehlen wir Leitungsbytes und lehnen
    nicht angeforderte Kompression rundweg ab."""
    blob = gzip.compress(b"A" * 50_000_000)

    def handler(request):
        return _stream(blob, headers={"Content-Encoding": "gzip"})

    with pytest.raises(UpdateCheckError):
        fetch_update_info("1.0.0", "free", endpoint=EP, transport=_client(handler))


def test_zu_grosse_unkomprimierte_antwort_wird_abgebrochen():
    riesig = json.dumps({"latest_version": "1.1.0", "notice": "x" * (MAX_BYTES + 1000)})

    def handler(request):
        return _stream(riesig.encode())

    with pytest.raises(UpdateCheckError):
        fetch_update_info("1.0.0", "free", endpoint=EP, transport=_client(handler))


def test_kaputtes_json():
    def handler(request):
        return _stream(b"{nicht json")

    with pytest.raises(UpdateCheckError):
        fetch_update_info("1.0.0", "free", endpoint=EP, transport=_client(handler))


def test_fehlerstatus():
    def handler(request):
        return httpx.Response(503)

    with pytest.raises(UpdateCheckError):
        fetch_update_info("1.0.0", "free", endpoint=EP, transport=_client(handler))


def test_netzfehler():
    def handler(request):
        raise httpx.ConnectError("kein Netz")

    with pytest.raises(UpdateCheckError):
        fetch_update_info("1.0.0", "free", endpoint=EP, transport=_client(handler))


def test_unbekannte_einstufung_wird_normal():
    info = fetch_update_info(
        "1.0.0", "free", endpoint=EP,
        transport=_ok({**RELEASE, "body": "severity: weltuntergang"}),
    )
    assert info.severity == "normal"


def test_fremder_link_wird_geleert():
    info = fetch_update_info(
        "1.0.0", "free", endpoint=EP,
        transport=_ok({**RELEASE,
                       "html_url": "https://evil.com/x",
                       "body": "hinweis: hier\nhinweis-url: https://evil.com/shop"}),
    )
    assert info.latest_version == "1.1.0", "sonst prüft der Test gar keinen Link"
    assert info.url == ""
    assert info.mitteilung_url == ""


@pytest.mark.parametrize("feld,wert", [
    ("name", "x" * 600),          # ueber der Feldgrenze von UpdateInfo
    ("tag_name", 123),            # falscher Typ
    ("html_url", ["kein", "string"]),
])
def test_ausreisser_im_release_kippen_die_pruefung_nicht(feld, wert):
    """Eine pydantic ValidationError darf am Aufrufer nicht vorbeifallen: der
    Router faengt nur UpdateCheckError, der Nutzer saehe sonst einen 500. Die
    Abbildung kappt deshalb auf die Feldgrenzen und erzwingt Zeichenketten —
    geprueft wird hier, dass sie das auch tut und nicht nur nicht abstuerzt."""
    info = fetch_update_info(
        "1.0.0", "free", endpoint=EP, transport=_ok({**RELEASE, feld: wert}),
    )
    assert len(info.notice) <= 500
    assert len(info.latest_version) <= 32
    assert len(info.url) <= 300


def test_dismissible_aus_der_antwort_wird_ignoriert():
    """Spec §7.1: Die Gegenseite liefert Daten, NIEMALS Verhalten. Ein
    `dismissible: true` neben `severity: security` darf den eskalierten,
    nicht schliessbaren Zustand nicht aufweichen — sonst koennte eine
    manipulierte Antwort einen Gesetzeshinweis wegklickbar machen."""
    info = fetch_update_info(
        "1.0.0", "free", endpoint=EP,
        transport=_ok({**RELEASE, "body": "severity: security",
                       "dismissible": True}),
    )
    assert not hasattr(info, "dismissible"), "das Feld darf gar nicht erst ankommen"

    # und die Anzeigelogik entscheidet allein
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from app.services.update_banner import compute_banner

    b = compute_banner(
        SimpleNamespace(
            update_latest_version=info.latest_version, update_severity=info.severity,
            update_notice=info.notice, update_url=info.url,
            update_mitteilung_text="", update_mitteilung_url="",
            update_dismissed_version=None, update_snoozed_until=None,
            update_last_checked_at=None, update_last_attempt_at=None,
        ),
        "1.0.0", datetime.now(timezone.utc),
    )
    assert b.kind == "escalated"
    assert b.dismissible is False


def test_unbekannte_felder_kippen_nichts():
    """Eine aeltere Installation muss eine neuere Antwort ueberleben."""
    info = fetch_update_info(
        "1.0.0", "free", endpoint=EP,
        transport=_ok({**RELEASE, "voellig_neues_feld": {"a": 1}}),
    )
    assert info.latest_version == "1.1.0"
