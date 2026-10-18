"""Der Auftragsschluessel ueber BEIDE Tabellen (Bauschritt 7a, Festlegung 12).

§ 8a und § 8b sprechen von „einem Dokument" zu einem Schluessel: Das kann
eine Rechnung oder eine Abrechnungsaufstellung sein. dokument_zu fragt
deshalb beide Tabellen, und belegen lehnt einen Schluessel ab, der in der
JEWEILS ANDEREN Tabelle schon offen ist — ein Unique-Index ueber zwei
Tabellen gibt es in Postgres nicht (siehe services/auftragsschluessel.py).
"""
import pytest

from app.services import auftragsschluessel
from app.services.auftragsschluessel import SchluesselBelegtError
from tests.factories import orm_invoice_aus_auftrag, orm_item
from tests.factories_aufstellung import orm_aufstellung

SCHLUESSEL = "plattform:2026-09:kanal-a:x1"
ANDERER = "plattform:2026-09:kanal-b:y2"


def _beleg(pg_session):
    inv = orm_invoice_aus_auftrag([orm_item(1, "1", "100.00", "19")], SCHLUESSEL)
    pg_session.add(inv)
    pg_session.commit()
    return inv


def _aufstellung(pg_session, **over):
    a = orm_aufstellung(**over)
    pg_session.add(a)
    pg_session.commit()
    return a


def test_dokument_zu_findet_die_aufstellung(pg_session):
    _aufstellung(pg_session, schluessel=SCHLUESSEL)

    assert auftragsschluessel.dokument_zu(pg_session, SCHLUESSEL) == "Entwurf"


def test_dokument_zu_nennt_die_nummer_einer_gestellten_aufstellung(pg_session):
    a = _aufstellung(pg_session, schluessel=SCHLUESSEL, status="issued")

    assert auftragsschluessel.dokument_zu(pg_session, SCHLUESSEL) == a.nummer


def test_dokument_zu_findet_die_rechnung_weiter(pg_session):
    inv = _beleg(pg_session)

    assert auftragsschluessel.dokument_zu(pg_session, SCHLUESSEL) == "Entwurf"
    assert inv.auftragsschluessel_offen == SCHLUESSEL


def test_belegen_lehnt_den_schluessel_einer_offenen_rechnung_ab(pg_session):
    """Ein Schlüssel darf nicht gleichzeitig an einer Rechnung und an einer
    Aufstellung offen sein. Der Index jeder Tabelle sieht die andere nicht,
    deshalb prueft die eine Stelle, die beide sieht: belegen."""
    _beleg(pg_session)
    a = _aufstellung(pg_session)  # noch ohne Schluessel, committet

    with pytest.raises(SchluesselBelegtError):
        auftragsschluessel.belegen(a, SCHLUESSEL)
    pg_session.rollback()
    assert a.auftragsschluessel_offen is None


def test_belegen_lehnt_den_schluessel_einer_offenen_aufstellung_ab(pg_session):
    _aufstellung(pg_session, schluessel=SCHLUESSEL)
    inv = orm_invoice_aus_auftrag([orm_item(1, "1", "100.00", "19")], ANDERER)
    pg_session.add(inv)
    pg_session.commit()

    with pytest.raises(SchluesselBelegtError):
        auftragsschluessel.belegen(inv, SCHLUESSEL)
    pg_session.rollback()
    assert inv.auftragsschluessel_offen == ANDERER


def test_belegen_erlaubt_den_freigegebenen_schluessel(pg_session):
    """Freigeben heisst nur die Sperre weg: Der Nachweis bleibt Archiv und
    hindert die andere Tabelle nicht."""
    inv = _beleg(pg_session)
    auftragsschluessel.freigeben(inv)
    pg_session.commit()

    a = _aufstellung(pg_session)
    auftragsschluessel.belegen(a, SCHLUESSEL)
    pg_session.commit()

    assert a.auftragsschluessel == SCHLUESSEL
    assert a.auftragsschluessel_offen == SCHLUESSEL
