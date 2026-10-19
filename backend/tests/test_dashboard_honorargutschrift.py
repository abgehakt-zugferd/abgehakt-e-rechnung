"""Honorargutschrift (389) auf der Uebersicht: Vorsteuer mindert die geschaetzten Abgaben.

Entscheidung des Betreibers vom 2026-09-30 (docs/specs/gutschriftverfahren-389.md):
die Vorsteuer aus Honorargutschriften wird in „Geschaetzte Steuerabgaben“ abgezogen,
nicht in „Schuldige Umsatzsteuer“. Geprueft werden beide Richtungen am selben Beleg.
"""
import uuid
from datetime import date
from app.zeit import heute
from decimal import Decimal

import app.main as main
from app.models.customer import Customer
from app.models.invoice import Invoice
from tests.test_dashboard import _inv, _request


def _honorargutschrift(pg_session, status, gross, net, tax):
    """Der Wächter verbietet, einen gestellten Beleg umzutypisieren; die Art gilt ab Anlage."""
    autor = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Autor",
                     address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(autor)
    pg_session.flush()
    inv = Invoice(invoice_number=f"HG-{uuid.uuid4().hex[:6]}", customer_id=autor.id,
                  issue_date=heute(), due_date=heute(), currency="EUR",
                  net_total=net, tax_total=tax, gross_total=Decimal(gross),
                  status=status, invoice_type="self_billing")
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_vorsteuer_mindert_steuerabgaben_nicht_schuldige_ust(pg_session):
    _inv(pg_session, "issued", "1190.00", net=Decimal("1000.00"), tax=Decimal("190.00"))
    _honorargutschrift(
        pg_session, "issued", "535.00", net=Decimal("500.00"), tax=Decimal("35.00"),
    )

    ctx = main.dashboard(_request(), pg_session).context

    assert Decimal(ctx["vat_liability_ytd"]) == Decimal("190.00")
    assert Decimal(ctx["vorsteuer_honorargutschriften_ytd"]) == Decimal("35.00")
    assert Decimal(ctx["estimated_tax_ytd"]) == (
        Decimal("155.00") + Decimal(ctx["steuer_ruecklage_ytd"])
    )


def test_entwurf_einer_honorargutschrift_mindert_nichts(pg_session):
    _inv(pg_session, "issued", "1190.00", net=Decimal("1000.00"), tax=Decimal("190.00"))
    _honorargutschrift(
        pg_session, "draft", "535.00", net=Decimal("500.00"), tax=Decimal("35.00"),
    )

    ctx = main.dashboard(_request(), pg_session).context

    assert Decimal(ctx["vorsteuer_honorargutschriften_ytd"]) == Decimal("0")
    assert Decimal(ctx["estimated_tax_ytd"]) == (
        Decimal("190.00") + Decimal(ctx["steuer_ruecklage_ytd"])
    )


def test_uebersicht_zeigt_den_abzug(client, pg_session):
    _honorargutschrift(
        pg_session, "issued", "535.00", net=Decimal("500.00"), tax=Decimal("35.00"),
    )
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "− Vorsteuer Honorargutschriften 35" in r.text


def test_beide_richtungen_und_storno(pg_session, client):
    from app.services import dashboard_kennzahlen as k
    from app.services.rechnungsliste_filter import filtere_rechnungsliste
    standard = _inv(pg_session, "issued", "1190", net=Decimal("1000"), tax=Decimal("190"))
    hg = _honorargutschrift(pg_session, "issued", "535", Decimal("500"), Decimal("35"))
    seit = heute().replace(month=1, day=1)
    assert k.offene_forderungen(pg_session).betrag == 1190
    assert k.umsatz_im_zeitraum(pg_session, seit) == 0
    assert k.bezahlt_im_zeitraum(pg_session, seit) == 0
    assert k.schuldige_umsatzsteuer(pg_session, seit) == 190
    assert k.offene_auszahlungen(pg_session).anzahl == 1
    assert k.offene_auszahlungen(pg_session).betrag == 535
    assert k.vorsteuer_honorargutschriften(pg_session, seit) == 35
    assert "Offene Auszahlungen" in client.get("/dashboard").text
    for art, ids in [("honorargutschrift", {hg.id}), ("rechnung", {standard.id}), ("gutschrift", set())]:
        query, _ = filtere_rechnungsliste(pg_session.query(Invoice), art=art)
        assert {i.id for i in query.all()} == ids
    storno = Invoice(invoice_number="ST-PROBE", customer_id=hg.customer_id,
        issue_date=heute(), due_date=heute(), status="draft",
        invoice_type="self_billing_storno", original_invoice_id=hg.id,
        net_total=500, tax_total=35, gross_total=535)
    pg_session.add(storno)
    pg_session.commit()
    assert k.offene_auszahlungen(pg_session).betrag == 535
    storno.status = "issued"
    pg_session.commit()
    assert k.offene_auszahlungen(pg_session).betrag == 0
    assert k.vorsteuer_honorargutschriften(pg_session, seit) == 0
    hg.status = "cancelled"
    pg_session.commit()
    assert k.vorsteuer_honorargutschriften(pg_session, seit) == 0
    assert k.schuldige_umsatzsteuer(pg_session, seit) == 190
    query, _ = filtere_rechnungsliste(pg_session.query(Invoice), art="honorargutschrift")
    assert {i.id for i in query.all()} == {hg.id}


def test_bezahlte_389_ist_keine_einnahme(pg_session):
    from app.services import dashboard_kennzahlen as k
    _inv(pg_session, "paid", "1190", net=Decimal("1000"), tax=Decimal("190"))
    hg = _honorargutschrift(pg_session, "issued", "535", Decimal("500"), Decimal("35"))
    hg.status, hg.bezahlt_am = "paid", heute()
    pg_session.commit()
    seit = heute().replace(month=1, day=1)
    assert k.umsatz_im_zeitraum(pg_session, seit) == 1000
    assert k.bezahlt_im_zeitraum(pg_session, seit) == 1190
    assert k.schuldige_umsatzsteuer(pg_session, seit) == 190
    assert k.offene_forderungen(pg_session).betrag == 0
    assert k.offene_auszahlungen(pg_session).betrag == 0
    assert k.vorsteuer_honorargutschriften(pg_session, seit) == 35
