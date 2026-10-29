"""Zahlungsvorgabe an der öffentlichen Entwurfs-, Router- und Beleggrenze."""
from datetime import date
from xml.etree import ElementTree as ET

import pytest
from pypdf import PdfReader
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models.company import Company
from app.models.invoice import Invoice
from app.services import mustang, pdf_generator, zugferd_xml
from app.services.auftragszahlung import hinweis_fehlt, ist_rechnungsauftrag
from app.services.rechnungsauftrag_wirkung import entwurf_anlegen
from tests.factories import orm_company
from tests.probe_daten import IBAN_FIRMA_PROBE
from tests.test_rechnungsauftrag_wirkung import _kunde, _urteil
from tests.helpers import mustang_befund

HINWEIS = "Die Zahlung erfolgt durch Auszahlung des Leistungsempfängers."
RAM = "{urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100}"


def _entwurf(db, hinweis=HINWEIS):
    firma = db.get(Company, 1)
    if firma is None:
        firma = orm_company()
        db.add(firma)
    firma.bank_iban = IBAN_FIRMA_PROBE
    firma.bank_bic = "ABCDDEFF"
    kunde = _kunde(db, zahlungshinweis=hinweis)
    inv = entwurf_anlegen(db, _urteil(), company=firma)
    db.commit()
    return inv, kunde, firma


@pytest.mark.parametrize("hinweis", [None, "   "])
def test_fehlender_hinweis_erzeugt_entwurf_ohne_faelligkeit(pg_session, hinweis):
    inv, _, _ = _entwurf(pg_session, hinweis)
    assert inv.status == "draft"
    assert inv.due_date is None
    assert not inv.payment_terms
    # rechnungsauftrag_wirkung setzt invoice_type=None (Standard 380); der
    # CHECK und ist_rechnungsauftrag müssen dieselbe Grenze nutzen.
    assert inv.invoice_type is None
    assert ist_rechnungsauftrag(inv)
    assert hinweis_fehlt(inv)


def test_hinweisregel_gilt_nicht_fuer_formular_alias_standard(pg_session):
    """Das Formular speichert Standardrechnungen als NULL, nicht als
    'standard'. Ein Alias am Beleg ist kein offener Rechnungsauftrag."""
    inv, _, _ = _entwurf(pg_session, None)
    inv.invoice_type = "standard"
    assert not ist_rechnungsauftrag(inv)
    assert not hinweis_fehlt(inv)


def test_check_erlaubt_auftrag_ohne_hinweis_weist_manuell_ab(pg_session):
    inv, _, _ = _entwurf(pg_session, None)
    assert inv.invoice_type is None
    # Bereits gespeichert: Auftrag mit NULL-Typ ohne Termin und Hinweis.
    pg_session.execute(
        text("UPDATE invoices SET payment_terms = NULL WHERE id = :id"),
        {"id": inv.id},
    )
    pg_session.flush()
    # Formular-Alias 'standard' gehört nicht zur Ausnahme (wie Migration 032).
    with pytest.raises(IntegrityError), pg_session.begin_nested():
        pg_session.execute(
            text("UPDATE invoices SET invoice_type = 'standard' WHERE id = :id"),
            {"id": inv.id},
        )
    # Manueller Entwurf: ohne Auftragskennung greift der alte CHECK.
    with pytest.raises(IntegrityError), pg_session.begin_nested():
        pg_session.execute(text(
            "INSERT INTO invoices (invoice_number, issue_date, status) "
            "VALUES ('RE-MAN-206', '2026-10-05', 'draft')"
        ))


def test_warnung_und_finalisierungssperre(client, pg_session):
    inv, kunde, _ = _entwurf(pg_session, None)
    html = client.get(f"/invoices/{inv.id}").text
    assert "Zahlungshinweis fehlt" in html
    assert f'href="/customers/{kunde.id}/bearbeiten"' in html
    antwort = client.post(f"/invoices/{inv.id}/finalisieren")
    assert antwort.status_code == 400
    assert "Zahlungshinweis fehlt" in antwort.text
    assert f"/customers/{kunde.id}/bearbeiten" in antwort.text
    pg_session.refresh(inv)
    assert inv.status == "draft"
    assert inv.pdf_filename is None
    assert inv.zugferd_xml is None


def test_kundenvorgabe_explizit_uebernehmen(client, pg_session):
    inv, kunde, _ = _entwurf(pg_session, None)
    kunde.zahlungshinweis = HINWEIS
    pg_session.commit()
    antwort = client.post(f"/invoices/{inv.id}/zahlungshinweis-uebernehmen")
    assert antwort.status_code == 303
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).payment_terms == HINWEIS
    assert "Zahlungshinweis fehlt" not in client.get(f"/invoices/{inv.id}").text


@pytest.mark.parametrize("mit_termin", [False, True])
def test_pdf_zahlungsangaben_und_xml(pg_session, tmp_path, mit_termin):
    inv, _, firma = _entwurf(pg_session)
    if mit_termin:
        inv.auftragsschluessel = None
        inv.auftragsschluessel_offen = None
        inv.uebergabe_beleg_id = None
        inv.uebergabe_beleg_sha256 = None
        inv.due_date = date(2026, 10, 19)
        pg_session.commit()
    pdf = tmp_path / "rechnung.pdf"
    pdf_generator.generate_pdf(inv, firma, pdf)
    reader = PdfReader(pdf)
    text = "\n".join(page.extract_text() for page in reader.pages)
    assert HINWEIS in text.replace("\n", " ")
    # Textmarker statt Bildzahl: ein Firmenlogo im Storage wäre sonst ein
    # falsches Positiv für den QR-Block.
    for angabe in ("IBAN:", "Verwendungszweck", "Zum Überweisen scannen", "19.10.2026"):
        assert (angabe in text) is mit_termin, angabe
    xml = zugferd_xml.generate_xml(inv, firma)
    root = ET.fromstring(xml)
    assert root.find(f".//{RAM}SpecifiedTradePaymentTerms/{RAM}Description").text == HINWEIS
    assert (root.find(f".//{RAM}DueDateDateTime") is not None) is mit_termin
    assert root.find(f".//{RAM}IBANID").text == IBAN_FIRMA_PROBE
    pfad = tmp_path / "rechnung.xml"
    pfad.write_text(xml)
    ergebnis = mustang.validate(pfad)
    mustang_befund.gueltig(ergebnis, ergebnis)


@pytest.mark.parametrize("hinweis", [None, "   "])
def test_server_sperrt_auch_mit_faelligkeit(client, pg_session, hinweis):
    inv, kunde, _ = _entwurf(pg_session, HINWEIS)
    inv.payment_terms = hinweis
    inv.due_date = date(2026, 10, 19)
    pg_session.commit()
    antwort = client.post(f"/invoices/{inv.id}/finalisieren")
    assert antwort.status_code == 400
    assert "Zahlungshinweis fehlt" in antwort.text
    assert f"/customers/{kunde.id}/bearbeiten" in antwort.text
    pg_session.refresh(inv)
    assert inv.status == "draft"


def test_bearbeiten_erfindet_keine_firmenbedingung(client, pg_session):
    from tests.test_rechnungsauftrag_wirkung import _formular
    inv, _, _ = _entwurf(pg_session, None)
    antwort = client.post(f"/invoices/{inv.id}/bearbeiten", data=_formular(inv, payment_terms=""))
    assert antwort.status_code == 303, antwort.text
    pg_session.refresh(inv)
    assert not inv.payment_terms
    assert inv.due_date is None


def test_uebernahme_ersetzt_keinen_bestehenden_hinweis(client, pg_session):
    inv, kunde, _ = _entwurf(pg_session)
    kunde.zahlungshinweis = "Neue Kundenvorgabe."
    pg_session.commit()
    antwort = client.post(f"/invoices/{inv.id}/zahlungshinweis-uebernehmen")
    assert antwort.status_code == 400
    pg_session.refresh(inv)
    assert inv.payment_terms == HINWEIS


def test_uebernommener_hinweis_erlaubt_echte_finalisierung(client, pg_session):
    inv, kunde, _ = _entwurf(pg_session, None)
    kunde.zahlungshinweis = HINWEIS
    pg_session.commit()
    assert client.post(f"/invoices/{inv.id}/zahlungshinweis-uebernehmen").status_code == 303
    antwort = client.post(f"/invoices/{inv.id}/finalisieren")
    assert antwort.status_code == 303, antwort.text
    pg_session.refresh(inv)
    # #227: Rechnungsauftrag bleibt issued, ohne erfundenes bezahlt_am.
    assert inv.status == "issued"
    assert inv.bezahlt_am is None
    assert inv.due_date is None
    assert HINWEIS in inv.zugferd_xml
    assert client.post(f"/invoices/{inv.id}/zahlungshinweis-uebernehmen").status_code == 400
