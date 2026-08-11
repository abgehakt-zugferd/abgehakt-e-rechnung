#!/usr/bin/env python3
"""
Owner-/Migrationsrolle sicherstellen (#151) — läuft VOR `alembic upgrade head`.

Postgres legt beim ersten Start nur `POSTGRES_USER` an, und das ist bewusst der
Bootstrap-Superuser (OID 10, nicht demotierbar). Die Rolle, mit der Alembic
verbindet, muss also jemand erzeugen. Ohne diesen Schritt endet der erste Start
einer frischen Installation mit `FATAL: password authentication failed` — einer
Meldung, die nach einem Tippfehler aussieht statt nach einer fehlenden Rolle.

Verbindet über BOOTSTRAP_DATABASE_URL (Superuser) und legt die Rolle aus
DATABASE_URL an. Idempotent: läuft bei jedem Start.

Aufruf (Compose):  docker compose exec app python scripts/bootstrap_owner.py
"""
import os
import sys
from urllib.parse import unquote, urlsplit

from sqlalchemy import create_engine

# Das App-Paket liegt eine Ebene über scripts/ (im Container /app, auf dem Host backend/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.roles import ensure_owner_role, resolve_owner_role  # noqa: E402


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("FEHLER: DATABASE_URL nicht gesetzt.", file=sys.stderr)
        return 1

    bootstrap_url = os.environ.get("BOOTSTRAP_DATABASE_URL", "")
    if not bootstrap_url:
        # Fail-closed und mit Ansage: ohne Bootstrap-Verbindung KANN die Rolle
        # nicht entstehen. Stillschweigend weiterlaufen hieße, den Start in
        # genau die irreführende Passwortmeldung laufen zu lassen, die dieses
        # Skript verhindern soll.
        print(
            "FEHLER: BOOTSTRAP_DATABASE_URL nicht gesetzt — die Owner-Rolle kann nicht "
            "angelegt werden. In .env DB_BOOTSTRAP_USER/DB_BOOTSTRAP_PASSWORD setzen.",
            file=sys.stderr,
        )
        return 1

    # Passwort der Owner-Rolle steht in DATABASE_URL — dieselbe Quelle, mit der
    # Alembic sich gleich anmeldet. Aus DB_PASSWORD zu lesen wäre eine zweite
    # Kopie, die auseinanderlaufen kann.
    passwort = urlsplit(database_url).password
    if not passwort:
        print("FEHLER: DATABASE_URL enthält kein Passwort.", file=sys.stderr)
        return 1

    owner = resolve_owner_role(database_url)
    engine = create_engine(bootstrap_url)
    with engine.begin() as conn:
        ensure_owner_role(conn, unquote(passwort), owner_role=owner)
    print(f"OK: Owner-Rolle {owner} vorhanden (Attribute, Passwort, Datenbank-Eigentum).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
