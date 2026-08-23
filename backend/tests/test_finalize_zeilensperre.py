"""
Zwei gleichzeitige Finalisierungen desselben Entwurfs (#6, Sperrteil).

Der Dateiteil dieses Berichts ist erledigt: die Pipeline arbeitet seit
`test_finalize_archiv_sauber.py` in einem eigenen Wegwerf-Verzeichnis, zwei Läufe
löschen sich die Zwischenstufen nicht mehr gegenseitig weg. Der teure Rest steht
noch. Zwei Anfragen lesen denselben Entwurf, beide sehen `draft`, und beide starten
Ghostscript und Mustang für denselben Beleg. Das kostet nicht nur Sekunden doppelt:
der zweite Lauf veroeffentlicht am Ende ueber den fertigen Beleg des ersten hinweg,
und was dann im Archiv liegt, entstand aus einem Zustand, den niemand geprueft hat.

Die Zusage dieser Datei: die Finalisierung fasst die Zeile an, bevor sie arbeitet.
Wer die Sperre nicht bekommt, wartet; wer sie bekommt, liest den Status neu. Der
Verlierer laeuft deshalb in ein sauberes „Nur Entwuerfe koennen finalisiert werden",
statt eine zweite Pipeline zu starten.

Gemessen wird an `pdf_generator.generate_pdf`: das ist der erste teure Schritt und
zugleich der erste, der ueberhaupt etwas erzeugt. Wird er beim Verlierer aufgerufen,
lief die Pipeline, und dann ist es einerlei, woran sie hinterher scheitert.
"""
import threading
import time
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.models.customer import Customer
from app.models.invoice import Invoice, InvoiceItem
from app.routers.invoices import finalize_invoice


def _valid_draft(pg_session) -> uuid.UUID:
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name="Kunde GmbH",
                 address_line1="Weg 1", zip_code="10115", city="Berlin", country="DE")
    pg_session.add(c)
    pg_session.flush()
    inv = Invoice(invoice_number=f"RE-LOCK-{uuid.uuid4().hex[:6]}", customer_id=c.id,
                  issue_date=date(2026, 7, 8), delivery_date=date(2026, 7, 8),
                  due_date=date(2026, 7, 22), currency="EUR", zugferd_profile="EN16931",
                  tax_category="S", status="draft", payment_terms="14 Tage netto",
                  net_total=Decimal("200.00"), tax_total=Decimal("38.00"),
                  gross_total=Decimal("238.00"))
    inv.items = [InvoiceItem(position=1, description="Beratung", unit="Std",
                             quantity=Decimal("2"), unit_price=Decimal("100.00"),
                             tax_rate=Decimal("19"), net_amount=Decimal("200.00"),
                             tax_amount=Decimal("38.00"), gross_amount=Decimal("238.00"))]
    pg_session.add(inv)
    pg_session.commit()
    return inv.id


@pytest.fixture()
def anfrage_session(pg_engine):
    """Eigene Session fuer den Routenaufruf, wie im Betrieb eine eigene pro Anfrage.

    Bewusst nicht `pg_session`: dort liegt der Entwurf bereits im Identitaetsspeicher,
    und dann bewiese der Test die Sperre nur fuer einen Sonderfall, den es im Betrieb
    nicht gibt.
    """
    session = sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)()
    # Ohne Zeitgrenze wartet der Verlierer im roten Fall bis zum Sankt-Nimmerleins-Tag
    # und der Test haengt, statt fehlzuschlagen.
    session.execute(text("SET lock_timeout = '3s'"))
    session.commit()
    yield session
    session.rollback()
    session.close()


def test_verlierer_startet_die_pipeline_nicht_solange_die_zeile_gehalten_wird(
        pg_session, pg_engine, anfrage_session):
    """Ein anderer Lauf haelt die Zeile: die Pipeline darf gar nicht erst anlaufen."""
    invoice_id = _valid_draft(pg_session)

    halter = sessionmaker(bind=pg_engine)()
    halter.execute(text("SELECT id FROM invoices WHERE id = :i FOR UPDATE"),
                   {"i": str(invoice_id)})
    anfrage_session.execute(text("SET lock_timeout = '400ms'"))
    anfrage_session.commit()
    try:
        with patch("app.routers.invoices.pdf_generator.generate_pdf") as erzeuge:
            with pytest.raises(OperationalError):
                finalize_invoice(invoice_id, db=anfrage_session)
        erzeuge.assert_not_called()
    finally:
        halter.rollback()
        halter.close()


def test_verlierer_sieht_nach_der_sperre_den_neuen_status(pg_session, pg_engine,
                                                          anfrage_session):
    """Der Gewinner committet waehrend der Verlierer wartet. Danach ist es kein Entwurf mehr."""
    invoice_id = _valid_draft(pg_session)

    gewinner_haelt = threading.Event()
    gewinner_fertig = threading.Event()

    def gewinner():
        session = sessionmaker(bind=pg_engine)()
        try:
            session.execute(text("SELECT id FROM invoices WHERE id = :i FOR UPDATE"),
                            {"i": str(invoice_id)})
            gewinner_haelt.set()
            time.sleep(0.5)          # solange steht der Verlierer in der Sperre
            session.execute(text("UPDATE invoices SET status = 'issued' WHERE id = :i"),
                            {"i": str(invoice_id)})
            session.commit()
        finally:
            session.rollback()
            session.close()
            gewinner_fertig.set()

    faden = threading.Thread(target=gewinner)
    faden.start()
    assert gewinner_haelt.wait(timeout=5), "Der Gewinner bekam die Zeile nicht"
    try:
        with patch("app.routers.invoices.pdf_generator.generate_pdf") as erzeuge:
            with pytest.raises(HTTPException) as fehler:
                finalize_invoice(invoice_id, db=anfrage_session)
        assert fehler.value.status_code == 400
        assert "Entwürfe" in fehler.value.detail
        erzeuge.assert_not_called()
    finally:
        faden.join(timeout=10)

    assert gewinner_fertig.is_set()


def test_der_gewinner_finalisiert_ungehindert(pg_session, pg_engine, anfrage_session):
    """Gutfall: ohne Nebenbuhler kommt die Sperre keinem in die Quere.

    Ohne diesen Test bliebe eine Sperre gruen, die schlicht jeden Lauf abweist.
    """
    invoice_id = _valid_draft(pg_session)

    with patch("app.routers.invoices.pdf_generator.generate_pdf") as erzeuge:
        with pytest.raises(HTTPException) as fehler:
            finalize_invoice(invoice_id, db=anfrage_session)
    # Die Pipeline lief los und scheiterte erst an der fehlenden PDF-Stufe, nicht an
    # der Statuspruefung: genau das unterscheidet den Gewinner vom Verlierer.
    erzeuge.assert_called_once()
    assert fehler.value.status_code == 400
    assert "Entwürfe" not in fehler.value.detail
