"""
Wrapper für die Mustang CLI. Ruft die JAR über subprocess auf.
Version + SHA-256 stehen im `backend/Dockerfile` — hier bewusst keine Nummer.
"""
import subprocess
import json
import re
from pathlib import Path
from app.config import get_settings

settings = get_settings()
JAR = str(settings.mustang_jar)


ZEITGRENZE = 60


class MustangNichtAusfuehrbar(Exception):
    """Mustang konnte nicht laufen (JAR fehlt, Java fehlt, Zeitgrenze): nichts gemessen.

    Das ist etwas anderes als „ungueltig". Wer es wie ein leeres `is_valid=False`
    behandelt, verwechselt „nicht gemessen" mit „XML fehlerhaft".
    """


def _run(args: list[str]) -> tuple[str, str, int]:
    if not jar_available():
        raise MustangNichtAusfuehrbar(f"Mustang-JAR fehlt ({JAR}).")
    cmd = ["java", "-Xmx512m", "-Dfile.encoding=UTF-8", "-jar", JAR] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=ZEITGRENZE)
    except subprocess.TimeoutExpired as fehler:
        # Eine überschrittene Zeitgrenze ist ein Prüfergebnis, kein Programmabsturz.
        # Auf einem betagten Rechner oder unter Last braucht die JVM länger als eine
        # Minute; ließe man `TimeoutExpired` durchfliegen, umginge sie im
        # Finalisieren die gesamte Aufräumlogik (kein `unlink`, kein `db.rollback()`)
        # und hinterließe eine verwaiste PDF mit echter Rechnungsnummer im
        # GoBD-Verzeichnis. Als „nicht ausführbar" gemeldet, greift der normale
        # fail-closed-Weg: Rechnung bleibt Entwurf, Dateien weg, ein Satz statt 500.
        raise MustangNichtAusfuehrbar(
            f"Zeitgrenze von {ZEITGRENZE} Sekunden überschritten. "
            "Der Rechner war vermutlich ausgelastet — bitte erneut versuchen.") from fehler
    except OSError as fehler:
        raise MustangNichtAusfuehrbar(f"Java nicht startbar ({fehler}).") from fehler
    return result.stdout, result.stderr, result.returncode


def combine(pdf_path: Path, xml_path: Path, out_path: Path, profile: str = "EN16931") -> bool:
    profile_flag = _profile_flag(profile)
    out = Path(out_path)
    # Alte Datei entfernen, damit ein stiller Fehlschlag sie nicht maskiert.
    out.unlink(missing_ok=True)
    try:
        stdout, stderr, rc = _run([
            "--action", "combine",
            "--source", str(pdf_path),
            "--source-xml", str(xml_path),
            "--out", str(out_path),
            "--format", "zf",
            "--version", "2",
            "--profile", profile_flag,
            # Ohne diese Flags fragt Mustang interaktiv auf stdin nach Anhängen und
            # Format; ohne stdin → NullPointerException, keine Ausgabedatei, aber rc=0.
            "--no-additional-attachments",
        ])
    except MustangNichtAusfuehrbar:
        return False
    return rc == 0 and out.exists() and out.stat().st_size > 0


def validate(xml_or_pdf_path: Path) -> dict:
    """Mustang-Prüfung. `nicht_ausfuehrbar` trennt „nicht gemessen" von „ungültig".

    Bei `nicht_ausfuehrbar=True` ist `is_valid` immer False, `grund` nennt die
    Ursache und steht auch in `raw`/`errors`, damit jede Anzeige sie zeigt.
    """
    try:
        stdout, stderr, rc = _run([
            "--action", "validate",
            "--source", str(xml_or_pdf_path),
            "--no-notices",
        ])
    except MustangNichtAusfuehrbar as fehler:
        grund = str(fehler)
        # `[error]` steht bewusst drin, damit auch `_no_errors` es als Fehler sieht.
        meldung = f"[error] Mustang nicht ausführbar, nicht gemessen: {grund}"
        return {"is_valid": False, "nicht_ausfuehrbar": True, "grund": grund,
                "raw": meldung, "errors": [meldung], "warnings": []}
    output = stdout + stderr
    return {
        "is_valid": rc == 0 and _no_errors(output),
        "nicht_ausfuehrbar": False,
        "grund": "",
        "raw": output,
        "errors": _extract_issues(output, "error"),
        "warnings": _extract_issues(output, "warning"),
    }


def ist_gueltige_e_rechnung(result: dict) -> bool:
    """Ob ein Mustang-validate-Ergebnis eine gültige E-Rechnung belegt.

    Eine Stelle für Prüfseite, Finalisieren und Versand. Die Prüfseite übergibt
    reine XML, Finalisieren/Versand das kombinierte PDF; Mustang schreibt
    „XML:valid“ in beiden Fällen nur bei bestandener XML-Prüfung. Bare PDF/A
    ohne XML kann PDF/A-konform wirken, liefert aber kein „XML:valid“.
    """
    if result.get("nicht_ausfuehrbar"):
        return False
    return bool(result.get("is_valid")) and "XML:valid" in (result.get("raw") or "")


def extract_xml(pdf_path: Path, out_xml: Path) -> bool:
    try:
        _, _, rc = _run([
            "--action", "extract",
            "--source", str(pdf_path),
            "--out", str(out_xml),
        ])
    except MustangNichtAusfuehrbar:
        return False
    return rc == 0


def jar_available() -> bool:
    jar = Path(JAR)
    return jar.exists()


def _profile_flag(profile: str) -> str:
    mapping = {
        "EN16931": "E",
        "BASIC": "B",
        "XRECHNUNG": "EN16931",
        "EXTENDED": "EX",
    }
    return mapping.get(profile, "E")


def _no_errors(output: str) -> bool:
    # Nur explizite [error]- oder [fehler]-Marker zählen — "0 errors" in
    # Erfolgszusammenfassungen enthält "error" als Substring und darf nicht
    # als Fehler gewertet werden.
    return not re.search(r'\[(error|fehler)\]', output, re.IGNORECASE)


def _extract_issues(output: str, severity: str) -> list[str]:
    pattern = re.compile(rf"\[{severity}\].*", re.IGNORECASE)
    return [m.group() for m in pattern.finditer(output)]
