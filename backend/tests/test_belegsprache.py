"""Belegsprache Deutsch und Englisch (docs/specs/belegsprache.md, S1-S10).

Die Sprache haengt an der Rechnung. Sie steuert nur die maschinell erzeugte
menschliche Darstellung (PDF, Zahlen, Daten, Schablonen). XML bleibt sprachfrei
in ihren Codes und behaelt fuer E/K/O den deutschen Rechtstext; AE bleibt
zweisprachig. Nutzertexte werden nie uebersetzt.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import AuditLog, Invoice, InvoiceItem
from app.services import pdf_generator, zugferd_xml
from app.services.belegsprache import (
    UnknownDocumentLanguageError,
    darstellung,
    resolve_belegsprache,
)
from app.services.invoice_guard import InvoiceStateError
from app.services.storno import build_storno
from app.config import get_settings

AE_HINWEIS = (
    "Steuerschuldnerschaft des Leistungsempfängers / reverse charge, "
    "Art. 196 Council Directive 2006/112/EC"
)
EN_PAYMENT_DEFAULT = "Payable within 14 days of receipt without deduction."


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _kunde(pg_session, **over):
    kw = dict(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Kunde GmbH",
        address_line1="Weg 1",
        zip_code="80331",
        city="Muenchen",
        country="DE",
        vat_id="DE987654321",
    )
    kw.update(over)
    c = Customer(**kw)
    pg_session.add(c)
    pg_session.flush()
    return c


def _englische_vorgabe(pg_session, text=EN_PAYMENT_DEFAULT):
    firma = pg_session.query(Company).filter(Company.id == 1).one()
    firma.payment_terms_default_en = text
    pg_session.commit()
    return firma


def _zaehler(pg_session):
    return pg_session.query(Company).filter(Company.id == 1).one().invoice_counter


def _payload(kunde, *, document_language=..., payment_terms="", **extra):
    daten = {
        "customer_id": str(kunde.id),
        "issue_date": "2026-10-09",
        "due_date": "2026-10-23",
        "delivery_date": "2026-10-09",
        "tax_category": "S",
        "payment_terms": payment_terms,
        "items_json": json.dumps([{
            "description": "Beratung",
            "unit": "Stunde",
            "quantity": "2.5",
            "unit_price": "420",
            "tax_rate": "19",
        }]),
    }
    if document_language is not ...:
        daten["document_language"] = document_language
    daten.update(extra)
    return daten


def _pdf_text(inv, company, tmp_path, name="beleg.pdf"):
    out = tmp_path / name
    pdf_generator.generate_pdf(inv, company, out)
    return "".join(page.extract_text() or "" for page in PdfReader(str(out)).pages)


def _entwurf(pg_session, kunde, *, document_language="de", invoice_type=None,
             tax_category="S", status="draft", **over):
    item = InvoiceItem(
        position=1,
        description="Beratung DE-Text",
        unit="Stunde",
        quantity=Decimal("2.5"),
        unit_price=Decimal("420.00"),
        tax_rate=Decimal("0") if tax_category != "S" else Decimal("19"),
        net_amount=Decimal("1050.00"),
        tax_amount=Decimal("0") if tax_category != "S" else Decimal("199.50"),
        gross_amount=Decimal("1050.00") if tax_category != "S" else Decimal("1249.50"),
    )
    kw = dict(
        invoice_number=f"RE-{uuid.uuid4().hex[:8]}",
        customer_id=kunde.id,
        issue_date=date(2026, 10, 9),
        due_date=date(2026, 10, 23),
        delivery_date=date(2026, 10, 9),
        payment_terms="Zahlbar ohne Abzug." if document_language == "de" else EN_PAYMENT_DEFAULT,
        notes="Freitext bleibt deutsch.",
        currency="EUR",
        zugferd_profile="EN16931",
        tax_category=tax_category,
        invoice_type=invoice_type,
        document_language=document_language,
        status=status,
        net_total=Decimal("1050.00"),
        tax_total=Decimal("0") if tax_category != "S" else Decimal("199.50"),
        gross_total=Decimal("1050.00") if tax_category != "S" else Decimal("1249.50"),
    )
    kw.update(over)
    inv = Invoice(**kw)
    inv.items = [item]
    pg_session.add(inv)
    pg_session.commit()
    pg_session.refresh(inv)
    inv.customer = kunde
    return inv


# ── Resolver / Darstellung (Einheit ohne DB) ───────────────────────────────


def test_resolve_akzeptiert_nur_de_und_en():
    assert resolve_belegsprache("de") == "de"
    assert resolve_belegsprache("en") == "en"
    for wert in (None, "", "fr", "DE", "EN", "deutsch"):
        with pytest.raises(UnknownDocumentLanguageError):
            resolve_belegsprache(wert)


def test_darstellung_formate_sind_zustandslos():
    """S3-Nullprobe auf Modulebene: keine globale Sprache, kein locale."""
    en = darstellung("en")
    de = darstellung("de")
    assert en.format_betrag(Decimal("1050")) == "EUR 1,050.00"
    assert en.format_menge(Decimal("2.5")) == "2.5"
    assert en.format_datum(date(2026, 10, 9)) == "2026-10-09"
    assert de.format_betrag(Decimal("1050")) == "1.050,00 €"
    assert de.format_menge(Decimal("2.5")) == "2,5"
    assert de.format_datum(date(2026, 10, 9)) == "09.10.2026"
    # Nochmal en nach de: Reihenfolge darf nichts aendern.
    assert en.format_betrag(Decimal("1050")) == "EUR 1,050.00"


def test_titel_und_steuerhinweise_sprachmatrix():
    de = darstellung("de")
    en = darstellung("en")
    assert de.titel(None) == "RECHNUNG"
    assert de.titel("prepayment") == "ANZAHLUNGSRECHNUNG"
    assert de.titel("credit_note") == "GUTSCHRIFT"
    assert de.titel("correction") == "KORREKTURRECHNUNG"
    assert en.titel(None) == "INVOICE"
    assert en.titel("prepayment") == "PREPAYMENT INVOICE"
    assert en.titel("credit_note") == "CREDIT NOTE"
    assert en.titel("correction") == "CORRECTIVE INVOICE"
    assert de.steuerhinweis("AE") == AE_HINWEIS
    assert en.steuerhinweis("AE") == AE_HINWEIS
    assert "§ 19 UStG" in de.steuerhinweis("E")
    assert "§ 19" in en.steuerhinweis("E") or "section 19" in en.steuerhinweis("E").lower()
    assert de.steuerhinweis("E") != en.steuerhinweis("E")


# ── S1 ─────────────────────────────────────────────────────────────────────


def test_s1_de_und_en_entwurf_anlegen_ungueltig_vor_zaehler(pg_session):
    kunde = _kunde(pg_session)
    _englische_vorgabe(pg_session)
    client = _client(pg_session)
    vorher = _zaehler(pg_session)

    r_de = client.post("/invoices/neu", data=_payload(kunde))
    assert r_de.status_code == 303
    pg_session.expire_all()
    de_id = r_de.headers["location"].rsplit("/", 1)[-1]
    de_inv = pg_session.get(Invoice, uuid.UUID(de_id))
    assert de_inv.document_language == "de"

    r_en = client.post(
        "/invoices/neu",
        data=_payload(kunde, document_language="en", payment_terms=""),
    )
    assert r_en.status_code == 303
    pg_session.expire_all()
    en_id = r_en.headers["location"].rsplit("/", 1)[-1]
    en_inv = pg_session.get(Invoice, uuid.UUID(en_id))
    assert en_inv.document_language == "en"
    assert en_inv.payment_terms == EN_PAYMENT_DEFAULT

    zaehler_nach_ok = _zaehler(pg_session)
    assert zaehler_nach_ok == vorher + 2

    for schlecht in ("fr", ""):
        r = client.post(
            "/invoices/neu",
            data=_payload(kunde, document_language=schlecht),
        )
        assert r.status_code == 400
        assert _zaehler(pg_session) == zaehler_nach_ok

    # Direkt gesetzter unbekannter Code: harter Fehler vor PDF.
    inv = _entwurf(pg_session, kunde, document_language="de")
    inv.document_language = "xx"
    pg_session.commit()
    company = pg_session.query(Company).filter(Company.id == 1).one()
    with pytest.raises(UnknownDocumentLanguageError):
        pdf_generator.generate_pdf(inv, company, Path("/tmp/should-not-exist.pdf"))


# ── S2 / S3 ────────────────────────────────────────────────────────────────


def test_s2_englisches_pdf_ohne_deutsche_schablone(pg_session, tmp_path):
    kunde = _kunde(pg_session)
    company = _englische_vorgabe(pg_session)
    inv = _entwurf(pg_session, kunde, document_language="en")
    text = _pdf_text(inv, company, tmp_path)
    assert "EUR 1,050.00" in text or "EUR 1,249.50" in text
    assert "2.5" in text
    assert "2026-10-09" in text
    assert "INVOICE" in text
    assert "Invoice number" in text
    assert "Invoice date" in text
    assert "Date of supply" in text
    assert "Due date" in text
    assert "Description" in text
    assert "Quantity" in text
    assert "Unit price" in text
    assert "Net amount" in text
    assert "Invoice total" in text
    assert "plus" in text and "VAT on" in text
    assert "1.050,00 €" not in text
    assert "RECHNUNG" not in text or "INVOICE" in text
    assert "Rechnungsnummer" not in text
    assert "Nettobetrag" not in text
    assert "zzgl." not in text
    assert "MwSt." not in text
    # Nutzertext unveraendert
    assert "Beratung DE-Text" in text
    assert "Freitext bleibt deutsch." in text


def test_s3_reihenfolge_en_dann_de_aendert_nichts(pg_session, tmp_path):
    kunde = _kunde(pg_session)
    company = _englische_vorgabe(pg_session)
    en = _entwurf(pg_session, kunde, document_language="en",
                  invoice_number=f"EN-{uuid.uuid4().hex[:6]}")
    de = _entwurf(pg_session, kunde, document_language="de",
                  invoice_number=f"DE-{uuid.uuid4().hex[:6]}")
    en_text = _pdf_text(en, company, tmp_path, "en.pdf")
    de_text = _pdf_text(de, company, tmp_path, "de.pdf")
    assert "EUR 1,050.00" in en_text or "EUR 1,249.50" in en_text
    assert "2026-10-09" in en_text
    assert "1.050,00 €" in de_text or "1.249,50 €" in de_text
    assert "09.10.2026" in de_text
    # Erneutes Lesen der ersten PDF-Datei: Byte unveraendert.
    en_text_2 = "".join(
        p.extract_text() or "" for p in PdfReader(str(tmp_path / "en.pdf")).pages
    )
    assert en_text_2 == en_text


# ── S4 ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("typ,de_titel,en_titel", [
    (None, "RECHNUNG", "INVOICE"),
    ("prepayment", "ANZAHLUNGSRECHNUNG", "PREPAYMENT INVOICE"),
    ("credit_note", "GUTSCHRIFT", "CREDIT NOTE"),
    ("correction", "KORREKTURRECHNUNG", "CORRECTIVE INVOICE"),
])
def test_s4_acht_titel(pg_session, tmp_path, typ, de_titel, en_titel):
    kunde = _kunde(pg_session)
    company = _englische_vorgabe(pg_session)
    for lang, titel in (("de", de_titel), ("en", en_titel)):
        inv = _entwurf(
            pg_session, kunde, document_language=lang, invoice_type=typ,
            invoice_number=f"{lang}-{typ or 'std'}-{uuid.uuid4().hex[:4]}",
        )
        text = _pdf_text(inv, company, tmp_path, f"{lang}-{typ}.pdf")
        assert titel in text


def test_s4_storno_englischer_rechnung_bleibt_englisch(pg_session, tmp_path):
    kunde = _kunde(pg_session)
    company = _englische_vorgabe(pg_session)
    original = _entwurf(pg_session, kunde, document_language="en", status="issued")
    storno = build_storno(original, "RE-STORNO-EN", date(2026, 10, 15))
    assert storno.document_language == "en"
    assert storno.invoice_type == "credit_note"
    assert storno.items[0].description == original.items[0].description
    assert "Credit note" in storno.payment_terms or "cancellation" in storno.payment_terms.lower()
    assert "2026-10-09" in storno.notes
    assert "Gutschrift/Storno" not in storno.payment_terms
    assert "vom " not in storno.notes
    storno.customer = kunde
    text = _pdf_text(storno, company, tmp_path, "storno-en.pdf")
    assert "CREDIT NOTE" in text


# ── S5 ─────────────────────────────────────────────────────────────────────


def test_s5_ae_zweisprachig_in_pdf_und_xml(pg_session, tmp_path):
    kunde = _kunde(pg_session, country="AT", vat_id="ATU12345678")
    company = _englische_vorgabe(pg_session)
    for lang in ("de", "en"):
        inv = _entwurf(
            pg_session, kunde, document_language=lang, tax_category="AE",
            invoice_number=f"AE-{lang}-{uuid.uuid4().hex[:4]}",
        )
        text = _pdf_text(inv, company, tmp_path, f"ae-{lang}.pdf")
        assert AE_HINWEIS in text
        xml = zugferd_xml.generate_xml(inv, company)
        assert AE_HINWEIS in xml
        assert "VATEX-EU-AE" in xml


# ── S6 ─────────────────────────────────────────────────────────────────────


def test_s6_vorlage_vererbt_sprache_nicht_belegart(pg_session):
    kunde = _kunde(pg_session)
    _englische_vorgabe(pg_session)
    vorlage = _entwurf(
        pg_session, kunde, document_language="en", invoice_type="prepayment",
        status="issued",
        payment_terms="Custom English terms from template.",
        notes="Notiz aus Vorlage",
    )
    client = _client(pg_session)
    vorher_z = _zaehler(pg_session)
    vorher_n = {
        "invoices": pg_session.query(Invoice).count(),
        "items": pg_session.query(InvoiceItem).count(),
        "audit": pg_session.query(AuditLog).count(),
    }
    updated = vorlage.updated_at

    r = client.get(f"/invoices/neu?vorlage={vorlage.id}")
    assert r.status_code == 200
    assert 'name="document_language"' in r.text
    assert re.search(
        r'<option[^>]*value="en"[^>]*selected', r.text
    ) or re.search(r'<option[^>]*selected[^>]*value="en"', r.text)
    assert "Custom English terms from template." in r.text
    assert "Notiz aus Vorlage" in r.text
    assert "Beratung DE-Text" in r.text
    # Belegart startet Standard
    assert re.search(
        r'<option[^>]*value="standard"[^>]*selected', r.text
    ) or re.search(r'<option[^>]*selected[^>]*value="standard"', r.text)

    pg_session.expire_all()
    assert _zaehler(pg_session) == vorher_z
    assert pg_session.query(Invoice).count() == vorher_n["invoices"]
    assert pg_session.query(InvoiceItem).count() == vorher_n["items"]
    assert pg_session.query(AuditLog).count() == vorher_n["audit"]
    assert pg_session.get(Invoice, vorlage.id).updated_at == updated

    post = client.post(
        "/invoices/neu",
        data=_payload(
            kunde,
            document_language="en",
            payment_terms="Custom English terms from template.",
            notes="Notiz aus Vorlage",
        ),
    )
    assert post.status_code == 303
    neu_id = post.headers["location"].rsplit("/", 1)[-1]
    neu = pg_session.get(Invoice, uuid.UUID(neu_id))
    assert neu.document_language == "en"
    assert neu.invoice_type is None
    assert neu.original_invoice_id is None
    assert neu.uebergabe_beleg_id is None


# ── S7 ─────────────────────────────────────────────────────────────────────


def test_s7_englische_leervorgabe_sperrt_nur_englisch(pg_session):
    kunde = _kunde(pg_session)
    firma = pg_session.query(Company).filter(Company.id == 1).one()
    firma.payment_terms_default_en = ""
    pg_session.commit()
    client = _client(pg_session)
    vorher = _zaehler(pg_session)
    anzahl = pg_session.query(Invoice).count()

    ok = client.post("/invoices/neu", data=_payload(kunde, document_language="de"))
    assert ok.status_code == 303

    bad = client.post(
        "/invoices/neu",
        data=_payload(kunde, document_language="en", payment_terms=""),
    )
    assert bad.status_code == 400
    pg_session.expire_all()
    assert _zaehler(pg_session) == vorher + 1
    assert pg_session.query(Invoice).count() == anzahl + 1

    _englische_vorgabe(pg_session)
    # Leeres Feld nimmt englische Vorgabe
    gut = client.post(
        "/invoices/neu",
        data=_payload(kunde, document_language="en", payment_terms=""),
    )
    assert gut.status_code == 303
    neu = pg_session.get(Invoice, uuid.UUID(gut.headers["location"].rsplit("/", 1)[-1]))
    assert neu.payment_terms == EN_PAYMENT_DEFAULT

    # Sprachwechsel ueberschreibt vorhandenen Text nicht (Server: gespeicherter Wert bleibt)
    draft = _entwurf(
        pg_session, kunde, document_language="de",
        payment_terms="Eigener Vertragstext bleibt.",
    )
    r = client.post(
        f"/invoices/{draft.id}/bearbeiten",
        data={
            **_payload(kunde, document_language="en",
                       payment_terms="Eigener Vertragstext bleibt."),
            "issue_date": draft.issue_date.isoformat(),
            "due_date": draft.due_date.isoformat(),
        },
    )
    assert r.status_code in (303, 200)
    pg_session.expire_all()
    draft = pg_session.get(Invoice, draft.id)
    assert draft.document_language == "en"
    assert draft.payment_terms == "Eigener Vertragstext bleibt."


# ── S8 ─────────────────────────────────────────────────────────────────────


def test_s8_finalisiert_sperrt_sprache_archiv_unveraendert(pg_session, tmp_path):
    kunde = _kunde(pg_session)
    _englische_vorgabe(pg_session)
    inv = _entwurf(
        pg_session, kunde, document_language="de", status="issued",
        pdf_filename="archiv-de.pdf",
        zugferd_xml="<r>DE-XML</r>",
    )

    pdf_dir = get_settings().storage_path / "pdfs"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    archiv = pdf_dir / inv.pdf_filename
    archiv.write_bytes(b"%PDF-1.4 archived-german-bytes")
    xml_vorher = inv.zugferd_xml
    bytes_vorher = archiv.read_bytes()

    with pytest.raises(InvoiceStateError):
        inv.document_language = "en"
        pg_session.commit()
    pg_session.rollback()

    draft = _entwurf(
        pg_session, kunde, document_language="de",
        invoice_number=f"DR-{uuid.uuid4().hex[:6]}",
    )
    draft.document_language = "en"
    pg_session.commit()
    assert pg_session.get(Invoice, draft.id).document_language == "en"

    assert archiv.read_bytes() == bytes_vorher
    assert pg_session.get(Invoice, inv.id).zugferd_xml == xml_vorher

    with patch.object(pdf_generator, "generate_pdf") as gen:
        r = _client(pg_session).get(f"/invoices/{inv.id}/pdf")
        assert r.status_code == 200
        assert r.content == bytes_vorher
        gen.assert_not_called()


# ── S9 ─────────────────────────────────────────────────────────────────────


def test_s9_migration_setzt_bestand_auf_de_ohne_dateien():
    """Upgrade 014 -> 015: Bestandsbeleg wird explizit de, Dateien unangetastet."""
    settings = get_settings()
    basis, _, _ = settings.database_url.rpartition("/")
    dbname = "abgehakt_belegsprache_mig"
    admin = create_engine(settings.database_url, isolation_level="AUTOCOMMIT", pool_pre_ping=True)
    with admin.connect() as conn:
        conn.execute(text(f"DROP DATABASE IF EXISTS {dbname} WITH (FORCE)"))
        conn.execute(text(f"CREATE DATABASE {dbname}"))
    url = f"{basis}/{dbname}"
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    vorher_env = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(cfg, "014")
        eng = create_engine(url)
        with eng.begin() as conn:
            conn.execute(text(
                "INSERT INTO company (id, name, address_line1, zip_code, city, country, "
                "invoice_prefix, invoice_year_in_number, invoice_counter, payment_terms_default) "
                "VALUES (1, 'Mig Firma', 'Str 1', '12345', 'Stadt', 'DE', 'RE', true, 1, "
                "'Zahlbar innerhalb von 14 Tagen.') "
                "ON CONFLICT (id) DO NOTHING"
            ))
            # customers + invoice wie nach 014 (ohne document_language)
            conn.execute(text(
                "INSERT INTO customers (id, customer_number, name, address_line1, zip_code, city, country) "
                "VALUES ('11111111-1111-1111-1111-111111111111', 'K-MIG', 'Kunde', 'W 1', '80331', "
                "'Muenchen', 'DE')"
            ))
            conn.execute(text(
                "INSERT INTO invoices (id, invoice_number, customer_id, issue_date, due_date, "
                "currency, status, zugferd_profile, tax_category, net_total, tax_total, gross_total, "
                "pdf_filename, zugferd_xml) "
                "VALUES ('22222222-2222-2222-2222-222222222222', 'RE-MIG-001', "
                "'11111111-1111-1111-1111-111111111111', '2026-01-15', '2026-01-29', "
                "'EUR', 'issued', 'EN16931', 'S', 100, 19, 119, "
                "'RE-MIG-001.pdf', '<xml>bestand</xml>')"
            ))
        eng.dispose()

        # Archivdatei anlegen (Pfad egal fuer Migration; Migration darf sie nicht aendern)
        pdf_dir = get_settings().storage_path / "pdfs"
        pdf_dir.mkdir(parents=True, exist_ok=True)
        archiv = pdf_dir / "RE-MIG-001.pdf"
        archiv.write_bytes(b"%PDF-1.4 migration-bestand")
        bytes_vorher = archiv.read_bytes()

        command.upgrade(cfg, "head")

        eng = create_engine(url)
        with eng.connect() as conn:
            row = conn.execute(text(
                "SELECT document_language, pdf_filename, zugferd_xml FROM invoices "
                "WHERE invoice_number = 'RE-MIG-001'"
            )).one()
            en_default = conn.execute(text(
                "SELECT payment_terms_default_en FROM company WHERE id = 1"
            )).scalar()
        eng.dispose()

        assert row.document_language == "de"
        assert row.pdf_filename == "RE-MIG-001.pdf"
        assert row.zugferd_xml == "<xml>bestand</xml>"
        assert en_default in (None, "")
        assert archiv.read_bytes() == bytes_vorher
    finally:
        if vorher_env is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = vorher_env
        with admin.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {dbname} WITH (FORCE)"))
        admin.dispose()


# ── S10 ────────────────────────────────────────────────────────────────────


def test_s10_xml_identisch_zwischen_de_und_en(pg_session):
    kunde = _kunde(pg_session)
    company = _englische_vorgabe(pg_session)
    de = _entwurf(
        pg_session, kunde, document_language="de", tax_category="AE",
        invoice_number="XML-DE-001",
        notes="Bemerkung bleibt",
        payment_terms="ZB bleibt deutsch",
    )
    en = _entwurf(
        pg_session, kunde, document_language="en", tax_category="AE",
        invoice_number="XML-EN-001",
        notes="Bemerkung bleibt",
        payment_terms="ZB bleibt deutsch",
    )
    # Gleiche fachliche Inhalte ausser Nummer und Sprache
    xml_de = zugferd_xml.generate_xml(de, company)
    xml_en = zugferd_xml.generate_xml(en, company)

    def _codes(xml: str):
        root = ET.fromstring(xml)
        ns = {
            "rsm": "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100",
            "ram": "urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100",
            "udt": "urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100",
        }
        type_code = root.find(".//ram:TypeCode", ns)
        currency = root.find(".//ram:InvoiceCurrencyCode", ns)
        return {
            "type": type_code.text if type_code is not None else None,
            "currency": currency.text if currency is not None else None,
            "vatex": "VATEX-EU-AE" in xml,
            "dates_ymd": sorted(re.findall(r">(\d{8})<", xml)),
            "notes": "Bemerkung bleibt" in xml,
            "payment": "ZB bleibt deutsch" in xml,
            "desc": "Beratung DE-Text" in xml,
            "lang_attr": 'languageID' in xml or "LanguageID" in xml or "document_language" in xml,
        }

    c_de, c_en = _codes(xml_de), _codes(xml_en)
    assert c_de["type"] == c_en["type"] == "380"
    assert c_de["currency"] == c_en["currency"] == "EUR"
    assert c_de["vatex"] and c_en["vatex"]
    assert c_de["dates_ymd"] == c_en["dates_ymd"]
    assert all(len(d) == 8 for d in c_de["dates_ymd"])
    assert c_de["notes"] and c_en["notes"]
    assert c_de["payment"] and c_en["payment"]
    assert c_de["desc"] and c_en["desc"]
    assert not c_de["lang_attr"] and not c_en["lang_attr"]

    # E/K/O: PDF englisch, XML deutsch
    for kat, fragment in (
        ("E", "§ 19 UStG"),
        ("K", "§ 4 Nr. 1b"),
        ("O", "§ 3a Abs. 2"),
    ):
        en_kat = _entwurf(
            pg_session, kunde, document_language="en", tax_category=kat,
            invoice_number=f"XML-{kat}-{uuid.uuid4().hex[:4]}",
        )
        xml = zugferd_xml.generate_xml(en_kat, company)
        assert fragment in xml


def test_schablonentexte_vollstaendig_in_belegdarstellung():
    """Vollstaendige Liste der PDF-Schablonen; Befund, wenn etwas fehlt."""
    en = darstellung("en")
    erwartet = {
        "INVOICE", "PREPAYMENT INVOICE", "CREDIT NOTE", "CORRECTIVE INVOICE",
        "Invoice number", "Invoice date", "Date of supply", "Period of supply",
        "Expected period of supply", "Due date", "Customer number", "Your reference",
        "Purchase order number", "Customer VAT ID", "No.", "Description", "Quantity",
        "Unit", "Unit price", "VAT", "Amount", "Net amount", "Credit note amount",
        "Invoice total", "Reference", "Scan to pay", "VAT ID", "Tax number", "DRAFT",
    }
    felder = {
        getattr(en, name).rstrip(":.")
        for name in dir(en)
        if not name.startswith("_") and isinstance(getattr(en, name), str)
    }
    for intern in (None, "prepayment", "credit_note", "correction"):
        felder.add(en.titel(intern))
    fehlend = {e.rstrip(":.") for e in erwartet} - felder
    assert not fehlend, f"Fehlende Schablonentexte: {fehlend}"
    assert "plus" in en.steuerzeile_muster
    assert "Please transfer the credit note amount" in en.fallback_gutschrift_ueberweisung
    assert en.fallback_gutschrift_ohne == "Credit note without payment request."
    assert en.fallback_zahlbar == "Payable without deduction."
