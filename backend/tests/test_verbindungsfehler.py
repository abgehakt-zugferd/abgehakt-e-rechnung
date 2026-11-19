"""Gemeinsames Hilfsmodul: nur echte Verbindungsfehler rechtfertigen einen Skip."""
from sqlalchemy.exc import OperationalError

from tests.helpers.verbindungsfehler import ist_verbindungsfehler


def test_verbindungsfehler_erkennen_ohne_echte_db():
    """Erfundene Ausnahmeobjekte: Verbindung ja, Rechte/fehlende DB nein."""
    assert ist_verbindungsfehler(OperationalError("x", {}, Exception("connection refused")))
    assert ist_verbindungsfehler(OperationalError("x", {}, Exception("could not connect to server")))
    assert not ist_verbindungsfehler(
        OperationalError("x", {}, Exception("password authentication failed")))
    assert not ist_verbindungsfehler(
        OperationalError("x", {}, Exception('database "x" does not exist')))
    assert not ist_verbindungsfehler(
        OperationalError("x", {}, Exception("permission denied to create database")))


def test_skip_stellen_nutzen_das_gemeinsame_hilfsmodul():
    """conftest, Migrationskette, Altzeilen und Owner-Bootstrap importieren denselben Helfer."""
    from pathlib import Path

    wurzel = Path(__file__).resolve().parent
    stellen = (
        wurzel / "conftest.py",
        wurzel / "test_migrationskette.py",
        wurzel / "test_migrationen_altzeilen.py",
        wurzel / "test_owner_role_bootstrap.py",
    )
    import_zeile = "from tests.helpers.verbindungsfehler import ist_verbindungsfehler"
    for pfad in stellen:
        text = pfad.read_text(encoding="utf-8")
        assert import_zeile in text, f"{pfad.name} importiert das Hilfsmodul nicht"
        assert "ist_verbindungsfehler(" in text, f"{pfad.name} ruft den Helfer nicht auf"


def test_migrations_bestand_fehlermeldung_unterscheidet_verbindungsfehler():
    """017/018/029: Verbindungsfehler behalten die alte Meldung, andere nennen den Fehler."""
    from pathlib import Path

    wurzel = Path(__file__).resolve().parent
    dateien = (
        (wurzel / "test_migration_017_bestand.py", "017"),
        (wurzel / "test_migration_018_bestand.py", "018"),
        (wurzel / "test_migration_029_bestand.py", "029"),
    )
    import_zeile = "from tests.helpers.verbindungsfehler import ist_verbindungsfehler"
    for pfad, nummer in dateien:
        text = pfad.read_text(encoding="utf-8")
        assert import_zeile in text, f"{pfad.name} importiert das Hilfsmodul nicht"
        assert "ist_verbindungsfehler(" in text, f"{pfad.name} unterscheidet nicht per Helfer"
        assert f"Migration {nummer} nicht gemessen:" in text, (
            f"{pfad.name} nennt bei Nicht-Verbindungsfehler nicht den echten Fehler"
        )
