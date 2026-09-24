"""Pro Original hoechstens eine nicht verworfene Gutschrift (#90).

Die Vorabpruefung in `create_storno` nimmt keine Sperre. Zwei ueberlappende
Anfragen lesen beide "keine vorhanden" und legen beide an. Die Zusage gehoert
deshalb in die Datenbank: ein partieller Unique-Index auf `original_invoice_id`
fuer Zeilen mit `status <> 'discarded'`.

Gemessen wird an zwei Sitzungen derselben Datenbank, ohne Threads: beide lesen,
beide schreiben; die zweite muss beim Schreiben scheitern. Ein Test mit
Attrappen-Datenbank bliebe gruen, waehrend echter Code bricht.
"""
import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models.company import Company
from app.models.invoice import Invoice, InvoiceItem
from app.routers.invoices import create_storno
from tests.test_storno_integration import _original, _zaehler


INDEX_NAME = "uq_invoices_eine_aktive_gutschrift_pro_original"


def _gutschrift(
    *,
    original_id,
    customer_id,
    net_total,
    tax_total,
    gross_total,
    number: str,
    status: str = "draft",
) -> Invoice:
    inv = Invoice(
        invoice_number=number,
        customer_id=customer_id,
        issue_date=date(2025, 6, 12),
        due_date=date(2025, 6, 12),
        currency="EUR",
        zugferd_profile="EN16931",
        tax_category="S",
        status=status,
        invoice_type="credit_note",
        original_invoice_id=original_id,
        net_total=net_total,
        tax_total=tax_total,
        gross_total=gross_total,
    )
    inv.items = [
        InvoiceItem(
            position=1,
            description="Storno",
            unit="Std",
            quantity=Decimal("1"),
            unit_price=net_total,
            tax_rate=Decimal("19"),
            net_amount=net_total,
            tax_amount=tax_total,
            gross_amount=gross_total,
        )
    ]
    return inv


def _felder(original):
    return {
        "original_id": original.id,
        "customer_id": original.customer_id,
        "net_total": original.net_total,
        "tax_total": original.tax_total,
        "gross_total": original.gross_total,
    }


def test_zweite_aktive_gutschrift_scheitert_am_schreiben(pg_session, pg_engine):
    """Wettlauf ohne Threads: beide lesen leer, beide schreiben; die zweite fliegt.

    Vor dem partiellen Unique-Index committen beide. Danach muss der zweite
    Commit mit IntegrityError scheitern, und genau eine aktive Gutschrift bleiben.
    """
    original = _original(pg_session, "issued")
    felder = _felder(original)
    original_id = felder["original_id"]
    pg_session.close()

    Session = sessionmaker(bind=pg_engine)
    a, b = Session(), Session()
    try:
        assert (
            a.query(Invoice)
            .filter(
                Invoice.original_invoice_id == original_id,
                Invoice.status != "discarded",
            )
            .count()
            == 0
        )
        assert (
            b.query(Invoice)
            .filter(
                Invoice.original_invoice_id == original_id,
                Invoice.status != "discarded",
            )
            .count()
            == 0
        )

        a.add(_gutschrift(**felder, number=f"GS-A-{uuid.uuid4().hex[:6]}"))
        a.commit()

        b.add(_gutschrift(**felder, number=f"GS-B-{uuid.uuid4().hex[:6]}"))
        with pytest.raises(IntegrityError):
            b.commit()
        b.rollback()

        pruefer = Session()
        try:
            aktiv = (
                pruefer.query(Invoice)
                .filter(
                    Invoice.original_invoice_id == original_id,
                    Invoice.status != "discarded",
                )
                .count()
            )
            assert aktiv == 1, (
                f"Zum selben Original liegen {aktiv} aktive Gutschriften; "
                "der partielle Unique-Index fehlt oder greift nicht."
            )
        finally:
            pruefer.close()
    finally:
        a.rollback()
        a.close()
        b.rollback()
        b.close()


def test_verworfene_gutschrift_sperrt_den_index_nicht(pg_session, pg_engine):
    """Die discarded-Ausnahme muss in der Datenbankzusage stehen, nicht nur im Router.

    Sonst waere ein Fehlgriff endgueltig: wer den Storno-Entwurf verwirft, koennte
    denselben Beleg nicht erneut stornieren.
    """
    original = _original(pg_session, "issued")
    felder = _felder(original)
    original_id = felder["original_id"]
    pg_session.close()

    Session = sessionmaker(bind=pg_engine)
    s = Session()
    try:
        s.add(
            _gutschrift(
                **felder,
                number=f"GS-D-{uuid.uuid4().hex[:6]}",
                status="discarded",
            )
        )
        s.commit()
        s.add(
            _gutschrift(
                **felder,
                number=f"GS-N-{uuid.uuid4().hex[:6]}",
                status="draft",
            )
        )
        s.commit()

        offen = (
            s.query(Invoice)
            .filter(
                Invoice.original_invoice_id == original_id,
                Invoice.status != "discarded",
            )
            .count()
        )
        assert offen == 1
        gesamt = (
            s.query(Invoice)
            .filter(Invoice.original_invoice_id == original_id)
            .count()
        )
        assert gesamt == 2
    finally:
        s.rollback()
        s.close()


def test_modell_kennt_den_partiellen_unique_index():
    """Quelle fuer create_all und alembic check; sonst Drift wie bei #003."""
    indizes = {i.name: i for i in Invoice.__table__.indexes}
    assert INDEX_NAME in indizes, sorted(indizes)
    idx = indizes[INDEX_NAME]
    assert idx.unique
    where = str(idx.dialect_options.get("postgresql", {}).get("where", ""))
    assert "discarded" in where, where


def test_partieller_unique_index_liegt_in_der_datenbank(pg_engine):
    indizes = {i["name"]: i for i in inspect(pg_engine).get_indexes("invoices")}
    assert INDEX_NAME in indizes, sorted(indizes)
    assert indizes[INDEX_NAME]["unique"] is True


def test_integritaetskollision_liefert_400_mit_gutschriftnummer(
    pg_session, pg_engine,
):
    """Wenn der Index greift, bevor die Vorabpruefung es tut: 400, kein 500.

    Nachstellung ohne Threads: vor dem Commit der Router-Sitzung schiebt eine
    zweite Sitzung die konkurrierende Gutschrift ein (wie der Gewinner eines
    Wettlaufs). Der Verlierer muss dieselbe fachliche Meldung sehen wie bei der
    Vorabpruefung.
    """
    original = _original(pg_session, "issued")
    felder = _felder(original)
    original_id = felder["original_id"]
    pg_session.close()

    Session = sessionmaker(bind=pg_engine)
    db = Session()

    def _nebenbuhler_einschleusen(session):
        if getattr(session, "_storno_kollision_gesetzt", False):
            return
        session._storno_kollision_gesetzt = True
        other = Session()
        try:
            other.add(
                _gutschrift(
                    **felder,
                    number=f"GS-W-{uuid.uuid4().hex[:6]}",
                    status="draft",
                )
            )
            other.commit()
        finally:
            other.close()

    event.listen(db, "before_commit", _nebenbuhler_einschleusen)
    try:
        with pytest.raises(HTTPException) as fehler:
            create_storno(original_id, db=db)
        assert fehler.value.status_code == 400, fehler.value
        assert "existiert bereits die Gutschrift" in str(fehler.value.detail)
        assert "GS-W-" in str(fehler.value.detail)
    finally:
        event.remove(db, "before_commit", _nebenbuhler_einschleusen)
        db.rollback()
        db.close()

    pruefer = Session()
    try:
        aktiv = (
            pruefer.query(Invoice)
            .filter(
                Invoice.original_invoice_id == original_id,
                Invoice.status != "discarded",
            )
            .count()
        )
        assert aktiv == 1
    finally:
        pruefer.close()


def test_integritaetskollision_verbraucht_keine_rechnungsnummer(
    pg_session, pg_engine,
):
    """Rollback nach IntegrityError muss den Zaehler mitzuruecknehmen.

    `generate_next_invoice_number` erhoeht den Zaehler per flush in derselben
    Transaktion. Scheitert erst der Commit am Index, darf nach dem Rollback keine
    Nummernluecke ohne Datensatz bleiben.
    """
    original = _original(pg_session, "issued")
    felder = _felder(original)
    original_id = felder["original_id"]
    vorher = _zaehler(pg_session)
    pg_session.close()

    Session = sessionmaker(bind=pg_engine)
    db = Session()

    def _nebenbuhler_einschleusen(session):
        if getattr(session, "_storno_kollision_gesetzt", False):
            return
        session._storno_kollision_gesetzt = True
        other = Session()
        try:
            other.add(
                _gutschrift(
                    **felder,
                    number=f"GS-Z-{uuid.uuid4().hex[:6]}",
                    status="draft",
                )
            )
            other.commit()
        finally:
            other.close()

    event.listen(db, "before_commit", _nebenbuhler_einschleusen)
    try:
        with pytest.raises(HTTPException) as fehler:
            create_storno(original_id, db=db)
        assert fehler.value.status_code == 400
    finally:
        event.remove(db, "before_commit", _nebenbuhler_einschleusen)
        db.rollback()
        db.close()

    pruefer = Session()
    try:
        # Der Nebenbuhler nutzt eine freie Nummer ohne generate_next_invoice_number.
        # Der Verlierer hat per Router eine Nummer gezogen und muss sie per
        # Rollback zurueckgeben.
        assert pruefer.query(Company).filter_by(id=1).one().invoice_counter == vorher
    finally:
        pruefer.close()
