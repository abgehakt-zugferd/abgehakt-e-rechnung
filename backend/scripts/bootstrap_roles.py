#!/usr/bin/env python3
"""
Idempotentes Rollen-Provisioning (B2, Spec §5): legt abgehakt_app an + Grants.

Verbindet über DATABASE_URL (Owner-Rolle, braucht CREATEROLE) — bzw. bei frischer
Installation/Demotion einmalig über BOOTSTRAP_DATABASE_URL (Break-Glass-Superuser).
Passwort aus DB_APP_PASSWORD (env). MUSS nach dem Anlegen der Tabellen laufen
(Grants auf bestehende Tabellen), d. h. nach `alembic upgrade head`.

Aufruf (Compose):  docker compose exec app python scripts/bootstrap_roles.py
"""
import os
import sys

from sqlalchemy import create_engine

# Das App-Paket liegt eine Ebene über scripts/ (im Container /app, auf dem Host backend/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.roles import ensure_app_role, resolve_owner_role  # noqa: E402


def main() -> int:
    # DATABASE_URL hat Vorrang, NICHT die Bootstrap-Verbindung: wer `abgehakt_app`
    # anlegt, bekommt die ADMIN-Option darauf. Legt der Bootstrap-Superuser sie an,
    # darf die Owner-Rolle sie nie wieder ändern und jeder weitere Start scheitert an
    # `permission denied to alter role` (gemessen 2026-08-07, nachdem
    # BOOTSTRAP_DATABASE_URL für #151 dauerhaft gesetzt wurde — vorher war die
    # Bevorzugung folgenlos, weil die Variable nie gesetzt war).
    # Break-Glass bleibt möglich, aber nur ausdrücklich: BOOTSTRAP_ROLLEN_ALS_SUPERUSER=1.
    url = os.environ.get("DATABASE_URL")
    if os.environ.get("BOOTSTRAP_ROLLEN_ALS_SUPERUSER") == "1":
        url = os.environ.get("BOOTSTRAP_DATABASE_URL") or url
    if not url:
        print("FEHLER: DATABASE_URL nicht gesetzt.", file=sys.stderr)
        return 1
    password = os.environ.get("DB_APP_PASSWORD", "")
    if not password:
        print("FEHLER: DB_APP_PASSWORD nicht gesetzt.", file=sys.stderr)
        return 1

    # Owner ist die Alembic-Rolle aus DATABASE_URL — auch wenn wir für das
    # Provisioning selbst über BOOTSTRAP_DATABASE_URL (Break-Glass) verbinden.
    owner = resolve_owner_role(os.environ.get("DATABASE_URL"))

    engine = create_engine(url)
    with engine.begin() as conn:
        ensure_app_role(conn, password, owner_role=owner)
    print(f"OK: abgehakt_app provisioniert (Rolle + Grants, Owner={owner}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
