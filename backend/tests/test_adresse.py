"""Tests fuer Adresszeilen-Hilfen."""

from app.services.adresse import bereinige_adresszeile2


def test_adresszeile2_wird_entfernt_wenn_identisch_mit_name():
    assert bereinige_adresszeile2("ZEMP Golden Goose GmbH", "ZEMP Golden Goose GmbH") is None


def test_adresszeile2_bleibt_bei_echtem_zusatz():
    assert bereinige_adresszeile2("Firma GmbH", "Gebaeude B") == "Gebaeude B"


def test_adresszeile2_vergleicht_case_insensitive():
    assert bereinige_adresszeile2("Firma GmbH", "firma gmbh") is None
