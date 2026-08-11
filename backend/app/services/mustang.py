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


def _run(args: list[str]) -> tuple[str, str, int]:
    cmd = ["java", "-Xmx512m", "-Dfile.encoding=UTF-8", "-jar", JAR] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=ZEITGRENZE)
    except subprocess.TimeoutExpired:
        # Eine überschrittene Zeitgrenze ist ein Prüfergebnis, kein Programmabsturz.
        # Auf einem betagten Rechner oder unter Last braucht die JVM länger als eine
        # Minute; ließe man `TimeoutExpired` durchfliegen, umginge sie im
        # Finalisieren die gesamte Aufräumlogik (kein `unlink`, kein `db.rollback()`)
        # und hinterließe eine verwaiste PDF mit echter Rechnungsnummer im
        # GoBD-Verzeichnis. Als Fehlschlag gemeldet, greift der normale
        # fail-closed-Weg: Rechnung bleibt Entwurf, Dateien weg, ein Satz statt 500.
        # `[error]` steht bewusst drin, damit auch `_no_errors` es als Fehler sieht.
        return "", (f"[error] Zeitgrenze von {ZEITGRENZE} Sekunden überschritten. "
                    "Der Rechner war vermutlich ausgelastet — bitte erneut versuchen."), 124
    return result.stdout, result.stderr, result.returncode


def combine(pdf_path: Path, xml_path: Path, out_path: Path, profile: str = "EN16931") -> bool:
    profile_flag = _profile_flag(profile)
    out = Path(out_path)
    # Alte Datei entfernen, damit ein stiller Fehlschlag sie nicht maskiert.
    out.unlink(missing_ok=True)
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
    return rc == 0 and out.exists() and out.stat().st_size > 0


def validate(xml_or_pdf_path: Path) -> dict:
    stdout, stderr, rc = _run([
        "--action", "validate",
        "--source", str(xml_or_pdf_path),
        "--no-notices",
    ])
    output = stdout + stderr
    return {
        "is_valid": rc == 0 and _no_errors(output),
        "raw": output,
        "errors": _extract_issues(output, "error"),
        "warnings": _extract_issues(output, "warning"),
    }


def extract_xml(pdf_path: Path, out_xml: Path) -> bool:
    _, _, rc = _run([
        "--action", "extract",
        "--source", str(pdf_path),
        "--out", str(out_xml),
    ])
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
