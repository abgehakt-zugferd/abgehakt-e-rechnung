"""Das Formular darf für die eigene Ausgangsrechnung nicht § 13b UStG nennen (23.09.2026).

§ 13b UStG ist der Eingangsfall: der deutsche Leistungsempfänger schuldet die Steuer
für eine an ihn erbrachte Leistung. Auf der eigenen Rechnung an einen Unternehmer in
einem anderen EU-Staat tragen § 3a Abs. 2 UStG (der Leistungsort liegt bei ihm) und
Art. 196 MwStSystRL (er schuldet die Steuer).

Der Betrag ist in beiden Fällen derselbe, deshalb fällt es niemandem auf. Der Empfänger
bucht aber nach der Norm, die auf dem Beleg steht, und eine ausländische Buchhaltung
findet § 13b UStG in ihrem Recht nicht wieder.
"""
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.services.zugferd_xml import EXEMPTION_REASONS


def _formular_html(pg_session) -> str:
    app.dependency_overrides[get_db] = lambda: pg_session
    try:
        return TestClient(app, follow_redirects=False).get("/invoices/neu").text
    finally:
        app.dependency_overrides.pop(get_db, None)


def _ae_option(html: str) -> str:
    zeilen = [z for z in html.splitlines() if 'value="AE"' in z]
    assert len(zeilen) == 1, f"erwartet genau eine AE-Option, gefunden {len(zeilen)}"
    return zeilen[0]


def test_das_formular_nennt_bei_eu_b2b_den_richtigen_rechtsgrund(pg_session):
    option = _ae_option(_formular_html(pg_session))
    assert "13b" not in option
    assert "Art. 196" in option


def test_formularlabel_und_befreiungsgrund_nennen_dieselbe_norm(pg_session):
    """Sonst wählt der Nutzer nach einer Norm und der Beleg trägt eine andere."""
    option = _ae_option(_formular_html(pg_session))
    grund = EXEMPTION_REASONS["AE"]

    # "196" allein genuegt nicht: ein Text wie "Vermerk 196" traegt die Ziffer
    # ohne die Norm und liesse beide Zusicherungen gruen (gemessen 2026-09-23).
    assert "Art. 196" in option
    assert "Art. 196" in grund
    assert "13b" not in option
    assert "13b" not in grund
