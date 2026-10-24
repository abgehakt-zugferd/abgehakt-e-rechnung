"""#230 Commit A: abrechnungsquartal steuert keine Ausgabe mehr.

Wirkung ueber entwuerfe_anlegen, Liste ueber anzeigefelder, XML ueber
generate_xml. Auftraege MIT Feld; die Annahme ohne Feld folgt in Commit B.
"""

import copy
import uuid
from datetime import datetime, timezone

from app.models.company import Company
from app.models.customer import Customer
from app.services.abrechnungsauftrag_wirkung import entwuerfe_anlegen
from app.services.uebergabe_befund import Belegurteil
from app.services.uebergabe_listenzeile import anzeigefelder
from app.services.zugferd_xml import generate_xml
from tests.helpers.uebergabe import (
    PARTNER_A,
    auftrag,
    gutschrift,
)

ERZEUGT = datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)
PARTNER_UUID = uuid.UUID(PARTNER_A)
HALBGEVIERT = "\u2013"


def _kunde(pg_session):
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Autorin A",
        address_line1="Weg 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
        gutschriftempfaenger=True,
        ust_status="regelbesteuert",
        tax_number="12/345/67890",
    )
    kunde.id = PARTNER_UUID
    pg_session.add(kunde)
    pg_session.flush()
    return kunde


def _urteil_aus_nutzlast(nutzlast, sha="a" * 64):
    return Belegurteil(
        beleg_sha256=sha,
        beleg_id="c0c0c0c0-0000-4000-8000-0000000000aa",
        angenommen=True,
        bereits_verarbeitet=False,
        feststellungen=(),
        absender="tantiemen-app",
        nutzlast_art="abrechnungsauftrag",
        erzeugt_am=ERZEUGT,
        nutzlast=nutzlast,
        gegenstand="Probeverlag",
        zeitraum="",
        summe="174,33",
    )


def test_wirkung_mit_quartal_setzt_bt10_leer_und_notiz_mit_zeitraum(pg_session):
    _kunde(pg_session)
    nutzlast = auftrag()

    entwurf = entwuerfe_anlegen(pg_session, _urteil_aus_nutzlast(nutzlast))[0]
    pg_session.flush()
    company = pg_session.query(Company).filter(Company.id == 1).one()
    xml = generate_xml(entwurf, company)

    assert entwurf.buyer_reference is None
    assert "BuyerReference" not in xml
    erwartet = f"Abrechnungsauftrag 01.04.2026{HALBGEVIERT}30.06.2026, Probeverlag"
    assert entwurf.notes == erwartet
    assert erwartet in xml
    assert "2026-Q2" not in (entwurf.notes or "")


def test_wirkung_bt10_aus_auftragsschluessel_der_gutschrift(pg_session):
    _kunde(pg_session)
    gut = gutschrift()
    gut["auftragsschluessel"] = "probe:2026-04:kanal-a:x1"
    nutzlast = auftrag(gutschriften=[gut])

    entwurf = entwuerfe_anlegen(pg_session, _urteil_aus_nutzlast(nutzlast))[0]
    pg_session.flush()
    company = pg_session.query(Company).filter(Company.id == 1).one()
    xml = generate_xml(entwurf, company)

    assert entwurf.buyer_reference == "probe:2026-04:kanal-a:x1"
    assert "<ram:BuyerReference>probe:2026-04:kanal-a:x1</ram:BuyerReference>" in xml
    assert "2026-Q2" not in (entwurf.notes or "")
    assert "2026-Q2" not in xml.split("<ram:IncludedNote>")[1].split(
        "</ram:IncludedNote>"
    )[0]


def test_listenzeile_zeitraum_aus_gutschriften_mit_quartal():
    nutzlast = auftrag()

    felder = anzeigefelder(nutzlast, "abrechnungsauftrag")

    assert felder["zeitraum"] == f"01.04.2026{HALBGEVIERT}30.06.2026"
    assert felder["gegenstand"] == "Probeverlag"
    assert "2026-Q2" not in felder["zeitraum"]


def test_listenzeile_spanne_bei_verschiedenen_leistungszeitraeumen():
    erste = gutschrift()
    zweite = copy.deepcopy(gutschrift(PARTNER_A, netto="10.00"))
    zweite["leistungszeitraum"] = {"von": "2026-03-15", "bis": "2026-07-31"}
    nutzlast = auftrag(gutschriften=[erste, zweite])

    felder = anzeigefelder(nutzlast, "abrechnungsauftrag")

    assert felder["zeitraum"] == f"15.03.2026{HALBGEVIERT}31.07.2026"
    assert "2026-Q2" not in felder["zeitraum"]


def test_veraendertes_abrechnungsquartal_aendert_keine_ausgabe(pg_session):
    """Anderer Quartalwert, gleiche Gutschriften: BT-10, Notiz und Liste gleich."""
    _kunde(pg_session)
    basis = auftrag()
    anders = auftrag(abrechnungsquartal="2026-Q3")

    e1 = entwuerfe_anlegen(pg_session, _urteil_aus_nutzlast(basis, sha="1" * 64))[0]
    e2 = entwuerfe_anlegen(pg_session, _urteil_aus_nutzlast(anders, sha="2" * 64))[0]

    assert e1.buyer_reference == e2.buyer_reference
    assert e1.notes == e2.notes
    assert "2026-Q2" not in (e1.notes or "")
    assert "2026-Q3" not in (e2.notes or "")
    assert anzeigefelder(basis, "abrechnungsauftrag") == anzeigefelder(
        anders, "abrechnungsauftrag",
    )
