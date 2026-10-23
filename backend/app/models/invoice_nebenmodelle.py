from __future__ import annotations

import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, Boolean, CheckConstraint, DateTime, Date, Index, Numeric, Integer, Text, JSON, func, text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base



class InvoiceItem(Base):
    __tablename__ = "invoice_items"
    __table_args__ = (
        CheckConstraint("(basis_netto IS NULL) = (satz IS NULL)",
                        name="ck_invoice_items_herleitung_beide_oder_keine"),
        CheckConstraint(
            "(leistung_von IS NULL) = (leistung_bis IS NULL)",
            name="ck_invoice_items_leistung_beide_oder_keiner",
        ),
        CheckConstraint(
            "leistung_von IS NULL OR leistung_von <= leistung_bis",
            name="ck_invoice_items_leistung_reihenfolge",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    invoice_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # BT-155, eigene Artikel- oder Leistungsnummer; optional. Grenzen und
    # Normalisierung: services/positionsangaben.py.
    artikelnummer: Mapped[Optional[str]] = mapped_column(String(50))
    # BT-134/135, Leistungszeitraum dieser Position; optional, beide oder keiner,
    # von <= bis (Produktregel, strenger als BR-30). Der Kopfzeitraum bleibt die
    # Pflichtangabe nach § 14 Abs. 4 Nr. 6 UStG.
    leistung_von: Mapped[Optional[date]] = mapped_column(Date)
    leistung_bis: Mapped[Optional[date]] = mapped_column(Date)
    # Freier Anzeigetext, der Positionen zu einer (zusammenhaengenden) Gruppe
    # ordnet (Bauschritt 3, Entscheidung 3). Nur Form, nie Wortlaut: dieselbe
    # Zeichenkette, zusammenhaengende Positionsnummern. Pruefungen und Grenzen
    # liegen in services/positionsangaben.py und pruefregeln/positionen.py —
    # der Zusammenhang reicht ueber Zeilen, ein CHECK koennte ihn nicht ausdruecken.
    gruppe: Mapped[Optional[str]] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="Stück", server_default="Stück")
    # basis_netto ist Geld (der Leser erzwingt genau zwei Nachkommastellen),
    # der satz aber nicht: Das Übergabeformat erlaubt mindestens zwei, beliebig
    # viele Nachkommastellen ("33.333333"). Eine Skala hier rundete beim Import
    # auf 33.33, und jedes Bearbeiten des Entwurfs scheiterte an der Nachgerechnung.
    basis_netto: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    satz: Mapped[Optional[Decimal]] = mapped_column(Numeric())
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
    an die Buchhaltung und `invoices.kunde_zugestellt_am` die Erstzustellung an
    den Kunden (Bauschritt 5a), beide guardgesichert unveränderlich (#98 P0.3);
    diese Tabelle hält alle Versuche — auch die gescheiterten. Der Fehlertext
    (z. B. „550 blocked") ist der eigentliche Wert: ohne ihn steht die Nutzerin bei
    einer gesperrten Adresse vor einem stummen Fehlschlag.

    Bewusst OHNE eigenen Guard/DB-Trigger: die Tabelle ist Zusatznachweis, nicht der
    rechtliche Anker (das bleiben `datev_sent_at` + Audit-Log). Sie ist selbst ein
    Protokoll und wird von `audit.py` deshalb nicht zusätzlich auditiert.
    """
    __tablename__ = "invoice_send_log"
    __table_args__ = (
        # Entscheidung 6: Drei Wege, die sich im Protokoll unterscheiden muessen —
        # der kombinierte Standardversand, der Gang nur an die Buchhaltung und
        # (Teil 5b) der Freitext-Vermerk einer Zustellung ohne Mail. Der CHECK
        # sichert den Wertevorrat auch ohne Anwendung. Identisch zu Migration
        # 029 (alembic check).
        CheckConstraint(
            "ziel IN ('kunde_und_buchhaltung', 'buchhaltung', 'kunde_vermerk')",
            name="ck_invoice_send_log_ziel",
        ),
        # Nur der Freitext-Vermerk traegt keinen Empfaenger: Ein Mail-Weg ohne
        # to_email waere ein halber Nachweis. Identisch zu Migration 029
        # (alembic check).
        CheckConstraint(
            "ziel = 'kunde_vermerk' OR to_email IS NOT NULL",
            name="ck_invoice_send_log_empfaenger_ausser_vermerk",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    invoice_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("invoices.id"), nullable=False, index=True
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Nullable seit Bauschritt 5a: Nur ein kunde_vermerk (Zustellung ohne
    # Mail, Teil 5b) hat keinen Empfaenger — der CHECK oben erzwingt das.
    to_email: Mapped[Optional[str]] = mapped_column(String(255))
    # Die tatsächlich verwendete Liste, nicht die Voreinstellung (#58): der Nachweis
    # muss sagen, wer den Beleg bekommen hat.
    cc_email: Mapped[Optional[str]] = mapped_column(String(500))
    datev_bcc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Weg dieses Eintrags (Entscheidung 6): Er beschreibt den gewaehlten Versand-
    # weg, nicht allein das Ergebnis — die tatsaechlichen Empfaenger stehen in
    # to_email/cc_email/datev_bcc, Abweichungen des Wegs in weg_notiz.
    ziel: Mapped[str] = mapped_column(Text, nullable=False)
    # Notiz zum Weg: heute die Abweichung, wenn der Standardversand ohne
    # Upload-Adresse nur an den Kunden ging; ab Teil 5b der Freitext des
    # Nutzers (etwa „Upload in das Kundenportal").
    weg_notiz: Mapped[Optional[str]] = mapped_column(Text)
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
