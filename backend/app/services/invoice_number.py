import re
from datetime import date
from sqlalchemy.orm import Session
from app.models.company import Company

# Der Präfix wird Teil der Rechnungsnummer, und die Rechnungsnummer wird Teil
# eines Dateinamens (`storage/pdfs/{nummer}.pdf`) und des Betreffs der
# DATEV-Mail. Deshalb wird er hier eingeschränkt, nicht dort maskiert: eine
# Nummer, die als Dateiname taugt, taugt überall.
#
# Weißliste statt Schwarzliste. Eine Liste verbotener Zeichen vergisst immer
# eines, und das eine vergessene schiebt den Beleg aus dem GoBD-Archiv
# (`storage/pdfs/../../x.pdf` liegt außerhalb) oder bricht den Mailversand.
ERLAUBTE_PRAEFIX_ZEICHEN = re.compile(r"^[A-Za-z0-9._-]+$")
PRAEFIX_REGEL = (
    "Der Rechnungspräfix darf nur Buchstaben, Ziffern, Punkt, Bindestrich und "
    "Unterstrich enthalten (z. B. RE oder RG-2026). Er wird Teil des Dateinamens "
    "im Archiv."
)


def pruefe_praefix(praefix: str) -> str | None:
    """Gibt eine Meldung zurück, wenn der Präfix unzulässig ist, sonst None."""
    wert = (praefix or "").strip()
    if not wert:
        return "Der Rechnungspräfix darf nicht leer sein."
    if len(wert) > 20:
        return "Der Rechnungspräfix ist zu lang (höchstens 20 Zeichen)."
    if not ERLAUBTE_PRAEFIX_ZEICHEN.match(wert):
        return PRAEFIX_REGEL
    if wert.strip(".") == "":
        # `.` und `..` bestehen die Zeichenprüfung, sind als Pfadbestandteil aber
        # genau das Problem.
        return PRAEFIX_REGEL
    return None


def generate_next_invoice_number(db: Session, issue_date: date | None = None) -> str:
    company = db.query(Company).filter(Company.id == 1).with_for_update().first()
    if not company:
        raise RuntimeError("Firmendaten nicht konfiguriert. Bitte zuerst Einstellungen ausfüllen.")

    company.invoice_counter += 1
    db.flush()

    counter = str(company.invoice_counter).zfill(3)
    if company.invoice_year_in_number:
        # Jahr aus dem Ausstellungsdatum beim Anlegen (#19). Die Nummer selbst bleibt
        # danach unveraenderlich (#145); ein spaeteres Umdatieren des Belegs aendert sie nicht.
        year = (issue_date or date.today()).year
        return f"{company.invoice_prefix}-{year}-{counter}"
    return f"{company.invoice_prefix}-{counter}"
