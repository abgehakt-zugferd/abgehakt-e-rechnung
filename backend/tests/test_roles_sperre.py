"""`ensure_app_role` und die Rollenanlage unter Gleichzeitigkeit.

Rollen leben im ganzen Postgres-Cluster, nicht in einer Datenbank. Laufen zwei
Provisionierungen gleichzeitig (parallele Testprozesse, parallele Starts),
scheitert CREATE ROLE an `duplicate_object` oder ALTER ROLE an `tuple
concurrently updated`; `IF NOT EXISTS` schliesst das Zeitfenster nicht.

Drei Wachter:
- deterministisch: haelt jemand die Sperre, kommt `ensure_app_role` nicht voran;
- Rennen in EINER Datenbank: die Sperre in `ensure_app_role` haelt es zusammen;
- Rennen ueber getrennte Datenbanken: Advisory-Sperren sind pro Datenbank,
  dort traegt die clusterweite Sperre der Tests (helpers/rollensperre.py).
Die Rennen laufen ueber eine Barriere und scheitern ohne Sperre in fast jedem
Aufruf; trotzdem bleibt das Deterministische der Anker.
"""
import threading
from collections import Counter
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.db.roles import APP_ROLE_LOCK_KEY, ensure_app_role, resolve_owner_role
from tests.helpers.rollensperre import clusterweite_rollensperre
from tests.helpers.testdb import je_prozess

SPERR_ROLLE = je_prozess("abgehakt_test_sperre")
RENNEN_FAEDEN = 6
RENNEN_RUNDEN = 3
SCHUTZTABELLEN = (
    "invoices", "customers", "aufstellungen", "aufstellung_anlagen", "uebergabe_eingaenge",
)


def _rolle_loeschen(conn, rolle: str) -> None:
    if conn.execute(
        text("SELECT 1 FROM pg_roles WHERE rolname = :r").bindparams(r=rolle)
    ).scalar():
        conn.execute(text(f"DROP OWNED BY {rolle}"))
        conn.execute(text(f"DROP ROLE {rolle}"))


@pytest.fixture()
def aufraeumen(pg_engine):
    yield
    with pg_engine.begin() as conn:
        _rolle_loeschen(conn, SPERR_ROLLE)


@contextmanager
def _sperre_halten(engine):
    """Haelt die Sperre in einer offenen Transaktion, bis der Block endet."""
    bereit = threading.Event()
    freigeben = threading.Event()

    def halter():
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=APP_ROLE_LOCK_KEY))
                bereit.set()
                freigeben.wait(timeout=30)

    faden = threading.Thread(target=halter)
    faden.start()
    assert bereit.wait(timeout=10), "Sperre nicht erhalten"
    try:
        yield
    finally:
        freigeben.set()
        faden.join(timeout=10)


def test_ensure_app_role_wartet_auf_die_sperre(pg_engine, aufraeumen):
    owner = resolve_owner_role(get_settings().database_url)
    fertig = threading.Event()
    fehler: list[BaseException] = []

    def provisionieren():
        try:
            with pg_engine.begin() as conn:
                ensure_app_role(conn, "sperre-testpasswort", app_role=SPERR_ROLLE, owner_role=owner)
        except BaseException as exc:  # noqa: BLE001 - an den Test weiterreichen
            fehler.append(exc)
        finally:
            fertig.set()

    with _sperre_halten(pg_engine):
        faden = threading.Thread(target=provisionieren)
        faden.start()
        # Ohne Sperre ist die Provisionierung in Millisekunden durch.
        assert not fertig.wait(timeout=1.5), "ensure_app_role hat die gehaltene Sperre ignoriert"

    assert fertig.wait(timeout=15), "ensure_app_role lief nach Freigabe nicht weiter"
    faden.join(timeout=5)
    assert not fehler, fehler


def _rennen(engines, rolle_fuer_runde, owner, mit_clustersperre=None) -> Counter:
    """Alle Faeden rufen ensure_app_role fuer dieselbe frische Rolle gleichzeitig."""
    fehler: Counter = Counter()
    for runde in range(RENNEN_RUNDEN):
        rolle = rolle_fuer_runde(runde)
        barriere = threading.Barrier(len(engines))

        def arbeit(engine):
            barriere.wait()
            try:
                def lauf():
                    with engine.begin() as conn:
                        ensure_app_role(conn, "rennen-passwort", app_role=rolle, owner_role=owner)

                if mit_clustersperre:
                    with clusterweite_rollensperre(mit_clustersperre):
                        lauf()
                else:
                    lauf()
            except Exception as exc:  # noqa: BLE001
                fehler[type(getattr(exc, "orig", exc)).__name__] += 1

        faeden = [threading.Thread(target=arbeit, args=(e,)) for e in engines]
        for f in faeden:
            f.start()
        for f in faeden:
            f.join()
    return fehler


def test_gleichzeitige_provisionierung_in_einer_datenbank(pg_engine):
    owner = resolve_owner_role(get_settings().database_url)
    namen = [je_prozess(f"abgehakt_test_rennen_a{i}") for i in range(RENNEN_RUNDEN)]
    try:
        fehler = _rennen([pg_engine] * RENNEN_FAEDEN, lambda r: namen[r], owner)
    finally:
        with pg_engine.begin() as conn:
            for n in namen:
                _rolle_loeschen(conn, n)
    assert not fehler, dict(fehler)


ROLLEN_B = [je_prozess(f"abgehakt_test_rennen_b{i}") for i in range(RENNEN_RUNDEN)]


@pytest.fixture()
def getrennte_datenbanken():
    """Je Faden eine eigene, minimale Datenbank mit den Tabellen der Rechte-Matrix."""
    url = get_settings().database_url
    basis = url.rpartition("/")[0]
    namen = [je_prozess(f"abgehakt_test_rennen_db{i}") for i in range(RENNEN_FAEDEN)]
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    engines = []
    try:
        with admin.connect() as conn:
            for n in namen:
                conn.execute(text(f"DROP DATABASE IF EXISTS {n} WITH (FORCE)"))
                conn.execute(text(f"CREATE DATABASE {n}"))
        for n in namen:
            e = create_engine(f"{basis}/{n}")
            engines.append(e)
            with e.begin() as conn:
                for t in SCHUTZTABELLEN:
                    conn.execute(text(f"CREATE TABLE {t} (id int)"))
        yield url, engines
    finally:
        for e in engines:
            e.dispose()
        with admin.connect() as conn:
            for n in namen:
                conn.execute(text(f"DROP DATABASE IF EXISTS {n} WITH (FORCE)"))
            # Erst nach den Datenbanken: dort hingen die Grants der Rollen.
            for r in ROLLEN_B:
                conn.execute(text(f"DROP ROLE IF EXISTS {r}"))
        admin.dispose()


def test_gleichzeitige_provisionierung_ueber_getrennte_datenbanken(getrennte_datenbanken):
    url, engines = getrennte_datenbanken
    owner = resolve_owner_role(url)
    fehler = _rennen(engines, lambda r: ROLLEN_B[r], owner, mit_clustersperre=url)
    assert not fehler, dict(fehler)
