"""Einheitenkatalog Option A (docs/specs/einheiten.md): eine Quelle fuer Formular,
Validator und CII. Unbekannte Werte werden nie zu Stueck umgedeutet.
"""
import json
import re
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import defusedxml.ElementTree as DET
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem, ValidationResult
from app.services import pdf_generator, zugferd_xml
from app.services.einheiten import (
    Einheit,
    UnknownUnitError,
    einheiten,
    resolve_einheit,
)
from app.services.invoice_guard import InvoiceStateError, register_invoice_guard

register_invoice_guard()

RAM = "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"
NS = {"ram": RAM}

# Spec-Tabelle: 10 Schluessel, 16 Bezeichnungen, Reihenfolge verbindlich.
ERWARTETE_KATALOG = (
    ("piece", ("Stück",), "C62"),
    ("person", ("Person", "Personen", "Persons"), "IE"),
    ("hour", ("Stunde", "Stunden"), "HUR"),
    ("day", ("Tag", "Tage"), "DAY"),
    ("month", ("Monat", "Monate"), "MON"),
    ("kilometre", ("Kilometer",), "KMT"),
    ("metre", ("Meter",), "MTR"),
    ("kilogram", ("kg",), "KGM"),
    ("litre", ("Liter",), "LTR"),
    ("lump_sum", ("Pauschal", "Pauschale"), "LS"),
)
ALT_13 = (
    ("Stück", "C62"),
    ("Stunde", "HUR"),
    ("Stunden", "HUR"),
    ("Tag", "DAY"),
    ("Tage", "DAY"),
    ("Monat", "MON"),
    ("Monate", "MON"),
    ("Kilometer", "KMT"),
    ("Meter", "MTR"),
    ("kg", "KGM"),
    ("Liter", "LTR"),
    ("Pauschal", "LS"),
    ("Pauschale", "LS"),
)
ALLE_16 = tuple(b for _, bez, _ in ERWARTETE_KATALOG for b in bez)


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _customer(pg_session, name="Kunde GmbH"):
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name=name,
        address_line1="Weg 1",
        zip_code="80331",
        city="München",
        country="DE",
    )
    pg_session.add(c)
    pg_session.commit()
    return c


def _payload(customer, items, issue="2026-06-11"):
    return {
        "customer_id": str(customer.id),
        "issue_date": issue,
        "due_date": "2026-06-25",
        "tax_category": "S",
        "items_json": json.dumps(items),
    }


def _item(desc="Leistung", unit="Stück", qty="1", price="100", rate="19"):
    return {
        "description": desc,
        "unit": unit,
        "quantity": qty,
        "unit_price": price,
        "tax_rate": rate,
    }


def _draft(pg_session, customer, *, unit="Stück", qty="1", desc="Leistung"):
    inv = Invoice(
        invoice_number=f"RE-{uuid.uuid4().hex[:8]}",
        customer_id=customer.id,
        issue_date=date(2026, 6, 11),
        due_date=date(2026, 6, 25),
        delivery_date=date(2026, 6, 11),
        status="draft",
        currency="EUR",
        zugferd_profile="EN16931",
        tax_category="S",
        payment_terms="14 Tage",
        net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
        archive_until=date(2034, 12, 31),
    )
    pg_session.add(inv)
    pg_session.flush()
    q = Decimal(qty)
    price = Decimal("100.00")
    net = (q * price).quantize(Decimal("0.01"))
    tax = (net * Decimal("0.19")).quantize(Decimal("0.01"))
    pg_session.add(InvoiceItem(
        invoice_id=inv.id,
        position=1,
        description=desc,
        unit=unit,
        quantity=q,
        unit_price=price,
        tax_rate=Decimal("19"),
        net_amount=net,
        tax_amount=tax,
        gross_amount=net + tax,
    ))
    inv.net_total = net
    inv.tax_total = tax
    inv.gross_total = net + tax
    pg_session.commit()
    return inv


def _einheit_select(html: str) -> str:
    treffer = re.search(
        r'<label class="label">Einheit</label>\s*<select[^>]*>.*?</select>',
        html,
        re.S,
    )
    assert treffer, "kein Einheit-Select im Formular"
    return treffer.group(0)


def _option_werte(select_html: str) -> list[str]:
    return re.findall(r'<option[^>]*>([^<]+)</option>', select_html)


def _company_counter(pg_session) -> int:
    return pg_session.query(Company).filter(Company.id == 1).one().invoice_counter


def _frisch(pg_session, inv_id):
    pg_session.expunge_all()
    return pg_session.query(Invoice).filter(Invoice.id == inv_id).first()


def _xml_unit_codes(xml: str) -> list[str]:
    root = DET.fromstring(xml.encode("utf-8"))
    return [el.get("unitCode") for el in root.findall(".//ram:BilledQuantity", NS)]


def _pdf_text(path: Path) -> str:
    return "".join(p.extract_text() or "" for p in PdfReader(str(path)).pages)


# ── E1: Formular aus dem Katalog ─────────────────────────────────────────────

def test_e1_neu_formular_zeigt_genau_16_katalogbezeichnungen_in_reihenfolge(pg_session):
    r = _client(pg_session).get("/invoices/neu")
    assert r.status_code == 200
    werte = _option_werte(_einheit_select(r.text))
    assert werte == list(ALLE_16)


def test_e1_bearbeiten_formular_zeigt_dieselben_16(pg_session):
    cust = _customer(pg_session)
    inv = _draft(pg_session, cust)
    r = _client(pg_session).get(f"/invoices/{inv.id}/bearbeiten")
    assert r.status_code == 200
    werte = _option_werte(_einheit_select(r.text))
    assert werte == list(ALLE_16)


def test_e1_alle_formularwerte_sind_aufloesbar():
    for bez in ALLE_16:
        resolve_einheit(bez)


def test_e1_zusaetzlicher_katalogeintrag_erscheint_ohne_templateaenderung(pg_session):
    original = einheiten

    def mit_extra():
        basis = list(original())
        basis.append(Einheit(key="box", un_code="XBX", bezeichnungen=("Karton",)))
        return tuple(basis)

    with patch("app.services.einheiten.einheiten", mit_extra):
        r = _client(pg_session).get("/invoices/neu")
    assert r.status_code == 200
    werte = _option_werte(_einheit_select(r.text))
    assert "Karton" in werte


# ── E2: Resolver und XML-Codes ───────────────────────────────────────────────

def test_e2_katalog_reihenfolge_und_codes():
    katalog = einheiten()
    assert len(katalog) == 10
    for i, (key, bez, code) in enumerate(ERWARTETE_KATALOG):
        e = katalog[i]
        assert e.key == key
        assert tuple(e.bezeichnungen) == bez
        assert e.un_code == code


def test_e2_altbezeichnungen_und_personen_ueber_resolver_und_xml():
    from tests.factories import company_stub, customer_stub, item_stub, zugferd_invoice_stub

    for bez, code in ALT_13 + (("Person", "IE"), ("Personen", "IE"), ("Persons", "IE")):
        assert resolve_einheit(bez).un_code == code
        inv = zugferd_invoice_stub(items=[item_stub(unit=bez)])
        inv.customer = customer_stub()
        root = DET.fromstring(
            zugferd_xml.generate_xml(inv, company_stub()).encode("utf-8")
        )
        qty = root.find(".//ram:BilledQuantity", NS)
        assert qty is not None
        assert qty.get("unitCode") == code, f"{bez} → {qty.get('unitCode')!r}"


def test_e2_leerer_und_unbekannter_wert_werfen():
    with pytest.raises(UnknownUnitError):
        resolve_einheit("")
    with pytest.raises(UnknownUnitError) as exc:
        resolve_einheit("Flasche")
    assert exc.value.wert == "Flasche"
    with pytest.raises(UnknownUnitError):
        resolve_einheit("stück")  # keine Gross-/Kleinschreibungsheuristik


# ── E3: Persons speichern, XML und PDF ───────────────────────────────────────

def test_e3_zwei_persons_positionen_in_xml_und_pdf(pg_session, tmp_path):
    cust = _customer(pg_session)
    items = [
        _item(desc="Preisklasse A", unit="Persons", qty="3", price="40"),
        _item(desc="Preisklasse B", unit="Persons", qty="5", price="60"),
    ]
    r = _client(pg_session).post("/invoices/neu", data=_payload(cust, items))
    assert r.status_code == 303, r.text[:500]

    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == cust.id).one()
    assert [i.unit for i in inv.items] == ["Persons", "Persons"]
    assert [i.quantity for i in inv.items] == [Decimal("3"), Decimal("5")]

    company = pg_session.query(Company).filter(Company.id == 1).one()
    # Relationship fuer Generator laden
    inv = (
        pg_session.query(Invoice)
        .filter(Invoice.id == inv.id)
        .one()
    )
    xml = zugferd_xml.generate_xml(inv, company)
    codes = _xml_unit_codes(xml)
    assert codes == ["IE", "IE"]

    pdf_path = tmp_path / "persons.pdf"
    pdf_generator.generate_pdf(inv, company, pdf_path)
    text = _pdf_text(pdf_path)
    assert "Persons" in text
    assert "Stück" not in text or text.count("Persons") >= 2
    # Mengen sichtbar (PDF formatiert deutsch)
    assert "3" in text and "5" in text


# ── E4: HTTP 400, keine Teilpersistenz ───────────────────────────────────────

@pytest.mark.parametrize("unit", ["Flasche", "", "   "])
def test_e4_anlegen_mit_ungueltiger_einheit_ist_400_ohne_persistenz(pg_session, unit):
    cust = _customer(pg_session)
    vor_counter = _company_counter(pg_session)
    r = _client(pg_session).post(
        "/invoices/neu",
        data=_payload(cust, [_item(unit=unit)]),
    )
    assert r.status_code == 400
    assert "Position" in r.text
    # Eingegebener Wert benannt (leer/Whitespace: Position reicht; sonst der Wert)
    if unit.strip():
        assert "Flasche" in r.text

    pg_session.expire_all()
    assert pg_session.query(Invoice).filter(Invoice.customer_id == cust.id).count() == 0
    assert _company_counter(pg_session) == vor_counter


@pytest.mark.parametrize("unit", ["Flasche", "", "   "])
def test_e4_bearbeiten_mit_ungueltiger_einheit_aendert_nichts(pg_session, unit):
    cust = _customer(pg_session)
    inv = _draft(pg_session, cust, unit="Stück")
    inv_id = inv.id
    cust_id = cust.id
    vor = _frisch(pg_session, inv_id)
    vor_unit = vor.items[0].unit
    vor_desc = vor.items[0].description
    vor_counter = _company_counter(pg_session)

    r = _client(pg_session).post(
        f"/invoices/{inv_id}/bearbeiten",
        data={
            "customer_id": str(cust_id),
            "issue_date": "2026-06-11",
            "due_date": "2026-06-25",
            "tax_category": "S",
            "items_json": json.dumps([_item(desc="Geaendert", unit=unit)]),
        },
    )
    assert r.status_code == 400
    assert "Position" in r.text

    frisch = _frisch(pg_session, inv_id)
    assert frisch.items[0].unit == vor_unit
    assert frisch.items[0].description == vor_desc
    assert _company_counter(pg_session) == vor_counter


# ── E5: Altbestand, Validator, Generator ─────────────────────────────────────

def test_e5_altentwurf_zeigt_ungueltigen_wert(pg_session):
    cust = _customer(pg_session)
    inv = _draft(pg_session, cust, unit="Flasche")
    r = _client(pg_session).get(f"/invoices/{inv.id}/bearbeiten")
    assert r.status_code == 200
    assert "Flasche" in r.text
    assert "Flasche (ungueltig)" in r.text
    # Nicht still auf Stueck umgebogen in den geladenen Positionen
    assert '"unit": "Flasche"' in r.text or '"unit":"Flasche"' in r.text


def test_e5_pruefen_meldet_unit_unknown_finalisieren_bleibt_draft(pg_session):
    cust = _customer(pg_session)
    inv = _draft(pg_session, cust, unit="Flasche")
    client = _client(pg_session)

    r = client.post(f"/invoices/{inv.id}/pruefen")
    assert r.status_code == 303
    pg_session.expire_all()
    result = (
        pg_session.query(ValidationResult)
        .filter(ValidationResult.invoice_id == inv.id)
        .order_by(ValidationResult.validated_at.desc())
        .first()
    )
    assert result is not None
    assert result.is_valid is False
    codes = {e["code"] for e in result.errors}
    assert "UNIT_UNKNOWN" in codes

    r2 = client.post(f"/invoices/{inv.id}/finalisieren")
    assert r2.status_code == 400
    frisch = _frisch(pg_session, inv.id)
    assert frisch.status == "draft"
    assert frisch.zugferd_xml is None
    assert frisch.pdf_filename is None


def test_e5_direkter_generator_wirft_unknown_unit_error():
    from tests.factories import company_stub, customer_stub, item_stub, zugferd_invoice_stub

    inv = zugferd_invoice_stub(items=[item_stub(unit="Flasche")])
    inv.customer = customer_stub()
    with pytest.raises(UnknownUnitError):
        zugferd_xml.generate_xml(inv, company_stub())


# ── E6: Pauschal bleibt, Korrektur entfernt UNIT_UNKNOWN ─────────────────────

def test_e6_pauschal_bleibt_beim_oeffnen_code_ls(pg_session):
    cust = _customer(pg_session)
    r = _client(pg_session).post(
        "/invoices/neu",
        data=_payload(cust, [_item(unit="Pauschal")]),
    )
    assert r.status_code == 303
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == cust.id).one()
    assert inv.items[0].unit == "Pauschal"
    assert resolve_einheit(inv.items[0].unit).un_code == "LS"

    r2 = _client(pg_session).get(f"/invoices/{inv.id}/bearbeiten")
    assert r2.status_code == 200
    assert '"unit": "Pauschal"' in r2.text or '"unit":"Pauschal"' in r2.text


def test_e6_korrektur_auf_personen_entfernt_unit_unknown(pg_session):
    cust = _customer(pg_session)
    inv = _draft(pg_session, cust, unit="Flasche")
    client = _client(pg_session)

    client.post(f"/invoices/{inv.id}/pruefen")
    codes_vorher = {
        e["code"]
        for e in (
            pg_session.query(ValidationResult)
            .filter(ValidationResult.invoice_id == inv.id)
            .order_by(ValidationResult.validated_at.desc())
            .first()
            .errors
        )
    }
    assert "UNIT_UNKNOWN" in codes_vorher

    r = client.post(
        f"/invoices/{inv.id}/bearbeiten",
        data=_payload(cust, [_item(unit="Personen")]),
    )
    assert r.status_code == 303

    client.post(f"/invoices/{inv.id}/pruefen")
    pg_session.expire_all()
    result = (
        pg_session.query(ValidationResult)
        .filter(ValidationResult.invoice_id == inv.id)
        .order_by(ValidationResult.validated_at.desc())
        .first()
    )
    codes = {e["code"] for e in result.errors}
    assert "UNIT_UNKNOWN" not in codes


# ── E7: Issued unveraenderlich, Archiv unveraendert ──────────────────────────

def test_e7_issued_einheit_aendern_wirft_guardfehler(pg_session):
    cust = _customer(pg_session)
    inv = Invoice(
        invoice_number=f"RE-{uuid.uuid4().hex[:8]}",
        customer_id=cust.id,
        issue_date=date(2026, 6, 11),
        due_date=date(2026, 6, 25),
        delivery_date=date(2026, 6, 11),
        status="issued",
        currency="EUR",
        zugferd_profile="EN16931",
        tax_category="S",
        net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
        archive_until=date(2034, 12, 31),
        zugferd_xml="<xml>alt</xml>",
        pdf_filename="RE-alt.pdf",
    )
    pg_session.add(inv)
    pg_session.flush()
    item = InvoiceItem(
        invoice_id=inv.id,
        position=1,
        description="Leistung",
        unit="Stück",
        quantity=Decimal("1"),
        unit_price=Decimal("100"),
        tax_rate=Decimal("19"),
        net_amount=Decimal("100.00"),
        tax_amount=Decimal("19.00"),
        gross_amount=Decimal("119.00"),
    )
    pg_session.add(item)
    pg_session.commit()

    item.unit = "Personen"
    with pytest.raises(InvoiceStateError):
        pg_session.commit()
    pg_session.rollback()


def test_e7_archivierte_xml_pdf_bleiben_nach_katalogerweiterung(pg_session, tmp_path):
    """Gespeicherte Artefakte werden gelesen, nicht neu erzeugt."""
    from app.config import get_settings

    settings = get_settings()
    marke = uuid.uuid4().hex[:8]
    pdf_name = f"RE-E7-{marke}.pdf"
    xml_name = f"RE-E7-{marke}.xml"
    pdf_path = settings.storage_path / "pdfs" / pdf_name
    xml_path = settings.storage_path / "xml" / xml_name
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    xml_path.parent.mkdir(parents=True, exist_ok=True)
    xml_inhalt = '<rsm:CrossIndustryInvoice unitCode="C62">E7-MARKER</rsm:CrossIndustryInvoice>'
    pdf_inhalt = b"%PDF-1.4\nE7-PDF-MARKER\n"
    xml_path.write_text(xml_inhalt, encoding="utf-8")
    pdf_path.write_bytes(pdf_inhalt)

    cust = _customer(pg_session)
    inv = Invoice(
        invoice_number=f"RE-E7-{marke}",
        customer_id=cust.id,
        issue_date=date(2026, 6, 11),
        due_date=date(2026, 6, 25),
        status="issued",
        currency="EUR",
        zugferd_profile="EN16931",
        tax_category="S",
        net_total=Decimal("100"),
        tax_total=Decimal("19"),
        gross_total=Decimal("119"),
        zugferd_xml=xml_inhalt,
        pdf_filename=pdf_name,
    )
    pg_session.add(inv)
    pg_session.commit()

    original = einheiten

    def mit_extra():
        return original() + (
            Einheit(key="box", un_code="XBX", bezeichnungen=("Karton",)),
        )

    try:
        with patch("app.services.einheiten.einheiten", mit_extra):
            r_pdf = _client(pg_session).get(f"/invoices/{inv.id}/pdf")
            assert r_pdf.status_code == 200
            assert b"E7-PDF-MARKER" in r_pdf.content
            # DB-XML unveraendert
            frisch = _frisch(pg_session, inv.id)
            assert frisch.zugferd_xml == xml_inhalt
            assert xml_path.read_text(encoding="utf-8") == xml_inhalt
    finally:
        pdf_path.unlink(missing_ok=True)
        xml_path.unlink(missing_ok=True)


# --- Hinweis zu den Schreibweisen ----------------------------------------

HINWEIS = "Singular, Plural und englische Schreibweise sind dieselbe Einheit"


def test_formular_erklaert_die_doppelten_schreibweisen(pg_session):
    """Drei Eintraege fuer Personen sehen im Ausklappmenue aus wie drei Einheiten.

    Person, Personen und Persons tragen denselben Code IE; die Wahl bestimmt nur
    den Text auf dem Beleg. Ohne diesen Satz sieht es aus, als koenne man sich
    zwischen ihnen vertun. Dasselbe gilt fuer Stunde/Stunden, Tag/Tage,
    Monat/Monate und Pauschal/Pauschale.
    """
    r = _client(pg_session).get("/invoices/neu")
    assert r.status_code == 200
    assert HINWEIS in r.text, "Das Anlegeformular erklaert die Schreibweisen nicht"


def test_der_hinweis_steht_ausserhalb_der_positionsschleife(pg_session):
    """Der Satz gehoert neben die Ueberschrift, nicht in die Positionsschleife.

    Innerhalb von `x-for` erschiene er im Browser einmal je Position. Gezaehlt
    werden kann das nicht: `x-for` ist Alpine, der Server rendert den Block genau
    einmal und vervielfaeltigt ihn nie. Ein Test auf `count == 1` waere deshalb
    tautologisch, er bliebe auch bei falscher Platzierung gruen. Gemessen wird
    daher die Stelle: der Hinweis muss vor dem Schleifenblock stehen.
    """
    cust = _customer(pg_session)
    inv = _draft(pg_session, cust)
    r = _client(pg_session).get(f"/invoices/{inv.id}/bearbeiten")
    assert r.status_code == 200

    schleife = r.text.find('x-for="(item, idx) in items"')
    assert schleife != -1, "Positionsschleife nicht gefunden"
    stelle = r.text.find(HINWEIS)
    assert stelle != -1, "Hinweis nicht gefunden"
    assert stelle < schleife, (
        "Der Hinweis steht in der Positionsschleife und erschiene je Position"
    )
