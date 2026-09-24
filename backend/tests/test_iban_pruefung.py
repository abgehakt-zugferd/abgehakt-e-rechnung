"""IBAN-Pruefung (Issue #91): Durchstich und Kernregel.

Testdaten ausschliesslich konstruiert (Sentinel PROBE, Nullen). Rechnung siehe
knowledge/IBAN/pruefung.md und tests/probe_daten.py.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.services.bankverbindung import normalisiere_iban, pruefe_iban
from app.services.epc_qr import build_epc_payload
from app.services.iban import IbanProfil, pruefe_iban as pruefe_iban_kern
from app.services.pdf_generator import generate_pdf
from app.services.zugferd_xml import generate_xml
from tests.factories import company_stub, customer_stub, zugferd_invoice_stub
from tests.probe_daten import (
    IBAN_AZ_FALSCHE_PZ,
    IBAN_AZ_PROBE,
    IBAN_BR_PROBE,
    IBAN_PROBE,
    IBAN_PROBE_SPACED,
    STEUER_PROBE_ELF,
)


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


_REQUIRED = {
    "name": "Probe IBAN GmbH",
    "address_line1": "Weg 1",
    "zip_code": "10115",
    "city": "Berlin",
    "country": "DE",
}


def test_kunden_speichern_lehnt_iban_mit_falscher_pruefziffer_ab(pg_session):
    """Durchstich: POST /customers/neu mit falscher Pruefziffer persistiert nichts."""
    nummer = f"IBAN-{uuid.uuid4().hex[:8]}"
    r = _client(pg_session).post(
        "/customers/neu",
        data={
            **_REQUIRED,
            "customer_number": nummer,
            "bank_iban": IBAN_AZ_FALSCHE_PZ,
        },
    )
    assert r.status_code == 200, "Formularfehler erwartet, kein Redirect"
    assert "IBAN" in r.text
    assert IBAN_AZ_FALSCHE_PZ in r.text
    pg_session.expire_all()
    assert (
        pg_session.query(Customer).filter(Customer.customer_number == nummer).first()
        is None
    )


def test_pruefe_iban_registry_nimmt_az_probe_an():
    assert pruefe_iban_kern(IBAN_AZ_PROBE, IbanProfil.REGISTRY) == IBAN_AZ_PROBE
    assert pruefe_iban(IBAN_AZ_PROBE) is None


def test_pruefe_iban_registry_lehnt_falsche_pruefziffer_ab():
    with pytest.raises(ValueError, match="Pruefziffer"):
        pruefe_iban_kern(IBAN_AZ_FALSCHE_PZ, IbanProfil.REGISTRY)


def test_pruefe_iban_registry_lehnt_falsche_laenge_ab():
    # AZ Laenge 28; konstruierte 27 mit Rest 1 (AZ26PROBE + 18 Nullen).
    kurz = "AZ26" + "PROBE" + ("0" * 18)
    assert len(kurz) == 27
    with pytest.raises(ValueError, match="Laenge"):
        pruefe_iban_kern(kurz, IbanProfil.REGISTRY)


def test_pruefe_iban_registry_lehnt_unbekanntes_praefix_ab():
    # ZZ nicht in Registry; MOD 97-10 fuer ZZ74PROBE+11 Nullen waere Rest 1.
    fremd = "ZZ74" + "PROBE" + ("0" * 11)
    with pytest.raises(ValueError, match="nicht registriert"):
        pruefe_iban_kern(fremd, IbanProfil.REGISTRY)


def test_normalisiere_iban_kleinbuchstaben_und_leerraum():
    assert normalisiere_iban(IBAN_PROBE_SPACED.lower()) == IBAN_PROBE


def test_pruefe_iban_leeres_feld_bleibt_erlaubt():
    assert pruefe_iban("") is None
    assert pruefe_iban("   ") is None
    assert pruefe_iban_kern(None) is None


def test_epc_sct_lehnt_registry_gueltige_br_probe_ab():
    assert pruefe_iban_kern(IBAN_BR_PROBE, IbanProfil.REGISTRY) == IBAN_BR_PROBE
    with pytest.raises(ValueError, match="EPC-SCT"):
        build_epc_payload(
            beneficiary_name="Firma",
            iban=IBAN_BR_PROBE,
            amount=Decimal("10.00"),
        )


def test_epc_sct_nimmt_de_probe_an():
    payload = build_epc_payload(
        beneficiary_name="Firma",
        iban=IBAN_PROBE,
        amount=Decimal("10.00"),
    )
    assert payload.split("\n")[6] == IBAN_PROBE


def test_option_a_pdf_bricht_bei_ungueltiger_firmen_iban_ab(tmp_path):
    company = company_stub(bank_iban=IBAN_AZ_FALSCHE_PZ)
    inv = zugferd_invoice_stub(customer=customer_stub())
    with pytest.raises(ValueError, match="Firma.*bank_iban"):
        generate_pdf(inv, company, tmp_path / "x.pdf")


def test_option_a_xml_bricht_bei_ungueltiger_firmen_iban_ab():
    company = company_stub(bank_iban=IBAN_AZ_FALSCHE_PZ)
    inv = zugferd_invoice_stub(customer=customer_stub())
    with pytest.raises(ValueError, match="Firma.*bank_iban"):
        generate_xml(inv, company)


def test_kunden_speichern_nimmt_gueltige_probe_an(pg_session):
    nummer = f"IBAN-{uuid.uuid4().hex[:8]}"
    r = _client(pg_session).post(
        "/customers/neu",
        data={
            **_REQUIRED,
            "customer_number": nummer,
            "bank_iban": IBAN_PROBE_SPACED,
        },
    )
    assert r.status_code == 303
    pg_session.expire_all()
    c = pg_session.query(Customer).filter(Customer.customer_number == nummer).first()
    assert c is not None
    assert c.bank_iban == IBAN_PROBE


def _firma_form(**extra):
    data = {
        "name": "Muster Handwerk GmbH",
        "address_line1": "Musterstraße 1",
        "zip_code": "12345",
        "city": "Musterstadt",
        "country": "DE",
        "invoice_prefix": "RE",
        "kst_satz_percent": "15",
        "soli_auf_kst_percent": "5,5",
        "gewerbe_hebesatz": "490",
    }
    data.update(extra)
    return data


def test_einstellungen_lehnen_falsche_iban_pruefziffer_ab(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    client = TestClient(app, follow_redirects=False)
    vorher = pg_session.query(Company).filter(Company.id == 1).first().bank_iban
    antwort = client.post(
        "/settings/firma",
        data=_firma_form(bank_iban=IBAN_AZ_FALSCHE_PZ),
    )
    assert antwort.status_code == 200
    assert "IBAN" in antwort.text
    pg_session.expire_all()
    assert pg_session.query(Company).filter(Company.id == 1).first().bank_iban == vorher
    app.dependency_overrides.clear()


def test_setup_lehnt_falsche_iban_ab_und_setzt_flag_nicht(pg_session):
    from datetime import timezone

    firma = pg_session.query(Company).filter(Company.id == 1).first()
    firma.setup_completed_at = None
    firma.name = ""
    pg_session.commit()
    app.dependency_overrides[get_db] = lambda: pg_session
    client = TestClient(app, follow_redirects=False)
    antwort = client.post(
        "/setup",
        data={
            "name": "Kanzlei Probe",
            "address_line1": "Weg 1",
            "zip_code": "80331",
            "city": "München",
            "country": "DE",
            "tax_number": STEUER_PROBE_ELF,
            "vat_id": "",
            "bank_iban": IBAN_AZ_FALSCHE_PZ,
        },
    )
    assert antwort.status_code == 400
    assert "IBAN" in antwort.text
    pg_session.expire_all()
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    assert firma.setup_completed_at is None
    app.dependency_overrides.clear()


def test_option_a_epc_bricht_bei_ungueltiger_iban_ab():
    """Girocode: ungueltige Bestands-IBAN darf keinen Payload erzeugen."""
    with pytest.raises(ValueError, match="Pruefziffer|ungueltig"):
        build_epc_payload(
            beneficiary_name="Firma",
            iban=IBAN_AZ_FALSCHE_PZ,
            amount=Decimal("10.00"),
        )


def test_gen_iban_daten_pruefen_ist_gruen():
    """Drift-Waechter gegen Worktree-Artefakte (app/ gemountet, kein Image-scripts/)."""
    from app.iban_daten_gen import pruefen

    assert pruefen() == 0
