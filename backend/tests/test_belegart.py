"""Belegart und Vorabrechnung (docs/specs/vorabrechnung.md, Option B, V1-V10).

386 (Anzahlungsrechnung) ist eine bewusst waehlbare Belegart neben der
Standardrechnung; Standard bleibt die Vorgabe. 381/384/389 sind allgemein
gueltige Codes, aber keine manuelle Wahl: sie entstehen auf eigenen Wegen
(Storno, Integrationsweg). Deshalb genuegt die Mitgliedschaft in der
Typtabelle nicht als Waehlbarkeitspruefung.

Der erste 386-Schnitt deckt nur die noch nicht bezahlte Vorausforderung mit
bekanntem geplantem Leistungszeitraum. Das ist eine Produktbegrenzung,
strenger als EN16931, und wird hier nicht als Normpflicht behandelt.
"""
import json
import re
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import mustang, pdf_generator, pdfa, zugferd_xml
from app.services.belegart import (
    TYPE_CODE_MAP,
    InvoiceTypeNotSelectable,
    UnknownInvoiceTypeError,
    belegart,
    manuelle_belegart,
    manuelle_belegarten,
)
from app.services.invoice_guard import InvoiceStateError
from app.services.validator import validate_invoice
from tests.factories import (
    company_stub,
    customer_stub,
    item_stub,
    validator_invoice_stub,
    zugferd_invoice_stub,
)
from tests.test_pdf_generator import _sample_company


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _kunde(pg_session, name="Kunde GmbH"):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name=name,
                 address_line1="Weg 1", zip_code="80331", city="Muenchen", country="DE")
    pg_session.add(c)
    pg_session.commit()
    return c


def _entwurf(pg_session, kunde, *, invoice_type=None, status="draft", aus_beleg=False):
    inv = Invoice(
        invoice_number=f"RE-{uuid.uuid4().hex[:8]}",
        customer_id=kunde.id,
        issue_date=date(2026, 6, 11),
        due_date=date(2026, 6, 25),
        status=status,
        currency="EUR",
        zugferd_profile="EN16931",
        tax_category="S",
        invoice_type=invoice_type,
        net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
        uebergabe_beleg_id="beleg-1" if aus_beleg else None,
        uebergabe_beleg_sha256=("1" * 64) if aus_beleg else None,
    )
    pg_session.add(inv)
    pg_session.flush()
    pg_session.add(InvoiceItem(
        invoice_id=inv.id, position=1, description="Beratung", unit="Stunde",
        quantity=Decimal("1"), unit_price=Decimal("100"), tax_rate=Decimal("19"),
        net_amount=Decimal("100.00"), tax_amount=Decimal("19.00"),
        gross_amount=Decimal("119.00"),
    ))
    pg_session.commit()
    return inv


def _payload(kunde, *, invoice_type=..., items=None):
    daten = {
        "customer_id": str(kunde.id),
        "issue_date": "2026-06-11",
        "due_date": "2026-06-25",
        "tax_category": "S",
        "items_json": json.dumps(items if items is not None else [{
            "description": "Beratung", "unit": "Stunde", "quantity": "1",
            "unit_price": "100", "tax_rate": "19",
        }]),
    }
    if invoice_type is not ...:
        daten["invoice_type"] = invoice_type
    return daten


def _frisch(pg_session, inv_id):
    # expire_all statt expunge_all: der Kunde aus _kunde bleibt an die Session
    # gebunden und wird bei Zugriff frisch geladen; expunge wuerde ihn
    # abkoppeln und _payload(kunde) liesse dann an DetachedInstanceError laufen.
    pg_session.expire_all()
    return pg_session.query(Invoice).filter(Invoice.id == inv_id).first()


def _zaehler(pg_session):
    return pg_session.query(Company).filter(Company.id == 1).one().invoice_counter


def _optionen(html: str, name: str):
    """Werte der Optionen eines select-Feldes, oder None wenn das Feld fehlt."""
    m = re.search(rf'<select[^>]*name="{re.escape(name)}"[^>]*>(.*?)</select>', html, re.S)
    if not m:
        return None
    return re.findall(r'<option[^>]*value="([^"]*)"', m.group(1))


def _gewaehlt(html: str, name: str):
    """value der selected-Option eines select-Feldes, oder None."""
    m = re.search(rf'<select[^>]*name="{re.escape(name)}"[^>]*>(.*?)</select>', html, re.S)
    if not m:
        return None
    block = m.group(1)
    sel = re.search(r'<option[^>]*value="([^"]*)"[^>]*selected', block)
    if sel:
        return sel.group(1)
    sel = re.search(r'<option[^>]*selected[^>]*value="([^"]*)"', block)
    return sel.group(1) if sel else None


def _pdf_text(inv, company, tmp_path):
    out = tmp_path / "beleg.pdf"
    pdf_generator.generate_pdf(inv, company, out)
    return "".join(page.extract_text() or "" for page in PdfReader(str(out)).pages)


# ── V5: Typaufloesung, Aliase, fail-closed ─────────────────────────────────
# Steht bewusst am Anfang: belegart() ist die fachliche Quelle, auf der alles
# andere aufbaut.

class TestV5Typaufloesung:
    @pytest.mark.parametrize("wert,bt3", [
        (None, "380"),
        ("standard", "380"),
        ("invoice", "380"),
        ("prepayment", "386"),
        ("credit_note", "381"),
        ("credit", "381"),
        ("storno", "381"),
        ("correction", "384"),
        ("self_billing", "389"),
        ("self-billing", "389"),
    ])
    def test_bekannte_werte_und_aliase_behalten_ihre_codes(self, wert, bt3):
        assert belegart(wert).bt3 == bt3

    @pytest.mark.parametrize("wert", ["386", "380", "unbekannt", "stornorechnung", ""])
    def test_unbekannte_werte_werfen(self, wert):
        """Rohe Codes wie '386' sind keine internen Werte; fail-closed."""
        with pytest.raises(UnknownInvoiceTypeError):
            belegart(wert)

    def test_kanonische_interne_werte(self):
        assert belegart(None).intern is None
        assert belegart("standard").intern is None
        assert belegart("invoice").intern is None
        assert belegart("prepayment").intern == "prepayment"
        assert belegart("storno").intern == "credit_note"
        assert belegart("self-billing").intern == "self_billing"

    def test_pdf_titel_aus_belegdarstellung(self):
        """Sichtbarer Titel liegt in Belegdarstellung, nicht mehr in belegart."""
        from app.services.belegsprache import darstellung
        de = darstellung("de")
        assert de.titel(None) == "RECHNUNG"
        assert de.titel("prepayment") == "ANZAHLUNGSRECHNUNG"
        assert de.titel("credit_note") == "GUTSCHRIFT"
        assert de.titel("correction") == "KORREKTURRECHNUNG"
        assert de.titel("self_billing") == "GUTSCHRIFT"
        assert not hasattr(belegart(None), "pdf_titel")

    def test_manuelle_waehlbarkeit(self):
        assert belegart(None).manuell_waehlbar
        assert belegart("prepayment").manuell_waehlbar
        for wert in ("credit_note", "correction", "self_billing"):
            assert not belegart(wert).manuell_waehlbar

    def test_manuelle_belegarten_genau_standard_und_anzahlung(self):
        arten = manuelle_belegarten()
        assert tuple(a.form_wert for a in arten) == ("standard", "prepayment")
        assert all(a.manuell_waehlbar for a in arten)

    def test_manuelle_belegart_abbildung(self):
        """Fehlendes Feld bleibt abwaertskompatibel Standard (Speicherung None)."""
        assert manuelle_belegart(None) is None
        assert manuelle_belegart("standard") is None
        assert manuelle_belegart("prepayment") == "prepayment"

    @pytest.mark.parametrize("wert", [
        "", "invoice", "386", "380", "381", "389",
        "credit_note", "credit", "storno", "correction",
        "self_billing", "self-billing", "schnitzel",
    ])
    def test_manuelle_belegart_verbotene_werte_werfen(self, wert):
        """381/389 sind allgemein gueltige Codes und trotzdem keine manuelle Wahl;
        die leere Zeichenfolge wird nicht still zu 380."""
        with pytest.raises(InvoiceTypeNotSelectable):
            manuelle_belegart(wert)

    def test_validator_meldet_unbekannten_gespeicherten_typ(self):
        inv = validator_invoice_stub(invoice_type="schnitzel")
        errors, _ = validate_invoice(inv, company_stub())
        assert any(e.code == "INVOICE_TYPE_INVALID" for e in errors)

    def test_generator_wirft_bei_unbekanntem_typ(self):
        inv = zugferd_invoice_stub(invoice_type="schnitzel")
        with pytest.raises(UnknownInvoiceTypeError):
            zugferd_xml.generate_xml(inv, company_stub())

    def test_kein_zweites_mapping_neben_der_fachlichen_quelle(self):
        """TYPE_CODE_MAP lebt in belegart.py; zugferd_xml re-exportiert dasselbe Objekt."""
        assert zugferd_xml.TYPE_CODE_MAP is TYPE_CODE_MAP
        assert TYPE_CODE_MAP["prepayment"] == "386"


# ── V1: Formular bietet exakt Standard und Anzahlung ────────────────────────

class TestV1FormularAuswahl:
    def test_neuformular_bietet_genau_standard_und_anzahlung(self, client):
        r = client.get("/invoices/neu")
        assert r.status_code == 200
        assert _optionen(r.text, "invoice_type") == ["standard", "prepayment"]

    def test_entwurfseditor_bietet_genau_standard_und_anzahlung(self, client, pg_session):
        inv = _entwurf(pg_session, _kunde(pg_session))
        r = client.get(f"/invoices/{inv.id}/bearbeiten")
        assert r.status_code == 200
        assert _optionen(r.text, "invoice_type") == ["standard", "prepayment"]

    def test_neuformular_vorgabe_ist_standard(self, client):
        r = client.get("/invoices/neu")
        assert _gewaehlt(r.text, "invoice_type") == "standard"

    def test_speichern_und_neuladen_erhaelt_die_wahl(self, client, pg_session):
        kunde = _kunde(pg_session)
        r = client.post("/invoices/neu", data=_payload(kunde, invoice_type="prepayment"))
        assert r.status_code == 303
        inv_id = uuid.UUID(r.headers["location"].rsplit("/", 1)[-1])
        assert _frisch(pg_session, inv_id).invoice_type == "prepayment"

        r = client.get(f"/invoices/{inv_id}/bearbeiten")
        assert _gewaehlt(r.text, "invoice_type") == "prepayment"

        r = client.post(f"/invoices/{inv_id}/bearbeiten",
                        data=_payload(kunde, invoice_type="standard"))
        assert r.status_code == 303
        assert _frisch(pg_session, inv_id).invoice_type is None

        r = client.get(f"/invoices/{inv_id}/bearbeiten")
        assert _gewaehlt(r.text, "invoice_type") == "standard"

    def test_fehlendes_feld_bei_neuanlage_ergibt_standard(self, client, pg_session):
        kunde = _kunde(pg_session)
        r = client.post("/invoices/neu", data=_payload(kunde))
        assert r.status_code == 303
        inv_id = uuid.UUID(r.headers["location"].rsplit("/", 1)[-1])
        assert _frisch(pg_session, inv_id).invoice_type is None


# ── V2: Ausgabe der Anzahlung (BT-3, PDF-Titel), Summen unveraendert ────────

class TestV2Ausgabe:
    def test_xml_bt3_386_bei_anzahlung_380_bei_standard(self):
        inv = zugferd_invoice_stub(
            invoice_type="prepayment", delivery_date=None,
            service_period_start=date(2026, 12, 1),
            service_period_end=date(2026, 12, 31),
        )
        xml = zugferd_xml.generate_xml(inv, company_stub())
        assert "<ram:TypeCode>386</ram:TypeCode>" in xml

        xml_std = zugferd_xml.generate_xml(zugferd_invoice_stub(), company_stub())
        assert "<ram:TypeCode>380</ram:TypeCode>" in xml_std

    def test_pdf_titel_anzahlungsrechnung_und_rechnung(self, tmp_path):
        inv = validator_invoice_stub(
            invoice_type="prepayment", delivery_date=None,
            service_period_start=date(2026, 12, 1),
            service_period_end=date(2026, 12, 31),
        )
        text = _pdf_text(inv, _sample_company(), tmp_path)
        assert "ANZAHLUNGSRECHNUNG" in text

        text_std = _pdf_text(validator_invoice_stub(), _sample_company(), tmp_path)
        assert "RECHNUNG" in text_std
        assert "ANZAHLUNGSRECHNUNG" not in text_std

    def test_positionen_und_summen_identisch_zwischen_den_arten(self):
        """Der Belegtyp veraendert weder Preise noch Mengen oder Summen."""
        def summen(xml):
            return {
                schluessel: re.search(
                    rf"<ram:{schluessel}[^>]*>([^<]+)</ram:{schluessel}>", xml
                ).group(1)
                for schluessel in (
                    "LineTotalAmount", "TaxBasisTotalAmount",
                    "GrandTotalAmount", "DuePayableAmount",
                )
            }

        basis = dict(
            delivery_date=None,
            service_period_start=date(2026, 12, 1),
            service_period_end=date(2026, 12, 31),
        )
        xml_386 = zugferd_xml.generate_xml(
            zugferd_invoice_stub(invoice_type="prepayment", **basis), company_stub())
        xml_380 = zugferd_xml.generate_xml(zugferd_invoice_stub(**basis), company_stub())
        assert summen(xml_386) == summen(xml_380)


# ── V3: Verbotene manuelle Wahl, serverseitig, ohne Wirkung ────────────────

VERBOTENE_WAHLEN = [
    "invoice", "", "386", "380", "381", "389",
    "credit_note", "credit", "storno", "correction",
    "self_billing", "self-billing", "schnitzel",
]


class TestV3VerboteneWahl:
    @pytest.mark.parametrize("wert", VERBOTENE_WAHLEN)
    def test_neu_post_mit_verbotener_wahl_400_ohne_wirkung(self, client, pg_session, wert):
        kunde = _kunde(pg_session)
        zaehler_vorher = _zaehler(pg_session)
        anzahl_vorher = pg_session.query(Invoice).count()

        r = client.post("/invoices/neu", data=_payload(kunde, invoice_type=wert))

        assert r.status_code == 400
        assert "INVOICE_TYPE_NOT_SELECTABLE" in r.text
        pg_session.expunge_all()
        assert pg_session.query(Invoice).count() == anzahl_vorher
        assert _zaehler(pg_session) == zaehler_vorher, (
            "Abgelehnte Wahl hat den Nummernzaehler erhoeht (Nummernluecke ohne Beleg)."
        )

    @pytest.mark.parametrize("wert", VERBOTENE_WAHLEN)
    def test_edit_post_mit_verbotener_wahl_400_ohne_wirkung(self, client, pg_session, wert):
        kunde = _kunde(pg_session)
        inv = _entwurf(pg_session, kunde)
        inv_id = inv.id

        r = client.post(f"/invoices/{inv_id}/bearbeiten",
                        data=_payload(kunde, invoice_type=wert))

        assert r.status_code == 400
        assert "INVOICE_TYPE_NOT_SELECTABLE" in r.text
        assert _frisch(pg_session, inv_id).invoice_type is None


# ── V4: Systembelege (389) behalten ihre Art ────────────────────────────────

class TestV4Systembelege:
    def test_389_entwurf_formular_ohne_typfeld(self, client, pg_session):
        inv = _entwurf(pg_session, _kunde(pg_session),
                       invoice_type="self_billing", aus_beleg=True)
        r = client.get(f"/invoices/{inv.id}/bearbeiten")
        assert r.status_code == 200
        assert 'name="invoice_type"' not in r.text

    def test_389_entwurf_ohne_typfeld_behaelt_art(self, client, pg_session):
        kunde = _kunde(pg_session)
        inv = _entwurf(pg_session, kunde, invoice_type="self_billing", aus_beleg=True)
        inv_id = inv.id

        r = client.post(f"/invoices/{inv_id}/bearbeiten", data=_payload(kunde))

        assert r.status_code == 303
        assert _frisch(pg_session, inv_id).invoice_type == "self_billing"

    @pytest.mark.parametrize("wert", ["standard", "prepayment"])
    def test_389_entwurf_umtypisieren_wird_abgelehnt(self, client, pg_session, wert):
        kunde = _kunde(pg_session)
        inv = _entwurf(pg_session, kunde, invoice_type="self_billing", aus_beleg=True)
        inv_id = inv.id

        r = client.post(f"/invoices/{inv_id}/bearbeiten",
                        data=_payload(kunde, invoice_type=wert))

        assert r.status_code == 400
        assert "INVOICE_TYPE_NOT_SELECTABLE" in r.text
        frisch = _frisch(pg_session, inv_id)
        assert frisch.invoice_type == "self_billing"
        assert frisch.uebergabe_beleg_sha256 == "1" * 64, "Herkunft veraendert"

    def test_storno_entwurf_bleibt_im_gesperrten_editorweg(self, client, pg_session):
        kunde = _kunde(pg_session)
        inv = _entwurf(pg_session, kunde, invoice_type="credit_note")
        assert client.get(f"/invoices/{inv.id}/bearbeiten").status_code == 400
        r = client.post(f"/invoices/{inv.id}/bearbeiten", data=_payload(kunde))
        assert r.status_code == 400


# ── V6: Zwei Raten, jede traegt nur ihren eigenen Betrag ────────────────────

def _raten_positionen():
    """Kuenstliche Beispielwerte der Spec: 3 Personen zu 100 und 5 zu 80 EUR
    als halbe Preise, netto 700 EUR je Rate, S mit 19 Prozent."""
    return [
        item_stub(position=1, description="Training, Rate (Teil 1)", unit="Person",
                  quantity=Decimal("3"), unit_price=Decimal("100.00"),
                  tax_rate=Decimal("19"), net_amount=Decimal("300.00"),
                  tax_amount=Decimal("57.00"), gross_amount=Decimal("357.00")),
        item_stub(position=2, description="Training, Rate (Teil 2)", unit="Person",
                  quantity=Decimal("5"), unit_price=Decimal("80.00"),
                  tax_rate=Decimal("19"), net_amount=Decimal("400.00"),
                  tax_amount=Decimal("76.00"), gross_amount=Decimal("476.00")),
    ]


def _rate(invoice_type):
    return zugferd_invoice_stub(
        invoice_type=invoice_type,
        delivery_date=None,
        service_period_start=date(2026, 12, 1),
        service_period_end=date(2026, 12, 31),
        items=_raten_positionen(),
        net_total=Decimal("700.00"),
        tax_total=Decimal("133.00"),
        gross_total=Decimal("833.00"),
    )


class TestV6ZweiRaten:
    def test_beide_raten_tragen_nur_ihren_eigenen_betrag(self):
        xml_386 = zugferd_xml.generate_xml(_rate("prepayment"), company_stub())
        xml_380 = zugferd_xml.generate_xml(_rate(None), company_stub())

        for xml in (xml_386, xml_380):
            assert "<ram:GrandTotalAmount>833.00</ram:GrandTotalAmount>" in xml
            assert "<ram:DuePayableAmount>833.00</ram:DuePayableAmount>" in xml
            assert "TotalPrepaidAmount" not in xml, (
                "BT-113 ist der bereits gezahlte Betrag; diese Forderung ist unbezahlt."
            )
            assert "InvoiceReferencedDocument" not in xml, (
                "Kein automatischer gegenseitiger Rechnungsbezug zwischen den Raten."
            )
        assert "<ram:TypeCode>386</ram:TypeCode>" in xml_386
        assert "<ram:TypeCode>380</ram:TypeCode>" in xml_380


# ── V7: Geplanter Zeitraum statt tatsaechlicher Lieferung ──────────────────

class TestV7ZeitraumStattLieferung:
    def _vorausrechnung(self, **kw):
        basis = dict(
            invoice_type="prepayment",
            delivery_date=None,
            service_period_start=date(2026, 12, 1),
            service_period_end=date(2026, 12, 31),
        )
        basis.update(kw)
        return validator_invoice_stub(**basis)

    def test_386_mit_zukuenftigem_zeitraum_ohne_fehler(self):
        errors, _ = validate_invoice(self._vorausrechnung(), company_stub())
        assert errors == [], [f"{e.code}: {e.message}" for e in errors]

    def test_386_mit_delivery_date_wird_abgelehnt(self):
        inv = self._vorausrechnung(delivery_date=date(2026, 12, 1))
        errors, _ = validate_invoice(inv, company_stub())
        assert any(e.code == "PREPAYMENT_ACTUAL_DELIVERY" for e in errors)

    def test_386_ohne_zeitraum_wird_abgelehnt(self):
        inv = self._vorausrechnung(service_period_start=None, service_period_end=None)
        errors, _ = validate_invoice(inv, company_stub())
        codes = [e.code for e in errors]
        assert "PREPAYMENT_PERIOD_REQUIRED" in codes
        assert "DELIVERY_DATE_MISSING" not in codes, (
            "Bei 386 ist das Leistungsdatum verboten; die fehlende Pflichtangabe "
            "ist der Zeitraum, nicht das Datum."
        )

    def test_386_mit_halbem_zeitraum_wird_abgelehnt(self):
        inv = self._vorausrechnung(service_period_end=None)
        errors, _ = validate_invoice(inv, company_stub())
        assert any(e.code == "SERVICE_PERIOD_INCOMPLETE" for e in errors)

    def test_386_mit_umgekehrtem_zeitraum_wird_abgelehnt(self):
        inv = self._vorausrechnung(
            service_period_start=date(2026, 12, 31),
            service_period_end=date(2026, 12, 1),
        )
        errors, _ = validate_invoice(inv, company_stub())
        assert any(e.code == "SERVICE_PERIOD_INVALID" for e in errors)

    def test_xml_schreibt_bg14_und_kein_actual_delivery(self):
        inv = zugferd_invoice_stub(
            invoice_type="prepayment", delivery_date=None,
            service_period_start=date(2026, 12, 1),
            service_period_end=date(2026, 12, 31),
        )
        xml = zugferd_xml.generate_xml(inv, company_stub())
        assert "BillingSpecifiedPeriod" in xml
        assert "20261201" in xml
        assert "20261231" in xml
        assert "ActualDeliverySupplyChainEvent" not in xml

    def test_pdf_nennt_den_zeitraum_voraussichtlich(self, tmp_path):
        inv = self._vorausrechnung()
        text = _pdf_text(inv, _sample_company(), tmp_path)
        assert "Voraussichtlicher Leistungszeitraum" in text
        assert "Leistungsdatum:" not in text


# ── V8: Bestehende Datumspruefungen bleiben unberuehrt ─────────────────────

class TestV8BestehendeDatumspruefungen:
    def test_380_oberhalb_kleinbetrag_ohne_leistungszeitpunkt_gesperrt(self):
        inv = validator_invoice_stub(
            delivery_date=None,
            service_period_start=None,
            service_period_end=None,
            items=[item_stub(quantity=Decimal("5"), unit_price=Decimal("100.00"),
                             net_amount=Decimal("500.00"), tax_amount=Decimal("95.00"),
                             gross_amount=Decimal("595.00"))],
            net_total=Decimal("500.00"),
            tax_total=Decimal("95.00"),
            gross_total=Decimal("595.00"),
        )
        errors, _ = validate_invoice(inv, company_stub())
        assert any(e.code == "DELIVERY_DATE_MISSING" for e in errors)

    def test_kategorie_k_ohne_datum_unabhaengig_vom_betrag_gesperrt(self):
        inv = validator_invoice_stub(
            delivery_date=None,
            service_period_start=None,
            service_period_end=None,
            tax_category="K",
            gross_total=Decimal("100.00"),
            items=[item_stub(quantity=Decimal("1"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("0"), net_amount=Decimal("100.00"),
                             tax_amount=Decimal("0.00"), gross_amount=Decimal("100.00"))],
            net_total=Decimal("100.00"),
            tax_total=Decimal("0.00"),
            customer=customer_stub(country="AT", vat_id="ATU12345678"),
        )
        errors, _ = validate_invoice(inv, company_stub(vat_id="DE123456789"))
        assert any(e.code == "DELIVERY_DATE_MISSING" for e in errors)

    def test_380_kleinbetrag_ohne_datum_bleibt_frei(self):
        inv = validator_invoice_stub(
            delivery_date=None,
            service_period_start=None,
            service_period_end=None,
        )
        errors, _ = validate_invoice(inv, company_stub())
        assert not any(e.code == "DELIVERY_DATE_MISSING" for e in errors)


# ── V9: Unveraenderlichkeit der Belegart nach Finalisierung ─────────────────

class TestV9Unveraenderlichkeit:
    @pytest.mark.parametrize("status", ["issued", "paid"])
    def test_typaenderung_nach_finalisierung_ist_guardfehler(self, pg_session, status):
        inv = _entwurf(pg_session, _kunde(pg_session), status=status)
        inv.invoice_type = "prepayment"
        with pytest.raises(InvoiceStateError):
            pg_session.commit()
        pg_session.rollback()

    def test_normaler_draft_wechselt_zwischen_den_manuellen_arten(self, pg_session):
        inv = _entwurf(pg_session, _kunde(pg_session))
        inv.invoice_type = "prepayment"
        pg_session.commit()
        inv.invoice_type = None
        pg_session.commit()
        assert inv.invoice_type is None


# ── V10: Mustang-Freigabe mit der gepinnten JAR ─────────────────────────────
# Integrationsannahme, hier gemessen statt angenommen: 386-CII ohne BT-113 und
# ohne BT-72, mit zukuenftigem BG-14, plus das daraus eingebettete
# EN16931-PDF. Ein Fehlschlag ist ein Befund und wird nicht weggeglaettet.

def _v10_rechnung():
    cust = Customer(name="Muster Kunde GmbH", address_line1="Kundenweg 1",
                    zip_code="10115", city="Berlin", country="DE")
    inv = Invoice(
        invoice_number="RE-2026-386",
        issue_date=date(2026, 9, 25),
        due_date=date(2026, 10, 9),
        delivery_date=None,
        service_period_start=date(2026, 12, 1),
        service_period_end=date(2026, 12, 31),
        currency="EUR",
        net_total=Decimal("700.00"),
        tax_total=Decimal("133.00"),
        gross_total=Decimal("833.00"),
        tax_category="S",
        payment_terms="Zahlbar innerhalb von 14 Tagen ohne Abzug.",
        notes="",
        invoice_type="prepayment",
    )
    inv.customer = cust
    inv.items = [
        InvoiceItem(position=1, description="Training, Rate 1 von 2 (3 Personen)",
                    unit="Person", quantity=Decimal("3"),
                    unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
                    net_amount=Decimal("300.00"), tax_amount=Decimal("57.00"),
                    gross_amount=Decimal("357.00")),
        InvoiceItem(position=2, description="Training, Rate 1 von 2 (5 Personen)",
                    unit="Person", quantity=Decimal("5"),
                    unit_price=Decimal("80.00"), tax_rate=Decimal("19"),
                    net_amount=Decimal("400.00"), tax_amount=Decimal("76.00"),
                    gross_amount=Decimal("476.00")),
    ]
    return inv


def _v10_firma():
    return Company(
        id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
        zip_code="12345", city="Musterstadt", email="info@example.de", phone="+49 111",
        vat_id="DE123456789", tax_number="123/456/78901",
        bank_iban="DE33PROBE0000000000001", bank_bic="ABCDDEFF", bank_name="Testbank",
        country="DE",
    )


@pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)
class TestV10MustangFreigabe:
    def test_386_cii_validiert_bt3_ist_exakt_386(self, tmp_path):
        inv = _v10_rechnung()
        xml = zugferd_xml.generate_xml(inv, _v10_firma())

        # BT-3 getrennt vom Validatorgruen zugesichert: 380 waere auch gueltig.
        assert "<ram:TypeCode>386</ram:TypeCode>" in xml
        assert "TotalPrepaidAmount" not in xml
        assert "ActualDeliverySupplyChainEvent" not in xml
        assert "BillingSpecifiedPeriod" in xml

        xml_path = tmp_path / "voraus.xml"
        xml_path.write_text(xml, encoding="utf-8")
        result = mustang.validate(xml_path)
        assert result["is_valid"], (
            f"386-CII ohne BT-113/BT-72 mit zukuenftigem BG-14 validiert NICHT "
            f"(gepinnte JAR, siehe Dockerfile).\nFehler: {result['errors']}\n"
            f"Rohbericht:\n{result['raw']}\nXML:\n{xml}"
        )

    def test_386_eingebettetes_en16931_pdf_validiert(self, tmp_path):
        company, invoice = _v10_firma(), _v10_rechnung()
        visual = tmp_path / "visual.pdf"
        pdf_generator.generate_pdf(invoice, company, visual)

        pdfa_pdf = tmp_path / "pdfa.pdf"
        assert pdfa.to_pdfa3(visual, pdfa_pdf, title=invoice.invoice_number), (
            "Ghostscript PDF/A-3-Konvertierung fehlgeschlagen"
        )

        xml_path = tmp_path / "voraus.xml"
        xml_path.write_text(zugferd_xml.generate_xml(invoice, company), encoding="utf-8")

        combined = tmp_path / "zugferd.pdf"
        assert mustang.combine(pdfa_pdf, xml_path, combined), "Mustang combine fehlgeschlagen"

        result = mustang.validate(combined)
        assert result["is_valid"] and "XML:valid" in result["raw"], (
            f"Eingebettetes 386-PDF validiert NICHT.\nFehler: {result['errors']}\n"
            f"Rohbericht:\n{result['raw']}"
        )


# ── Vorlagenvertrag: Belegart wird nie vererbt (docs/specs/kopieren.md) ────

class TestVorlagenvertrag:
    def test_vorausrechnung_als_vorlage_vererbt_die_art_nicht(self, client, pg_session):
        kunde = _kunde(pg_session)
        vorlage = _entwurf(pg_session, kunde, invoice_type="prepayment", status="issued")

        r = client.get(f"/invoices/neu?vorlage={vorlage.id}")
        assert r.status_code == 200
        assert _gewaehlt(r.text, "invoice_type") == "standard", (
            "Eine Vorausrechnung als Vorlage darf keine Vorausrechnung vererben."
        )

        r = client.post("/invoices/neu", data=_payload(kunde))
        assert r.status_code == 303
        inv_id = uuid.UUID(r.headers["location"].rsplit("/", 1)[-1])
        assert _frisch(pg_session, inv_id).invoice_type is None
