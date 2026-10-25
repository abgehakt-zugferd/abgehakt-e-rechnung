#!/usr/bin/env python3
"""CLI: Uebergabekette eines Absenders in der Testinstanz neu beginnen (#214).

Entfernt die gemerkten Eingaenge EINES Absenders, damit zuletzt_angenommen
wieder None liefert. Nur in einer Testinstanz. Rechnungen, Entwuerfe,
Aufstellungen, Kunden und Firmendaten bleiben unberuehrt. Aufbewahrungskopien
bleiben liegen: kopie_aufbewahren ist bei gleichem Hash idempotent, ein
erneutes Annehmen desselben Belegs scheitert nicht an der Kopie.

Die App-Rolle darf `uebergabe_eingaenge` nicht loeschen (#220). Dieses Skript
verbindet deshalb als Eigentuemer (`DATABASE_URL`, wie Alembic), und zwar erst
NACH der Testinstanz-Pruefung.
"""
from __future__ import annotations

import sys
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.installation import is_testinstanz
from app.models.uebergabe_eingang import UebergabeEingang


def main(argv: Optional[list[str]] = None, *, db: Optional[Session] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not is_testinstanz():
        print(
            "Nur in einer Testinstanz erlaubt "
            "(installation_mode=testinstanz).",
            file=sys.stderr,
        )
        return 2

    if not argv or not argv[0].strip():
        print("Absender fehlt.", file=sys.stderr)
        return 2

    absender = argv[0].strip()
    return _eingaenge_entfernen(absender, db=db)


def _owner_session() -> Session:
    """Eigentuemerrolle aus `database_url` (DATABASE_URL), nie die App-Rolle."""
    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


def _eingaenge_entfernen(absender: str, *, db: Optional[Session]) -> int:
    eigene = db is None
    if eigene:
        db = _owner_session()
    try:
        zeilen = (
            db.query(UebergabeEingang)
            .filter(UebergabeEingang.absender == absender)
            .all()
        )
        anzahl = len(zeilen)
        for zeile in zeilen:
            db.delete(zeile)
        db.commit()
        if anzahl == 0:
            print(
                f"Keine Eingänge für Absender {absender}.",
                file=sys.stderr,
            )
        else:
            print(f"{anzahl} Eingänge für Absender {absender} entfernt.")
        return 0
    finally:
        if eigene:
            db.close()


if __name__ == "__main__":
    sys.exit(main())
