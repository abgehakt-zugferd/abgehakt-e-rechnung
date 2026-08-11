from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.config import get_settings

settings = get_settings()

# App-Laufzeit läuft als Least-Privilege-Rolle abgehakt_app (B2). Fail-closed: fehlt
# APP_DATABASE_URL, startet die App NICHT — kein stiller Fallback auf DATABASE_URL
# (das liefe wieder mit Owner-Rechten und hebelte Least-Privilege aus).
if not settings.app_database_url:
    raise RuntimeError(
        "APP_DATABASE_URL ist nicht gesetzt — die App verbindet ausschließlich als "
        "Least-Privilege-Rolle abgehakt_app (B2). Setze APP_DATABASE_URL in .env/Compose."
    )

engine = create_engine(settings.app_database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
