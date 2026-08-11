"""
generate_next_invoice_number() gegen ECHTES Postgres (#98 P1).

Die frühere Fassung war 100 % Mock: sie prüfte u. a. `with_for_update.assert_called_once()`
— reine Call-Mechanik ohne DB-Semantik (blieb grün, selbst wenn der Zähler nicht
persistierte oder die Nummer kollidierte). Hier wird das eigentliche Geschäftsversprechen
bewiesen: fortlaufende, eindeutige, persistierte Rechnungsnummern.
"""
from datetime import date

import pytest

from app.models.company import Company
from app.services.invoice_number import generate_next_invoice_number


def _company(pg_session) -> Company:
    return pg_session.query(Company).filter(Company.id == 1).first()


def test_sequential_numbers_increment_and_persist(pg_session):
    _company(pg_session).invoice_counter = 0
    pg_session.commit()

    year = date.today().year
    first = generate_next_invoice_number(pg_session)
    second = generate_next_invoice_number(pg_session)
    pg_session.commit()

    assert first == f"RE-{year}-001"
    assert second == f"RE-{year}-002"
    assert first != second
    # Zählerstand ist wirklich in der DB gelandet (nicht nur am Mock-Objekt)
    pg_session.expire_all()
    assert _company(pg_session).invoice_counter == 2


def test_number_without_year(pg_session):
    c = _company(pg_session)
    c.invoice_counter = 2
    c.invoice_year_in_number = False
    pg_session.commit()

    assert generate_next_invoice_number(pg_session) == "RE-003"


def test_generation_holds_exclusive_row_lock(pg_session, pg_engine):
    """#98 P2 — Ersatz für den entfernten `with_for_update`-Call-Spy durch einen ECHTEN
    Nebenläufigkeits-Beweis (deterministisch, ohne Threads → kein Hänger-Risiko).

    Session A ruft `generate_next_invoice_number` (SELECT … FOR UPDATE + Increment,
    ohne Commit) → sie hält jetzt einen exklusiven Row-Lock auf company id=1. Ein
    zweiter Aussteller (Session B) kann denselben Row-Lock währenddessen NICHT
    bekommen (`FOR UPDATE NOWAIT` → OperationalError/LockNotAvailable). Damit ist
    bewiesen, dass die Nummernvergabe die Firmenzeile für ihre gesamte Dauer exklusiv
    sperrt und konkurrierende Aufrufe serialisiert — genau das verhindert, dass zwei
    parallele Transaktionen dieselbe fortlaufende Nummer ziehen.

    GRENZE (bewusst dokumentiert): dies beweist die exklusive Sperre, nicht eine
    threaded Duplikat-Reproduktion; die Eindeutigkeit selbst deckt
    `test_sequential_numbers_increment_and_persist` ab.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError
    from sqlalchemy.orm import sessionmaker

    _company(pg_session).invoice_counter = 0
    pg_session.commit()
    pg_session.close()   # Verbindung des Fixtures freigeben, damit sie nicht mitsperrt

    Session = sessionmaker(bind=pg_engine)
    a, b = Session(), Session()
    try:
        num_a = generate_next_invoice_number(a)      # A hält den Row-Lock (kein Commit)
        with pytest.raises(OperationalError):
            b.execute(text("SELECT invoice_counter FROM company WHERE id = 1 FOR UPDATE NOWAIT")).first()
        b.rollback()
        a.commit()                                   # Lock freigeben
        num_b = generate_next_invoice_number(b)      # B zieht jetzt die NÄCHSTE Nummer
        b.commit()
        assert num_a != num_b
        b.expire_all()
        assert b.query(Company).filter(Company.id == 1).first().invoice_counter == 2
    finally:
        a.rollback(); a.close()
        b.rollback(); b.close()


def test_raises_when_company_missing(pg_session):
    # Company-Singleton entfernen (raw SQL — kein ORM-Delete/Guard), dann muss der
    # Generator fail-closed mit RuntimeError abbrechen statt eine Nummer zu erfinden.
    from sqlalchemy import text
    pg_session.execute(text("DELETE FROM company WHERE id = 1"))
    pg_session.commit()
    with pytest.raises(RuntimeError, match="Firmendaten"):
        generate_next_invoice_number(pg_session)
