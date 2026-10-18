"""Fälligkeit optional, wenn ein Zahlungshinweis gilt (Bauschritt 2b).

EN 16931 BR-CO-25 verlangt bei offenem Betrag BT-9 (Fälligkeitsdatum) ODER
BT-20 (Zahlungsbedingungen). Ein Kunde, der nach eigenem Takt zahlt (z. B.
eine Plattform nach ihrem Auszahlungsbericht), bekommt kein Fälligkeitsdatum,
sondern den Zahlungshinweis in den Zahlungsbedingungen. Jede Fläche, die das
Datum bisher still voraussetzte, muss hier None vertragen.

Die Migration selbst (Nullable + CHECK als zweite Linie) beprobt
test_migrationskette.py; der Datenbank-CHECK wird hier nicht noch einmal
direkt gereizt, weil Formular und Validator die erste Linie sind.
"""
import json
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import text

from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import gobd_export, mailtext, pdf_generator, zugferd_xml
from app.services.dashboard_kennzahlen import ueberfaellige_forderungen
from app.services.rechnungsliste_filter import filtere_rechnungsliste
from app.services.validator import validate_invoice
from app.database import get_db
from tests.factories import (
    company_stub as _firma_stub,
    validator_invoice_stub as _beleg_stub,
)
from tests.helpers.finalize_pipeline import (
    cleanup,
    client,
    finalize_with_fake_pipeline,
)

HINWEIS = "Zahlung nach Auszahlungsbericht der Plattform."


def teardown_function():
    app.dependency_overrides.clear()


# ------------------------------------------------------ Formular (Anlegen/Bearbeiten)

_ITEMS = [{"description": "Plattformumsaetze", "unit": "Stück",
           "quantity": "1", "unit_price": "100", "tax_rate": "19"}]


def _ohne_firmavorgabe(pg_session):
    """Die deutsche Firmavorgabe raeumen wir weg: sonst fiele _zahlungsbedingungen
    auf sie zurueck und der Fehlerfall (weder Datum noch Bedingungen) waere ueber
    das Formular gar nicht erreichbar."""
    pg_session.execute(text("UPDATE company SET payment_terms_default = ''"))
    pg_session.commit()


def _anlegen(client, **over):
    daten = dict({
        "issue_date": "2026-10-05",
        "due_date": "",
        "service_period_start": "2026-09-01",
        "service_period_end": "2026-09-30",
        "tax_category": "S",
        "items_json": json.dumps(_ITEMS),
        "payment_terms": HINWEIS,
    })
    daten.update(over)
    return client.post("/invoices/neu", data=daten)


def test_anlegen_ohne_faelligkeit_speichert_den_hinweis(pg_session):
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Plattform GmbH",
                     address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE")
    pg_session.add(kunde)
    pg_session.commit()

    r = _anlegen(client(pg_session), customer_id=str(kunde.id))

    assert r.status_code == 303
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == kunde.id).one()
    assert inv.due_date is None
    assert inv.payment_terms == HINWEIS


def test_anlegen_ohne_faelligkeit_und_ohne_bedingungen_ist_formularfehler(pg_session):
    _ohne_firmavorgabe(pg_session)

    r = _anlegen(client(pg_session), payment_terms="")

    assert r.status_code == 400
    assert "DUE_DATE_OR_PAYMENT_TERMS_REQUIRED" in r.text
    # Kein Beleg, keine verbrannte Nummer: abgewiesen heisst nicht angelegt.
    assert pg_session.query(Invoice).count() == 0


def test_bearbeiten_leert_die_faelligkeit_mit_hinweis(pg_session):
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Plattform GmbH",
                     address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE")
    pg_session.add(kunde)
    pg_session.commit()
    r = _anlegen(client(pg_session), customer_id=str(kunde.id), due_date="2026-10-19")
    assert r.status_code == 303
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == kunde.id).one()

    r = client(pg_session).post(f"/invoices/{inv.id}/bearbeiten", data={
        "customer_id": str(kunde.id),
        "issue_date": "2026-10-05",
        "due_date": "",
        "service_period_start": "2026-09-01",
        "service_period_end": "2026-09-30",
        "tax_category": "S",
        "items_json": json.dumps(_ITEMS),
        "payment_terms": HINWEIS,
    })

    assert r.status_code == 303
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.id == inv.id).one()
    assert inv.due_date is None
    assert inv.payment_terms == HINWEIS


def test_bearbeiten_ohne_faelligkeit_und_ohne_bedingungen_ist_formularfehler(pg_session):
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Plattform GmbH",
                     address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE")
    pg_session.add(kunde)
    pg_session.commit()
    # Mit Faelligkeit anlegen, damit der Abweis nichts halb Gespeichertes
    # behaupten koennte: der Entwurf muss danach noch das Datum tragen.
    r = _anlegen(client(pg_session), customer_id=str(kunde.id), due_date="2026-10-19")
    assert r.status_code == 303
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.customer_id == kunde.id).one()
    _ohne_firmavorgabe(pg_session)

    r = client(pg_session).post(f"/invoices/{inv.id}/bearbeiten", data={
        "customer_id": str(kunde.id),
        "issue_date": "2026-10-05",
        "due_date": "",
        "service_period_start": "2026-09-01",
        "service_period_end": "2026-09-30",
        "tax_category": "S",
        "items_json": json.dumps(_ITEMS),
        "payment_terms": "",
    })

    assert r.status_code == 400
    assert "DUE_DATE_OR_PAYMENT_TERMS_REQUIRED" in r.text
    pg_session.expire_all()
    inv = pg_session.query(Invoice).filter(Invoice.id == inv.id).one()
    assert inv.due_date == date(2026, 10, 19)  # nichts halb gespeichert
    assert inv.payment_terms == HINWEIS


# ------------------------------------------------------ Ansichten (Liste/Detail/Vorschau)

def _entwurf_ohne_faelligkeit(pg_session, status="draft", due_date=None):
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Plattform GmbH",
                     address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE")
    pg_session.add(kunde)
    pg_session.flush()
    inv = Invoice(
        invoice_number=f"RE-2026-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
        issue_date=date(2026, 10, 5), delivery_date=date(2026, 10, 5),
        due_date=due_date, payment_terms=HINWEIS,
        currency="EUR", zugferd_profile="EN16931", tax_category="S",
        status=status, net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
    )
    inv.items = [InvoiceItem(position=1, description="Plattformumsaetze", unit="Stunde",
                             quantity=Decimal("1"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
                             tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"))]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_liste_zeigt_hinweis_statt_faelligkeit(pg_session):
    inv = _entwurf_ohne_faelligkeit(pg_session)
    r = client(pg_session).get("/invoices/")
    assert r.status_code == 200
    assert "laut Zahlungshinweis" in r.text


def test_detail_zeigt_hinweis_statt_faelligkeit(pg_session):
    inv = _entwurf_ohne_faelligkeit(pg_session)
    r = client(pg_session).get(f"/invoices/{inv.id}")
    assert r.status_code == 200
    assert "laut Zahlungshinweis" in r.text


def test_vorschau_rendert_ohne_faelligkeit(pg_session):
    """Die Vorschau erzeugt die XML gleich mit — hier zeigt sich am ehesten ein
    craschender BT-9-Baustein."""
    inv = _entwurf_ohne_faelligkeit(pg_session)
    r = client(pg_session).get(f"/invoices/{inv.id}/vorschau")
    assert r.status_code == 200
    assert "DueDateDateTime" not in r.text


def test_bearbeiten_formular_ohne_faelligkeit(pg_session):
    inv = _entwurf_ohne_faelligkeit(pg_session)
    r = client(pg_session).get(f"/invoices/{inv.id}/bearbeiten")
    assert r.status_code == 200


# ------------------------------------------------------ PDF

def _firma():
    return _firma_stub(
        name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
        zip_code="12345", city="Musterstadt", country="DE",
        vat_id="DE123456789", tax_number="123/456/78901",
        bank_iban="DE33PROBE0000000000001", bank_bic="ABCDDEFF", bank_name="Testbank",
    )


def _beleg(due_date, payment_terms=HINWEIS):
    inv = Invoice(
        invoice_number="RE-2026-889", issue_date=date(2026, 10, 5),
        delivery_date=date(2026, 10, 5), due_date=due_date,
        payment_terms=payment_terms, document_language="de",
        net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"), tax_category="S",
    )
    inv.customer = Customer(name="Plattform GmbH", address_line1="Kundenweg 1",
                            zip_code="10115", city="Berlin", country="DE")
    inv.items = [InvoiceItem(position=1, description="Plattformumsaetze", unit="Stunde",
                             quantity=Decimal("1"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
                             tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"))]
    return inv


def _pdf_text(path):
    from pypdf import PdfReader
    return "\n".join(seite.extract_text() or "" for seite in PdfReader(str(path)).pages)


def test_pdf_ohne_faelligkeit_zeigt_den_hinweis_genau_einmal(tmp_path):
    """Ohne Fälligkeit entfällt die Kopfzeile; der Zahlungsblock zeigt den Hinweis
    schon, also darf er nicht ein zweites Mal oben stehen."""
    out = tmp_path / "rechnung.pdf"
    pdf_generator.generate_pdf(_beleg(None), _firma(), out)
    flach = _pdf_text(out).replace("\n", " ")
    assert "Fälligkeitsdatum" not in flach
    assert flach.count(HINWEIS) == 1


def test_pdf_mit_faelligkeit_zeigt_noch_das_datum(tmp_path):
    out = tmp_path / "rechnung.pdf"
    pdf_generator.generate_pdf(_beleg(date(2026, 10, 19)), _firma(), out)
    flach = _pdf_text(out).replace("\n", " ")
    assert "Fälligkeitsdatum" in flach
    assert "19.10.2026" in flach


# ------------------------------------------------------ ZUGFeRD-XML (BT-9/BT-20)

def _terms_beschreibung(xml_str):
    import xml.etree.ElementTree as ET
    ns = {"ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100"}
    return ET.fromstring(xml_str).findtext(
        ".//ram:SpecifiedTradePaymentTerms/ram:Description", default=None, namespaces=ns,
    )


def test_xml_ohne_faelligkeit_traegt_nur_die_bedingungen():
    xml = zugferd_xml.generate_xml(
        _beleg(None), _firma(),
    )
    assert "DueDateDateTime" not in xml
    assert _terms_beschreibung(xml) == HINWEIS


def test_xml_mit_faelligkeit_traegt_bt9_weiterhin():
    xml = zugferd_xml.generate_xml(
        _beleg(date(2026, 10, 19)), _firma(),
    )
    assert "DueDateDateTime" in xml
    assert _terms_beschreibung(xml) == HINWEIS


# ------------------------------------------------------ Finalisieren (Ende zu Ende)

def test_finalisieren_ohne_faelligkeit_mit_hinweis(pg_session):
    inv = _entwurf_ohne_faelligkeit(pg_session)
    try:
        r = finalize_with_fake_pipeline(pg_session, inv.id)
        # Die Route veroeffentlicht nur, wenn Mustang is_valid UND XML:valid
        # meldet; der Fake aus finalize_pipeline liefert genau das. Der 303er
        # beweist also, dass der Beleg die Mustang-Pruefung passiert hat.
        assert r.status_code == 303

        pg_session.expire_all()
        row = pg_session.get(Invoice, inv.id)
        assert row.status == "issued"
        # BT-9 entfaellt ganz, BT-20 traegt den Hinweis (kein leeres Element).
        assert "DueDateDateTime" not in (row.zugferd_xml or "")
        assert _terms_beschreibung(row.zugferd_xml) == HINWEIS
    finally:
        cleanup(inv.invoice_number)


# ------------------------------------------------------ Mail und GoBD

def test_mail_platzhalter_faelligkeit_traegt_den_hinweis():
    from app.models.app_config import AppConfig
    inv = _beleg(None)
    config = AppConfig(mail_betreff_de="Rechnung {rechnungsnummer}",
                       mail_text_de="Fällig: {faellig_am}")
    inhalt = mailtext.rechnungsmail(inv, _firma(), config)
    assert f"Fällig: {HINWEIS}" in inhalt.rumpf


def test_gobd_export_laesst_die_faelligkeitszelle_leer(tmp_path):
    inv = _beleg(None)
    inv.id = uuid.uuid4()
    data = gobd_export.build_gobd_export(
        invoices=[inv], customers=[inv.customer], audit_rows=[], uebergaben=[],
        storage_path=tmp_path, date_from=date(2026, 1, 1), date_to=date(2026, 12, 31),
    )
    import io
    import zipfile
    import csv
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        text = zf.read("rechnungen.csv").decode("utf-8-sig")
    zeile = next(csv.DictReader(io.StringIO(text), delimiter=";"))
    assert zeile["faelligkeitsdatum"] == ""


# ------------------------------------------------------ Kennzahlen und Filter

def test_ueberfaellig_zaehlt_beleg_ohne_faelligkeit_nie(pg_session):
    _entwurf_ohne_faelligkeit(pg_session, status="issued")
    ergebnis = ueberfaellige_forderungen(pg_session, date(2026, 12, 31))
    assert ergebnis.anzahl == 0
    assert ergebnis.betrag == Decimal("0")
    assert ergebnis.aeltester_tage is None


def test_listenfilter_ueberfaellig_ohne_faelligkeit_nie(pg_session):
    ohne = _entwurf_ohne_faelligkeit(pg_session, status="issued")
    # Beim Anlegen gesetzt, nicht nachtraeglich: der Guard schuetzt
    # finalisierte Belege vor Aenderungen, auch im Test.
    with_date = _entwurf_ohne_faelligkeit(
        pg_session, status="issued", due_date=date(2026, 1, 1),
    )

    query, _ = filtere_rechnungsliste(
        pg_session.query(Invoice), faellig="ueberfaellig", heute=date(2026, 12, 31),
    )
    treffer = {row.id for row in query.all()}
    assert ohne.id not in treffer
    assert with_date.id in treffer


# ------------------------------------------------------ Validator (erste Linie vor der DB-CHECK)

def test_validator_meldet_weder_datum_noch_bedingungen():
    fehler, _ = validate_invoice(
        _beleg_stub(due_date=None, payment_terms=None), _firma_stub(),
    )
    codes = {f.code for f in fehler}
    assert "DUE_DATE_OR_PAYMENT_TERMS_REQUIRED" in codes


def test_validator_akzeptiert_hinweis_statt_datum():
    fehler, _ = validate_invoice(
        _beleg_stub(due_date=None, payment_terms=HINWEIS), _firma_stub(),
    )
    codes = {f.code for f in fehler}
    assert "DUE_DATE_OR_PAYMENT_TERMS_REQUIRED" not in codes
    assert "DUE_DATE_BEFORE_ISSUE" not in codes
