"""Bestehende Rechnung als Vorlage: Anlegeformular vorbefuellen (docs/specs/kopieren.md).

GET /invoices/neu?vorlage=<uuid> oeffnet denselben Anlageweg vorbefuellt.
Beim GET entsteht kein Datensatz; gespeichert wird weiter ueber POST /invoices/neu.
invoice bleibt None (sonst speichert das Formular auf die Vorlage).
"""
import json
import re
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import AuditLog, Invoice, InvoiceItem


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _kunde(pg_session, *, name="Vorlage Kunde GmbH", is_active=True, deleted_at=None):
    c = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name=name,
        address_line1="Weg 1",
        zip_code="80331",
        city="Muenchen",
        country="DE",
        is_active=is_active,
        deleted_at=deleted_at,
    )
    pg_session.add(c)
    pg_session.flush()
    return c


def _vorlage(pg_session, kunde=None, **over):
    """Gestellte Rechnung mit allen Feldern, die der Feldvertrag vorbelegt."""
    if kunde is None:
        kunde = _kunde(pg_session)
    item = InvoiceItem(
        position=1,
        description="Rate Beratung Q1",
        unit="Stunde",
        quantity=Decimal("2"),
        unit_price=Decimal("150.00"),
        tax_rate=Decimal("19"),
        net_amount=Decimal("300.00"),
        tax_amount=Decimal("57.00"),
        gross_amount=Decimal("357.00"),
    )
    kw = dict(
        invoice_number=f"RE-VOR-{uuid.uuid4().hex[:6]}",
        customer_id=kunde.id,
        issue_date=date(2025, 3, 10),
        due_date=date(2025, 3, 24),
        delivery_date=date(2025, 3, 5),
        service_period_start=date(2025, 1, 1),
        service_period_end=date(2025, 3, 31),
        payment_terms="Zwei Raten laut Auftrag.",
        buyer_reference="LW-VORLAGE",
        buyer_order_reference="PO-RATEN-42",
        notes="Erste Rate von zwei.",
        currency="EUR",
        tax_category="AE",
        status="issued",
        net_total=Decimal("300.00"),
        tax_total=Decimal("57.00"),
        gross_total=Decimal("357.00"),
        pdf_filename="RE-VOR-alt.pdf",
    )
    kw.update(over)
    inv = Invoice(**kw)
    inv.items = [item]
    pg_session.add(inv)
    pg_session.commit()
    pg_session.refresh(inv)
    return inv, kunde


def _zaehler(pg_session):
    return pg_session.query(Company).filter(Company.id == 1).one().invoice_counter


def _zeilen(pg_session):
    return {
        "invoices": pg_session.query(Invoice).count(),
        "invoice_items": pg_session.query(InvoiceItem).count(),
        "audit_logs": pg_session.query(AuditLog).count(),
    }


def _pdf_dateien():
    return sorted(p.name for p in (get_settings().storage_path / "pdfs").glob("*"))


def _feldwert(html: str, name: str) -> str | None:
    """value= eines input/textarea/select-Feldes; bei select die selected-Option."""
    m = re.search(
        rf'<(?:input|textarea)[^>]*name="{re.escape(name)}"[^>]*>',
        html,
    )
    if m:
        tag = m.group(0)
        if tag.startswith("<textarea"):
            # Inhalt zwischen Tags
            m2 = re.search(
                rf'<textarea[^>]*name="{re.escape(name)}"[^>]*>(.*?)</textarea>',
                html,
                re.S,
            )
            return m2.group(1) if m2 else ""
        vm = re.search(r'value="([^"]*)"', tag)
        return vm.group(1) if vm else ""

    m = re.search(
        rf'<select[^>]*name="{re.escape(name)}"[^>]*>(.*?)</select>',
        html,
        re.S,
    )
    if not m:
        return None
    block = m.group(1)
    sel = re.search(r'<option[^>]*value="([^"]*)"[^>]*selected', block)
    if sel:
        return sel.group(1)
    # selected vor value
    sel = re.search(r'<option[^>]*selected[^>]*value="([^"]*)"', block)
    return sel.group(1) if sel else ""


# --- K1 ------------------------------------------------------------------


def test_k1_gestellte_vorlage_oeffnet_neuanlage_vorbefuellt(pg_session):
    """K1: GET mit vorlage liefert Anlegeformular, Aktion neu, Felder vorbelegt, Daten heute."""
    inv, kunde = _vorlage(pg_session)
    heute = date.today()
    faellig = heute + timedelta(days=14)

    r = _client(pg_session).get(f"/invoices/neu?vorlage={inv.id}")
    assert r.status_code == 200
    html = r.text

    assert 'action="/invoices/neu"' in html
    assert f"/invoices/{inv.id}/bearbeiten" not in html
    assert "NEUE RECHNUNG" in html
    assert "RECHNUNG BEARBEITEN" not in html
    assert inv.invoice_number not in html

    assert _feldwert(html, "customer_id") == str(kunde.id)
    assert "Rate Beratung Q1" in html
    assert '"unit": "Stunde"' in html or '"unit":"Stunde"' in html
    assert '"quantity": "2"' in html or '"quantity":"2"' in html
    assert "150.00" in html
    assert '"taxCategory": "AE"' in html or '"taxCategory":"AE"' in html
    assert _feldwert(html, "buyer_order_reference") == "PO-RATEN-42"
    assert _feldwert(html, "buyer_reference") == "LW-VORLAGE"
    assert _feldwert(html, "service_period_start") == "2025-01-01"
    assert _feldwert(html, "service_period_end") == "2025-03-31"
    assert _feldwert(html, "delivery_date") == "2025-03-05"
    assert "Zwei Raten laut Auftrag." in html
    assert "Erste Rate von zwei." in html

    assert _feldwert(html, "issue_date") == heute.isoformat()
    assert _feldwert(html, "due_date") == faellig.isoformat()
    assert _feldwert(html, "issue_date") != inv.issue_date.isoformat()
    assert _feldwert(html, "due_date") != inv.due_date.isoformat()


def test_k1_inaktiver_vorlagenkunde_bleibt_leer_mit_hinweis(pg_session):
    """Vorlagenkunde nicht in der Auswahlliste: Felder trotzdem, Kunde leer, Hinweis."""
    kunde = _kunde(pg_session, name="Inaktiv Vorlage", is_active=False)
    inv, _ = _vorlage(pg_session, kunde=kunde)

    r = _client(pg_session).get(f"/invoices/neu?vorlage={inv.id}")
    assert r.status_code == 200
    html = r.text

    assert _feldwert(html, "customer_id") in ("", None)
    assert f'value="{kunde.id}"' not in html
    assert "Rate Beratung Q1" in html
    assert "PO-RATEN-42" in html
    assert "Vorlagenkunde nicht waehlbar" in html


# --- K2 ------------------------------------------------------------------


def test_k2_speichern_legt_neuen_entwurf_an_vorlage_unveraendert(pg_session):
    """K2: POST /neu nach Vorbelegung: neuer Entwurf, Zaehler +1, Vorlage unangetastet."""
    kunde = _kunde(pg_session)
    original, _ = _vorlage(
        pg_session, kunde=kunde, invoice_number=f"RE-ORIG-{uuid.uuid4().hex[:6]}",
    )
    inv, _ = _vorlage(
        pg_session,
        kunde=kunde,
        invoice_type="credit_note",
        original_invoice_id=original.id,
        uebergabe_beleg_id="beleg-abc",
        uebergabe_beleg_sha256="a" * 64,
    )

    vor_nummer = inv.invoice_number
    vor_status = inv.status
    vor_beschreibung = inv.items[0].description
    vor_type = inv.invoice_type
    vor_orig = inv.original_invoice_id
    vor_ueb_id = inv.uebergabe_beleg_id
    vor_ueb_hash = inv.uebergabe_beleg_sha256
    zaehler_vorher = _zaehler(pg_session)

    client = _client(pg_session)
    get = client.get(f"/invoices/neu?vorlage={inv.id}")
    assert get.status_code == 200
    html = get.text
    assert 'action="/invoices/neu"' in html
    assert _feldwert(html, "buyer_order_reference") == "PO-RATEN-42"
    assert 'name="invoice_type"' not in html

    heute = date.today()
    r = client.post("/invoices/neu", data={
        "customer_id": _feldwert(html, "customer_id"),
        "issue_date": _feldwert(html, "issue_date"),
        "due_date": _feldwert(html, "due_date"),
        "tax_category": "AE",
        "buyer_reference": _feldwert(html, "buyer_reference"),
        "buyer_order_reference": _feldwert(html, "buyer_order_reference"),
        "service_period_start": _feldwert(html, "service_period_start"),
        "service_period_end": _feldwert(html, "service_period_end"),
        "delivery_date": _feldwert(html, "delivery_date"),
        "payment_terms": "Zwei Raten laut Auftrag.",
        "notes": "Zweite Rate.",
        "items_json": json.dumps([{
            "description": "Rate Beratung Q1",
            "unit": "Stunde",
            "quantity": "2",
            "unit_price": "150.00",
            "tax_rate": "19",
        }]),
    })
    assert r.status_code == 303
    neue_id = uuid.UUID(r.headers["location"].rsplit("/", 1)[-1])

    pg_session.expire_all()
    neu = pg_session.get(Invoice, neue_id)
    vorlage = pg_session.get(Invoice, inv.id)

    assert neu is not None
    assert neu.id != inv.id
    assert neu.status == "draft"
    assert neu.invoice_number != vor_nummer
    assert neu.buyer_order_reference == "PO-RATEN-42"
    assert _zaehler(pg_session) == zaehler_vorher + 1

    assert vorlage.invoice_number == vor_nummer
    assert vorlage.status == vor_status
    assert vorlage.items[0].description == vor_beschreibung
    assert vorlage.invoice_type == vor_type
    assert vorlage.original_invoice_id == vor_orig
    assert vorlage.uebergabe_beleg_id == vor_ueb_id
    assert vorlage.uebergabe_beleg_sha256 == vor_ueb_hash

    assert neu.invoice_type is None
    assert neu.original_invoice_id is None
    assert neu.uebergabe_beleg_id is None
    assert neu.uebergabe_beleg_sha256 is None


# --- K3 ------------------------------------------------------------------


def test_k3_get_schreibt_nichts(pg_session):
    """K3: GET mit Vorlagen-UUID aendert Zaehler, Zeilen, updated_at und PDFs nicht."""
    inv, _ = _vorlage(pg_session)
    # Ausgangslage mit Bestand: leere DB wuerde "nichts angelegt" tautologisch machen
    assert pg_session.query(Invoice).count() >= 1
    assert pg_session.query(InvoiceItem).count() >= 1

    # PDF-Datei anlegen, damit "kein neues PDF" ueber eine nicht-leere Menge geht
    pdf_dir = get_settings().storage_path / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    (pdf_dir / inv.pdf_filename).write_bytes(b"%PDF-1.4 vorlage")

    zaehler_vorher = _zaehler(pg_session)
    zeilen_vorher = _zeilen(pg_session)
    pdfs_vorher = _pdf_dateien()
    updated_vorher = inv.updated_at

    r = _client(pg_session).get(f"/invoices/neu?vorlage={inv.id}")
    assert r.status_code == 200
    # Ohne Vorbelegung waere dieser GET derselbe wie leeres /neu und pruefte nichts
    assert _feldwert(r.text, "buyer_order_reference") == "PO-RATEN-42"

    pg_session.expire_all()
    vorlage = pg_session.get(Invoice, inv.id)
    assert _zaehler(pg_session) == zaehler_vorher
    assert _zeilen(pg_session) == zeilen_vorher
    assert vorlage.updated_at == updated_vorher
    assert _pdf_dateien() == pdfs_vorher


# --- K4 ------------------------------------------------------------------


def test_k4_unbekannte_uuid_sichtbarer_fehler_kein_datensatz(pg_session):
    """K4: unbekannte UUID → sichtbarer Fehler, nichts angelegt."""
    # Bestand, damit "kein neuer Datensatz" messbar ist
    _vorlage(pg_session)
    vorher = _zeilen(pg_session)
    unbekannt = uuid.uuid4()

    r = _client(pg_session).get(f"/invoices/neu?vorlage={unbekannt}")
    assert r.status_code in (200, 303, 404)
    if r.status_code == 303:
        r = _client(pg_session).get(r.headers["location"])
    assert r.status_code in (200, 404)
    assert "Vorlage nicht gefunden" in r.text
    pg_session.expire_all()
    assert _zeilen(pg_session) == vorher


def test_k4_ungueltiger_parameter_sichtbarer_fehler_kein_datensatz(pg_session):
    """K4: syntaktisch ungueltiger vorlage-Wert → sichtbarer Fehler, nichts angelegt."""
    _vorlage(pg_session)
    vorher = _zeilen(pg_session)

    r = _client(pg_session).get("/invoices/neu?vorlage=keine-uuid")
    assert r.status_code in (200, 303, 404)
    if r.status_code == 303:
        r = _client(pg_session).get(r.headers["location"])
    assert r.status_code in (200, 404)
    assert "Vorlage ungueltig" in r.text
    pg_session.expire_all()
    assert _zeilen(pg_session) == vorher


# --- K5 ------------------------------------------------------------------


def test_k5_gutschrift_als_vorlage_erbt_keinen_typ(pg_session):
    """K5: Vorlage credit_note → Formular ohne Typ-Kennzeichnung; Entwurf ohne credit_note."""
    inv, kunde = _vorlage(pg_session, invoice_type="credit_note")

    client = _client(pg_session)
    r = client.get(f"/invoices/neu?vorlage={inv.id}")
    assert r.status_code == 200
    html = r.text
    assert _feldwert(html, "buyer_order_reference") == "PO-RATEN-42"
    assert 'name="invoice_type"' not in html
    assert 'value="credit_note"' not in html
    assert "NEUE RECHNUNG" in html

    post = client.post("/invoices/neu", data={
        "customer_id": _feldwert(html, "customer_id"),
        "issue_date": _feldwert(html, "issue_date"),
        "due_date": _feldwert(html, "due_date"),
        "tax_category": "S",
        "buyer_order_reference": _feldwert(html, "buyer_order_reference"),
        "items_json": json.dumps([{
            "description": "X", "unit": "Stück", "quantity": "1",
            "unit_price": "10", "tax_rate": "19",
        }]),
    })
    assert post.status_code == 303
    neue_id = uuid.UUID(post.headers["location"].rsplit("/", 1)[-1])
    pg_session.expire_all()
    neu = pg_session.get(Invoice, neue_id)
    assert neu.status == "draft"
    assert neu.invoice_type is None
    assert neu.buyer_order_reference == "PO-RATEN-42"


# --- K6 ------------------------------------------------------------------


def test_k6_genau_eine_formularvorlage():
    """K6: unter templates/invoices/ genau eine Formular-Datei form.html."""
    ordner = Path(__file__).resolve().parents[1] / "app" / "templates" / "invoices"
    formular_dateien = sorted(
        p.name for p in ordner.iterdir()
        if p.is_file() and p.name.startswith("form")
    )
    assert formular_dateien == ["form.html"], (
        f"Erwartet genau form.html, gefunden: {formular_dateien}"
    )


# --- Einstieg auf der Detailseite ----------------------------------------


def test_detail_hat_einstieg_als_vorlage(pg_session):
    inv, _ = _vorlage(pg_session)
    r = _client(pg_session).get(f"/invoices/{inv.id}")
    assert r.status_code == 200
    assert f"/invoices/neu?vorlage={inv.id}" in r.text


# --- no-store mit Query-Parametern (Messung, Spec Abschnitt Bestand) -----


def test_vorlage_url_hat_no_store_und_zurueck_guard(pg_session):
    """Ob no-store und Zurueck-Erkennung mit Query-Parametern greifen (Nachpruefung)."""
    inv, _ = _vorlage(pg_session)
    r = _client(pg_session).get(f"/invoices/neu?vorlage={inv.id}")
    assert r.status_code == 200
    assert "no-store" in r.headers.get("cache-control", "")
    html = r.text
    for marker in ("pageshow", "persisted", "back_forward",
                   "abgehakt:entwurf-formular-abgeschickt",
                   'id="rechnung-anlegen"', 'id="rechnung-anlegen-verbraucht"'):
        assert marker in html, f"Marker '{marker}' fehlt bei vorbefuellter URL"


# --- Naht zwischen Vorbelegung und Einheitenkatalog ----------------------


def test_ungueltige_einheit_der_vorlage_bleibt_im_formular_sichtbar(pg_session):
    """Ein Altwert ausserhalb des Katalogs muss auch beim Vorbefuellen waehlbar bleiben.

    docs/specs/einheiten.md, Punkt 5: "Ein unbekannter Altwert in einem neuen
    Kopierentwurf bleibt sichtbar und blockiert dessen Finalisierung." Die Option
    dafuer hing bisher an `invoice`, das beim Vorbefuellen per Vertrag None ist.
    Ohne Option verliert Alpine den Wert beim ersten Absenden lautlos.
    """
    inv, _ = _vorlage(pg_session, status="draft", pdf_filename=None)
    inv.items[0].unit = "Flasche"
    pg_session.commit()

    r = _client(pg_session).get(f"/invoices/neu?vorlage={inv.id}")
    assert r.status_code == 200

    block = re.search(r"<select[^>]*x-model=\"item\.unit\"[^>]*>(.*?)</select>", r.text, re.S)
    assert block, "Einheiten-Auswahl nicht gefunden"
    assert 'value="Flasche"' in block.group(1), (
        "Der ungueltige Altwert der Vorlage hat keine Option, der Wert geht beim Absenden verloren"
    )
    assert "Flasche" in json.loads(re.search(
        r'id="vorhandene-positionen">(.*?)</script>', r.text, re.S).group(1))[0]["unit"]
