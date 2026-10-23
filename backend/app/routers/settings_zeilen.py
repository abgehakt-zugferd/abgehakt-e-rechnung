"""Singleton-Zeilen fuer Einstellungen (Firma, AppConfig)."""

from sqlalchemy.orm import Session

from app.models.app_config import AppConfig
from app.models.company import Company


def get_or_create_company(db: Session) -> Company:
    company = db.query(Company).filter(Company.id == 1).first()
    if not company:
        company = Company(id=1)
        db.add(company)
        db.commit()
        db.refresh(company)
    return company


def get_or_create_app_config(db: Session) -> AppConfig:
    config = db.query(AppConfig).filter(AppConfig.id == 1).first()
    if not config:
        config = AppConfig(id=1)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config
