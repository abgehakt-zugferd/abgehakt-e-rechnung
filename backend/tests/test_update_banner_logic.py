"""Anzeigelogik (#120) — reine Funktion, keine DB noetig.

Die Regeln stehen in Spec §4.6. Wichtigste: Der eskalierte Zustand ignoriert
update_dismissed_version, sonst liesse sich ein Gesetzeshinweis durch einen
frueheren Klick stummschalten.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.update_banner import REMINDER_DAYS, compute_banner

JETZT = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)


def cfg(**kw):
    grund = dict(
        update_last_checked_at=JETZT, update_last_attempt_at=JETZT,
        update_latest_version=None, update_severity=None, update_notice=None,
        update_url=None, update_mitteilung_text=None, update_mitteilung_url=None,
        update_dismissed_version=None, update_snoozed_until=None,
        update_consent_at=JETZT,
    )
    grund.update(kw)
    return SimpleNamespace(**grund)


def test_kein_update_und_frisch_geprueft_zeigt_nichts():
    assert compute_banner(cfg(), "1.0.0", JETZT) is None


def test_eskaliert_bei_security():
    b = compute_banner(cfg(update_latest_version="1.1.0", update_severity="security",
                           update_notice="Sicherheitslücke geschlossen."), "1.0.0", JETZT)
    assert b.kind == "escalated"
    assert b.dismissible is False


def test_eskaliert_bei_legal():
    b = compute_banner(cfg(update_latest_version="1.1.0", update_severity="legal"), "1.0.0", JETZT)
    assert b.kind == "escalated"
    assert b.dismissible is False


def test_eskaliert_ignoriert_weggeklickte_version():
    b = compute_banner(cfg(update_latest_version="1.1.0", update_severity="security",
                           update_dismissed_version="1.1.0"), "1.0.0", JETZT)
    assert b.kind == "escalated"


def test_normal_ist_wegklickbar():
    b = compute_banner(cfg(update_latest_version="1.1.0", update_severity="normal"), "1.0.0", JETZT)
    assert b.kind == "normal"
    assert b.dismissible is True


def test_weggeklickte_version_verschwindet():
    assert compute_banner(cfg(update_latest_version="1.1.0", update_severity="normal",
                              update_dismissed_version="1.1.0"), "1.0.0", JETZT) is None


def test_neuere_version_kommt_wieder():
    b = compute_banner(cfg(update_latest_version="1.2.0", update_severity="normal",
                           update_dismissed_version="1.1.0"), "1.0.0", JETZT)
    assert b.kind == "normal"


def test_erinnerung_nach_30_tagen():
    alt = JETZT - timedelta(days=REMINDER_DAYS + 1)
    b = compute_banner(cfg(update_last_checked_at=alt, update_last_attempt_at=alt), "1.0.0", JETZT)
    assert b.kind == "reminder"
    assert b.dismissible is True


def test_erinnerung_vor_30_tagen_nicht():
    kuerzlich = JETZT - timedelta(days=REMINDER_DAYS - 1)
    assert compute_banner(cfg(update_last_checked_at=kuerzlich,
                              update_last_attempt_at=kuerzlich), "1.0.0", JETZT) is None


def test_nie_geprueft_erinnert():
    b = compute_banner(cfg(update_last_checked_at=None, update_last_attempt_at=None),
                       "1.0.0", JETZT)
    assert b.kind == "reminder"


def test_schlummer_unterdrueckt_die_erinnerung():
    alt = JETZT - timedelta(days=REMINDER_DAYS + 1)
    assert compute_banner(cfg(update_last_checked_at=alt, update_last_attempt_at=alt,
                              update_snoozed_until=JETZT + timedelta(days=5)),
                          "1.0.0", JETZT) is None


def test_gescheiterter_versuch_beschuldigt_niemanden():
    alt = JETZT - timedelta(days=REMINDER_DAYS + 1)
    b = compute_banner(cfg(update_last_checked_at=alt, update_last_attempt_at=JETZT),
                       "1.0.0", JETZT)
    assert b.kind == "attempt_failed"
    assert b.dismissible is True


def test_gleiche_zeitstempel_sind_kein_fehlversuch():
    """Randfall: attempt == checked bedeutet, die Pruefung LIEF durch —
    das ist eine Erinnerung, kein 'war nicht moeglich'."""
    alt = JETZT - timedelta(days=REMINDER_DAYS + 1)
    b = compute_banner(cfg(update_last_checked_at=alt, update_last_attempt_at=alt),
                       "1.0.0", JETZT)
    assert b.kind == "reminder"


def test_unbekannte_einstufung_eskaliert_nicht():
    """Beide Regeln zusammen: Eine manipulierte Antwort darf ueber eine
    unverstandene Einstufung KEINEN dauerhaften Banner erzwingen."""
    b = compute_banner(cfg(update_latest_version="9.9.9",
                           update_severity="weltuntergang"), "1.0.0", JETZT)
    assert b.kind == "normal"
    assert b.dismissible is True


def test_dev_version_zeigt_nichts():
    assert compute_banner(cfg(update_latest_version="9.9.9", update_severity="security"),
                          "dev", JETZT) is None


def test_uhr_in_der_zukunft_erzeugt_keinen_hinweis():
    zukunft = JETZT + timedelta(days=400)
    assert compute_banner(cfg(update_last_checked_at=zukunft, update_last_attempt_at=zukunft),
                          "1.0.0", JETZT) is None


def test_pro_text_kommt_im_banner_gar_nicht_erst_vor():
    """Der Pro-Hinweis ist KEIN Feld des Banners (mehr): sonst kann er nur dort
    und nur so erscheinen wie der Banner — im eskalierten Fall also in einem
    nicht schliessbaren Kasten. Eigener Zustand: compute_mitteilung,
    eigene Tests in test_mitteilung.py."""
    b = compute_banner(cfg(update_latest_version="1.1.0", update_severity="security",
                           update_mitteilung_text="Pro empfängt E-Rechnungen.",
                           update_mitteilung_url="https://abgehakt.app/shop"), "1.0.0", JETZT)
    assert b.kind == "escalated"
    assert b.dismissible is False
    assert "Pro" not in str(b)
