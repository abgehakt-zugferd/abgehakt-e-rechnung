"""Kein Entwurf aus dem Uebergabebeleg, solange die Ersteinrichtung fehlt (#170).

Migration 001 legt die Firmenzeile (id=1) immer an - leer, mit
`setup_completed_at IS NULL`. Die Wirkungen pruefen heute nur `company is None`.
Gewuenschtes Verhalten: ohne abgeschlossene Ersteinrichtung entsteht kein
Entwurf (kein Invoice, kein UebergabeEingang), sichtbar als `WirkungFehler`.
"""

import uuid
from datetime import datetime, timezone
import pytest

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.uebergabe_eingang import UebergabeEingang
from app.services.abrechnungsauftrag_wirkung import (
    WirkungFehler,
    entwuerfe_anlegen,
)
from app.services.rechnungsauftrag_wirkung import entwurf_anlegen
from app.services.uebergabe_befund import Belegurteil
from app.services.uebergabebeleg import ABSENDER_TANTIEMEN
from tests.helpers.uebergabe import PARTNER_A, rechnungsauftrag

ERZEUGT = datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)
PARTNER_UUID = uuid.UUID(PARTNER_A)


def _firma_ohne_ersteinrichtung(pg_session):
    """Frische Installation: Zeile da, Einrichtung nicht abgeschlossen."""
    firma = pg_session.query(Company).filter(Company.id == 1).one()
    firma.setup_completed_at = None
    firma.name = ""
    firma.address_line1 = ""
    firma.zip_code = ""
    firma.city = ""
    firma.tax_number = None
    firma.vat_id = None
    pg_session.flush()
    return firma


def _kunde_rechnungsauftrag(pg_session):
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Beispiel GmbH",
        address_line1="Platz 1",
        zip_code="1015",
        city="Amsterdam",
        country="NL",
        auftrag_steuer="AE",
        vat_id="NL123456789B01",
        kopftext="Vereinbarung vom 1. Januar 2026.",
        fusstext="Der Abrechnungsbericht ist die Einzelaufstellung.",
        zahlungshinweis="Zahlung folgt dem Auszahlungsbericht.",
        belegsprache_vorgabe="de",
    )
    kunde.id = PARTNER_UUID
    pg_session.add(kunde)
    pg_session.flush()
    return kunde


def _kunde_abrechnungsauftrag(pg_session):
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Beispiel Autorin",
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


def _urteil_rechnungsauftrag():
    return Belegurteil(
        beleg_sha256="a" * 64,
        beleg_id="11111111-2222-4333-8444-555555555556",
        angenommen=True,
        absender=ABSENDER_TANTIEMEN,
        nutzlast_art="rechnungsauftrag",
        erzeugt_am=ERZEUGT,
        nutzlast=rechnungsauftrag(),
    )


def _urteil_abrechnungsauftrag():
    nutzlast = {
        "abrechnungsquartal": "2026-Q2",
        "projekt": {"id": "probe", "name": "Probeverlag"},
        "bemessung": {
            "erloes_netto": "797.30",
            "direktkosten_netto": "100.00",
            "deckungsbeitrag_netto": "697.30",
        },
        "grundlagen": [],
        "gutschriften": [{
            "beteiligter": {
                "partner_id": PARTNER_A,
                "anzeigename": "Beispiel Autorin",
            },
            "typcode": "389",
            "leistungszeitraum": {"von": "2026-04-01", "bis": "2026-06-30"},
            "positionen": [{
                "nr": 1,
                "bezeichnung": "Beteiligung am Deckungsbeitrag 2026-Q2",
                "herleitung": {"basis_netto": "697.30", "satz": "25.00"},
                "netto": "174.33",
            }],
            "summe": {"netto": "174.33"},
        }],
        "vortraege": [],
    }
    return Belegurteil(
        beleg_sha256="b" * 64,
        beleg_id="c0c0c0c0-0000-4000-8000-000000000001",
        angenommen=True,
        absender=ABSENDER_TANTIEMEN,
        nutzlast_art="abrechnungsauftrag",
        erzeugt_am=ERZEUGT,
        nutzlast=nutzlast,
        gegenstand="Probeverlag",
        zeitraum="2026-Q2",
        summe="174,33",
    )


def test_rechnungsauftrag_ohne_ersteinrichtung_legt_keinen_entwurf_an(pg_session):
    _firma_ohne_ersteinrichtung(pg_session)
    _kunde_rechnungsauftrag(pg_session)

    with pytest.raises(WirkungFehler):
        entwurf_anlegen(pg_session, _urteil_rechnungsauftrag())

    pg_session.rollback()
    assert pg_session.query(Invoice).count() == 0
    assert pg_session.query(UebergabeEingang).count() == 0


def test_abrechnungsauftrag_ohne_ersteinrichtung_legt_keinen_entwurf_an(pg_session):
    _firma_ohne_ersteinrichtung(pg_session)
    _kunde_abrechnungsauftrag(pg_session)

    with pytest.raises(WirkungFehler):
        entwuerfe_anlegen(pg_session, _urteil_abrechnungsauftrag())

    pg_session.rollback()
    assert pg_session.query(Invoice).count() == 0
    assert pg_session.query(UebergabeEingang).count() == 0
