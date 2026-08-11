"""Verkäuferkontakt, elektronische Adressen und Käuferreferenz (#153).

Bei der Abnahme am 09.08.2026 meldete Mustang für eine fehlerfreie Rechnung sechs
Hinweise aus dem XRechnung-CIUS. Sie sind keine Fehler: gebunden sind wir an die
EN-16931-Schematron, nicht an den deutschen Behördenstandard. Sie beschreiben aber,
was fehlt, damit eine Rechnung auch maschinell zustellbar ist.

Vier davon werden hier geschlossen, weil sie echte Angaben sind und nicht nur
Formalien:

* `BR-DE-2`  BG-6, Verkäuferkontakt. Wen ruft der Empfänger bei Rückfragen an?
* `PEPPOL-EN16931-R020`  BT-34, elektronische Adresse des Verkäufers.
* `PEPPOL-EN16931-R010`  BT-49, elektronische Adresse des Käufers.
* `BR-DE-15`  BT-10, Käuferreferenz. Im B2B die Bestellnummer des Kunden, gegenüber
  Behörden die Leitweg-ID.

Zwei bleiben bewusst offen, siehe `test_die_beiden_offenen_hinweise_bleiben_offen`.

Wichtig ist die Reihenfolge: die CII-`TradePartyType`-Sequenz ist geordnet
(`ID, GlobalID, Name, RoleCode, Description, SpecifiedLegalOrganization,
DefinedTradeContact, PostalTradeAddress, URIUniversalCommunication,
SpecifiedTaxRegistration`). Ein Element an der falschen Stelle ist ein Schemafehler,
den die String-Tests hier NICHT sehen würden. Deshalb steht am Ende ein echter
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

# ⚠️ `get_db` MUSS hier oben stehen, nicht in der Testfunktion. `test_app_database
# _url_failclosed.py` ruft `importlib.reload(app.database)` und tauscht damit das
# Funktionsobjekt aus. Die Router haben ihres beim Import in `Depends(...)`
# festgehalten; ein Import zur Laufzeit liefert das NEUE, und
# `app.dependency_overrides[get_db]` trifft dann niemanden mehr. Die Anfrage geht
# dann gegen die echte Entwicklungsdatenbank statt gegen `pg_session` — und
# scheitert an fremden Daten, nicht am geprüften Verhalten.
from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import mustang, zugferd_xml, pdf_generator


def _company(**over) -> Company:
    kw = dict(
        id=1, name="Muster Handwerk GmbH", address_line1="Musterstraße 1",
        zip_code="12345", city="Musterstadt", country="DE",
        email="info@example.de", phone="+49 111 222333",
        contact_name="Maria Muster",
        vat_id="DE123456789", tax_number="123/456/78901",
        bank_iban="DE00123456780000000000", bank_bic="ABCDDEFF",
        bank_name="Testbank",
    )
    kw.update(over)
    return Company(**kw)


def _customer(**over) -> Customer:
    kw = dict(
        customer_number="K-1", name="Kunde GmbH", address_line1="Kundenweg 2",
        zip_code="80331", city="München", country="DE",
        email="rechnung@kunde.example",
    )
    kw.update(over)
    return Customer(**kw)


def _invoice(customer=None, **over) -> Invoice:
    item = InvoiceItem(
        position=1, description="Beratungsleistung", quantity=Decimal("2"),
        unit="Std", unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
        net_amount=Decimal("200.00"), tax_amount=Decimal("38.00"),
        gross_amount=Decimal("238.00"),
    )
    kw = dict(
        invoice_number="RE-2026-778", issue_date=date(2026, 8, 9),
        delivery_date=date(2026, 8, 9), due_date=date(2026, 8, 23), currency="EUR",
        net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
        gross_total=Decimal("238.00"), tax_category="S",
        buyer_reference="BST-4711",
        payment_terms="Zahlbar innerhalb 14 Tagen.", notes="",
    )
    kw.update(over)
    inv = Invoice(**kw)
    inv.customer = customer if customer is not None else _customer()
    inv.items = [item]
    return inv


def _xml(**over) -> str:
    return zugferd_xml.generate_xml(_invoice(**over), _company())


# ── BG-6: der Verkäuferkontakt ──────────────────────────────────────────────

def test_der_verkaeuferkontakt_traegt_name_telefon_und_mail():
    xml = _xml()

    kontakt = xml.split("<ram:DefinedTradeContact>")[1].split("</ram:DefinedTradeContact>")[0]
    assert "<ram:PersonName>Maria Muster</ram:PersonName>" in kontakt
    assert "+49 111 222333" in kontakt
    assert "info@example.de" in kontakt


def test_ohne_eigenen_kontaktnamen_steht_die_firma_dort():
    """Ein leeres Pflichtfeld wäre ein Schemafehler. Die Firma ist die ehrlichste
    Antwort auf 'an wen wende ich mich', solange niemand eine Person genannt hat."""
    xml = zugferd_xml.generate_xml(_invoice(), _company(contact_name=None))

    assert "<ram:PersonName>Muster Handwerk GmbH</ram:PersonName>" in xml


def test_der_kontakt_steht_vor_der_anschrift():
    """CII-Sequenz: DefinedTradeContact vor PostalTradeAddress. Andersherum ist es
    ein Schemafehler, den kein String-Test sonst bemerkt."""
    xml = _xml()
    verkaeufer = xml.split("<ram:SellerTradeParty>")[1].split("</ram:SellerTradeParty>")[0]

    assert verkaeufer.index("<ram:DefinedTradeContact>") < verkaeufer.index("<ram:PostalTradeAddress>")


# ── BT-34 / BT-49: elektronische Adressen ───────────────────────────────────

def test_beide_seiten_tragen_ihre_elektronische_adresse():
    xml = _xml()
    verkaeufer = xml.split("<ram:SellerTradeParty>")[1].split("</ram:SellerTradeParty>")[0]
    kaeufer = xml.split("<ram:BuyerTradeParty>")[1].split("</ram:BuyerTradeParty>")[0]

    assert '<ram:URIID schemeID="EM">info@example.de</ram:URIID>' in verkaeufer
    assert '<ram:URIID schemeID="EM">rechnung@kunde.example</ram:URIID>' in kaeufer


def test_ohne_mailadresse_bleibt_das_element_weg():
    """Ein leeres `URIID` ist ein Schemafehler. Die Angabe ist optional, also
    entfällt der ganze Block, statt leer dazustehen."""
    xml = zugferd_xml.generate_xml(_invoice(customer=_customer(email=None)),
                                   _company(email=None))

    assert "URIUniversalCommunication" not in xml


def test_die_elektronische_adresse_steht_nach_der_anschrift():
    xml = _xml()
    verkaeufer = xml.split("<ram:SellerTradeParty>")[1].split("</ram:SellerTradeParty>")[0]

    assert verkaeufer.index("</ram:PostalTradeAddress>") < verkaeufer.index("<ram:URIUniversalCommunication>")
    assert verkaeufer.index("<ram:URIUniversalCommunication>") < verkaeufer.index("<ram:SpecifiedTaxRegistration>")


# ── BT-10: die Käuferreferenz ───────────────────────────────────────────────

def test_die_kaeuferreferenz_steht_in_der_xml():
    xml = _xml()

    assert "<ram:BuyerReference>BST-4711</ram:BuyerReference>" in xml


def test_ohne_kaeuferreferenz_bleibt_das_element_weg():
    xml = zugferd_xml.generate_xml(_invoice(buyer_reference=None), _company())

    assert "BuyerReference" not in xml


def test_die_kaeuferreferenz_steht_vor_dem_verkaeufer():
    """CII-Sequenz in ApplicableHeaderTradeAgreement: BuyerReference zuerst."""
    xml = _xml()
    vereinbarung = xml.split("<ram:ApplicableHeaderTradeAgreement>")[1]

    assert vereinbarung.index("<ram:BuyerReference>") < vereinbarung.index("<ram:SellerTradeParty>")


# ── Die Grenze festhalten ───────────────────────────────────────────────────

def test_die_beiden_offenen_hinweise_bleiben_offen():
    """`BR-DE-21` würde die Kennung auf den XRechnung-CIUS umstellen. Das ist ein
    anderes Profil, kein Zusatz: wer XRechnung braucht, braucht mehr als eine
    Kennung, und wer sie nicht braucht, bekäme eine falsche Zusage in die Datei.
    `BT-23` (Geschäftsprozess) ist ohne PEPPOL-Anbindung eine Konstante ohne
    Empfänger. Dieser Test hält beides fest, damit es beim nächsten Mustang-Lauf
    niemand beiläufig 'aufräumt'."""
    xml = _xml()

    assert "urn:cen.eu:en16931:2017" in xml
    assert "xrechnung" not in xml.lower()
    assert "BusinessProcessSpecifiedDocumentContextParameter" not in xml


# ── Beweis gegen das echte Schema ───────────────────────────────────────────

@pytest.mark.skipif(not mustang.jar_available(), reason="Mustang-JAR nicht verfügbar")
def test_die_erweiterte_rechnung_bleibt_schema_gueltig():
    xml = _xml()
    fd, name = tempfile.mkstemp(suffix=".xml")
    p = Path(name)
    try:
        os.write(fd, xml.encode("utf-8"))
        os.close(fd)
        ergebnis = mustang.validate(p)
    finally:
        p.unlink(missing_ok=True)

    assert ergebnis["is_valid"], ergebnis.get("raw", "")


@pytest.mark.skipif(not mustang.jar_available(), reason="Mustang-JAR nicht verfügbar")
def test_die_vier_hinweise_sind_verschwunden():
    """Der eigentliche Beweis: nicht 'wir haben Felder ergänzt', sondern 'die
    Beanstandung ist weg'."""
    xml = _xml()
    fd, name = tempfile.mkstemp(suffix=".xml")
    p = Path(name)
    try:
        os.write(fd, xml.encode("utf-8"))
        os.close(fd)
        roh = mustang.validate(p).get("raw", "")
    finally:
        p.unlink(missing_ok=True)

    for regel in ("BR-DE-2]", "BR-DE-15]", "PEPPOL-EN16931-R010", "PEPPOL-EN16931-R020"):
        assert regel not in roh, f"{regel} steht weiterhin in der Mustang-Ausgabe"


# ── Die Angaben müssen auch eingebbar sein ──────────────────────────────────

def _seed_kunde(pg_session) -> Customer:
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                     address_line1="Weg 1", zip_code="80331", city="München",
                     country="DE", email="rechnung@kunde.example")
    pg_session.add(kunde)
    pg_session.commit()
    return kunde


def test_die_einstellungen_haben_ein_feld_fuer_den_ansprechpartner(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    try:
        # Der Router hängt unter "/settings/"; ohne Folgen des Schrägstrich-Umzugs
        # käme ein leerer Rumpf zurück und der Test wäre aus dem falschen Grund rot.
        html = TestClient(app).get("/settings/").text
    finally:
        app.dependency_overrides.clear()

    assert 'name="contact_name"' in html, (
        "Ohne Eingabefeld bliebe der Ansprechpartner für immer der Firmenname"
    )


def test_das_rechnungsformular_hat_ein_feld_fuer_die_kaeuferreferenz(pg_session):
    _seed_kunde(pg_session)
    app.dependency_overrides[get_db] = lambda: pg_session
    try:
        html = TestClient(app, follow_redirects=False).get("/invoices/neu").text
    finally:
        app.dependency_overrides.clear()

    assert 'name="buyer_reference"' in html


def test_die_kaeuferreferenz_ueberlebt_das_anlegen_und_das_bearbeiten(pg_session):
    """Ein Feld, das das Formular zeigt, der Router aber nicht liest, ist
    schlimmer als keins: der Nutzer glaubt, die Angabe stünde auf der Rechnung."""
    kunde = _seed_kunde(pg_session)
    app.dependency_overrides[get_db] = lambda: pg_session
    try:
        client = TestClient(app, follow_redirects=False)
        felder = {
            "customer_id": str(kunde.id),
            "issue_date": "2026-08-09",
            "due_date": "2026-08-23",
            "tax_category": "S",
            "buyer_reference": "BST-4711",
            "items_json": '[{"description":"Leistung","quantity":"1","unit":"Stück",'
                          '"unit_price":"100.00","tax_rate":"19"}]',
        }
        antwort = client.post("/invoices/neu", data=felder)
        assert antwort.status_code == 303, antwort.text
        rechnung_id = antwort.headers["location"].rsplit("/", 1)[-1]

        gespeichert = pg_session.query(Invoice).filter(
            Invoice.id == uuid.UUID(rechnung_id)).first()
        pg_session.refresh(gespeichert)
        assert gespeichert.buyer_reference == "BST-4711"

        geaendert = client.post(f"/invoices/{rechnung_id}/bearbeiten",
                                data={**felder, "buyer_reference": "BST-9999"})
        assert geaendert.status_code == 303, geaendert.text
        pg_session.refresh(gespeichert)
        assert gespeichert.buyer_reference == "BST-9999"
    finally:
        app.dependency_overrides.clear()


def test_die_kaeuferreferenz_steht_auf_dem_pdf(tmp_path):
    """Dieselbe Falle wie beim Befreiungsgrund: eine Angabe, die der Nutzer
    eingibt, die in der XML steht und die auf dem gedruckten Beleg fehlt. Der
    Kunde ordnet die Rechnung genau daran seiner Bestellung zu."""
    from pypdf import PdfReader

    ziel = tmp_path / "rechnung.pdf"
    pdf_generator.generate_pdf(_invoice(), _company(), ziel)
    text = "\n".join(seite.extract_text() or "" for seite in PdfReader(str(ziel)).pages)

    assert "BST-4711" in text, text


def test_die_kaeuferreferenz_steht_auf_der_detailseite(pg_session):
    # Die Rechnung MIT dem gespeicherten Kunden bauen: ein nachträgliches
    # `customer = None` würde über die Beziehung auch `customer_id` leeren.
    kunde = _seed_kunde(pg_session)
    rechnung = _invoice(customer=kunde)
    rechnung.invoice_number = f"RE-2026-{uuid.uuid4().hex[:6]}"
    pg_session.add(rechnung)
    pg_session.commit()

    app.dependency_overrides[get_db] = lambda: pg_session
    try:
        html = TestClient(app).get(f"/invoices/{rechnung.id}").text
    finally:
        app.dependency_overrides.clear()

    assert "BST-4711" in html
