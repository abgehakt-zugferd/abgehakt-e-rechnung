"""Aus einem angenommenen aufstellungsauftrag entsteht der Entwurf der
Abrechnungsaufstellung (§ 8b, Bauschritt 7b).

Wie bei den anderen Wirkungen: erst der Knopf schreibt, alles oder nichts,
committet der Aufrufer. Und das Gegenteil von § 8a: Am Kunden ist keine
Steuervorgabe zu pruefen, denn die Aufstellung ist keine Rechnung (§ 14
UStG) - der Kunde hier traegt bewusst KEINE (Festlegung 13 greift nicht).

Die Anlagen sind Nachweise: Erst wenn beide byte-gleich im eigenen Speicher
liegen, entstehen Zeilen (fail closed). Alles Erfundene kommt aus
helpers/uebergabe; der Speicher ist der Wegwerf-Speicher der Testumgebung.
"""

import hashlib
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.config import get_settings
from app.models.aufstellung import Aufstellung, AufstellungAnlage
from app.models.customer import Customer
from app.models.uebergabe_eingang import UebergabeEingang
from app.services.abrechnungsauftrag_wirkung import (
    BelegSchonVerarbeitet,
    WirkungFehler,
)
from app.services.aufstellungsauftrag_wirkung import entwurf_anlegen
from app.services.uebergabe_befund import Belegurteil, Feststellung
from app.services.uebergabe_eingang import RICHTUNG
from app.zeit import heute
from tests.helpers.uebergabe import (
    ANLAGE_ABRECHNUNGSBERICHT,
    ANLAGE_MEDIENTYP,
    ANLAGE_ZAHLUNGSBERICHT,
    PARTNER_A,
    anlage,
    aufstellungsauftrag,
    probe_anlagen,
)

ERZEUGT = datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)
SCHLUESSEL = "plattform:2026-02:kanal-b:x1"


def _kunde(pg_session, kennung=PARTNER_A):
    """Ein Kunde ganz ohne Steuervorgabe (kein auftrag_steuer, keine USt-IdNr.)
    - die Aufstellung ist keine Rechnung, dazu ist am Kunden nichts zu
    pruefen. Waere das Gegenteil verlangt, muesste dieser Kunde scheitern."""
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Beispiel Services LLC",
        address_line1="Way 1", zip_code="10001", city="New York", country="US",
    )
    kunde.id = uuid.UUID(str(kennung))
    pg_session.add(kunde)
    pg_session.flush()
    return kunde


def _urteil(nutzlast=None, **aenderungen):
    felder = dict(
        beleg_sha256="3" * 64,
        beleg_id="11111111-2222-4333-8444-555555555566",
        angenommen=True,
        absender="tantiemen-app",
        nutzlast_art="aufstellungsauftrag",
        erzeugt_am=ERZEUGT,
        nutzlast=aufstellungsauftrag() if nutzlast is None else nutzlast,
    )
    felder.update(aenderungen)
    return Belegurteil(**felder)


def _anlagen_ordner():
    """Der Anlagenordner des EIGENEN Speichers - wohin die Wirkung kopiert."""
    return get_settings().storage_path / "uebergaben" / RICHTUNG / "anlagen"


def _entwurf(pg_session, nutzlast=None, bestand=None, **aenderungen):
    if bestand is None:
        bestand = probe_anlagen()
    return entwurf_anlegen(
        pg_session, _urteil(nutzlast, **aenderungen),
        anlagen_bytes=bestand.get,
    )


def test_aus_dem_auftrag_wird_der_entwurf(pg_session):
    _kunde(pg_session)

    entwurf = entwurf_anlegen(
        pg_session, _urteil(), anlagen_bytes=probe_anlagen().get,
        dateiname="aufstellung.json",
    )
    pg_session.flush()

    assert entwurf.status == "draft"
    # Der eigene Kreis (Festlegung 18): Praefix AA-, eigener Zaehler.
    assert entwurf.nummer == f"AA-{heute().year}-001"
    assert entwurf.customer_id == uuid.UUID(PARTNER_A)
    assert entwurf.leistung_von == date(2026, 2, 1)
    assert entwurf.leistung_bis == date(2026, 2, 28)
    assert entwurf.zahlungsnummer == "100000000000001"
    assert entwurf.zahlungsdatum == date(2026, 4, 29)
    assert entwurf.waehrung == "USD"
    assert entwurf.brutto == Decimal("6.92")
    assert entwurf.quellensteuer == Decimal("2.08")
    assert entwurf.netto == Decimal("4.84")
    assert entwurf.kurs == Decimal("0.8533")
    assert entwurf.zahlbetrag_eur == Decimal("4.13")
    assert entwurf.auftragsschluessel == SCHLUESSEL
    assert entwurf.auftragsschluessel_offen == SCHLUESSEL
    assert entwurf.uebergabe_beleg_id == "11111111-2222-4333-8444-555555555566"
    assert entwurf.uebergabe_beleg_sha256 == "3" * 64
    # Noch nicht gestellt: Das Ausstellungsdatum setzt erst der Mensch
    # (aufstellung_guard), ein Entwurf ohne Datum ist keiner von heute.
    assert entwurf.ausstellungsdatum is None


def test_bei_eur_gibt_es_keine_umrechnung(pg_session):
    """Festlegung 21: Abgehakt rechnet keinen Wert in Euro um - bei EUR
    bleiben kurs und zahlbetrag_eur leer (der Leser lehnt das Feld ab)."""
    _kunde(pg_session)
    nutzlast = aufstellungsauftrag(waehrung="EUR")
    del nutzlast["umrechnung"]

    entwurf = _entwurf(pg_session, nutzlast)
    pg_session.flush()

    assert entwurf.kurs is None
    assert entwurf.zahlbetrag_eur is None


def test_zwei_anlagenzeilen_aus_dem_auftrag(pg_session):
    _kunde(pg_session)

    entwurf = _entwurf(pg_session)
    pg_session.flush()

    zeilen = sorted(entwurf.anlagen, key=lambda zeile: zeile.quelle)
    assert [zeile.quelle for zeile in zeilen] == ["abrechnungsbericht", "zahlungsbericht"]
    assert [zeile.dateiname for zeile in zeilen] == ["bericht.xlsx", "zahlung.xlsx"]
    assert [zeile.sha256 for zeile in zeilen] == [
        hashlib.sha256(ANLAGE_ABRECHNUNGSBERICHT).hexdigest(),
        hashlib.sha256(ANLAGE_ZAHLUNGSBERICHT).hexdigest(),
    ]
    assert [zeile.groesse for zeile in zeilen] == [
        len(ANLAGE_ABRECHNUNGSBERICHT), len(ANLAGE_ZAHLUNGSBERICHT),
    ]
    assert all(zeile.medientyp == ANLAGE_MEDIENTYP for zeile in zeilen)


def test_beide_anlagen_liegen_byte_gleich_im_eigenen_speicher(pg_session):
    _kunde(pg_session)

    _entwurf(pg_session)
    pg_session.flush()

    for bytes_ in (ANLAGE_ABRECHNUNGSBERICHT, ANLAGE_ZAHLUNGSBERICHT):
        kopie = _anlagen_ordner() / f"{hashlib.sha256(bytes_).hexdigest()}.xlsx"
        assert kopie.read_bytes() == bytes_
        assert hashlib.sha256(kopie.read_bytes()).hexdigest() == \
            hashlib.sha256(bytes_).hexdigest()


def test_eine_geteilte_anlage_wird_einmal_abgelegt(pg_session):
    """Zwei Aufstellungen koennen dieselbe Anlage nennen (derselbe Bericht,
    zweimal gerechnet): Der Platz ist der Hash, derselbe Hash ist derselbe
    Platz - die zweite Aufstellung findet die Kopie vor und schreibt nichts."""
    _kunde(pg_session)
    andere = b"anderer Zahlungsbericht, erfundene Bytes ohne xlsx."
    bestand = probe_anlagen()
    bestand[hashlib.sha256(andere).hexdigest()] = andere
    zweite = aufstellungsauftrag(
        auftragsschluessel="plattform:2026-02:kanal-b:x2",
        anlagen=[
            anlage("abrechnungsbericht", "bericht.xlsx", ANLAGE_ABRECHNUNGSBERICHT),
            anlage("zahlungsbericht", "zahlung.xlsx", andere),
        ],
    )

    _entwurf(pg_session)
    _entwurf(
        pg_session, zweite, bestand=bestand,
        beleg_sha256="4" * 64, beleg_id="11111111-2222-4333-8444-555555555567",
    )
    pg_session.flush()

    geteilt = f"{hashlib.sha256(ANLAGE_ABRECHNUNGSBERICHT).hexdigest()}.xlsx"
    assert [p.name for p in _anlagen_ordner().glob(geteilt)] == [geteilt]
    # Zwei Aufstellungen, vier Zeilen - aber nur drei Dateien: Die geteilte
    # Anlage liegt einmal, jede eigene je einmal.
    assert {p.name for p in _anlagen_ordner().iterdir()} == {
        f"{hashlib.sha256(bytes_).hexdigest()}.xlsx"
        for bytes_ in (ANLAGE_ABRECHNUNGSBERICHT, ANLAGE_ZAHLUNGSBERICHT, andere)
    }
    assert pg_session.query(AufstellungAnlage).count() == 4


def test_fehlt_eine_anlage_entsteht_kein_entwurf(pg_session):
    _kunde(pg_session)

    with pytest.raises(WirkungFehler) as befund:
        _entwurf(pg_session, bestand={})

    assert "fehlt" in str(befund.value)
    pg_session.rollback()
    assert pg_session.query(Aufstellung).count() == 0
    assert pg_session.query(AufstellungAnlage).count() == 0
    assert pg_session.query(UebergabeEingang).count() == 0


def test_stimmt_die_anlage_nicht_mit_ihrem_hash_ueberein_entsteht_nichts(pg_session):
    """Die Wirkung liest die Anlage selbst noch einmal: Passt die geschriebene
    Kopie nicht zum Hash des Eintrags, ist das KopieFehler und damit
    WirkungFehler - der Eintrag waere sonst eine Behauptung ohne Beweis."""
    _kunde(pg_session)
    wahr = b"die echte Anlage, erfundene Bytes ohne xlsx."
    nutzlast = aufstellungsauftrag(anlagen=[
        anlage("abrechnungsbericht", "bericht.xlsx", wahr),
        anlage("zahlungsbericht", "zahlung.xlsx", ANLAGE_ZAHLUNGSBERICHT),
    ])
    bestand = {hashlib.sha256(wahr).hexdigest(): b"nicht die Anlage"}

    with pytest.raises(WirkungFehler) as befund:
        _entwurf(pg_session, nutzlast, bestand=bestand)

    assert "ueberein" in str(befund.value)
    pg_session.rollback()
    assert pg_session.query(Aufstellung).count() == 0
    assert not (_anlagen_ordner() / f"{hashlib.sha256(wahr).hexdigest()}.xlsx").exists()


def test_scheitert_die_kopie_entsteht_kein_entwurf(pg_session):
    """Fail closed: Ohne schreibbaren eigenen Speicher entsteht kein Entwurf
    - eine Aufstellung, die ihre Anlagen nur im Ordner eines anderen haette,
    waere Aufbewahrung auf Verlaub des Absenderordners (§ 12)."""
    _kunde(pg_session)
    frisch = b"frische erfundene Anlage, die noch nirgends liegt."
    nutzlast = aufstellungsauftrag(anlagen=[
        anlage("abrechnungsbericht", "bericht.xlsx", frisch),
        anlage("zahlungsbericht", "zahlung.xlsx", ANLAGE_ZAHLUNGSBERICHT),
    ])
    bestand = probe_anlagen()
    bestand[hashlib.sha256(frisch).hexdigest()] = frisch
    _anlagen_ordner().mkdir(parents=True, exist_ok=True)
    _anlagen_ordner().chmod(0o500)

    try:
        with pytest.raises(WirkungFehler):
            _entwurf(pg_session, nutzlast, bestand=bestand)
    finally:
        _anlagen_ordner().chmod(0o700)

    pg_session.rollback()
    assert pg_session.query(Aufstellung).count() == 0
    assert pg_session.query(AufstellungAnlage).count() == 0
    assert pg_session.query(UebergabeEingang).count() == 0


def test_der_beleg_wird_gemerkt(pg_session):
    _kunde(pg_session)

    entwurf_anlegen(
        pg_session, _urteil(), anlagen_bytes=probe_anlagen().get,
        dateiname="aufstellung.json",
    )
    pg_session.flush()

    zeile = pg_session.query(UebergabeEingang).one()
    assert zeile.beleg_sha256 == "3" * 64
    assert zeile.nutzlast_art == "aufstellungsauftrag"
    assert zeile.dateiname == "aufstellung.json"


def test_ein_abgelehnter_auftrag_wirkt_nicht(pg_session):
    _kunde(pg_session)

    with pytest.raises(WirkungFehler):
        _entwurf(
            pg_session,
            angenommen=False,
            feststellungen=(Feststellung("SIGNATUR_UNGUELTIG", "$"),),
        )

    pg_session.rollback()
    assert pg_session.query(Aufstellung).count() == 0


def test_ein_schon_verarbeiteter_auftrag_wirkt_kein_zweites_mal(pg_session):
    _kunde(pg_session)

    with pytest.raises(BelegSchonVerarbeitet):
        _entwurf(pg_session, bereits_verarbeitet=True)

    assert pg_session.query(Aufstellung).count() == 0
