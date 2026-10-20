from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.invoice import Invoice
from app.services.einheiten import UnknownUnitError, resolve_einheit
from app.services.invoice_number import generate_next_invoice_number
from app.services.rechnung.fehler import RechnungFehler
from app.services.rechnung.firma import get_company
from app.services.belegart import ist_storno
from app.services.storno import build_storno
from app.zeit import heute


def _original_laden(db: Session, original_id) -> Invoice:
    original = db.query(Invoice).filter(Invoice.id == original_id).first()
    if not original:
        raise RechnungFehler(404, "Rechnung nicht gefunden")
    if original.status not in ("issued", "paid"):
        raise RechnungFehler(400, "Nur finalisierte Rechnungen (issued/paid) können storniert werden.")
    if ist_storno(original.invoice_type):
        raise RechnungFehler(400, "Eine Stornorechnung kann nicht erneut storniert werden.")
    return original


def _vorhandene_gutschrift(
    db: Session, original_id, *, ausgenommen_id=None,
) -> Invoice | None:
    q = (
        db.query(Invoice)
        .filter(Invoice.original_invoice_id == original_id,
                Invoice.status != "discarded")
    )
    if ausgenommen_id is not None:
        q = q.filter(Invoice.id != ausgenommen_id)
    return q.order_by(Invoice.invoice_number).first()


def _gutschrift_existiert(nummer: str) -> RechnungFehler:
    return RechnungFehler(
        400,
        f"Zu dieser Rechnung existiert bereits die Gutschrift "
        f"{nummer}. Ein Beleg wird nur einmal storniert; "
        "eine zweite Gutschrift würde die Forderung doppelt mindern. Ist die "
        "vorhandene Gutschrift versehentlich entstanden, verwirf zuerst ihren "
        "Entwurf.",
    )


def _einzige_gutschrift_sichern(
    db: Session, original: Invoice, *, ausgenommen_id=None,
) -> None:
    # Pro Original höchstens EINE Gutschrift (#7). Zwei Gutschriften zum selben
    # Beleg mindern die Forderung doppelt: in der OPOS-Liste, in der DATEV-Buchung
    # und in der Umsatzsteuervoranmeldung.
    #
    # Auch ein noch OFFENER Entwurf blockiert. Sonst entstünden zwei Entwürfe, die
    # beide finalisierbar sind, und der Fehler fiele erst beim zweiten
    # Finalisieren auf, wenn bereits ein Beleg unveränderlich im Archiv liegt.
    #
    # Ein VERWORFENER Storno blockiert nicht: wer versehentlich storniert und den
    # Entwurf verwirft, muss den Beleg erneut stornieren können, sonst wäre ein
    # Fehlgriff endgültig.
    #
    # Die Prüfung steht VOR `generate_next_invoice_number`: der Zähler auf
    # `Company` wird beim Ziehen der Nummer erhöht, eine Ablehnung danach ließe
    # eine Nummernlücke ohne jeden Datensatz zurück — genau die Lücke, die #145
    # mit dem Status `discarded` vermeiden wollte.
    #
    # `ausgenommen_id` (#178): beim Zurueckholen darf die eigene Zeile nicht als
    # Konkurrenz zaehlen, sobald ihr Status schon wieder auf draft steht.
    vorhandene = _vorhandene_gutschrift(
        db, original.id, ausgenommen_id=ausgenommen_id,
    )
    if vorhandene:
        raise _gutschrift_existiert(vorhandene.invoice_number)


def _einheiten_sichern(original: Invoice) -> None:
    # Vor der Nummernvergabe: traegt der Beleg eine Einheit, die der Katalog nicht
    # kennt, dann erbt die Gutschrift sie (storno.py) und ist danach weder
    # finalisierbar (UNIT_UNKNOWN) noch bearbeitbar (der Stornoeditor ist gesperrt,
    # weil eine Gutschrift die Betraege des Originals unveraendert uebernimmt).
    # Das waere eine Sackgasse mit verbrauchter Rechnungsnummer. Lieber hier absagen
    # und den Wert benennen, als einen Entwurf anzulegen, der nie fertig wird.
    for pos in sorted(original.items, key=lambda i: i.position):
        try:
            resolve_einheit(pos.unit if pos.unit is not None else "")
        except UnknownUnitError:
            raise RechnungFehler(
                400,
                f"Position {pos.position} dieses Belegs traegt die Einheit "
                f"{(pos.unit or '')!r}, die der Einheitenkatalog nicht kennt. Eine "
                "Gutschrift uebernimmt die Angaben des Originals unveraendert und "
                "waere damit nicht finalisierbar. Der Wert muss zuerst im Beleg "
                "berichtigt werden; das geht nicht im Stornoweg.",
            ) from None


def _speichern(db: Session, storno: Invoice, original_id) -> None:
    db.add(storno)
    try:
        db.commit()
    except IntegrityError:
        # Zweite Schicht (#90): der partielle Unique-Index faengt den Wettlauf,
        # den die Vorabpruefung oben ohne Sperre nicht serialisiert. Rollback
        # nimmt die in derselben Transaktion gezogene Nummer mit zurueck: keine
        # Luecke ohne Datensatz. Die Meldung entspricht der Vorabpruefung.
        db.rollback()
        vorhandene = _vorhandene_gutschrift(db, original_id)
        nummer = vorhandene.invoice_number if vorhandene else "?"
        raise _gutschrift_existiert(nummer)


def entwurf_anlegen(db: Session, original_id) -> Invoice:
    """Stornorechnung (Gutschrift) als Entwurf zu einem gestellten Beleg anlegen."""
    original = _original_laden(db, original_id)
    _einzige_gutschrift_sichern(db, original)

    get_company(db)  # stellt sicher, dass Firmendaten konfiguriert sind (sonst 400)

    _einheiten_sichern(original)

    storno_datum = heute()
    number = generate_next_invoice_number(db, issue_date=storno_datum)
    storno = build_storno(original, number, storno_datum)
    _speichern(db, storno, original_id)
    return storno


def pruefe_zurueckholbar(db: Session, storno: Invoice) -> None:
    """Ob ein verworfener Storno-Entwurf wieder aktiv werden darf (#178).

    Wiederverwendet `_original_laden` und `_einzige_gutschrift_sichern`. Die
    zurueckzuholende Gutschrift selbst zaehlt nicht als vorhandene Konkurrenz.
    """
    if storno.original_invoice_id is None:
        return
    original = _original_laden(db, storno.original_invoice_id)
    _einzige_gutschrift_sichern(db, original, ausgenommen_id=storno.id)


def gutschrift_konflikt_nach_integrity(db: Session, storno: Invoice) -> None:
    """Zweite Schicht am Gutschrift-Index: IntegrityError → fachlicher Fehler."""
    if storno.original_invoice_id is None:
        return
    vorhandene = _vorhandene_gutschrift(
        db, storno.original_invoice_id, ausgenommen_id=storno.id,
    )
    if vorhandene is not None:
        raise _gutschrift_existiert(vorhandene.invoice_number)
