"""#227: Rechnung aus Rechnungsauftrag ist bei Ausstellung bezahlt.

XML: BT-113 = Brutto, BT-115 = 0.00 (BR-CO-16). PDF: Bereits gezahlt / Offener
Betrag. Status paid, nicht offen/ueberfaellig. Andere Rechnungen unveraendert.
"""
from decimal import Decimal
from xml.etree import ElementTree as ET

import pytest
from pypdf import PdfReader

from app.models.company import Company
from app.models.invoice import Invoice
from app.services import mustang, pdf_generator, zugferd_xml
from app.services.auftragszahlung import ist_rechnungsauftrag
from app.services.belegsprache import darstellung
from app.services.dashboard_kennzahlen import offene_forderungen, ueberfaellige_forderungen
from app.services.rechnungsauftrag_wirkung import entwurf_anlegen
from app.zeit import heute
from tests.factories import orm_company, orm_customer, orm_invoice_for
from tests.probe_daten import IBAN_FIRMA_PROBE
from tests.test_rechnungsauftrag_wirkung import _kunde, _urteil

HINWEIS = "Die Zahlung erfolgt durch Auszahlung des Leistungsempfängers."
RAM = "{urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100}"


def _entwurf(db, *, sprache="de", hinweis=HINWEIS):
    firma = db.get(Company, 1)
    if firma is None:
        firma = orm_company()
        db.add(firma)
    firma.bank_iban = IBAN_FIRMA_PROBE
    firma.bank_bic = "ABCDDEFF"
    _kunde(db, zahlungshinweis=hinweis, belegsprache_vorgabe=sprache)
    inv = entwurf_anlegen(db, _urteil(), company=firma)
    inv.document_language = sprache
    inv.payment_terms = hinweis
    db.commit()
    return inv, firma


def _summation(root):
    return root.find(f".//{RAM}SpecifiedTradeSettlementHeaderMonetarySummation")


def _kind_namen(summation):
    return [el.tag.split("}", 1)[-1] for el in list(summation)]


def test_xml_prepaid_brutto_due_zero_br_co_16(pg_session):
    inv, firma = _entwurf(pg_session)
    assert ist_rechnungsauftrag(inv)
    xml = zugferd_xml.generate_xml(inv, firma)
    root = ET.fromstring(xml)
    summe = _summation(root)
    brutto = summe.find(f"{RAM}GrandTotalAmount").text
    prepaid = summe.find(f"{RAM}TotalPrepaidAmount")
    due = summe.find(f"{RAM}DuePayableAmount")
    assert prepaid is not None and prepaid.text == brutto
    assert due is not None and due.text == "0.00"
    bt112 = Decimal(brutto)
    bt113 = Decimal(prepaid.text)
    bt115 = Decimal(due.text)
    assert bt115 == bt112 - bt113
    namen = _kind_namen(summe)
    assert namen.index("GrandTotalAmount") < namen.index("TotalPrepaidAmount")
    assert namen.index("TotalPrepaidAmount") < namen.index("DuePayableAmount")


@pytest.mark.skipif(not mustang.jar_available(), reason="Mustang-JAR nicht verfügbar")
def test_mustang_nimmt_prepaid_rechnungsauftrag_an(pg_session, tmp_path):
    inv, firma = _entwurf(pg_session)
    xml = zugferd_xml.generate_xml(inv, firma)
    assert "<ram:TotalPrepaidAmount>" in xml
    assert "<ram:DuePayableAmount>0.00</ram:DuePayableAmount>" in xml
    pfad = tmp_path / "auftrag.xml"
    pfad.write_text(xml)
    ergebnis = mustang.validate(pfad)
    assert ergebnis["is_valid"], ergebnis


@pytest.mark.parametrize("sprache,bereits,offen", [
    ("de", "Bereits gezahlt", "Offener Betrag"),
    ("en", "Already paid", "Amount due"),
])
def test_pdf_bereits_gezahlt_und_offener_betrag(pg_session, tmp_path, sprache, bereits, offen):
    inv, firma = _entwurf(pg_session, sprache=sprache)
    d = darstellung(sprache)
    pdf = tmp_path / f"auftrag-{sprache}.pdf"
    pdf_generator.generate_pdf(inv, firma, pdf)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(pdf).pages)
    assert d.label_bereits_gezahlt == bereits
    assert d.label_offener_betrag == offen
    assert bereits in text
    assert offen in text
    assert d.format_betrag(Decimal("0.00"), inv.currency) in text
    brutto = d.format_betrag(inv.gross_total, inv.currency)
    assert brutto in text
    assert text.index(bereits) > text.index(d.label_rechnungsbetrag)
    assert "Zahlungsdatum" not in text
    assert "Payment date" not in text
    assert "Zahlungsnummer" not in text
    assert "Payment number" not in text


def test_andere_rechnung_ohne_prepaid_due_gleich_brutto(pg_session, tmp_path):
    import uuid
    kunde = orm_customer(customer_number=f"K-{uuid.uuid4().hex[:8]}")
    pg_session.add(kunde)
    pg_session.flush()
    inv = orm_invoice_for(kunde)
    pg_session.add(inv)
    firma = pg_session.get(Company, 1)
    if firma is None:
        firma = orm_company()
        pg_session.add(firma)
    firma.bank_iban = IBAN_FIRMA_PROBE
    pg_session.commit()
    assert not ist_rechnungsauftrag(inv)
    xml = zugferd_xml.generate_xml(inv, firma)
    root = ET.fromstring(xml)
    summe = _summation(root)
    assert summe.find(f"{RAM}TotalPrepaidAmount") is None
    brutto = summe.find(f"{RAM}GrandTotalAmount").text
    assert summe.find(f"{RAM}DuePayableAmount").text == brutto
    pdf = tmp_path / "normal.pdf"
    pdf_generator.generate_pdf(inv, firma, pdf)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(pdf).pages)
    assert "Bereits gezahlt" not in text
    assert "Already paid" not in text
    assert "Offener Betrag" not in text
    assert "Amount due" not in text


def test_finalisieren_setzt_paid_nicht_offen_nicht_ueberfaellig(client, pg_session):
    inv, _ = _entwurf(pg_session)
    antwort = client.post(f"/invoices/{inv.id}/finalisieren")
    assert antwort.status_code == 303, antwort.text
    pg_session.expire_all()
    row = pg_session.get(Invoice, inv.id)
    assert "TotalPrepaidAmount" in row.zugferd_xml
    assert "<ram:DuePayableAmount>0.00</ram:DuePayableAmount>" in row.zugferd_xml
    # Kennzahlen vor Status: bleibt der Beleg issued, faellt offen zuerst.
    offen = offene_forderungen(pg_session)
    assert offen.anzahl == 0
    assert offen.betrag == Decimal("0")
    ueber = ueberfaellige_forderungen(pg_session, heute())
    assert ueber.anzahl == 0
    assert ueber.betrag == Decimal("0")
    assert row.status == "paid"
    assert row.bezahlt_am == heute()
