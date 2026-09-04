"""Tests fuer Belegstatus-Etiketten in der Oberfläche."""

from datetime import datetime, timezone

from app.services.beleg_status import badge_klasse, etikett


def test_issued_versendet_wenn_datev_sent_at_gesetzt():
    ts = datetime(2026, 9, 2, 13, 0, tzinfo=timezone.utc)
    assert etikett("issued", ts) == "Versendet"
    assert badge_klasse("issued", ts) == "sent"


def test_issued_nicht_versendet_wenn_kein_versand():
    assert etikett("issued", None) == "Nicht versendet"
    assert badge_klasse("issued", None) == "offen"


def test_andere_status_bleiben_unveraendert():
    assert etikett("paid") == "Bezahlt"
    assert badge_klasse("paid") == "paid"
    assert etikett("draft") == "Entwurf"
    assert badge_klasse("cancelled") == "cancelled"
