"""Das Beiblatt eines oeffentlichen Schluessels (§ 6, abgehakt#166).

Der Schluesselordner IST die Absenderliste, und das Beiblatt hat einen
geschlossenen Feldbestand. Ein unbekanntes Feld, ein fehlendes Pflichtfeld
oder eine falsche Zeitform machen den Schluessel unbrauchbar: Der Beleg wird
mit SCHLUESSEL_UNBEKANNT abgelehnt, nie mit einer Ausnahme - der Empfaenger
kann immer sagen, WELCHE Bytes er abgelehnt hat.
"""

import pytest

from app.services.uebergabe_befund import Empfangslage, beleg_beurteilen
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
    """Das einzige freie Feld: Notizen des Empfaengers am eigenen Bestand
    gehen den Feldbestand des Formats nichts an."""
    signieren, wurzel = schluessel
    beiblatt_ablegen(wurzel, beiblatt(notizen="Probeschluessel der Testinstanz"))

    urteil = _urteil(schluessel)

    assert urteil.angenommen, _codes(urteil)


def test_ein_gueltiges_beiblatt_nimmt_den_beleg_an(schluessel):
    """Die Gegenprobe: das Beiblatt, wie es `schluesselpaar` ablegt, nimmt
    den Beleg an - der geschlossene Bestand lehnt nur Abweichungen ab."""
    urteil = _urteil(schluessel)

    assert urteil.angenommen, _codes(urteil)
