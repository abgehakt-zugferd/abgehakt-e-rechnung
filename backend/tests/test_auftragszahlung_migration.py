"""Der bestehende CHECK muss auch bei Migration die offene Vorgabe erlauben."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.test_auftragszahlung import _entwurf

NAME = "ck_invoices_faelligkeit_oder_bedingungen"


def test_migration_erlaubt_nur_unfertige_rechnungsauftraege(pg_session):
    inv, _, _ = _entwurf(pg_session)
    pfad = Path(__file__).resolve().parents[1] / "alembic/versions/032_auftragszahlung.py"
    spec = importlib.util.spec_from_file_location("migration_032", pfad)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    verbindung = pg_session.connection()
    with Operations.context(MigrationContext.configure(verbindung)):
        migration.downgrade()
        with pytest.raises(IntegrityError), pg_session.begin_nested():
            pg_session.execute(text("UPDATE invoices SET payment_terms = NULL WHERE id = :id"), {"id": inv.id})
        migration.upgrade()
        pg_session.execute(text("UPDATE invoices SET payment_terms = NULL WHERE id = :id"), {"id": inv.id})
        for aenderung in ("status = 'issued'", "auftragsschluessel = NULL, auftragsschluessel_offen = NULL",
                          "uebergabe_beleg_sha256 = NULL", "invoice_type = 'self_billing'"):
            with pytest.raises(IntegrityError), pg_session.begin_nested():
                pg_session.execute(text(f"UPDATE invoices SET {aenderung} WHERE id = :id"), {"id": inv.id})
    pg_session.rollback()
