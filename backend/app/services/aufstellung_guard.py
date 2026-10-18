"""
GoBD-Unveränderlichkeit für Abrechnungsaufstellungen (Aufstellung), erzwungen
auf Session-Ebene — kein Codepfad (Router, Skript, SQLAlchemy-Shell) kann sie
umgehen.

  draft     → issued | discarded   (stellen, verwerfen)
  discarded → draft                (zurueckholen)
  issued    → cancelled            (stornieren, Festlegung 17)
  cancelled → (Endstatus)

Regeln (wie invoice_guard, denn die Aufstellung ist kein Beleg der Rechnung,
aber GoBD-gebunden wie einer — Entscheidung 8):
  - Gestellte und stornierte Aufstellungen (issued/cancelled) sind INHALTLICH
    unveränderlich. Nur Metadaten dürfen sich noch ändern: `status` (per
    erlaubtem Übergang), `datev_sent_at` (einmal setzen), `auftragsschluessel_
    offen` (nur leeren) und `updated_at` (Auto-Timestamp). Es gibt kein
    `bezahlt`: Die Aufstellung kennt keinen Zahlungseingang als Status.
  - Aufstellungen werden NIE hard-gelöscht — auch keine Entwürfe.
  - Entwürfe (draft) und verworfene Entwürfe (discarded) bleiben frei
    bearbeitbar; discarded erklärt die Nummernlücke (Festlegung 18).
    Ausnahme Storno: Originalbezug und dessen Werte bleiben gebunden,
    eigene Anlagen sind schon im Entwurf verboten (Festlegung 17).

Warum eine eigene Datei neben invoice_guard.py statt gemeinsame Maschinerie:
Der invoice_guard ist rechnungsspezifisch durch und durch (bezahlt_am an
issued→paid gebunden, Gutschrifts-Endgültigkeit #142, Positionen-Umhaengen
#120); herausgezogen und parametrisiert muesste die bewaehrte, GoBD-kritische
Maschine des invoice_guard verformt und ihre Tests angefasst werden. Was
wirklich identisch ist — der Klebstoff mit SQLAlchemy (get_history,
Status-Vorwert aus der DB, neue-Objekte-dieser-Transaktion) — ist klein und
wird hier einmal nachgebaut, in der Morphologie des Vorbilds, damit beide
Dateien nebeneinander lesbar bleiben.

Anlagen: Die Anlage einer GESTELLTEN Aufstellung ist unveränderlich, nicht
loeschbar und nicht nachschiebbar. Das Loeschen einer Anlage ist ausserdem
IMMER verboten — auch im Entwurf —, weil ihr Platz durch
(aufstellung_id, quelle) fix ist: Korrektur heisst neue Datei in dieselbe
Zeile (UPDATE), nie Zeile weg; der DB-Trigger auf aufstellung_anlagen
verbietet dasselbe ohne Ausnahme.

MUSS vor register_audit_listeners() registriert werden (analog
invoice_guard): wirft der Guard erst nach dem Audit-before_flush, blieben
dessen Pending-Einträge in session.info liegen und würden als Geister-
Audit-Zeilen geschrieben.
"""
from sqlalchemy import event, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import get_history

from app.models.aufstellung import Aufstellung, AufstellungAnlage
from app.services.aufstellung_storno_guard import (
    pruefe_storno, pruefe_aufhebung, pruefe_storno_anlage, pruefe_stornobezug,
)

FINALIZED: set[str] = {"issued", "cancelled"}

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"issued", "discarded"},
    "discarded": {"draft"},
    "issued": {"cancelled"},
    "cancelled": set(),
}

# Felder, die auch NACH dem Finalisieren noch geschrieben werden dürfen —
# Metadaten, kein Inhalt der Aufstellung. `status` wird separat über
# ALLOWED_TRANSITIONS geprüft; `auftragsschluessel_offen` ist Sonderfall
# (Festlegung 12): erlaubt ist nach issued nur das LEEREN.
MUTABLE_AFTER_FINALIZE: set[str] = {
    "status", "datev_sent_at", "auftragsschluessel_offen", "updated_at",
}

# Session-Schlüssel für die in DIESER Transaktion neu erzeugten Aufstellungen.
# Ihre schrittweise Befüllung über mehrere Flushes ist Erstellung, keine
# Manipulation (Storno-Zeile in 7e wird denselben Weg gehen wie das
# Storno einer Rechnung).
_NEW_KEY = "_aufstellung_guard_new_this_txn"

_registered = False


class AufstellungStateError(RuntimeError):
    """Verstoß gegen die GoBD-Unveränderlichkeit/Statusmaschine der
    Abrechnungsaufstellung."""


def _resolve_old_status(session: Session, obj: Aufstellung) -> str:
    """Status VOR dem Flush ermitteln (robust gegen (un)geladene Attribute)."""
    hist = get_history(obj, "status")
    if hist.deleted:
        return hist.deleted[0]
    if not hist.has_changes():
        return obj.status
    prev = session.execute(
        select(Aufstellung.__table__.c.status)
        .where(Aufstellung.__table__.c.id == obj.id)
    ).scalar()
    if prev is None:
        raise AufstellungStateError(
            f"Vorheriger Status von Aufstellung {obj.id} konnte nicht ermittelt "
            "werden — Flush abgebrochen (GoBD-Guard)."
        )
    return prev


def _parent_status(session: Session, anlage: AufstellungAnlage, neue: set) -> str | None:
    """Committeten Status der zugehörigen Aufstellung — oder None, wenn die
    Anlage zu einer in DIESER Transaktion neu erzeugten Aufstellung gehört
    (dann ist ihre Anlage Teil der Erstellung).

    Erst das Parent-OBJEKT fragen: Fuer eine in diesem Flush NEU angehaengte
    Anlage (`anlage.aufstellung = a`) ist aufstellung_id vor dem Flush noch
    None — der FK wird erst beim Assemblieren gesetzt. Der Status steht
    trotzdem am schon geladenen Parent.
    """
    parent = anlage.__dict__.get("aufstellung")
    if parent is not None:
        return None if parent in neue else parent.status
    pid = anlage.aufstellung_id
    # Parent nicht im Objekt geladen: FK gegen DB lesen — aber eine in DIESEN
    # Flush noch nicht geschriebene neue Aufstellung hat dort noch keine Zeile.
    if pid is None or pid in {a.id for a in neue if a.id is not None}:
        return None
    return session.execute(
        select(Aufstellung.__table__.c.status)
        .where(Aufstellung.__table__.c.id == pid)
    ).scalar()


def _guard_anlage(session: Session, anlage: AufstellungAnlage, neue: set) -> None:
    """Anlagen: einer finalisierten Aufstellung unveraenderlich (Aendern,
    Nachschieben); das Loeschen regelt Punkt 1 in _before_flush unbedingt."""
    if _parent_status(session, anlage, neue) in FINALIZED:
        raise AufstellungStateError(
            "Anlagen einer gestellten oder stornierten Aufstellung sind "
            "unveränderlich (GoBD) — Korrektur nur per Storno."
        )


def _pruefe_forward_only(session: Session, obj: Aufstellung, attr: str, label: str) -> None:
    """Einmal setzen, nie ändern — das Muster der Versandvermerke."""
    hist = get_history(obj, attr)
    if not hist.has_changes():
        return
    alt = hist.deleted[0] if hist.deleted else session.execute(
        select(getattr(Aufstellung.__table__.c, attr))
        .where(Aufstellung.__table__.c.id == obj.id)
    ).scalar()
    neu = hist.added[0] if hist.added else None
    if alt is not None and neu != alt:
        raise AufstellungStateError(
            f"{label} ist nach dem Setzen unveränderlich (GoBD) — "
            "weder Löschen noch Umdatieren erlaubt."
        )


def _before_flush(session: Session, flush_context, instances) -> None:
    for obj in set(session.new) | set(session.dirty):
        if isinstance(obj, Aufstellung):
            pruefe_storno(session, obj, AufstellungStateError)
        elif isinstance(obj, AufstellungAnlage):
            pruefe_storno_anlage(session, obj, AufstellungStateError)
    neue: set = session.info.setdefault(_NEW_KEY, set())
    for obj in session.new:
        if isinstance(obj, Aufstellung):
            neue.add(obj)

    # 1. Hard-Delete ist IMMER verboten (GoBD) — Aufstellungen wie Anlagen.
    for obj in session.deleted:
        if isinstance(obj, Aufstellung):
            raise AufstellungStateError(
                "Aufstellungen dürfen nicht gelöscht werden (GoBD) — "
                "Korrektur nur durch eine Storno-Zeile."
            )
        if isinstance(obj, AufstellungAnlage):
            raise AufstellungStateError(
                "Anlagen dürfen nicht gelöscht werden — ihr Platz je Quelle ist "
                "fix (DB-CHECK), Korrektur ist ein Update der Zeile mit neuer "
                "Datei, neuem Hash."
            )

    # 2. Änderungen an bestehenden Aufstellungen prüfen.
    for obj in session.dirty:
        if not isinstance(obj, Aufstellung) or obj in neue:
            continue
        if not session.is_modified(obj, include_collections=False):
            continue

        _pruefe_aenderung(session, obj)

    # 3. Anlagen: Ändern (dirty) und Nachschieben (new) bei finalisierter
    #    Aufstellung verboten; Löschen immer (siehe 1.).
    for obj in session.dirty:
        if isinstance(obj, AufstellungAnlage) and session.is_modified(
            obj, include_collections=False
        ):
            _guard_anlage(session, obj, neue)
    for obj in session.new:
        if isinstance(obj, AufstellungAnlage):
            _guard_anlage(session, obj, neue)


def _pruefe_aenderung(session, obj):
    pruefe_stornobezug(obj, AufstellungStateError)
    old_status = _resolve_old_status(session, obj)
    status_hist = get_history(obj, "status")

    if status_hist.has_changes():
        new_status = status_hist.added[0] if status_hist.added else None
        if new_status not in ALLOWED_TRANSITIONS.get(old_status, set()):
            raise AufstellungStateError(
                f"Illegaler Statusübergang {old_status!r} → {new_status!r}."
            )
        if new_status == "cancelled":
            pruefe_aufhebung(session, obj, AufstellungStateError)
        # Stellen heisst: mit Ausstellungsdatum. Es ist die einzige
        # Pflicht, die erst beim Uebergang entsteht — ohne Datum waere
        # der gestellte Beleg im Archiv undatiert.
        if new_status == "issued" and obj.ausstellungsdatum is None:
            raise AufstellungStateError(
                "Eine Aufstellung lässt sich nur mit Ausstellungsdatum stellen."
            )

    # Versandvermerk forward-only (Muster datev_sent_at, Bauschritt 5a):
    # None → Zeitpunkt erlaubt, danach unveraenderlich.
    _pruefe_forward_only(session, obj, "datev_sent_at", "datev_sent_at (Versandnachweis)")

    _pruefe_inhalt(obj, old_status)


def _pruefe_inhalt(obj, old_status):
    # Sperre (Festlegung 12): nach dem Finalisieren nur GELEERT werden.
    ao_hist = get_history(obj, "auftragsschluessel_offen")
    if ao_hist.has_changes() and old_status in FINALIZED:
        neuer_wert = ao_hist.added[0] if ao_hist.added else None
        if neuer_wert is not None:
            raise AufstellungStateError(
                "auftragsschluessel_offen darf nach dem Finalisieren nur "
                "geleert werden — Setzen oder Aendern sperrt einen "
                "Auftragsschluessel, der schon freigegeben oder von einem "
                "anderen Beleg belegt ist."
            )

    # Inhalt einer finalisierten Aufstellung ist unveränderlich
    if old_status in FINALIZED:
        for col_attr in obj.__mapper__.column_attrs:
            key = col_attr.key
            if key in MUTABLE_AFTER_FINALIZE:
                continue
            if get_history(obj, key).has_changes():
                raise AufstellungStateError(
                    f"Finalisierte Aufstellung ({old_status}) ist unveränderlich "
                    f"(GoBD) — Feld {key!r} darf nicht geändert werden. "
                    "Korrektur nur per Storno."
                )


def _clear_new_this_txn(session: Session) -> None:
    """Nach Commit/Rollback darf die „neu erzeugt"-Ausnahme nicht in die
    nächste Transaktion durchsickern."""
    session.info.pop(_NEW_KEY, None)


def register_aufstellung_guard() -> None:
    """Guard global an die Session-Klasse hängen. Idempotent."""
    global _registered
    if _registered:
        return
    event.listen(Session, "before_flush", _before_flush)
    event.listen(Session, "after_commit", _clear_new_this_txn)
    event.listen(Session, "after_rollback", _clear_new_this_txn)
    _registered = True
