"""BT-22: Kopf- und Fusstext des Belegs als IncludedNote in der CII-XML.

Oeffentliche Grenze: ``generate_xml``. Reihenfolge und Inhalt per XML-Parser,
nicht per Substring. Leer oder nur Leerraum erzeugt keine Notiz (EN 16931 R74).
"""
import xml.etree.ElementTree as ET

from app.services.zugferd_xml import generate_xml
from tests.factories import (
    company_stub as _company,
    zugferd_invoice_stub as _invoice,
)

NS = {
    "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
    "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
}


def _notizen(invoice) -> list[str]:
    root = ET.fromstring(generate_xml(invoice, _company()))
    return [
        el.text or ""
        for el in root.findall(
            ".//rsm:ExchangedDocument/ram:IncludedNote/ram:Content", NS
        )
    ]


def test_kopf_und_fusstext_als_bt22_in_reihenfolge():
    inv = _invoice(
        kopftext="Vertragsgrundlage Plattformvertrag",
        fusstext="Der Abrechnungsbericht ist die Einzelaufstellung.",
        notes="Bitte bis 30.06.2026 zahlen.",
    )
    assert _notizen(inv) == [
        "Vertragsgrundlage Plattformvertrag",
        "Der Abrechnungsbericht ist die Einzelaufstellung.",
        "Bitte bis 30.06.2026 zahlen.",
    ]


def test_leerer_kopf_und_fusstext_erzeugen_keine_notiz():
    for kopf, fuss in (
        (None, None),
        ("", ""),
        ("   ", "\n\t"),
    ):
        inv = _invoice(kopftext=kopf, fusstext=fuss, notes=None)
        assert _notizen(inv) == [], f"unerwartete Notizen fuer {kopf!r}/{fuss!r}"


def test_nur_kopftext_ohne_fusstext():
    inv = _invoice(
        kopftext="Vereinbarung vom 1. Januar 2026.",
        fusstext=None,
        notes=None,
    )
    assert _notizen(inv) == ["Vereinbarung vom 1. Januar 2026."]


def test_markup_und_sonderzeichen_als_reiner_text():
    inv = _invoice(
        kopftext="Zeile eins\nZeile zwei <b>kein</b> Markup",
        fusstext="Fuss <10 Stueck & mehr",
        notes=None,
    )
    assert _notizen(inv) == [
        "Zeile eins\nZeile zwei <b>kein</b> Markup",
        "Fuss <10 Stueck & mehr",
    ]


def test_gutschriftverfahren_systemnotiz_bleibt_erste():
    inv = _invoice(
        invoice_type="self_billing",
        kopftext="Vertragsgrundlage Plattformvertrag",
        fusstext="Der Abrechnungsbericht ist die Einzelaufstellung.",
        notes="Vielen Dank.",
    )
    notizen = _notizen(inv)
    assert notizen[0] == "Gutschrift"
    assert notizen == [
        "Gutschrift",
        "Vertragsgrundlage Plattformvertrag",
        "Der Abrechnungsbericht ist die Einzelaufstellung.",
        "Vielen Dank.",
    ]
