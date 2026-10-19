import re
from datetime import date
from sqlalchemy.orm import Session
from app.models.company import Company
from app.zeit import heute

# Der Präfix wird Teil der Belegnummer, und die Belegnummer wird Teil
# eines Dateinamens (`storage/pdfs/{nummer}.pdf`) und des Betreffs der
# DATEV-Mail. Deshalb wird er hier eingeschränkt, nicht dort maskiert: eine
# Nummer, die als Dateiname taugt, taugt überall. Das gilt fuer Rechnungen
# wie fuer Aufstellungen — dieselbe Weissliste, derselbe Grund.
#
# Weißliste statt Schwarzliste. Eine Liste verbotener Zeichen vergisst immer
# eines, und das eine vergessene schiebt den Beleg aus dem GoBD-Archiv
# (`storage/pdfs/../../x.pdf` liegt außerhalb) oder bricht den Mailversand.
ERLAUBTE_PRAEFIX_ZEICHEN = re.compile(r"^[A-Za-z0-9._-]+$")


def _praefix_regel(feldname: str) -> str:
    return (
        f"Der {feldname} darf nur Buchstaben, Ziffern, Punkt, Bindestrich und "
        "Unterstrich enthalten (z. B. RE oder RG-2026). Er wird Teil des "
        "Dateinamens im Archiv."
    )


def pruefe_praefix(praefix: str, *, feldname: str = "Rechnungspräfix") -> str | None:
    """Gibt eine Meldung zurück, wenn der Präfix unzulässig ist, sonst None.

    feldname benennt das Feld in der Meldung — die Regel ist fuer jeden
    Nummernkreis dieselbe, die Ansprache der Nutzerin nicht.
    """
    wert = (praefix or "").strip()
    if not wert:
        return f"Der {feldname} darf nicht leer sein."
    if len(wert) > 20:
        return f"Der {feldname} ist zu lang (höchstens 20 Zeichen)."
    if not ERLAUBTE_PRAEFIX_ZEICHEN.match(wert):
        return _praefix_regel(feldname)
    if wert.strip(".") == "":
        # `.` und `..` bestehen die Zeichenprüfung, sind als Pfadbestandteil aber
        # genau das Problem.
        return _praefix_regel(feldname)
    return None


def _naechste_nummer(
    db: Session,
    *,
    praefix_feld: str,
    zaehler_feld: str,
    jahr_feld: str,
    datum: date | None,
) -> str:
    """Die EINE lueckenlose Nummernvergabe: Firmenzeile sperren (FOR UPDATE
    serialisiert nebenlaeufige Aussteller), Zaehler erhoehen, flushen (der
    Zaehlerstand ueberlebt den Absturz zwischen Nummer und Commit nur in
    der DB, nicht im Objekt), Jahr ggf. aus dem Belegdatum ziehen.

    Parametrisiert ueber die Spaltennamen an company: Rechnung und
    Aufstellung teilen sich den Mechanismus (Bauschritt 7a, Entscheidung 8),
    nicht aber Praefix und Zaehler — jeder Kreis bleibt fuer sich lueckenlos.
    """
    company = db.query(Company).filter(Company.id == 1).with_for_update().first()
    if not company:
        raise RuntimeError("Firmendaten nicht konfiguriert. Bitte zuerst Einstellungen ausfüllen.")

    zaehler = getattr(company, zaehler_feld) + 1
    setattr(company, zaehler_feld, zaehler)
    db.flush()

    counter = str(zaehler).zfill(3)
    # Der Default-Praefix der Aufstellung ist "AA-" (Entscheidung 8), der der
    # Rechnung "RE". Der Bindestrich gehoert zum NUMMERNFORMAT, nicht zum
    # Praefix — traegt der Praefix ihn schon mit, darf das Format keinen
    # zweiten setzen ("AA--001" waere ein Dateiname, den niemand bestellt
    # hat). Fuer Rechnungsnummern aendert sich nichts: "RE" behaelt seinen
    # Trenner wie bisher.
    trenner = "" if getattr(company, praefix_feld).endswith("-") else "-"
    if getattr(company, jahr_feld):
        # Jahr aus dem Belegdatum beim Anlegen (#19). Die Nummer selbst bleibt
        # danach unveraenderlich; ein spaeteres Umdatieren des Belegs aendert
        # sie nicht.
        year = (datum or heute()).year
        return f"{getattr(company, praefix_feld)}{trenner}{year}-{counter}"
    return f"{getattr(company, praefix_feld)}{trenner}{counter}"


def generate_next_invoice_number(db: Session, issue_date: date | None = None) -> str:
    return _naechste_nummer(
        db,
        praefix_feld="invoice_prefix",
        zaehler_feld="invoice_counter",
        jahr_feld="invoice_year_in_number",
        datum=issue_date,
    )


def generate_next_aufstellung_number(db: Session, ausstellungsdatum: date | None = None) -> str:
    """Nummer einer Abrechnungsaufstellung — eigener Praefix, eigener Zaehler,
    derselbe Mechanismus wie fuer Rechnungen.

    Die Jahreszahl in der Nummer regelt invoice_year_in_number MIT: Das ist
    der eine Nummernstil der Firma. Ein zweites Flag je Belegart wuerde
    Zustaende erlauben, die niemand bestellt hat (Rechnung mit, Aufstellung
    ohne Jahr).
    """
    return _naechste_nummer(
        db,
        praefix_feld="aufstellung_prefix",
        zaehler_feld="aufstellung_counter",
        jahr_feld="invoice_year_in_number",
        datum=ausstellungsdatum,
    )
