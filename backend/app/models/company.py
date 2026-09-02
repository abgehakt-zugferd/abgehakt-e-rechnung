from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Company(Base):
    __tablename__ = "company"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    # KEINE Defaults auf den Firmenfeldern (#99 §4.1): sie ließen eine frische
    # Installation fremde Firmendaten tragen, ohne dass jemand etwas eingab —
    # und die Werte landeten von dort in PDF, ZUGFeRD-XML und Mailtext.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line2: Mapped[str | None] = mapped_column(String(255))
    zip_code: Mapped[str] = mapped_column(String(20), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    # `server_default` zusätzlich zu `default`: die Singleton-Zeile entsteht in der
    # Migration per rohem INSERT, der nur die Identitätsfelder setzt. Ohne den
    # DB-seitigen Wert scheitert er an NOT NULL. Gilt für alle folgenden
    # Nicht-Identitätsfelder.
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="DE", server_default="DE")
    tax_number: Mapped[str | None] = mapped_column(String(50))
    vat_id: Mapped[str | None] = mapped_column(String(20))
    vat_id_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vat_id_check_valid: Mapped[bool | None] = mapped_column(Boolean)
    vat_id_vies_name: Mapped[str | None] = mapped_column(String(500))
    vat_id_name_match: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(50))
    # BT-41, der Ansprechpartner auf der Rechnung (#153). Leer erlaubt: dann steht
    # der Firmenname dort. Ein leeres Element wäre ein Schemafehler, ein fehlender
    # Ansprechpartner ist dagegen nur eine fehlende Angabe.
    contact_name: Mapped[str | None] = mapped_column(String(255))
    bank_iban: Mapped[str | None] = mapped_column(String(34))
    bank_bic: Mapped[str | None] = mapped_column(String(11))
    bank_name: Mapped[str | None] = mapped_column(String(100))
    invoice_prefix: Mapped[str] = mapped_column(String(20), nullable=False, default="RE", server_default="RE")
    invoice_year_in_number: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    invoice_counter: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    payment_terms_default: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="Zahlbar innerhalb von 14 Tagen nach Rechnungseingang ohne Abzug.",
        server_default="Zahlbar innerhalb von 14 Tagen nach Rechnungseingang ohne Abzug.",
    )
    # Ersteinrichtung abgeschlossen — ein Zustand, keine Heuristik auf Feldinhalten
    # (#99 §4.0). NULL heißt: die Nutzerin war noch nie im Einrichtungsschritt.
    setup_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
