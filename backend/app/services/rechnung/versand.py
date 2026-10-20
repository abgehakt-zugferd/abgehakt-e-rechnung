from datetime import date, datetime, timezone
from functools import partial
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.app_config import AppConfig
from app.models.company import Company
from app.models.invoice import Invoice, InvoiceSendLog
from app.services import datev_email, empfaenger, mailtext, mustang
from app.services.belegsprache import UnknownDocumentLanguageError
from app.services.rechnung.fehler import RechnungFehler
from app.zeit import ZEITZONE, heute


def empfaenger_adresse(invoice: Invoice, customer_email: str) -> str:
    """Zieladresse des Standardversands: Formularwert, sonst die E-Mail des Kunden."""
    to_email = customer_email or (invoice.customer.email if invoice.customer else "")
    if not to_email:
        raise RechnungFehler(400, "Keine E-Mail-Adresse des Kunden bekannt.")
    return to_email


def pruefe_versandgrundlage(invoice: Invoice) -> Path:
    """Vorprüfungen, die für JEDE Versandart gelten (Bauschritt 5a): Status,
    PDF-Existenz und die Mustang-Beweispflicht für die eingebettete XML.

    Warum eine Stelle: Der Standardversand und der Weg nur an die Buchhaltung
    teilen dieselben Regeln — eine Kopie würde auseinanderlaufen, und ein
    Beleg, der an einem Weg durchgeht, muss am anderen nicht anders prüfen.
    """
    if invoice.status not in ("issued", "paid"):
        raise RechnungFehler(400, "Nur finalisierte Rechnungen können gesendet werden.")
    if not invoice.pdf_filename:
        raise RechnungFehler(400, "Kein PDF vorhanden. Bitte zuerst finalisieren.")
    # Fail-closed (#98 P0.1): nur ein ZUGFeRD-PDF (mit eingebetteter XML) darf raus.
    # Ein reines Visual-PDF (*_visual.pdf) ist keine gültige E-Rechnung.
    if invoice.pdf_filename.endswith("_visual.pdf"):
        raise RechnungFehler(
            400,
            "PDF ohne eingebettete E-Rechnung (Visual-PDF) darf nicht versendet "
            "werden. Rechnung erneut finalisieren, um ein ZUGFeRD-PDF zu erzeugen.",
        )
    # E3 (#98 Hardness): der Dateiname (`_visual`-Suffix) ist nur eine Vorabprüfung
    # und beweist nichts über den Inhalt — ein bares ReportLab-PDF ohne eingebettete
    # ZUGFeRD-XML hätte den Suffix-Check passiert. Verbindlich ist Mustang
    # (mustang.ist_gueltige_e_rechnung). Ohne Mustang lässt sich die Einbettung
    # nicht beweisen → nicht senden (fail-closed).
    if not mustang.jar_available():
        raise RechnungFehler(
            400, "E-Rechnungs-Validierung nicht möglich (Mustang nicht verfügbar) — "
            "Versand abgebrochen.")
    pdf_path = get_settings().storage_path / "pdfs" / invoice.pdf_filename
    validation = mustang.validate(pdf_path)
    if not mustang.ist_gueltige_e_rechnung(validation):
        raise RechnungFehler(
            400, "PDF enthält keine gültig eingebettete E-Rechnung (Mustang-"
            "Validierung fehlgeschlagen). Bitte die Rechnung erneut finalisieren.")
    return pdf_path


def vermerk_einmal_setzen(invoice: Invoice, attr: str, zeit: datetime) -> None:
    """Versand-/Zustellvermerk nur beim ersten Mal setzen (Muster
    datev_sent_at, #98 P0.3): Ein bedingungsloses Setzen liefe beim zweiten
    Versand am invoice_guard in den Fehler, und der Vermerk bliebe der
    Erstversand. Die weiteren Versuche stehen im Protokoll. Der Zeitpunkt
    kommt vom Aufrufer, damit EIN Versand auch für beide Vermerke EINEN
    Zeitpunkt hat."""
    if getattr(invoice, attr) is None:
        setattr(invoice, attr, zeit)


def _zustellversuch(db: Session, protokoll: InvoiceSendLog, senden: Callable[[], None]) -> None:
    """Mail absetzen und den Ausgang im Protokoll nachtragen (Fehler: committet, dann Abbruch)."""
    try:
        senden()
    except (
        UnknownDocumentLanguageError,
        mailtext.BetreffMitZeilenumbruchError,
        datev_email.EmailError,
    ) as e:
        protokoll.success = False
        protokoll.error = str(e)
        db.commit()
        raise RechnungFehler(400, str(e)) from e
    except Exception as e:
        # Jede unerwartete Ausnahme schliesst den Nachweis; still schlucken waere schlimmer.
        protokoll.success = False
        protokoll.error = str(e)
        db.commit()
        raise


def _cc_bestimmen(cc_email: str, to_email: str) -> str:
    cc_fehler = empfaenger.pruefe(cc_email)
    if cc_fehler:
        raise RechnungFehler(400, cc_fehler)
    # `ohne=to_email`: wer im An-Feld steht, bekaeme die Rechnung sonst zweimal.
    return empfaenger.normalisiere(cc_email, ohne=to_email)


def _standard_protokoll(invoice: Invoice, to_email: str, cc: str, upload: str | None) -> InvoiceSendLog:
    # `ziel` benennt den gewaehlten WEG des Standardversands (Kunde und, wenn
    # konfiguriert, Buchhaltung als Blindkopie). Die tatsaechlichen Empfaenger
    # stehen in to_email/cc_email/datev_bcc — fehlt die Upload-Adresse, ist die
    # Blindkopie weg, und genau diese Abweichung traegt weg_notiz, statt den Weg
    # still umzudeuten.
    return InvoiceSendLog(
        invoice_id=invoice.id, ziel="kunde_und_buchhaltung", to_email=to_email,
        cc_email=cc or None, datev_bcc=bool(upload), success=None,
        weg_notiz=None if upload else (
            "Upload-Adresse der Buchhaltung nicht konfiguriert — keine "
            "Blindkopie, nur an den Kunden gesendet."
        ),
    )


def _standardmail_senden(db: Session, invoice: Invoice, to_email: str, cc: str, pdf_path: Path) -> None:
    company = db.query(Company).filter(Company.id == 1).first()
    config = db.query(AppConfig).filter(AppConfig.id == 1).first()
    inhalt = mailtext.rechnungsmail(invoice, company, config)
    datev_email.send_invoice(
        to_email=to_email,
        mailinhalt=inhalt,
        pdf_path=pdf_path,
        bcc_datev=True,
        db=db,
        cc_email=cc,
    )


def _standard_vermerke(db: Session, invoice: Invoice, protokoll: InvoiceSendLog,
                       upload: str | None) -> None:
    protokoll.success = True
    # Zwei getrennte Vermerke (Entscheidung 6): Der Standardversand beliefert
    # den Kunden immer und die Buchhaltung, soweit eine Upload-Adresse steht.
    # Ohne sie ist der Vermerk „an die Buchhaltung" eine Behauptung, die niemand
    # pruefen kann — er bleibt dann leer, und der Beleg gilt weiter als bei der
    # Buchhaltung nicht eingegangen. Beide nur beim ersten Mal (guardgesichert)
    # und mit dem Zeitpunkt DIESES Versands.
    jetzt = datetime.now(timezone.utc)
    vermerk_einmal_setzen(invoice, "kunde_zugestellt_am", jetzt)
    if upload:
        vermerk_einmal_setzen(invoice, "datev_sent_at", jetzt)
    db.commit()


def an_kunde_und_buchhaltung(db: Session, invoice: Invoice, to_email: str, cc_email: str) -> None:
    """Standardversand: Kunde, CC und (mit Upload-Adresse) Blindkopie an die Buchhaltung."""
    pdf_path = pruefe_versandgrundlage(invoice)
    # Entscheidet beides: ob die Mail eine Blindkopie an die Upload-Adresse
    # bekommt (`send_invoice` lässt sie still weg, wenn keine konfiguriert
    # ist — so läuft es heute) und welcher Vermerk am Ende gesetzt wird.
    upload = datev_email.upload_adresse(db)

    # Ab hier findet ein echter Zustellversuch statt — erst ab hier wird
    # protokolliert (#146). Ein an den Vorprüfungen gescheiterter Aufruf hat nie
    # gesendet und gehört nicht ins Versandprotokoll.
    #
    # Der Versuch wird geschrieben und committet, BEVOR SMTP angesprochen wird (#10).
    # Vorher lief es andersherum, und ein Commit-Fehler nach erfolgreichem Versand
    # hinterliess keine Spur: die Mail war beim Kunden und beim Steuerbuero, die
    # Datenbank sagte „nie gesendet", und der naechste Klick schickte den Beleg ein
    # zweites Mal. Der Ausgang ist zu diesem Zeitpunkt offen (`success = None`) und
    # wird unten nachgetragen; bleibt er offen stehen, ist genau das die Auskunft:
    # die Mail koennte drausssen sein, bitte im Postausgang nachsehen.
    # Vor `db.add(protokoll)` (#58): eine abgelehnte Eingabe hat nie gesendet und
    # darf keine Protokollzeile mit offenem Ausgang hinterlassen, die spaeter wie
    # ein moeglicher Zweitversand aussieht.
    cc = _cc_bestimmen(cc_email, to_email)
    protokoll = _standard_protokoll(invoice, to_email, cc, upload)
    db.add(protokoll)
    db.commit()
    _zustellversuch(db, protokoll,
                    partial(_standardmail_senden, db, invoice, to_email, cc, pdf_path))
    _standard_vermerke(db, invoice, protokoll, upload)


def _buchhaltungsmail_senden(db: Session, invoice: Invoice, upload: str, pdf_path: Path) -> None:
    company = db.query(Company).filter(Company.id == 1).first()
    inhalt = mailtext.buchhaltungsmail(invoice, company)
    datev_email.send_invoice(
        to_email=upload,
        mailinhalt=inhalt,
        pdf_path=pdf_path,
        bcc_datev=False,
        db=db,
    )


def an_buchhaltung(db: Session, invoice: Invoice) -> None:
    """Nur an die Buchhaltung (Entscheidung 6): Mail allein an die Upload-Adresse,
    neutrale Schablone ohne Kundenanrede (Festlegung 16), keine Blindkopie und
    kein CC — der Kunde bleibt offen, kunde_zugestellt_am bleibt unberührt."""
    pdf_path = pruefe_versandgrundlage(invoice)
    upload = datev_email.upload_adresse(db)
    if not upload:
        # Ein Knopf ohne Ziel wäre ein 500er — derselbe Fall wie „SMTP nicht
        # konfiguriert" eine Zeile tiefer im Dienst: verständlich, vor dem
        # Protokoll, ohne dass etwas gesendet wurde.
        raise RechnungFehler(
            400,
            "Keine Upload-Adresse der Buchhaltung konfiguriert. Bitte in den "
            "Einstellungen die DATEV-Upload-Adresse hinterlegen.",
        )

    # Wie beim Standardversand (#10/#146): erst der committete Versuch mit
    # offenem Ausgang, dann SMTP, dann der Nachtrag des Ergebnisses.
    protokoll = InvoiceSendLog(
        invoice_id=invoice.id, ziel="buchhaltung", to_email=upload,
        datev_bcc=False, success=None,
    )
    db.add(protokoll)
    db.commit()
    _zustellversuch(db, protokoll,
                    partial(_buchhaltungsmail_senden, db, invoice, upload, pdf_path))

    protokoll.success = True
    # Nur der Vermerk der Buchhaltung — der Kunde hat mit diesem Weg nichts
    # erhalten, also bleibt kunde_zugestellt_am unberührt und der Beleg gilt
    # weiter als „nicht versendet" (Entscheidung 6).
    vermerk_einmal_setzen(invoice, "datev_sent_at", datetime.now(timezone.utc))
    db.commit()


def zustellung_eingabe(invoice: Invoice, datum: str, weg: str) -> tuple[date, str]:
    """Formulareingabe der Handzustellung prüfen: (Zustelltag, getrimmter Weg).

    Reihenfolge wie im Formularweg: Status, Weg, Datumsformat.
    """
    if invoice.status not in ("issued", "paid"):
        raise RechnungFehler(
            400, "Eine Zustellung lässt sich nur zu gestellten Belegen vermerken.")
    weg = weg.strip()
    if not weg:
        raise RechnungFehler(
            400, "Bitte den Weg der Zustellung angeben, etwa „Upload in das Kundenportal“.")
    try:
        tag = date.fromisoformat(datum)
    except ValueError:
        raise RechnungFehler(400, "Bitte das Datum der Zustellung angeben (JJJJ-MM-TT).")
    return tag, weg


def zustellung_vermerken(db: Session, invoice: Invoice, tag: date, weg: str) -> None:
    """Zustellung an den Kunden von Hand vermerken (Bauschritt 5b, Teil 2).

    Nicht jede Zustellung geht durch dieses Programm: Upload in ein Kunden-
    portal, Aushaendigung, Fax. Der Vermerk zeichnet so einen Vorgang NACH und
    ist die Behauptung des Nutzers, nicht das Ergebnis eines Versands — deshalb
    kein SMTP, keine Versandgrundlage (`pruefe_versandgrundlage` prueft das
    PDF auf dem Weg zu einem VERSAND; der Beleg wurde ausserhalb bereits
    zugesellt) und `success = True` im Protokoll.

    `tag` und `weg` kommen aus `zustellung_eingabe`.
    """
    # Grenzen in Europe/Berlin (app.zeit), nicht nach der Uhr des Containers:
    # „heute" ist der Kalendertag der Anwenderin.
    if tag > heute():
        raise RechnungFehler(400, "Das Datum der Zustellung liegt in der Zukunft.")
    if tag < invoice.issue_date:
        raise RechnungFehler(
            400, "Das Datum der Zustellung liegt vor dem Ausstellungsdatum.")
    # sent_at traegt das GEWAEHLTE Zustelldatum, nicht den Erfassungszeitpunkt:
    # Das Protokoll sortiert nach sent_at (Modell, „neueste zuerst"), und eine
    # Korrektur mit frueherem Zustelldatum muesste sonst obenauf stehen. Der
    # Erfassungszeitpunkt ist bewusst nicht gesondert gesichert — der Nachweis
    # gilt der Zustellung, nicht dem Erfassen.
    zustell_zeit = datetime(tag.year, tag.month, tag.day, tzinfo=ZEITZONE)
    protokoll = InvoiceSendLog(
        invoice_id=invoice.id, ziel="kunde_vermerk", to_email=None,
        weg_notiz=weg, sent_at=zustell_zeit, success=True,
    )
    db.add(protokoll)
    # Erstvermerk wie bei jedem Weg: einmal setzen, nie aendern (invoice_guard,
    # GoBD). Die Korrektur steht allein im Protokoll.
    vermerk_einmal_setzen(invoice, "kunde_zugestellt_am", zustell_zeit)
    db.commit()
