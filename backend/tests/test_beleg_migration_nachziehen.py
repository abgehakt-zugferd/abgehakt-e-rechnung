"""Tests fuer Migration: Versand/Bezahlt aus altem System nachziehen."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceSendLog
from scripts.beleg_migration_nachziehen import nachziehen


def _inv(pg_session, number, issue, due, *, payment_terms=None):
    c = Customer(
        customer_number=f"K-MIG-{number}",
        name="Migration Kunde",
        email="kunde@example.de",
        address_line1="Weg 1",
        zip_code="80331",
        city="München",
        country="DE",
    )
    pg_session.add(c)
    pg_session.flush()
    # Check ck_invoices_faelligkeit_oder_bedingungen: due_date oder payment_terms.
    terms = payment_terms
    if due is None and terms is None:
        terms = "Zahlbar nach Vereinbarung."
    inv = Invoice(
        invoice_number=number,
        customer_id=c.id,
        issue_date=issue,
        due_date=due,
        payment_terms=terms,
        currency="EUR",
        net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
        status="issued",
        pdf_filename=f"{number}.pdf",
    )
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_nachziehen_setzt_versand_und_bezahlt(pg_session):
    inv = _inv(pg_session, "MIG-001", date(2026, 7, 8), date(2026, 7, 22))
    nachziehen(["MIG-001"], db=pg_session)

    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.invoice_number == "MIG-001").one()
    assert row.status == "paid"
    assert row.datev_sent_at == datetime(2026, 7, 8, 12, 0, tzinfo=timezone.utc)
    assert row.bezahlt_am == date(2026, 7, 22)
    # updated_at ist Aenderungszeitpunkt, nicht historischer Zahlungszeitpunkt.
    assert row.updated_at != datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
    log = pg_session.query(InvoiceSendLog).filter(InvoiceSendLog.invoice_id == row.id).one()
    assert log.success is True
    assert log.ziel == "kunde_und_buchhaltung"
    assert "vorheriges Abgehakt" in log.error
    # Der historische Versand ging an Kunde UND Buchhaltung: Beide Vermerke
    # stehen auf denselben Zeitpunkt (Bestandsregel aus Migration 029).
    assert row.kunde_zugestellt_am == row.datev_sent_at


def test_nachziehen_setzt_das_zahlungsdatum(pg_session):
    """Die Uebersicht zaehlt Zahlungen nach bezahlt_am. Schreibt das Skript das
    Datum nur nach updated_at, fehlt der Beleg in Umsatz und Geldeingang."""
    _inv(pg_session, "MIG-BA1", date(2026, 3, 2), date(2026, 3, 16))
    _inv(pg_session, "MIG-BA2", date(2026, 3, 2), date(2026, 3, 16))

    nachziehen(["MIG-BA1"], db=pg_session)
    nachziehen(["MIG-BA2"], db=pg_session,
               bezahlt_am=datetime(2026, 4, 30, 23, 30, tzinfo=timezone.utc))

    pg_session.expunge_all()
    stand = {i.invoice_number: (i.status, i.bezahlt_am) for i in
             pg_session.query(Invoice).filter(Invoice.invoice_number.in_(["MIG-BA1", "MIG-BA2"]))}
    assert stand["MIG-BA1"] == ("paid", date(2026, 3, 16))
    # 23:30 UTC am 30.04. ist in Berlin schon der 01.05.
    assert stand["MIG-BA2"] == ("paid", date(2026, 5, 1))


def test_nachziehen_bricht_ohne_faelligkeitsdatum_ab(pg_session):
    """Ohne due_date und ohne bezahlt_am: klare Meldung statt Absturz."""
    inv = _inv(pg_session, "MIG-NODUE", date(2026, 7, 8), None)

    with pytest.raises(ValueError, match="Faelligkeitsdatum|bezahlt_am"):
        nachziehen(["MIG-NODUE"], db=pg_session)

    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).status == "issued"


def test_nachziehen_laesst_updated_at_beim_echten_aenderungszeitpunkt(pg_session):
    """Historischer Zahlertag steht in bezahlt_am; updated_at bleibt Nachzieh-Zeit."""
    vor = datetime.now(timezone.utc)
    historisch = datetime(2026, 4, 30, 12, 0, tzinfo=timezone.utc)
    _inv(pg_session, "MIG-UA1", date(2026, 3, 2), date(2026, 3, 16))

    nachziehen(["MIG-UA1"], db=pg_session, bezahlt_am=historisch)

    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.invoice_number == "MIG-UA1").one()
    assert row.status == "paid"
    assert row.bezahlt_am == date(2026, 4, 30)
    assert row.updated_at != historisch
    assert row.updated_at >= vor
