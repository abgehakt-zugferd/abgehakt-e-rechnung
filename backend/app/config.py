from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path

from app.services.secret_key import lade_oder_erzeuge

# Eine Ebene über `app/`: im Bau ist das `/app/VERSION`, im Repo `backend/VERSION`
# — beides innerhalb des Baukontexts `./backend`.
VERSIONSDATEI = Path(__file__).resolve().parents[1] / "VERSION"


def version_aus_datei(pfad: Path = VERSIONSDATEI) -> str:
    """Die Version für Installationen ohne Git.

    Wer das Programm als Archiv herunterlädt und baut, hat kein `git describe`
    zur Hand. Ohne diese Datei meldete jede so entstandene Installation 'dev',
    und für 'dev' zeigt `compute_banner` grundsätzlich nichts an — die
    Update-Prüfung wäre überall dort tot, wo sie gebraucht wird.
    """
    try:
        return pfad.read_text(encoding="utf-8").strip() or "dev"
    except OSError:
        return "dev"


class Settings(BaseSettings):
    database_url: str = "postgresql://abgehakt_admin:changeme@localhost:5432/abgehakt"
    # App-Laufzeit als Least-Privilege-Rolle abgehakt_app (fail-closed in database.py).
    app_database_url: str = ""
    db_app_user: str = "abgehakt_app"
    db_app_password: str = ""
    # Kein eingebrannter Default: leer bedeutet „aus der Schlüsseldatei im
    # storage-Volume holen bzw. dort einmalig erzeugen" (#99 §5.4, siehe
    # model_post_init). Eine gesetzte Umgebungsvariable hat Vorrang — sonst
    # verlören Bestandsinstallationen mit .env schlagartig alle verschlüsselten Werte.
    secret_key: str = ""

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    datev_bcc_email: str = ""

    # Versionsidentität (#120): --build-arg APP_VERSION, sonst die Datei VERSION
    # (siehe model_post_init). NICHT aus pyproject.toml — eine Erhöhung dort bricht
    # `uv sync --locked`, weil uv.lock den Projekteintrag mit Version führt (rc=1).
    app_version: str = ""

    storage_path: Path = Path("/app/storage")
    mustang_jar: Path = Path("/app/lib/Mustang-CLI.jar")

    class Config:
        env_file = ".env"
        extra = "ignore"

    def model_post_init(self, __context) -> None:
        """Ohne .env keine Sackgasse: der Schlüssel verwaltet sich selbst (L7)."""
        # Leer heißt „nicht gesetzt": `ARG APP_VERSION=` ohne `--build-arg` legt eine
        # leere Umgebungsvariable an, und die gewönne sonst gegen die Datei.
        if not self.app_version.strip():
            self.app_version = version_aus_datei()
        if not self.secret_key:
            self.secret_key = lade_oder_erzeuge(self.storage_path)


@lru_cache()
def get_settings() -> Settings:
    return Settings()
