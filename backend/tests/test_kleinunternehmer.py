"""Kleinunternehmer nach § 19 UStG: MwSt.-Kategorie "E" (#152).

Bis heute kannte das Programm vier Kategorien (S, AE, K, O). Wer nach § 19 UStG
abrechnet, hatte damit keinen richtigen Weg:

* "S" mit 0 % wird intern zu "Z" (Nullsatz) — das heißt "steuerpflichtig zum
  Satz null", nicht "steuerbefreit". Falsche Aussage auf dem Beleg.
* "O" (nicht steuerbar) ist fachlich falsch: Kleinunternehmerumsätze SIND
  steuerbar, die Steuer wird nur nicht erhoben (§ 19 Abs. 1 Satz 1 UStG).
* Der nach § 14 Abs. 4 Nr. 8 UStG nötige Hinweis auf die Steuerbefreiung stand
  nirgends.

Die Zielgruppe des Programms sind Selbständige und Kleinstbetriebe; ein großer
Teil davon rechnet nach § 19 ab. Es ist derselbe Fehlertyp wie `BR-CO-26`:
eine vollständige Testsuite, in der jede Rechnung Regelbesteuerung hat, sieht
die Lücke nicht. Deshalb steht hier neben den String-Tests ein echter
Mustang-Lauf.
"""
import os
import tempfile
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import mustang, pdfa, zugferd_xml
from app.services.validator import validate_invoice


def teardown_function():
    app.dependency_overrides.clear()


PARAGRAF_19 = "§ 19"


def _company(**over) -> Company:
    """Ein echter Kleinunternehmer: Steuernummer, KEINE USt-IdNr."""
    kw = dict(
        id=1, name="Anna Beispiel", address_line1="Werkstattweg 4",
        zip_code="12345", city="Musterstadt", country="DE",
        email="anna@example.de", phone="+49 111",
        vat_id=None, tax_number="123/456/78901",
        bank_iban="DE00123456780000000000", bank_bic="ABCDDEFF",
        bank_name="Testbank",
    )
    kw.update(over)
    return Company(**kw)


def _customer(**over) -> Customer:
    kw = dict(
        customer_number="K-1", name="Kunde GmbH", address_line1="Kundenweg 2",
        zip_code="80331", city="München", country="DE",
    )
    kw.update(over)
    return Customer(**kw)


def _invoice(tax_rate=Decimal("0"), **over) -> Invoice:
    netto = Decimal("500.00")
    steuer = (netto * tax_rate / Decimal("100")).quantize(Decimal("0.01"))
    item = InvoiceItem(
        position=1, description="Reparatur", quantity=Decimal("1"),
        unit="Pauschal", unit_price=netto, tax_rate=tax_rate,
        net_amount=netto, tax_amount=steuer, gross_amount=netto + steuer,
    )
    kw = dict(
        invoice_number="RE-2026-001", issue_date=date(2026, 8, 9),
        delivery_date=date(2026, 8, 9), due_date=date(2026, 8, 23), currency="EUR",
        net_total=netto, tax_total=steuer, gross_total=netto + steuer,
        tax_category="E", payment_terms="Zahlbar innerhalb 14 Tagen.", notes="",
    )
    kw.update(over)
    inv = Invoice(**kw)
    inv.customer = _customer()
    inv.items = [item]
    return inv


# ── Die XML sagt "steuerbefreit" und nennt den Grund ────────────────────────

def test_kategorie_e_steht_als_kategorie_in_der_xml():
    xml = zugferd_xml.generate_xml(_invoice(), _company())

    assert "<ram:CategoryCode>E</ram:CategoryCode>" in xml
    assert "<ram:CategoryCode>Z</ram:CategoryCode>" not in xml


def test_der_befreiungsgrund_nennt_paragraf_19():
    """§ 14 Abs. 4 Nr. 8 UStG verlangt den Hinweis auf die Steuerbefreiung.
    Ein leeres oder allgemeines Feld erfüllt das nicht."""
    xml = zugferd_xml.generate_xml(_invoice(), _company())

    assert "<ram:ExemptionReason>" in xml
    grund = xml.split("<ram:ExemptionReason>")[1].split("</ram:ExemptionReason>")[0]
    assert PARAGRAF_19 in grund, grund


def test_kategorie_e_setzt_den_steuersatz_auf_null():
    xml = zugferd_xml.generate_xml(_invoice(), _company())

    assert "<ram:RateApplicablePercent>0.00</ram:RateApplicablePercent>" in xml


# ── Die Prüfung lässt § 19 zu, aber nicht mit ausgewiesener Steuer ──────────

def test_die_pruefung_beanstandet_kategorie_e_nicht():
    fehler, _ = validate_invoice(_invoice(), _company())

    codes = [f.code for f in fehler]
    assert "TAX_CATEGORY_INVALID" not in codes, codes


def test_kategorie_e_mit_ausgewiesener_steuer_ist_ein_fehler():
    """Ein Kleinunternehmer, der Umsatzsteuer ausweist, schuldet sie nach
    § 14c Abs. 2 UStG — auch wenn er sie nicht schulden dürfte. Das darf das
    Programm nicht durchlassen."""
    rechnung = _invoice(tax_rate=Decimal("19"))

    fehler, _ = validate_invoice(rechnung, _company())

    codes = [f.code for f in fehler]
    assert "TAX_CATEGORY_RATE_MISMATCH" in codes, codes


def test_kategorie_e_verlangt_keine_ust_idnr_des_kaeufers():
    """Anders als AE/K ist § 19 ein reiner Inlandsfall — eine USt-IdNr. des
    Kunden zu verlangen wäre eine Hürde ohne Grund."""
    fehler, _ = validate_invoice(_invoice(), _company())

    codes = [f.code for f in fehler]
    assert "BUYER_VAT_ID_REQUIRED" not in codes, codes


# ── Der Hinweis muss auch auf dem sichtbaren Beleg stehen ───────────────────

def test_das_pdf_traegt_den_hinweis_auf_paragraf_19(tmp_path):
    """Die XML hat seit 2025 rechtlich Vorrang, aber gelesen wird das PDF.
    § 14 Abs. 4 Nr. 8 UStG verlangt den Hinweis auf dem Beleg, nicht in einer
    Datei, die der Empfänger nie öffnet."""
    from pypdf import PdfReader
    from app.services import pdf_generator

    ziel = tmp_path / "rechnung.pdf"
    pdf_generator.generate_pdf(_invoice(), _company(), ziel)
    text = "\n".join(seite.extract_text() or "" for seite in PdfReader(str(ziel)).pages)

    assert PARAGRAF_19 in text, text


def test_der_hinweis_im_pdf_ist_derselbe_wie_in_der_xml():
    """Zwei Kopien desselben Rechtstextes driften auseinander, und die Kopie im
    PDF fällt beim Erweitern zuerst hinten runter — genau so fehlte § 19 hier."""
    from app.services import pdf_generator

    assert pdf_generator.TAX_NOTICE is zugferd_xml.EXEMPTION_REASONS


# ── Erreichbar sein heißt: im Auswahlfeld stehen ────────────────────────────

def test_das_rechnungsformular_bietet_paragraf_19_an(pg_session):
    """Eine Kategorie, die es nur im Modell gibt, hilft niemandem: das Formular
    ist der einzige Weg, auf dem ein Nutzer sie je setzen kann."""
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                     address_line1="Weg 1", zip_code="80331", city="München",
                     country="DE")
    pg_session.add(kunde)
    pg_session.commit()
    app.dependency_overrides[get_db] = lambda: pg_session

    html = TestClient(app, follow_redirects=False).get("/invoices/neu").text

    assert 'value="E"' in html, "MwSt.-Kategorie E fehlt im Auswahlfeld"
    assert PARAGRAF_19 in html, "Der Nutzer erkennt die Auswahl nur am Paragrafen"


def test_die_auswahl_sagt_dass_sie_den_status_nicht_herstellt(pg_session):
    """Ein Auswahlfeld im Rechnungsprogramm macht niemanden zum Kleinunternehmer.
    Die Regelung setzt voraus, dass man sie gegenüber dem Finanzamt in Anspruch
    nimmt und die Umsatzgrenzen einhält. Wer das verwechselt und trotzdem ohne
    Steuer abrechnet, schuldet sie am Ende selbst — die Auswahl sieht aber aus
    wie eine Entscheidung, die man hier trifft. Also muss hier stehen, dass sie
    es nicht ist."""
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                     address_line1="Weg 1", zip_code="80331", city="München",
                     country="DE")
    pg_session.add(kunde)
    pg_session.commit()
    app.dependency_overrides[get_db] = lambda: pg_session

    html = TestClient(app, follow_redirects=False).get("/invoices/neu").text

    assert "Finanzamt" in html, (
        "Der Hinweis fehlt, dass die Kleinunternehmerregelung gegenüber dem "
        "Finanzamt in Anspruch genommen sein muss"
    )


# ── Beweis gegen das echte Schema, nicht gegen Substrings ───────────────────

@pytest.mark.skipif(not mustang.jar_available(), reason="Mustang-JAR nicht verfügbar")
def test_kleinunternehmer_rechnung_ist_schema_gueltig():
    xml = zugferd_xml.generate_xml(_invoice(), _company())
    fd, name = tempfile.mkstemp(suffix=".xml")
    p = Path(name)
    try:
        os.write(fd, xml.encode("utf-8"))
        os.close(fd)
        ergebnis = mustang.validate(p)
    finally:
        p.unlink(missing_ok=True)

    assert ergebnis["is_valid"], ergebnis.get("raw", "")


@pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)
def test_kleinunternehmer_finalize_e2e_erzeugt_gueltiges_zugferd_pdf(pg_session):
    """#27: Kategorie E durch die echte Finalize-Pipeline."""
    from app.config import get_settings

    settings = get_settings()
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE")
    pg_session.add(c)
    pg_session.flush()
    number = f"RE-KU-{uuid.uuid4().hex[:6]}"
    inv = Invoice(
        invoice_number=number, customer_id=c.id, issue_date=date(2026, 8, 9),
        delivery_date=date(2026, 8, 9), due_date=date(2026, 8, 23), currency="EUR",
        net_total=Decimal("500.00"), tax_total=Decimal("0.00"),
        gross_total=Decimal("500.00"), tax_category="E", status="draft",
        payment_terms="Zahlbar innerhalb 14 Tagen.",
    )
    inv.items = [InvoiceItem(
        position=1, description="Reparatur", unit="Pauschal", quantity=Decimal("1"),
        unit_price=Decimal("500.00"), tax_rate=Decimal("0"), net_amount=Decimal("500.00"),
        tax_amount=Decimal("0.00"), gross_amount=Decimal("500.00"),
    )]
    pg_session.add(inv)
    pg_session.commit()
    app.dependency_overrides[get_db] = lambda: pg_session
    client = TestClient(app, follow_redirects=False)
    r = client.post(f"/invoices/{inv.id}/finalisieren")
    assert r.status_code == 303
    pg_session.expire_all()
    row = pg_session.get(Invoice, inv.id)
    assert row.status == "issued"
    pdf_path = settings.storage_path / "pdfs" / row.pdf_filename
    try:
        assert pdf_path.exists()
        result = mustang.validate(pdf_path)
        assert result["is_valid"], result.get("raw", "")
        assert "XML:valid" in result["raw"]
    finally:
        pdf_path.unlink(missing_ok=True)
        (settings.storage_path / "xml" / f"{number}.xml").unlink(missing_ok=True)
