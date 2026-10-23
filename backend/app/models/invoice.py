from __future__ import annotations

import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, Boolean, CheckConstraint, DateTime, Date, Index, Numeric, Integer, Text, JSON, func, text, ForeignKey
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

    # Pro Original hoechstens eine nicht verworfene Gutschrift (#90). Die
    # Vorabpruefung in create_storno nimmt keine Sperre; ohne diesen Index
    # legen zwei ueberlappende Anfragen zwei Gutschriften an und mindern die
    # Forderung doppelt. Verworfene Stornos (`discarded`) zaehlen nicht, sonst
    # waere ein Fehlgriff endgueltig. Dieselbe Quelle wie Migration 013 und
    # create_all in der Test-DB (alembic check).
    __table_args__ = (
        Index(
            "uq_invoices_eine_aktive_gutschrift_pro_original",
            "original_invoice_id",
            unique=True,
            postgresql_where=text(
                "status <> 'discarded' AND original_invoice_id IS NOT NULL"
            ),
        ),
        # Pro Original hoechstens eine nicht verworfene Ersatzrechnung, aus demselben
        # Grund und mit derselben Ausnahme wie oben (docs/specs/ersatzrechnung.md).
        Index(
            "uq_invoices_eine_aktive_ersatzrechnung_pro_original",
            "ersetzt_invoice_id",
            unique=True,
            postgresql_where=text(
                "status <> 'discarded' AND ersetzt_invoice_id IS NOT NULL"
            ),
        ),
        # Abzug (BG-20, #147): immer als Paar. Kein Abzug heisst beide NULL;
        # gesetzt heisst Betrag positiv und Grund gefuellt. Der Grund ist
        # Pflicht (EN 16931 BR-33) und wird im Router verlangt, nicht hier
        # ersetzt. Identisch zu Migration 023 (alembic check).
        CheckConstraint(
            "(abzug_betrag IS NULL AND abzug_grund IS NULL) "
            "OR (abzug_betrag > 0 AND abzug_grund IS NOT NULL)",
            name="ck_invoices_abzug_beide_oder_gueltig",
        ),
        # BT-9 oder BT-20 bleiben für fertige Belege Pflicht. Nur ein
        # noch offener oder verworfener Rechnungsauftrag darf auf die
        # Kundenvorgabe warten (#206, Migration 032).
        CheckConstraint(
            "due_date IS NOT NULL OR (payment_terms IS NOT NULL AND payment_terms <> '') "
            "OR (status IN ('draft', 'discarded') AND auftragsschluessel IS NOT NULL "
            "AND uebergabe_beleg_sha256 IS NOT NULL AND invoice_type IS NULL)",
            name="ck_invoices_faelligkeit_oder_bedingungen",
        ),
        # Entscheidung 7 / Festlegung 12: Solange zu einem Auftragsschluessel
        # ein Beleg besteht, der weder storniert noch verworfen ist, darf kein
        # zweiter entstehen. Der partielle Index sichert diese Zusage gegen zwei
        # gleichzeitige Anfragen; NULL (freigegeben) sperrt nicht. Identisch
        # zu Migration 028 (alembic check).
        Index(
            "uq_invoices_auftragsschluessel_offen",
            "auftragsschluessel_offen",
            unique=True,
            postgresql_where=text("auftragsschluessel_offen IS NOT NULL"),
        ),
        # Die Sperre ist kein zweiter, freier Wert: Sie ist entweder weg oder
        # deckt sich mit dem Nachweis. Identisch zu Migration 028 (alembic
        # check).
        CheckConstraint(
            "auftragsschluessel_offen IS NULL OR auftragsschluessel_offen = auftragsschluessel",
            name="ck_invoices_auftragsschluessel_offen_wie_nachweis",
        ),
    )

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
    # BT-9, optional seit Bauschritt 2b: ein Kunde, der nach eigenem Takt zahlt,
    # bekommt kein Fälligkeitsdatum, sondern einen Zahlungshinweis in
    # payment_terms (BT-20). EN 16931 BR-CO-25 verlangt bei offenem Betrag eines
    # von beiden; Formular und Validator sind die erste Linie, der CHECK unten
    # die zweite.
    due_date: Mapped[Optional[date]] = mapped_column(Date)
    delivery_date: Mapped[Optional[date]] = mapped_column(Date)
    service_period_start: Mapped[Optional[date]] = mapped_column(Date)
    service_period_end: Mapped[Optional[date]] = mapped_column(Date)
    payment_terms: Mapped[Optional[str]] = mapped_column(String(500))
    # BT-10, die Referenz des Käufers (#153): gegenüber Behörden die Leitweg-ID,
    # sonst eine vom Kunden vorgegebene Referenz. Die Bestellnummer / Purchase
    # Order gehört nicht hierher — dafür ist buyer_order_reference (BT-13, #101).
    buyer_reference: Mapped[Optional[str]] = mapped_column(String(100))
    # BT-13, Bestellnummer des Kunden (#101): eigene Spalte neben buyer_reference,
    # damit Leitweg-ID und Purchase-Order gleichzeitig getragen werden können.
    buyer_order_reference: Mapped[Optional[str]] = mapped_column(String(100))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    # Kopf- und Fusstext, beim Anlegen aus dem Kunden KOPIERT (Festlegung 15):
    # Platzhalter {leistungsmonat} schon ersetzt, spaetere Aenderungen am Kunden
    # erreichen diesen Beleg nicht mehr. Bewusst eigene Spalten und nicht live
    # gelesen, damit der Beleg auch nach einer Kundenkorrektur noch aussieht wie
    # gestellt. Nach dem Finalisieren Rechnungsinhalt: nicht in
    # MUTABLE_AFTER_FINALIZE, der Guard schuetzt sie wie notes.
    kopftext: Mapped[Optional[str]] = mapped_column(Text)
    fusstext: Mapped[Optional[str]] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR", server_default="EUR")
    net_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    tax_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    gross_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    # Abzug auf Belegebene (BG-20, #147). net/tax/gross_total enthalten ihn
    # bereits: net_total ist die Steuerbasis, tax_total die Steuer auf der
    # verminderten Basis. Rechnet nur services/belegsummen.py.
    abzug_betrag: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    abzug_grund: Mapped[Optional[str]] = mapped_column(Text)
    # draft → issued → paid / cancelled
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft", index=True
    )
    zugferd_profile: Mapped[str] = mapped_column(
        String(20), nullable=False, default="EN16931", server_default="EN16931"
    )
    tax_category: Mapped[str] = mapped_column(String(5), nullable=False, default="S", server_default="S")
    # Belegsprache steuert nur die menschliche Darstellung (PDF). Nicht aus Land,
    # Adresse oder USt-IdNr. ableiten. Nach Finalisieren unveraenderlich
    # (nicht in MUTABLE_AFTER_FINALIZE). docs/specs/belegsprache.md
    document_language: Mapped[str] = mapped_column(
        String(2), nullable=False, default="de", server_default="de"
    )
    # P7: TypeCode für ZUGFeRD (380=Rechnung, 381=Gutschrift/Storno, 384=Korrektur, 389=Gutschriftverfahren)
    # Wird in zugferd_xml/ verwendet, um den richtigen TypeCode zu setzen
    invoice_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, default=None)
    # Herkunft aus einem signierten Uebergabebeleg (#22). Gesetzt heisst: die
    # Betraege, der Beteiligte und der Leistungszeitraum stammen aus einem Beleg,
    # der acht Jahre lang die Autoritaet ist. Sie sind deshalb auch im Entwurf
    # gesperrt: eine Rechnung, die auf einen Beleg zeigt, den sie nicht mehr
    # wiedergibt, ist schlimmer als eine falsche Rechnung, denn sie sieht belegt aus.
    uebergabe_beleg_id: Mapped[Optional[str]] = mapped_column(String(64))
    uebergabe_beleg_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    zugferd_xml: Mapped[Optional[str]] = mapped_column(Text)
    pdf_filename: Mapped[Optional[str]] = mapped_column(String(255))
    # Erstversand an die BUCHHALTUNG (Bauschritt 5a, Entscheidung 6): Bis hier
    # deckte diese Spalte den ganzen Versand ab, weil eine Mail Kunde und
    # Buchhaltung in einem Schritt belief. Seit beide getrennte Vermerke
    # haben, zaehlt sie nur noch den Weg an die Buchhaltung; der Kunde hat
    # kunde_zugestellt_am. Wie dort: einmal setzen, nie aendern (invoice_guard,
    # GoBD).
    datev_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Erstzustellung an den KUNDEN, auf jedem Weg (Mail oder, ab Teil 5b,
    # Freitext-Vermerk). Ein Beleg kann der Buchhaltung zugegangen sein, ohne
    # dass der Kunde ihn hat — dann steht hier NULL, und der Beleg gilt als
    # nicht versendet. Gleiches Muster wie datev_sent_at: einmal setzen, nie
    # aendern (invoice_guard, GoBD).
    kunde_zugestellt_am: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Zahlungseingang (Entscheidung 2026-09-30): nur beim Uebergang issued→paid
    # gesetzt, danach unveraenderlich. Umsatz und „Bezahlt diesen Monat“ rechnen danach.
    bezahlt_am: Mapped[Optional[date]] = mapped_column(Date)
    # GoBD: 8-Jahr-Aufbewahrung – Datum ab dem die Frist läuft
    archive_until: Mapped[Optional[date]] = mapped_column(Date)
    # P5: Bezug auf Originalrechnung für Stornorechnungen (GoBD-Nachvollziehbarkeit)
    original_invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id"),
        nullable=True,
        index=True
    )
    # Ersatzrechnung (docs/specs/ersatzrechnung.md): eine gewoehnliche Rechnung, die
    # eine stornierte ersetzt (BT-25). Bewusst nicht original_invoice_id: die gehoert
    # den Folgebelegen 381/384/389 und ist bei 380/386 verboten.
    ersetzt_invoice_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("invoices.id"),
        nullable=True,
        index=True
    )
    # Auftragsschluessel des vorgelagerten Systems (Bauschritt 4a,
    # Entscheidung 7): der Nachweis, aus welchem Auftrag der Beleg entstand.
    # Nach dem Finalisieren unveraenderlich (nicht in MUTABLE_AFTER_FINALIZE).
    # Gesetzt und geleert wird er nur ueber services/auftragsschluessel.py.
    auftragsschluessel: Mapped[Optional[str]] = mapped_column(Text)
    # Dieselbe Zeichenkette, solange der Beleg den Schluessel sperrt, sonst
    # NULL. Der Status taugt dafuer nicht: Eine per Stornorechnung aufgehobene
    # Rechnung bleibt 'issued' oder 'paid' (Festlegung 12), deshalb sperrt eine
    # eigene Spalte mit partiellem Unique-Index (unten). Nach dem Finalisieren
    # darf sie nur geleert werden (invoice_guard, Muster datev_sent_at).
    auftragsschluessel_offen: Mapped[Optional[str]] = mapped_column(Text)
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
        uselist=False,
        foreign_keys="Invoice.original_invoice_id",
    )
    ersetzte_rechnung: Mapped[Optional["Invoice"]] = relationship(
        "Invoice",
        remote_side=[_id_col],
        uselist=False,
        foreign_keys="Invoice.ersetzt_invoice_id",
    )
    # P5: Liste aller Stornorechnungen zu dieser Rechnung
    storno_invoices: Mapped[list["Invoice"]] = relationship(
        "Invoice",
        back_populates="original_invoice",
        foreign_keys="Invoice.original_invoice_id",
    )


# Bestehende Importgrenze für Positionen und Protokolle bleibt erhalten.
from app.models.invoice_nebenmodelle import (
    InvoiceItem, ValidationResult, InvoiceSendLog, AuditLog,
)
