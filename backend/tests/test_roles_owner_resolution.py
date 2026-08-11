"""
B2-Folgearbeit: die Owner-Rolle für `ALTER DEFAULT PRIVILEGES` darf NICHT hart
verdrahtet sein.

Hintergrund: der Bootstrap-User (den der Postgres-Container beim ersten Start
anlegt, OID 10) lässt sich von Postgres aus prinzipiell nicht demoten. Eigentümer
der Objekte ist deshalb eine eigene Rolle, `abgehakt_admin`. Läuft
`bootstrap_roles.py` gegen `FOR ROLE <Bootstrap-User>`, scheitert es mit
`permission denied` (der Owner ist nicht dessen Mitglied) — und der Entrypoint
(`set -e`) verhindert den App-Start.

Die Owner-Rolle ist per Definition die Rolle, mit der Alembic/Bootstrap verbinden,
also der User aus `DATABASE_URL` — nicht aus `BOOTSTRAP_DATABASE_URL`.
"""
import pytest

from app.db.roles import resolve_owner_role


@pytest.mark.parametrize(
    "url,expected",
    [
        ("postgresql://abgehakt_admin:pw@db:5432/abgehakt", "abgehakt_admin"),
        ("postgresql://abgehakt_db:pw@localhost:5432/abgehakt", "abgehakt_db"),
        ("postgresql+psycopg2://owner1:pw@db/abgehakt", "owner1"),
        # Sonderzeichen im Namen sind prozentkodiert und müssen dekodiert werden.
        ("postgresql://own%40er:pw@db:5432/abgehakt", "own@er"),
    ],
)
def test_resolve_owner_role_liest_user_aus_url(url, expected):
    assert resolve_owner_role(url) == expected


@pytest.mark.parametrize("url", ["", None, "postgresql://db:5432/abgehakt"])
def test_resolve_owner_role_faellt_auf_default_zurueck(url):
    """Kein User in der URL ⇒ dokumentierter Default, kein Crash."""
    assert resolve_owner_role(url) == "abgehakt_admin"


def test_resolve_owner_role_ignoriert_passwort_mit_at_zeichen():
    """Ein `@` im Passwort darf den Host nicht als User ausgeben."""
    assert resolve_owner_role("postgresql://abgehakt_admin:pw%40word@db:5432/abgehakt") == "abgehakt_admin"
