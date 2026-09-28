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
