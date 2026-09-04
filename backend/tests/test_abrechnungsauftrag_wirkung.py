"""Aus einem angenommenen Beleg werden Entwuerfe (abgehakt#22, Punkt 4).

Erst der Knopf schreibt fest. Was hier passiert, passiert deshalb nie beim
Lesen: Entwuerfe anlegen UND den Beleg als verarbeitet merken, in einem Zug.
Nie teilweise - drei von vier angelegten Gutschriften sind ein Zustand, den von
aussen niemand erkennt.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.uebergabe_eingang import UebergabeEingang
from app.services.abrechnungsauftrag_wirkung import (
    BelegSchonVerarbeitet,
    WirkungFehler,
    entwuerfe_anlegen,
)
from app.services.uebergabe_befund import Belegurteil, Feststellung

PARTNER_A = uuid.UUID("3f5b1c80-0000-4000-8000-00000000000a")
PARTNER_B = uuid.UUID("3f5b1c80-0000-4000-8000-00000000000b")
ERZEUGT = datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)


def _kunde(pg_session, kennung, ust_status="regelbesteuert", name="Autorin A"):
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name=name,
        address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE",
        ust_status=ust_status,
    )
    kunde.id = kennung
    pg_session.add(kunde)
    pg_session.flush()
    return kunde


def _gutschrift(partner_id, netto="174.33", nummer=1):
    return {
        "beteiligter": {"partner_id": str(partner_id), "anzeigename": "Autorin A"},
        "typcode": "389",
        "leistungszeitraum": {"von": "2026-04-01", "bis": "2026-06-30"},
        "positionen": [{
            "nr": nummer,
            "bezeichnung": "Beteiligung am Deckungsbeitrag 2026-Q2, Probeverlag",
            "herleitung": {"basis_netto": "697.30", "satz": "25.00"},
            "netto": netto,
        }],
        "summe": {"netto": netto},
    }


def _urteil(gutschriften=None, angenommen=True, bereits=False, sha="1" * 64):
    nutzlast = {
        "abrechnungsquartal": "2026-Q2",
        "projekt": {"id": "probe", "name": "Probeverlag"},
        "bemessung": {"erloes_netto": "797.30", "direktkosten_netto": "100.00",
                      "deckungsbeitrag_netto": "697.30"},
        "grundlagen": [],
        "gutschriften": gutschriften if gutschriften is not None else [_gutschrift(PARTNER_A)],
        "vortraege": [],
    }
    return Belegurteil(
        beleg_sha256=sha, beleg_id="c0c0c0c0-0000-4000-8000-000000000001",
        angenommen=angenommen, bereits_verarbeitet=bereits,
        feststellungen=() if angenommen else (Feststellung("SIGNATUR_UNGUELTIG", "$"),),
        absender="tantiemen-app", nutzlast_art="abrechnungsauftrag", erzeugt_am=ERZEUGT,
        nutzlast=nutzlast, abrechnungsquartal="2026-Q2", projekt="Probeverlag",
        zahl_gutschriften=len(nutzlast["gutschriften"]),
        summe_netto=Decimal(nutzlast["gutschriften"][0]["summe"]["netto"])
        if nutzlast["gutschriften"] else Decimal("0"),
    )


def test_aus_einer_gutschrift_wird_ein_entwurf(pg_session):
    _kunde(pg_session, PARTNER_A)

    entwuerfe = entwuerfe_anlegen(pg_session, _urteil(), dateiname="auftrag.json")
    pg_session.flush()

    assert len(entwuerfe) == 1
    entwurf = entwuerfe[0]
    assert entwurf.status == "draft"
    assert entwurf.invoice_type == "self_billing"
    assert entwurf.customer_id == PARTNER_A
    assert entwurf.service_period_start.isoformat() == "2026-04-01"
    assert entwurf.service_period_end.isoformat() == "2026-06-30"
    assert entwurf.net_total == Decimal("174.33")


def test_der_entwurf_zeigt_auf_den_beleg(pg_session):
    _kunde(pg_session, PARTNER_A)

    entwurf = entwuerfe_anlegen(pg_session, _urteil(), dateiname="auftrag.json")[0]

    assert entwurf.uebergabe_beleg_id == "c0c0c0c0-0000-4000-8000-000000000001"
    assert entwurf.uebergabe_beleg_sha256 == "1" * 64


def test_regelbesteuert_ergibt_sieben_prozent(pg_session):
    _kunde(pg_session, PARTNER_A, ust_status="regelbesteuert")

    entwurf = entwuerfe_anlegen(pg_session, _urteil())[0]
    pg_session.flush()

    assert entwurf.tax_category == "S"
    assert entwurf.items[0].tax_rate == Decimal("7.00")
    assert entwurf.tax_total == Decimal("12.20")
    assert entwurf.gross_total == Decimal("186.53")


def test_kleinunternehmer_bekommt_keine_umsatzsteuer(pg_session):
    """§ 19 UStG. Wer als Kleinunternehmer Umsatzsteuer ausweist, schuldet sie
    nach § 14c Abs. 2 UStG - auf einer Gutschrift, die er nicht geschrieben hat."""
    _kunde(pg_session, PARTNER_A, ust_status="kleinunternehmer")

    entwurf = entwuerfe_anlegen(pg_session, _urteil())[0]
    pg_session.flush()

    assert entwurf.tax_category == "E"
    assert entwurf.items[0].tax_rate == Decimal("0.00")
    assert entwurf.tax_total == Decimal("0.00")
    assert entwurf.gross_total == entwurf.net_total


def test_der_beleg_gilt_danach_als_verarbeitet(pg_session):
    _kunde(pg_session, PARTNER_A)

    entwuerfe_anlegen(pg_session, _urteil(), dateiname="auftrag.json")
    pg_session.flush()

    zeile = pg_session.query(UebergabeEingang).one()
    assert zeile.beleg_sha256 == "1" * 64
    assert zeile.dateiname == "auftrag.json"


def test_ein_abgelehnter_beleg_wirkt_nicht(pg_session):
    _kunde(pg_session, PARTNER_A)

    with pytest.raises(WirkungFehler):
        entwuerfe_anlegen(pg_session, _urteil(angenommen=False))

    assert pg_session.query(Invoice).count() == 0
    assert pg_session.query(UebergabeEingang).count() == 0


def test_ein_schon_verarbeiteter_beleg_wirkt_kein_zweites_mal(pg_session):
    _kunde(pg_session, PARTNER_A)

    with pytest.raises(BelegSchonVerarbeitet):
        entwuerfe_anlegen(pg_session, _urteil(bereits=True))

    assert pg_session.query(Invoice).count() == 0


def test_zwei_gutschriften_werden_zwei_entwuerfe(pg_session):
    _kunde(pg_session, PARTNER_A)
    _kunde(pg_session, PARTNER_B, name="Autor B")

    entwuerfe = entwuerfe_anlegen(
        pg_session,
        _urteil([_gutschrift(PARTNER_A), _gutschrift(PARTNER_B, netto="265.77")]),
    )
    pg_session.flush()

    assert [e.customer_id for e in entwuerfe] == [PARTNER_A, PARTNER_B]
    assert len({e.invoice_number for e in entwuerfe}) == 2


def test_ein_fehlender_kunde_laesst_keine_einzige_gutschrift_zurueck(pg_session):
    """Nie teilweise: der zweite Beteiligte fehlt, also entsteht auch fuer den
    ersten nichts. Das Urteil haette das schon gefangen; hier haelt es die
    Wirkung selbst fest, damit es auch ohne Urteil nicht schiefgeht."""
    _kunde(pg_session, PARTNER_A)

    with pytest.raises(WirkungFehler):
        entwuerfe_anlegen(
            pg_session,
            _urteil([_gutschrift(PARTNER_A), _gutschrift(PARTNER_B, netto="265.77")]),
        )

    pg_session.rollback()
    assert pg_session.query(Invoice).count() == 0
    assert pg_session.query(UebergabeEingang).count() == 0


def test_ein_unbekannter_typcode_wirkt_nicht(pg_session):
    """381 und 389 sind zwei verschiedene Belege; alles andere ist keiner."""
    _kunde(pg_session, PARTNER_A)
    gutschrift = _gutschrift(PARTNER_A)
    gutschrift["typcode"] = "999"

    with pytest.raises(WirkungFehler):
        entwuerfe_anlegen(pg_session, _urteil([gutschrift]))
