"""#156: Herleitung bleibt nach Import, Neuladen und Bearbeitung erhalten."""
import json
from decimal import Decimal
import pytest
from app.routers.invoices import _items_as_json
from app.services.abrechnungsauftrag_wirkung import entwuerfe_anlegen
from tests.test_abrechnungsauftrag_wirkung import _kunde, _urteil, _gutschrift, PARTNER_A
from tests.test_belegart import _payload, _frisch


def test_import_bearbeitung_herleitung(client, pg_session, tmp_path):
    kunde = _kunde(pg_session, PARTNER_A)
    g = _gutschrift(PARTNER_A)
    g["positionen"].append(dict(nr=2, bezeichnung="Weitere Beteiligung",
        netto="125.00", herleitung=dict(basis_netto="1000.00", satz="12.50")))
    g["summe"]["netto"] = "299.33"
    inv = entwuerfe_anlegen(pg_session, _urteil([g]), dateiname="auftrag.json")[0]
    pg_session.commit()
    inv = _frisch(pg_session, inv.id)
    items = json.loads(_items_as_json(inv))
    for item in items:
        item.update(description="Bearbeiteter Text", basis_netto="999", satz="99")
    response = client.post(f"/invoices/{inv.id}/bearbeiten", data=_payload(kunde, items=items))
    assert response.status_code == 303, response.text
    inv = _frisch(pg_session, inv.id)
    rows = sorted(inv.items, key=lambda p: p.position)
    assert [(p.basis_netto, p.satz) for p in rows] == [
        (Decimal("697.30"), Decimal("25")), (Decimal("1000"), Decimal("12.5"))]
    from app.services.pdf_generator import generate_pdf
    from app.models.company import Company
    from pypdf import PdfReader
    pdf = tmp_path / "herleitung.pdf"
    generate_pdf(inv, pg_session.query(Company).first(), pdf)
    text = " ".join(p.extract_text() for p in PdfReader(str(pdf)).pages)
    assert "697,30" in text and "1.000,00" in text
    assert "12,5" in text and "Bemessungsgrundlage" in text


@pytest.mark.parametrize("basis,satz,preis,ok", [
    ("697.30", "25", "174.33", True), ("697.30", "25", "174.32", False),
    ("1000", "", "125", False), ("", "", "125", True),
    ("NaN", "25", "125", False),
])
def test_manuelle_rechenprobe(client, pg_session, basis, satz, preis, ok):
    from tests.test_belegart import _kunde as kunde_anlegen
    kunde = kunde_anlegen(pg_session)
    response = client.post("/invoices/neu", data=_payload(kunde,
        invoice_type="honorargutschrift", items=[dict(description="Beteiligung",
        quantity="1", unit="Pauschal", unit_price=preis, tax_rate="7",
        basis_netto=basis, satz=satz)]))
    assert (response.status_code == 303) == ok, response.text


def test_datenbank_verlangt_beide_werte(pg_session):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from tests.test_belegart import _kunde as kunde_anlegen, _entwurf
    inv = _entwurf(pg_session, kunde_anlegen(pg_session), invoice_type="self_billing")
    with pytest.raises(IntegrityError), pg_session.begin_nested():
        pg_session.execute(text(
            "UPDATE invoice_items SET basis_netto = 100, satz = NULL WHERE invoice_id = :id"
        ), {"id": inv.id})


def test_manuelle_herleitung_ueberlebt_formular(client, pg_session):
    from app.models.invoice import Invoice
    from tests.test_belegart import _kunde as kunde_anlegen
    kunde = kunde_anlegen(pg_session)
    response = client.post("/invoices/neu", data=_payload(kunde,
        invoice_type="honorargutschrift", items=[dict(description="Beteiligung",
        quantity="1", unit="Pauschal", unit_price="125", tax_rate="7",
        basis_netto="1000", satz="12.50")]))
    assert response.status_code == 303
    inv = pg_session.query(Invoice).one()
    items = json.loads(_items_as_json(inv))
    items[0]["description"] = "Neue Beschreibung"
    response = client.post(f"/invoices/{inv.id}/bearbeiten", data=_payload(kunde, items=items))
    assert response.status_code == 303
    inv = _frisch(pg_session, inv.id)
    assert (inv.items[0].basis_netto, inv.items[0].satz) == (Decimal("1000"), Decimal("12.5"))
