"""Das Verarbeitungsgedaechtnis (abgehakt#22, § 11) und die eigene Kopie (§ 12).

Gemerkt wird NUR, was angenommen wurde. Ein abgelehnter Beleg wird nicht
gemerkt und darf erneut vorgelegt werden: ein mangels abgelegtem Schluessel
abgelehnter Beleg muss durchgehen, sobald der Schluessel liegt. Wer
"verarbeitet" weiter fasst, friert die erste Ablehnung ein und macht einen
behebbaren Fehler unbehebbar.

Angenommen wird ein Beleg erst mit seiner Aufbewahrungskopie: § 12 verlangt
unveraenderte Aufbewahrung auch beim EMPFAENGER, acht Jahre.
"""

import hashlib
import io
import os
import time
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.config import get_settings
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.uebergabe_eingang import UebergabeEingang
from app.services.gobd_export import build_gobd_export
from app.services.uebergabe_befund import Belegurteil, Feststellung
from app.services.uebergabe_eingang import (
    DatenbankLage,
    KopieFehler,
    kopie_aufbewahren,
    merken,
)

ABSENDER = "tantiemen-app"
ZEIT = datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)
RICHTUNG = "tantiemen-app-nach-abgehakt"


@pytest.fixture
def speicher(tmp_path, monkeypatch):
    """Ein Wegwerf-Speicher je Test: die Kopien duerfen nie ins Speicherverzeichnis
    der Sitzung gelangen, sonst faerben Tests aufeinander ein."""
    monkeypatch.setattr(get_settings(), "storage_path", tmp_path)
    return tmp_path


def _urteil(kennung="a" * 36, sha="1" * 64, zeit=ZEIT, angenommen=True):
    return Belegurteil(
        beleg_sha256=sha, beleg_id=kennung, angenommen=angenommen,
        absender=ABSENDER, nutzlast_art="abrechnungsauftrag", erzeugt_am=zeit,
    )


def _kunde(pg_session, kennung=None, geloescht=False):
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Autorin A",
        address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE",
        deleted_at=datetime.now(timezone.utc) if geloescht else None,
    )
    if kennung:
        kunde.id = kennung
    pg_session.add(kunde)
    pg_session.flush()
    return kunde


def test_ein_angenommener_beleg_wird_gemerkt(pg_session):
    merken(pg_session, _urteil(), dateiname="auftrag-2026-Q2.json")
    pg_session.flush()

    zeile = pg_session.query(UebergabeEingang).one()
    assert zeile.beleg_id == "a" * 36
    assert zeile.beleg_sha256 == "1" * 64
    assert zeile.absender == ABSENDER
    assert zeile.dateiname == "auftrag-2026-Q2.json"
    assert zeile.erzeugt_am == ZEIT


def test_ein_abgelehnter_beleg_wird_nicht_gemerkt(pg_session):
    urteil = Belegurteil(
        beleg_sha256="2" * 64, beleg_id="b" * 36, angenommen=False,
        feststellungen=(Feststellung("SIGNATUR_UNGUELTIG", "$.signatur.wert"),),
        absender=ABSENDER, nutzlast_art="abrechnungsauftrag", erzeugt_am=ZEIT,
    )

    with pytest.raises(ValueError):
        merken(pg_session, urteil, dateiname="kaputt.json")

    assert pg_session.query(UebergabeEingang).count() == 0


def test_derselbe_beleg_zweimal_merken_legt_keine_zweite_zeile_an(pg_session):
    merken(pg_session, _urteil(), dateiname="a.json")
    pg_session.flush()
    merken(pg_session, _urteil(), dateiname="a.json")
    pg_session.flush()

    assert pg_session.query(UebergabeEingang).count() == 1


def test_die_lage_findet_die_kennung_wieder(pg_session):
    merken(pg_session, _urteil(), dateiname="a.json")
    pg_session.flush()

    lage = DatenbankLage(pg_session)
    assert lage.sha_zu_beleg_id("a" * 36) == "1" * 64
    assert lage.sha_zu_beleg_id("c" * 36) is None


def test_die_lage_nennt_den_zuletzt_angenommenen(pg_session):
    merken(pg_session, _urteil(kennung="a" * 36, sha="1" * 64), dateiname="a.json")
    pg_session.flush()
    merken(
        pg_session,
        _urteil(kennung="b" * 36, sha="2" * 64, zeit=ZEIT + timedelta(hours=1)),
        dateiname="b.json",
    )
    pg_session.flush()

    hash_, zeit = DatenbankLage(pg_session).zuletzt_angenommen(ABSENDER)
    assert hash_ == "2" * 64
    assert zeit == ZEIT + timedelta(hours=1)


def test_ohne_vorgeschichte_kennt_die_lage_keinen_vorgaenger(pg_session):
    assert DatenbankLage(pg_session).zuletzt_angenommen(ABSENDER) is None


def test_die_lage_kennt_nur_den_eigenen_absender(pg_session):
    merken(pg_session, _urteil(), dateiname="a.json")
    pg_session.flush()

    assert DatenbankLage(pg_session).zuletzt_angenommen("feiyr-konto") is None


def test_partner_bekannt_ist_der_kundenstamm(pg_session):
    kunde = _kunde(pg_session)

    lage = DatenbankLage(pg_session)
    assert lage.partner_bekannt(str(kunde.id))
    assert not lage.partner_bekannt(str(uuid.uuid4()))


def test_ein_geloeschter_kunde_ist_kein_beteiligter(pg_session):
    kunde = _kunde(pg_session, geloescht=True)

    assert not DatenbankLage(pg_session).partner_bekannt(str(kunde.id))


def test_eine_partner_id_die_keine_uuid_ist(pg_session):
    """Kein Absturz, kein Anlegen: sie ist schlicht unbekannt."""
    assert not DatenbankLage(pg_session).partner_bekannt("nicht-mal-eine-uuid")


# --- Die Aufbewahrungskopie (§ 12: unveraendert, auch beim Empfaenger, acht Jahre) ---

def test_die_kopie_liegt_byte_gleich_unter_dem_hash_als_namen(speicher):
    roh = b'{"beleg": "probe"}'
    sha = hashlib.sha256(roh).hexdigest()

    ziel = kopie_aufbewahren(roh, sha, RICHTUNG)

    assert ziel == speicher / "uebergaben" / RICHTUNG / f"{sha}.json"
    assert ziel.read_bytes() == roh
    assert hashlib.sha256(ziel.read_bytes()).hexdigest() == sha


def test_zweimal_aufbewahren_aendert_am_bestand_nichts(speicher):
    roh = b'{"beleg": "probe"}'
    sha = hashlib.sha256(roh).hexdigest()
    ziel = kopie_aufbewahren(roh, sha, RICHTUNG)
    vorher = (ziel.read_bytes(), ziel.stat().st_mtime_ns)

    kopie_aufbewahren(roh, sha, RICHTUNG)

    assert (ziel.read_bytes(), ziel.stat().st_mtime_ns) == vorher
    assert [p.name for p in ziel.parent.iterdir()] == [ziel.name]


def test_ein_anderer_inhalt_unter_gleichem_namen_ist_ein_fehler(speicher):
    roh = b'{"beleg": "probe"}'
    sha = hashlib.sha256(roh).hexdigest()
    ziel = speicher / "uebergaben" / RICHTUNG / f"{sha}.json"
    ziel.parent.mkdir(parents=True)
    ziel.write_bytes(b"kein Beleg, sondern ein Fremdkoerper")

    with pytest.raises(KopieFehler):
        kopie_aufbewahren(roh, sha, RICHTUNG)

    # Der Bestand bleibt unangetastet: niemand korrigiert hier still vor.
    assert ziel.read_bytes() == b"kein Beleg, sondern ein Fremdkoerper"


def test_ein_nicht_beschreibbares_verzeichnis_ist_ein_fehler(speicher):
    ordner = speicher / "uebergaben"
    ordner.mkdir()
    ordner.chmod(0o500)

    try:
        with pytest.raises(KopieFehler):
            kopie_aufbewahren(b"{}", hashlib.sha256(b"{}").hexdigest(), RICHTUNG)
    finally:
        ordner.chmod(0o700)

    assert not (ordner / RICHTUNG).exists()


def test_der_z3_export_liefert_die_aufbewahrungskopien_mit(speicher):
    """Z3 ist Datenzugriff auf die aufbewahrungspflichtigen Unterlagen: ohne die
    Uebergabebelege waere der Export die Gutschrift ohne ihren Ursprungsbeleg."""
    roh = b'{"beleg": "probe"}'
    sha = hashlib.sha256(roh).hexdigest()
    kopie_aufbewahren(roh, sha, RICHTUNG)

    kunde = Customer(
        customer_number="K-2026-001", name="Export GmbH",
        address_line1="Weg 1", zip_code="12345", city="Musterstadt",
    )
    kunde.id = uuid.uuid4()
    rechnung = Invoice(
        invoice_number="RE-2026-001", customer_id=kunde.id,
        issue_date=date(2026, 3, 15), status="issued",
        net_total=Decimal("1000.00"), tax_total=Decimal("0.00"),
        gross_total=Decimal("1000.00"), currency="EUR", tax_category="S",
    )
    rechnung.customer = kunde
    rechnung.items = []

    # Die Zeile der Annahme (angenommen_am innerhalb des Export-Zeitraums)
    # waehlt der Router zu; hier reichen wir sie wie der Router es tut (#160).
    zeile = UebergabeEingang(
        beleg_id="a" * 36, beleg_sha256=sha, absender=ABSENDER,
        nutzlast_art="abrechnungsauftrag", erzeugt_am=ZEIT, angenommen_am=ZEIT,
    )

    daten = build_gobd_export(
        invoices=[rechnung], customers=[kunde], audit_rows=[],
        storage_path=speicher, date_from=date(2026, 1, 1), date_to=date(2026, 12, 31),
        uebergaben=[zeile],
    )
    zf = zipfile.ZipFile(io.BytesIO(daten))
    name = f"uebergaben/{RICHTUNG}/{sha}.json"

    assert name in zf.namelist()
    assert zf.read(name) == roh


# --- Verwaiste .kopie-Reste (Issue #160) ---

def _verwaise(speicher, name, stunden):
    ordner = speicher / "uebergaben" / RICHTUNG
    ordner.mkdir(parents=True)
    muell = ordner / name
    muell.write_bytes(b"halber Schreibvorgang, kein Beleg")
    vor_x_stunden = time.time() - stunden * 3600
    os.utime(muell, (vor_x_stunden, vor_x_stunden))
    return muell


def test_verwaiste_kopie_reste_werden_bei_naechstem_schreiben_entfernt(speicher):
    """#160: Ein harter Absturz mitten im Schreiben erreicht den finally-Block
    nicht, die halbe .kopie-Datei bliebe fuer immer unter storage/ liegen (die
    Anwendung loescht dort sonst nichts). Beim naechsten Schreiben in dasselbe
    Verzeichnis gehoert der Muell weg: Es sind keine Belege, sondern
    abgebrochene Schreibvorgaenge, ihr endgueltiger Name waere {sha}.json."""
    muell = _verwaise(speicher, ".kopie-abgestuerzt", stunden=4)
    roh = b'{"beleg": "neu"}'

    kopie_aufbewahren(roh, hashlib.sha256(roh).hexdigest(), RICHTUNG)

    assert not muell.exists()


def test_eine_frische_kopie_eines_laufenden_schreibvorgangs_bleibt_liegen(speicher):
    """#160: Die Stunde Zurueckhaltung schuetzt den Schreibvorgang, der gerade
    in demselben Verzeichnis laeuft: eine frische .kopie-Datei ist niemandes
    Muell, das Raeumen darf sie nicht anfassen."""
    laufend = _verwaise(speicher, ".kopie-laufend", stunden=0)
    roh = b'{"beleg": "neu"}'

    kopie_aufbewahren(roh, hashlib.sha256(roh).hexdigest(), RICHTUNG)

    assert laufend.exists()
