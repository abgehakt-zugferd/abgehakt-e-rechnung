"""Das Formular darf ein Pflichtfeld nicht „empfohlen" nennen.

Gefunden am 09.08.2026 beim Durchspielen aus Sicht eines Bauunternehmers. Unter
dem Feld „Leistungsdatum" stand `§ 14 Abs. 4 Nr. 6 UStG, empfohlen`. Die Prüfung
in `services/validator.py` macht daraus seit dem Produktentscheid #98 E7 aber
einen **harten Fehler**, sobald die Rechnung 250 € erreicht (§ 33 UStDV,
Kleinbetragsgrenze).

Der Widerspruch trifft fast jeden: eine Handwerkerrechnung liegt über 250 €. Der
Nutzer liest „empfohlen", lässt das Feld leer, klickt auf Finalisieren und
bekommt eine Fehlermeldung für etwas, das ihm die Oberfläche gerade als
freiwillig verkauft hat. Wer dem Formular einmal nicht glaubt, glaubt ihm auch
beim nächsten Hinweis nicht.

Der Test bindet beide Seiten aneinander: solange der Prüfcode `DELIVERY_DATE_
MISSING` als `error` kennt, darf im Formular nicht „empfohlen" stehen.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path

import uuid

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services.validator import validate_invoice

FORMULAR = Path(__file__).resolve().parents[1] / "app" / "templates" / "invoices" / "form.html"


def teardown_function():
    app.dependency_overrides.clear()


def _firma() -> Company:
    return Company(
        id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
        zip_code="12345", city="Musterstadt", country="DE",
        tax_number="12/345/67890", vat_id="DE123456789",
    )


def _rechnung(brutto: Decimal, delivery_date=None) -> Invoice:
    netto = (brutto / Decimal("1.19")).quantize(Decimal("0.01"))
    steuer = brutto - netto
    inv = Invoice(
        invoice_number="RE-2026-001", issue_date=date(2026, 8, 9),
        due_date=date(2026, 8, 23), delivery_date=delivery_date, currency="EUR",
        net_total=netto, tax_total=steuer, gross_total=brutto, tax_category="S",
    )
    inv.customer = Customer(customer_number="K-1", name="Kunde GmbH",
                            address_line1="Weg 1", zip_code="80331",
                            city="München", country="DE")
    inv.items = [InvoiceItem(
        position=1, description="Leistung", quantity=Decimal("1"), unit="Pauschal",
        unit_price=netto, tax_rate=Decimal("19"), net_amount=netto,
        tax_amount=steuer, gross_amount=brutto,
    )]
    return inv


def test_ab_250_euro_ist_das_leistungsdatum_ein_harter_fehler():
    """Der Anlass der Regel. Ändert sich das je, muss der Hinweis unten mitziehen."""
    fehler, _ = validate_invoice(_rechnung(Decimal("500.00")), _firma())

    assert "DELIVERY_DATE_MISSING" in [f.code for f in fehler]


def test_unter_250_euro_bleibt_es_freiwillig():
    fehler, _ = validate_invoice(_rechnung(Decimal("100.00")), _firma())

    assert "DELIVERY_DATE_MISSING" not in [f.code for f in fehler]


def test_genau_250_euro_bleibt_freiwillig():
    """§ 33 UStDV befreit Betraege, die 250 Euro nicht uebersteigen. 250,00 €
    uebersteigt 250 € nicht."""
    fehler, _ = validate_invoice(_rechnung(Decimal("250.00")), _firma())

    assert "DELIVERY_DATE_MISSING" not in [f.code for f in fehler]


def test_das_formular_behauptet_die_pflicht_nicht_schon_bei_250_euro():
    """Beide Seiten aneinandergebunden: „ab 250 €" liest sich als einschliesslich
    und widerspricht der Pruefung genau an der Grenze."""
    text = FORMULAR.read_text(encoding="utf-8")
    block = text.split('name="delivery_date"')[1][:400]

    assert "ab 250" not in block, (
        "Das Formular kuendigt eine Pflicht an, die bei genau 250 € nicht besteht"
    )


def test_das_formular_nennt_das_leistungsdatum_nicht_empfohlen():
    text = FORMULAR.read_text(encoding="utf-8")
    block = text.split('name="delivery_date"')[1][:400]

    assert "empfohlen" not in block, (
        "Das Formular nennt ein Feld freiwillig, das die Prüfung ab 250 € "
        "erzwingt. Der Nutzer lässt es dann leer und scheitert am Finalisieren."
    )


def test_das_formular_nennt_die_grenze_von_250_euro():
    text = FORMULAR.read_text(encoding="utf-8")
    block = text.split('name="delivery_date"')[1][:400]

    assert "250" in block, (
        "Ohne die Grenze bleibt unklar, wann das Feld Pflicht ist"
    )


def test_der_hinweis_steht_auch_dann_da_wenn_das_formular_neu_geladen_wird(pg_session):
    """Gegenprobe über die echte Seite: der Hinweis darf nicht in einem Zweig
    stecken, den das Anlegeformular gar nicht rendert."""
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                     address_line1="Weg 1", zip_code="80331", city="München",
                     country="DE")
    pg_session.add(kunde)
    pg_session.commit()
    app.dependency_overrides[get_db] = lambda: pg_session

    html = TestClient(app, follow_redirects=False).get("/invoices/neu").text

    assert "250" in html.split('name="delivery_date"')[1][:400]


def test_das_formular_nennt_die_pflicht_bei_innergemeinschaftlicher_lieferung():
    """#47: bei Steuertyp K gilt die Kleinbetragsbefreiung nicht.

    Ohne diesen Hinweis liest der Nutzer direkt darüber „Bis 250 € einschließlich
    freiwillig" und lässt das Feld leer, während das Gate ihn danach aufhält. Der
    Widerspruch entsteht auf derselben Seite, ohne dass er dazwischen etwas tut.
    """
    text = FORMULAR.read_text(encoding="utf-8")
    block = text.split('name="delivery_date"')[1][:900]

    assert "innergemeinschaftlich" in block.lower(), (
        "Das Formular verschweigt, dass die Kleinbetragsbefreiung bei ig. "
        "Lieferungen nicht gilt"
    )


def test_die_ig_lieferung_verlangt_das_leistungsdatum_auch_unter_250_euro():
    """Die andere Seite derselben Zusage: solange der Prüfcode das verlangt, muss
    der Hinweis oben stehen bleiben."""
    inv = _rechnung(Decimal("200.00"))
    inv.delivery_date = None
    inv.tax_category = "K"
    inv.customer.vat_id = "ATU12345678"
    inv.net_total = inv.gross_total = Decimal("200.00")
    inv.tax_total = Decimal("0.00")
    for pos in inv.items:
        pos.unit_price = pos.net_amount = pos.gross_amount = Decimal("200.00")
        pos.tax_rate = pos.tax_amount = Decimal("0.00")

    fehler, _ = validate_invoice(inv, _firma())

    assert "DELIVERY_DATE_MISSING" in [f.code for f in fehler]
