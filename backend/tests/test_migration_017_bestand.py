"""Migration 017 an Bestandsdaten: sie schreibt jeden vorhandenen Kunden um.

`test_migrationskette.py` migriert eine LEERE Datenbank; ob das UPDATE den
Altbestand trifft, sieht dort niemand. In der Produktivdatenbank standen am
2026-09-30 alle 7 Kunden ungeprueft auf `regelbesteuert`. Genau dieser Zustand
wird hier auf 016 angelegt und durch 017 hindurch und wieder zurueck gefuehrt.
"""
import os
import uuid

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from tests.test_migrationskette import _alembic_config

DB = "abgehakt_migration017"


@pytest.fixture()
def auf_016():
    settings = get_settings()
    basis, _, _ = settings.database_url.rpartition("/")
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {DB}"))
    except OperationalError:
        admin.dispose()
        pytest.fail("PostgreSQL nicht erreichbar: Migration 017 nicht gemessen")
    url = f"{basis}/{DB}"
    cfg = _alembic_config(url)
    vorher = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "016")
        yield engine, cfg
    finally:
        engine.dispose()
        if vorher is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = vorher
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)"))
        admin.dispose()


def _kunde(conn, nummer, status):
    kid = uuid.uuid4()
    conn.execute(text(
        "INSERT INTO customers (id, customer_number, name, address_line1, zip_code, city, ust_status) "
        "VALUES (:id, :nr, 'Jürgen Weiß', 'Weg 1', '80331', 'München', :st)"
    ), {"id": kid, "nr": nummer, "st": status})
    return kid


def _beleg(conn, kunde, art):
    conn.execute(text(
        "INSERT INTO invoices (invoice_number, customer_id, issue_date, due_date, invoice_type) "
        "VALUES (:nr, :k, '2026-09-01', '2026-09-15', :art)"
    ), {"nr": f"RE-{uuid.uuid4().hex[:6]}", "k": kunde, "art": art})


def _stand(conn, kid):
    return conn.execute(text(
        "SELECT ust_status, gutschriftempfaenger FROM customers WHERE id = :id"
    ), {"id": kid}).one()


def test_017_macht_den_bestand_ungeklaert_und_markiert_nur_389_kunden(auf_016):
    engine, cfg = auf_016
    with engine.begin() as conn:
        regel = _kunde(conn, "K-1", "regelbesteuert")
        klein = _kunde(conn, "K-2", "kleinunternehmer")
        autor = _kunde(conn, "K-3", "regelbesteuert")
        _beleg(conn, regel, None)
        _beleg(conn, autor, "self_billing")

    command.upgrade(cfg, "017")

    with engine.connect() as conn:
        assert tuple(_stand(conn, regel)) == ("ungeklaert", False)
        assert tuple(_stand(conn, klein)) == ("ungeklaert", False)
        assert tuple(_stand(conn, autor)) == ("ungeklaert", True)
        neu = conn.execute(text(
            "INSERT INTO customers (customer_number, name, address_line1, zip_code, city) "
            "VALUES ('K-4', 'Neu', 'Weg 2', '10115', 'Berlin') RETURNING ust_status"
        )).scalar()
        conn.rollback()
    assert neu == "ungeklaert"


def test_017_downgrade_kehrt_zu_regelbesteuert_zurueck(auf_016):
    engine, cfg = auf_016
    with engine.begin() as conn:
        kid = _kunde(conn, "K-1", "regelbesteuert")
    command.upgrade(cfg, "017")

    command.downgrade(cfg, "016")

    with engine.connect() as conn:
        status = conn.execute(text(
            "SELECT ust_status FROM customers WHERE id = :id"
        ), {"id": kid}).scalar()
        spalten = set(conn.execute(text(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'customers'"
        )).scalars())
    assert status == "regelbesteuert"
    assert not {"gutschriftempfaenger", "tax_number", "ust_status_bestaetigt_am"} & spalten
