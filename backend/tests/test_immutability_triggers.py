"""
B2 — DB-Trigger (GoBD-Unveränderlichkeit) + Least-Privilege-Rolle.
Beide Schichten sind nur in echtem Postgres beweisbar (pg_session).

Trigger-Schicht: Verbindung als Bootstrap-Admin (im Test-Env ist das ein
Superuser) — der STÄRKERE Nachweis: die Trigger fangen sogar ein versehentliches
DELETE/TRUNCATE eines Superusers (genau der 2026-07-08-Fall).
"""
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import InternalError


def _seed_draft(pg_engine):
    """Kunde + Draft-Rechnung + Position via RAW SQL (umgeht ORM-Guards) — für
    DELETE-Tests (BEFORE DELETE FOR EACH ROW feuert nur bei vorhandenen Zeilen)."""
    cid, iid, itid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    cnum = f"K-{uuid.uuid4().hex[:6]}"
    inum = f"RE-{uuid.uuid4().hex[:6]}"
    with pg_engine.begin() as c:
        c.execute(text(
            "INSERT INTO customers (id, customer_number, name, address_line1, zip_code, city, country, is_active) "
            "VALUES (:id,:cnum,'Test','Str 1','12345','Stadt','DE',true)"), {"id": cid, "cnum": cnum})
        c.execute(text(
            "INSERT INTO invoices (id, invoice_number, customer_id, issue_date, due_date, currency, "
            "net_total, tax_total, gross_total, status, zugferd_profile, tax_category) "
            "VALUES (:id,:inum,:cid,'2026-01-01','2026-01-15','EUR',100,19,119,'draft','EN16931','S')"),
            {"id": iid, "inum": inum, "cid": cid})
        c.execute(text(
            "INSERT INTO invoice_items (id, invoice_id, position, description, unit, quantity, unit_price, "
            "tax_rate, net_amount, tax_amount, gross_amount) "
            "VALUES (:id,:iid,1,'Pos','Stück',1,100,19,100,19,119)"), {"id": itid, "iid": iid})
    return cid, iid, itid


def _seed_customer(pg_engine):
    """Bare customer with no invoice (for testing customers DELETE trigger in isolation)."""
    cid = uuid.uuid4()
    cnum = f"K-{uuid.uuid4().hex[:6]}"
    with pg_engine.begin() as c:
        c.execute(text(
            "INSERT INTO customers (id, customer_number, name, address_line1, zip_code, city, country, is_active) "
            "VALUES (:id,:cnum,'Test','Str 1','12345','Stadt','DE',true)"), {"id": cid, "cnum": cnum})
    return cid


def _seed_aufstellung(pg_engine):
    """Kunde + Aufstellung + eine Anlage via RAW SQL — die Aufstellung ist
    kein Beleg der Rechnung, hat aber dieselben GoBD-Trigger (Bauschritt 7a)."""
    cid, aid, anid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with pg_engine.begin() as c:
        c.execute(text(
            "INSERT INTO customers (id, customer_number, name, address_line1, zip_code, city, country, is_active) "
            "VALUES (:id,:cnum,'Test','Str 1','12345','Stadt','DE',true)"),
            {"id": cid, "cnum": f"K-{uuid.uuid4().hex[:6]}"})
        c.execute(text(
            "INSERT INTO aufstellungen (id, nummer, customer_id, leistung_von, leistung_bis, "
            "zahlungsnummer, zahlungsdatum, waehrung, brutto, quellensteuer, netto) "
            "VALUES (:id,:nummer,:cid,'2026-09-01','2026-09-30','4711','2026-09-30','EUR',100,0,100)"),
            {"id": aid, "nummer": f"AA-{uuid.uuid4().hex[:6]}", "cid": cid})
        c.execute(text(
            "INSERT INTO aufstellung_anlagen (id, aufstellung_id, quelle, dateiname, sha256, "
            "groesse, medientyp) VALUES (:id,:aid,'abrechnungsbericht','b.xlsx',"
            "'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',2048,"
            "'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')"),
            {"id": anid, "aid": aid})
    return aid, anid


# ---- Trigger-Schicht (Admin/Superuser-Verbindung = pg_engine) -----------------

def test_admin_delete_invoices_blocked(pg_engine):
    _cid, iid, itid = _seed_draft(pg_engine)
    with pytest.raises(InternalError) as exc:
        with pg_engine.begin() as c:
            c.execute(text("DELETE FROM invoice_items WHERE id = :id"), {"id": itid})
            c.execute(text("DELETE FROM invoices WHERE id = :id"), {"id": iid})
    assert "GoBD" in str(exc.value)


def test_admin_delete_customers_blocked(pg_engine):
    cid = _seed_customer(pg_engine)
    with pytest.raises(InternalError) as exc:
        with pg_engine.begin() as c:
            c.execute(text("DELETE FROM customers WHERE id = :id"), {"id": cid})
    assert "GoBD" in str(exc.value)


def test_admin_delete_aufstellungen_blocked(pg_engine):
    aid, _anid = _seed_aufstellung(pg_engine)
    with pytest.raises(InternalError) as exc:
        with pg_engine.begin() as c:
            c.execute(text("DELETE FROM aufstellungen WHERE id = :id"), {"id": aid})
    assert "GoBD" in str(exc.value)


def test_admin_delete_anlagen_blocked(pg_engine):
    """Anlagen sind der gepruefte Dateinachweis (Hash, Groesse): Auch im
    Entwurf ist keine Zeile je loeschbar — Korrektur heisst UPDATE, und das
    DELETE-Verbot ist deshalb hier genauso unbedingt wie auf invoices."""
    _aid, anid = _seed_aufstellung(pg_engine)
    with pytest.raises(InternalError) as exc:
        with pg_engine.begin() as c:
            c.execute(text("DELETE FROM aufstellung_anlagen WHERE id = :id"), {"id": anid})
    assert "GoBD" in str(exc.value)


@pytest.mark.parametrize("tbl", [
    "invoices", "invoice_items", "customers", "aufstellungen", "aufstellung_anlagen",
])
def test_admin_truncate_blocked(pg_engine, tbl):
    with pytest.raises(InternalError) as exc:
        with pg_engine.begin() as c:
            c.execute(text(f"TRUNCATE {tbl} CASCADE"))
    assert "GoBD" in str(exc.value)


def test_admin_delete_draft_invoice_item_succeeds(pg_engine):
    """Anti-Überblock: Draft-Positionen bleiben löschbar (kein DELETE-Trigger auf
    invoice_items). Belegt, dass der Backstop NICHT überblockt."""
    _cid, _iid, itid = _seed_draft(pg_engine)
    # Fresh connection to ensure no pending FK state
    with pg_engine.begin() as c:
        remaining_before = c.execute(
            text("SELECT count(*) FROM invoice_items WHERE id = :id"), {"id": itid}
        ).scalar()
        assert remaining_before == 1  # Verify it was seeded
        c.execute(text("DELETE FROM invoice_items WHERE id = :id"), {"id": itid})
    # Verify in new transaction
    with pg_engine.begin() as c:
        remaining = c.execute(
            text("SELECT count(*) FROM invoice_items WHERE id = :id"), {"id": itid}
        ).scalar()
    assert remaining == 0


def test_admin_update_status_still_passes_documented_gap(pg_engine):
    """Dokumentierte Restlücke (Spec §4/§8): rohes UPDATE gegen die Statusmaschine
    geht weiterhin durch — abgesichert nur durch Audit-Log + Backups, nicht durch
    Trigger. Charakterisiert die bewusste Scope-Grenze."""
    _cid, iid, _itid = _seed_draft(pg_engine)
    with pg_engine.begin() as c:
        c.execute(text("UPDATE invoices SET status='paid' WHERE id = :id"), {"id": iid})
    # Verify in new transaction
    with pg_engine.begin() as c:
        status = c.execute(
            text("SELECT status FROM invoices WHERE id = :id"), {"id": iid}
        ).scalar()
    assert status == "paid"


def test_alle_gobd_trigger_installiert(pg_engine):
    """DELETE-Trigger auf den nie loeschbaren Tabellen, TRUNCATE-Trigger
    auch auf invoice_items (deren DELETE im Entwurf legal ist) und den
    Anlagen (deren DELETE nie legal ist, siehe oben)."""
    with pg_engine.connect() as c:
        names = {r[0] for r in c.execute(text(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'gobd_%'"
        ))}
    expected = (
        {f"gobd_no_delete_{t}" for t in (
            "invoices", "customers", "aufstellungen", "aufstellung_anlagen")}
        | {f"gobd_no_truncate_{t}" for t in (
            "invoices", "invoice_items", "customers",
            "aufstellungen", "aufstellung_anlagen")}
    )
    assert names == expected
    assert len(expected) == 9


# ---- Least-Privilege-Schicht (Verbindung als abgehakt_app) ------------------------

from sqlalchemy.exc import ProgrammingError


@pytest.mark.parametrize("tbl", ["invoices", "customers", "aufstellungen",
                                 "aufstellung_anlagen"])
def test_app_role_delete_denied(pg_app_engine, tbl):
    """Rechte greifen VOR dem Trigger → 42501 (permission denied), erreicht den
    Trigger gar nicht erst. Die Default-Privilegien raeumen DELETE auf KEINE
    der Tabellen ein — REVOKE in PROTECTED_NO_DELETE haelt den Zustand."""
    with pytest.raises(ProgrammingError) as exc:
        with pg_app_engine.begin() as c:
            c.execute(text(f"DELETE FROM {tbl}"))
    assert "42501" in str(exc.value) or "permission denied" in str(exc.value)


@pytest.mark.parametrize("tbl", [
    "invoices", "invoice_items", "customers", "aufstellungen", "aufstellung_anlagen",
])
def test_app_role_truncate_denied(pg_app_engine, tbl):
    with pytest.raises(ProgrammingError) as exc:
        with pg_app_engine.begin() as c:
            c.execute(text(f"TRUNCATE {tbl}"))
    assert "42501" in str(exc.value) or "permission denied" in str(exc.value)


def test_app_role_crud_aufstellung_erlaubt(pg_app_engine, pg_engine):
    """CRUD ohne DELETE heisst SELECT, INSERT, UPDATE — auch an den neuen
    Tabellen. Der Weg dorthin ist derselbe wie bei invoices: Default-
    Privilegen raeumen alles ein, der REVOKE zieht DELETE zurueck."""
    _aid, anid = _seed_aufstellung(pg_engine)
    with pg_app_engine.begin() as c:
        cnt = c.execute(text(
            "SELECT count(*) FROM aufstellungen WHERE id = :id"),
            {"id": _aid}).scalar()
        assert cnt == 1
        c.execute(text("UPDATE aufstellungen SET bemerkung='ok' WHERE id = :id"),
                  {"id": _aid})
        c.execute(text("UPDATE aufstellung_anlagen SET groesse=4096 WHERE id = :id"),
                  {"id": anid})
        bemerkung = c.execute(text(
            "SELECT bemerkung FROM aufstellungen WHERE id = :id"),
            {"id": _aid}).scalar()
    assert bemerkung == "ok"


def test_app_role_delete_draft_item_allowed(pg_app_engine, pg_engine):
    """invoice_items behält DELETE — Draft-Positionen bleiben der App löschbar."""
    _cid, _iid, itid = _seed_draft(pg_engine)
    with pg_app_engine.begin() as c:
        c.execute(text("DELETE FROM invoice_items WHERE id = :id"), {"id": itid})
        remaining = c.execute(
            text("SELECT count(*) FROM invoice_items WHERE id = :id"), {"id": itid}
        ).scalar()
    assert remaining == 0


def test_app_role_crud_smoke_allowed(pg_app_engine, pg_engine):
    """Normalbetrieb bleibt funktionsfähig: SELECT + UPDATE als abgehakt_app gelingen."""
    _cid, iid, _itid = _seed_draft(pg_engine)
    with pg_app_engine.begin() as c:
        cnt = c.execute(text("SELECT count(*) FROM invoices WHERE id = :id"), {"id": iid}).scalar()
        assert cnt == 1
        c.execute(text("UPDATE invoices SET notes='ok' WHERE id = :id"), {"id": iid})
        notes = c.execute(text("SELECT notes FROM invoices WHERE id = :id"), {"id": iid}).scalar()
    assert notes == "ok"


def test_app_role_is_not_superuser(pg_app_engine):
    """Produkt-Invariante: die App-Rolle ist NOSUPERUSER (Spec §5, Test 11)."""
    with pg_app_engine.connect() as c:
        is_super = c.execute(
            text("SELECT rolsuper FROM pg_roles WHERE rolname = 'abgehakt_app'")
        ).scalar()
    assert is_super is False
