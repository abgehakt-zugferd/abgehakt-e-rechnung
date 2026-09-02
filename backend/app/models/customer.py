import uuid
from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, func, Integer, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    customer_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    address_line1: Mapped[str] = mapped_column(String(255), nullable=False)
    address_line2: Mapped[str | None] = mapped_column(String(255))
    zip_code: Mapped[str] = mapped_column(String(20), nullable=False)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="DE", server_default="DE")
    vat_id: Mapped[str | None] = mapped_column(String(20))
    vat_id_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vat_id_check_valid: Mapped[bool | None] = mapped_column(Boolean)
    vat_id_vies_name: Mapped[str | None] = mapped_column(String(500))
    vat_id_name_match: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    # Kommagetrennte Liste (#58), gepflegt über `services/empfaenger.py`. Sie steht
    # hier und nicht in `app_config`, weil sie zu DIESEM Kunden gehört: die globale
    # Voreinstellung ginge sonst an jeden anderen Kunden mit in Kopie.
    # Nicht in die ZUGFeRD-XML: dort ist die elektronische Adresse des Erwerbers
    # (BT-49) einwertig, das bleibt `email`.
    cc_emails: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(50))
    bank_iban: Mapped[str | None] = mapped_column(String(34))
    bank_bic: Mapped[str | None] = mapped_column(String(11))
    bank_name: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(String(2000))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    invoices: Mapped[list["Invoice"]] = relationship("Invoice", back_populates="customer")
