"""031: Pflicht-FK des Versandnachweises und partielle Storno-Eindeutigkeit."""
import uuid

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from tests.test_migrationskette import migrationsdatenbank  # noqa: F401
from tests.test_migration_030_aufstellung import _gueltige_aufstellung_mit_anlage


def test_migration_031_constraints(migrationsdatenbank):
    from alembic import command
    url, cfg = migrationsdatenbank
    command.upgrade(cfg, "head")
    engine = create_engine(url)
    with engine.connect() as conn:
        original = _gueltige_aufstellung_mit_anlage(conn, "a" * 64)
        inspector = inspect(conn)
        columns = {c["name"]: c for c in inspector.get_columns("aufstellung_send_logs")}
        assert not columns["aufstellung_id"]["nullable"]
        assert not columns["to_email"]["nullable"]
        assert inspector.get_foreign_keys("aufstellung_send_logs")[0]["referred_table"] == "aufstellungen"
        sql = text("INSERT INTO aufstellungen (id, nummer, customer_id, status, "
                   "leistung_von, leistung_bis, zahlungsnummer, zahlungsdatum, "
                   "waehrung, brutto, quellensteuer, netto, storniert_id) "
                   "SELECT :id, :nr, customer_id, :status, leistung_von, leistung_bis, "
                   "zahlungsnummer, zahlungsdatum, waehrung, brutto, quellensteuer, netto, id "
                   "FROM aufstellungen WHERE id = :original")
        conn.execute(sql, dict(id=uuid.uuid4(), nr="AA-S1", status="draft", original=original))
        conn.commit()
        with pytest.raises(IntegrityError):
            conn.execute(sql, dict(id=uuid.uuid4(), nr="AA-S2", status="draft", original=original))
        conn.rollback()
        conn.execute(sql, dict(id=uuid.uuid4(), nr="AA-S3", status="discarded", original=original))
        conn.commit()
    engine.dispose()
