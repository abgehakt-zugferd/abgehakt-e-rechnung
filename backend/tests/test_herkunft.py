"""
Fremde Webseiten dürfen nicht in das Archiv schreiben (Herkunftsprüfung).

Die Anwendung hat bewusst keine Anmeldung: wer die Oberfläche erreicht, darf
alles. Daraus folgt aber NICHT, dass jede beliebige Webseite mitschreiben darf.
Ein Formular auf einer fremden Seite darf ohne Vorabfrage an
`http://localhost:3000` senden — der Browser schickt es mit, weil ein einfacher
Formular-POST keine CORS-Vorabfrage auslöst. Lesen kann die fremde Seite die
Antwort nicht (Same-Origin-Policy), schreiben schon.

Hier wiegt das schwerer als anderswo: Schreibvorgänge sind endgültig. Eine so
angelegte und finalisierte Rechnung lässt sich nach GoBD nicht mehr löschen,
nur stornieren, und die Rechnungsnummer ist vergeben.

Geprüft wird der `Origin`-Kopf, kein Token: die Anwendung hat keine Sitzungen
und keine Anmeldung, ein Token bräuchte erst ein Cookie und müsste in jedes
Formular. Browser senden `Origin` bei jedem POST — auch bei einem
Formular-POST von einer fremden Seite. Genau das ist der Angriff.
"""
import uuid

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _kundendaten():
    return {"customer_number": f"K-{uuid.uuid4().hex[:8]}", "name": "Fremd GmbH",
            "address_line1": "Weg 1", "zip_code": "80331", "city": "München",
            "country": "DE"}


def test_fremde_seite_darf_keinen_kunden_anlegen(pg_session):
    """Der Angriff selbst: ein Formular auf einer fremden Seite sendet an die
    lokale Anwendung. Der Browser setzt dabei `Origin` auf die fremde Seite."""
    from app.models.customer import Customer
    vorher = pg_session.query(Customer).count()

    r = _client(pg_session).post("/customers/neu", data=_kundendaten(),
                                 headers={"origin": "https://boese.example"})

    assert r.status_code == 403
    pg_session.expire_all()
    assert pg_session.query(Customer).count() == vorher


def test_fremde_seite_darf_keine_rechnung_finalisieren(pg_session):
    """Finalisieren ist der teuerste Schreibvorgang: er vergibt eine Nummer und
    erzeugt einen Beleg, der nicht mehr löschbar ist."""
    r = _client(pg_session).post(f"/invoices/{uuid.uuid4()}/finalisieren",
                                 headers={"origin": "https://boese.example"})

    # 403, nicht 404: die Herkunft wird geprüft, BEVOR überhaupt nachgesehen
    # wird, ob es die Rechnung gibt. Sonst verriete die Antwort einer fremden
    # Seite, welche Kennungen vergeben sind.
    assert r.status_code == 403


def test_abweisung_erscheint_als_seite(pg_session):
    """Auch diese Abweisung ist eine Seite, kein JSON — wer sie zu Gesicht
    bekommt, hat sich in aller Regel selbst vertan (Lesezeichen, Proxy)."""
    r = _client(pg_session).post("/customers/neu", data=_kundendaten(),
                                 headers={"origin": "https://boese.example"})

    assert r.headers["content-type"].startswith("text/html")
    assert '{"detail"' not in r.text


def test_eigene_oberflaeche_darf_schreiben(pg_session):
    """Gegenprobe: der Browser sendet bei jedem POST aus der eigenen Oberfläche
    `Origin` mit der eigenen Adresse. Ohne diesen Test wäre die Prüfung von
    „blockiert alles" nicht zu unterscheiden."""
    from app.models.customer import Customer
    daten = _kundendaten()

    r = _client(pg_session).post("/customers/neu", data=daten,
                                 headers={"origin": "http://testserver"})

    assert r.status_code == 303
    pg_session.expire_all()
    assert pg_session.query(Customer).filter(
        Customer.customer_number == daten["customer_number"]).count() == 1


def test_ohne_herkunftsangabe_bleibt_es_erlaubt(pg_session):
    """`curl`, Skripte und die Testsuite senden keinen `Origin`. Sie zu sperren
    brächte nichts: ein Browser LÄSST den Kopf bei einem fremden POST nicht weg,
    ein Angreifer kann ihn also nicht einfach unterdrücken. Wer ohne Browser
    zugreift, sitzt ohnehin schon am Rechner."""
    from app.models.customer import Customer
    daten = _kundendaten()

    r = _client(pg_session).post("/customers/neu", data=daten)

    assert r.status_code == 303
    pg_session.expire_all()
    assert pg_session.query(Customer).filter(
        Customer.customer_number == daten["customer_number"]).count() == 1


def test_lesen_bleibt_von_ueberall_erlaubt(pg_session):
    """Nur schreibende Verfahren werden geprüft. Ein GET ändert nichts, und die
    fremde Seite kann die Antwort ohnehin nicht lesen."""
    r = _client(pg_session).get("/customers", headers={"origin": "https://boese.example"})

    # Nicht auf 200 prüfen: `/customers` leitet mit 307 auf `/customers/` um.
    # Die Eigenschaft, um die es geht, ist allein „nicht abgewiesen".
    assert r.status_code != 403
