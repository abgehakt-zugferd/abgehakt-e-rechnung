"""Laenderlisten fuer die Landesauswahl in den Formularen (#75, #81).

Bisher kannten die Formulare nur DE, AT, CH und US — ein Kunde in Finnland
liess sich ueber die Oberflaeche nicht anlegen. Seit #75 steht die kuratierte
Liste `LAENDER` (47) einmal in `app/laender.py` und wird als Jinja-Global in
die drei Router gegeben. Seit #81 steht daneben `ISO_LAENDER` (249) fuer
Einrichtung und Einstellungen; das Kundenformular bleibt bei den 47.

Griechenland traegt zwei Codes, und das ist kein Fehler: gespeichert und in
der ZUGFeRD-XML steht `GR` (ISO 3166-1), VIES kennt Griechenland als `EL`.
Die Abbildung lebt in `services/ust_id_pruefung._VIES_LAENDER` und wird hier
nur festgehalten, nicht verdoppelt.
"""
import re
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.templating import Jinja2Templates

from app.laender import (ISO_LAENDER, LAENDER, registriere_laender_globals,
                         sortierschluessel as _faltung)
from app.models.customer import Customer
from app.services import mustang, pdfa
from app.services.ust_id_pruefung import aufteilen_ust_id




def test_liste_hat_genau_47_eintraege():
    assert len(LAENDER) == 47


def test_iso_liste_hat_genau_249_eintraege():
    """#81: volle ISO-3166-1-alpha-2-Liste (249 offiziell vergebene Codes).
    Die Zahl folgt aus der Quelle, nicht aus einer Wunschvorgabe; ein
    Vertauschen mit LAENDER (47) macht diesen Test und den Kundentest rot."""
    assert len(ISO_LAENDER) == 249


def test_japan_steht_in_der_iso_liste():
    """Abnahme #81: Aussteller mit Sitz in Japan muss waehlbar sein."""
    assert ("JP", "Japan") in ISO_LAENDER


def test_jeder_laender_eintrag_steht_gleichnamig_in_iso_liste():
    """Sonst driften die kuratierte und die volle Liste auseinander."""
    iso = set(ISO_LAENDER)
    for eintrag in LAENDER:
        assert eintrag in iso, f"{eintrag!r} fehlt oder weicht in ISO_LAENDER ab"


def test_deutschland_steht_an_erster_stelle():
    assert LAENDER[0] == ("DE", "Deutschland")
    assert ISO_LAENDER[0] == ("DE", "Deutschland")


def test_danach_alphabetisch_nach_deutschem_namen():
    namen = [name for _, name in LAENDER[1:]]
    assert namen == sorted(namen, key=_faltung)
    iso_namen = [name for _, name in ISO_LAENDER[1:]]
    assert iso_namen == sorted(iso_namen, key=_faltung)


def test_diakritika_sortieren_wie_ihr_grundbuchstabe():
    """Ålandinseln gehoert zwischen Ägypten und Albanien, nicht ans Listenende.

    Diese Zusicherung nennt die Nachbarn beim Namen, statt mit `_faltung` zu
    pruefen. Ein Test, der dieselbe Regel anwendet, mit der die Liste erzeugt
    wurde, bestaetigt nur sich selbst: `å` lag hinter `z`, die Liste war
    danach sortiert, und der Sortiertest blieb trotzdem gruen.
    """
    codes = [code for code, _ in ISO_LAENDER]
    assert codes.index("EG") < codes.index("AX") < codes.index("AL"), (
        "Ålandinseln steht an Position "
        f"{codes.index('AX') + 1} von {len(codes)}, erwartet zwischen "
        f"Ägypten ({codes.index('EG') + 1}) und Albanien ({codes.index('AL') + 1})"
    )


def test_codes_sind_eindeutig_und_iso_alpha2():
    for liste in (LAENDER, ISO_LAENDER):
        codes = [code for code, _ in liste]
        assert len(codes) == len(set(codes))
        for code in codes:
            assert len(code) == 2 and code.isalpha() and code.isupper()


def test_finnland_und_griechenland_sind_enthalten():
    codes = {code for code, _ in LAENDER}
    assert "FI" in codes
    assert "GR" in codes


def test_griechenland_gr_gespeichert_vies_liefert_el():
    """GR ist der gespeicherte ISO-Code; die VIES-Abbildung bildet danach EL."""
    assert ("GR", "Griechenland") in LAENDER
    land, nummer = aufteilen_ust_id("GR123456789")
    assert land == "EL"
    assert nummer == "123456789"


def test_registriere_laender_globals_setzt_globals_je_instanz():
    """Jeder Router haelt sein eigenes Jinja-Environment — die Globals muessen
    je Instanz gesetzt werden (dieselbe Lage wie bei branding/darstellung)."""
    templates = Jinja2Templates(directory="app/templates")
    registriere_laender_globals(templates)
    assert templates.env.globals["LAENDER"] is LAENDER
    assert templates.env.globals["ISO_LAENDER"] is ISO_LAENDER


def _render_makro(gewaehlt: str, liste=None) -> str:
    templates = Jinja2Templates(directory="app/templates")
    registriere_laender_globals(templates)
    makro = templates.env.get_template("partials/land_auswahl.html").module.land_auswahl
    if liste is None:
        return makro("country", gewaehlt)
    return makro("country", gewaehlt, liste=liste)


def test_makro_rendert_volle_liste():
    html = _render_makro("DE")
    assert html.count("<option") == 47
    assert 'value="FI"' in html


def test_makro_mit_iso_liste_rendert_249_eintraege_inkl_japan():
    """#81: Einrichtung/Einstellungen reichen ISO_LAENDER; Vorgabe bleibt LAENDER."""
    html = _render_makro("DE", liste=ISO_LAENDER)
    assert html.count("<option") == 249
    assert '<option value="JP"' in html
    assert "Japan (JP)" in html


def test_makro_markiert_das_gewaehlte_land():
    html = _render_makro("FI")
    assert '<option value="FI" selected>Finnland (FI)</option>' in html
    assert html.count("selected") == 1


def test_makro_laesst_umlaut_namen_unbeschaedigt():
    html = _render_makro("DE")
    assert "Österreich" in html
    assert "Türkei" in html


def test_makro_rueckfall_unbekannter_code_gegen_iso_liste():
    """Auch die ISO-Liste aendert sich; unbekannte Codes duerfen nicht verschwinden."""
    html = _render_makro("XX", liste=ISO_LAENDER)
    assert '<option value="XX" selected>XX</option>' in html
    assert html.count("selected") == 1

# ------------------------------------------------------- Formulare (HTTP)

def _land_select(html: str) -> str:
    """Den <select name="country">-Block aus einer gerenderten Antwort holen."""
    treffer = re.search(r'<select name="country".*?</select>', html, re.S)
    assert treffer, "kein <select name=\"country\"> in der Antwort"
    return treffer.group(0)


def test_kundenformular_zeigt_die_kuratierte_laenderliste(client):
    """#81: Kunden bleiben bei 47; JP darf hier keine normale Option sein.
    Vertauschen mit ISO_LAENDER macht option-Zahl und fehlendes JP rot."""
    r = client.get("/customers/neu")
    assert r.status_code == 200
    block = _land_select(r.text)
    assert block.count("<option") == 47
    assert 'value="FI"' in block
    assert 'value="JP"' not in block
    # Vorgabe fuer einen neuen Kunden bleibt Deutschland.
    assert '<option value="DE" selected>' in block


def test_einstellungen_zeigen_die_iso_laenderliste(client):
    r = client.get("/settings/")
    assert r.status_code == 200
    block = _land_select(r.text)
    assert block.count("<option") == 249
    assert 'value="JP"' in block
    assert "Japan (JP)" in block


def test_umlaut_name_kommt_unbeschaedigt_durch_die_antwort(client):
    """Ein Umlaut-Name muss unbeschaedigt durch Vorlage UND HTTP-Antwort —
    eine reine Code-Pruefung wuerde ein kaputtes Encoding nicht fangen."""
    r = client.get("/settings/")
    assert r.status_code == 200
    assert "Österreich" in r.text
    assert "Türkei" in r.text


def test_einrichtung_zeigt_die_iso_laenderliste(client):
    r = client.get("/setup")
    assert r.status_code == 200
    block = _land_select(r.text)
    assert block.count("<option") == 249
    assert 'value="JP"' in block
    assert "Japan (JP)" in block


def test_unbekannter_gespeicherter_code_bleibt_ausgewaehlt(client, pg_session):
    """Rueckfall fuer Bestandsdaten: steht im Datensatz ein Code, den LAENDER
    nicht kennt, rendert das Makro ihn als zusaetzliche ausgewaehlte Option.
    Ohne den Rueckfall setzte ein Speichern des Formulars den Kunden
    stillschweigend auf den ersten Listeneintrag."""
    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Bestand AG",
                     address_line1="Weg 1", zip_code="10115", city="Berlin",
                     country="JP")
    pg_session.add(kunde)
    pg_session.commit()

    r = client.get(f"/customers/{kunde.id}/bearbeiten")
    assert r.status_code == 200
    block = _land_select(r.text)
    assert '<option value="JP" selected>JP</option>' in block

    # Ein blosses GET aendert die Datenbank nicht; eine Zusicherung danach kann
    # nur der Fixture-Aufbau rot machen, nie der Produktivcode. Gemessen wird
    # deshalb der Fall aus dem Docstring: Wer das Land nicht anfasst, schickt
    # die ausgewaehlte Option zurueck. Ohne Rueckfall waere das DE.
    treffer = re.search(r'<option value="([^"]+)" selected>', block)
    assert treffer, "keine ausgewaehlte Option im Select"
    client.post(f"/customers/{kunde.id}/bearbeiten", data={
        "customer_number": kunde.customer_number, "name": kunde.name,
        "address_line1": kunde.address_line1, "address_line2": "",
        "zip_code": kunde.zip_code, "city": kunde.city,
        "country": treffer.group(1), "vat_id": "", "ust_status": "regelbesteuert",
        "email": "", "cc_emails": "", "phone": "",
        "bank_iban": "", "bank_bic": "", "bank_name": "",
        "notes": "", "is_active": "1",
    })

    pg_session.expire_all()
    assert pg_session.get(Customer, kunde.id).country == "JP"


def test_einstellungen_rueckfall_fuer_code_ausserhalb_iso_liste(client, pg_session):
    """#81: Rueckfall auch gegen ISO_LAENDER; XX ist kein offizieller Code."""
    from app.models.company import Company

    firma = pg_session.get(Company, 1)
    firma.country = "XX"
    pg_session.commit()

    r = client.get("/settings/")
    assert r.status_code == 200
    block = _land_select(r.text)
    assert '<option value="XX" selected>XX</option>' in block
    treffer = re.search(r'<option value="([^"]+)" selected>', block)
    assert treffer, "keine ausgewaehlte Option im Select"

    client.post("/settings/firma", data={
        "name": firma.name, "address_line1": firma.address_line1,
        "address_line2": "", "zip_code": firma.zip_code, "city": firma.city,
        "country": treffer.group(1), "tax_number": firma.tax_number or "",
        "vat_id": firma.vat_id or "", "invoice_prefix": firma.invoice_prefix or "RE",
        "payment_terms_default": firma.payment_terms_default or "Zahlbar.",
        "payment_terms_default_en": "Payable within 14 days without deduction.",
    })

    pg_session.expire_all()
    assert pg_session.get(Company, 1).country == "XX"


# ------------------------------------------- End-to-End bis in die XML

@pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)
def test_finnischer_kunde_landet_als_fi_in_der_kaeufer_xml(pg_session):
    """#75: der gespeicherte Code laeuft unveraendert in ram:CountryID des
    Kaeufers — ein Kunde in Finnland erzeugt eine Rechnung mit FI, nicht mit
    einem Ersatzland. Echte Pipeline (draft → pruefen → finalisieren) gegen
    echtes Postgres, wie in test_finalize_e2e.py."""
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.database import get_db
    from app.main import app
    from app.models.invoice import Invoice, InvoiceItem

    kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}",
                     name="Helsinki Oy", address_line1="Mannerheimintie 1",
                     zip_code="00100", city="Helsinki", country="FI")
    pg_session.add(kunde)
    pg_session.flush()
    netto = Decimal("200.00")
    steuer = Decimal("38.00")
    nummer = f"RE-FI-{uuid.uuid4().hex[:6]}"
    rechnung = Invoice(invoice_number=nummer, customer_id=kunde.id,
                       issue_date=date(2026, 9, 23), delivery_date=date(2026, 9, 23),
                       due_date=date(2026, 10, 7), currency="EUR",
                       net_total=netto, tax_total=steuer, gross_total=netto + steuer,
                       tax_category="S", status="draft",
                       payment_terms="Zahlbar innerhalb 14 Tagen.")
    rechnung.items = [InvoiceItem(position=1, description="Beratungsleistung",
                                  unit="Stunde", quantity=Decimal("2"),
                                  unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
                                  net_amount=netto, tax_amount=steuer,
                                  gross_amount=netto + steuer)]
    pg_session.add(rechnung)
    pg_session.commit()

    app.dependency_overrides[get_db] = lambda: pg_session
    try:
        client = TestClient(app, follow_redirects=False)
        assert client.post(f"/invoices/{rechnung.id}/pruefen").status_code == 303
        assert client.post(f"/invoices/{rechnung.id}/finalisieren").status_code == 303
    finally:
        app.dependency_overrides.clear()

    pg_session.expire_all()
    satz = pg_session.get(Invoice, rechnung.id)
    assert satz.status == "issued"
    kaeufer = re.search(
        r"<ram:BuyerTradeParty>.*?</ram:BuyerTradeParty>", satz.zugferd_xml, re.S
    )
    assert kaeufer, "kein BuyerTradeParty in der erzeugten XML"
    assert "<ram:CountryID>FI</ram:CountryID>" in kaeufer.group(0)

    einstellungen = get_settings()
    (einstellungen.storage_path / "pdfs" / f"{nummer}.pdf").unlink(missing_ok=True)
    (einstellungen.storage_path / "pdfs" / f"{nummer}_visual.pdf").unlink(missing_ok=True)
    (einstellungen.storage_path / "xml" / f"{nummer}.xml").unlink(missing_ok=True)


@pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)
def test_japanischer_aussteller_landet_als_jp_in_der_verkaeufer_xml(pg_session):
    """#81: Einrichtung mit JP, Einstellungen zeigen JP gewaehlt, finalisierte
    Rechnung traegt JP in ram:CountryID der SellerTradeParty."""
    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.database import get_db
    from app.main import app
    from app.models.company import Company
    from app.models.invoice import Invoice, InvoiceItem

    firma = pg_session.get(Company, 1)
    firma.setup_completed_at = None
    firma.name = ""
    firma.address_line1 = ""
    firma.zip_code = ""
    firma.city = ""
    firma.tax_number = None
    firma.vat_id = None
    firma.country = "DE"
    pg_session.commit()

    app.dependency_overrides[get_db] = lambda: pg_session
    try:
        client = TestClient(app, follow_redirects=False)
        r = client.post("/setup", data={
            "name": "Tokyo Trading KK",
            "address_line1": "1-1 Chiyoda",
            "zip_code": "100-0001",
            "city": "Tokyo",
            "country": "JP",
            "tax_number": "T1234567890123",
            "vat_id": "",
        })
        assert r.status_code == 303, r.text

        pg_session.expire_all()
        assert pg_session.get(Company, 1).country == "JP"

        settings = client.get("/settings/")
        assert settings.status_code == 200
        block = _land_select(settings.text)
        assert '<option value="JP" selected>Japan (JP)</option>' in block

        kunde = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}",
                         name="Berlin GmbH", address_line1="Weg 1",
                         zip_code="10115", city="Berlin", country="DE")
        pg_session.add(kunde)
        pg_session.flush()
        netto = Decimal("100.00")
        steuer = Decimal("19.00")
        nummer = f"RE-JP-{uuid.uuid4().hex[:6]}"
        rechnung = Invoice(invoice_number=nummer, customer_id=kunde.id,
                           issue_date=date(2026, 9, 23), delivery_date=date(2026, 9, 23),
                           due_date=date(2026, 10, 7), currency="EUR",
                           net_total=netto, tax_total=steuer, gross_total=netto + steuer,
                           tax_category="S", status="draft",
                           payment_terms="Zahlbar innerhalb 14 Tagen.")
        rechnung.items = [InvoiceItem(position=1, description="Leistung",
                                      unit="Stück", quantity=Decimal("1"),
                                      unit_price=Decimal("100.00"), tax_rate=Decimal("19"),
                                      net_amount=netto, tax_amount=steuer,
                                      gross_amount=netto + steuer)]
        pg_session.add(rechnung)
        pg_session.commit()

        assert client.post(f"/invoices/{rechnung.id}/pruefen").status_code == 303
        assert client.post(f"/invoices/{rechnung.id}/finalisieren").status_code == 303
    finally:
        app.dependency_overrides.clear()

    pg_session.expire_all()
    satz = pg_session.get(Invoice, rechnung.id)
    assert satz.status == "issued"
    verkaeufer = re.search(
        r"<ram:SellerTradeParty>.*?</ram:SellerTradeParty>", satz.zugferd_xml, re.S
    )
    assert verkaeufer, "kein SellerTradeParty in der erzeugten XML"
    assert "<ram:CountryID>JP</ram:CountryID>" in verkaeufer.group(0)

    einstellungen = get_settings()
    (einstellungen.storage_path / "pdfs" / f"{nummer}.pdf").unlink(missing_ok=True)
    (einstellungen.storage_path / "pdfs" / f"{nummer}_visual.pdf").unlink(missing_ok=True)
    (einstellungen.storage_path / "xml" / f"{nummer}.xml").unlink(missing_ok=True)
