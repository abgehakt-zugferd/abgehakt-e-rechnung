"""Aus einem angenommenen rechnungsauftrag wird ein Entwurf (§ 8a, Bauschritt 4b).

Wie bei der 389 gilt: Erst der Knopf schreibt fest, alles oder nichts, und was
entsteht, ist ein ENTWURF. Der Unterschied ist die Steuer: Der Auftrag traegt
nur Netto, Kategorie und Vermerk kommen aus der Vorgabe am Kunden (Festlegung
13). Fehlt sie, entsteht nichts - das Muster ist der ungeklaerte Steuerstatus
der 389: Die Steuer wird nicht geraten.
"""

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.uebergabe_eingang import UebergabeEingang
from app.services.archive_frist import berechne_archive_until
from app.services.rechnungsauftrag_wirkung import (
    BelegSchonVerarbeitet,
    WirkungFehler,
    entwurf_anlegen,
)
from app.services.uebergabe_befund import Belegurteil, Feststellung
from app.services.validator import validate_invoice
from app.zeit import heute
from tests.factories import (
    company_stub as _company,
    validator_invoice_stub as _invoice,
)
from tests.helpers.uebergabe import PARTNER_A, rechnungsauftrag

ERZEUGT = datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)
SCHLUESSEL = "plattform:2026-02:kanal-a:x1"


def _kunde(pg_session, kennung=PARTNER_A, **felder):
    """Kunde mit der Steuervorgabe fuer Auftraege (Festlegung 13).

    Land NL: Reverse Charge (AE) passt zu einem Kunden in einem anderen
    EU-Mitgliedstaat; ein DE-Kunde wuerde nur eine zusaetzliche Warnung
    der Plausibilitaetspruefung geben (steuerkategorie_land.py).
    """
    angaben = dict(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Plattform Beispiel GmbH",
        address_line1="Platz 1", zip_code="1015", city="Amsterdam", country="NL",
        auftrag_steuer="AE", vat_id="NL123456789B01",
        kopftext="Vereinbarung vom 1. Januar 2026, Abrechnungsmonat {leistungsmonat}.",
        fusstext="Der Abrechnungsbericht ist die Einzelaufstellung.",
        zahlungshinweis="Zahlung folgt dem Auszahlungsbericht der Plattform.",
        belegsprache_vorgabe="de",
    )
    angaben.update(felder)
    kunde = Customer(**angaben)
    kunde.id = uuid.UUID(str(kennung))
    pg_session.add(kunde)
    pg_session.flush()
    return kunde


def _urteil(nutzlast=None, **aenderungen):
    felder = dict(
        beleg_sha256="2" * 64,
        beleg_id="11111111-2222-4333-8444-555555555556",
        angenommen=True,
        absender="tantiemen-app",
        nutzlast_art="rechnungsauftrag",
        erzeugt_am=ERZEUGT,
        nutzlast=rechnungsauftrag() if nutzlast is None else nutzlast,
    )
    felder.update(aenderungen)
    return Belegurteil(**felder)


# --- Der Entwurf aus dem Auftrag ---------------------------------------------


def test_aus_dem_auftrag_wird_ein_entwurf_der_standardrechnung(pg_session):
    _kunde(pg_session)

    entwurf = entwurf_anlegen(pg_session, _urteil(), dateiname="auftrag.json")
    pg_session.flush()

    assert entwurf.status == "draft"
    # invoice_type None ist die Standardrechnung (380); der Auftrag nennt
    # ebendiesen Typcode, die Anwendung setzt ihn nicht noch einmal.
    assert entwurf.invoice_type is None
    assert entwurf.tax_category == "AE"
    assert entwurf.currency == "EUR"
    assert entwurf.service_period_start == date(2026, 2, 1)
    assert entwurf.service_period_end == date(2026, 2, 28)
    assert entwurf.notes is None
    assert entwurf.auftragsschluessel == SCHLUESSEL
    assert entwurf.auftragsschluessel_offen == SCHLUESSEL
    assert entwurf.uebergabe_beleg_id == "11111111-2222-4333-8444-555555555556"
    assert entwurf.uebergabe_beleg_sha256 == "2" * 64


def test_die_positionen_folgen_nr_und_das_vorzeichen_bleibt(pg_session):
    """Menge 1, Einheit wie bei der 389 (Pauschal), Einzelpreis = netto,
    negative Positionen erlaubt (Festlegung 11). Die Reihenfolge entspricht
    nr, nicht der Reihenfolge im JSON."""
    _kunde(pg_session)
    nutzlast = rechnungsauftrag()
    nutzlast["positionen"] = [
        nutzlast["positionen"][1],   # nr 2 zuerst in der Datei
        nutzlast["positionen"][0],
    ]

    entwurf = entwurf_anlegen(pg_session, _urteil(nutzlast))
    pg_session.flush()

    positionen = sorted(entwurf.items, key=lambda p: p.position)
    assert [p.position for p in positionen] == [1, 2]
    assert [p.gruppe for p in positionen] == ["Gruppe A", "Gruppe B"]
    assert [p.unit_price for p in positionen] == [Decimal("174.44"), Decimal("-3.10")]
    assert all(p.unit == "Pauschal" for p in positionen)
    assert all(p.quantity == Decimal("1") for p in positionen)
    assert all(p.tax_rate == Decimal("0") for p in positionen)
    assert all(p.tax_amount == Decimal("0") for p in positionen)
    assert entwurf.net_total == Decimal("171.34")
    assert entwurf.tax_total == Decimal("0.00")
    assert entwurf.gross_total == Decimal("171.34")


def test_kopf_und_fusstext_sind_kopiert_und_der_monat_ersetzt(pg_session):
    """Festlegung 15: kopiert, nicht gelesen; {leistungsmonat} ist beim
    Speichern schon ersetzt - ein gespeicherter Entwurf, in dem der
    Platzhalter wie Text stünde, erreichte unbeanstandet den Kunden."""
    _kunde(pg_session)

    entwurf = entwurf_anlegen(pg_session, _urteil())
    pg_session.flush()

    assert entwurf.kopftext == (
        "Vereinbarung vom 1. Januar 2026, Abrechnungsmonat 02/2026."
    )
    assert entwurf.fusstext == "Der Abrechnungsbericht ist die Einzelaufstellung."
    assert entwurf.document_language == "de"


def test_zahlungshinweis_des_kunden_ersetzt_die_faelligkeit(pg_session):
    """Entscheidung 4: Ein Kunde, der nach eigenem Takt zahlt, bekommt keinen
    Termin (BT-9 entfaellt), sondern seinen Hinweis in den Bedingungen."""
    _kunde(pg_session)

    entwurf = entwurf_anlegen(pg_session, _urteil())
    pg_session.flush()

    assert entwurf.due_date is None
    assert entwurf.payment_terms == (
        "Zahlung folgt dem Auszahlungsbericht der Plattform."
    )


def test_ohne_zahlungshinweis_entsteht_entwurf_ohne_faelligkeit(pg_session):
    """#206: Ohne Kundenvorgabe keine erfundene Frist; der Entwurf bleibt offen."""
    _kunde(pg_session, zahlungshinweis=None)

    entwurf = entwurf_anlegen(pg_session, _urteil())
    pg_session.flush()

    assert entwurf.status == "draft"
    assert entwurf.payment_terms is None
    assert entwurf.issue_date == date(2026, 9, 3)
    assert entwurf.due_date is None


def test_der_beleg_wird_gemerkt(pg_session):
    _kunde(pg_session)

    entwurf_anlegen(pg_session, _urteil(), dateiname="auftrag.json")
    pg_session.flush()

    zeile = pg_session.query(UebergabeEingang).one()
    assert zeile.beleg_sha256 == "2" * 64
    assert zeile.dateiname == "auftrag.json"


# --- Ohne Steuervorgabe entsteht nichts ---------------------------------------


@pytest.mark.parametrize("aenderung", [
    dict(auftrag_steuer=None),
    dict(vat_id=None),
    dict(vat_id="  "),
])
def test_ohne_steuervorgabe_entsteht_kein_entwurf(pg_session, aenderung):
    """Festlegung 13: AE verlangt die USt-IdNr. des Kunden; ohne Vorgabe am
    Kunden wird die Steuer nicht geraten. Die Meldung nennt BEIDES, denn der
    Grund kann an jedem der beiden Felder liegen."""
    _kunde(pg_session, **aenderung)

    with pytest.raises(WirkungFehler) as befund:
        entwurf_anlegen(pg_session, _urteil())

    assert str(befund.value) == (
        "Am Kunden fehlt die Steuervorgabe für Aufträge (AE) bzw. die USt-IdNr."
    )
    pg_session.rollback()
    assert pg_session.query(Invoice).count() == 0
    assert pg_session.query(UebergabeEingang).count() == 0


def test_ein_abgelehnter_auftrag_wirkt_nicht(pg_session):
    _kunde(pg_session)

    with pytest.raises(WirkungFehler):
        entwurf_anlegen(pg_session, _urteil(
            angenommen=False,
            feststellungen=(Feststellung("SIGNATUR_UNGUELTIG", "$"),),
        ))

    assert pg_session.query(Invoice).count() == 0
    assert pg_session.query(UebergabeEingang).count() == 0


def test_ein_schon_verarbeiteter_auftrag_wirkt_kein_zweites_mal(pg_session):
    _kunde(pg_session)

    with pytest.raises(BelegSchonVerarbeitet):
        entwurf_anlegen(pg_session, _urteil(bereits_verarbeitet=True))

    assert pg_session.query(Invoice).count() == 0


# --- Ausstellungsdatum erst beim Finalisieren (Festlegung 14) -----------------


def test_finalisieren_setzt_das_ausstellungsdatum_auf_heute(pg_session):
    """Der Entwurf traegt das Datum nur vorlaeufig (Kalendertag von
    erzeugt_am); gestellt wird die Rechnung am Tag des Finalisierens. Das
    Faelligkeitsdatum wandert um denselben Abstand mit, die Archivfrist
    haengt am neuen Tag. Ein Termin am Entwurf ist hier gesetzt, weil #206
    ohne Kundenvorgabe keinen Termin mehr erfindet."""
    _kunde(pg_session)
    entwurf = entwurf_anlegen(pg_session, _urteil())
    entwurf.due_date = entwurf.issue_date + timedelta(days=14)
    pg_session.commit()
    vorher = entwurf.issue_date

    from tests.helpers.finalize_pipeline import (
        cleanup,
        finalize_with_fake_pipeline,
    )
    try:
        antwort = finalize_with_fake_pipeline(pg_session, entwurf.id)
        assert antwort.status_code == 303, antwort.text
    finally:
        cleanup(entwurf.invoice_number)

    pg_session.expire_all()
    gestellt = pg_session.get(Invoice, entwurf.id)
    # #227: Rechnungsauftrag wird beim Finalisieren als bezahlt markiert.
    assert gestellt.status == "paid"
    assert gestellt.issue_date == heute()
    assert gestellt.issue_date != vorher
    assert gestellt.due_date == heute() + timedelta(days=14)
    assert gestellt.archive_until == berechne_archive_until(heute())


def test_finalisieren_haelt_den_zahlungshinweis_ohne_termin(pg_session):
    """Ohne Faelligkeitsdatum gibt es keinen Abstand zu verschieben: Der
    Zahlungshinweis regelt die Zahlung, das Ausstellungsdatum kommt trotzdem
    auf heute (die Frist des § 14a haengt daran)."""
    _kunde(pg_session)
    entwurf = entwurf_anlegen(pg_session, _urteil())
    pg_session.commit()

    from tests.helpers.finalize_pipeline import (
        cleanup,
        finalize_with_fake_pipeline,
    )
    try:
        antwort = finalize_with_fake_pipeline(pg_session, entwurf.id)
        assert antwort.status_code == 303, antwort.text
    finally:
        cleanup(entwurf.invoice_number)

    pg_session.expire_all()
    gestellt = pg_session.get(Invoice, entwurf.id)
    assert gestellt.issue_date == heute()
    assert gestellt.due_date is None


# --- Warnung § 14a: Ausstellungsfrist -----------------------------------------


def _warnungen(invoice):
    _, warnungen = validate_invoice(invoice, _company(vat_id="DE123456789"))
    return {w.code for w in warnungen}


def test_ausstellung_nach_dem_15_des_folgemonats_warnt():
    """§ 14a Abs. 1 Satz 2 UStG: Reverse Charge ist bis zum 15. des Monats
    nach der Leistung zu stellen. Eine Warnung, kein Fehler: Die Frist zu
    versaeumen macht die Rechnung nicht ungueltig."""
    inv = _invoice(
        tax_category="AE",
        issue_date=date(2026, 3, 16),
        service_period_start=date(2026, 2, 1),
        service_period_end=date(2026, 2, 28),
    )

    assert "AUSSTELLUNGSFRIST_14A" in _warnungen(inv)


def test_der_15_des_folgemonats_selbst_ist_noch_fristgerecht():
    inv = _invoice(
        tax_category="AE",
        issue_date=date(2026, 3, 15),
        service_period_start=date(2026, 2, 1),
        service_period_end=date(2026, 2, 28),
    )

    assert "AUSSTELLUNGSFRIST_14A" not in _warnungen(inv)


def test_die_frist_wechselt_im_dezember_auf_den_januar():
    inv = _invoice(
        tax_category="AE",
        issue_date=date(2027, 1, 16),
        service_period_start=date(2026, 12, 1),
        service_period_end=date(2026, 12, 31),
    )

    assert "AUSSTELLUNGSFRIST_14A" in _warnungen(inv)


def test_die_frist_gilt_nur_fuer_reverse_charge():
    """Bei anderen Kategorien bleibt die 14a-Frist stumm: § 14a betrifft
    die Steuerschuldnerschaft des Leistungsempfaengers, nicht die 19 %."""
    inv = _invoice(
        tax_category="S",
        issue_date=date(2026, 3, 16),
        service_period_start=date(2026, 2, 1),
        service_period_end=date(2026, 2, 28),
    )

    assert "AUSSTELLUNGSFRIST_14A" not in _warnungen(inv)


def test_ohne_leistungszeitraumende_gibt_es_keine_frist():
    inv = _invoice(tax_category="AE", issue_date=date(2026, 3, 16))

    assert "AUSSTELLUNGSFRIST_14A" not in _warnungen(inv)


# --- Bearbeiten: die gebundenen Felder bleiben die des Auftrags ---------------


def _formular(entwurf, **aenderungen):
    daten = {
        "customer_id": str(entwurf.customer_id),
        "issue_date": entwurf.issue_date.isoformat(),
        "due_date": "",
        "service_period_start": "2027-01-01",
        "service_period_end": "2027-01-31",
        "tax_category": "S",
        "payment_terms": "Umgeschriebener Zahlungshinweis.",
        "buyer_reference": "",
        "notes": "",
        "kopftext": "",
        "fusstext": "",
        "items_json": json.dumps([
            {"description": "Umgeschrieben", "unit": "Stück", "quantity": "5",
             "unit_price": "99.99", "tax_rate": "0"},
            {"description": "Auch umgeschrieben", "unit": "Stück",
             "quantity": "5", "unit_price": "-99.99", "tax_rate": "0"},
        ]),
    }
    daten.update(aenderungen)
    return daten


def test_bearbeiten_aendert_die_gebundenen_felder_nicht(client, pg_session):
    """Festlegung 13 bindet die Steuerkategorie am Auftragsentwurf; Betraege,
    Beteiligter, Zeitraum und Gruppen bindet belegsperre.gilt seit 4a/3. Das
    Formular mag mitsenden, was will - der Bestand gewinnt."""
    _kunde(pg_session)
    entwurf = entwurf_anlegen(pg_session, _urteil())
    pg_session.commit()

    antwort = client.post(f"/invoices/{entwurf.id}/bearbeiten",
                          data=_formular(entwurf))

    assert antwort.status_code == 303, antwort.text
    pg_session.expire_all()
    entwurf = pg_session.get(Invoice, entwurf.id)
    assert entwurf.tax_category == "AE"
    assert entwurf.service_period_start == date(2026, 2, 1)
    assert entwurf.service_period_end == date(2026, 2, 28)
    positionen = sorted(entwurf.items, key=lambda p: p.position)
    assert [p.gruppe for p in positionen] == ["Gruppe A", "Gruppe B"]
    assert [p.unit_price for p in positionen] == [Decimal("174.44"), Decimal("-3.10")]
    assert all(p.quantity == Decimal("1") for p in positionen)
    assert all(p.unit == "Pauschal" for p in positionen)
    assert entwurf.net_total == Decimal("171.34")
