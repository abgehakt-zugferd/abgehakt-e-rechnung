"""
GoBD-Schutz der Kundenstammdaten, erzwungen auf Session-Ebene — kein Codepfad
(Router, Skript, SQLAlchemy-Shell) kann ihn umgehen.

Regel (docs/ARCHITEKTUR.md, „Kritische Regeln — niemals brechen"):
  - Kunden werden NIE hard-gelöscht — nur `deleted_at` setzen (Soft-Delete).

Analog booking_guard/invoice_guard und wie diese VOR register_audit_listeners()
registrieren: wirft der Guard erst nach dem Audit-before_flush, blieben dessen
Pending-Einträge in session.info liegen und würden als Geister-Audit-Zeilen
geschrieben.
"""
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.customer import Customer

_registered = False


class CustomerDeleteError(RuntimeError):
    """Verstoß gegen die GoBD-Aufbewahrung der Kundenstammdaten (Hard-Delete)."""


def _before_flush(session: Session, flush_context, instances) -> None:
    for obj in session.deleted:
        if isinstance(obj, Customer):
            raise CustomerDeleteError(
                "Kunden dürfen nicht gelöscht werden (GoBD) — "
                "stattdessen deleted_at setzen (Soft-Delete)."
            )


def register_customer_guard() -> None:
    """Guard global an die Session-Klasse hängen. Idempotent."""
    global _registered
    if _registered:
        return
    event.listen(Session, "before_flush", _before_flush)
    _registered = True
