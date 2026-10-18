"""Befunde aus dem Review des 389-Umfangs (Honorargutschrift, Storno, Einspielen).

Jeder Test haelt einen belegten Befund fest, nicht eine Vermutung. Die Nummern
vor den Tests entsprechen der Reihenfolge des Review-Protokolls.
"""
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services.zugferd_xml import generate_xml
from tests.factories import company_stub, customer_stub, item_stub, zugferd_invoice_stub
from tests.probe_daten import STEUER_PROBE_ZEHN, UST_DE_PROBE
from tests.test_beleg_aus_xml_einspielen import (
    _kunde as _einspiel_kunde,
    _lege_xml_und_pdf,
)
from scripts.beleg_aus_xml_einspielen import einspielen


def _kunde(pg_session, **over):
    kw = dict(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Probe Empfaenger GmbH",
        address_line1="Weg 1",
        zip_code="10115",
        city="Berlin",
        country="DE",
    )
    kw.update(over)
    kunde = Customer(**kw)
    pg_session.add(kunde)
    pg_session.commit()
    return kunde


def _beleg(pg_session, kunde, *, invoice_type, status="issued", **over):
    inv = Invoice(
        invoice_number=f"RE-REV-{uuid.uuid4().hex[:6]}",
        customer_id=kunde.id,
        issue_date=date(2026, 10, 1),
        due_date=date(2026, 10, 15),
        currency="EUR",
        tax_category="S",
        invoice_type=invoice_type,
        status=status,
        net_total=Decimal("100.00"),
        tax_total=Decimal("19.00"),
        gross_total=Decimal("119.00"),
        payment_terms="Zahlbar in 14 Tagen.",
    )
    inv.items = [InvoiceItem(
        position=1, description="Leistung", unit="Stück",
        quantity=Decimal("1"), unit_price=Decimal("100.00"),
        tax_rate=Decimal("19"), net_amount=Decimal("100.00"),
        tax_amount=Decimal("19.00"), gross_amount=Decimal("119.00"),
    )]
    for feld, wert in over.items():
        setattr(inv, feld, wert)
    pg_session.add(inv)
    pg_session.commit()
    return inv


# ── Befund 1: Titel-Filter wirft bei unbekannter Belegart ──────────────────


def test_liste_und_detail_bleiben_200_bei_unbekannter_belegart(client, pg_session):
    """Die Spalte invoice_type ist unbeschränkt; der Jinja-Filter beleg_bezeichnung
    rief belegart() auf, das fuer einen unbekannten gespeicherten Wert wirft.
    Liste und Detailseite endeten dann in HTTP 500, statt den Bestand zu zeigen."""
    kunde = _kunde(pg_session)
    inv = _beleg(pg_session, kunde, invoice_type="altwert")

    liste = client.get("/invoices/")
    detail = client.get(f"/invoices/{inv.id}")

    assert liste.status_code == 200, (
        "Die Rechnungsliste stuerzt über einen unbekannten gespeicherten Typ ab"
    )
    assert detail.status_code == 200, (
        "Die Detailseite stuerzt über einen unbekannten gespeicherten Typ ab"
    )
    # Der Rohwert bleibt sichtbar, damit der Bestand erkennbar und korrigierbar ist.
    assert "altwert" in liste.text
    assert "altwert" in detail.text


# ── Befund 2: Einspielskript übersieht das Storno einer 389 (261) ───────────


def _xml_261(nummer, kunde):
    """261-XML im eigenen Format: Rollen wie bei 389 getauscht, mit Originalbezug.

    Der Generator baut sie aus derselben Besetzung, die auch das Einspielen
    beantworten muss; die Steuersätze sind die der gutschrifttypischen Probe.
    """
    cust = customer_stub(
        name=kunde.name, address_line1=kunde.address_line1,
        zip_code=kunde.zip_code, city=kunde.city, country=kunde.country,
        vat_id=kunde.vat_id,
    )
    netto = Decimal("100.00")
    steuer = Decimal("7.00")
    inv = zugferd_invoice_stub(
        invoice_number=nummer,
        invoice_type="self_billing_storno",
        original_invoice_id=uuid.uuid4(),
        original_invoice=SimpleNamespace(
            invoice_number="HG-2026-001", issue_date=date(2026, 7, 8),
        ),
        customer=cust,
        issue_date=date(2026, 8, 1),
        due_date=date(2026, 8, 15),
        delivery_date=date(2026, 7, 8),
        tax_category="S",
        items=[item_stub(
            tax_rate=Decimal("7.00"), net_amount=netto,
            tax_amount=steuer, gross_amount=netto + steuer,
            quantity=Decimal("1.0000"), unit_price=netto,
        )],
        net_total=netto, tax_total=steuer, gross_total=netto + steuer,
    )
    return generate_xml(inv, company_stub(
        name="Muster Handwerk GmbH", tax_number=STEUER_PROBE_ZEHN, vat_id=UST_DE_PROBE,
    ))


def test_einspielen_findet_den_kunden_einer_261_im_verkaeuferblock(pg_session):
    """Das Skript suchte den Kunden nur bei invoice_type == "self_billing" im
    Verkaeuferblock; belegrollen tauscht die Rollen auch beim Storno einer 389
    (BT-3 261). Eine 261 fand deshalb keinen Kunde und wurde nie eingespielt."""
    from app.models.invoice import Invoice

    nummer = "ST-EIN-261"
    kunde = _einspiel_kunde(pg_session, ust_status="regelbesteuert")
    _lege_xml_und_pdf(nummer, _xml_261(nummer, kunde))

    einspielen([nummer], db=pg_session)

    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.invoice_number == nummer).one()
    assert row.invoice_type == "self_billing_storno"
    assert row.customer_id == kunde.id, (
        "Der Kunde einer 261 steht im Verkaeuferblock; das Skript hat die "
        "Rollenfrage nicht aus belegrollen bezogen"
    )


# ── Befund 3: Einspielskript übernimmt die Systemnotiz ─────────────────────


def _xml_389(nummer, kunde, notes):
    cust = customer_stub(
        name=kunde.name, address_line1=kunde.address_line1,
        zip_code=kunde.zip_code, city=kunde.city, country=kunde.country,
        vat_id=kunde.vat_id,
    )
    netto = Decimal("100.00")
    steuer = Decimal("7.00")
    inv = zugferd_invoice_stub(
        invoice_number=nummer,
        invoice_type="self_billing",
        customer=cust,
        issue_date=date(2026, 7, 8),
        due_date=date(2026, 7, 22),
        delivery_date=date(2026, 7, 8),
        tax_category="S",
        notes=notes,
        items=[item_stub(
            tax_rate=Decimal("7.00"), net_amount=netto,
            tax_amount=steuer, gross_amount=netto + steuer,
            quantity=Decimal("1.0000"), unit_price=netto,
        )],
        net_total=netto, tax_total=steuer, gross_total=netto + steuer,
    )
    return generate_xml(inv, company_stub(
        name="Muster Handwerk GmbH", tax_number=STEUER_PROBE_ZEHN, vat_id=UST_DE_PROBE,
    ))


def test_einspielen_ueberspringt_die_systemnotiz_einer_389(pg_session):
    """Der Generator schreibt seit #156 vor der Nutzernotiz die Systemnotiz
    ("Gutschrift") in BT-22; das Skript las nur die ERSTE IncludedNote als
    Bemerkung ein. Zurueck in der DB, verdoppelte jede Neuerausgabe sie."""
    from app.models.company import Company
    from app.models.invoice import Invoice

    nummer = "HG-EIN-NOT"
    kunde = _einspiel_kunde(pg_session, ust_status="regelbesteuert")
    _lege_xml_und_pdf(nummer, _xml_389(nummer, kunde, "Abrechnung Q3"))

    einspielen([nummer], db=pg_session)

    pg_session.expire_all()
    row = pg_session.query(Invoice).filter(Invoice.invoice_number == nummer).one()
    assert row.notes == "Abrechnung Q3", (
        "Die Systemnotiz wurde als Nutzernotiz eingespielt statt uebersprungen"
    )
    firma = pg_session.query(Company).filter(Company.id == 1).one()
    neu = generate_xml(row, firma)
    assert neu.count("Gutschrift") == 1, (
        "Die Systemnotiz der Vorlage ist als Nutzernotiz gespeichert und wird "
        "bei der Neuerausgabe verdoppelt"
    )
