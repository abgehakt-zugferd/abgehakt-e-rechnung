"""
Anzeigelogik des Update-Hinweises (#120). Rein: keine DB, kein HTTP, keine Uhr —
`now` wird hereingereicht, damit die Regeln testbar sind.

Regeln: Spec §4.6. Kein Verhaltensmerkmal stammt aus der Serverantwort.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.services.update_check import ESCALATED, is_newer_version

REMINDER_DAYS = 30
SNOOZE_DAYS = 30


@dataclass(frozen=True)
class Banner:
    kind: str            # escalated | normal | reminder | attempt_failed
    dismissible: bool
    text: str
    url: str = ""
    version: str = ""


@dataclass(frozen=True)
class Mitteilung:
    """Freie Mitteilung aus dem Release-Text. Bewusst KEIN Feld von Banner:
    sonst kann sie nur dort und nur so erscheinen wie der Update-Banner — und der
    ist im eskalierten Fall nicht schliessbar. Getrennt gehalten ist sie frei
    platzierbar und immer schliessbar."""

    text: str
    url: str = ""


def compute_mitteilung(cfg) -> Mitteilung | None:
    """None = nichts anzeigen. Weggedrückt wird nach Text, nicht nach Version."""
    text = (cfg.update_mitteilung_text or "").strip()
    if not text:
        return None
    if (cfg.update_mitteilung_verworfen or "").strip() == text:
        return None
    return Mitteilung(text, cfg.update_mitteilung_url or "")


def compute_banner(cfg, current_version: str, now: datetime) -> Banner | None:
    """Berechnet den Anzeigezustand. None = nichts anzeigen."""
    if current_version == "dev":
        return None          # Entwicklungsversion wird nicht verglichen

    latest = cfg.update_latest_version or ""
    severity = cfg.update_severity or "normal"

    if latest and is_newer_version(latest, current_version):
        notice = cfg.update_notice or f"Version {latest} ist verfügbar."
        url = cfg.update_url or ""
        if severity in ESCALATED:
            # Eskaliert ignoriert update_dismissed_version mit Absicht.
            return Banner("escalated", False, notice, url, latest)
        if cfg.update_dismissed_version and not is_newer_version(
            latest, cfg.update_dismissed_version
        ):
            return None
        return Banner("normal", True, notice, url, latest)

    if cfg.update_snoozed_until and cfg.update_snoozed_until > now:
        return None

    checked = cfg.update_last_checked_at
    attempt = cfg.update_last_attempt_at
    if checked is not None and checked > now:
        return None          # Uhr läuft falsch — lieber nichts als eine absurde Zahl
    if checked is not None and now - checked < timedelta(days=REMINDER_DAYS):
        return None

    if attempt is not None and (checked is None or attempt > checked):
        return Banner(
            "attempt_failed", True,
            "Die letzte Update-Prüfung war nicht möglich.",
        )

    tage = 0 if checked is None else max(0, (now - checked).days)
    text = (
        "Du hast noch nie nach Updates gesucht. Bleib auf dem neuesten Stand."
        if checked is None
        else f"Du hast seit {tage} Tagen nicht nach Updates gesucht. "
             "Bleib auf dem neuesten Stand."
    )
    return Banner("reminder", True, text)
