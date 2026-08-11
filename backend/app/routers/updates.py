"""Update-Prüfung (#120): zwei Form-Posts, Post/Redirect/Get wie im Rest des Projekts."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.branding import register_branding_globals
from app.config import get_settings
from app.database import get_db
from app.models.app_config import AppConfig
from app.services.update_banner import SNOOZE_DAYS
from app.services.update_check import ENDPOINT, UpdateCheckError, fetch_update_info

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
register_branding_globals(templates)


def _config(db: Session) -> AppConfig:
    cfg = db.query(AppConfig).filter(AppConfig.id == 1).first()
    if cfg is None:
        cfg = AppConfig(id=1)
        db.add(cfg)
        db.flush()
    return cfg


def _edition() -> str:
    return "free"   # Edition-Weiche folgt mit #99; bis dahin ist alles Free.


@router.post("/pruefen")
def pruefen(request: Request, bestaetigt: str = Form(default=""),
            db: Session = Depends(get_db)):
    cfg = _config(db)
    version = get_settings().app_version

    # Ohne einmalige Bestaetigung wird NICHTS uebertragen (Datenschutz, Spec §9).
    if cfg.update_consent_at is None and bestaetigt != "1":
        db.commit()
        # Nur die Adresse. Version und Ausgabe werden nicht übertragen
        # (siehe update_check.fetch_update_info) und haben deshalb auf einer
        # Seite nichts zu suchen, die auflistet, was hinausgeht — sie standen
        # dort einmal und machten die Einwilligung falsch.
        return templates.TemplateResponse(
            request, "updates/consent.html", {"endpoint": ENDPOINT},
        )

    jetzt = datetime.now(timezone.utc)
    if cfg.update_consent_at is None:
        cfg.update_consent_at = jetzt
    cfg.update_last_attempt_at = jetzt
    try:
        info = fetch_update_info(version, _edition())
    except UpdateCheckError:
        db.commit()          # Versuch festhalten, gespeicherte Daten unberuehrt lassen
        return RedirectResponse("/", status_code=303)

    cfg.update_last_checked_at = jetzt
    cfg.update_latest_version = info.latest_version
    cfg.update_severity = info.severity
    cfg.update_notice = info.notice
    cfg.update_url = info.url
    cfg.update_mitteilung_text = info.mitteilung
    cfg.update_mitteilung_url = info.mitteilung_url
    cfg.update_snoozed_until = None
    db.commit()
    return RedirectResponse("/", status_code=303)


@router.get("/anleitung")
def anleitung(request: Request):
    return templates.TemplateResponse("updates/anleitung.html", {"request": request})


def _sicheres_ziel(weiter: str) -> str:
    """Nur eigene, absolute Pfade — sonst ist der Schließen-Knopf eine offene
    Weiterleitung. `//evil.com` ist protokollrelativ und landet auf einem fremden
    Host; ein Backslash wird von manchen Browsern wie `/` behandelt. Deshalb
    reicht „fängt mit / an" als Prüfung nicht."""
    if weiter.startswith("/") and not weiter.startswith("//") and "\\" not in weiter:
        return weiter
    return "/"


@router.post("/mitteilung-schliessen")
def mitteilung_schliessen(weiter: str = Form(default="/"), db: Session = Depends(get_db)):
    """Der Pro-Hinweis ist IMMER schließbar (Spec §4.6). Weggedrückt wird der
    Text, nicht eine Version — genau dieser Hinweis kommt nicht wieder."""
    cfg = _config(db)
    if cfg.update_mitteilung_text:
        cfg.update_mitteilung_verworfen = cfg.update_mitteilung_text.strip()
    db.commit()
    return RedirectResponse(_sicheres_ziel(weiter), status_code=303)


@router.post("/hinweis-schliessen")
def hinweis_schliessen(db: Session = Depends(get_db)):
    cfg = _config(db)
    if cfg.update_latest_version:
        cfg.update_dismissed_version = cfg.update_latest_version
    cfg.update_snoozed_until = datetime.now(timezone.utc) + timedelta(days=SNOOZE_DAYS)
    db.commit()
    return RedirectResponse("/", status_code=303)
