"""Die Abrechnungsaufstellung als EIGENES Modell (Bauschritt 7a, Entscheidung 8
aus docs/specs/rechnungs-und-aufstellungsauftrag.md).

Keine Steuer, kein Typcode, keine XML, kein Mustang: Die Aufstellung ist
KEINE Rechnung und wird nicht als Belegart der Rechnung gefuehrt. Sie bildet
lediglich die Invarianten der Rechnung nach — Nummer schon beim Entwurf
(Festlegung 18), Sperre des Auftragsschluessels (Festlegung 12),
Unveraenderlichkeit nach dem Stellen (aufstellung_guard) — in einer eigenen
Tabelle, damit die Rechnung dafuer nicht verbogen werden muss.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric,
    String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Wie invoice.py: die id-Spalte separat definiert, damit Relationships sie
# referenzieren koennen; server_default, damit auch rohes SQL (Migration,
# psql) eine id bekommt.
_id_col = mapped_column(
    UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    server_default=text("gen_random_uuid()"),
)


class Aufstellung(Base):
    __tablename__ = "aufstellungen"

    __table_args__ = (
        # draft: freier Entwurf. issued: gestellt, inhaltlich unveraenderlich
        # (aufstellung_guard). cancelled: storniert, Endzustand. discarded:
        # verworfener Entwurf, der die Nummernluecke erklaert (Festlegung 18)
        # und zurueckholbar ist. Es gibt kein paid: Die Aufstellung ist keine
        # Rechnung und kennt keinen Zahlungseingang als Status — der Geldweg
        # steht in zahlungsnummer/zahlungsdatum, nicht am Beleg.
        CheckConstraint(
            "status IN ('draft', 'issued', 'cancelled', 'discarded')",
            name="ck_aufstellungen_status_wertevorrat",
        ),
        # Festlegung 21: Abgehakt rechnet keinen Wert in Euro um. Bei
        # Berichtswaehrung EUR gibt es deshalb nichts umzurechnen (beide
        # Spalten NULL); bei Fremdwaehrung muessen Kurs und Zahlbetrag
        # stehen, sonst waere der Bericht ein Blatt ohne Ergebnis. Die
        # Gleichung Netto x Kurs wird bewusst NICHT geprueft (§ 8b).
        CheckConstraint(
            "(waehrung = 'EUR') = (kurs IS NULL AND zahlbetrag_eur IS NULL)",
            name="ck_aufstellungen_umrechnung_nur_bei_fremdwaehrung",
        ),
        # Die Gleichung aus § 8b ist Invariante der Zeile, nicht Aufgabe des
        # Aufrufers: brutto - quellensteuer = netto, exakt, in der DB.
        CheckConstraint(
            "brutto - quellensteuer = netto",
            name="ck_aufstellungen_summe",
        ),
        # Festlegung 12, dieselbe Begründung wie bei invoices: Der Status
        # taugt nicht als Sperrkriterium, die Sperre ist entweder weg oder
        # deckt sich mit dem Nachweis. Identisch zu Migration 030 (alembic
        # check); der partielle Unique-Index darunter sichert die Zusage
        # gegen zwei gleichzeitige Anfragen — je Tabelle; ueber beide
        # Tabellen wacht services/auftragsschluessel.py.
        CheckConstraint(
            "auftragsschluessel_offen IS NULL OR auftragsschluessel_offen = auftragsschluessel",
            name="ck_aufstellungen_auftragsschluessel_offen_wie_nachweis",
        ),
        Index(
            "uq_aufstellungen_auftragsschluessel_offen",
            "auftragsschluessel_offen",
            unique=True,
            postgresql_where=text("auftragsschluessel_offen IS NOT NULL"),
        ),
        Index(
            "uq_aufstellungen_ein_aktives_storno_pro_original", "storniert_id",
            unique=True,
            postgresql_where=text("status <> 'discarded' AND storniert_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = _id_col
    nummer: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    # draft | issued | cancelled | discarded — der Wertevorrat steht als CHECK
    # unten, die Maschine dafuer im aufstellung_guard.
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft", index=True
    )
    # NOT NULL im Unterschied zur Rechnung: Einem Rechnungsentwurf fehlt der
    # Kunde vielleicht noch, eine Aufstellung entsteht dagegen aus einem
    # § 8b-Auftrag, der ihn immer nennt — ohne Kunde ist sie nichts.
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=False
    )
    # Leistungsmonat, aus dem Auftrag gebunden; der Leser § 8b erzwingt genau
    # einen Kalendermonat.
    leistung_von: Mapped[date] = mapped_column(Date, nullable=False)
    leistung_bis: Mapped[date] = mapped_column(Date, nullable=False)
    # Die Zahlung des vorgelagerten Systems (§ 8b): Nummer und Datum sind
    # Angaben des Auftraggebers, keine Buchung von Abgehakt.
    zahlungsnummer: Mapped[str] = mapped_column(String(50), nullable=False)
    zahlungsdatum: Mapped[date] = mapped_column(Date, nullable=False)
    # Berichtswaehrung, drei Grossbuchstaben (kein Default: Die Waehrung
    # kommt aus dem Auftrag, ein Default waere ein erfundener Platzhalter).
    waehrung: Mapped[str] = mapped_column(String(3), nullable=False)
    brutto: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    quellensteuer: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    netto: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Der Kurs ist weder Geld noch Satz (§ 8b: Zeichenkette im Auftrag) —
    # deshalb Numeric OHNE Praezisionsgrenze; gerundet wird hier nicht.
    kurs: Mapped[Optional[Decimal]] = mapped_column(Numeric, nullable=True)
    zahlbetrag_eur: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    # Auftragsschluessel: Nachweis und Sperre, dieselben Regeln wie bei
    # invoices (Festlegung 12); gesetzt und geleert nur ueber
    # services/auftragsschluessel.py, die beide Tabellen sieht.
    auftragsschluessel: Mapped[Optional[str]] = mapped_column(Text)
    auftragsschluessel_offen: Mapped[Optional[str]] = mapped_column(Text)
    # Herkunft aus dem angenommenen § 8b-Auftrag: der Nachweis, aus welchem
    # Beleg die Zeile entstand.
    uebergabe_beleg_id: Mapped[Optional[str]] = mapped_column(String(64))
    uebergabe_beleg_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    bemerkung: Mapped[Optional[str]] = mapped_column(Text)
    # Nullable bis zum Finalisieren; der aufstellung_guard macht es beim
    # Uebergang zu issued zur Pflicht — ein gestellter Beleg ohne Datum
    # ist im GoBD-Sinn nicht existent.
    ausstellungsdatum: Mapped[Optional[date]] = mapped_column(Date)
    pdf_filename: Mapped[Optional[str]] = mapped_column(String(255))
    # Erstversand an die Buchhaltung (Bauschritt 5a, Entscheidung 6): einmal
    # setzen, nie aendern (aufstellung_guard). Der Kunde hat hier keinen
    # eigenen Vermerk — die Aufstellung geht nur an die Buchhaltung
    # (Entscheidung 9); auch Schritt 7d kennt keinen Kundenversand.
    datev_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    archive_until: Mapped[Optional[date]] = mapped_column(Date)
    # Storno als eigene Zeile (Festlegung 17): gesetzt an der Storno-Zeile,
    # zeigt auf das Original. Das Original selbst wird 'cancelled' und
    # behaelt seine Nummer.
    storniert_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aufstellungen.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    original: Mapped[Optional["Aufstellung"]] = relationship(
        "Aufstellung", remote_side=[_id_col], foreign_keys=[storniert_id],
    )
    customer: Mapped["Customer"] = relationship("Customer")  # noqa: F821
    # KEIN delete-cascade: Anlagen sind Nachweise, ihre Zeile zu entfernen
    # waere Loeschen von Belegbestandteilen — verboten (Trigger und Guard).
    anlagen: Mapped[list["AufstellungAnlage"]] = relationship(
        order_by="AufstellungAnlage.quelle",
    )


class AufstellungAnlage(Base):
    """Eine der genau zwei xlsx-Anlagen (§ 8b): abrechnungsbericht und
    zahlungsbericht, als byte-gleiche Kopie mit geprueftem SHA-256."""

    __tablename__ = "aufstellung_anlagen"

    __table_args__ = (
        CheckConstraint(
            "quelle IN ('abrechnungsbericht', 'zahlungsbericht')",
            name="ck_aufstellung_anlagen_quelle_wertevorrat",
        ),
        # Die Hash-Form hier, weil die Anlage der Nachweis ist: Ein Hash
        # ausserhalb der Form ist keine Pruefung, sondern eine Behauptung.
        CheckConstraint(
            "sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_aufstellung_anlagen_sha256_form",
        ),
        # Der Platz jeder Quelle ist fix: genau ein Abrechnungsbericht und
        # ein Zahlungsbericht je Aufstellung. Eine zweite Zeile derselben
        # Quelle waere eine zweite Behauptung ueber dieselbe Datei.
        UniqueConstraint(
            "aufstellung_id", "quelle",
            name="uq_aufstellung_anlagen_aufstellung_quelle",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    aufstellung_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("aufstellungen.id"), nullable=False
    )
    quelle: Mapped[str] = mapped_column(String(50), nullable=False)
    dateiname: Mapped[str] = mapped_column(String(255), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    groesse: Mapped[int] = mapped_column(Integer, nullable=False)
    medientyp: Mapped[str] = mapped_column(String(100), nullable=False)

    aufstellung: Mapped[Aufstellung] = relationship(back_populates="anlagen")
