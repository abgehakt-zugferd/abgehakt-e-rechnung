"""Layout der Rechnungsansicht: Fehler zuerst, Positionen in voller Breite.

Naht ist GET /invoices/{id}; geprüft wird die gerenderte Seite (Reihenfolge und
Einbettung der Bereiche), nicht der Quelltext der Vorlage.
"""
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.invoice_nebenmodelle import ValidationResult
from tests.helpers.ersatzrechnung import beleg as _beleg, kunde as _kunde


@pytest.fixture
def client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    yield TestClient(app, follow_redirects=False)
    app.dependency_overrides.clear()


class _Spuren(HTMLParser):
    """Merkt sich je Überschrift/Beschriftung die Reihenfolge und die umgebenden Bereiche."""

    def __init__(self):
        super().__init__()
        self.stack = []
        self.funde = []  # (text, [bereiche], laufnummer)
        self.n = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("br", "input", "meta", "link", "img", "hr"):
            return
        self.stack.append((tag, dict(attrs).get("data-bereich")))

    def handle_endtag(self, tag):
        while self.stack:
            t, _ = self.stack.pop()
            if t == tag:
                break

    def handle_data(self, data):
        text = data.strip()
        if text:
            self.n += 1
            self.funde.append((text, [b for _, b in self.stack if b], self.n))


def _spuren(html):
    p = _Spuren()
    p.feed(html)
    return p.funde


def _erste(funde, text):
    treffer = [f for f in funde if f[0] == text]
    assert treffer, f"{text!r} fehlt auf der Seite"
    return treffer


def _pruefung(pg_session, beleg, *, errors=None, warnings=None):
    pg_session.add(ValidationResult(
        invoice_id=beleg.id, is_valid=not errors,
        errors=errors or [], warnings=warnings or []))
    pg_session.commit()


def _seite(client, beleg):
    r = client.get(f"/invoices/{beleg.id}")
    assert r.status_code == 200, r.text
    return _spuren(r.text)


def test_positionen_liegen_ausserhalb_der_linken_spalte(pg_session, client):
    beleg = _beleg(pg_session, _kunde(pg_session))
    funde = _seite(client, beleg)
    (_, bereiche, nr_pos), = _erste(funde, "POSITIONEN")
    assert "voll" in bereiche
    (_, b_datum, nr_datum), = _erste(funde, "Rechnungsdatum")
    assert "links" in b_datum and nr_datum < nr_pos
    assert "rechts" in _erste(funde, "KUNDE")[0][1]


def test_zahlungsbedingungen_folgen_den_positionen_in_voller_breite(pg_session, client):
    beleg = _beleg(pg_session, _kunde(pg_session))
    beleg.payment_terms = "Zahlbar innerhalb von 14 Tagen."
    pg_session.commit()
    funde = _seite(client, beleg)
    (_, bereiche, nr_zb), = _erste(funde, "Zahlungsbedingungen")
    (_, _, nr_pos), = _erste(funde, "POSITIONEN")
    assert "voll" in bereiche and nr_zb > nr_pos


def test_pruefprotokoll_mit_fehlern_steht_vor_den_rechnungsdaten(pg_session, client):
    beleg = _beleg(pg_session, _kunde(pg_session))
    _pruefung(pg_session, beleg, errors=[{"message": "Pflichtfeld fehlt", "field": "x"}])
    funde = _seite(client, beleg)
    (_, bereiche, nr_pp), = _erste(funde, "PRÜFPROTOKOLL")
    (_, _, nr_datum), = _erste(funde, "Rechnungsdatum")
    assert nr_pp < nr_datum
    assert "voll" in bereiche


def test_pruefprotokoll_mit_warnungen_steht_ebenfalls_oben(pg_session, client):
    beleg = _beleg(pg_session, _kunde(pg_session))
    _pruefung(pg_session, beleg, warnings=[{"message": "Bitte prüfen"}])
    funde = _seite(client, beleg)
    (_, bereiche, _), = _erste(funde, "PRÜFPROTOKOLL")
    assert "voll" in bereiche


def test_pruefprotokoll_ohne_fehler_bleibt_in_der_rechten_spalte(pg_session, client):
    beleg = _beleg(pg_session, _kunde(pg_session))
    _pruefung(pg_session, beleg)
    funde = _seite(client, beleg)
    (_, bereiche, _), = _erste(funde, "PRÜFPROTOKOLL")
    assert "rechts" in bereiche


def test_ohne_pruefung_bleibt_der_hinweis_in_der_rechten_spalte(pg_session, client):
    beleg = _beleg(pg_session, _kunde(pg_session))
    funde = _seite(client, beleg)
    (_, bereiche, _), = _erste(funde, "NOCH NICHT GEPRÜFT")
    assert "rechts" in bereiche
