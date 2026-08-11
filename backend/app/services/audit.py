"""
GoBD: Automatisches Audit-Log (Tabelle audit_log) via SQLAlchemy-Events.

Dieser Teil: Serialisierung von Spaltenwerten in JSON-taugliche Typen.
Die Event-Listener folgen in register_audit_listeners() (Task 3).
"""
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import event, inspect as sa_inspect, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import LoaderCallableStatus

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import AuditLog, Invoice


def to_jsonable(value):
    """Spaltenwert in einen JSON-tauglichen Typ wandeln (für JSON-Spalten old/new_values)."""
    # LoaderCallableStatus.NO_VALUE means the value wasn't loaded/committed to the DB
    if isinstance(value, LoaderCallableStatus) or value is LoaderCallableStatus.NO_VALUE:
        return None
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def snapshot(obj) -> dict:
    """Alle Spaltenwerte eines ORM-Objekts als JSON-taugliches Dict (keine Relationships)."""
    state = sa_inspect(obj)
    return {
        attr.key: to_jsonable(getattr(obj, attr.key))
        for attr in state.mapper.column_attrs
    }


# Bewusste Auswahl (Spec 2026-07-08): Belege, Stammdaten, Firmendaten.
# InvoiceItem wird bewusst NICHT auditiert — der invoice_guard ist dort die
# einzige Verteidigungslinie (siehe docs/ARCHITEKTUR.md, „Zwei Verteidigungslinien").
# InvoiceSendLog ebenfalls nicht: die Tabelle ist selbst ein Protokoll.
AUDITED_MODELS = (Invoice, Customer, Company)

_PENDING_KEY = "_audit_pending"
_registered = False


def _changed_columns(obj, session: Session) -> tuple[dict, dict]:
    """(old, new) nur für tatsächlich geänderte Spalten eines dirty-Objekts.

    session wird nur für den NO_VALUE-Fallback benötigt (direkte DB-Abfrage des alten Werts).
    """
    state = sa_inspect(obj)
    old, new = {}, {}
    for attr in state.mapper.column_attrs:
        hist = state.attrs[attr.key].history
        if not hist.has_changes():
            continue
        # hist.deleted might be empty if committed_state doesn't have the value (e.g., after insert-commit
        # in a fresh session). Use committed_state directly as fallback.
        key = attr.key
        if hist.deleted:
            old_val = hist.deleted[0]
        elif key in state.committed_state:
            cs_val = state.committed_state[key]
            if cs_val is LoaderCallableStatus.NO_VALUE:
                # The committed state wasn't fully loaded. Query the DB directly.
                # Let DB errors propagate — silently writing None would corrupt GoBD audit trail.
                stmt = select(obj.__table__.c[key]).where(obj.__table__.c.id == obj.id)
                old_val = session.execute(stmt).scalar()
            else:
                old_val = cs_val
        else:
            old_val = None
        new_val = hist.added[0] if hist.added else None
        old[key] = to_jsonable(old_val)
        new[key] = to_jsonable(new_val)
    return old, new


def _before_flush(session: Session, flush_context, instances) -> None:
    # Frisch pro Flush: Reste eines abgebrochenen Flushs (z. B. Guard-Exception,
    # IntegrityError) dürfen nicht als Geister-Audit-Zeilen nachlaufen.
    pending = session.info[_PENDING_KEY] = []
    for obj in session.new:
        if isinstance(obj, AUDITED_MODELS):
            # id ggf. noch None → Snapshot erst im after_flush ziehen
            pending.append(("insert", obj, None, None))
    for obj in session.dirty:
        if isinstance(obj, AUDITED_MODELS) and session.is_modified(obj, include_collections=False):
            old, new = _changed_columns(obj, session)
            if new:
                pending.append(("update", obj, old, new))
    for obj in session.deleted:
        if isinstance(obj, AUDITED_MODELS):
            # Verteidigungslinie: hard deletes sind verboten, werden aber geloggt.
            pending.append(("delete", obj, snapshot(obj), None))


def _after_flush(session: Session, flush_context) -> None:
    pending = session.info.pop(_PENDING_KEY, [])
    if not pending:
        return
    rows = []
    for action, obj, old, new in pending:
        if action == "insert":
            new = snapshot(obj)  # jetzt hat obj eine id
        rows.append({
            "table_name": obj.__tablename__,
            "record_id": str(obj.id),
            "action": action,
            "old_values": old,
            "new_values": new,
        })
    # Core-Insert: im after_flush erlaubt, wendet Spalten-Defaults (uuid4) an
    # und löst selbst keinen weiteren ORM-Flush aus (→ keine Endlosschleife).
    session.execute(AuditLog.__table__.insert(), rows)


def _after_rollback(session: Session) -> None:
    """Nach Rollback: ausstehende Audit-Einträge löschen, damit sie nicht beim nächsten
    erfolgreichen Flush als Geister-Zeilen auftauchen (z.B. nach Guard-Exception).
    """
    session.info.pop(_PENDING_KEY, None)


def register_audit_listeners() -> None:
    """Audit-Listener global an die Session-Klasse hängen. Idempotent."""
    global _registered
    if _registered:
        return
    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "after_flush", _after_flush)
    event.listen(Session, "after_rollback", _after_rollback)
    _registered = True
