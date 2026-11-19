"""NOT VALID trägt: Altzeilen mit leerem Land bremsen das Upgrade nicht (035, 036).

Fremde Installationen können Zeilen mit country='' haben. Die CHECKs der Migrationen
035 (customers) und 036 (company) sind deshalb NOT VALID: das Upgrade läuft mit der
Altzeile durch, neue Zeilen mit '' scheitern danach und der Fehler nennt den
Constraint. Ohne NOT VALID bräche das Upgrade bei der fremden Installation ab.
"""
import os

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.config import get_settings
from tests.helpers.testdb import je_prozess
from tests.helpers.verbindungsfehler import ist_verbindungsfehler
from tests.test_migrationskette import _alembic_config

DB = je_prozess("abgehakt_altzeilen")

NEUER_KUNDE = ("INSERT INTO customers (customer_number, name, address_line1, zip_code, "
               "city, country) VALUES ('{n}', 'Kunde', 'Weg 1', '10115', 'Berlin', '')")


@pytest.fixture
def wegwerf_db():
    settings = get_settings()
    basis, _, _ = settings.database_url.rpartition("/")
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    try:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {DB}"))
    except OperationalError as fehler:
        admin.dispose()
        if not ist_verbindungsfehler(fehler):
            raise   # Rechte, fehlende Datenbank usw. sind Fehler, kein Skip
        pytest.skip("PostgreSQL nicht erreichbar – Migrationstest übersprungen")
    url = f"{basis}/{DB}"
    vorher = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        yield url, _alembic_config(url)
    finally:
        if vorher is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = vorher
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)"))
        admin.dispose()


def _scheitert_mit(url, sql, constraint):
    engine = create_engine(url)
    try:
        with pytest.raises(IntegrityError) as fehler:
            with engine.connect() as conn:
                conn.execute(text(sql))
                conn.commit()
        assert constraint in str(fehler.value)
    finally:
        engine.dispose()


def test_altzeile_kunde_mit_leerem_land_bremst_035_nicht(wegwerf_db):
    url, cfg = wegwerf_db
    command.upgrade(cfg, "034")
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text(NEUER_KUNDE.format(n="K-ALT-1")))
        conn.commit()
    engine.dispose()

    command.upgrade(cfg, "head")

    engine = create_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT count(*) FROM customers WHERE country = ''")).scalar() == 1
    engine.dispose()
    _scheitert_mit(url, NEUER_KUNDE.format(n="K-NEU-1"), "ck_customers_country_nicht_leer")


def test_altzeile_firma_mit_leerem_land_bremst_036_nicht(wegwerf_db):
    url, cfg = wegwerf_db
    command.upgrade(cfg, "035")
    engine = create_engine(url)
    with engine.connect() as conn:
        conn.execute(text("UPDATE company SET country = ''"))
        conn.commit()
    engine.dispose()

    command.upgrade(cfg, "head")

    engine = create_engine(url)
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT count(*) FROM company WHERE country = ''")).scalar() == 1
    engine.dispose()
    _scheitert_mit(
        url, "INSERT INTO company (id, name, address_line1, zip_code, city, country) "
             "VALUES (2, 'Firma', 'Weg 1', '10115', 'Berlin', '')",
        "ck_company_country_nicht_leer")

