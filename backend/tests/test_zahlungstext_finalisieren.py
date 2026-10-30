"""#260: Zahlungstext folgt der Belegsprache auch beim Finalisieren,
der Kundenhinweis geht der Firmenvorgabe vor.

Naht: POST /invoices/{id}/finalisieren und POST /invoices/{id}/bearbeiten.
PDF und BT-20 werden aus dem gespeicherten Entwurf gerendert, wie im Betrieb.
"""
from __future__ import annotations

import json
from xml.etree import ElementTree as ET

import pytest
from pypdf import PdfReader

from app.models.company import Company
from app.models.invoice import Invoice
from app.services import pdf_generator
from tests.helpers.finalize_pipeline import (
    cleanup,
    client,
    finalize_with_fake_pipeline,
    valid_draft,
)

VORGABE_DE = "Zahlbar innerhalb von 14 Tagen ohne Abzug."
VORGABE_EN = "Payable within 14 days of receipt without deduction."
KUNDENHINWEIS = "Payment per agreement with this customer."
FREITEXT = "Sondervereinbarung Probe bleibt stehen."
NS = {
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
}


def _firma(pg_session, *, de=VORGABE_DE, en=VORGABE_EN):
    firma = pg_session.query(Company).filter(Company.id == 1).one()
    firma.payment_terms_default = de
    firma.payment_terms_default_en = en
    pg_session.commit()
    return firma


def _entwurf(pg_session, *, sprache, text, kundenhinweis=None):
    inv = valid_draft(pg_session, prefix="RE-ZT")
    inv.document_language = sprache
    inv.payment_terms = text
    inv.customer.zahlungshinweis = kundenhinweis
    pg_session.commit()
    return inv


def _bt20(inv) -> str | None:
    root = ET.fromstring(inv.zugferd_xml)
    el = root.find(".//ram:SpecifiedTradePaymentTerms/ram:Description", NS)
    return el.text if el is not None else None


def _pdf_text(inv, firma, tmp_path) -> str:
    out = tmp_path / "beleg.pdf"
    pdf_generator.generate_pdf(inv, firma, out)
    return "".join(p.extract_text() or "" for p in PdfReader(str(out)).pages)


def _finalisieren(pg_session, inv):
    nummer = inv.invoice_number
    try:
        antwort = finalize_with_fake_pipeline(pg_session, inv.id)
    finally:
        cleanup(nummer)
    pg_session.expire_all()
    return antwort, pg_session.get(Invoice, inv.id)


def test_finalisieren_tauscht_deutsche_vorgabe_im_englischen_entwurf(pg_session, tmp_path):
    firma = _firma(pg_session)
    inv = _entwurf(pg_session, sprache="en", text=VORGABE_DE)

    antwort, gestellt = _finalisieren(pg_session, inv)

    assert antwort.status_code == 303, antwort.text
    assert gestellt.status == "issued"
    assert gestellt.payment_terms == VORGABE_EN
    assert _bt20(gestellt) == VORGABE_EN
    text = _pdf_text(gestellt, firma, tmp_path)
    assert VORGABE_EN in text
    assert VORGABE_DE not in text


def _bearbeiten(pg_session, inv, *, sprache, text):
    antwort = client(pg_session).post(
        f"/invoices/{inv.id}/bearbeiten",
        data={
            "customer_id": str(inv.customer_id),
            "issue_date": inv.issue_date.isoformat(),
            "due_date": inv.due_date.isoformat(),
            "delivery_date": inv.delivery_date.isoformat(),
            "tax_category": "S",
            "document_language": sprache,
            "payment_terms": text,
            "items_json": json.dumps([{
                "description": "Beratung", "unit": "Stunde", "quantity": "2",
                "unit_price": "100", "tax_rate": "19",
            }]),
        },
    )
    pg_session.expire_all()
    return antwort, pg_session.get(Invoice, inv.id)


def test_finalisieren_setzt_kundenhinweis_statt_firmenvorgabe(pg_session):
    _firma(pg_session)
    inv = _entwurf(pg_session, sprache="en", text=VORGABE_DE, kundenhinweis=KUNDENHINWEIS)

    antwort, gestellt = _finalisieren(pg_session, inv)

    assert antwort.status_code == 303, antwort.text
    assert gestellt.payment_terms == KUNDENHINWEIS
    assert _bt20(gestellt) == KUNDENHINWEIS


def test_speichern_setzt_kundenhinweis_statt_firmenvorgabe(pg_session):
    _firma(pg_session)
    inv = _entwurf(pg_session, sprache="de", text=VORGABE_DE, kundenhinweis=KUNDENHINWEIS)

    antwort, entwurf = _bearbeiten(pg_session, inv, sprache="en", text=VORGABE_DE)

    assert antwort.status_code in (303, 200), antwort.text
    assert entwurf.document_language == "en"
    assert entwurf.payment_terms == KUNDENHINWEIS


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_finalisieren_laesst_freitext_unveraendert(pg_session, sprache):
    _firma(pg_session)
    inv = _entwurf(pg_session, sprache=sprache, text=FREITEXT, kundenhinweis=KUNDENHINWEIS)

    antwort, gestellt = _finalisieren(pg_session, inv)

    assert antwort.status_code == 303, antwort.text
    assert gestellt.payment_terms == FREITEXT
    assert _bt20(gestellt) == FREITEXT


def test_finalisieren_blockiert_ohne_englische_vorgabe_und_kundenhinweis(pg_session):
    _firma(pg_session, en="")
    inv = _entwurf(pg_session, sprache="en", text=VORGABE_DE)

    antwort, entwurf = _finalisieren(pg_session, inv)

    assert antwort.status_code == 400
    assert "Englische Standard-Zahlungsbedingungen fehlen" in antwort.text
    assert entwurf.status == "draft"
    assert entwurf.payment_terms == VORGABE_DE
    assert entwurf.zugferd_xml is None


def test_finalisieren_deutsche_vorgabe_im_deutschen_entwurf_bleibt(pg_session):
    _firma(pg_session)
    inv = _entwurf(pg_session, sprache="de", text=VORGABE_DE, kundenhinweis=KUNDENHINWEIS)

    antwort, gestellt = _finalisieren(pg_session, inv)

    assert antwort.status_code == 303, antwort.text
    assert gestellt.payment_terms == VORGABE_DE


def test_rechnungsauftrag_behaelt_seinen_hinweis_beim_finalisieren(pg_session):
    _firma(pg_session)
    inv = _entwurf(pg_session, sprache="en", text=VORGABE_DE, kundenhinweis=KUNDENHINWEIS)
    inv.invoice_type = None
    inv.auftragsschluessel = "auftrag-probe-260"
    inv.uebergabe_beleg_sha256 = "a" * 64
    pg_session.commit()

    antwort, gestellt = _finalisieren(pg_session, inv)

    assert antwort.status_code == 303, antwort.text
    assert gestellt.payment_terms == VORGABE_DE
