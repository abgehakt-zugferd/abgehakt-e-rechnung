"""Befunde aus dem Review der drei Features vom 25.09.2026.

Jeder Test haelt einen belegten Befund fest, nicht eine Vermutung.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _firma(pg_session):
    f = pg_session.query(Company).filter(Company.id == 1).first()
    if f is None:
        f = Company(
            id=1, name="Probe GmbH", address_line1="Weg 1", zip_code="80331",
            city="Muenchen", country="DE", vat_id="DE123456789",
            tax_number="123" + "/" + "456" + "/" + "78901",
            bank_iban="DE33PROBE0000000000001", bank_bic="ABCDDEFF",
            bank_name="Probebank", invoice_counter=5,
        )
        pg_session.add(f)
        pg_session.commit()
    return f


def _kunde(pg_session):
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Alt Kunde GmbH",
        address_line1="Weg 2", zip_code="10115", city="Berlin", country="DE",
    )
    pg_session.add(c)
    pg_session.commit()
    return c


def _altbeleg_mit_unbekannter_einheit(pg_session, kunde):
    """Gestellte Rechnung aus der Zeit vor dem Einheitenkatalog.

    `Flasche` war damals kein Fehler: der Generator fiel still auf C62 zurueck.
    Die Position wird vor dem Commit gesetzt, weil der Guard sie danach sperrt.
    """
    inv = Invoice(
        invoice_number="RE-ALT-0001", customer_id=kunde.id,
        issue_date=date(2025, 5, 2), due_date=date(2025, 5, 16),
        delivery_date=date(2025, 5, 2), currency="EUR", tax_category="S",
        status="issued", net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"), payment_terms="Zahlbar in 14 Tagen.",
    )
    inv.items = [InvoiceItem(
        position=1, description="Lieferung", unit="Flasche",
        quantity=Decimal("1"), unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
        net_amount=Decimal("100.00"), tax_amount=Decimal("19.00"),
        gross_amount=Decimal("119.00"),
    )]
    pg_session.add(inv)
    pg_session.commit()
    pg_session.refresh(inv)
    return inv


def test_storno_eines_altbelegs_verbrennt_keine_nummer_und_endet_nicht_in_der_sackgasse(pg_session):
    """Befund 1: Storno eines Altbelegs mit unbekannter Einheit.

    Vorher: die Gutschrift entstand, verbrauchte eine Rechnungsnummer und liess
    sich danach weder finalisieren (UNIT_UNKNOWN) noch bearbeiten (Editor gesperrt).
    Eine Sackgasse mit verbrauchter Nummer ist schlimmer als eine klare Absage.
    """
    firma = _firma(pg_session)
    kunde = _kunde(pg_session)
    alt = _altbeleg_mit_unbekannter_einheit(pg_session, kunde)
    zaehler_vorher = firma.invoice_counter
    anzahl_vorher = pg_session.query(Invoice).count()

    r = _client(pg_session).post(f"/invoices/{alt.id}/storno")

    assert r.status_code == 400, (
        "Der Storno legt einen Entwurf an, der nie finalisierbar ist; "
        f"stattdessen kam {r.status_code}"
    )
    assert "Flasche" in r.text, "Die Meldung nennt den unbekannten Wert nicht"
    assert "1" in r.text, "Die Meldung nennt die Position nicht"

    pg_session.expire_all()
    assert pg_session.query(Company).filter(Company.id == 1).first().invoice_counter == zaehler_vorher, (
        "Die abgewiesene Stornoanfrage hat eine Rechnungsnummer verbraucht"
    )
    assert pg_session.query(Invoice).count() == anzahl_vorher, (
        "Die abgewiesene Stornoanfrage hat einen Beleg angelegt"
    )


def test_pdf_vorschau_meldet_unbekannte_belegart_statt_abzustuerzen(pg_session):
    """Befund 2: `UnknownInvoiceTypeError` war im PDF-Vorschauweg nicht behandelt.

    Die HTML- und XML-Vorschau fangen den Fehler ab, der PDF-Weg nicht: dort
    entstand eine 500. Ein Serverfehler sagt dem Nutzer nicht, was zu tun ist.
    """
    _firma(pg_session)
    kunde = _kunde(pg_session)
    entwurf = Invoice(
        invoice_number="RE-2026-0099", customer_id=kunde.id,
        issue_date=date.today(), due_date=date.today(), currency="EUR",
        tax_category="S", status="draft", invoice_type="unbekannt",
        net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"), payment_terms="Zahlbar in 14 Tagen.",
    )
    entwurf.items = [InvoiceItem(
        position=1, description="Leistung", unit="Stück", quantity=Decimal("1"),
        unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
        net_amount=Decimal("100.00"), tax_amount=Decimal("19.00"),
        gross_amount=Decimal("119.00"),
    )]
    pg_session.add(entwurf)
    pg_session.commit()

    r = _client(pg_session).get(f"/invoices/{entwurf.id}/vorschau.pdf")

    assert r.status_code == 400, (
        f"Die PDF-Vorschau antwortet mit {r.status_code} statt mit einer "
        "verstaendlichen Ablehnung"
    )


@pytest.mark.parametrize("wert", ["", "keine-uuid", str(uuid.uuid4())])
def test_ungueltige_vorlagenkennung_ist_kein_stilles_leeres_formular(pg_session, wert):
    """Befund 5: Die Spec verlangt 404 oder Redirect mit Fehlertext.

    Der leere Parameter lief bisher ganz ohne Hinweis durch, die beiden anderen
    antworteten mit 200. Ein 200 auf eine ungueltige Kennung sagt dem Aufrufer,
    es sei alles in Ordnung.
    """
    _firma(pg_session)
    r = _client(pg_session).get(f"/invoices/neu?vorlage={wert}")

    assert r.status_code == 404, (
        f"Vorlagenkennung {wert!r} ergab {r.status_code} statt 404"
    )
    assert pg_session.query(Invoice).count() == 0


def test_neuanlage_und_vorbefuellen_rendern_dieselbe_vorlage(pg_session):
    """Befund aus dem zweiten Review: K6 prueft Dateinamen statt Verhalten.

    `test_k6_genau_eine_formularvorlage` sucht Dateien, die mit `form` beginnen.
    Ein zweites Template unter einem anderen Namen, etwa `neu_aus_vorlage.html`,
    ueberlebt das gemessen mit 0 roten Tests, obwohl es genau die Dublette ist,
    die K6 verhindern soll. Gemessen wird hier deshalb, welche Vorlage die Route
    tatsaechlich rendert; der Dateiname ist dafuer gleichgueltig.
    """
    from app.routers import invoices as invoices_router

    _firma(pg_session)
    kunde = _kunde(pg_session)
    vorlage = Invoice(
        invoice_number="RE-2026-0077", customer_id=kunde.id,
        issue_date=date.today(), due_date=date.today(), currency="EUR",
        tax_category="S", status="draft", net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"), gross_total=Decimal("119.00"),
        payment_terms="Zahlbar in 14 Tagen.",
    )
    vorlage.items = [InvoiceItem(
        position=1, description="Leistung", unit="Stück", quantity=Decimal("1"),
        unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
        net_amount=Decimal("100.00"), tax_amount=Decimal("19.00"),
        gross_amount=Decimal("119.00"),
    )]
    pg_session.add(vorlage)
    pg_session.commit()
    pg_session.refresh(vorlage)

    gerendert: list[str] = []
    echt = invoices_router.templates.TemplateResponse

    def aufzeichnen(name, *args, **kwargs):
        if isinstance(name, str):
            gerendert.append(name)
        return echt(name, *args, **kwargs)

    invoices_router.templates.TemplateResponse = aufzeichnen
    try:
        client = _client(pg_session)
        assert client.get("/invoices/neu").status_code == 200
        assert client.get(f"/invoices/neu?vorlage={vorlage.id}").status_code == 200
    finally:
        invoices_router.templates.TemplateResponse = echt

    assert gerendert == ["invoices/form.html", "invoices/form.html"], (
        "Neuanlage und Vorbefuellen rendern nicht dieselbe Vorlage: "
        f"{gerendert}"
    )


def test_anzahlung_mit_eintages_zeitraum_ist_gueltig_und_steht_in_der_xml(pg_session):
    """Befund aus dem zweiten Review: keine Fixture mit Ein-Tages-Zeitraum.

    `docs/specs/vorabrechnung.md` sagt ausdruecklich, dass Beginn und Ende fuer
    einen einzelnen Tag gleich gesetzt werden. Der Code laesst das zu
    (`leistungszeitraum_ungueltig` prueft `start > end`), aber alle V7-Fixturen
    tragen einen Mehrtageszeitraum. Damit kippt die Regel unbemerkt, sobald
    jemand die Pruefung auf `>=` verschaerft: sie ist richtig und ungemessen.
    """
    from app.services import zugferd_xml
    from app.services.validator import validate_invoice

    firma = _firma(pg_session)
    kunde = _kunde(pg_session)
    ein_tag = date(2026, 11, 12)
    inv = Invoice(
        invoice_number="RE-2026-0088", customer_id=kunde.id,
        issue_date=date.today(), due_date=date.today(), currency="EUR",
        tax_category="S", status="draft", invoice_type="prepayment",
        service_period_start=ein_tag, service_period_end=ein_tag,
        net_total=Decimal("100.00"), tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"), payment_terms="Zahlbar in 14 Tagen.",
    )
    inv.items = [InvoiceItem(
        position=1, description="Training", unit="Person", quantity=Decimal("1"),
        unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
        net_amount=Decimal("100.00"), tax_amount=Decimal("19.00"),
        gross_amount=Decimal("119.00"),
    )]
    inv.customer = kunde
    pg_session.add(inv)
    pg_session.commit()
    pg_session.refresh(inv)

    fehler, _ = validate_invoice(inv, firma)
    codes = [f.code for f in fehler]
    assert "PREPAYMENT_PERIOD_REQUIRED" not in codes, (
        "Ein Zeitraum von einem einzelnen Tag gilt als fehlend"
    )
    assert "SERVICE_PERIOD_INVALID" not in codes, (
        "Ein Zeitraum von einem einzelnen Tag gilt als umgekehrt"
    )

    xml = zugferd_xml.generate_xml(inv, firma)
    assert "<ram:TypeCode>386</ram:TypeCode>" in xml
    assert xml.count("20261112") >= 2, (
        "BG-14 traegt Beginn und Ende des einzelnen Tages nicht"
    )
    assert "ActualDeliverySupplyChainEvent" not in xml
