import hashlib
import os
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.invoice import Invoice, ValidationResult
from app.services import mustang, validator
from app.zeit import jetzt


def xml_hash(xml: str | None) -> str | None:
    """SHA-256 des gespeicherten zugferd_xml: bindet ein Prüfergebnis an genau dieses XML."""
    return hashlib.sha256(xml.encode("utf-8")).hexdigest() if xml else None


def befund_als_eintrag(befund: dict) -> dict:
    """Ein Mustang-Befund als Eintrag in errors/warnings des Prüfergebnisses.

    Code MUSTANG_<Regel>; ohne Kennung MUSTANG_FEHLER bzw. MUSTANG_WARNUNG.
    """
    fehler = befund["schwere"] == "error"
    fallback = "FEHLER" if fehler else "WARNUNG"
    return {
        "code": f"MUSTANG_{befund['regel'] or fallback}",
        "severity": befund["schwere"],
        "message": befund["text"],
        "field": "",
    }


def _eintraege(issues) -> list[dict]:
    return [{"code": i.code, "severity": i.severity, "message": i.message, "field": i.field}
            for i in issues]


def _mustang_eintraege(befunde: list[dict], schwere: str) -> list[dict]:
    return [befund_als_eintrag(b) for b in befunde if b["schwere"] == schwere]


def run_validation(db: Session, invoice: Invoice, company: Company) -> ValidationResult:
    """Regelprüfung (§ 14 UStG) + optionale Mustang-Prüfung der bereits erzeugten XML.

    Der Mustang-Zweig läuft nur mit `invoice.zugferd_xml`; ein Entwurf hat keine, dort
    ist das ein reiner In-Prozess-Regellauf ohne Subprocess. Legt das
    `ValidationResult` an, committet aber NICHT — das entscheidet der Aufrufer.
    """
    errors, warnings = validator.validate_invoice(invoice, company)

    mustang_result = None
    if invoice.zugferd_xml:
        fd, tmp_name = tempfile.mkstemp(suffix=".xml")
        xml_path = Path(tmp_name)
        try:
            os.write(fd, invoice.zugferd_xml.encode("utf-8"))
            os.close(fd)
            mustang_result = mustang.validate(xml_path)
        finally:
            xml_path.unlink(missing_ok=True)

    befunde = mustang.befunde_von(mustang_result) if mustang_result else []
    vr = ValidationResult(
        invoice_id=invoice.id,
        is_valid=len(errors) == 0 and (
            mustang_result is None or mustang.ist_gueltige_e_rechnung(mustang_result)
        ),
        # Mustang-Befunde gehören ins Protokoll (#299). Warnungen sperren hier nichts;
        # is_valid hängt weiter nur an der Mustang-Wertung, nicht an diesen Listen.
        errors=_eintraege(errors) + _mustang_eintraege(befunde, "error"),
        warnings=_eintraege(warnings) + _mustang_eintraege(befunde, "warning"),
        mustang_output=mustang_result["raw"] if mustang_result else None,
        xml_sha256=xml_hash(invoice.zugferd_xml),
        anlass="pruefung",
    )
    db.add(vr)
    return vr


def finalisierung_protokollieren(db: Session, invoice: Invoice, company: Company,
                                 mustang_result: dict, bestaetigte: list[str] | None) -> ValidationResult:
    """Prüfergebnis der Finalisierung: Momentaufnahme des gestellten XML.

    Hält die Mustang-Befunde fest, die beim Einbetten gemessen wurden (kein zweiter
    Mustang-Lauf). Wurde trotz Warnung finalisiert, stehen die übergangenen
    Regelkennungen und der Zeitpunkt der Bestätigung im Ergebnis (GoBD: was wurde
    wann bestätigt; einen Benutzer gibt es nicht). Committet nicht.
    """
    errors, warnings = validator.validate_invoice(invoice, company)
    befunde = mustang.befunde_von(mustang_result)
    eintraege = _eintraege(warnings) + _mustang_eintraege(befunde, "warning")
    jetzt_ = jetzt()
    if bestaetigte:
        eintraege.append({
            "code": "MUSTANG_WARNUNG_BESTAETIGT", "severity": "warning", "field": "",
            "message": "Trotz Warnung finalisiert. Übergangene Regeln: " + ", ".join(bestaetigte),
        })
    vr = ValidationResult(
        invoice_id=invoice.id,
        is_valid=mustang.ist_gueltige_e_rechnung(mustang_result),
        errors=_eintraege(errors) + _mustang_eintraege(befunde, "error"),
        warnings=eintraege,
        mustang_output=mustang_result.get("raw"),
        validated_at=jetzt_,
        xml_sha256=xml_hash(invoice.zugferd_xml),
        anlass="finalisierung",
        bestaetigte_regeln=list(bestaetigte) if bestaetigte else None,
        bestaetigt_am=jetzt_ if bestaetigte else None,
    )
    db.add(vr)
    return vr
