"""Der Rechnungspräfix wird Teil eines Dateinamens und muss geprüft werden.

Gefunden bei der Sicherheitsprüfung am 09.08.2026. Die Rechnungsnummer entsteht
als `{invoice_prefix}-{jahr}-{zaehler}` und geht anschließend ungeprüft in einen
Pfad: `storage/pdfs/{rechnungsnummer}.pdf`. Ein Präfix mit `/` oder `..` schiebt
den Beleg damit aus dem Archiv heraus. Nachgemessen:

    Path("/app/storage/pdfs") / "../../../tmp/x-2026-001.pdf"
    → /tmp/x-2026-001.pdf

Das ist in erster Linie kein Angriff, sondern ein Aufbewahrungsproblem: die
Datenbank sagt „gestellt", im GoBD-Archiv liegt nichts. Es braucht dafür keine
böse Absicht, ein Präfix wie `RE/2026` genügt, und das tippt jemand versehentlich.

Steuerzeichen sind aus einem zweiten Grund verboten: die Rechnungsnummer steht im
Betreff der DATEV-Mail. Python weigert sich dort zu Recht (`ValueError: Header
values may not contain linefeed or carriage return characters`) — der Versand
stürzt also ab, statt heimlich eine Kopie zu verschicken. Kein Loch, aber ein
Absturz an einer Stelle, an der der Nutzer ihn nicht deuten kann.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.company import Company
from app.services.invoice_number import pruefe_praefix


def teardown_function():
    app.dependency_overrides.clear()


ERLAUBT = ["RE", "R", "RG-2026", "MUSTER_RE", "Rechnung.Nr", "AB123"]
VERBOTEN = [
    "RE/2026",          # Unterverzeichnis
    "../fremd",         # aus dem Archiv heraus
    "..",
    "RE\\2026",         # Windows-Trenner
    "RE\nBcc: x",       # Steuerzeichen, bricht den Mailversand
    "RE\r\nX",
    "RE\t2026",
    "RE:2026",          # Doppelpunkt trennt Kopfzeilen und ist unter Windows verboten
    "RE*",              # Platzhalter im Dateinamen
    "RE?",
]


@pytest.mark.parametrize("praefix", ERLAUBT)
def test_uebliche_praefixe_bleiben_erlaubt(praefix):
    """Die Regel darf nicht so streng werden, dass sie normale Wünsche verbietet."""
    assert pruefe_praefix(praefix) is None, praefix


@pytest.mark.parametrize("praefix", VERBOTEN)
def test_pfad_und_steuerzeichen_werden_abgelehnt(praefix):
    meldung = pruefe_praefix(praefix)

    assert meldung, f"{praefix!r} wurde durchgelassen"
    assert isinstance(meldung, str) and meldung.strip()


def test_die_meldung_nennt_das_erlaubte_und_nicht_nur_das_verbotene():
    """„Ungültige Eingabe" hilft niemandem. Der Nutzer muss wissen, was er
    stattdessen tippen soll."""
    meldung = pruefe_praefix("RE/2026")

    assert any(w in meldung for w in ("Buchstaben", "Ziffern")), meldung


def test_die_einstellungen_speichern_einen_unzulaessigen_praefix_nicht(pg_session):
    """Die Prüfung muss dort greifen, wo der Wert hereinkommt. Sonst steht sie im
    Dienst und niemand ruft sie auf."""
    app.dependency_overrides[get_db] = lambda: pg_session
    client = TestClient(app, follow_redirects=False)
    vorher = pg_session.query(Company).filter(Company.id == 1).first().invoice_prefix

    antwort = client.post("/settings/firma", data={
        "name": "Muster Handwerk GmbH", "address_line1": "Musterstraße 1",
        "zip_code": "12345", "city": "Musterstadt", "country": "DE",
        "tax_number": "12/345/67890", "invoice_prefix": "../entwischt",
    })

    assert antwort.status_code == 200, "Kein Redirect: die Seite muss den Fehler zeigen"
    pg_session.expire_all()
    nachher = pg_session.query(Company).filter(Company.id == 1).first().invoice_prefix
    assert nachher == vorher, "Der unzulässige Präfix wurde gespeichert"


def test_ein_zulaessiger_praefix_wird_weiterhin_gespeichert(pg_session):
    """Gegenprobe: die Sperre darf nicht das Speichern überhaupt verhindern."""
    app.dependency_overrides[get_db] = lambda: pg_session
    client = TestClient(app, follow_redirects=False)

    antwort = client.post("/settings/firma", data={
        "name": "Muster Handwerk GmbH", "address_line1": "Musterstraße 1",
        "zip_code": "12345", "city": "Musterstadt", "country": "DE",
        "tax_number": "12/345/67890", "invoice_prefix": "RG-2026",
    })

    assert antwort.status_code == 303, antwort.text
    pg_session.expire_all()
    firma = pg_session.query(Company).filter(Company.id == 1).first()
    assert firma.invoice_prefix == "RG-2026"
