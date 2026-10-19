"""Tests fuer Belegstatus-Etiketten in der Oberfläche.

Seit der Entkopplung von Buchhaltung und Kunde (Bauschritt 5) meint „nicht
versendet“ die ZUSTELLUNG AN DEN KUNDEN (`kunde_zugestellt_am`). Ein Beleg, der
nur der Buchhaltung vorliegt, ist keine Zustellung an den Kunden.
"""

from datetime import datetime, timezone

from app.services.beleg_status import badge_klasse, etikett, ist_nicht_versendet


def test_issued_versendet_wenn_kunde_bedient():
    ts = datetime(2026, 9, 2, 13, 0, tzinfo=timezone.utc)
    assert etikett("issued", ts) == "Versendet"
    assert badge_klasse("issued", ts) == "sent"
    assert ist_nicht_versendet("issued", ts) is False


def test_issued_nicht_versendet_ohne_kundenzustellung():
    assert etikett("issued", None) == "Nicht versendet"
    assert badge_klasse("issued", None) == "offen"
    assert ist_nicht_versendet("issued", None) is True


def test_nur_an_die_buchhaltung_bleibt_nicht_versendet(pg_session):
    """Der Gang nur an die Buchhaltung beliefert den Kunden nicht (Bauschritt
    5a, Entscheidung 6): datev_sent_at steht, kunde_zugestellt_am bleibt leer,
    und das Etikett folgt dem Kunden."""
    from tests.test_dashboard import _inv

    inv = _inv(pg_session, "issued", "30.00")
    inv.datev_sent_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    pg_session.commit()

    assert ist_nicht_versendet(inv.status, inv.kunde_zugestellt_am) is True
    assert etikett(inv.status, inv.kunde_zugestellt_am) == "Nicht versendet"
    assert badge_klasse(inv.status, inv.kunde_zugestellt_am) == "offen"


def test_andere_status_bleiben_unveraendert():
    assert etikett("paid") == "Bezahlt"
    assert badge_klasse("paid") == "paid"
    assert etikett("draft") == "Entwurf"
    assert badge_klasse("cancelled") == "cancelled"


def test_sql_bedingung_und_python_regel_sagen_dasselbe(pg_session):
    """Beide Fassungen der Regel muessen dieselbe Menge meinen.

    Ein Entwurf und eine bezahlte Rechnung haben nie eine Kundenzustellung.
    Traegt die SQL-Fassung nur `kunde_zugestellt_am IS NULL`, zaehlt sie beide
    mit, und der Hinweisstreifen meldet eine Versandluecke, die es nicht gibt.
    Der Beleg nur an die Buchhaltung gehoert in die Menge: Der Kunde hat ihn
    nicht.
    """
    from app.models.invoice import Invoice
    from app.services.beleg_status import nicht_versendet_bedingung
    from tests.test_dashboard import _inv

    offen = _inv(pg_session, "issued", "100.00")
    nur_buchhaltung = _inv(pg_session, "issued", "30.00")
    nur_buchhaltung.datev_sent_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    versendet = _inv(pg_session, "issued", "50.00")
    versendet.kunde_zugestellt_am = datetime(2026, 9, 1, tzinfo=timezone.utc)
    entwurf = _inv(pg_session, "draft", "10.00")
    bezahlt = _inv(pg_session, "paid", "20.00")
    pg_session.commit()

    treffer = {
        beleg.id
        for beleg in pg_session.query(Invoice).filter(
            nicht_versendet_bedingung(Invoice.status, Invoice.kunde_zugestellt_am)
        )
    }
    nach_python = {
        beleg.id
        for beleg in (offen, nur_buchhaltung, versendet, entwurf, bezahlt)
        if ist_nicht_versendet(beleg.status, beleg.kunde_zugestellt_am)
    }

    # Erst gegeneinander, dann gegen die ausgeschriebene Antwort: ohne die zweite
    # Zusicherung koennten beide Fassungen gemeinsam falsch sein.
    assert treffer == nach_python
    assert treffer == {offen.id, nur_buchhaltung.id}
