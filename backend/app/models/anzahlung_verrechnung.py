"""Verknuepfung Schlussrechnung - verrechnete Anzahlung (#259).

Eine Zeile je verrechnetem Beleg. Der partielle Unique-Index sichert in der
Datenbank, dass ein Beleg hoechstens in EINER Schlussrechnung verrechnet ist,
solange die Zeile `aktiv` ist. `aktiv` endet, wenn die Schlussrechnung
verworfen oder durch eine gestellte Gutschrift aufgehoben wird; die Zeile
bleibt dann als Nachweis stehen (services/anzahlungen.py). Identisch zu
Migration 033 (alembic check).
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AnzahlungVerrechnung(Base):
    __tablename__ = "anzahlung_verrechnungen"
    __table_args__ = (
        UniqueConstraint("schlussrechnung_id", "anzahlung_id",
                         name="uq_anzahlung_verrechnung_paar"),
        Index(
            "uq_anzahlung_nur_einmal_aktiv",
            "anzahlung_id",
            unique=True,
            postgresql_where=text("aktiv"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    schlussrechnung_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True,
    )
    anzahlung_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False,
    )
    aktiv: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true"),
    )

    anzahlung = relationship("Invoice", foreign_keys=[anzahlung_id])
