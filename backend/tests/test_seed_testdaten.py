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
from scripts.seed_testdaten import _firma_belegt, _firma_felder, _vorgabe_land, main
from tests.helpers import mustang_befund
from tests.helpers.firma_eingerichtet import leere_firma as _teilweise_leer


def leere_firma(pg_session):
    """Firmenzeile ganz leer: auch die Pflichtangaben der Rechtsform und die Kontaktdaten,
    die die Fixture setzt. Jedes nicht leere Feld waere fuer das Skript Bestand."""
    firma = _teilweise_leer(pg_session)
    for feld in ("rechtsform", "registergericht", "registernummer", "vertretung",
                 "email", "phone", "sitz"):
        setattr(firma, feld, None)
    pg_session.commit()
    return firma


def _zahlen(pg_session):
    return (pg_session.query(Customer).count(), pg_session.query(Invoice).count())


def test_leere_db_erhaelt_zwei_kunden_und_zwei_entwuerfe(pg_session, capsys):
    leere_firma(pg_session)

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
    assert "2 Kunden" in capsys.readouterr().out


def test_firma_mit_name_ist_bestand_auch_ohne_abgeschlossene_einrichtung(pg_session, capsys):
    firma = leere_firma(pg_session)
    firma.name = "Vorhandene Firma"
    firma.address_line1 = "Altweg 9"
    pg_session.commit()

    rc = main([], db=pg_session)

    assert rc != 0
    assert "--erzwingen" in capsys.readouterr().err
    pg_session.expire_all()
    firma = pg_session.query(Company).filter(Company.id == 1).one()
    assert (firma.name, firma.address_line1) == ("Vorhandene Firma", "Altweg 9")
    assert firma.setup_completed_at is None
    assert _zahlen(pg_session) == (0, 0)


def test_eingerichtete_firma_ist_bestand_und_bleibt_mit_erzwingen_unberuehrt(pg_session):
    vorher = pg_session.query(Company).filter(Company.id == 1).one().name

    assert main([], db=pg_session) != 0
    assert _zahlen(pg_session) == (0, 0)

    assert main(["--erzwingen"], db=pg_session) == 0
    pg_session.expire_all()
    assert pg_session.query(Company).filter(Company.id == 1).one().name == vorher
    assert _zahlen(pg_session) == (2, 2)


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
    leere_firma(pg_session)
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
    leere_firma(pg_session)
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
    leere_firma(pg_session)
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


@pytest.mark.parametrize("feld, wert", [
    ("address_line1", "Altweg 9"), ("zip_code", "99999"), ("city", "Altstadt"),
    ("tax_number", "00/000/00000"), ("vat_id", "XX000"), ("registergericht", "Amtsgericht Alt"),
    ("vertretung", "Alte Leitung"), ("email", "alt@example.invalid"),
    ("rechtsform", "ug"), ("registernummer", "HRB 7"),
    # Ein Land, das vom Spaltenvorgabewert DE abweicht, ist eine Entscheidung des Betreibers.
    ("country", "AT"),
])
def test_jedes_nicht_leere_firmenfeld_ist_bestand_auch_bei_leerem_namen(
    pg_session, capsys, feld, wert,
):
    """Name leer, aber ein anderes Feld belegt: die Musterwerte duerften es ueberschreiben."""
    firma = leere_firma(pg_session)
    setattr(firma, feld, wert)
    pg_session.commit()

    rc = main([], db=pg_session)

    assert rc != 0
    assert "--erzwingen" in capsys.readouterr().err
    pg_session.expire_all()
    firma = pg_session.query(Company).filter(Company.id == 1).one()
    assert getattr(firma, feld) == wert
    assert not (firma.name or "").strip()
    assert _zahlen(pg_session) == (0, 0)


def test_firma_belegt_liest_vorgabeland_aus_dem_modell(monkeypatch):
    """Vorgabeland kommt von der Modellspalte, nicht aus dem Musterliteral.

    Aendert man den Spaltendefault (hier per monkeypatch auf „AT“), zaehlt eine
    sonst leere Firmenzeile mit country="AT" nicht als Bestand, eine mit "DE" doch.
    """
    from types import SimpleNamespace

    spalte = Company.__table__.c.country
    monkeypatch.setattr(spalte.default, "arg", "AT")

    leer = {feld: "" for feld in _firma_felder()}
    assert _firma_belegt(SimpleNamespace(**{**leer, "country": "AT"})) is False
    assert _firma_belegt(SimpleNamespace(**{**leer, "country": "DE"})) is True


def test_vorgabe_land_lehnt_callable_ab(monkeypatch):
    """Callable als default.arg liefert Unsinn per str(); klarer RuntimeError statt raten."""
    spalte = Company.__table__.c.country
    monkeypatch.setattr(spalte.default, "arg", lambda: "DE")

    with pytest.raises(RuntimeError, match=r"aufrufbar|Callable|callable"):
        _vorgabe_land()


def test_vorgabe_land_nimmt_server_default_klauseltext_ohne_anfuehrungszeichen(monkeypatch):
    """SQL-Klausel (TextClause): Klauseltext ohne Anführungszeichen, nicht str(Klausel)."""
    from sqlalchemy import text

    spalte = Company.__table__.c.country
    monkeypatch.setattr(spalte, "default", None)
    monkeypatch.setattr(spalte.server_default, "arg", text("'AT'"))

    assert _vorgabe_land() == "AT"


def test_vorgabe_land_lehnt_fremden_arg_typ_ab(monkeypatch):
    """Alles außer str (bzw. Klauseltext) ist kein Vorgabeland."""
    spalte = Company.__table__.c.country
    monkeypatch.setattr(spalte.default, "arg", 42)

    with pytest.raises(RuntimeError, match=r"str"):
        _vorgabe_land()


@pytest.mark.parametrize(("wert", "gemeldet"), [
    ("DEU", "'DEU'"), ("", "''"), ("D1", "'D1'"), ("'  '", "'  '"),
])
def test_vorgabe_land_lehnt_nicht_iso_alpha2_ab(monkeypatch, wert, gemeldet):
    """Nach strip/upper muss das Vorgabeland genau zwei A–Z sein; die Meldung nennt den Wert."""
    spalte = Company.__table__.c.country
    monkeypatch.setattr(spalte.default, "arg", wert)

    with pytest.raises(RuntimeError) as ei:
        _vorgabe_land()
    assert f"gefunden: {gemeldet}" in str(ei.value)


def test_vorgabe_land_lehnt_cast_klausel_ab(monkeypatch):
    """Server-Default mit Cast (`'DE'::character varying`) ist kein reines Landeskürzel."""
    from sqlalchemy import text

    spalte = Company.__table__.c.country
    monkeypatch.setattr(spalte, "default", None)
    monkeypatch.setattr(spalte.server_default, "arg", text("'DE'::character varying"))

    with pytest.raises(RuntimeError, match="ISO-Alpha-2"):
        _vorgabe_land()


def test_vorgabe_land_nimmt_kleingeschriebenes_iso_alpha2(monkeypatch):
    """Kleinbuchstaben werden normalisiert und als ISO-Alpha-2 akzeptiert."""
    spalte = Company.__table__.c.country
    monkeypatch.setattr(spalte.default, "arg", "at")

    assert _vorgabe_land() == "AT"
