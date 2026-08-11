"""Update-Spalten (#120) gegen echtes Postgres — Schema-Wirkung ist mit Mocks nicht beweisbar."""
from datetime import datetime, timedelta, timezone

from app.models.app_config import AppConfig

SPALTEN = [
    "update_last_checked_at", "update_last_attempt_at", "update_latest_version",
    "update_severity", "update_notice", "update_url", "update_mitteilung_text",
    "update_mitteilung_url", "update_dismissed_version", "update_snoozed_until",
    "update_consent_at",
]


def test_alle_spalten_existieren_und_sind_nullable(pg_session):
    tabelle = AppConfig.__table__
    for name in SPALTEN:
        assert name in tabelle.c, f"Spalte {name} fehlt"
        assert tabelle.c[name].nullable, f"{name} muss nullable sein (Bestand ohne Werte)"


def test_werte_ueberleben_den_commit(pg_session):
    jetzt = datetime.now(timezone.utc)
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if cfg is None:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
    cfg.update_last_checked_at = jetzt
    cfg.update_last_attempt_at = jetzt
    cfg.update_latest_version = "1.2.3"
    cfg.update_severity = "legal"
    cfg.update_notice = "Setzt die Sendepflicht um."
    cfg.update_url = "https://abgehakt.app/changelog"
    cfg.update_mitteilung_text = "Pro empfängt E-Rechnungen."
    cfg.update_mitteilung_url = "https://abgehakt.app/shop"
    cfg.update_dismissed_version = "1.2.2"
    cfg.update_snoozed_until = jetzt + timedelta(days=30)
    cfg.update_consent_at = jetzt
    pg_session.commit()
    # expunge_all statt expire_all: expire laesst NICHT-gemappte Attribute im
    # Identity-Map-Objekt stehen — der Test laese dann seine eigenen Python-
    # Attribute zurueck statt der Datenbank und waere auch ohne Spalten gruen.
    pg_session.expunge_all()

    frisch = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    assert frisch is not cfg, "Es muss frisch aus der Datenbank geladen worden sein"
    assert frisch.update_latest_version == "1.2.3"
    assert frisch.update_severity == "legal"
    assert frisch.update_consent_at is not None
    # timezone=True: der Wert kommt aware zurueck
    assert frisch.update_last_checked_at.tzinfo is not None
