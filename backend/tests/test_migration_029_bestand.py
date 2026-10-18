"""Migration 029 an Bestandsdaten: Vermerke und Weg-Spalten nachziehen.

`test_migrationskette.py` migriert eine leere Datenbank; ob das UPDATE den
Altbestand trifft und die CHECKs die Bestandszeilen annehmen, sieht dort
niemand. Der Bestand vor 029 kennt nur den kombinierten Versand — jede
Zeile ging, wenn sie ging, an Kunde UND Buchhaltung, deshalb ist
kunde_zugestellt_am = datev_sent_at die ehrliche Rueckuebersetzung.
"""
import os
import uuid

import pytest
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.config import get_settings
from tests.test_migrationskette import _alembic_config

DB = "abgehakt_migration029"


@pytest.fixture()
def auf_028():
    settings = get_settings()
    basis, _, _ = settings.database_url.rpartition("/")
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {DB}"))
    except OperationalError:
        admin.dispose()
        pytest.fail("PostgreSQL nicht erreichbar: Migration 029 nicht gemessen")
    url = f"{basis}/{DB}"
    cfg = _alembic_config(url)
    vorher = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "028")
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


def _beleg(conn, gesendet: bool):
    nr = f"RE-029-{uuid.uuid4().hex[:6]}"
    if gesendet:
        conn.execute(text(
            "INSERT INTO invoices (invoice_number, issue_date, payment_terms, status, "
            "datev_sent_at) VALUES (:nr, '2026-06-01', 'Zahlbar.', 'issued', "
            "CAST('2026-07-08 12:00:00+00' AS timestamptz))"
        ), {"nr": nr})
    else:
        conn.execute(text(
            "INSERT INTO invoices (invoice_number, issue_date, payment_terms, status) "
            "VALUES (:nr, '2026-06-01', 'Zahlbar.', 'issued')"
        ), {"nr": nr})
    return nr


def _protokollzeile(conn, beleg_id, to_email="kunde@example.de"):
    # id muss mit: Invoice.send_log.id hat nur einen ORM-Default, keinen
    # server_default — rohes SQL vergisst sie sonst still.
    conn.execute(text(
        "INSERT INTO invoice_send_log (id, invoice_id, to_email, datev_bcc, success) "
        "VALUES (gen_random_uuid(), :b, :m, true, true)"
    ), {"b": beleg_id, "m": to_email})


def test_029_fuellt_kunde_zugestellt_am_aus_datev_sent_at(auf_028):
    engine, cfg = auf_028
    with engine.begin() as conn:
        gesendet = _beleg(conn, gesendet=True)
        offen = _beleg(conn, gesendet=False)

    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        zeile = conn.execute(text(
            "SELECT datev_sent_at, kunde_zugestellt_am FROM invoices "
            "WHERE invoice_number = :nr"
        ), {"nr": gesendet}).one()
        ohne = conn.execute(text(
            "SELECT kunde_zugestellt_am FROM invoices WHERE invoice_number = :nr"
        ), {"nr": offen}).scalar()
    # Der bisherige Versand tat Kunde und Buchhaltung in einem Schritt: Der
    # Bestand darf den Kundenvermerk nicht verlieren, deshalb wird er kopiert.
    assert zeile.kunde_zugestellt_am == zeile.datev_sent_at
    assert ohne is None


def test_029_fuellt_ziel_fuer_bestandsprotokoll(auf_028):
    engine, cfg = auf_028
    with engine.begin() as conn:
        nr = _beleg(conn, gesendet=True)
        beleg_id = conn.execute(text(
            "SELECT id FROM invoices WHERE invoice_number = :nr"
        ), {"nr": nr}).scalar()
        _protokollzeile(conn, beleg_id)

    command.upgrade(cfg, "head")

    with engine.connect() as conn:
        ziel, weg = conn.execute(text(
            "SELECT ziel, weg_notiz FROM invoice_send_log"
        )).one()
    assert ziel == "kunde_und_buchhaltung"  # so lief der Versand bisher: beides
    assert weg is None


def test_029_check_ziel_wertevorrat_und_empfaenger(auf_028):
    """Die CHECKs gelten auch ohne Anwendung: ziel kennt drei Wege, und nur der
    Freitext-Vermerk (Teil 5b) darf ohne Empfaenger auskommen."""
    engine, cfg = auf_028
    with engine.begin() as conn:
        nr = _beleg(conn, gesendet=False)
        beleg_id = conn.execute(text(
            "SELECT id FROM invoices WHERE invoice_number = :nr"
        ), {"nr": nr}).scalar()
    command.upgrade(cfg, "head")

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO invoice_send_log (id, invoice_id, ziel, to_email, datev_bcc) "
                "VALUES (gen_random_uuid(), :b, 'flugpost', 'x@example.de', false)"
            ), {"b": beleg_id})
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO invoice_send_log (id, invoice_id, ziel, datev_bcc) "
                "VALUES (gen_random_uuid(), :b, 'buchhaltung', false)"
            ), {"b": beleg_id})
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO invoice_send_log (id, invoice_id, ziel, weg_notiz, datev_bcc) "
            "VALUES (gen_random_uuid(), :b, 'kunde_vermerk', "
            "'Upload ins Kundenportal am 3.10.2026', false)"
        ), {"b": beleg_id})


def test_029_downgrade_entfernt_die_neuen_spalten(auf_028):
    engine, cfg = auf_028
    with engine.begin() as conn:
        _beleg(conn, gesendet=True)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "028")
    with engine.connect() as conn:
        spalten = set(conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'invoices'"
        )).scalars())
        log_spalten = set(conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'invoice_send_log'"
        )).scalars())
    assert "kunde_zugestellt_am" not in spalten
    assert "ziel" not in log_spalten
    assert "weg_notiz" not in log_spalten
