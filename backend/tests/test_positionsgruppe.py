"""Positionsgruppen (Bauschritt 3; Entscheidung 3 und Festlegung 11).

Eine Position kann einer Gruppe angehoeren — freier Anzeigetext, etwa
"Gruppe A". Gruppen sind zusammenhaengend: Positionen derselben Gruppe folgen
in der Positionsnummer aufeinander. Der Leser erzwingt das fuer Auftraege;
fuer manuelle Entwuerfe prueft es der Validator (POSITION_GRUPPE_GETRENNT).

Drei Adapter lesen dieselbe Spalte: Das PDF zeigt vor der ersten Position
jeder Gruppe eine Ueberschrift und nach ihrer letzten eine Zwischensumme
(reine Addition der Positionsnetto). Die XML bleibt flach — EN 16931 kennt
keine Zwischensummen — und traegt die Gruppe als Positionsnotiz (BT-127).
Festlegung 11: Bei einer gebundenen Standardrechnung (380) ist ein negativer
Einzelpreis zulaessig (eine Erstattung im Abrechnungsmonat), solange die
Rechnungssumme netto positiv bleibt.
"""
import re
import uuid
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import belegsperre, mustang, positionsangaben, zugferd_xml
from app.services.validator import validate_invoice
from tests.factories import (
    company_stub,
    item_stub,
    orm_company,
    orm_item,
    orm_invoice,
    validator_invoice_stub,
)
from tests.helpers.finalize_pipeline import cleanup, finalize_with_fake_pipeline
from tests.helpers import mustang_befund

RAM = "{urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100}"


# ------------------------------------------------ Positionsangaben: die eine Quelle

def test_formular_liefert_die_gruppe_als_spalte():
    """gruppe laeuft durch dieselbe Quelle wie Artikelnummer und Zeitraum;
    alles andere wuerde an einer der vier Stationen verloren gehen."""
    werte = positionsangaben.aus_formular({"gruppe": "  Gruppe A "}, 1)
    assert werte["gruppe"] == "Gruppe A"
    assert positionsangaben.aus_formular({"gruppe": ""}, 1)["gruppe"] is None


def test_gruppe_mit_steuerzeichen_wird_abgelehnt():
    """Der Gruppentext landet im PDF und in der XML (BT-127); Steuerzeichen
    machen die XML ungueltig, statt escaped zu werden."""
    with pytest.raises(positionsangaben.PositionsangabeUngueltig):
        positionsangaben.aus_formular({"gruppe": "Gruppe\tA"}, 1)


def test_vorlage_und_storno_uebernehmen_die_gruppe():
    """Wie die Artikelnummer: Die Gruppe ist Rechnungsinhalt, kein Bezug auf
    die alte Rechnung — Vorlage (und damit Ersatzrechnung) und Storno
    uebernehmen sie."""
    alt = SimpleNamespace(artikelnummer="A-1", leistung_von=None,
                          leistung_bis=None, gruppe="Gruppe A")
    assert positionsangaben.fuer_formular(alt, vorlage=True)["gruppe"] == "Gruppe A"
    assert positionsangaben.kopie(alt)["gruppe"] == "Gruppe A"


# ------------------------------------------------ Testbelege

def _beleg_mit_gruppen():
    """Zwei Positionen Gruppe A, eine Gruppe B, eine ohne Gruppe — jede Form
    (Ueberschrift, Summe, Notiz) braucht ihren eigenen Fall."""
    a1 = orm_item(1, "1", "100.00", "19", description="Erstes Digital")
    a1.gruppe = "Gruppe A"
    a2 = orm_item(2, "1", "50.00", "19", description="Zweites Digital")
    a2.gruppe = "Gruppe A"
    b1 = orm_item(3, "1", "20.00", "19", description="Softwarepflege")
    b1.gruppe = "Gruppe B"
    frei = orm_item(4, "1", "10.00", "19", description="Ohne Gruppe")
    return orm_invoice([a1, a2, b1, frei])


def _pdf_text(invoice, tmp_path):
    from pypdf import PdfReader

    from app.services import pdf_generator
    out = tmp_path / "beleg.pdf"
    pdf_generator.generate_pdf(invoice, orm_company(), out)
    return " ".join("".join(p.extract_text() for p in PdfReader(str(out)).pages).split())


# ------------------------------------------------ PDF: Ueberschrift und Zwischensumme

def test_pdf_zeigt_je_gruppe_ueberschrift_und_zwischensumme(tmp_path):
    text = _pdf_text(_beleg_mit_gruppen(), tmp_path)

    # Die Ueberschrift steht VOR der ersten, die Summe NACH der letzten
    # Position der Gruppe; die Reihenfolge im Text weist beides nach.
    assert text.index("Gruppe A") < text.index("Erstes Digital") < text.index("Zweites Digital")
    assert text.index("Zweites Digital") < text.index("Zwischensumme Gruppe A")
    # Reine Addition der Positionsnetto (100 + 50), keine Rundung, kein Steueranteil.
    assert "150,00" in text
    assert "Zwischensumme Gruppe B" in text
    # Positionen ohne Gruppe folgen auf die letzte Zwischensumme, ohne eigene Zeile.
    assert text.index("Zwischensumme Gruppe B") < text.index("Ohne Gruppe")
    assert "Zwischensumme Ohne Gruppe" not in text


def test_pdf_ohne_gruppen_nennt_keine_zwischensumme(tmp_path):
    inv = _beleg_mit_gruppen()
    for item in inv.items:
        item.gruppe = None
    text = _pdf_text(inv, tmp_path)
    assert "Zwischensumme" not in text


@pytest.mark.parametrize("sprache,label", [("de", "Zwischensumme"), ("en", "Subtotal")])
def test_zwischensumme_label_je_belegsprache(tmp_path, sprache, label):
    inv = _beleg_mit_gruppen()
    inv.document_language = sprache
    text = _pdf_text(inv, tmp_path)
    assert f"{label} Gruppe A" in text


# ------------------------------------------------ XML: BT-127, flach ohne Zwischensummen

def _zeilendokument(xml: str, nr: int):
    """AssociatedDocumentLineDocument der Position `nr`; die Notiz steht dort
    und nicht im Settlement (BT-127 ist eine Dokumentzeilenangabe)."""
    for zeile in ET.fromstring(xml.encode("utf-8")).iter(f"{RAM}IncludedSupplyChainTradeLineItem"):
        doc = zeile.find(f"{RAM}AssociatedDocumentLineDocument")
        if doc.findtext(f"{RAM}LineID") == str(nr):
            return doc
    raise AssertionError(f"Position {nr} fehlt")


def test_xml_traegt_die_gruppe_als_positionsnotiz_bt127():
    xml = zugferd_xml.generate_xml(_beleg_mit_gruppen(), orm_company())

    doc = _zeilendokument(xml, 1)
    # CII-Sequenz im AssociatedDocumentLineDocument: LineID vor IncludedNote
    # (docs/DEV-DOCU.md, "Reihenfolge in der CII"). Ein find() sieht die Notiz
    # auch an falscher Stelle; die Tagfolge haelt sie.
    assert [k.tag for k in doc] == [f"{RAM}LineID", f"{RAM}IncludedNote"]
    assert doc.findtext(f"{RAM}IncludedNote/{RAM}Content") == "Gruppe: Gruppe A"
    assert _zeilendokument(xml, 2).findtext(f"{RAM}IncludedNote/{RAM}Content") == "Gruppe: Gruppe A"
    # Ohne Gruppe kein leeres Element — EN 16931: optionale Angabe entfaellt ganz.
    assert _zeilendokument(xml, 4).find(f"{RAM}IncludedNote") is None
    # Die XML bleibt flach: Gruppen stehen nur als Notizen, nie als Summenzeilen.
    assert "Zwischensumme" not in xml


def test_xml_maskiert_den_gruppentext():
    inv = _beleg_mit_gruppen()
    inv.items[0].gruppe = "A & B <Ltd>"
    xml = zugferd_xml.generate_xml(inv, orm_company())

    # Der Parselauf beweist beides: Die Datei bleibt gueltig UND der Inhalt
    # kommt unveraendert zurueck (maskiert stünde "&amp;" im Ergebnis).
    assert _zeilendokument(xml, 1).findtext(f"{RAM}IncludedNote/{RAM}Content") == "Gruppe: A & B <Ltd>"


@pytest.mark.skipif(not mustang.jar_available(), reason="Mustang-JAR nicht verfügbar")
def test_mustang_meldet_die_gruppen_xml_als_valide(tmp_path):
    xml = zugferd_xml.generate_xml(_beleg_mit_gruppen(), orm_company())
    pfad = tmp_path / "beleg.xml"
    pfad.write_text(xml, encoding="utf-8")

    befund = mustang.validate(pfad)
    mustang_befund.gueltig(befund, befund["errors"])
    assert "XML:valid" in befund["raw"], befund["raw"]


# ------------------------------------------------ Finalisieren: Validator- und Mustang-Gate

def _kunde(pg_session):
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                     address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE")
    pg_session.add(kunde)
    pg_session.flush()
    return kunde


def _entwurf_mit_gruppen(pg_session):
    kunde = _kunde(pg_session)
    inv = Invoice(invoice_number=f"RE-GR-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
                  issue_date=date(2026, 7, 8), delivery_date=date(2026, 7, 8),
                  due_date=date(2026, 7, 22), currency="EUR", zugferd_profile="EN16931",
                  tax_category="S", status="draft", payment_terms="14 Tage netto",
                  net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
                  gross_total=Decimal("238.00"))
    inv.items = [
        InvoiceItem(position=1, description="Erstes Digital", unit="Stunde",
                    quantity=Decimal("1"), unit_price=Decimal("100.00"),
                    tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
                    tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"),
                    gruppe="Gruppe A"),
        InvoiceItem(position=2, description="Zweites Digital", unit="Stunde",
                    quantity=Decimal("1"), unit_price=Decimal("100.00"),
                    tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
                    tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"),
                    gruppe="Gruppe A"),
    ]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_entwurf_mit_gruppen_laueft_durch_validator_und_mustang(pg_session):
    """Der 303er beweist beide Gates: Der ECHTE Validator muss den Beleg
    freigeben, und die Route veroeffentlicht nur, wenn Mustang is_valid UND
    XML:valid meldet (Mustang-Lauf ueber tests/helpers/finalize_pipeline.py)."""
    inv = _entwurf_mit_gruppen(pg_session)
    try:
        r = finalize_with_fake_pipeline(pg_session, inv.id)
        assert r.status_code == 303, r.text

        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.status == "issued"
        assert "Gruppe: Gruppe A" in (row.zugferd_xml or "")
    finally:
        cleanup(inv.invoice_number)


def _gebundener_entwurf_mit_erstattung(pg_session):
    """Festlegung 11: gebundene 380 mit einer negativen Position (Erstattung
    im Abrechnungsmonat); die Rechnungssumme netto bleibt groesser null."""
    kunde = _kunde(pg_session)
    inv = Invoice(invoice_number=f"RE-ER-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
                  issue_date=date(2026, 7, 8), delivery_date=date(2026, 7, 8),
                  due_date=date(2026, 7, 22), currency="EUR", zugferd_profile="EN16931",
                  tax_category="S", status="draft", payment_terms="14 Tage netto",
                  net_total=Decimal("70.00"), tax_total=Decimal("13.30"),
                  gross_total=Decimal("83.30"),
                  uebergabe_beleg_sha256="1" * 64)
    inv.items = [
        InvoiceItem(position=1, description="Beteiligung Q2", unit="Pauschal",
                    quantity=Decimal("1"), unit_price=Decimal("100.00"),
                    tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
                    tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00")),
        InvoiceItem(position=2, description="Erstattung zuviel gezahlt", unit="Pauschal",
                    quantity=Decimal("1"), unit_price=Decimal("-30.00"),
                    tax_rate=Decimal("19"), net_amount=Decimal("-30.00"),
                    tax_amount=Decimal("-5.70"), gross_amount=Decimal("-35.70")),
    ]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_erstattung_laueft_durch_validator_und_mustang(pg_session):
    inv = _gebundener_entwurf_mit_erstattung(pg_session)
    try:
        r = finalize_with_fake_pipeline(pg_session, inv.id)
        assert r.status_code == 303, r.text

        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.status == "issued"
    finally:
        cleanup(inv.invoice_number)


# ------------------------------------------------ Validator: ITEM_PRICE_NEGATIVE

def _codes(befunde):
    return {b.code for b in befunde}


def _negative_position():
    return item_stub(position=2, unit_price=Decimal("-30.00"),
                     net_amount=Decimal("-30.00"), tax_amount=Decimal("-5.70"),
                     gross_amount=Decimal("-35.70"))


def _summen(items, **over):
    netto = sum(i.net_amount for i in items)
    steuer = sum(i.tax_amount for i in items)
    return dict(net_total=netto, tax_total=steuer, gross_total=netto + steuer, **over)


def test_negative_position_bleibt_fuer_manuelle_rechnung_fehler():
    """Die Ausnahme gilt NUR gebundenen 380; eine manuell getippte 380 mit
    negativem Preis bleibt ein Fehler."""
    inv = validator_invoice_stub(items=[_negative_position()],
                                 **_summen([_negative_position()]))
    errors, _ = validate_invoice(inv, company_stub())
    assert "ITEM_PRICE_NEGATIVE" in _codes(errors)


def test_negative_position_ist_fuer_gebundene_380_zulaessig():
    items = [item_stub(position=1), _negative_position()]
    inv = validator_invoice_stub(items=items, **_summen(items),
                                 uebergabe_beleg_sha256="1" * 64)
    errors, _ = validate_invoice(inv, company_stub())
    assert "ITEM_PRICE_NEGATIVE" not in _codes(errors)


def test_negative_position_mit_summe_nicht_positiv_bleibt_fehler():
    """Die Erstattung darf die Rechnung nicht ins Negative kippen: Summe <= 0
    greift die Ausnahme nicht."""
    inv = validator_invoice_stub(items=[_negative_position()],
                                 net_total=Decimal("0.00"),
                                 tax_total=Decimal("0.00"),
                                 gross_total=Decimal("0.00"),
                                 uebergabe_beleg_sha256="1" * 64)
    errors, _ = validate_invoice(inv, company_stub())
    assert "ITEM_PRICE_NEGATIVE" in _codes(errors)


def test_negative_position_bleibt_fuer_gebundene_389_fehler():
    """Nur die 380: Eine Honorargutschrift (389) mit negativem Preis bleibt
    unzulaessig, auch wenn sie aus einem Beleg stammt."""
    inv = validator_invoice_stub(invoice_type="self_billing",
                                 items=[_negative_position()],
                                 **_summen([_negative_position()]),
                                 uebergabe_beleg_sha256="1" * 64)
    errors, _ = validate_invoice(inv, company_stub())
    assert "ITEM_PRICE_NEGATIVE" in _codes(errors)


# ------------------------------------------------ Validator: POSITION_GRUPPE_GETRENNT

def test_getrennte_gruppe_ist_am_manuellen_entwurf_fehler():
    items = [
        item_stub(position=1, gruppe="Gruppe A"),
        item_stub(position=2, gruppe="Gruppe B"),
        item_stub(position=3, gruppe="Gruppe A"),
    ]
    inv = validator_invoice_stub(items=items, **_summen(items))
    errors, _ = validate_invoice(inv, company_stub())
    assert "POSITION_GRUPPE_GETRENNT" in _codes(errors)


def test_zusammenhaengende_gruppe_ist_kein_befund():
    items = [
        item_stub(position=1, gruppe="Gruppe A"),
        item_stub(position=2, gruppe="Gruppe A"),
        item_stub(position=3, gruppe="Gruppe B"),
    ]
    inv = validator_invoice_stub(items=items, **_summen(items))
    errors, _ = validate_invoice(inv, company_stub())
    assert "POSITION_GRUPPE_GETRENNT" not in _codes(errors)


def test_getrennte_gruppe_prueft_der_validator_nur_am_manuellen_entwurf():
    """Der Leser erzwingt den Zusammenhang fuer Auftraege; der Validator
    wiederholt das nicht an gebundenen Belegen."""
    items = [
        item_stub(position=1, gruppe="Gruppe A"),
        item_stub(position=2, gruppe="Gruppe B"),
        item_stub(position=3, gruppe="Gruppe A"),
    ]
    inv = validator_invoice_stub(items=items, **_summen(items),
                                 uebergabe_beleg_sha256="1" * 64)
    errors, _ = validate_invoice(inv, company_stub())
    assert "POSITION_GRUPPE_GETRENNT" not in _codes(errors)


# ------------------------------------------------ Bindung (belegsperre)

def test_belegsperre_bindet_die_gruppe_an_den_bestand():
    alt = SimpleNamespace(position=1, quantity=Decimal("1"), unit_price=Decimal("10"),
                          unit="Stück", basis_netto=None, satz=None,
                          leistung_von=None, leistung_bis=None, gruppe="Gruppe A")
    inv = SimpleNamespace(items=[alt])
    eingabe = [{"description": "Neu", "quantity": "9", "unit_price": "99", "unit": "Stunde",
                "gruppe": "Gruppe Z"}]

    gebunden = belegsperre.positionen_binden(inv, eingabe)

    assert gebunden[0]["gruppe"] == "Gruppe A"


def test_die_sperre_nennt_die_gruppen():
    assert any("Gruppe" in feld for feld in belegsperre.GESPERRTE_FELDER)


# ------------------------------------------------ Formular

def _formular_entwurf(pg_session, kunde, *, aus_beleg):
    inv = Invoice(
        invoice_number=f"RE-FG-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
        issue_date=date(2026, 9, 3), due_date=date(2026, 9, 17),
        tax_category="S", status="draft",
        net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
        uebergabe_beleg_sha256="1" * 64 if aus_beleg else None,
    )
    pg_session.add(inv)
    pg_session.flush()
    pg_session.add(InvoiceItem(
        invoice_id=inv.id, position=1, description="Erstes Digital", unit="Stunde",
        quantity=Decimal("1"), unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
        net_amount=Decimal("100.00"), tax_amount=Decimal("19.00"),
        gross_amount=Decimal("119.00"), gruppe="Gruppe A",
    ))
    pg_session.commit()
    return inv


def _gruppen_feld(html: str) -> str:
    feld = re.search(r'<input[^>]*x-model="item\.gruppe"[^>]*>', html)
    assert feld, "Formular zeigt kein Gruppenfeld an der Position"
    return feld.group()


def test_formular_zeigt_die_gruppe_und_traegt_den_bestand(client, pg_session):
    kunde = _kunde(pg_session)
    entwurf = _formular_entwurf(pg_session, kunde, aus_beleg=False)

    html = client.get(f"/invoices/{entwurf.id}/bearbeiten").text

    # Der gespeicherte Wert steht im Alpine-Formular (items_json).
    assert "Gruppe A" in html
    assert "readonly" not in _gruppen_feld(html)


def test_formular_sperrt_die_gruppe_am_beleg_entwurf(client, pg_session):
    kunde = _kunde(pg_session)
    entwurf = _formular_entwurf(pg_session, kunde, aus_beleg=True)

    html = client.get(f"/invoices/{entwurf.id}/bearbeiten").text

    feld = _gruppen_feld(html)
    assert "Gruppe A" in html
    assert "readonly" in feld, feld


# ------------------------------------------------ Datenbank: Spalte nullable

def test_gruppe_ist_nullable_und_speicherbar(pg_session):
    kunde = _kunde(pg_session)
    inv = Invoice(invoice_number=f"RE-DB-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
                  issue_date=date(2026, 9, 3), due_date=date(2026, 9, 17),
                  tax_category="S", status="draft",
                  net_total=Decimal("0"), tax_total=Decimal("0"),
                  gross_total=Decimal("0"))
    pg_session.add(inv)
    pg_session.flush()
    pg_session.add(InvoiceItem(
        invoice_id=inv.id, position=1, description="Ohne Gruppe", unit="Stück",
        quantity=Decimal("1"), unit_price=Decimal("0"), tax_rate=Decimal("19"),
        net_amount=Decimal("0"), tax_amount=Decimal("0"), gross_amount=Decimal("0"),
    ))
    pg_session.commit()

    pg_session.expire_all()
    ohne = pg_session.get(Invoice, inv.id).items[0]
    assert ohne.gruppe is None
    ohne.gruppe = "Gruppe A"
    pg_session.commit()

    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).items[0].gruppe == "Gruppe A"
