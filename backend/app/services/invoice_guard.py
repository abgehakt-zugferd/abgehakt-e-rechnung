"""
GoBD-Unveränderlichkeit für Rechnungen (Invoice), erzwungen auf Session-Ebene —
kein Codepfad (Router, Skript, SQLAlchemy-Shell) kann sie umgehen.

  draft     → issued            (finalisieren)
  issued    → paid | cancelled
  paid      → (nichts; Endstatus)
  cancelled → (nichts; Endstatus)

Regeln (docs/ARCHITEKTUR.md, „Kritische Regeln — niemals brechen"):
  - Finalisierte Rechnungen (issued/paid/cancelled) sind INHALTLICH unveränderlich.
    Nur Metadaten dürfen sich noch ändern: `status` (per erlaubtem Übergang),
    `datev_sent_at` (Versandzeitpunkt), `bezahlt_am` (nur mit issued→paid) und
    `updated_at` (Auto-Timestamp).
  - Rechnungen werden NIE hard-gelöscht (auch keine Entwürfe) — nur `cancelled`/Storno.
  - Entwürfe (draft) bleiben frei bearbeitbar.

MUSS vor register_audit_listeners() registriert werden (analog booking_guard):
wirft der Guard erst nach dem Audit-before_flush, blieben dessen Pending-Einträge
in session.info liegen und würden als Geister-Audit-Zeilen geschrieben.
"""
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import get_history

from app.models.invoice import Invoice, InvoiceItem

FINALIZED: set[str] = {"issued", "paid", "cancelled"}

# `discarded` (#145) ist der verworfene ENTWURF — nicht `cancelled` (das ist der
# gestellte, stornierte Beleg mit PDF und XML). Er existiert, weil Rechnungen nie
# hart gelöscht werden dürfen und die Nummer schon beim Entwurf vergeben ist: der
# Datensatz bleibt und erklärt die Nummernlücke. Aus `discarded` führt kein Weg
# direkt in einen Belegstatus — erst zurückholen, dann finalisieren.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"issued", "discarded"},
    "discarded": {"draft"},
    "issued": {"paid", "cancelled"},
    "paid": set(),
    "cancelled": set(),
}

# Felder, die auch NACH Finalisierung noch geschrieben werden dürfen — Metadaten,
# kein Rechnungsinhalt. `status` wird separat über ALLOWED_TRANSITIONS geprüft.
MUTABLE_AFTER_FINALIZE: set[str] = {
    "status", "datev_sent_at", "bezahlt_am", "updated_at",
}

# Session-Schlüssel für die in DIESER Transaktion neu erzeugten Rechnungen. Sie
# werden erst mit dem Commit „unveränderlich"; ihre schrittweise Befüllung (z. B.
# Storno: Invoice als 'issued' anlegen → flush → zugferd_xml setzen → commit)
# ist Erstellung, keine Manipulation und darf nicht am Guard scheitern.
# Es werden die Invoice-OBJEKTE gehalten (nicht id()), damit über mehrere Flushes
# hinweg auch ihre – erst beim Flush vergebene – UUID gelesen werden kann; das
# ordnet neu erzeugte Positionen ihrer neuen (noch nicht committeten) Rechnung zu.
_NEW_KEY = "_invoice_guard_new_this_txn"

_registered = False


class InvoiceStateError(RuntimeError):
    """Verstoß gegen die GoBD-Unveränderlichkeit/Statusmaschine der Rechnungen."""


def _resolve_old_status(session: Session, obj: Invoice) -> str:
    """Status VOR dem Flush ermitteln (robust gegen (un)geladene Attribute)."""
    hist = get_history(obj, "status")
    if hist.deleted:
        return hist.deleted[0]
    if not hist.has_changes():
        return obj.status
    # Status geändert, aber kein Vorwert in der History (Attribut war nie geladen)
    # → aus der DB nachladen; fail-closed, wenn das nicht gelingt.
    prev = session.execute(
        select(Invoice.__table__.c.status).where(Invoice.__table__.c.id == obj.id)
    ).scalar()
    if prev is None:
        raise InvoiceStateError(
            f"Vorheriger Status von Rechnung {obj.id} konnte nicht ermittelt werden — "
            "Flush abgebrochen (GoBD-Guard)."
        )
    return prev


def _parent_status(session: Session, item: InvoiceItem, new_invoices: set) -> str | None:
    """Committeten Status der zugehörigen Rechnung ermitteln — oder None, wenn die
    Position zu einer in DIESER Transaktion neu erzeugten Rechnung gehört (dann ist
    ihre Anlage Teil der Erstellung und der Guard greift nicht)."""
    # Bereits geladenes Relationship-Objekt (z. B. via `storno.items = [...]`) —
    # ohne Lazy-Load. Gehört es zu einer neuen Rechnung → Erstellung, kein Eingriff.
    parent = item.__dict__.get("invoice")
    if parent is not None and parent in new_invoices:
        return None
    pid = item.invoice_id
    if pid is None:
        # FK noch nicht gesetzt (wird erst beim Flush aus dem Relationship befüllt).
        # Ein Parent gäbe es nur als neues Objekt → oben bereits abgedeckt.
        return None
    if pid in {inv.id for inv in new_invoices if inv.id is not None}:
        return None
    return session.execute(
        select(Invoice.__table__.c.status).where(Invoice.__table__.c.id == pid)
    ).scalar()


def _vorheriger_parent_status(session: Session, item: InvoiceItem) -> str | None:
    """Committeten Status der Rechnung, zu der die Position VOR dem Umhängen gehörte.

    `item.invoice_id` trägt nach einer Änderung schon den neuen Wert (#120). Der alte
    wird aus der Datenbank gelesen, nicht aus der History: die ist leer, wenn das
    Attribut vor dem Setzen nie geladen war. None bei neuen Positionen."""
    if not get_history(item, "invoice_id").has_changes():
        return None
    items = InvoiceItem.__table__
    invoices = Invoice.__table__
    return session.execute(
        select(invoices.c.status)
        .join(items, items.c.invoice_id == invoices.c.id)
        .where(items.c.id == item.id)
    ).scalar()


def _guard_item(session: Session, item: InvoiceItem, new_invoices: set) -> None:
    """Positionen einer finalisierten Rechnung sind unveränderlich (GoBD) —
    kein Ändern, Löschen, Nachschieben oder Umhängen (audit.py auditiert Items bewusst
    nicht, daher ist der Guard hier die einzige Verteidigungslinie)."""
    if (
        _parent_status(session, item, new_invoices) in FINALIZED
        or _vorheriger_parent_status(session, item) in FINALIZED
    ):
        raise InvoiceStateError(
            "Positionen einer finalisierten Rechnung sind unveränderlich (GoBD) — "
            "Korrektur nur per Storno."
        )


def _before_flush(session: Session, flush_context, instances) -> None:
    # 0. In dieser Transaktion neu erzeugte Rechnungen merken (als Objekte, damit
    #    ihre – erst beim Flush vergebene – UUID gelesen werden kann). Ihre Befüllung
    #    über mehrere Flushes hinweg ist Erstellung, kein nachträglicher Eingriff.
    new_invoices: set = session.info.setdefault(_NEW_KEY, set())
    for obj in session.new:
        if isinstance(obj, Invoice):
            new_invoices.add(obj)

    # 1. Hard-Delete von Rechnungen ist IMMER verboten (GoBD, §14b UStG)
    for obj in session.deleted:
        if isinstance(obj, Invoice):
            raise InvoiceStateError(
                "Rechnungen dürfen nicht gelöscht werden (GoBD) — "
                "Status 'cancelled' setzen oder Storno erzeugen."
            )

    # 2. Änderungen an bestehenden Rechnungen prüfen
    for obj in session.dirty:
        if not isinstance(obj, Invoice):
            continue
        if obj in new_invoices:
            # Erst in dieser (noch nicht committeten) Transaktion angelegt → Teil der
            # Erstellung. Unveränderlichkeit greift erst ab dem nächsten Commit.
            continue
        if not session.is_modified(obj, include_collections=False):
            continue

        old_status = _resolve_old_status(session, obj)
        status_hist = get_history(obj, "status")

        # Statusübergang validieren (falls er sich ändert)
        if status_hist.has_changes():
            new_status = status_hist.added[0] if status_hist.added else None
            if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
                raise InvoiceStateError(
                    f"Illegaler Statusübergang {old_status!r} → {new_status!r}."
                )
            # Eine gestellte Gutschrift ist endgueltig (Issue #142): storniert,
            # lebte das Original wieder auf und steckte fest. Die Route sagt
            # vorher freundlich, was stattdessen zu tun ist (storno.pruefe_stornierbar).
            if new_status == "cancelled" and obj.invoice_type == "credit_note":
                raise InvoiceStateError(
                    "Eine gestellte Gutschrift ist endgueltig und laesst sich nicht "
                    "stornieren (#142). Korrektur ueber eine neue Rechnung zum Original."
                )
            # Bezahlt heisst: mit Zahlungsdatum. Ohne fiele der Beleg still aus Umsatz
            # und Geldeingang, und nachtragen liesse es sich nicht mehr.
            if new_status == "paid" and obj.bezahlt_am is None:
                raise InvoiceStateError(
                    "Bezahlt ohne Zahlungsdatum (bezahlt_am) ist nicht erlaubt."
                )

        # Versandnachweis ist forward-only (#98 P0.3): None → Zeitpunkt ist erlaubt
        # (der Versand selbst), aber ein einmal gesetzter datev_sent_at darf nicht
        # mehr geleert oder umdatiert werden — sonst ließe sich der DATEV-Versand
        # nachträglich verleugnen. (datev_sent_at bleibt in MUTABLE_AFTER_FINALIZE,
        # damit das erstmalige Setzen an issued/paid weiter durchgeht.)
        ds_hist = get_history(obj, "datev_sent_at")
        if ds_hist.has_changes():
            # Vorwert robust ermitteln — nach Commit ist das Attribut expired, die
            # History-`deleted` also leer; dann aus der DB nachladen (wie beim Status).
            old_ds = ds_hist.deleted[0] if ds_hist.deleted else session.execute(
                select(Invoice.__table__.c.datev_sent_at)
                .where(Invoice.__table__.c.id == obj.id)
            ).scalar()
            new_ds = ds_hist.added[0] if ds_hist.added else None
            if old_ds is not None and new_ds != old_ds:
                raise InvoiceStateError(
                    "datev_sent_at (Versandnachweis) ist nach dem Setzen unveränderlich "
                    "(GoBD) — weder Löschen noch Umdatieren erlaubt."
                )

        # Zahlungsdatum: nur mit issued → paid setzen, danach forward-only
        # (Entscheidung 2026-09-30). In MUTABLE_AFTER_FINALIZE, damit das Setzen
        # beim erlaubten Statuswechsel nicht an der allgemeinen Sperre scheitert.
        ba_hist = get_history(obj, "bezahlt_am")
        if ba_hist.has_changes():
            old_ba = ba_hist.deleted[0] if ba_hist.deleted else session.execute(
                select(Invoice.__table__.c.bezahlt_am)
                .where(Invoice.__table__.c.id == obj.id)
            ).scalar()
            new_ba = ba_hist.added[0] if ba_hist.added else None
            if old_ba is not None and new_ba != old_ba:
                raise InvoiceStateError(
                    "bezahlt_am (Zahlungsdatum) ist nach dem Setzen unveränderlich "
                    "(GoBD) — weder Löschen noch Umdatieren erlaubt."
                )
            if old_ba is None and new_ba is not None:
                new_status = (
                    status_hist.added[0]
                    if status_hist.has_changes() and status_hist.added
                    else None
                )
                if not (old_status == "issued" and new_status == "paid"):
                    raise InvoiceStateError(
                        "bezahlt_am darf nur beim Statuswechsel issued → paid gesetzt werden."
                    )

        # Inhalt einer finalisierten Rechnung ist unveränderlich
        if old_status in FINALIZED:
            for col_attr in obj.__mapper__.column_attrs:
                key = col_attr.key
                if key in MUTABLE_AFTER_FINALIZE:
                    continue
                if get_history(obj, key).has_changes():
                    raise InvoiceStateError(
                        f"Finalisierte Rechnung ({old_status}) ist unveränderlich (GoBD) — "
                        f"Feld {key!r} darf nicht geändert werden. Korrektur nur per Storno."
                    )

    # 3. Positionen finalisierter Rechnungen sind ebenfalls unveränderlich —
    #    Ändern (dirty), Löschen (deleted) und Nachschieben (new) sind verboten.
    for obj in session.dirty:
        if isinstance(obj, InvoiceItem) and session.is_modified(obj, include_collections=False):
            _guard_item(session, obj, new_invoices)
    for obj in session.deleted:
        if isinstance(obj, InvoiceItem):
            _guard_item(session, obj, new_invoices)
    for obj in session.new:
        if isinstance(obj, InvoiceItem):
            _guard_item(session, obj, new_invoices)


def _clear_new_this_txn(session: Session) -> None:
    """Nach Commit/Rollback ist die Transaktion vorbei — die „neu erzeugt"-Ausnahme
    darf NICHT in die nächste Transaktion durchsickern (sonst ließe sich eine dann
    committete Rechnung weiter verändern)."""
    session.info.pop(_NEW_KEY, None)


def register_invoice_guard() -> None:
    """Guard global an die Session-Klasse hängen. Idempotent."""
    global _registered
    if _registered:
        return
    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "after_commit", _clear_new_this_txn)
    event.listen(Session, "after_rollback", _clear_new_this_txn)
    _registered = True
