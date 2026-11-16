"""Seed-Skript fuer eine Test-VM: erfundene Firma, zwei Kunden, zwei Entwuerfe.

Das Skript laeuft ueber den normalen Dienstweg (Nummernvergabe, Finalisierung durch
die echte ZUGFeRD-Pipeline mit Mustang), nicht per SQL. Es bricht ab, wenn die DB
schon Kunden oder Rechnungen enthaelt, ausser mit `--erzwingen`.
"""
from decimal import Decimal

import pytest

from app.config import get_settings
from app.models.company import Company
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.services import mustang, pdfa
from app.services.ersteinrichtung import ist_eingerichtet
from scripts.seed_testdaten import main
from tests.helpers import mustang_befund
from tests.helpers.firma_eingerichtet import leere_firma


def _zahlen(pg_session):
    return (pg_session.query(Customer).count(), pg_session.query(Invoice).count())


def test_leere_db_erhaelt_zwei_kunden_und_zwei_entwuerfe(pg_session, capsys):
    firma_vorher = pg_session.query(Company).filter(Company.id == 1).one().name

    rc = main([], db=pg_session)

    assert rc == 0
    pg_session.expire_all()
    assert _zahlen(pg_session) == (2, 2)
    kunden = pg_session.query(Customer).order_by(Customer.customer_number).all()
    laender = sorted(k.country for k in kunden)
    assert laender[0] != "DE" and laender[1] == "DE"
    ausland = next(k for k in kunden if k.country != "DE")
    assert ausland.vat_id, "der Kunde im EU-Ausland traegt eine Platzhalter-USt-IdNr."
    entwuerfe = pg_session.query(Invoice).all()
    assert {e.customer_id for e in entwuerfe} == {k.id for k in kunden}
    for e in entwuerfe:
        assert e.status == "draft"
        assert len(e.items) >= 1
        assert e.net_total == sum((i.net_amount for i in e.items), Decimal("0"))
        assert e.gross_total == e.net_total + e.tax_total
    assert {e.tax_category for e in entwuerfe} == {"S", "AE"}
    # Eine vorhandene, eingerichtete Firma bleibt unberuehrt.
    assert pg_session.query(Company).filter(Company.id == 1).one().name == firma_vorher
    assert "2 Kunden" in capsys.readouterr().out


def test_leere_firmenzeile_wird_mit_erfundenen_daten_eingerichtet(pg_session):
    leere_firma(pg_session)

    assert main([], db=pg_session) == 0

    pg_session.expire_all()
    firma = pg_session.query(Company).filter(Company.id == 1).one()
    assert ist_eingerichtet(firma)
    assert firma.name and firma.tax_number and firma.vat_id
    assert _zahlen(pg_session) == (2, 2)


def test_fehlende_firmenzeile_wird_angelegt(pg_session):
    pg_session.query(Company).delete()
    pg_session.commit()

    assert main([], db=pg_session) == 0

    pg_session.expire_all()
    assert ist_eingerichtet(pg_session.query(Company).filter(Company.id == 1).one())


def test_vorhandener_kunde_bricht_ohne_erzwingen_ab_und_schreibt_nichts(pg_session, capsys):
    pg_session.add(Customer(customer_number="K-VORHER", name="Vorhandener Kunde",
                            address_line1="Weg 1", zip_code="10115", city="Berlin",
                            country="DE"))
    pg_session.commit()
    firma_vorher = pg_session.query(Company).filter(Company.id == 1).one().invoice_counter

    rc = main([], db=pg_session)

    assert rc != 0
    assert "--erzwingen" in capsys.readouterr().err
    pg_session.expire_all()
    assert _zahlen(pg_session) == (1, 0)
    assert pg_session.query(Company).filter(Company.id == 1).one().invoice_counter == firma_vorher


def test_leere_firma_und_vorhandener_kunde_aendert_auch_die_firma_nicht(pg_session):
    """Der Schutz steht VOR jeder Schreibung, auch vor der Firmeneinrichtung."""
    leere_firma(pg_session)
    pg_session.add(Customer(customer_number="K-VORHER", name="Vorhandener Kunde",
                            address_line1="Weg 1", zip_code="10115", city="Berlin",
                            country="DE"))
    pg_session.commit()

    assert main([], db=pg_session) != 0

    pg_session.expire_all()
    assert not ist_eingerichtet(pg_session.query(Company).filter(Company.id == 1).one())


def test_erzwingen_legt_trotz_vorhandenem_kunden_an(pg_session):
    pg_session.add(Customer(customer_number="K-VORHER", name="Vorhandener Kunde",
                            address_line1="Weg 1", zip_code="10115", city="Berlin",
                            country="DE"))
    pg_session.commit()

    assert main(["--erzwingen"], db=pg_session) == 0

    pg_session.expire_all()
    assert _zahlen(pg_session) == (3, 2)


@pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfuegbar",
)
def test_finalisieren_erzeugt_gueltige_e_rechnungen_im_storage(pg_session):
    storage = get_settings().storage_path
    angelegt = []
    try:
        assert main(["--finalisieren"], db=pg_session) == 0

        pg_session.expire_all()
        rechnungen = pg_session.query(Invoice).all()
        assert len(rechnungen) == 2
        for rechnung in rechnungen:
            assert rechnung.status == "issued"
            assert "CrossIndustryInvoice" in (rechnung.zugferd_xml or "")
            pdf = storage / "pdfs" / rechnung.pdf_filename
            xml = storage / "xml" / f"{rechnung.invoice_number}.xml"
            angelegt += [pdf, xml]
            assert pdf.exists() and xml.exists()
            ergebnis = mustang.validate(pdf)
            mustang_befund.gueltig_mit_xml(ergebnis, f"nicht valide:\n{ergebnis['raw']}")
    finally:
        for datei in angelegt:
            datei.unlink(missing_ok=True)
