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
from app.services.invoice_number import (
    generate_next_aufstellung_number,
    generate_next_invoice_number,
)
from app.zeit import heute


def _company(pg_session) -> Company:
    return pg_session.query(Company).filter(Company.id == 1).first()


def test_sequential_numbers_increment_and_persist(pg_session):
    _company(pg_session).invoice_counter = 0
    pg_session.commit()

    year = heute().year
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


def test_number_year_follows_issue_date_at_assignment(pg_session):
    """#19: Das Jahr in der Nummer kommt aus dem Ausstellungsdatum beim Anlegen."""
    c = _company(pg_session)
    c.invoice_counter = 0
    c.invoice_year_in_number = True
    pg_session.commit()

    num = generate_next_invoice_number(pg_session, issue_date=date(2027, 1, 2))
    assert num == "RE-2027-001"


# ── Aufstellungen: derselbe Mechanismus, eigener Praefix und Zaehler ──────────

def test_aufstellungen_zaehlen_eigen_und_lueckenlos(pg_session):
    """Eigener Nummernkreis (Entscheidung 8): eigener Praefix, eigener
    Zaehler, dieselbe lueckenlose Logik. Die Reihenfolge, in der Belege
    entstehen, mischt die Kreise, ohne dass einer eine Luecke bekommt."""
    c = _company(pg_session)
    c.invoice_counter = 0
    c.aufstellung_counter = 0
    pg_session.commit()

    year = heute().year
    assert generate_next_invoice_number(pg_session) == f"RE-{year}-001"
    assert generate_next_aufstellung_number(pg_session) == f"AA-{year}-001"
    assert generate_next_aufstellung_number(pg_session) == f"AA-{year}-002"
    assert generate_next_invoice_number(pg_session) == f"RE-{year}-002"

    pg_session.expire_all()
    c = _company(pg_session)
    assert c.invoice_counter == 2
    assert c.aufstellung_counter == 2


def test_aufstellung_nummer_ohne_jahr_wenn_die_firma_kein_jahr_will(pg_session):
    """Ein Stil je Firma: invoice_year_in_number regelt die Jahreszahl in
    BEIDEN Nummernkreisen, nicht nur in den Rechnungsnummern."""
    c = _company(pg_session)
    c.invoice_counter = 2
    c.aufstellung_counter = 2
    c.invoice_year_in_number = False
    pg_session.commit()

    assert generate_next_invoice_number(pg_session) == "RE-003"
    assert generate_next_aufstellung_number(pg_session) == "AA-003"


def test_aufstellung_nummer_jahr_aus_ausstellungsdatum(pg_session):
    _company(pg_session).aufstellung_counter = 0
    pg_session.commit()

    num = generate_next_aufstellung_number(
        pg_session, ausstellungsdatum=date(2027, 1, 2))
    assert num == "AA-2027-001"


def test_aufstellungspraefix_traegt_die_gleiche_whitelist(pg_session):
    """Der Aufstellungspraefix wird ebensowohl Teil eines Dateinamens im
    Archiv wie der Rechnungspraefix — dieselbe Weissliste, eigener Name in
    der Meldung."""
    from app.services.invoice_number import pruefe_praefix

    assert pruefe_praefix("AA-", feldname="Aufstellungspräfix") is None
    meldung = pruefe_praefix("AA/2026", feldname="Aufstellungspräfix")
    assert "Aufstellungspräfix" in meldung
    assert any(w in meldung for w in ("Buchstaben", "Ziffern"))
