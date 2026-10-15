"""Tests für die Plausibilitätsprüfung Steuerkategorie gegen Kundenland (#145).

Reine Funktion ohne Datenbank: jede Regel einzeln mit einem warnenden Fall
und einem Gegenfall, damit keine Regel einfach immer zuschlägt. Die Warntexte
werden vollständig verglichen, weil Nutzer sie lesen.
"""
import pytest

from app.services.steuerkategorie_land import (
    EU_MITGLIEDSTAATEN,
    kategorie_passt_zum_land,
)


WARNUNG_INLAND = (
    "Der Kunde sitzt in Deutschland. Reverse Charge (AE), "
    "innergemeinschaftliche Lieferung (K) und nicht im Inland steuerbar (O) "
    "passen in der Regel nicht zu einem Inlandskunden. "
    "Bitte die Steuerkategorie prüfen."
)
WARNUNG_EU = (
    "Der Kunde sitzt in einem anderen EU-Mitgliedstaat. "
    "Für sonstige Leistungen an Unternehmer dort gilt in der Regel "
    "Reverse Charge (Kategorie AE), nicht O. "
    "Bitte die Steuerkategorie prüfen."
)
WARNUNG_DRITTLAND = (
    "Der Kunde sitzt außerhalb der EU. Reverse Charge (AE) und "
    "innergemeinschaftliche Lieferung (K) gelten nur innerhalb der EU; "
    "für sonstige Leistungen an Unternehmer im Drittland ist in der Regel "
    "Kategorie O richtig. Bitte die Steuerkategorie prüfen."
)


def test_eu_mitgliedstaaten_sind_exakt_die_27():
    """Locking-Test: kein Land darf stillschweigend dazukommen oder verschwinden.
    Griechenland ist hier GR, nicht EL."""
    assert EU_MITGLIEDSTAATEN == frozenset({
        "AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR",
        "GR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT", "NL", "PL",
        "PT", "RO", "SE", "SI", "SK",
    })


# Regel 1: Inlandskunde mit AE, K oder O


@pytest.mark.parametrize("kategorie", ["AE", "K", "O"])
def test_inlandskunde_mit_ae_k_o_warnt(kategorie):
    assert kategorie_passt_zum_land(kategorie, "DE") == WARNUNG_INLAND


def test_inlandskunde_mit_s_warnt_nicht():
    assert kategorie_passt_zum_land("S", "DE") is None


# Regel 2: EU-Kunde (nicht DE) mit O


def test_eu_kunde_mit_o_warnt():
    assert kategorie_passt_zum_land("O", "AT") == WARNUNG_EU


def test_eu_kunde_mit_ae_warnt_nicht():
    assert kategorie_passt_zum_land("AE", "AT") is None


# Regel 3: Drittlandkunde mit AE oder K


@pytest.mark.parametrize("kategorie", ["AE", "K"])
def test_drittlandkunde_mit_ae_k_warnt(kategorie):
    assert kategorie_passt_zum_land(kategorie, "US") == WARNUNG_DRITTLAND


def test_drittlandkunde_mit_o_warnt_nicht():
    assert kategorie_passt_zum_land("O", "US") is None


# Fehlendes oder leeres Kundenland


@pytest.mark.parametrize("land", [None, "", "   "])
def test_fehlendes_land_liefert_nie_eine_warnung(land):
    """Ohne Land kann nichts plausibel geprüft werden: still schweigen."""
    assert kategorie_passt_zum_land("AE", land) is None


# S und E warnen nie


@pytest.mark.parametrize("land", ["DE", "AT", "US", None, ""])
@pytest.mark.parametrize("kategorie", ["S", "E"])
def test_s_und_e_warnen_nie(kategorie, land):
    """S (Inlandssteuer) und E (Kleinunternehmer) hängen nicht vom Land ab."""
    assert kategorie_passt_zum_land(kategorie, land) is None


# Normalisierung des Landes


@pytest.mark.parametrize("land", ["us", " US ", "Us"])
def test_gross_und_kleinschreibung_des_landes_ist_egal(land):
    assert kategorie_passt_zum_land("AE", land) == WARNUNG_DRITTLAND


# EU-Mitgliedschaft einzelner Länder


def test_gr_ist_eu_mitgliedstaat():
    """GR (nicht EL) ist EU: O warnt nach Regel 2, AE bleibt erlaubt."""
    assert kategorie_passt_zum_land("O", "GR") == WARNUNG_EU
    assert kategorie_passt_zum_land("AE", "GR") is None


@pytest.mark.parametrize("land", ["CH", "GB", "NO", "US"])
def test_ch_gb_no_us_sind_kein_eu_land(land):
    """Drittländer: AE warnt nach Regel 3, statt nach Regel 2 durchzurutschen."""
    assert kategorie_passt_zum_land("AE", land) == WARNUNG_DRITTLAND
