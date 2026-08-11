"""
GoBD-Unveränderlichkeit für Rechnungen (Invoice), erzwungen auf Session-Ebene —
kein Codepfad (Router, Skript, SQLAlchemy-Shell) kann sie umgehen.

Statusmaschine (docs/ARCHITEKTUR.md):
  draft   → issued            (finalisieren)
  issued  → paid | cancelled
  paid    → (nichts; Endstatus)
  cancelled → (nichts; Endstatus)

Regeln:
  - Finalisierte Rechnungen (issued/paid/cancelled) sind inhaltlich unveränderlich;
    nur Metadaten (status per erlaubtem Übergang, datev_sent_at) dürfen sich ändern.
  - Rechnungen dürfen NIE hard-gelöscht werden (auch keine Entwürfe) — Storno/cancel.
  - Entwürfe bleiben frei bearbeitbar.
  - Guard läuft VOR dem Audit-Listener (kein Geister-Audit nach abgebrochenem Flush).

Diese Tests brauchen echtes Postgres (Event-Listener sind mit Mocks nicht beweisbar).
"""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services.audit import register_audit_listeners
from app.services.invoice_guard import InvoiceStateError, register_invoice_guard

# Reihenfolge wie in main.py: Guards zuerst, dann Audit
register_invoice_guard()
register_audit_listeners()


def _customer(session) -> Customer:
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Testkunde GmbH",
        address_line1="Musterweg 1",
        zip_code="80331",
        city="München",
        country="DE",
    )
    session.add(c)
    session.flush()
    return c


def _invoice(session, status="draft", **kw) -> Invoice:
    """Erzeugt eine Rechnung DIREKT im Zielstatus (Bypass des Guards über raw defaults
    ist nicht nötig — neue Rechnungen dürfen in jedem Status entstehen; der Guard
    prüft nur Änderungen an bestehenden Zeilen)."""
    c = kw.pop("customer", None) or _customer(session)
    inv = Invoice(
        invoice_number=kw.pop("invoice_number", f"RE-2026-{uuid.uuid4().hex[:6]}"),
        customer_id=c.id,
        issue_date=date(2026, 6, 11),
        due_date=date(2026, 6, 25),
        currency="EUR",
        zugferd_profile="EN16931",
        tax_category="S",
        net_total=Decimal("1000.00"),
        tax_total=Decimal("190.00"),
        gross_total=Decimal("1190.00"),
        status=status,
        **kw,
    )
    session.add(inv)
    session.commit()
    return inv


# ── Erlaubte Änderungen ──────────────────────────────────────────────────────

def test_draft_is_freely_editable(pg_session):
    inv = _invoice(pg_session, status="draft")
    inv.notes = "geändert"
    inv.gross_total = Decimal("2000.00")
    pg_session.commit()
    assert inv.notes == "geändert"


def test_finalize_draft_to_issued_with_field_changes(pg_session):
    inv = _invoice(pg_session, status="draft")
    # Finalisieren setzt xml/pdf/status in EINEM Flush — muss erlaubt sein
    inv.zugferd_xml = "<xml/>"
    inv.pdf_filename = "RE.pdf"
    inv.status = "issued"
    pg_session.commit()
    assert inv.status == "issued"


def test_issued_to_paid_allowed(pg_session):
    inv = _invoice(pg_session, status="issued")
    inv.status = "paid"
    pg_session.commit()
    assert inv.status == "paid"


def test_issued_to_cancelled_allowed(pg_session):
    inv = _invoice(pg_session, status="issued")
    inv.status = "cancelled"
    pg_session.commit()
    assert inv.status == "cancelled"


def test_datev_sent_at_settable_on_issued(pg_session):
    inv = _invoice(pg_session, status="issued")
    inv.datev_sent_at = datetime.now(timezone.utc)
    pg_session.commit()
    assert inv.datev_sent_at is not None


def test_datev_sent_at_settable_on_paid(pg_session):
    inv = _invoice(pg_session, status="paid")
    inv.datev_sent_at = datetime.now(timezone.utc)
    pg_session.commit()
    assert inv.datev_sent_at is not None


def test_datev_sent_at_clear_forbidden(pg_session):
    """Versandnachweis (#98 P0.3): einmal gesetzt, darf datev_sent_at NICHT auf None
    zurückgesetzt werden — sonst ließe sich der DATEV-Versand still verleugnen."""
    inv = _invoice(pg_session, status="issued")
    inv.datev_sent_at = datetime.now(timezone.utc)
    pg_session.commit()
    inv.datev_sent_at = None
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


def test_datev_sent_at_overwrite_forbidden(pg_session):
    """Einmal gesetzter Versandzeitpunkt ist fix — kein Umdatieren auf einen anderen
    Zeitpunkt (Nachweis-Manipulation)."""
    inv = _invoice(pg_session, status="issued")
    inv.datev_sent_at = datetime(2026, 6, 1, 10, 0, tzinfo=timezone.utc)
    pg_session.commit()
    inv.datev_sent_at = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


def test_create_as_issued_then_populate_in_same_txn_is_allowed(pg_session):
    """Storno-/Import-Muster: Rechnung als 'issued' anlegen → flush → zugferd_xml
    setzen → commit, alles in EINER Transaktion. Das ist Erstellung, kein Eingriff
    in eine bereits finalisierte Rechnung → muss durchgehen."""
    c = _customer(pg_session)
    inv = Invoice(
        invoice_number="RE-2026-IMP01", customer_id=c.id,
        issue_date=date(2026, 6, 11), due_date=date(2026, 6, 25),
        currency="EUR", zugferd_profile="EN16931", tax_category="S",
        net_total=Decimal("1000.00"), tax_total=Decimal("190.00"),
        gross_total=Decimal("1190.00"), status="issued",
    )
    pg_session.add(inv)
    pg_session.flush()              # Invoice ist jetzt 'issued' + persistent …
    inv.zugferd_xml = "<xml/>"      # … wird aber noch in derselben Txn befüllt
    inv.pdf_filename = "RE.pdf"
    pg_session.commit()
    assert inv.zugferd_xml == "<xml/>"


def test_frozen_after_commit_even_if_created_as_issued(pg_session):
    """Nach dem Commit greift die Unveränderlichkeit — die „neu erzeugt"-Ausnahme
    darf nicht in die nächste Transaktion durchsickern."""
    inv = _invoice(pg_session, status="issued")  # add + commit
    inv.zugferd_xml = "<manipuliert/>"
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


# ── Verbotene Inhaltsänderungen an finalisierten Rechnungen ──────────────────

@pytest.mark.parametrize("status", ["issued", "paid", "cancelled"])
def test_gross_total_immutable_after_finalize(pg_session, status):
    inv = _invoice(pg_session, status=status)
    inv.gross_total = Decimal("9999.99")
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


@pytest.mark.parametrize(
    "field,value",
    [
        ("invoice_number", "RE-HACK-001"),
        ("net_total", Decimal("1.00")),
        ("tax_total", Decimal("0.00")),
        ("issue_date", date(2020, 1, 1)),
        ("customer_id", None),  # wird unten gesetzt
        ("notes", "nachträglich geändert"),
        ("zugferd_xml", "<fake/>"),
        ("pdf_filename", "andere.pdf"),
    ],
)
def test_content_fields_immutable_on_issued(pg_session, field, value):
    inv = _invoice(pg_session, status="issued")
    if field == "customer_id":
        value = _customer(pg_session).id
    setattr(inv, field, value)
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


# ── Verbotene Statusübergänge ────────────────────────────────────────────────

def test_issued_to_draft_forbidden(pg_session):
    inv = _invoice(pg_session, status="issued")
    inv.status = "draft"
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


def test_paid_to_issued_forbidden(pg_session):
    inv = _invoice(pg_session, status="paid")
    inv.status = "issued"
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


def test_cancelled_is_terminal(pg_session):
    inv = _invoice(pg_session, status="cancelled")
    inv.status = "paid"
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


# ── Positionen (InvoiceItem) finalisierter Rechnungen sind unveränderlich ─────
# Ohne Item-Guard könnten Positionen einer 'issued'-Rechnung per SQLAlchemy-Shell
# geändert/gelöscht werden — ohne Exception, ohne Audit (audit.py auditiert Items
# bewusst nicht). Der Guard schließt dieses GoBD-Loch.

def _item(**kw) -> InvoiceItem:
    return InvoiceItem(
        position=kw.pop("position", 1),
        description=kw.pop("description", "Beratung"),
        unit=kw.pop("unit", "Std"),
        quantity=kw.pop("quantity", Decimal("10")),
        unit_price=kw.pop("unit_price", Decimal("100.00")),
        tax_rate=kw.pop("tax_rate", Decimal("19")),
        net_amount=kw.pop("net_amount", Decimal("1000.00")),
        tax_amount=kw.pop("tax_amount", Decimal("190.00")),
        gross_amount=kw.pop("gross_amount", Decimal("1190.00")),
        **kw,
    )


def _invoice_with_item(session, status="draft") -> Invoice:
    c = _customer(session)
    inv = Invoice(
        invoice_number=f"RE-2026-{uuid.uuid4().hex[:6]}",
        customer_id=c.id,
        issue_date=date(2026, 6, 11), due_date=date(2026, 6, 25),
        currency="EUR", zugferd_profile="EN16931", tax_category="S",
        net_total=Decimal("1000.00"), tax_total=Decimal("190.00"),
        gross_total=Decimal("1190.00"), status=status,
    )
    inv.items = [_item()]
    session.add(inv)
    session.commit()
    return inv


@pytest.mark.parametrize("status", ["issued", "paid", "cancelled"])
def test_item_content_immutable_on_finalized(pg_session, status):
    inv = _invoice_with_item(pg_session, status=status)
    inv.items[0].unit_price = Decimal("1.00")
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


@pytest.mark.parametrize("status", ["issued", "paid", "cancelled"])
def test_item_delete_forbidden_on_finalized(pg_session, status):
    inv = _invoice_with_item(pg_session, status=status)
    pg_session.delete(inv.items[0])
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


def test_item_add_forbidden_on_finalized(pg_session):
    inv = _invoice_with_item(pg_session, status="issued")
    pg_session.add(_item(invoice_id=inv.id, position=2, description="Nachgeschoben"))
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


def test_item_editable_on_draft(pg_session):
    inv = _invoice_with_item(pg_session, status="draft")
    inv.items[0].description = "geändert"
    pg_session.commit()
    assert inv.items[0].description == "geändert"


def test_item_created_with_new_issued_invoice_allowed(pg_session):
    """Storno-Muster: Rechnung als 'issued' MIT Positionen in EINER Transaktion
    anlegen — Erstellung, kein Eingriff → muss durchgehen."""
    inv = _invoice_with_item(pg_session, status="issued")
    assert len(inv.items) == 1


@pytest.mark.parametrize("status", ["issued", "paid", "cancelled"])
def test_items_clear_forbidden_on_finalized(pg_session, status):
    """#98 P2: `inv.items.clear()` (delete-orphan) auf einer finalisierten Rechnung
    darf NICHT durchgehen — sonst ließe sich der Rechnungsinhalt komplett entleeren,
    ohne eine einzelne Position anzufassen."""
    inv = _invoice_with_item(pg_session, status=status)
    inv.items.clear()
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


def test_items_collection_replace_forbidden_on_finalized(pg_session):
    """Die ganze Collection ersetzen (`inv.items = [neu]`) löscht die alte Position und
    schiebt eine neue nach — beide Wege sind auf issued gesperrt."""
    inv = _invoice_with_item(pg_session, status="issued")
    inv.items = [_item(position=1, description="Heimlich getauscht")]
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


# ── Hard-Delete immer verboten ───────────────────────────────────────────────

@pytest.mark.parametrize("status", ["draft", "issued", "paid", "cancelled"])
def test_hard_delete_forbidden(pg_session, status):
    inv = _invoice(pg_session, status=status)
    pg_session.delete(inv)
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


# ── Guard läuft VOR Audit: kein Geister-Audit nach abgebrochenem Flush ────────

def test_blocked_mutation_leaves_no_audit_ghost(pg_session):
    from app.models.invoice import AuditLog
    inv = _invoice(pg_session, status="issued")
    inv.gross_total = Decimal("5.00")
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()
    # Ein legaler Folge-Flush darf keine Audit-Zeile aus dem abgebrochenen Flush erben
    other = _invoice(pg_session, status="draft")
    other.notes = "ok"
    pg_session.commit()
    ghosts = (
        pg_session.query(AuditLog)
        .filter(AuditLog.record_id == str(inv.id))
        .all()
    )
    # Die einzige erlaubte Audit-Zeile zu inv ist ihr INSERT (create), kein UPDATE der Blockade
    assert all(g.action != "update" or g.new_values.get("gross_total") != "5.00" for g in ghosts)
