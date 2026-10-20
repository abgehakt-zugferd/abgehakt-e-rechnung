"""Bausteine fuer Tests zur abgeschlossenen Firmeneinrichtung (#170)."""
from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer


def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def kunde(pg_session):
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Probe Kunde GmbH",
        address_line1="Weg 1",
        zip_code="80331",
        city="Muenchen",
        country="DE",
    )
    pg_session.add(c)
    pg_session.flush()
    return c


def leere_firma(pg_session):
    """Firmenzeile wie nach Migration 001: vorhanden, Einrichtung offen."""
    firma = pg_session.query(Company).filter(Company.id == 1).one()
    firma.setup_completed_at = None
    firma.name = ""
    firma.address_line1 = ""
    firma.zip_code = ""
    firma.city = ""
    firma.tax_number = None
    firma.vat_id = None
    pg_session.commit()
    return firma
