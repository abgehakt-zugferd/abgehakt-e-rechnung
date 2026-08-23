from __future__ import annotations

import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Date, Index, Numeric, Integer, Text, JSON, func, text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base

# Define the id column separately to reference it in relationships
_id_col = mapped_column(
    UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    server_default=text("gen_random_uuid()"),
)


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = _id_col
    invoice_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    # Nullable, weil ein Entwurf keinen Empfänger braucht: man tippt Positionen und
    # Termine, bevor der Kunde im Stamm steht. Für die fertige RECHNUNG ist er Pflicht
    # (§ 14 Abs. 4 Nr. 1 UStG) — durchgesetzt wird das nicht hier, sondern von
    # `validator.validate_invoice` (`BUYER_MISSING`, harter Fehler) vor dem
    # fail-closed-Finalisieren. Die Spalte ist der falsche Ort dafür: sie würde die
    # Eingabe schon beim Speichern des Entwurfs verwerfen.
    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True
    )
    issue_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    delivery_date: Mapped[Optional[date]] = mapped_column(Date)
    payment_terms: Mapped[Optional[str]] = mapped_column(String(500))
    # BT-10, die Referenz des Käufers (#153): im B2B seine Bestellnummer, gegenüber
    # Behörden die Leitweg-ID. Gehört zur Rechnung, nicht zum Kunden — sie ändert
    # sich pro Auftrag.
    buyer_reference: Mapped[Optional[str]] = mapped_column(String(100))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR", server_default="EUR")
    net_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    tax_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    gross_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    # draft → issued → paid / cancelled
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft", index=True
    )
    zugferd_profile: Mapped[str] = mapped_column(
        String(20), nullable=False, default="EN16931", server_default="EN16931"
    )
    tax_category: Mapped[str] = mapped_column(String(5), nullable=False, default="S", server_default="S")
    # P7: TypeCode für ZUGFeRD (380=Rechnung, 381=Gutschrift/Storno, 384=Korrektur, 389=Gutschriftverfahren)
    # Wird in zugferd_xml.py verwendet, um den richtigen TypeCode zu setzen
    invoice_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default=None)
    zugferd_xml: Mapped[Optional[str]] = mapped_column(Text)
    pdf_filename: Mapped[Optional[str]] = mapped_column(String(255))
    datev_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # GoBD: 8-Jahr-Aufbewahrung – Datum ab dem die Frist läuft
    archive_until: Mapped[Optional[date]] = mapped_column(Date)
    # P5: Bezug auf Originalrechnung für Stornorechnungen (GoBD-Nachvollziehbarkeit)
    original_invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id"),
        nullable=True,
        index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    customer: Mapped[Optional["Customer"]] = relationship("Customer", back_populates="invoices")
    items: Mapped[list["InvoiceItem"]] = relationship(
        "InvoiceItem", back_populates="invoice", cascade="all, delete-orphan", order_by="InvoiceItem.position"
    )
    validations: Mapped[list["ValidationResult"]] = relationship(
        "ValidationResult", back_populates="invoice", cascade="all, delete-orphan"
    )
    # #146: Versandprotokoll, neueste zuerst — die Detailseite zeigt genau diese Reihenfolge.
    send_logs: Mapped[list["InvoiceSendLog"]] = relationship(
        "InvoiceSendLog", back_populates="invoice", cascade="all, delete-orphan",
        order_by="InvoiceSendLog.sent_at.desc()"
    )
    # P5: Beziehung zu Originalrechnung (für Stornos)
    original_invoice: Mapped[Optional["Invoice"]] = relationship(
        "Invoice",
        remote_side=[_id_col],
        back_populates="storno_invoices",
        uselist=False
    )
    # P5: Liste aller Stornorechnungen zu dieser Rechnung
    storno_invoices: Mapped[list["Invoice"]] = relationship(
        "Invoice",
        back_populates="original_invoice"
    )


class InvoiceItem(Base):
    __tablename__ = "invoice_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="Stück", server_default="Stück")
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=19, server_default="19")
    net_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="items")


class ValidationResult(Base):
    __tablename__ = "validation_results"

    # Gelesen wird immer dasselbe: das jüngste Ergebnis zu EINER Rechnung. Der
    # Index deckt beides ab — die Auswahl über `invoice_id`, die Sortierung über
    # `validated_at` absteigend. Ohne ihn läuft die Detailseite über die ganze
    # Tabelle, und diese Tabelle wächst bei jedem Klick auf „prüfen" (nicht erst
    # beim Finalisieren) und wird nie aufgeräumt.
    __table_args__ = (
        Index("ix_validation_results_invoice_zeit", "invoice_id", "validated_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    validated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    errors: Mapped[Optional[list]] = mapped_column(JSON)
    warnings: Mapped[Optional[list]] = mapped_column(JSON)
    mustang_output: Mapped[Optional[str]] = mapped_column(Text)

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="validations")


class InvoiceSendLog(Base):
    """Protokoll JEDES Zustellversuchs der Rechnungsmail (#146).

    Zweigeteilter Versandnachweis: `invoices.datev_sent_at` bleibt der ERSTversand
    und ist guardgesichert unveränderlich (#98 P0.3); diese Tabelle hält alle
    Versuche — auch die gescheiterten. Der Fehlertext (z. B. „550 blocked") ist der
    eigentliche Wert: ohne ihn steht die Nutzerin bei einer gesperrten Adresse vor
    einem stummen Fehlschlag.

    Bewusst OHNE eigenen Guard/DB-Trigger: die Tabelle ist Zusatznachweis, nicht der
    rechtliche Anker (das bleiben `datev_sent_at` + Audit-Log). Sie ist selbst ein
    Protokoll und wird von `audit.py` deshalb nicht zusätzlich auditiert.
    """
    __tablename__ = "invoice_send_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    to_email: Mapped[str] = mapped_column(String(255), nullable=False)
    cc_email: Mapped[Optional[str]] = mapped_column(String(255))
    datev_bcc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Drei Ausgaenge, nicht zwei (#10): die Zeile entsteht und wird committet, BEVOR
    # SMTP angesprochen wird. In der Zeit dazwischen ist der Ausgang offen, und NULL
    # ist genau das. Faellt der Commit danach um, bleibt sie offen stehen: die Mail
    # koennte drausssen sein. `False` an dieser Stelle waere eine Behauptung, die
    # niemand geprueft hat, und die Auskunft, auf die hin jemand erneut sendet.
    success: Mapped[Optional[bool]] = mapped_column(Boolean)
    error: Mapped[Optional[str]] = mapped_column(Text)

    invoice: Mapped["Invoice"] = relationship("Invoice", back_populates="send_logs")


class AuditLog(Base):
    __tablename__ = "audit_log"

    # Die Historie wird immer über Tabelle+Datensatz gelesen („was ist mit dieser
    # Rechnung passiert?"), nie über eine der beiden Spalten allein — deshalb ein
    # zusammengesetzter Index. Ohne ihn wird die Abfrage mit den Jahren zum
    # Full-Table-Scan: das Audit-Log wächst nur, es wird nie aufgeräumt.
    __table_args__ = (Index("ix_audit_log_table_record", "table_name", "record_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    table_name: Mapped[str] = mapped_column(String(100), nullable=False)
    record_id: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    old_values: Mapped[Optional[dict]] = mapped_column(JSON)
    new_values: Mapped[Optional[dict]] = mapped_column(JSON)
