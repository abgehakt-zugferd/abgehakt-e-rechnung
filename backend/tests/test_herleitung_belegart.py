"""#251: Herleitungswerte an der POST-Naht nach Belegart begrenzen."""
import json
from decimal import Decimal

import pytest

from app.models.invoice import Invoice
from app.routers.invoices.formular_lesen import items_as_json
from app.services.belegart import manuelle_belegarten
from tests.test_belegart import _entwurf, _frisch, _kunde, _payload, _zaehler


ARTEN = manuelle_belegarten()
STANDARD, ANZAHLUNG, HONORAR = ARTEN


def _position(**werte):
    return dict(description="Erfundene Beratung", unit="Stunde", quantity="1",
                unit_price="100", tax_rate="19", **werte)


@pytest.mark.parametrize("art", [STANDARD, ANZAHLUNG])
@pytest.mark.parametrize("bearbeiten", [False, True])
@pytest.mark.parametrize("werte", [dict(basis_netto="1000", satz="10"),
                                   dict(basis_netto="0"), dict(satz="0")])
def test_neue_herleitung_abgelehnt(client, pg_session, art, bearbeiten, werte):
    kunde = _kunde(pg_session)
    inv = _entwurf(pg_session, kunde, invoice_type=art.intern) if bearbeiten else None
    anzahl = pg_session.query(Invoice).count()
    zaehler = _zaehler(pg_session)
    url = f"/invoices/{inv.id}/bearbeiten" if inv else "/invoices/neu"
    response = client.post(url, data=_payload(
        kunde, invoice_type=art.form_wert, items=[_position(**werte)]))
    assert response.status_code == 400, response.text
    assert "Herleitungswerte sind nur bei Honorargutschriften erlaubt" in response.text
    assert pg_session.query(Invoice).count() == anzahl
    assert _zaehler(pg_session) == zaehler
    if inv:
        assert _frisch(pg_session, inv.id).items[0].basis_netto is None


@pytest.mark.parametrize("art", [STANDARD, ANZAHLUNG])
@pytest.mark.parametrize("aktion", ["behalten", "entfernen", "aendern", "anhaengen"])
def test_bestand(client, pg_session, art, aktion):
    kunde = _kunde(pg_session)
    inv = _entwurf(pg_session, kunde, invoice_type=art.intern)
    inv.items[0].basis_netto = Decimal("1000")
    inv.items[0].satz = Decimal("10")
    pg_session.commit()
    items = json.loads(items_as_json(inv))
    items[0]["description"] = "Korrigierte Beschreibung"
    if aktion == "entfernen":
        items[0].update(basis_netto="", satz="")
    elif aktion == "aendern":
        items[0].update(basis_netto="500", satz="20")
    elif aktion == "anhaengen":
        items.append(dict(items[0]))
    response = client.post(f"/invoices/{inv.id}/bearbeiten", data=_payload(kunde, items=items))
    erlaubt = aktion in {"behalten", "entfernen"}
    assert response.status_code == (303 if erlaubt else 400), response.text
    frisch = _frisch(pg_session, inv.id)
    assert len(frisch.items) == 1
    assert frisch.items[0].basis_netto == (None if aktion == "entfernen" else Decimal("1000"))
    assert frisch.items[0].description == ("Korrigierte Beschreibung" if erlaubt else "Beratung")


@pytest.mark.parametrize("art", [STANDARD, ANZAHLUNG])
def test_typwechsel_ist_kein_bestand(client, pg_session, art):
    kunde = _kunde(pg_session)
    inv = _entwurf(pg_session, kunde, invoice_type=HONORAR.intern)
    inv.items[0].basis_netto = Decimal("1000")
    inv.items[0].satz = Decimal("10")
    pg_session.commit()
    response = client.post(f"/invoices/{inv.id}/bearbeiten", data=_payload(
        kunde, invoice_type=art.form_wert, items=json.loads(items_as_json(inv))))
    assert response.status_code == 400, response.text
    assert _frisch(pg_session, inv.id).invoice_type == HONORAR.intern


@pytest.mark.parametrize("status", ["issued", "paid"])
def test_gestellte_belege_bleiben_unveraendert(client, pg_session, status):
    kunde = _kunde(pg_session)
    inv = _entwurf(pg_session, kunde, status=status)
    response = client.post(f"/invoices/{inv.id}/bearbeiten", data=_payload(
        kunde, items=[_position(basis_netto="1000", satz="10")]))
    assert response.status_code == 400
    frisch = _frisch(pg_session, inv.id)
    assert frisch.status == status
    assert frisch.items[0].basis_netto is None
    assert frisch.items[0].satz is None


@pytest.mark.parametrize("werte", [{}, dict(basis_netto=" ", satz="")])
def test_standard_ohne_typfeld_und_ohne_herleitung(client, pg_session, werte):
    response = client.post("/invoices/neu", data=_payload(
        _kunde(pg_session), items=[_position(**werte)]))
    assert response.status_code == 303, response.text
    assert pg_session.query(Invoice).one().items[0].basis_netto is None


def test_wechsel_zur_honorargutschrift_erlaubt_herleitung(client, pg_session):
    kunde = _kunde(pg_session)
    inv = _entwurf(pg_session, kunde)
    response = client.post(f"/invoices/{inv.id}/bearbeiten", data=_payload(
        kunde, invoice_type=HONORAR.form_wert,
        items=[_position(basis_netto="1000", satz="10")]))
    assert response.status_code == 303, response.text
    frisch = _frisch(pg_session, inv.id)
    assert frisch.invoice_type == HONORAR.intern
    assert frisch.items[0].basis_netto == Decimal("1000")
