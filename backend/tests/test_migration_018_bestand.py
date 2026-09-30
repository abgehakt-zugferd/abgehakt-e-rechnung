"""Migration 018 an Bestandsdaten: bezahlt_am fuer paid aus updated_at.

`test_migrationskette.py` migriert eine leere Datenbank; ob das UPDATE den
Altbestand trifft, sieht dort niemand.
"""
import os
import uuid
from datetime import date

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from app.config import get_settings
from tests.test_migrationskette import _alembic_config

DB = "abgehakt_migration018"


@pytest.fixture()
def auf_017():
    settings = get_settings()
    basis, _, _ = settings.database_url.rpartition("/")
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {DB}"))
    except OperationalError:
        admin.dispose()
        pytest.fail("PostgreSQL nicht erreichbar: Migration 018 nicht gemessen")
    url = f"{basis}/{DB}"
    cfg = _alembic_config(url)
    vorher = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "017")
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


def _kunde(conn):
    kid = uuid.uuid4()
    conn.execute(text(
        "INSERT INTO customers (id, customer_number, name, address_line1, zip_code, city) "
        "VALUES (:id, :nr, 'Probe Migration GmbH', 'Probeweg 4', '80331', 'Muenchen')"
    ), {"id": kid, "nr": f"K-{uuid.uuid4().hex[:6]}"})
    return kid


def _beleg(conn, kunde, status, updated_at_utc: str):
    nr = f"RE-{uuid.uuid4().hex[:6]}"
    conn.execute(text(
        "INSERT INTO invoices ("
        "invoice_number, customer_id, issue_date, due_date, status, updated_at"
        ") VALUES ("
        ":nr, :k, '2026-06-01', '2026-06-15', :st, CAST(:ua AS timestamptz)"
        ")"
    ), {"nr": nr, "k": kunde, "st": status, "ua": updated_at_utc})
    return nr


def test_018_fuellt_bezahlt_am_fuer_paid_aus_updated_at(auf_017):
    engine, cfg = auf_017
    with engine.begin() as conn:
        kunde = _kunde(conn)
        paid_nr = _beleg(conn, kunde, "paid", "2025-12-15 23:30:00+00")
        issued_nr = _beleg(conn, kunde, "issued", "2026-01-10 12:00:00+00")

    command.upgrade(cfg, "018")

    with engine.connect() as conn:
        paid = conn.execute(text(
            "SELECT bezahlt_am FROM invoices WHERE invoice_number = :nr"
        ), {"nr": paid_nr}).scalar()
        issued = conn.execute(text(
            "SELECT bezahlt_am FROM invoices WHERE invoice_number = :nr"
        ), {"nr": issued_nr}).scalar()
        spalten = set(conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'invoices'"
        )).scalars())
    # 23:30 UTC am 15.12. ist in Europe/Berlin schon 00:30 am 16.12.
    assert paid == date(2025, 12, 16)
    assert issued is None
    assert "bezahlt_am" in spalten


def test_018_downgrade_entfernt_spalte(auf_017):
    engine, cfg = auf_017
    with engine.begin() as conn:
        _beleg(conn, _kunde(conn), "paid", "2026-06-10 10:00:00+00")
    command.upgrade(cfg, "018")
    command.downgrade(cfg, "017")
    with engine.connect() as conn:
        spalten = set(conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'invoices'"
        )).scalars())
    assert "bezahlt_am" not in spalten
