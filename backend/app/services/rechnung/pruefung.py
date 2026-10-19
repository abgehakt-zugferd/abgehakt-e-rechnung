import os
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.invoice import Invoice, ValidationResult
from app.services import mustang, validator


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

    vr = ValidationResult(
        invoice_id=invoice.id,
        is_valid=len(errors) == 0 and (mustang_result is None or mustang_result["is_valid"]),
        errors=[{"code": e.code, "severity": e.severity, "message": e.message, "field": e.field} for e in errors],
        warnings=[{"code": w.code, "severity": w.severity, "message": w.message, "field": w.field} for w in warnings],
        mustang_output=mustang_result["raw"] if mustang_result else None,
    )
    db.add(vr)
    return vr
