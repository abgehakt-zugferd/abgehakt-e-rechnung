"""Einstellungen: Text der Rechnungsmail je Belegsprache.

Getrennt von SMTP/DATEV, damit settings.py die Groessengrenze haelt.
"""
from fastapi import Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import mailtext


def mail_form_werte(config, override: dict | None = None) -> dict:
    if override is not None:
        return override
    return {
        "mail_betreff_de": config.mail_betreff_de or "",
        "mail_text_de": config.mail_text_de or "",
        "mail_betreff_en": config.mail_betreff_en or "",
        "mail_text_en": config.mail_text_en or "",
    }


def _pruefe_mail_eingaben(werte: dict) -> dict[str, str]:
    fehler: dict[str, str] = {}
    for feld, text in werte.items():
        try:
            mailtext.pruefe_schablone(text)
        except mailtext.UnbekannterPlatzhalterError as e:
            fehler[feld] = f"Unbekannter Platzhalter: {{{e.name}}}"
    for feld in ("mail_betreff_de", "mail_betreff_en"):
        try:
            mailtext.pruefe_betreff(werte[feld])
        except mailtext.BetreffMitZeilenumbruchError as e:
            fehler[feld] = str(e)
    return fehler


def register(router, settings_page, get_or_create_app_config):
    @router.post("/mailtext")
    def save_mailtext(
        request: Request,
        mail_betreff_de: str = Form(""),
        mail_text_de: str = Form(""),
        mail_betreff_en: str = Form(""),
        mail_text_en: str = Form(""),
        db: Session = Depends(get_db),
    ):
        werte = {
            "mail_betreff_de": mail_betreff_de,
            "mail_text_de": mail_text_de,
            "mail_betreff_en": mail_betreff_en,
            "mail_text_en": mail_text_en,
        }
        fehler = _pruefe_mail_eingaben(werte)
        if fehler:
            return settings_page(
                request,
                db,
                saved=False,
                error="Die Rechnungsmail konnte nicht gespeichert werden.",
                mail_werte=werte,
                mail_fehler=fehler,
            )
        config = get_or_create_app_config(db)
        config.mail_betreff_de = mail_betreff_de.strip() or None
        config.mail_text_de = mail_text_de.strip() or None
        config.mail_betreff_en = mail_betreff_en.strip() or None
        config.mail_text_en = mail_text_en.strip() or None
        db.commit()
        return RedirectResponse(url="/settings?saved=true", status_code=303)
