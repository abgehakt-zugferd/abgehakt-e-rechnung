"""Tests fuer Belegstatus-Etiketten in der Oberfläche."""

from datetime import datetime, timezone

from app.services.beleg_status import badge_klasse, etikett, ist_nicht_versendet


def test_issued_versendet_wenn_datev_sent_at_gesetzt():
    ts = datetime(2026, 9, 2, 13, 0, tzinfo=timezone.utc)
    assert etikett("issued", ts) == "Versendet"
    assert badge_klasse("issued", ts) == "sent"
    assert ist_nicht_versendet("issued", ts) is False


def test_issued_nicht_versendet_wenn_kein_versand():
    assert etikett("issued", None) == "Nicht versendet"
    assert badge_klasse("issued", None) == "offen"
    assert ist_nicht_versendet("issued", None) is True


def test_andere_status_bleiben_unveraendert():
    assert etikett("paid") == "Bezahlt"
    assert badge_klasse("paid") == "paid"
    assert etikett("draft") == "Entwurf"
    assert badge_klasse("cancelled") == "cancelled"


def test_sql_bedingung_und_python_regel_sagen_dasselbe(pg_session):
    """Beide Fassungen der Regel muessen dieselbe Menge meinen.

    Ein Entwurf und eine bezahlte Rechnung haben nie einen Erstversand. Traegt die
    SQL-Fassung nur `datev_sent_at IS NULL`, zaehlt sie beide mit, und der
    Hinweisstreifen meldet eine Versandluecke, die es nicht gibt.
    """
    from app.models.invoice import Invoice
    from app.services.beleg_status import nicht_versendet_bedingung
    from tests.test_dashboard import _inv

    offen = _inv(pg_session, "issued", "100.00")
    versendet = _inv(pg_session, "issued", "50.00")
    versendet.datev_sent_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
    entwurf = _inv(pg_session, "draft", "10.00")
    bezahlt = _inv(pg_session, "paid", "20.00")
    pg_session.commit()

    treffer = {
        beleg.id
        for beleg in pg_session.query(Invoice).filter(
            nicht_versendet_bedingung(Invoice.status, Invoice.datev_sent_at)
        )
    }
    nach_python = {
        beleg.id
        for beleg in (offen, versendet, entwurf, bezahlt)
        if ist_nicht_versendet(beleg.status, beleg.datev_sent_at)
    }

    # Erst gegeneinander, dann gegen die ausgeschriebene Antwort: ohne die zweite
    # Zusicherung koennten beide Fassungen gemeinsam falsch sein.
    assert treffer == nach_python
    assert treffer == {offen.id}
