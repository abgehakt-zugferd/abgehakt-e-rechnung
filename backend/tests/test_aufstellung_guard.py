"""Der Zustandsguard der Abrechnungsaufstellung (Bauschritt 7a, Entscheidung 8).

  draft     → issued | discarded   (stellen, verwerfen)
  discarded → draft                (zurueckholen)
  issued    → cancelled            (stornieren)
  cancelled → (Endzustand)

Nach issued ist die Aufstellung wie eine gestellte Rechnung unveraenderlich
(GoBD) — ausser status, datev_sent_at (einmal setzen), auftragsschluessel_
offen (nur leeren) und updated_at. Es gibt kein paid: Eine Aufstellung
ist keine Rechnung und kennt keinen Zahlungseingang als Status.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.aufstellung_guard import (
    AufstellungStateError,
    register_aufstellung_guard,
)
from tests.factories_aufstellung import orm_anlage, orm_aufstellung

register_aufstellung_guard()  # idempotent — mehrfach registrieren darf nichts doppelt sperren

SCHLUESSEL = "plattform:2026-09:kanal-a:x1"
ANDERER = "plattform:2026-09:kanal-b:y2"


def _gestellt(pg_session, **over):
    """Committete, gestellte Aufstellung — der Zustand, in dem der Guard
    Unveraenderlichkeit schuldet."""
    kw = dict(status="issued", ausstellungsdatum=date(2026, 10, 1))
    kw.update(over)
    a = orm_aufstellung(**kw)
    pg_session.add(a)
    pg_session.commit()
    return a


# ── Zustandsuebergaenge ───────────────────────────────────────────────────────

@pytest.mark.parametrize("von,nach", [
    ("draft", "issued"),
    ("draft", "discarded"),
    ("discarded", "draft"),
])
def test_erlaubte_uebergaenge(pg_session, von, nach):
    a = orm_aufstellung(status=von,
                        ausstellungsdatum=date(2026, 10, 1) if nach == "issued" else None)
    pg_session.add(a)
    pg_session.commit()

    a.status = nach
    if nach == "issued":
        a.ausstellungsdatum = date(2026, 10, 1)
    pg_session.commit()


@pytest.mark.parametrize("von,nach", [
    ("draft", "cancelled"),
    ("draft", "paid"),
    ("discarded", "issued"),
    ("issued", "draft"),
    ("issued", "discarded"),
    ("issued", "paid"),
    ("cancelled", "draft"),
    ("cancelled", "issued"),
])
def test_verbotene_uebergaenge(pg_session, von, nach):
    a = orm_aufstellung(status=von)
    pg_session.add(a)
    pg_session.commit()

    a.status = nach
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()


def test_stellen_ohne_ausstellungsdatum_verboten(pg_session):
    """ausstellungsdatum ist bis zum Finalisieren nullable — beim Uebergang
    zu issued wird es Pflicht, sonst stunde ein gestellter Beleg ohne Datum."""
    a = orm_aufstellung(status="draft")
    pg_session.add(a)
    pg_session.commit()

    a.status = "issued"
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()


# ── Unveraenderlichkeit nach issued ──────────────────────────────────────────

def test_inhalt_einer_gestellten_aufstellung_unveraenderlich(pg_session):
    a = _gestellt(pg_session)

    a.bemerkung = "Nachtrag"
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()

    a.brutto = a.brutto + 1
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()

    a.ausstellungsdatum = date(2026, 10, 2)
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()


def test_stornieren_ohne_finalisiertes_storno_verboten(pg_session):
    a = _gestellt(pg_session, schluessel=SCHLUESSEL)

    a.status = "cancelled"
    a.auftragsschluessel_offen = None
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()


def test_datev_sent_at_einmal_setzen(pg_session):
    a = _gestellt(pg_session)
    moment = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)

    a.datev_sent_at = moment
    pg_session.commit()

    a.datev_sent_at = moment + timedelta(hours=1)
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()

    a.datev_sent_at = None
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()


def test_sperre_nach_issued_nur_leeren(pg_session):
    a = _gestellt(pg_session, schluessel=SCHLUESSEL)

    a.auftragsschluessel_offen = None
    pg_session.commit()

    a.auftragsschluessel_offen = SCHLUESSEL
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()


def test_sperre_nach_issued_nicht_aendern(pg_session):
    a = _gestellt(pg_session, schluessel=SCHLUESSEL)

    a.auftragsschluessel_offen = ANDERER
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()


def test_nachweis_nach_issued_unveraenderlich(pg_session):
    a = _gestellt(pg_session, schluessel=SCHLUESSEL)

    a.auftragsschluessel = ANDERER
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()


def test_verworfener_entwurf_bleibt_bearbeitbar(pg_session):
    """Wie bei der Rechnung erklaert die verworfene Zeile die Nummernluecke
    (Festlegung 18); ihr Zurueckholen und Bearbeiten bleibt frei."""
    a = orm_aufstellung(status="discarded")
    pg_session.add(a)
    pg_session.commit()

    a.bemerkung = "nochmal ueberlegen"
    # Summengleichheit (brutto - quellensteuer = netto) bleibt gewahrt: Der
    # Test will den GUARD pruefen, nicht den DB-CHECK — eine ungueltige Zeile
    # wuerde beide schlagen und nichts ueber die Freiheit des Entwurfs sagen.
    a.brutto = a.brutto + 1
    a.netto = a.netto + 1
    pg_session.commit()


# ── Anlagen und Loeschen ──────────────────────────────────────────────────────

def test_anlagen_einer_gestellten_aufstellung_unveraenderlich(pg_session):
    a = orm_aufstellung(status="issued", ausstellungsdatum=date(2026, 10, 1),
                        anlagen=[orm_anlage()])
    pg_session.add(a)
    pg_session.commit()
    anlage = a.anlagen[0]

    anlage.dateiname = "geaendert.xlsx"
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()

    anlage = a.anlagen[0]
    pg_session.delete(anlage)
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()

    nachgeschoben = orm_anlage("zahlungsbericht")
    nachgeschoben.aufstellung = a
    pg_session.add(nachgeschoben)
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()


def test_anlagen_sind_nicht_loeschbar_auch_nicht_im_entwurf(pg_session):
    """Der DB-Trigger verbietet DELETE auf aufstellung_anlagen unbedingt;
    der Guard wirft dasselbe vorher mit klarer Meldung: Der Platz jeder
    Anlage ist durch (aufstellung_id, quelle) fix, Korrektur heisst neue
    Datei in dieselbe Zeile, nie Zeile weg."""
    a = orm_aufstellung(anlagen=[orm_anlage()])
    pg_session.add(a)
    pg_session.commit()

    pg_session.delete(a.anlagen[0])
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()


def test_hard_delete_einer_aufstellung_verboten(pg_session):
    a = orm_aufstellung()
    pg_session.add(a)
    pg_session.commit()

    pg_session.delete(a)
    with pytest.raises(AufstellungStateError):
        pg_session.commit()
    pg_session.rollback()


def test_neue_aufstellung_ist_in_ihrer_transaktion_frei(pg_session):
    """Erstellung ist kein Eingriff: Eine in dieser Transaktion erzeugte
    Aufstellung darf ueber mehrere Flushes befuellt werden (Muster des
    invoice_guard fuer das Storno)."""
    a = orm_aufstellung(status="issued", ausstellungsdatum=date(2026, 10, 1))
    pg_session.add(a)
    pg_session.flush()

    a.bemerkung = "erst beim zweiten Flush gesetzt"
    pg_session.commit()
