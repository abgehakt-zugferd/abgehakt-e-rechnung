"""#264: Die Honorargutschriften (389) aus einem Abrechnungsauftrag tragen den
Auftragsschluessel der Gutschrift als Nachweis und als Sperre.

Oeffentliche Grenze: beleg_beurteilen (mit der Lage der Datenbank) und
entwuerfe_anlegen, so wie der Knopf "Als Rechnung anlegen" sie ruft. Vorbild
fuer die Sperre ist die 380 (Festlegung 12).
"""

import hashlib
import uuid

import pytest

from app.models.customer import Customer
from app.models.invoice import Invoice
from app.services import auftragsschluessel
from app.services.abrechnungsauftrag_wirkung import entwuerfe_anlegen
from app.services.uebergabe_befund import beleg_beurteilen
from app.services.uebergabe_eingang import DatenbankLage
from tests.helpers.uebergabe import PARTNER_A, auftrag, beleg, gutschrift, schluesselpaar

SCHLUESSEL = "probe:lauf-1:autorin-a"


@pytest.fixture
def signatur(tmp_path):
    return schluesselpaar(tmp_path / "schluessel")


def _kunde(pg_session):
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Autorin A",
        address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE",
        gutschriftempfaenger=True, ust_status="regelbesteuert",
        tax_number="12/345/67890",
    )
    kunde.id = uuid.UUID(str(PARTNER_A))
    pg_session.add(kunde)
    pg_session.commit()


def _einlesen(pg_session, signatur, **aenderungen):
    """Beurteilen gegen die Lage der Datenbank, bei Annahme anlegen und
    committen. Gibt (roh, urteil, entwuerfe) zurueck."""
    signieren, wurzel = signatur
    roh = beleg(signieren, **aenderungen)
    urteil = beleg_beurteilen(
        roh, DatenbankLage(pg_session), schluessel_wurzel=wurzel,
    )
    entwuerfe = []
    if urteil.angenommen:
        entwuerfe = entwuerfe_anlegen(pg_session, urteil, dateiname="auftrag.json")
        pg_session.commit()
    return roh, urteil, entwuerfe


def _zweiter_beleg(roh):
    return dict(
        beleg_id="11111111-2222-4333-8444-555555555577",
        vorgaenger_hash=hashlib.sha256(roh).hexdigest(),
    )


def test_zweites_einlesen_desselben_auftrags_legt_keine_zweite_gutschrift_an(
    pg_session, signatur,
):
    _kunde(pg_session)
    roh, erstes, _ = _einlesen(pg_session, signatur)
    assert erstes.angenommen

    _, zweites, entwuerfe = _einlesen(pg_session, signatur, **_zweiter_beleg(roh))

    assert not zweites.angenommen
    assert [(f.code, f.pfad) for f in zweites.feststellungen] == [
        ("AUFTRAG_SCHON_GERECHNET", "$.nutzlast.gutschriften[0].auftragsschluessel"),
    ]
    assert entwuerfe == []
    assert pg_session.query(Invoice).count() == 1


def test_der_entwurf_traegt_nachweis_und_sperre(pg_session, signatur):
    _kunde(pg_session)

    _, _, entwuerfe = _einlesen(pg_session, signatur)

    assert entwuerfe[0].auftragsschluessel == SCHLUESSEL
    assert entwuerfe[0].auftragsschluessel_offen == SCHLUESSEL
    assert auftragsschluessel.dokument_zu(pg_session, SCHLUESSEL) == "Entwurf"


def test_verworfener_entwurf_gibt_den_schluessel_frei_und_zurueckholen_nimmt_ihn_wieder(
    client, pg_session, signatur,
):
    """Festlegung 12 gilt unveraendert fuer die 389: Verwerfen gibt frei, der
    Nachweis bleibt; Zurueckholen belegt wieder, solange kein anderer Beleg
    den Schluessel gezogen hat (Festlegung 19)."""
    _kunde(pg_session)
    roh, _, entwuerfe = _einlesen(pg_session, signatur)
    erster = entwuerfe[0]

    assert client.post(f"/invoices/{erster.id}/verwerfen").status_code == 303
    pg_session.expire_all()
    assert erster.auftragsschluessel == SCHLUESSEL
    assert erster.auftragsschluessel_offen is None

    _, zweites, neue = _einlesen(pg_session, signatur, **_zweiter_beleg(roh))
    assert zweites.angenommen
    assert len(neue) == 1
    assert client.post(f"/invoices/{erster.id}/zurueckholen").status_code == 400

    neue[0].status = "discarded"
    auftragsschluessel.freigeben(neue[0])
    pg_session.commit()
    assert client.post(f"/invoices/{erster.id}/zurueckholen").status_code == 303
    pg_session.expire_all()
    assert erster.status == "draft"
    assert erster.auftragsschluessel_offen == SCHLUESSEL


def test_je_gutschrift_ein_eigener_schluessel(pg_session, signatur):
    _kunde(pg_session)
    nutzlast = auftrag(gutschriften=[
        gutschrift(auftragsschluessel="probe:lauf-1:a"),
        gutschrift(auftragsschluessel="probe:lauf-1:b"),
    ])

    _, urteil, entwuerfe = _einlesen(pg_session, signatur, nutzlast=nutzlast)

    assert urteil.angenommen, [(f.code, f.pfad) for f in urteil.feststellungen]
    assert sorted(e.auftragsschluessel_offen for e in entwuerfe) == [
        "probe:lauf-1:a", "probe:lauf-1:b",
    ]
