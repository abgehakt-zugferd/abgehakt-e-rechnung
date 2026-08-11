from datetime import datetime
from typing import Optional
from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class AppConfig(Base):
    __tablename__ = "app_config"

    # `autoincrement=False`: die Tabelle hat genau eine Zeile mit id=1. Eine Sequenz
    # darauf wäre nicht nur nutzlos, sie stünde beim Wert 1 und liefe damit beim
    # ersten id-losen INSERT in eine Kollision mit der Singleton-Zeile.
    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1, autoincrement=False)

    # SMTP Configuration
    smtp_host: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    smtp_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    smtp_user: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # TEXT, nicht String(255): der Wert ist ein Fernet-Chiffrat (services/crypto),
    # und das ist länger als das Klartextpasswort. Die Datenbank führt die Spalte
    # seit jeher als TEXT — nur das Modell hinkte hinterher.
    smtp_password: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    smtp_from: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    smtp_use_tls: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True, default=True)

    # DATEV Configuration
    datev_bcc_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # CC der Rechnungsmail (#147): sichtbare Kopie, z. B. an die eigene Ablage.
    # Nur Vorbelegung des Sende-Dialogs — verbindlich ist die abgeschickte Adresse.
    invoice_cc_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Update-Hinweis (#120). Zwei Zeitstempel mit Absicht:
    # last_checked_at = letzte ERFOLGREICHE Prüfung (speist "seit X Tagen"),
    # last_attempt_at = letzter VERSUCH. Liegt attempt nach checked, war die
    # Prüfung nicht möglich — dann wird der Nutzer nicht für unser Problem gerügt.
    update_last_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    update_last_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    update_latest_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    update_severity: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    update_notice: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    update_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    # Pro-Hinweis getrennt gehalten: er darf nie im nicht-wegklickbaren Banner landen.
    update_mitteilung_text: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    update_mitteilung_url: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    # Weggedrückt wird der Pro-Hinweis nach TEXT (er hat keine Version): genau
    # dieser Text kommt nicht wieder, ein neuer Text darf erscheinen.
    update_mitteilung_verworfen: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True
    )
    update_dismissed_version: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    update_snoozed_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Einmalige ausdrückliche Bestätigung vor dem ersten Abruf (Datenschutz, Spec §9).
    update_consent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
