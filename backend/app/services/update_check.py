"""
Update-Prüfung (#120): holt eine Versions-JSON vom eigenen Endpunkt und prüft sie.

Kennt weder Datenbank noch Templates. Der Abruf erfolgt AUSSCHLIESSLICH durch
Nutzerklick — es gibt hier bewusst keinen Scheduler und keinen Start-Hook.
"""
import json
from urllib.parse import urlparse, urlunparse

import httpx
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict, Field, ValidationError

# Einzige Stelle, an der die Adresse steht. BEWUSST keine Einstellung:
# ein umbiegbarer Endpunkt wäre in einer ausgelieferten Installation ein Angriffsweg.
#
# Quelle sind die Releases des eigenen Repos — kein selbst betriebener Server, der
# jahrelang laufen müsste, damit eine Installation im Feld ihre Version prüfen kann.
# Wer einen Release veröffentlicht, hat die Prüfung bedient.
REPO = "abgehakt-zugferd/abgehakt-e-rechnung"
ENDPOINT = f"https://api.github.com/repos/{REPO}/releases/latest"

# Abgerufen wird von api.github.com, die Release-Seite liegt aber auf github.com.
# Ein Vergleich nur gegen den Endpunkt-Host würde deshalb JEDEN Link verwerfen.
LINK_HOSTS = {"github.com"}

SEVERITIES = {"normal", "security", "legal"}
ESCALATED = {"security", "legal"}

# Kopfzeilen im Release-Text. GitHub kennt weder Dringlichkeit noch freien Hinweis;
# beides muss aber weiter möglich sein (eskaliertes Banner, eigene Hinweis-Zone).
# Nur die ersten Zeilen zählen — sonst löst ein "severity:" mitten im Änderungstext
# ein nicht wegklickbares Banner aus.
KOPFZEILEN = 6

MAX_BYTES = 65536
TIMEOUT = httpx.Timeout(10.0, connect=5.0, read=10.0)


class UpdateCheckError(Exception):
    """Prüfung nicht möglich. Fachlicher Fehler, kein Absturz."""


class UpdateInfo(BaseModel):
    """Geprüfte Antwort. `extra='ignore'`, damit ein neueres Serverfeld eine
    ältere Installation nicht umbringt."""

    model_config = ConfigDict(extra="ignore")

    latest_version: str = Field(default="", max_length=32)
    severity: str = Field(default="normal", max_length=16)
    notice: str = Field(default="", max_length=500)
    url: str = Field(default="", max_length=300)
    mitteilung: str = Field(default="", max_length=500)
    mitteilung_url: str = Field(default="", max_length=300)


def safe_link(raw: str, endpoint: str = ENDPOINT) -> str:
    """Gibt eine sichere, NEU ZUSAMMENGESETZTE URL zurück — oder '' (verworfen).

    Nie die Rohzeichenkette durchreichen: urlparse entfernt Steuerzeichen still,
    sonst würde das eine geprüft und das andere ins href geschrieben.
    """
    if not raw:
        return ""
    p = urlparse(raw)
    if p.scheme != "https":          # erschlägt javascript:, data:, //evil.com
        return ""
    if p.username or p.password:     # https://abgehakt.app@evil.com
        return ""
    host = p.hostname
    if not host:
        return ""
    erlaubt = {urlparse(endpoint).hostname} | LINK_HOSTS
    if host not in erlaubt:                  # exakt, nicht 'endet auf'
        return ""
    try:
        if host.encode("idna").decode("ascii") != host:   # Homographen
            return ""
    except UnicodeError:
        return ""
    return urlunparse(("https", host, p.path, "", p.query, ""))


def fetch_update_info(
    version: str,
    edition: str,
    *,
    endpoint: str = ENDPOINT,
    transport=None,
) -> UpdateInfo:
    """Holt den letzten Release. Wirft UpdateCheckError, wenn irgendetwas nicht stimmt.

    `version` und `edition` werden **nicht übertragen**: die Releases-Antwort hängt
    nicht davon ab, und was nicht gesendet wird, kann auch nicht ausgewertet werden.
    Sie bleiben in der Signatur, weil der Aufrufer sie hat und eine spätere Quelle
    sie wieder brauchen könnte.
    """
    headers = {"Accept": "application/vnd.github+json", "Accept-Encoding": "identity"}
    try:
        # follow_redirects=False ist httpx-Default und bleibt es: eine Umleitung
        # auf einen fremden Host soll schlicht ein Fehler sein.
        with httpx.Client(timeout=TIMEOUT, transport=transport, follow_redirects=False) as client:
            with client.stream("GET", endpoint, headers=headers) as response:
                if response.status_code != 200:
                    raise UpdateCheckError(f"HTTP {response.status_code}")
                encoding = response.headers.get("content-encoding", "").strip().lower()
                if encoding and encoding != "identity":
                    # Was wir nicht angefordert haben, entpacken wir nicht.
                    raise UpdateCheckError("Antwort ist komprimiert, obwohl nicht angefordert")
                buf = bytearray()
                for chunk in response.iter_raw():   # RAW = Leitungsbytes
                    buf += chunk
                    if len(buf) > MAX_BYTES:
                        raise UpdateCheckError("Antwort zu groß")
    except httpx.HTTPError as exc:
        raise UpdateCheckError(f"Verbindung fehlgeschlagen: {exc}") from exc

    try:
        data = json.loads(bytes(buf).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise UpdateCheckError("Antwort ist kein gültiges JSON") from exc
    if not isinstance(data, dict):
        raise UpdateCheckError("Antwort ist kein Objekt")

    try:
        info = UpdateInfo.model_validate(_aus_release(data))
    except ValidationError as exc:
        # Sonst schlaegt eine rohe ValidationError am Aufrufer vorbei durch:
        # der faengt UpdateCheckError, und der Nutzer saehe einen 500.
        raise UpdateCheckError("Antwort passt nicht zum erwarteten Schema") from exc
    return info.model_copy(update={
        "severity": info.severity if info.severity in SEVERITIES else "normal",
        "url": safe_link(info.url, endpoint),
        "mitteilung_url": safe_link(info.mitteilung_url, endpoint),
    })


def _kopfzeile(body: str, schluessel: str) -> str:
    """Liest `schluessel: wert` aus den ersten Zeilen des Release-Textes."""
    for zeile in (body or "").splitlines()[:KOPFZEILEN]:
        marke, trenner, wert = zeile.strip().partition(":")
        if trenner and marke.strip().lower() == schluessel:
            return wert.strip()
    return ""


def _aus_release(data: dict) -> dict:
    """GitHub-Release → die Felder, die die Anwendung kennt.

    Entwurf und Vorabversion ergeben ein leeres Ergebnis: `/releases/latest`
    überspringt beide bereits, aber das Verhalten der Anwendung darf nicht an einer
    fremden API-Zusage hängen.
    """
    if data.get("draft") or data.get("prerelease"):
        return {}
    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        return {}

    body = str(data.get("body") or "")
    name = str(data.get("name") or "").strip()
    return {
        "latest_version": tag[:32],
        "notice": (name or f"Version {tag.lstrip('vV')} ist verfügbar.")[:500],
        "url": str(data.get("html_url") or "")[:300],
        "severity": _kopfzeile(body, "severity")[:16],
        "mitteilung": _kopfzeile(body, "hinweis")[:500],
        "mitteilung_url": _kopfzeile(body, "hinweis-url")[:300],
    }


def is_newer_version(latest: str, current: str) -> bool:
    """True, wenn `latest` echt neuer als `current` ist.

    Fail-safe: Was sich nicht als Version lesen lässt (inkl. 'dev'), löst
    keinen Hinweis aus.
    """
    try:
        return Version(latest.lstrip("vV")) > Version(current.lstrip("vV"))
    except InvalidVersion:
        return False
