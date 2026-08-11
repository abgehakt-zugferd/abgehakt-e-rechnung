"""„Ist die Ersteinrichtung erledigt?" ist ein Zustand, kein Ratespiel (#99 §4.0/§4.1).

Vorher entschied die Heuristik `not company.tax_number and not company.vat_id`
(`main.py:86`) darüber. Die kippt zurück, sobald jemand die Steuernummer leert —
eine eingerichtete Installation erklärt sich dann selbst für uneingerichtet.
Verbindlich ist deshalb `company.setup_completed_at`.

Dazu: eine frisch angelegte Firma darf keine fremden Werte tragen. Die steckten an
ZWEI Stellen — `server_default` in Migration 001 und `default=` im ORM-Modell.
"""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.main import app
from app.models.company import Company

def _firma(pg_session, *, eingerichtet: bool, steuernummer="12/345/67890"):
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    firma.setup_completed_at = (
        datetime(2026, 7, 1, tzinfo=timezone.utc) if eingerichtet else None
    )
    firma.tax_number = steuernummer
    pg_session.commit()
    return firma


def _dashboard(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    try:
        return TestClient(app, follow_redirects=False).get("/dashboard")
    finally:
        app.dependency_overrides.clear()


def test_flag_haelt_auch_ohne_steuernummer(pg_session):
    """Der Grund für den Umbau: die alte Heuristik hätte hier wieder
    „einrichten!" gerufen, obwohl die Einrichtung nachweislich stattfand."""
    _firma(pg_session, eingerichtet=True, steuernummer=None)
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    firma.vat_id = None
    pg_session.commit()

    r = _dashboard(pg_session)

    assert r.status_code == 200


def test_firma_ohne_angaben_laesst_sich_nicht_mehr_anlegen(pg_session):
    """Der Verhaltensbeweis für die entfernten Defaults: vorher füllte das ORM
    stillschweigend „Muster Handwerk GmbH, Musterstraße 1, 12345 Musterstadt" ein,
    und eine frische Installation trug fremde Firmendaten, ohne dass jemand
    etwas eingegeben hätte. Ohne Default schlägt der Insert auf, wie er soll.

    Ein Test auf `information_schema.column_default` stünde hier vergeblich: die
    Test-DB entsteht über `Base.metadata.create_all` (conftest), Migrationen
    laufen dort nicht. Die Migration selbst wird gegen die echte DB per
    `alembic upgrade head` + `\\d company` verifiziert (docs/ARCHITEKTUR.md).
    """
    pg_session.add(Company(id=2))

    with pytest.raises(IntegrityError):
        pg_session.flush()

    pg_session.rollback()


def test_company_traegt_keine_fremden_defaults_mehr_im_modell():
    """Zweite Fundstelle: das ORM-Modell setzte dieselben Werte nochmal."""
    for spalte in ("name", "address_line1", "zip_code", "city"):
        default = Company.__table__.c[spalte].default
        assert default is None, f"{spalte} hat noch einen ORM-Default: {default!r}"
