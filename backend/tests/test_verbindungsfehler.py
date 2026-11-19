"""Gemeinsames Hilfsmodul: nur echte Verbindungsfehler rechtfertigen einen Skip."""
from sqlalchemy.exc import OperationalError

from tests.helpers.verbindungsfehler import ist_verbindungsfehler


class _PgOrig(Exception):
    """Erfundene psycopg-Ursache mit SQLSTATE, ohne echte DB."""

    def __init__(self, meldung: str, pgcode: str | None = None, sqlstate: str | None = None):
        super().__init__(meldung)
        if pgcode is not None:
            self.pgcode = pgcode
        if sqlstate is not None:
            self.sqlstate = sqlstate


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


def test_sqlstate_klasse_08_ist_verbindungsfehler_auch_ohne_passenden_text():
    """SQLSTATE-Klasse 08 schlägt den Meldungstext: Verbindung, egal was der Text sagt."""
    assert ist_verbindungsfehler(
        OperationalError("x", {}, _PgOrig("irgendwas anderes", pgcode="08006")))
    assert ist_verbindungsfehler(
        OperationalError("x", {}, _PgOrig("irgendwas anderes", sqlstate="08001")))


def test_sqlstate_andere_klasse_ist_kein_verbindungsfehler_trotz_passendem_text():
    """Andere SQLSTATE-Klasse verneint den Verbindungsfehler, auch wenn der Text passt."""
    assert not ist_verbindungsfehler(
        OperationalError("x", {}, _PgOrig("connection refused", pgcode="28P01")))
    assert not ist_verbindungsfehler(
        OperationalError("x", {}, _PgOrig("could not connect to server", sqlstate="42501")))


def test_ohne_sqlstate_bleibt_der_text_massgeblich():
    """Ohne SQLSTATE (Verbindung kam nie zustande) entscheidet weiterhin der Text."""
    assert ist_verbindungsfehler(
        OperationalError("x", {}, _PgOrig("connection refused")))
    assert not ist_verbindungsfehler(
        OperationalError("x", {}, _PgOrig("password authentication failed")))

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
