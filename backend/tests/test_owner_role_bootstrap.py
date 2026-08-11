"""#151: Eine frische Installation muss ihre Owner-Rolle selbst anlegen.

Der `db`-Container legt beim ersten Start nur `POSTGRES_USER` an — und das ist
bewusst der **Bootstrap**-User, weil die Bootstrap-Rolle nicht demotierbar ist
(OID 10). Die Owner-Rolle, mit der `alembic upgrade head` verbindet, entstand
bisher durch **keinen** Codepfad; in der Entwicklungsumgebung existierte sie nur,
weil sie von Hand angelegt wurde.

Auf einer fremden Maschine endete der erste Start deshalb mit

    FATAL: password authentication failed for user "abgehakt_admin"

— einer Meldung, die nach einem Tippfehler im Passwort aussieht statt nach einer
fehlenden Rolle. Genau der Ablauf, den ein Erstinstallierer als allererstes geht.

Der schärfste Test ist deshalb nicht „die Zeile steht in `pg_roles`", sondern
**die Anmeldung gelingt** (`test_owner_rolle_kann_sich_danach_anmelden`): das ist
wörtlich das, was in der Meldung oben fehlschlug.
"""
import os
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from app.db.roles import ensure_owner_role

# Eigene Namen, die mit nichts kollidieren: der Test legt eine echte Rolle im
# Cluster an und muss sie hinterher restlos wieder los sein.
TESTROLLE = "abgehakt_ownertest"
TEST_DB = "abgehakt_ownertest_db"
TEST_PASSWORT = "owner-testpasswort-nur-fuer-den-testlauf"


def _aufraeumen(conn) -> None:
    # Reihenfolge zwingend: eine Rolle, der noch eine Datenbank gehört, lässt
    # sich nicht löschen (`role ... cannot be dropped because some objects
    # depend on it`).
    conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)"))
    conn.execute(text(f"DROP ROLE IF EXISTS {TESTROLLE}"))


def _bootstrap_url() -> str:
    """Dieselbe Verbindung, die auch der Entrypoint benutzt (Vorrang wie in
    `scripts/bootstrap_owner.py`).

    Absichtlich nicht einfach `DATABASE_URL`: `GRANT pg_signal_backend` und
    `ALTER DATABASE … OWNER TO` verlangen mehr Rechte, als die Owner-Rolle hat.
    Liefe der Test über die Owner-Verbindung, prüfte er einen Pfad, den es in der
    Produktion nicht gibt — und wäre je nach Umgebung grün oder rot, ohne dass
    sich am Code etwas ändert. (In `run-tests.sh` fallen beide zusammen: dort ist
    `abgehakt_admin` der Bootstrap-Superuser.)
    """
    return os.environ.get("BOOTSTRAP_DATABASE_URL") or get_settings().database_url


@pytest.fixture()
def frische_datenbank():
    """Leere Datenbank, zu der es die Owner-Rolle garantiert noch NICHT gibt."""
    bootstrap_url = _bootstrap_url()
    admin = create_engine(bootstrap_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    try:
        with admin.connect() as conn:
            _aufraeumen(conn)
            conn.execute(text(f"CREATE DATABASE {TEST_DB}"))
    except OperationalError:
        admin.dispose()
        pytest.skip("PostgreSQL nicht erreichbar – Owner-Rollen-Test übersprungen")

    teile = urlsplit(bootstrap_url)
    basis = f"{teile.hostname}:{teile.port or 5432}"
    try:
        yield f"{teile.scheme}://{teile.username}:{teile.password}@{basis}/{TEST_DB}", basis
    finally:
        with admin.connect() as conn:
            _aufraeumen(conn)
        admin.dispose()


def _lege_owner_an(url: str, passwort: str = TEST_PASSWORT) -> None:
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            ensure_owner_role(conn, passwort, owner_role=TESTROLLE)
    finally:
        engine.dispose()


def _lege_owner_an_mit_app_rolle(url: str, app_rolle: str) -> None:
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            ensure_owner_role(conn, TEST_PASSWORT, owner_role=TESTROLLE, app_role=app_rolle)
    finally:
        engine.dispose()


def test_owner_rolle_kann_sich_danach_anmelden(frische_datenbank):
    """Der eigentliche Vorfall: die Anmeldung, die vorher `FATAL` lieferte."""
    url, basis = frische_datenbank

    _lege_owner_an(url)

    owner_engine = create_engine(f"postgresql://{TESTROLLE}:{TEST_PASSWORT}@{basis}/{TEST_DB}")
    try:
        with owner_engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar() == 1
    finally:
        owner_engine.dispose()


def test_owner_rolle_ist_kein_superuser_darf_aber_rollen_und_datenbanken_anlegen(frische_datenbank):
    """Die Attribute sind nicht kosmetisch.

    Ohne `CREATEROLE` kann der Entrypoint anschließend `abgehakt_app` nicht
    provisionieren; ohne `CREATEDB` scheitert `pg_dump`/Wiederherstellung in eine
    neue Datenbank. `SUPERUSER` wäre der GAU — dann hebelt die App die
    GoBD-Trigger aus, statt an ihnen zu scheitern.
    """
    url, _ = frische_datenbank

    _lege_owner_an(url)

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rolle = conn.execute(text(
                "SELECT rolsuper, rolcreaterole, rolcreatedb, rolcanlogin "
                "FROM pg_roles WHERE rolname = :r"
            ).bindparams(r=TESTROLLE)).one()
    finally:
        engine.dispose()

    assert rolle.rolsuper is False
    assert rolle.rolcreaterole is True
    assert rolle.rolcreatedb is True
    assert rolle.rolcanlogin is True


def test_owner_rolle_wird_eigentuemerin_der_datenbank(frische_datenbank):
    """Ohne Eigentum kein `CREATE` im Schema `public` — die Migration bräche ab.

    In PostgreSQL 15+ gehört `public` der Pseudo-Rolle `pg_database_owner`; das
    Recht, dort Tabellen anzulegen, hängt also am Datenbank-Eigentum und nicht an
    einem separaten GRANT.
    """
    url, _ = frische_datenbank

    _lege_owner_an(url)

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            eigentuemerin = conn.execute(text(
                "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = :d"
            ).bindparams(d=TEST_DB)).scalar()
    finally:
        engine.dispose()

    assert eigentuemerin == TESTROLLE


def test_owner_rolle_darf_fremde_verbindungen_beenden(frische_datenbank):
    """`pg_signal_backend`: sonst scheitert `DROP DATABASE … WITH (FORCE)`.

    Ohne diese Mitgliedschaft bricht jede Wiederherstellung ab, sobald noch eine
    Verbindung offen ist — und zwar mit `must be superuser to terminate`.
    """
    url, _ = frische_datenbank

    _lege_owner_an(url)

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            ist_mitglied = conn.execute(text(
                "SELECT pg_has_role(:r, 'pg_signal_backend', 'member')"
            ).bindparams(r=TESTROLLE)).scalar()
    finally:
        engine.dispose()

    assert ist_mitglied is True


def test_zweiter_aufruf_ist_idempotent_und_zieht_das_passwort_nach(frische_datenbank):
    """Der Entrypoint läuft bei JEDEM Start, nicht nur beim ersten.

    Zweimal aufrufen darf nicht scheitern — und ein in der `.env` geändertes
    Passwort muss ankommen, sonst sperrt sich die Installation nach einer
    Passwortrotation selbst aus.
    """
    url, basis = frische_datenbank
    _lege_owner_an(url)

    _lege_owner_an(url, passwort="zweites-passwort-nach-der-rotation")

    owner_engine = create_engine(
        f"postgresql://{TESTROLLE}:zweites-passwort-nach-der-rotation@{basis}/{TEST_DB}"
    )
    try:
        with owner_engine.connect() as conn:
            assert conn.execute(text("SELECT 1")).scalar() == 1
    finally:
        owner_engine.dispose()


def test_owner_rolle_darf_eine_fremd_angelegte_app_rolle_verwalten(frische_datenbank):
    """Selbstheilung für eine Rolle, die jemand anders angelegt hat.

    Gemessen am 2026-08-07: legt der Bootstrap-Superuser `abgehakt_app` an (was
    passiert, sobald irgendein Pfad über die Bootstrap-Verbindung läuft), fehlt
    der Owner-Rolle die ADMIN-Option — und `ensure_app_role` scheitert bei JEDEM
    weiteren Start an `permission denied to alter role`. Die Installation ist
    dann dauerhaft tot, ohne dass sich an der Konfiguration etwas geändert hat.

    `ensure_owner_role` läuft als Superuser und ist damit die einzige Stelle, die
    das noch geradeziehen kann.
    """
    url, _ = frische_datenbank
    app_rolle = f"{TESTROLLE}_app"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f"CREATE ROLE {app_rolle} LOGIN NOSUPERUSER"))
        try:
            _lege_owner_an_mit_app_rolle(url, app_rolle)

            with admin.connect() as conn:
                mit_admin_option = conn.execute(text(
                    "SELECT m.admin_option FROM pg_auth_members m "
                    "JOIN pg_roles r ON r.oid = m.roleid "
                    "JOIN pg_roles g ON g.oid = m.member "
                    "WHERE r.rolname = :app AND g.rolname = :owner"
                ).bindparams(app=app_rolle, owner=TESTROLLE)).scalar()
        finally:
            with admin.connect() as conn:
                conn.execute(text(f"DROP ROLE IF EXISTS {app_rolle}"))
    finally:
        admin.dispose()

    assert mit_admin_option is True


def test_leeres_passwort_wird_abgelehnt(frische_datenbank):
    """Fail-closed wie `ensure_app_role`: eine Rolle ohne Passwort ist keine.

    Eine still angelegte passwortlose Rolle sähe aus wie ein Erfolg und fiele
    erst bei der nächsten Anmeldung auf.
    """
    url, _ = frische_datenbank

    with pytest.raises(ValueError, match="Passwort"):
        _lege_owner_an(url, passwort="")


def test_entrypoint_legt_die_owner_rolle_vor_alembic_an():
    """Reihenfolge ist die halbe Korrektur.

    `alembic upgrade head` verbindet ALS Owner-Rolle. Läuft es vor dem Anlegen,
    ist die Rolle zwar hinterher da, der Start aber bereits abgebrochen — der
    Fehler bliebe exakt derselbe.
    """
    quelle = (Path(__file__).resolve().parent.parent / "entrypoint.sh").read_text()
    # Nur ausgeführte Zeilen: Kommentare erwähnen beide Befehle und würden die
    # Reihenfolge sonst nach Textposition statt nach Ausführung beurteilen.
    befehle = [
        zeile.strip() for zeile in quelle.splitlines()
        if zeile.strip() and not zeile.strip().startswith("#")
    ]

    anlegen = [i for i, z in enumerate(befehle) if "bootstrap_owner.py" in z]
    migrieren = [i for i, z in enumerate(befehle) if "alembic upgrade head" in z]

    assert anlegen, (
        "entrypoint.sh legt die Owner-Rolle nicht an — frische Installation startet nicht (#151)"
    )
    assert migrieren, "entrypoint.sh migriert nicht mehr"
    assert anlegen[0] < migrieren[0], (
        f"Owner-Rolle wird erst nach Alembic angelegt — zu spät: {befehle}"
    )
