"""Clusterweite Sperre fuer Provisionierungen, die Postgres-Rollen anfassen.

Rollen gehoeren dem ganzen Cluster. Die Advisory-Sperre in `ensure_app_role`
(`app.db.roles.APP_ROLE_LOCK_KEY`) gilt aber nur innerhalb EINER Datenbank:
Advisory-Schluessel sind pro Datenbank getrennt. Testprozesse mit je eigener
Datenbank (`ABGEHAKT_TEST_DB_JE_PROZESS=1`) serialisieren sich damit nicht.

Diese Sperre sitzt deshalb auf einer Verbindung zur gemeinsamen Datenbank aus
`DATABASE_URL`, die alle Prozesse teilen, und wird erst NACH dem Commit der
Provisionierung freigegeben. Eine Transaktionssperre auf einer zweiten
Verbindung liesse zu frueh los: der Nachfolger saehe die Rolle noch nicht.
"""
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, text

# Anderer Wert als APP_ROLE_LOCK_KEY: laeuft die Provisionierung zufaellig in
# der gemeinsamen Datenbank selbst, haette derselbe Schluessel einen
# Selbstverschluss zur Folge (zwei Verbindungen, eine Sperre).
CLUSTER_SPERRE_KEY = 0x6162_6765_6861_6B75


@contextmanager
def clusterweite_rollensperre(gemeinsame_url: str) -> Iterator[None]:
    engine = create_engine(gemeinsame_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:k)").bindparams(k=CLUSTER_SPERRE_KEY))
            try:
                yield
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:k)").bindparams(k=CLUSTER_SPERRE_KEY))
    finally:
        engine.dispose()
