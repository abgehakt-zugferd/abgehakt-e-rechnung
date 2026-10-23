"""Das Beiblatt eines oeffentlichen Schluessels (§ 6, abgehakt#166).

Der Schluesselordner IST die Absenderliste, und das Beiblatt hat einen
geschlossenen Feldbestand. Ein unbekanntes Feld, ein fehlendes Pflichtfeld
oder eine falsche Zeitform machen den Schluessel unbrauchbar: Der Beleg wird
mit SCHLUESSEL_UNBEKANNT abgelehnt, nie mit einer Ausnahme - der Empfaenger
kann immer sagen, WELCHE Bytes er abgelehnt hat.
"""

import json
from datetime import datetime, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.services.uebergabe_befund import Empfangslage, beleg_beurteilen
from app.services.uebergabe_schluessel import SchluesselUnbekannt, schluessel_laden
from tests.helpers.uebergabe import (
    ABSENDER_TANTIEMEN,
    PARTNER_A,
    SCHLUESSEL_ID,
    beiblatt,
    beiblatt_ablegen,
    beleg,
    schluesselpaar,
)


class Probelage(Empfangslage):
    """Nur die Partner des Probebelegs sind im Stamm - fuer die Gegenprobe."""

    def partner_bekannt(self, partner_id: str) -> bool:
        return partner_id == PARTNER_A


@pytest.fixture
def schluessel(tmp_path):
    """Ein Probeschluessel samt Beiblatt, wie er beim Empfaenger liegt."""
    return schluesselpaar(tmp_path)


def _urteil(schluessel) -> object:
    signieren, wurzel = schluessel
    return beleg_beurteilen(
        beleg(signieren), Probelage(), schluessel_wurzel=wurzel,
    )


def _codes(urteil) -> list:
    return [f.code for f in urteil.feststellungen]


def test_gueltigbis_statt_gueltig_bis_gilt_nicht_als_schluessel_ohne_ablauf(schluessel):
    """Der Tippfehler `gueltigbis` statt `gueltig_bis`: get() las das Feld
    nicht, der Ablauf im Beiblatt galt nicht - ein Schluessel, der nach dem
    eigenen Beiblatt abgelaufen war, blieb annehmbar."""
    signieren, wurzel = schluessel
    abgelaufen = {
        name: wert for name, wert in beiblatt().items() if name != "gueltig_bis"
    }
    abgelaufen["gueltigbis"] = "2026-09-02T00:00:00Z"  # vor erzeugt_am
    beiblatt_ablegen(wurzel, abgelaufen)

    urteil = _urteil(schluessel)

    assert not urteil.angenommen
    assert _codes(urteil) == ["SCHLUESSEL_UNBEKANNT"]


def test_gueltig_von_ohne_zone_macht_den_schluessel_unbrauchbar(schluessel):
    """fromisoformat parst eine naive Angabe anstandslos, und erst der
    Vergleich mit dem zeitzonenbewussten erzeugt_am warf einen TypeError -
    eine Ausnahme vor jeder Signaturpruefung. Seit #163 gilt die Form des
    § 2 auch hier, und seit #166 prueft sie das Beiblatt selbst."""
    signieren, wurzel = schluessel
    beiblatt_ablegen(wurzel, beiblatt(gueltig_von="2026-09-01T00:00:00"))

    urteil = _urteil(schluessel)

    assert not urteil.angenommen
    assert _codes(urteil) == ["SCHLUESSEL_UNBEKANNT"]


def test_ein_beiblatt_das_kein_json_ist_macht_den_schluessel_unbrauchbar(schluessel):
    """Vorher war json.JSONDecodeError eine Ausnahme, die den ganzen Beleg
    lahmlegte. Ein Beiblatt, das kein JSON ist, ist keins: Der Schluessel
    ist unbrauchbar, der Befund bleibt ein Befund."""
    signieren, wurzel = schluessel
    (wurzel / ABSENDER_TANTIEMEN / f"{SCHLUESSEL_ID}.json").write_text(
        "kein json", encoding="utf-8",
    )

    urteil = _urteil(schluessel)

    assert not urteil.angenommen
    assert _codes(urteil) == ["SCHLUESSEL_UNBEKANNT"]


def test_ein_fehlendes_pflichtfeld_macht_den_schluessel_unbrauchbar(schluessel):
    """`verfahren` steht im geschlossenen Feldbestand. Ohne die Pruefung war
    ein Beiblatt ohne es trotzdem stimmig genug, um angenommen zu werden."""
    signieren, wurzel = schluessel
    unvollstaendig = {
        name: wert for name, wert in beiblatt().items() if name != "verfahren"
    }
    beiblatt_ablegen(wurzel, unvollstaendig)

    urteil = _urteil(schluessel)

    assert not urteil.angenommen
    assert _codes(urteil) == ["SCHLUESSEL_UNBEKANNT"]


def test_notizen_duerfen_im_beiblatt_stehen(schluessel):
    """Das einzige freie Feld: Notizen sind ein Objekt; Schluessel darin
    heissen nicht wie Beiblattfelder und nicht probe/warum_probe/hinweis."""
    signieren, wurzel = schluessel
    beiblatt_ablegen(wurzel, beiblatt(notizen={
        "erlaeuterung": "Probeschluessel der Testinstanz",
    }))

    urteil = _urteil(schluessel)

    assert urteil.angenommen, _codes(urteil)


def test_notizen_als_zeichenkette_machen_den_schluessel_unbrauchbar(schluessel):
    signieren, wurzel = schluessel
    beiblatt_ablegen(wurzel, beiblatt(notizen="nur Text"))

    urteil = _urteil(schluessel)

    assert not urteil.angenommen
    assert _codes(urteil) == ["SCHLUESSEL_UNBEKANNT"]
    with pytest.raises(SchluesselUnbekannt, match="notizen muss ein Objekt"):
        schluessel_laden(ABSENDER_TANTIEMEN, SCHLUESSEL_ID, ERZEUGT_AM, wurzel=wurzel)


@pytest.mark.parametrize("schluesselname", [
    "gueltig_bis", "probe", "warum_probe", "hinweis", "notizen",
])
def test_notizen_schluessel_wie_feldnamen_machen_unbrauchbar(schluessel, schluesselname):
    signieren, wurzel = schluessel
    beiblatt_ablegen(wurzel, beiblatt(notizen={schluesselname: True}))

    urteil = _urteil(schluessel)

    assert not urteil.angenommen
    assert _codes(urteil) == ["SCHLUESSEL_UNBEKANNT"]
    with pytest.raises(SchluesselUnbekannt, match=schluesselname):
        schluessel_laden(ABSENDER_TANTIEMEN, SCHLUESSEL_ID, ERZEUGT_AM, wurzel=wurzel)


def test_ein_gueltiges_beiblatt_nimmt_den_beleg_an(schluessel):
    """Die Gegenprobe: das Beiblatt, wie es `schluesselpaar` ablegt, nimmt
    den Beleg an - der geschlossene Bestand lehnt nur Abweichungen ab."""
    urteil = _urteil(schluessel)

    assert urteil.angenommen, _codes(urteil)


# ── Der Pfad zum Schluessel entsteht aus Belegfeldern (#169). Absender und
# schluessel_id kommen aus der Datei, die jemand hingelegt hat; der Loader
# darf sie nicht ungeprueft in einen Pfad verwandeln.

ERZEUGT_AM = datetime(2026, 9, 3, 11, 0, tzinfo=timezone.utc)


def _kennung_ablegen(wurzel, absender, schluessel_id, privat):
    """Schluessel samt Beiblatt, wie er nach `absender`/`schluessel_id` heisst."""
    ordner = wurzel / absender
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / f"{schluessel_id}.pub").write_bytes(
        privat.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    )
    (ordner / f"{schluessel_id}.json").write_text(
        json.dumps({
            "schluessel_id": schluessel_id,
            "absender": absender,
            "verfahren": "Ed25519",
            "gueltig_von": "2026-09-01T00:00:00Z",
            "gueltig_bis": None,
        }),
        encoding="utf-8",
    )


@pytest.mark.parametrize("angabe", [
    "../angriff",      # aus dem Ordner hinaus
    "ein/zwei",        # eigener Unterordner
    ".versteckt",      # fuehrender Punkt
    "Grossbuchstabe",  # Kennungen sind kleinbuchstaben
    "",                # leer
    4711,              # gar keine Zeichenkette
])
def test_eine_angabe_die_keine_kennung_ist_hat_keinen_schluessel(schluessel, angabe):
    """Absender und schluessel_id bauen den Pfad; was nicht wie eine Kennung
    aussieht, fuehrt schon gar nicht erst zu einem Dateizugriff."""
    signieren, wurzel = schluessel
    with pytest.raises(SchluesselUnbekannt):
        schluessel_laden(angabe, SCHLUESSEL_ID, ERZEUGT_AM, wurzel=wurzel)
    with pytest.raises(SchluesselUnbekannt):
        schluessel_laden(ABSENDER_TANTIEMEN, angabe, ERZEUGT_AM, wurzel=wurzel)


def test_ein_beleg_der_den_schluesselordner_verlaesst_wird_nicht_gelesen(tmp_path):
    """Der Angriff geht ueber das Feld absender: "../angreifer" zeigt aus dem
    Schluesselordner hinaus. Seit der Kennungsform am Umschlag ist das schon
    WERT_UNBRAUCHBAR am Feld, bevor ein Pfad entsteht."""
    privat = Ed25519PrivateKey.generate()
    _kennung_ablegen(tmp_path, "angreifer", "angriff-2026-09", privat)
    (tmp_path / "ordner").mkdir()  # der Pfad "../angreifer" laesst sich nur
    # ueber einen VORHANDENEN Ordner hinaus aufloesen
    roh = beleg(
        privat.sign,
        absender="../angreifer",
        schluessel_id="angriff-2026-09",
    )

    urteil = beleg_beurteilen(
        roh, Probelage(), schluessel_wurzel=tmp_path / "ordner",
    )

    assert not urteil.angenommen
    assert _codes(urteil) == ["WERT_UNBRAUCHBAR"]
    assert urteil.feststellungen[0].pfad == "$.absender"


def test_ein_verweis_aus_dem_schluesselordner_hinaus_wird_nicht_gefolgt(schluessel, tmp_path):
    """Die Kennung besteht aus erlaubten Zeichen, aber hinter dem Namen liegt
    ein Verweis nach draussen. Erst das Aufgeloesten des Pfads entscheidet, ob
    er im Ordner bleibt - das Muster allein genuegt nicht."""
    signieren, wurzel = schluessel
    ordner = tmp_path / "ordner"
    ordner.mkdir()
    draussen = tmp_path / "draussen"
    draussen.mkdir()
    # Schluessel UND Beiblatt draussen: Nur wenn beides liegt, laedt der Loader
    # heute durch den Verweis hindurch - und genau das darf er nicht.
    (draussen / f"{SCHLUESSEL_ID}.pub").write_bytes(
        (wurzel / ABSENDER_TANTIEMEN / f"{SCHLUESSEL_ID}.pub").read_bytes()
    )
    (draussen / f"{SCHLUESSEL_ID}.json").write_text(
        (wurzel / ABSENDER_TANTIEMEN / f"{SCHLUESSEL_ID}.json").read_text()
    )
    (ordner / "verweis").symlink_to(draussen, target_is_directory=True)

    with pytest.raises(SchluesselUnbekannt):
        schluessel_laden("verweis", SCHLUESSEL_ID, ERZEUGT_AM, wurzel=ordner)

