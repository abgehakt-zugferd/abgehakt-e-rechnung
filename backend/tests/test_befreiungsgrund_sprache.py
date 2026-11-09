"""#290: BT-120 (Befreiungsgrund) spricht die Belegsprache des PDFs.

Quelle ist die Belegdarstellung (`steuerhinweis`); das PDF und das XML lesen
dieselbe Stelle. Deutsch bleibt Byte fuer Byte der bisherige Wortlaut, BT-121
ist sprachunabhaengig.
"""
from decimal import Decimal
import xml.etree.ElementTree as ET

import pytest

from app.services import mustang
from app.services.belegsprache import UnknownDocumentLanguageError, darstellung
from app.services.zugferd_xml import EXEMPTION_REASONS, exemption_reason, generate_xml
from tests.factories import company_stub, item_stub, zugferd_invoice_stub
from tests.test_zugferd_xml import NS

KOPF = ".//ram:ApplicableHeaderTradeSettlement/ram:ApplicableTradeTax/"
POSITION = ".//ram:IncludedSupplyChainTradeLineItem//ram:ApplicableTradeTax/"

DE = {
    "AE": "Steuerschuldnerschaft des Leistungsempfängers / reverse charge, Art. 196 Council Directive 2006/112/EC",
    "E": "Kein Ausweis von Umsatzsteuer, da Kleinunternehmer gemäß § 19 UStG.",
    "K": "Steuerfreie innergemeinschaftliche Lieferung gemäß § 4 Nr. 1b UStG i.V.m. § 6a UStG.",
    "O": "Nicht im Steuergebiet des Ausstellers steuerbar gemäß § 3a Abs. 2 UStG.",
    "GUTSCHRIFT_E": "Steuerbefreiung für Kleinunternehmer gemäß § 19 UStG.",
}
EN = {
    "AE": DE["AE"],
    "E": "No VAT charged as the supplier is a small business under section 19 of the German VAT Act (UStG).",
    "K": "VAT-exempt intra-Community supply under section 4 no. 1b UStG in conjunction with section 6a UStG.",
    "O": "Not taxable in the supplier's territory under section 3a (2) UStG.",
    "GUTSCHRIFT_E": "VAT exemption for small businesses under section 19 UStG.",
}


def _beleg(kategorie, sprache, invoice_type=None):
    kw = dict(
        tax_category=kategorie, document_language=sprache,
        items=[item_stub(tax_rate=Decimal("0.00"), tax_amount=Decimal("0.00"),
                         gross_amount=Decimal("200.00"))],
        net_total=Decimal("200.00"), tax_total=Decimal("0.00"),
        gross_total=Decimal("200.00"),
    )
    if invoice_type:
        kw["invoice_type"] = invoice_type
        if invoice_type == "self_billing_storno":
            kw["original_invoice"] = zugferd_invoice_stub(invoice_number="RE-2026-000")
    return zugferd_invoice_stub(**kw)


def _gründe(inv):
    root = ET.fromstring(generate_xml(inv, company_stub()))
    return (root.find(KOPF + "ram:ExemptionReason", NS),
            root.find(POSITION + "ram:ExemptionReason", NS))


def test_durchstich_englische_kategorie_o_steht_in_bt120_kopf_und_position():
    kopf, position = _gründe(_beleg("O", "en"))
    assert kopf.text == EN["O"]
    assert position.text == EN["O"]


FAELLE = [
    ("AE", None, "AE"), ("E", None, "E"), ("K", None, "K"), ("O", None, "O"),
    ("E", "self_billing", "GUTSCHRIFT_E"), ("E", "self_billing_storno", "GUTSCHRIFT_E"),
]


@pytest.mark.parametrize("kategorie,art,schluessel", FAELLE)
@pytest.mark.parametrize("sprache,erwartet", [("de", DE), ("en", EN)])
def test_bt120_je_kategorie_und_sprache(kategorie, art, schluessel, sprache, erwartet):
    inv = _beleg(kategorie, sprache, art)
    assert exemption_reason(inv) == erwartet[schluessel]
    kopf, position = _gründe(inv)
    assert kopf.text == erwartet[schluessel]
    assert position.text == erwartet[schluessel]


@pytest.mark.parametrize("sprache", ["de", "en"])
def test_bt121_bleibt_sprachunabhaengig(sprache):
    root = ET.fromstring(generate_xml(_beleg("AE", sprache), company_stub()))
    assert root.find(KOPF + "ram:ExemptionReasonCode", NS).text == "VATEX-EU-AE"


def test_unbekannte_sprache_bricht_ab_statt_still_zurueckzufallen():
    with pytest.raises(UnknownDocumentLanguageError):
        exemption_reason(_beleg("O", "fr"))


@pytest.mark.parametrize("kategorie,art", [("E", None), ("E", "self_billing"), ("K", None)])
def test_pdf_hinweis_und_xml_bt120_lauten_bei_en_gleich(kategorie, art):
    """Der Beleg-Hinweis kommt aus derselben Quelle wie BT-120: das PDF liest
    sie ueber blocks.append_hinweise, das XML ueber exemption_reason."""
    from app.services.pdf_generator.blocks import append_hinweise
    from app.services.pdf_generator.logic import belegdarstellung

    inv = _beleg(kategorie, "en", art)
    story: list = []
    append_hinweise(story, inv, belegdarstellung(inv), "Helvetica-Oblique")
    gedruckt = story[0].text
    kopf, _ = _gründe(inv)
    assert gedruckt == kopf.text


def test_kategorienmenge_bleibt_erhalten():
    assert set(EXEMPTION_REASONS) == {"AE", "E", "K", "O"}
    assert darstellung("en").steuerhinweis("S") is None


@pytest.mark.skipif(not mustang.jar_available(), reason="Mustang-JAR nicht verfügbar")
@pytest.mark.parametrize("kategorie", ["E", "O"])
def test_englische_rechnung_mit_befreiungsgrund_besteht_mustang(kategorie, tmp_path):
    """Der englische BT-120 bleibt schema- und regelgueltig (BR-E-10 / BR-O-10)."""
    from app.services import zugferd_xml
    from tests.helpers import mustang_befund
    from tests.test_kleinunternehmer import _company as orm_firma, _invoice as orm_beleg

    inv = orm_beleg(tax_category=kategorie, document_language="en")
    xml = zugferd_xml.generate_xml(inv, orm_firma())
    assert EN[kategorie] in xml
    datei = tmp_path / "beleg.xml"
    datei.write_text(xml, encoding="utf-8")
    ergebnis = mustang.validate(datei)
    mustang_befund.gueltig(ergebnis, ergebnis.get("raw", ""))
