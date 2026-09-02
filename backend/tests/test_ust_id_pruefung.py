"""USt-IdNr.-Pruefung gegen VIES (MockTransport, keine echten Netzaufrufe)."""
import json
from datetime import datetime, timezone

import httpx

from app.services.ust_id_pruefung import (
    VIES_ENDPOINT,
    aufteilen_ust_id,
    namen_gleich,
    normalisiere_ust_id,
    pruefe_ust_id_format,
    pruefe_ust_id_vies,
    speichern,
    zuruecksetzen,
)
from app.services.validator import validate_invoice
from tests.factories import company_stub, customer_stub, validator_invoice_stub, orm_customer
from tests.probe_daten import UST_DE_PROBE, UST_DE_PROBE_3


def _transport(payload: dict, status: int = 200):
    body = json.dumps(payload).encode()

    def handler(request):
        assert request.method == "POST"
        assert request.url == VIES_ENDPOINT
        return httpx.Response(status, content=iter([body]))

    return httpx.MockTransport(handler)


def test_normalisiere_ust_id():
    assert normalisiere_ust_id("de 123 456 789") == UST_DE_PROBE


def test_aufteilen_de():
    assert aufteilen_ust_id(UST_DE_PROBE) == ("DE", "123456789")


def test_aufteilen_griechenland_gr_nach_el():
    assert aufteilen_ust_id("GR123456789") == ("EL", "123456789")


def test_format_pruefung_lehnt_kurz_ab():
    assert pruefe_ust_id_format("DE1") is not None


def test_namen_gleich_tolerant():
    assert namen_gleich("Muster Handwerk GmbH", "Muster Handwerk")
    assert not namen_gleich("Alpha GmbH", "Beta AG")


def test_vies_gueltig():
    payload = {
        "valid": True,
        "name": "John Doe",
        "address": "123 Main St",
        "traderNameMatch": "VALID",
    }
    ergebnis = pruefe_ust_id_vies(
        "DE100",
        trader_name="John Doe",
        transport=_transport(payload),
    )
    assert ergebnis.verfuegbar
    assert ergebnis.gueltig is True
    assert ergebnis.name_abgleich == "stimmt"
    assert ergebnis.registrierter_name == "John Doe"


def test_vies_ungueltig():
    payload = {"valid": False, "name": "---", "address": "---"}
    ergebnis = pruefe_ust_id_vies("DE200", transport=_transport(payload))
    assert ergebnis.verfuegbar
    assert ergebnis.gueltig is False


def test_vies_nicht_erreichbar():
    def handler(request):
        return httpx.Response(503)

    ergebnis = pruefe_ust_id_vies(
        UST_DE_PROBE,
        transport=httpx.MockTransport(handler),
    )
    assert not ergebnis.verfuegbar
    assert ergebnis.gueltig is None


def test_name_abgleich_aus_vies_name():
    payload = {
        "valid": True,
        "name": "Bayerische Motoren Werke",
        "address": "Muenchen",
    }
    ergebnis = pruefe_ust_id_vies(
        "DE100",
        trader_name="BMW AG",
        transport=_transport(payload),
    )
    assert ergebnis.name_abgleich == "weicht_ab"


def test_speichern_und_zuruecksetzen():
    kunde = orm_customer(vat_id=UST_DE_PROBE, vat_id_checked_at=None, vat_id_check_valid=None)
    ergebnis = pruefe_ust_id_vies(
        "DE100",
        trader_name="Test",
        transport=_transport({"valid": True, "name": "Test", "traderNameMatch": "VALID"}),
    )
    speichern(kunde, ergebnis)
    assert kunde.vat_id_check_valid is True
    assert kunde.vat_id_name_match == "stimmt"
    zuruecksetzen(kunde)
    assert kunde.vat_id_checked_at is None


def test_validator_ungueltige_kunden_ust_id():
    kunde = customer_stub(
        vat_id=UST_DE_PROBE_3,
        vat_id_checked_at=datetime.now(timezone.utc),
        vat_id_check_valid=False,
        vat_id_name_match=None,
        vat_id_vies_name=None,
    )
    inv = validator_invoice_stub(customer=kunde)
    errors, _ = validate_invoice(inv, company_stub())
    assert any(e.code == "BUYER_VAT_ID_VIES_INVALID" for e in errors)
