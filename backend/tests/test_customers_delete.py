"""
POST /customers/{id}/loeschen — Soft-Delete (GoBD: Kunden NIE hart löschen).

Audit-#5: Die Route war ungetestet, obwohl die GoBD-Regel „niemals hard-deleten"
zentral ist. Echte pg_session-Integration (nicht Mock), damit bewiesen ist:
  - deleted_at wird gesetzt, die Zeile bleibt physisch erhalten (kein DELETE)
  - der Kunde verschwindet aus der Liste (deleted_at-Filter greift)
  - der Vorgang landet als Audit-Zeile (action=update, deleted_at im new_values)
  - unbekannte ID → 404
"""
import uuid

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import AuditLog


def teardown_function():
    app.dependency_overrides.clear()


def _customer(pg_session, number="K-DEL-1") -> Customer:
    c = Customer(
        customer_number=number, name="Löschkandidat GmbH",
        address_line1="Weg 1", zip_code="80331", city="München", country="DE",
    )
    pg_session.add(c)
    pg_session.commit()
    return c


def _client(pg_session) -> TestClient:
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def test_loeschen_setzt_deleted_at_und_loescht_nicht_hart(pg_session):
    c = _customer(pg_session)
    cid = c.id
    resp = _client(pg_session).post(f"/customers/{cid}/loeschen")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/customers"

    # Zeile existiert weiter (kein Hard-Delete), aber deleted_at ist gesetzt
    row = pg_session.query(Customer).filter(Customer.id == cid).first()
    assert row is not None, "Kunde wurde HART gelöscht — GoBD-Verstoß"
    assert row.deleted_at is not None


def test_geloeschter_kunde_verschwindet_aus_liste(pg_session):
    c = _customer(pg_session, number="K-DEL-2")
    client = _client(pg_session)
    assert "Löschkandidat GmbH" in client.get("/customers/").text
    client.post(f"/customers/{c.id}/loeschen")
    assert "Löschkandidat GmbH" not in client.get("/customers/").text


def test_loeschen_schreibt_audit_zeile(pg_session):
    c = _customer(pg_session, number="K-DEL-3")
    cid = c.id
    _client(pg_session).post(f"/customers/{cid}/loeschen")

    audits = (
        pg_session.query(AuditLog)
        .filter(AuditLog.table_name == "customers", AuditLog.record_id == str(cid))
        .all()
    )
    updates = [a for a in audits if a.action == "update"]
    assert updates, "Kein Audit-Update-Eintrag für den Soft-Delete"
    assert any(u.new_values and u.new_values.get("deleted_at") for u in updates)
    # Kein Hard-Delete → keine 'delete'-Audit-Zeile
    assert not any(a.action == "delete" for a in audits)


def test_loeschen_unbekannte_id_404(pg_session):
    resp = _client(pg_session).post(f"/customers/{uuid.uuid4()}/loeschen")
    assert resp.status_code == 404
