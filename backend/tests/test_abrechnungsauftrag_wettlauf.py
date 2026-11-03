"""#264: Seit die Gutschriften den Auftragsschluessel sperren, kann auch beim
Abrechnungsauftrag der partielle Unique-Index beim Commit zuschlagen
(Festlegung 19). Das Ergebnis ist eine Meldung, kein HTTP 500.
"""

from urllib.parse import parse_qs, urlparse

from app.models.invoice import Invoice
from app.models.uebergabe_eingang import UebergabeEingang
from app.services.uebergabe_eingang import DatenbankLage
from tests.factories import orm_invoice_aus_auftrag, orm_item
from tests.helpers.uebergabe import beleg
from tests.test_uebergaben_router import (  # noqa: F401  (Fixture + Helfer)
    _kunde,
    _schalter,
    belegordner,
)


def test_wettlauf_beim_abrechnungsauftrag_wird_zur_meldung_nicht_zu_500(
    client, pg_session, belegordner, monkeypatch,
):
    ordner, signieren = belegordner
    _kunde(pg_session)
    _schalter(pg_session)
    pg_session.add(orm_invoice_aus_auftrag(
        [orm_item(1, "1", "174.33", "0")], "probe:lauf-1:autorin-a",
    ))
    pg_session.commit()
    (ordner / "auftrag.json").write_bytes(beleg(signieren))
    monkeypatch.setattr(
        DatenbankLage, "dokument_zu_auftragsschluessel", lambda self, schluessel: None,
    )

    antwort = client.post("/uebergaben/auftrag.json/rechnung-anlegen")

    assert antwort.status_code == 303
    meldung = parse_qs(urlparse(antwort.headers["location"]).query)["fehler"][0]
    assert "AUFTRAG_SCHON_GERECHNET" in meldung
    assert "Entwurf" in meldung
    assert pg_session.query(Invoice).count() == 1
    assert pg_session.query(UebergabeEingang).count() == 0
