"""Empfängerlisten für die Kopie der Rechnungsmail (#58).

Reine Textverarbeitung, deshalb ohne Datenbank. Die Zerlegung entscheidet, wer
eine Rechnung zu sehen bekommt, und sie wird an drei Stellen gebraucht:
Kundenstamm, Einstellungen und Sende-Dialog. Sie liegt genau einmal im Code und
wird genau einmal hier geprüft; drei Kopien derselben Regel laufen auseinander.
"""
import pytest

from app.services import empfaenger


# ── zerlege ─────────────────────────────────────────────────────────────────

def test_zerlegt_an_komma_und_semikolon():
    assert empfaenger.zerlege("a@example.de, b@example.de;c@example.de") == [
        "a@example.de", "b@example.de", "c@example.de"]


@pytest.mark.parametrize("leer", [None, "", "   ", " , ; "])
def test_leere_eingabe_ergibt_leere_liste(leer):
    assert empfaenger.zerlege(leer) == []


def test_reihenfolge_bleibt_erhalten():
    """Die erste Adresse ist die des Hauptansprechpartners. Eine Sortierung
    würde diese Aussage stillschweigend wegwerfen."""
    assert empfaenger.zerlege("zweite@example.de, erste@example.de") == [
        "zweite@example.de", "erste@example.de"]


def test_dedupliziert_ohne_ruecksicht_auf_gross_und_kleinschreibung():
    """Sonst steht dieselbe Person zweimal im Kopf und bekommt die Rechnung
    doppelt zugestellt."""
    assert empfaenger.zerlege("Ines@example.de, ines@EXAMPLE.de") == ["Ines@example.de"]


def test_streicht_den_empfaenger_aus_der_kopie():
    """Wer im An-Feld steht, braucht keine Kopie an sich selbst."""
    assert empfaenger.zerlege(
        "kunde@example.de, ablage@example.de", ohne="KUNDE@example.de"
    ) == ["ablage@example.de"]


# ── pruefe ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("leer", [None, "", "   "])
def test_pruefe_erlaubt_leer(leer):
    """Keine Kopie ist ein zulässiger Wunsch, kein Eingabefehler."""
    assert empfaenger.pruefe(leer) is None


def test_pruefe_nimmt_gueltige_liste_an():
    assert empfaenger.pruefe("a@example.de; b@example.de") is None


def test_pruefe_meldet_ungueltige_adresse_beim_namen():
    meldung = empfaenger.pruefe("a@example.de, kein-at-zeichen")
    assert meldung is not None
    assert "kein-at-zeichen" in meldung


def test_pruefe_begrenzt_die_anzahl():
    zuviel = ", ".join(f"a{i}@example.de" for i in range(empfaenger.GRENZE_ANZAHL + 1))
    meldung = empfaenger.pruefe(zuviel)
    assert meldung is not None
    assert str(empfaenger.GRENZE_ANZAHL) in meldung


def test_pruefe_begrenzt_die_gesamtlaenge():
    """Die Spalte fasst 500 Zeichen. Ohne Prüfung bräche der Versand erst beim
    Schreiben des Protokolls ab, also nachdem die Mail draußen ist."""
    lang = ", ".join(f"{'x' * 100}{i}@example.de" for i in range(empfaenger.GRENZE_ANZAHL))
    meldung = empfaenger.pruefe(lang)
    assert meldung is not None
    assert str(empfaenger.GRENZE_LAENGE) in meldung


# ── formatiere ──────────────────────────────────────────────────────────────

def test_formatiere_verbindet_mit_komma_und_leerzeichen():
    assert empfaenger.formatiere(["a@example.de", "b@example.de"]) == \
        "a@example.de, b@example.de"


def test_formatiere_ohne_adressen_ergibt_leeren_text():
    assert empfaenger.formatiere([]) == ""
