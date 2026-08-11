"""
Least-Privilege-App-Rolle `abgehakt_app` — Provisioning & Grants (Spec §5).

ensure_app_role() ist idempotent und braucht NUR das CREATEROLE-Attribut (kein
Superuser): CREATE ROLE (falls fehlt), Passwort aus DB_APP_PASSWORD, Rechte-Matrix
(CRUD außer DELETE auf den geschützten Tabellen, kein TRUNCATE) + ALTER DEFAULT
PRIVILEGES für künftige (migrations-erzeugte) Tabellen.

Passwort NIE im Code/Migration — kommt aus der Umgebung. Rollen-/Tabellennamen
sind interne Konstanten (keine Nutzereingabe) → f-string-Identifier ok; das
Passwort dagegen IMMER als Bind-Param (psycopg2 bindet client-seitig, DDL ok).
"""
from urllib.parse import unquote, urlsplit

from sqlalchemy import text
from sqlalchemy.engine import Connection

APP_ROLE = "abgehakt_app"
OWNER_ROLE = "abgehakt_admin"
PROTECTED_NO_DELETE = ("invoices", "customers")


def resolve_owner_role(database_url: str | None, default: str = OWNER_ROLE) -> str:
    """Owner-Rolle = die Rolle, mit der Alembic/Bootstrap verbinden (User aus
    `DATABASE_URL`), NICHT aus `BOOTSTRAP_DATABASE_URL`.

    Den Bootstrap-User anzunehmen ist falsch: er legt beim ersten Start nur den
    Cluster an, Eigentümer der Objekte ist `abgehakt_admin`. `ALTER DEFAULT
    PRIVILEGES FOR ROLE <fremde Rolle>` scheitert mit `permission denied` und würde
    den Entrypoint (`set -e`) blockieren.
    """
    if not database_url:
        return default
    user = urlsplit(database_url).username
    return unquote(user) if user else default


def ensure_owner_role(
    conn: Connection,
    password: str,
    owner_role: str = OWNER_ROLE,
    app_role: str = APP_ROLE,
) -> None:
    """Legt die Owner-/Migrationsrolle an (#151) — idempotent, vor Alembic.

    `conn` muss die **Bootstrap**-Verbindung sein (der Superuser, den Postgres
    beim ersten Start als `POSTGRES_USER` anlegt). Das ist keine Bequemlichkeit:
    `GRANT pg_signal_backend` und `ALTER DATABASE … OWNER TO` verlangen Rechte,
    die die Owner-Rolle selbst noch gar nicht haben kann — sie existiert an
    dieser Stelle ja nicht.

    Kein `NOSUPERUSER` im `ALTER`-Zweig: das SUPERUSER-Attribut darf
    ausschließlich ein Superuser setzen, auch negativ. Es steht deshalb im
    `CREATE`-Zweig, wo es hingehört. Wer eine bestehende Owner-Rolle von Hand zum
    Superuser gemacht hat, bekommt das hier folglich nicht zurückgedreht —
    bewusst: in `run-tests.sh` sind Bootstrap- und Owner-Rolle dieselbe Rolle,
    ein harter Abbruch würde dort einen gesunden Aufbau abwürgen.
    """
    if not password:
        raise ValueError("ensure_owner_role: leeres Passwort (DB_PASSWORD nicht gesetzt).")

    conn.execute(text(
        f"DO $$ BEGIN "
        f"  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{owner_role}') THEN "
        f"    CREATE ROLE {owner_role} LOGIN NOSUPERUSER CREATEROLE CREATEDB; "
        f"  END IF; "
        f"END $$;"
    ))
    # CREATEROLE/CREATEDB auch im ALTER: die Rolle wurde in Bestandsumgebungen von
    # Hand angelegt (genau der Anlass für #151) und kann Attribute vermissen. Der
    # Codepfad, nicht die Handarbeit, definiert die Rolle.
    conn.execute(
        text(f"ALTER ROLE {owner_role} WITH LOGIN CREATEROLE CREATEDB PASSWORD :pw")
        .bindparams(pw=password)
    )

    # pg_signal_backend: ohne diese Mitgliedschaft scheitert `DROP DATABASE …
    # WITH (FORCE)` an `must be superuser to terminate` — und damit jede
    # Wiederherstellung, bei der noch eine Verbindung offen ist.
    conn.execute(text(f"GRANT pg_signal_backend TO {owner_role}"))

    # Eigentum an der Datenbank ist die Voraussetzung für CREATE im Schema
    # `public`: seit PostgreSQL 15 gehört es der Pseudo-Rolle `pg_database_owner`,
    # das Recht hängt also am Datenbank-Eigentum, nicht an einem eigenen GRANT.
    # Datenbankname aus der Verbindung, nicht aus der Umgebung — er ist damit
    # garantiert der, in dem gleich migriert wird.
    datenbank = conn.execute(text("SELECT current_database()")).scalar()
    conn.execute(text(f'ALTER DATABASE "{datenbank}" OWNER TO {owner_role}'))
    conn.execute(text(f'GRANT ALL ON DATABASE "{datenbank}" TO {owner_role}'))

    # Selbstheilung: existiert die App-Rolle bereits, aber von fremder Hand
    # angelegt (Bootstrap-Superuser statt Owner), fehlt dem Owner die
    # ADMIN-Option — `ensure_app_role` scheitert dann bei JEDEM Start an
    # `permission denied to alter role`, und zwar dauerhaft. Nur hier läuft noch
    # eine Verbindung, die das reparieren kann.
    conn.execute(text(
        f"DO $$ BEGIN "
        f"  IF EXISTS (SELECT FROM pg_roles WHERE rolname = '{app_role}') THEN "
        f"    GRANT {app_role} TO {owner_role} WITH ADMIN OPTION; "
        f"  END IF; "
        f"END $$;"
    ))


def ensure_app_role(
    conn: Connection,
    password: str,
    app_role: str = APP_ROLE,
    owner_role: str = OWNER_ROLE,
) -> None:
    if not password:
        raise ValueError("ensure_app_role: leeres Passwort (DB_APP_PASSWORD nicht gesetzt).")

    # 1. Rolle idempotent anlegen, dann Attribute + Passwort setzen.
    conn.execute(text(
        f"DO $$ BEGIN "
        f"  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{app_role}') THEN "
        f"    CREATE ROLE {app_role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE; "
        f"  END IF; "
        f"END $$;"
    ))
    # Fail-closed VOR dem ALTER: eine Superuser-App-Rolle wäre der GAU (Trigger
    # blocken zwar weiter, aber Rechte wären wertlos) — und der Owner könnte sie
    # ohnehin nicht anfassen. Klarer Fehler statt "permission denied".
    if conn.execute(
        text("SELECT rolsuper FROM pg_roles WHERE rolname = :r").bindparams(r=app_role)
    ).scalar():
        raise RuntimeError(
            f"ensure_app_role: Rolle {app_role} ist SUPERUSER — das darf die App-Rolle nie "
            f"sein. Manuell als Superuser korrigieren: ALTER ROLE {app_role} NOSUPERUSER;"
        )

    # KEIN NOSUPERUSER im ALTER: Postgres erlaubt das Setzen des SUPERUSER-Attributs
    # (auch das negative!) ausschließlich Superusern — die Owner-Rolle im Entrypoint
    # ist aber bewusst NOSUPERUSER. Die Attribute setzt der CREATE-Zweig oben.
    conn.execute(
        text(f"ALTER ROLE {app_role} WITH LOGIN PASSWORD :pw").bindparams(pw=password)
    )

    # 2. Schema + Sequences
    conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {app_role}"))
    conn.execute(text(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {app_role}"))

    # 3. Tabellen-CRUD, danach DELETE auf den geschützten Tabellen entziehen.
    conn.execute(text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {app_role}"))
    for tbl in PROTECTED_NO_DELETE:
        conn.execute(text(f"REVOKE DELETE ON {tbl} FROM {app_role}"))
    # KEIN GRANT TRUNCATE (Default → App kann nichts truncaten); KEIN CREATE auf dem Schema.

    # 4. Künftige (migrations-erzeugte) Objekte automatisch berechtigen.
    conn.execute(text(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner_role} IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app_role}"
    ))
    conn.execute(text(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner_role} IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {app_role}"
    ))
