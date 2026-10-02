"""Pflichtangaben auf Geschäftsbriefen (§ 35a GmbHG, § 80 AktG, §§ 37a, 125a HGB).

Eine Rechnung ist ein Geschäftsbrief. Eine Kapitalgesellschaft muss darauf Rechtsform,
Sitz, Registergericht, Registernummer und ihre Vertretung nennen. Fehlte bis 2026-10
vollständig: Abgehakt kannte weder Felder noch Ausgabe dafür.
"""
import uuid
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal

import pytest
from pypdf import PdfReader

from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.services import mustang, pdf_generator, zugferd_xml
from app.services.pflichtangaben import RECHTSFORMEN, pflichtangaben
from tests.factories import orm_company, orm_customer, orm_invoice_for
from tests.probe_daten import HRB_PROBE, IBAN_FIRMA_PROBE, STEUER_PROBE_ELF


def _gmbh(**over) -> Company:
    kw = dict(
        id=1, name="Muster Handwerk GmbH",
        address_line1="Musterstraße 1", zip_code="12345", city="Musterstadt",
        tax_number=STEUER_PROBE_ELF, bank_iban=IBAN_FIRMA_PROBE,
        rechtsform="gmbh",
        registergericht="Amtsgericht Musterstadt",
        registernummer=HRB_PROBE,
        vertretung="Probe Geschäftsführerin, Probe Geschäftsführer",
    )
    kw.update(over)
    return Company(**kw)


def _rechnung(document_language="de") -> Invoice:
    item = InvoiceItem(
        position=1, description="Beratungsleistung", quantity=Decimal("2"),
        unit="Stunde", unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
        net_amount=Decimal("200.00"), tax_amount=Decimal("38.00"),
    )
    inv = Invoice(
        invoice_number="RE-2026-777", issue_date=date(2026, 7, 8),
        delivery_date=date(2026, 7, 8), due_date=date(2026, 7, 22),
        net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
        gross_total=Decimal("238.00"), tax_category="S",
        payment_terms="Zahlbar innerhalb 14 Tagen.", notes="",
        document_language=document_language,
    )
    inv.customer = Customer(
        name="Probe Kunde GmbH", address_line1="Kundenweg 1",
        zip_code="10115", city="Berlin", country="DE",
    )
    inv.items = [item]
    return inv


def _pdf_text(company, tmp_path, inv=None) -> str:
    out = tmp_path / "beleg.pdf"
    pdf_generator.generate_pdf(inv or _rechnung(), company, out)
    text = "".join(p.extract_text() or "" for p in PdfReader(str(out)).pages)
    return " ".join(text.split())


def test_gmbh_traegt_registerangaben_und_geschaeftsfuehrung_im_pdf(tmp_path):
    text = _pdf_text(_gmbh(), tmp_path)

    assert "Sitz: Musterstadt" in text
    assert f"Registergericht: Amtsgericht Musterstadt, {HRB_PROBE}" in text
    assert "Geschäftsführung: Probe Geschäftsführerin, Probe Geschäftsführer" in text


def test_einzelunternehmen_braucht_keine_registerangaben():
    angaben = pflichtangaben(_gmbh(
        name="Probe Grafikdesign", rechtsform="einzelunternehmen",
        registergericht=None, registernummer=None, vertretung=None,
    ))

    assert angaben.zeilen == ()
    assert angaben.fehlend == ()


def test_ohne_gewaehlte_rechtsform_fehlt_die_rechtsform_selbst():
    """Bestand nach dem Update: niemand hat gewählt, also darf nicht gestellt werden."""
    angaben = pflichtangaben(_gmbh(rechtsform=None))

    assert angaben.zeilen == ()
    assert angaben.fehlend == ("rechtsform",)


def test_gmbh_ohne_register_und_geschaeftsfuehrung_meldet_alle_drei_luecken():
    angaben = pflichtangaben(_gmbh(registergericht=" ", registernummer=None, vertretung=""))

    assert angaben.fehlend == ("registergericht", "registernummer", "vertretung")


def test_entwurf_mit_luecken_druckt_keine_leeren_bezeichner():
    """Die Vorschau eines Entwurfs entsteht auch mit Lücken; dort darf kein
    „Registergericht: , “ stehen, das wie eine Angabe aussieht."""
    angaben = pflichtangaben(_gmbh(registergericht=None, registernummer=None, vertretung=None))

    assert angaben.zeilen == ("Sitz: Musterstadt",)


def test_ag_nennt_vorstand_und_verlangt_aufsichtsratsvorsitz():
    ag = _gmbh(name="Probe Werke AG", rechtsform="ag", vertretung="Probe Vorständin")

    assert pflichtangaben(ag).fehlend == ("aufsichtsrat_vorsitz",)

    ag.aufsichtsrat_vorsitz = "Probe Aufsichtsrätin"
    angaben = pflichtangaben(ag)
    assert angaben.fehlend == ()
    assert angaben.zeilen[1:] == (
        "Vorstand: Probe Vorständin  ·  Vorsitz des Aufsichtsrats: Probe Aufsichtsrätin",
    )


def test_gmbh_mit_aufsichtsrat_nennt_dessen_vorsitz_ohne_ihn_zu_verlangen():
    assert pflichtangaben(_gmbh()).fehlend == ()

    angaben = pflichtangaben(_gmbh(aufsichtsrat_vorsitz="Probe Aufsichtsrätin"))
    assert angaben.zeilen[-1].endswith("Vorsitz des Aufsichtsrats: Probe Aufsichtsrätin")


REGISTER = ("registergericht", "registernummer")
ERWARTET_LEER = {
    "einzelunternehmen": (),
    "ek": REGISTER,
    "ohg": REGISTER,
    "kg": REGISTER,
    "partg": REGISTER,
    "gmbh": REGISTER + ("vertretung",),
    "ug": REGISTER + ("vertretung",),
    "ag": REGISTER + ("vertretung", "aufsichtsrat_vorsitz"),
    "sonstige": (),
}


@pytest.mark.parametrize("rechtsform", sorted(ERWARTET_LEER))
def test_jede_rechtsform_verlangt_genau_ihre_angaben(rechtsform):
    leer = _gmbh(rechtsform=rechtsform, registergericht=None, registernummer=None,
                 vertretung=None, aufsichtsrat_vorsitz=None)

    assert pflichtangaben(leer).fehlend == ERWARTET_LEER[rechtsform]


def test_auswahl_im_formular_ist_genau_der_gepruefte_katalog():
    """Eine Rechtsform, die das Formular anbietet und die Tabelle oben nicht kennt,
    hätte ungeprüfte Anforderungen."""
    assert set(RECHTSFORMEN) == set(ERWARTET_LEER)


def test_englischer_beleg_beschriftet_die_angaben_englisch(tmp_path):
    text = _pdf_text(_gmbh(aufsichtsrat_vorsitz="Probe Aufsichtsrätin"), tmp_path,
                     _rechnung(document_language="en"))

    assert "Registered office: Musterstadt" in text
    assert f"Register court: Amtsgericht Musterstadt, {HRB_PROBE}" in text
    assert "Managing directors: Probe Geschäftsführerin" in text
    assert "Chair of the supervisory board: Probe Aufsichtsrätin" in text
    assert "Registergericht" not in text


def test_sonderzeichen_in_den_angaben_erscheinen_woertlich_im_pdf(tmp_path):
    """Der Fuß ist ReportLab-Markup: ein nacktes `<` oder `&` würde verschluckt
    oder bräche den Satz ab."""
    text = _pdf_text(_gmbh(vertretung="Probe <Leitung> & Partner"), tmp_path)

    assert "Geschäftsführung: Probe <Leitung> & Partner" in text


RAM = "{urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100}"


def _verkaeufer(xml: str):
    return ET.fromstring(xml.encode("utf-8")).find(f".//{RAM}SellerTradeParty")


def test_xml_traegt_registernummer_als_bt30_und_angaben_als_bt33(tmp_path):
    company = orm_company(rechtsform="gmbh", registergericht="Amtsgericht Musterstadt",
                          registernummer=HRB_PROBE, vertretung="Probe Geschäftsführerin")
    xml = zugferd_xml.generate_xml(orm_invoice_for(orm_customer()), company)

    seller = _verkaeufer(xml)
    assert seller.findtext(f"{RAM}SpecifiedLegalOrganization/{RAM}ID") == HRB_PROBE
    assert seller.findtext(f"{RAM}Description") == "\n".join(pflichtangaben(company).zeilen)

    pfad = tmp_path / "beleg.xml"
    pfad.write_text(xml, encoding="utf-8")
    befund = mustang.validate(pfad)
    assert befund["is_valid"], befund["errors"]


def _entwurf(pg_session) -> Invoice:
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Probe Kunde GmbH",
                     address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(kunde)
    pg_session.flush()
    inv = Invoice(invoice_number=f"RE-2026-{uuid.uuid4().hex[:6]}", customer_id=kunde.id,
                  issue_date=date(2026, 7, 8), delivery_date=date(2026, 7, 8),
                  due_date=date(2026, 7, 22), currency="EUR", tax_category="S",
                  status="draft", payment_terms="Zahlbar in 14 Tagen.",
                  net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
                  gross_total=Decimal("238.00"))
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Stunde",
                             quantity=Decimal("1"), unit_price=Decimal("200.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("200.00"),
                             tax_amount=Decimal("38.00"), gross_amount=Decimal("238.00"))]
    pg_session.add(inv)
    pg_session.commit()
    return inv


def test_stellen_bricht_ab_solange_registerangaben_fehlen(pg_session, client):
    firma = pg_session.get(Company, 1)
    firma.rechtsform, firma.registergericht, firma.registernummer = "gmbh", None, None
    firma.vertretung = "Probe Geschäftsführerin"
    pg_session.commit()
    inv = _entwurf(pg_session)

    antwort = client.post(f"/invoices/{inv.id}/finalisieren")

    assert antwort.status_code == 400
    assert "Registergericht" in antwort.text and "Registernummer" in antwort.text
    assert "§ 35a GmbHG" in antwort.text
    pg_session.expire_all()
    assert pg_session.get(Invoice, inv.id).status == "draft"


def test_stellen_bricht_ab_solange_keine_rechtsform_gewaehlt_ist(pg_session, client):
    firma = pg_session.get(Company, 1)
    firma.rechtsform = None
    pg_session.commit()
    inv = _entwurf(pg_session)

    antwort = client.post(f"/invoices/{inv.id}/finalisieren")

    assert antwort.status_code == 400
    assert "Rechtsform" in antwort.text


def _firma_form(**extra):
    data = {
        "name": "Muster Handwerk GmbH", "address_line1": "Musterstraße 1",
        "zip_code": "12345", "city": "Musterstadt", "country": "DE",
        "invoice_prefix": "RE", "kst_satz_percent": "15", "soli_auf_kst_percent": "5,5",
        "gewerbe_hebesatz": "400",
        "payment_terms_default": "Zahlbar innerhalb von 14 Tagen ohne Abzug.",
        "payment_terms_default_en": "Payable within 14 days without deduction.",
        "rechtsform": "ag", "sitz": " Probestadt ",
        "registergericht": "Amtsgericht Musterstadt", "registernummer": HRB_PROBE,
        "vertretung": "Probe Vorständin", "aufsichtsrat_vorsitz": "Probe Aufsichtsrätin",
    }
    data.update(extra)
    return data


def test_einstellungen_speichern_die_pflichtangaben(pg_session, client):
    antwort = client.post("/settings/firma", data=_firma_form())

    assert antwort.status_code == 303
    pg_session.expire_all()
    firma = pg_session.get(Company, 1)
    assert (firma.rechtsform, firma.sitz, firma.registergericht, firma.registernummer,
            firma.vertretung, firma.aufsichtsrat_vorsitz) == (
        "ag", "Probestadt", "Amtsgericht Musterstadt", HRB_PROBE,
        "Probe Vorständin", "Probe Aufsichtsrätin")


@pytest.mark.parametrize("rechtsform", ["", "gbr-erfunden"])
def test_einstellungen_ohne_gueltige_rechtsform_speichern_nichts(pg_session, client, rechtsform):
    antwort = client.post("/settings/firma", data=_firma_form(rechtsform=rechtsform, city="Anderswo"))

    assert antwort.status_code == 200
    assert "Rechtsform" in antwort.text
    pg_session.expire_all()
    firma = pg_session.get(Company, 1)
    assert (firma.rechtsform, firma.city) == ("gmbh", "Musterstadt")


def test_einstellungsseite_zeigt_gespeicherte_angaben_und_was_noch_fehlt(pg_session, client):
    firma = pg_session.get(Company, 1)
    firma.registernummer = None
    pg_session.commit()

    seite = client.get("/settings/").text

    assert '<option value="gmbh" selected>' in seite
    assert 'name="registergericht" value="Amtsgericht Musterstadt"' in seite
    assert "Noch nicht stellbar, es fehlt: Registernummer (§ 35a GmbHG)" in seite


def _einrichtung(**extra):
    data = {
        "name": "Probe Werkstatt GmbH", "address_line1": "Musterweg 3",
        "zip_code": "80331", "city": "München", "country": "DE",
        "tax_number": STEUER_PROBE_ELF,
        "rechtsform": "gmbh", "registergericht": "Amtsgericht Musterstadt",
        "registernummer": HRB_PROBE, "vertretung": "Probe Geschäftsführerin",
    }
    data.update(extra)
    return data


def _uneingerichtet(pg_session):
    firma = pg_session.get(Company, 1)
    firma.setup_completed_at = None
    firma.rechtsform = firma.registergericht = firma.registernummer = firma.vertretung = None
    pg_session.commit()


def test_einrichtung_speichert_die_pflichtangaben(pg_session, client):
    _uneingerichtet(pg_session)

    antwort = client.post("/setup", data=_einrichtung())

    assert antwort.status_code == 303
    pg_session.expire_all()
    firma = pg_session.get(Company, 1)
    assert pflichtangaben(firma).fehlend == ()
    assert firma.registernummer == HRB_PROBE


@pytest.mark.parametrize("luecke, erwartet", [
    ({"rechtsform": ""}, "Rechtsform"),
    ({"registernummer": ""}, "Registernummer (§ 35a GmbHG)"),
])
def test_einrichtung_bleibt_offen_solange_pflichtangaben_fehlen(pg_session, client, luecke, erwartet):
    _uneingerichtet(pg_session)

    antwort = client.post("/setup", data=_einrichtung(**luecke))

    assert antwort.status_code == 400
    assert erwartet in antwort.text
    pg_session.expire_all()
    assert pg_session.get(Company, 1).setup_completed_at is None


def test_einrichtungsseite_fragt_rechtsform_und_register_ab(pg_session, client):
    _uneingerichtet(pg_session)

    seite = client.get("/setup").text

    assert '<select name="rechtsform" required' in seite
    for schluessel in RECHTSFORMEN:
        assert f'<option value="{schluessel}"' in seite
    for feld in ("registergericht", "registernummer", "vertretung", "sitz", "aufsichtsrat_vorsitz"):
        assert f'name="{feld}"' in seite
