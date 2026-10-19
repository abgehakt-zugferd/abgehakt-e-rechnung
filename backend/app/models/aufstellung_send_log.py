"""Versandversuche der Aufstellung mit eigenem Pflicht-FK.

Wie InvoiceSendLog ist dies ein Zusatznachweis: NULL bedeutet offener
Ausgang, False gescheitert, True SMTP angenommen. CC, BCC und Kundenwege
existieren fuer Aufstellungen nicht; deshalb keine solchen Spalten.
"""
import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AufstellungSendLog(Base):
    __tablename__ = "aufstellung_send_logs"
    __table_args__ = (
        CheckConstraint("ziel = 'buchhaltung'", name="ck_aufstellung_send_logs_ziel"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    aufstellung_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aufstellungen.id"), nullable=False, index=True,
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    to_email: Mapped[str] = mapped_column(String(255), nullable=False)
    ziel: Mapped[str] = mapped_column(Text, nullable=False)
    success: Mapped[Optional[bool]] = mapped_column(Boolean)
    error: Mapped[Optional[str]] = mapped_column(Text)
