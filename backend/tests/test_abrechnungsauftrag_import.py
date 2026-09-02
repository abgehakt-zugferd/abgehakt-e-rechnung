"""Abrechnungsauftrag-Import (abgehakt#22) — nur Wegwerf-Postgres via pg_session."""

import json
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.models.customer import Customer
from app.models.invoice import Invoice
from app.services.abrechnungsauftrag_import import (
    BelegSchonVerarbeitet,
    PartnerUnbekannt,
    entwuerfe_aus_roh,
)
from app.services.pdf_generator import _document_title
from app.services.uebergabebeleg import (
    ABSENDER_TANTIEMEN,
    EMPFAENGER_ABGEHAKT,
    SignaturUngueltig,
    beleg_pruefen,
    umschlag,
)

_PARTNER_UUID = uuid.UUID("b7f1e0a4-3c4d-4e6f-8abc-def012345678")
_BELEG_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_ERZEUGT = "2026-09-01T12:00:00Z"


@pytest.fixture
def signier_setup(tmp_path):
    privat = Ed25519PrivateKey.generate()
    pub_ordner = tmp_path / "schluessel" / ABSENDER_TANTIEMEN
    pub_ordner.mkdir(parents=True)
    (pub_ordner / "tantiemen-2026-09.pub").write_bytes(
        privat.public_key().public_bytes(
            Encoding.PEM, PublicFormat.SubjectPublicKeyInfo,
        )
    )
    (pub_ordner / "tantiemen-2026-09.json").write_text(
        json.dumps({
            "schluessel_id": "tantiemen-2026-09",
            "absender": ABSENDER_TANTIEMEN,
            "gueltig_von": "2026-08-01T00:00:00Z",
            "gueltig_bis": None,
        }),
        encoding="utf-8",
    )
    return privat.sign, "tantiemen-2026-09", tmp_path / "schluessel"


def _kunde_anlegen(pg_session, partner_id=_PARTNER_UUID):
    kunde = Customer(
        customer_number="T-001",
        name="Test Autor",
        address_line1="Straße 1",
        zip_code="12345",
        city="Berlin",
        country="DE",
    )
    kunde.id = partner_id
    pg_session.add(kunde)
    pg_session.flush()
    return kunde


def _nutzlast():
    return {
        "abrechnungsquartal": "2026-Q3",
        "projekt": {"name": "Probebuch"},
        "bemessung": {"fenster_von": "2026-07-01", "fenster_bis": "2026-10-01"},
        "grundlagen": [],
        "gutschriften": [
            {
                "beteiligter": {
                    "partner_id": str(_PARTNER_UUID),
                    "anzeigename": "Test Autor",
                },
                "typcode": "389",
                "leistungszeitraum": {"von": "2026-07-01", "bis": "2026-09-30"},
                "positionen": [
                    {
                        "nr": 1,
                        "bezeichnung": "Beteiligung am Deckungsbeitrag 2026-Q3, Probebuch",
                        "netto": "100.00",
                    },
                ],
                "summe": {"netto": "100.00"},
            },
        ],
        "vortraege": [],
    }


def _signierter_beleg(signierer, schluessel_id):
    return umschlag(
        nutzlast=_nutzlast(),
        nutzlast_art="abrechnungsauftrag",
        beleg_id=_BELEG_ID,
        erzeugt_am=_ERZEUGT,
        absender=ABSENDER_TANTIEMEN,
        empfaenger=EMPFAENGER_ABGEHAKT,
        vorgaenger_hash=None,
        schluessel_id=schluessel_id,
        signierer=signierer,
    )


def test_signierter_auftrag_wird_geprueft(signier_setup):
    signierer, schluessel_id, wurzel = signier_setup
    roh = _signierter_beleg(signierer, schluessel_id)
    befund = beleg_pruefen(roh, wurzel=wurzel)
    assert befund.beleg_id == _BELEG_ID
    assert befund.nutzlast_art == "abrechnungsauftrag"


def test_import_erzeugt_entwurf(pg_session, signier_setup):
    signierer, schluessel_id, wurzel = signier_setup
    _kunde_anlegen(pg_session)
    roh = _signierter_beleg(signierer, schluessel_id)
    entwuerfe = entwuerfe_aus_roh(pg_session, roh, schluessel_wurzel=wurzel)
    pg_session.commit()

    assert len(entwuerfe) == 1
    inv = entwuerfe[0]
    assert inv.status == "draft"
    assert inv.invoice_type == "self_billing"
    assert inv.customer_id == _PARTNER_UUID
    assert inv.net_total == Decimal("100.00")
    assert inv.tax_total == Decimal("7.00")
    assert inv.gross_total == Decimal("107.00")
    assert len(inv.items) == 1
    assert inv.items[0].tax_rate == Decimal("7.00")
    assert inv.service_period_start == date(2026, 7, 1)
    assert inv.service_period_end == date(2026, 9, 30)
    assert inv.delivery_date is None


def test_unbekannter_partner_wird_abgelehnt(pg_session, signier_setup):
    signierer, schluessel_id, wurzel = signier_setup
    roh = _signierter_beleg(signierer, schluessel_id)
    with pytest.raises(PartnerUnbekannt):
        entwuerfe_aus_roh(pg_session, roh, schluessel_wurzel=wurzel)


def test_verfaelschte_signatur_wird_abgelehnt(signier_setup):
    signierer, schluessel_id, wurzel = signier_setup
    roh = _signierter_beleg(signierer, schluessel_id)
    beleg = json.loads(roh.decode("utf-8"))
    beleg["signatur"]["wert"] = "AAAA" + beleg["signatur"]["wert"]
    verfaelscht = json.dumps(beleg, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    with pytest.raises(SignaturUngueltig):
        beleg_pruefen(verfaelscht, wurzel=wurzel)


def test_doppelimport_wird_abgelehnt(pg_session, signier_setup):
    signierer, schluessel_id, wurzel = signier_setup
    _kunde_anlegen(pg_session)
    roh = _signierter_beleg(signierer, schluessel_id)
    entwuerfe_aus_roh(pg_session, roh, schluessel_wurzel=wurzel)
    pg_session.commit()
    with pytest.raises(BelegSchonVerarbeitet):
        entwuerfe_aus_roh(pg_session, roh, schluessel_wurzel=wurzel)


def test_self_billing_pdf_titel_ist_gutschrift(pg_session, signier_setup):
    signierer, schluessel_id, wurzel = signier_setup
    _kunde_anlegen(pg_session)
    roh = _signierter_beleg(signierer, schluessel_id)
    entwuerfe = entwuerfe_aus_roh(pg_session, roh, schluessel_wurzel=wurzel)
    assert _document_title(entwuerfe[0]) == "GUTSCHRIFT"
