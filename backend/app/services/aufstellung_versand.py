"""Nur das archivierte PDF/A an die Upload-Adresse, ohne Kundenempfaenger."""
from datetime import datetime, timezone
from pathlib import Path

from app.models.aufstellung import Aufstellung
from app.models.aufstellung_send_log import AufstellungSendLog
from app.models.company import Company
from app.services import datev_email, mailtext


class VersandFehler(ValueError):
    """Verstaendlicher Fehler vor oder beim Versand."""


def senden(db, aufstellung, settings):
    if aufstellung.status != "issued" or not aufstellung.pdf_filename:
        raise VersandFehler("Nur eine gestellte Aufstellung mit archiviertem PDF kann versandt werden.")
    pfad = Path(settings.storage_path) / "aufstellungen" / aufstellung.pdf_filename
    if not pfad.is_file():
        raise VersandFehler("Das archivierte PDF der Aufstellung fehlt.")
    upload = datev_email.upload_adresse(db)
    if not upload:
        raise VersandFehler("Keine Upload-Adresse der Buchhaltung konfiguriert. Bitte in den Einstellungen hinterlegen.")
    company = db.query(Company).filter(Company.id == 1).first()
    inhalt = mailtext.aufstellung_buchhaltungsmail(aufstellung, company)
    log = AufstellungSendLog(aufstellung_id=aufstellung.id, ziel="buchhaltung",
                            to_email=upload, success=None)
    db.add(log)
    # Vor SMTP dauerhaft offen protokollieren: Scheitert der spaetere Commit,
    # bleibt der Ausgang unbekannt statt einer falschen Behauptung "nicht gesendet".
    db.commit()
    try:
        datev_email.send_invoice(to_email=upload, mailinhalt=inhalt, pdf_path=pfad,
                                 bcc_datev=False, cc_email="", db=db)
    except datev_email.EmailError as fehler:
        log.success, log.error = False, str(fehler)
        db.commit()
        raise VersandFehler(str(fehler)) from fehler
    # Nach SMTP erneut sperren und frisch lesen: Ein paralleler Versand darf
    # den Erstvermerk nicht ueberschreiben (der vorherige Commit loest Sperren).
    aufstellung = db.query(Aufstellung).filter(
        Aufstellung.id == log.aufstellung_id,
    ).populate_existing().with_for_update().one()
    if aufstellung.datev_sent_at is None:
        aufstellung.datev_sent_at = datetime.now(timezone.utc)
    log.success = True
    db.commit()
