"""#247: Herleitung-Felder nur bei Honorargutschrift (bzw. mit Bestandswerten).

Naht: gerendertes Rechnungsformular (GET Neuanlage / Bearbeiten). Alpine laeuft
im Browser nicht mit; die Zusicherung greift an den Attributen und der
Vorbelegung, an denen die Sichtbarkeit haengt.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date
from decimal import Decimal

from app.models.invoice import Invoice, InvoiceItem
from app.services.belegart import belegart
from tests.test_belegart import _entwurf, _kunde


def _hg_form_wert() -> str:
    return belegart("self_billing").form_wert


def _herleitung_block(html: str) -> str:
    """HTML-Ausschnitt um das Label der Herleitung inkl. umschliessendem Tag."""
    m = re.search(
        r'(<(?:div|template)[^>]*>)\s*'
        r'<label class="label">Bemessungsgrundlage netto / Beteiligungssatz \(optional\)</label>',
        html,
    )
    assert m, "Herleitung-Label ohne umschliessenden Block"
    return m.group(0)


def _formular_vorgaben(html: str) -> dict:
    marke = 'id="formular-vorgaben">'
    start = html.index(marke) + len(marke)
    ende = html.index("</script>", start)
    return json.loads(html[start:ende])


def _vorhandene_positionen(html: str) -> list[dict]:
    marke = 'id="vorhandene-positionen">'
    start = html.index(marke) + len(marke)
    ende = html.index("</script>", start)
    return json.loads(html[start:ende])


def test_neuanlage_herleitung_an_honorargutschrift_gebunden(client):
    """Fall 1: Sichtbarkeit haengt am Formularwert der Honorargutschrift und am Select."""
    antwort = client.get("/invoices/neu")
    assert antwort.status_code == 200
    html = antwort.text

    block = _herleitung_block(html)
    assert re.search(r'\bx-show="[^"]*zeigtHerleitung[^"]*"', block), (
        "Herleitung-Block ohne x-show=\"…zeigtHerleitung…\""
    )

    select = re.search(r'<select[^>]*name="invoice_type"[^>]*>', html)
    assert select, "Belegart-Auswahl fehlt"
    assert 'x-model="invoiceType"' in select.group(0), (
        "Belegart-Select ohne x-model=\"invoiceType\" — Umschalten wirkt sonst nicht sofort"
    )

    vorgaben = _formular_vorgaben(html)
    assert vorgaben.get("honorargutschriftFormWert") == _hg_form_wert()
    assert vorgaben.get("invoiceType") == "standard"


def test_gespeicherte_389_ohne_auswahlbox_zeigt_herleitung_vorbelegt(client, pg_session):
    """Fall 2: ohne waehlbare Belegart richtet sich die Sichtbarkeit nach dem Bestand."""
    inv = _entwurf(
        pg_session, _kunde(pg_session),
        invoice_type="self_billing", aus_beleg=True,
    )
    html = client.get(f"/invoices/{inv.id}/bearbeiten").text
    assert 'name="invoice_type"' not in html

    vorgaben = _formular_vorgaben(html)
    assert vorgaben["invoiceType"] == _hg_form_wert(), (
        "Vorbelegung muss den Formularwert der gespeicherten 389 tragen, "
        "sonst bleibt die Herleitung hinter x-show versteckt"
    )
    assert vorgaben["honorargutschriftFormWert"] == _hg_form_wert()


def test_standard_mit_herleitungswerten_laesst_felder_pro_position_sichtbar(
    client, pg_session,
):
    """Fall 3: Position mit Bestandswerten bleibt sichtbar, auch ohne Honorargutschrift."""
    kunde = _kunde(pg_session)
    inv = Invoice(
        invoice_number=f"RE-{uuid.uuid4().hex[:8]}",
        customer_id=kunde.id,
        issue_date=date(2026, 6, 11),
        due_date=date(2026, 6, 25),
        status="draft",
        currency="EUR",
        zugferd_profile="EN16931",
        tax_category="S",
        invoice_type=None,
        net_total=Decimal("125.00"),
        tax_total=Decimal("8.75"),
        gross_total=Decimal("133.75"),
    )
    pg_session.add(inv)
    pg_session.flush()
    pg_session.add(InvoiceItem(
        invoice_id=inv.id, position=1, description="Beteiligung Probe",
        unit="Pauschal", quantity=Decimal("1"), unit_price=Decimal("125"),
        tax_rate=Decimal("7"), net_amount=Decimal("125.00"),
        tax_amount=Decimal("8.75"), gross_amount=Decimal("133.75"),
        basis_netto=Decimal("1000.00"), satz=Decimal("12.5"),
    ))
    pg_session.commit()

    html = client.get(f"/invoices/{inv.id}/bearbeiten").text
    vorgaben = _formular_vorgaben(html)
    assert vorgaben["invoiceType"] == "standard"

    positionen = _vorhandene_positionen(html)
    assert positionen[0]["basis_netto"] == "1000.00"
    assert positionen[0]["satz"] == "12.5"

    block = _herleitung_block(html)
    assert 'x-show="zeigtHerleitung(item)"' in block, (
        "Ohne Positions-Ausnahme wuerden Bestandswerte bei Standard still versteckt"
    )
    assert re.search(
        r"zeigtHerleitung\s*\([^)]*\)\s*\{[^}]*hatHerleitung",
        html,
        re.S,
    ), "zeigtHerleitung muss Bestandswerte (hatHerleitung) mitpruefen"
