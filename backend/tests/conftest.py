"""
Gemeinsame Fixtures. pg_engine/pg_session stellen eine echte Postgres-Wegwerf-DB
(abgehakt_test) bereit — nötig für Tests von SQLAlchemy-Event-Listenern,
die mit Mocks nicht beweisbar sind. Ohne erreichbares Postgres: skip.
"""
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.db.immutability_triggers import install
from app.db.roles import ensure_app_role, resolve_owner_role
from app.main import app

TEST_DB_NAME = "abgehakt_test"


def _vektor_lage() -> str:
    from tests.helpers.formatvektoren import (
        UMGEBUNGSVARIABLE,
        vektorordner,
    )

    ordner = vektorordner()
    if ordner:
        return f"formatvektoren: gemessen gegen {ordner}"
    return (
        "formatvektoren: NICHT GEMESSEN, kein Vektorordner mit protokoll.json "
        f"({UMGEBUNGSVARIABLE} setzen)"
    )


def pytest_report_header(config):
    return _vektor_lage()


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Sagen, ob gegen die Formatvektoren gemessen wurde (abgehakt#72).

    Fehlt der Vektorordner, sammelt tests/vektoren/ nichts ein: kein Skip, denn ein
    fehlender Ordner ist kein fehlgeschlagener Test, und ein Skip waere in
    diesem Repository ein Fehlschlag. Ohne diese Zeile saehe so ein Lauf
    genauso gruen aus wie einer, der wirklich gemessen hat.

    Am Ende und nicht nur im Kopf, weil der kanonische Lauf `pytest -q` fahrt
    und `-q` den Kopf unterdrueckt: eine Sichtbarkeit, die der eigene
    Standardlauf verschluckt, ist keine.
    """
    from tests.helpers.formatvektoren import vektorordner

    lage = _vektor_lage()
    if vektorordner():
        terminalreporter.write_line(lage)
    else:
        terminalreporter.write_sep("=", "formatvektoren", red=True, bold=True)
        terminalreporter.write_line(lage, red=True)


@pytest.fixture(scope="session", autouse=True)
def test_archiv(tmp_path_factory):
    """Belege aus Tests in ein Wegwerf-Verzeichnis lenken, nicht ins echte Archiv.

    `docker-compose.yml` hängt `./storage` in den Container. Ohne diese Fixture
    landen Testbelege (`RE-E2E-…`, `RE-SEND-…`) samt liegengebliebener
    Zwischenstufen in `storage/pdfs/` — zwischen den echten Rechnungen der
    Installation, von denen sie später nicht mehr zu unterscheiden sind.

    `autouse` und sitzungsweit: die Umlenkung darf nicht davon abhängen, dass
    ein Test daran denkt, sie anzufordern.

    Gesetzt wird das Attribut auf dem zwischengespeicherten Settings-Objekt
    (`get_settings()` ist `lru_cache`), das alle Module teilen. Alle Zugriffe im
    Anwendungscode lesen `settings.storage_path` erst beim Aufruf, keiner merkt
    sich den Pfad beim Import — deshalb wirkt die Umlenkung überall.

    Der Schlüssel (`secret.key`) ist davon nicht betroffen: er wird beim ersten
    `get_settings()` gelesen, also bevor diese Fixture greift.

    Wächter: tests/test_testumgebung.py
    """
    ziel = tmp_path_factory.mktemp("archiv")
    (ziel / "pdfs").mkdir()
    (ziel / "xml").mkdir()

    einstellungen = get_settings()
    vorher = einstellungen.storage_path
    einstellungen.storage_path = ziel
    yield ziel
    einstellungen.storage_path = vorher


@pytest.fixture(scope="session")
def pg_engine():
    settings = get_settings()
    base_url, _, _ = settings.database_url.rpartition("/")
    admin_engine = create_engine(settings.database_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
    except OperationalError:
        admin_engine.dispose()
        pytest.skip("PostgreSQL nicht erreichbar – DB-Integrationstests übersprungen")

    import app.models  # noqa: F401 — registriert alle Tabellen an Base.metadata
    from app.database import Base

    engine = create_engine(f"{base_url}/{TEST_DB_NAME}")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        install(conn)                                     # GoBD-Trigger in die Test-DB (wie Migration in Prod)
        # Owner = die Rolle aus DATABASE_URL (sie hat die Tabellen angelegt) — nicht
        # hart die Owner-Rolle: ALTER DEFAULT PRIVILEGES FOR ROLE <fremd> wäre permission denied.
        ensure_app_role(
            conn,
            settings.db_app_password,
            owner_role=resolve_owner_role(settings.database_url),
        )
    yield engine
    engine.dispose()
    with admin_engine.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {TEST_DB_NAME} WITH (FORCE)"))
    admin_engine.dispose()


@pytest.fixture()
def pg_session(pg_engine):
    """Frische Session pro Test; alle Tabellen vorher geleert (Test-Isolation)."""
    with pg_engine.connect() as conn:
        for tbl in ("invoices", "invoice_items", "customers"):
            conn.execute(text(f"ALTER TABLE {tbl} DISABLE TRIGGER USER"))
        try:
            conn.execute(text(
                "TRUNCATE app_config, audit_log, validation_results, uebergabe_eingaenge, "
                "invoice_items, invoices, customers, company RESTART IDENTITY CASCADE"
            ))
        finally:
            for tbl in ("invoices", "invoice_items", "customers"):
                conn.execute(text(f"ALTER TABLE {tbl} ENABLE TRIGGER USER"))
        conn.commit()
    TestSession = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)
    session = TestSession()

    # Seed company (Singleton id=1) via raw SQL — migrations laufen nicht in Base.metadata.create_all
    # (ORM würde den Audit-Listener triggern)
    with pg_engine.connect() as conn:
        conn.execute(text(
            # setup_completed_at gehört dazu: diese Fixture bildet eine EINGERICHTETE
            # Installation ab (vollständige Firma inkl. Steuernummer). Ohne das Flag
            # liefe jeder Test in das Ersteinrichtungs-Tor (#99 §4.1) — Tests, die
            # die Ersteinrichtung selbst prüfen, setzen es gezielt zurück.
            "INSERT INTO company (id, name, address_line1, zip_code, city, country, tax_number, vat_id, "
            "invoice_prefix, invoice_year_in_number, invoice_counter, payment_terms_default, setup_completed_at) "
            "VALUES (1, 'Muster Handwerk GmbH', 'Musterstraße 1', '12345', 'Musterstadt', 'DE', '12/345/67890', 'DE123456789', "
            "'RE', true, 0, 'Zahlbar innerhalb von 14 Tagen ohne Abzug.', now()) "
            "ON CONFLICT DO NOTHING"
        ))
        conn.commit()

    yield session
    session.close()


@pytest.fixture()
def client(pg_session):
    """TestClient mit pg_session als DB; Overrides werden nach dem Test geleert."""
    app.dependency_overrides[get_db] = lambda: pg_session
    with TestClient(app, follow_redirects=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def pg_app_engine(pg_engine):
    """Engine, die als abgehakt_app (Least-Privilege) gegen die Test-DB verbindet.
    Hängt an pg_engine → Rolle + Grants sind dann bereits provisioniert."""
    settings = get_settings()
    parsed = urlparse(settings.database_url)
    pw = settings.db_app_password
    port = parsed.port or 5432
    url = f"postgresql://{settings.db_app_user}:{pw}@{parsed.hostname}:{port}/{TEST_DB_NAME}"
    engine = create_engine(url, pool_pre_ping=True)
    yield engine
    engine.dispose()
