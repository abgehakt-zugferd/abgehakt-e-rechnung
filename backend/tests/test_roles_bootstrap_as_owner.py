"""
`ensure_app_role` MUSS von der Owner-Rolle (NOSUPERUSER + CREATEROLE) ausführbar
sein — sie ist es, die im Entrypoint läuft.

Prod-Regression 2026-07-25: nach dem Owner-Umzug auf `abgehakt_admin` scheiterte der
Entrypoint an `ALTER ROLE abgehakt_app WITH … NOSUPERUSER …`:

    permission denied to alter role
    DETAIL: Only roles with the SUPERUSER attribute may change the SUPERUSER attribute.

Postgres verbietet das explizite Setzen von NOSUPERUSER für Nicht-Superuser —
auch dann, wenn die Zielrolle das Attribut ohnehin nicht besitzt. Da der
Entrypoint `set -e` hat, startete die App nicht mehr.
"""
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.db.roles import APP_ROLE, ensure_app_role, resolve_owner_role

OWNER = "abgehakt_test_owner"
OWNER_PW = "test-owner-passwort-nur-fuer-testlauf"


@pytest.fixture()
def owner_engine(pg_engine):
    """Verbindung als Wegwerf-Rolle mit exakt den Prod-Owner-Rechten:
    NOSUPERUSER + CREATEROLE + ADMIN OPTION auf abgehakt_app."""
    settings = get_settings()
    parsed = urlparse(settings.database_url)
    db_name = pg_engine.url.database

    with pg_engine.begin() as c:
        c.execute(text(f"DROP ROLE IF EXISTS {OWNER}"))
        c.execute(text(
            f"CREATE ROLE {OWNER} LOGIN NOSUPERUSER CREATEROLE PASSWORD '{OWNER_PW}'"
        ))
        c.execute(text(f"GRANT {APP_ROLE} TO {OWNER} WITH ADMIN OPTION"))
        # Owner der Tabellen bleibt die Testrolle — für GRANT ON ALL TABLES nötig.
        c.execute(text(f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {OWNER} WITH GRANT OPTION"))
        c.execute(text(f"GRANT ALL ON SCHEMA public TO {OWNER}"))

    url = f"postgresql://{OWNER}:{OWNER_PW}@{parsed.hostname}:{parsed.port or 5432}/{db_name}"
    engine = create_engine(url, pool_pre_ping=True)
    yield engine
    engine.dispose()
    with pg_engine.begin() as c:
        # Aufräumen erfordert die Rechte der Rolle selbst — pg_engine ist hier
        # nicht zwingend Superuser (Owner-Rolle), daher explizit Mitglied werden.
        c.execute(text(f"GRANT {OWNER} TO CURRENT_USER"))
        c.execute(text(f"DROP OWNED BY {OWNER}"))
        c.execute(text(f"DROP ROLE IF EXISTS {OWNER}"))
        # `DROP OWNED BY` reißt auch die Grants weg, die diese Rolle für abgehakt_app
        # gesetzt hat — sonst fallen alle nachfolgenden Least-Privilege-Tests um
        # (Test-Isolation: Zustand von pg_engine wiederherstellen).
        ensure_app_role(
            c,
            settings.db_app_password,
            owner_role=resolve_owner_role(settings.database_url),
        )


def test_superuser_app_rolle_wird_fail_closed_abgelehnt(owner_engine):
    """Wäre die App-Rolle je Superuser, ist das ein GAU — dann muss ein klarer
    Fehler kommen, kein kryptisches `permission denied` aus dem ALTER.

    Zielrolle ist eine BESTEHENDE Superuser-Rolle (jede Installation hat den
    Bootstrap-User) — eine anzulegen bräuchte selbst Superuser-Rechte und wäre je
    nach Umgebung mal grün, mal Fehler.
    """
    with owner_engine.connect() as conn:
        super_role = conn.execute(
            text("SELECT rolname FROM pg_roles WHERE rolsuper ORDER BY oid LIMIT 1")
        ).scalar()
    assert super_role, "Testumgebung ohne Superuser-Rolle — unerwartet"

    with pytest.raises(RuntimeError, match="SUPERUSER"):
        with owner_engine.begin() as conn:
            ensure_app_role(conn, "pw-egal", app_role=super_role, owner_role=OWNER)


def test_ensure_app_role_laeuft_als_owner_ohne_superuser(owner_engine):
    """Der Entrypoint-Pfad: Owner-Rolle provisioniert abgehakt_app — ohne Superuser."""
    with owner_engine.begin() as conn:
        ensure_app_role(conn, "neues-app-passwort-testlauf", owner_role=OWNER)

    with owner_engine.connect() as conn:
        is_super = conn.execute(text(
            f"SELECT rolsuper FROM pg_roles WHERE rolname = '{APP_ROLE}'"
        )).scalar()
    assert is_super is False
