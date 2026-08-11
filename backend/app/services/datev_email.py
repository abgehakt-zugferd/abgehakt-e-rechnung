"""
Sendet ZUGFeRD-Rechnungs-PDF per SMTP an Kunden + BCC an DATEV Upload Mail.
DATEV Upload Mail akzeptiert nur PDF (kein reines XML).
Es wird genau EIN PDF-Anhang pro E-Mail versendet; das 20-MB-Limit von DATEV
wird geprüft (send_invoice). (Eine Mehr-Anhänge-/Sammelversand-Funktion gibt es
bewusst nicht — je Rechnung eine Mail.)
"""
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from app.config import get_settings
from sqlalchemy.orm import Session
from app.models.app_config import AppConfig
from app.models.company import Company

settings = get_settings()


class EffectiveSettings:
    """Effektive SMTP-/DATEV-Konfiguration: DB-Werte (AppConfig) überschreiben .env.

    Ein leerer/None-DB-Wert fällt auf den .env-Wert zurück. Ausnahme smtp_use_tls:
    hier zählt ausdrücklich `is not None`, damit ein bewusstes False in der DB nicht
    vom .env-Default True überschrieben wird.
    """

    # Felder mit einfacher "DB oder .env"-Semantik
    _OR_FIELDS = ("smtp_host", "smtp_port", "smtp_user",
                  "smtp_from", "datev_bcc_email")

    def __init__(self, db_config, base):
        self._base = base
        self._db = db_config

    def __getattr__(self, name):
        # __getattr__ greift nur, wenn das Attribut nicht anders gefunden wird.
        if name in ("_base", "_db"):
            raise AttributeError(name)
        if name == "smtp_use_tls":
            db_val = self._db.smtp_use_tls
            return db_val if db_val is not None else self._base.smtp_use_tls
        if name == "smtp_password":
            # DB-Wert ist verschlüsselt → entschlüsseln; sonst .env-Fallback (Klartext)
            from app.services import crypto
            db_val = self._db.smtp_password
            if db_val:
                return crypto.decrypt(db_val)
            return self._base.smtp_password
        if name in self._OR_FIELDS:
            return getattr(self._db, name) or getattr(self._base, name)
        return getattr(self._base, name)


def _get_effective_smtp_config(db: Session | None = None):
    """
    Lädt SMTP-Konfiguration: zuerst aus AppConfig (DB), dann aus .env.
    Falls db=None oder keine AppConfig-Zeile existiert, werden die .env-Werte verwendet.
    """
    if db is None:
        return settings

    config = db.query(AppConfig).filter(AppConfig.id == 1).first()
    if not config:
        return settings

    return EffectiveSettings(config, settings)


class EmailError(Exception):
    pass


def _company(db: Session | None):
    if db is None:
        return None
    return db.query(Company).filter(Company.id == 1).first()


def _anschrift(company) -> str:
    """„Name, Straße, PLZ Ort" — leer, wenn die Firma unvollständig ist."""
    if not company:
        return ""
    teile = [(company.name or "").strip(), (company.address_line1 or "").strip()]
    ort = " ".join(t for t in ((company.zip_code or "").strip(),
                               (company.city or "").strip()) if t)
    teile.append(ort)
    return ", ".join(t for t in teile if t)


def build_invoice_body(invoice_number: str, company) -> str:
    """Mailtext zur Rechnung. Der Absender kommt AUSSCHLIESSLICH aus `company`.

    Diese Mail verlässt das Haus (Kunde + BCC an den Steuerberater). Ein hart
    kodierter Absender würde dort einen fremden Dritten als datenschutzrechtlich
    Verantwortlichen für fremde Daten benennen — deshalb: die konfigurierte Firma
    oder gar niemand. Eine falsche Angabe ist schlechter als keine.
    """
    name = (company.name or "").strip() if company else ""
    zeilen = [
        "Sehr geehrte Damen und Herren,",
        "",
        f"anbei erhalten Sie Ihre Rechnung {invoice_number}.",
        "",
        "Das Dokument enthält die strukturierten ZUGFeRD-Rechnungsdaten "
        "(Factur-X EN16931) gemäß § 14 UStG.",
        "",
        "Bei Fragen stehen wir Ihnen gerne zur Verfügung.",
        "",
        "Mit freundlichen Grüßen",
    ]
    if name:
        zeilen.append(name)

    anschrift = _anschrift(company)
    if anschrift:
        zeilen += ["", "---", f"Verantwortlich: {anschrift}"]

    return "\n".join(zeilen) + "\n"


def build_test_mail(company) -> tuple[str, str]:
    """(Text, Betreff) der SMTP-Testmail. Nennt bewusst kein Produkt — der
    Platzhalter aus `branding.py` hat in einer echten Mail nichts verloren."""
    name = (company.name or "").strip() if company else ""
    zeilen = ["Diese E-Mail bestätigt, dass Ihre SMTP-Konfiguration korrekt ist."]
    if name:
        zeilen += ["", "Mit freundlichen Grüßen", name]
    return "\n".join(zeilen) + "\n", "SMTP-Test erfolgreich"


def send_invoice(
    to_email: str,
    invoice_number: str,
    customer_name: str,
    pdf_path: Path,
    bcc_datev: bool = True,
    db: Session = None,
    cc_email: str | None = "",
) -> None:
    cfg = _get_effective_smtp_config(db)
    if not cfg.smtp_host:
        raise EmailError("SMTP nicht konfiguriert. Bitte Einstellungen ausfüllen.")
    if not pdf_path.exists():
        raise EmailError(f"PDF nicht gefunden: {pdf_path}")
    if pdf_path.stat().st_size > 20 * 1024 * 1024:
        raise EmailError("PDF größer als 20 MB – DATEV Upload Mail würde die Datei ablehnen.")

    msg = EmailMessage()
    msg["From"] = cfg.smtp_from
    msg["To"] = to_email
    msg["Subject"] = f"Rechnung {invoice_number}"

    # CC (#147): sichtbare Kopie, z. B. an die eigene Ablage. Ein leeres Feld darf
    # KEINEN leeren Cc-Kopf erzeugen — manche Mailserver weisen das zurück.
    cc = (cc_email or "").strip()
    if cc:
        msg["Cc"] = cc

    bcc_addresses = []
    if bcc_datev and cfg.datev_bcc_email:
        bcc_addresses.append(cfg.datev_bcc_email)
    if bcc_addresses:
        msg["Bcc"] = ", ".join(bcc_addresses)

    msg.set_content(build_invoice_body(invoice_number, _company(db)))

    with open(pdf_path, "rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application",
            subtype="pdf",
            filename=pdf_path.name,
        )

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port) as server:
            if cfg.smtp_use_tls:
                server.starttls(context=context)
            if cfg.smtp_user and cfg.smtp_password:
                server.login(cfg.smtp_user, cfg.smtp_password)
            server.send_message(msg)
    except smtplib.SMTPException as e:
        raise EmailError(f"SMTP-Fehler: {e}") from e


def send_test_email(to_email: str, db: Session = None) -> None:
    cfg = _get_effective_smtp_config(db)
    if not cfg.smtp_host:
        raise EmailError("SMTP nicht konfiguriert.")

    msg = EmailMessage()
    msg["From"] = cfg.smtp_from
    msg["To"] = to_email
    body, betreff = build_test_mail(_company(db))
    msg["Subject"] = betreff
    msg.set_content(body)

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port) as server:
            if cfg.smtp_use_tls:
                server.starttls(context=context)
            if cfg.smtp_user and cfg.smtp_password:
                server.login(cfg.smtp_user, cfg.smtp_password)
            server.send_message(msg)
    except smtplib.SMTPException as e:
        raise EmailError(f"SMTP-Fehler: {e}") from e
