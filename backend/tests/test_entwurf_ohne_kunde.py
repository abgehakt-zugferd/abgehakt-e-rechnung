"""Ein Entwurf darf ohne Kunden gespeichert werden (10.08.2026).

Der Anlass ist ein Ablauf, der vorher in eine Sackgasse lief: Man tippt Positionen,
Beschreibung und Daten zusammen, klickt auf Speichern und bekommt den Kunden als
Pflichtfeld zurück. Wer ihn noch nicht angelegt hat, muss die Seite verlassen, und die
Eingabe ist weg. Ein Entwurf, der Pflichtfelder hat, ist kein Entwurf.

Die Grenze verschiebt sich damit nicht, sie rückt nur an die richtige Stelle. Der
Kunde ist für die *Rechnung* Pflicht (§ 14 Abs. 4 Nr. 1 UStG), nicht für den Entwurf.
`validator.validate_invoice` kennt diesen Fall längst als harten Fehler
(`BUYER_MISSING`), und das Finalisieren ist fail-closed. Ein Entwurf ohne Kunden kann
deshalb gespeichert werden, aber niemals zu einem Beleg werden. Genau das prüft
`test_finalisieren_ohne_kunde_bleibt_verboten`; fällt er, ist die Lockerung eine Lücke
geworden.

Echte Persistenz (`pg_session`), weil alles hier DB-Wirkung hat: die Spalte
`invoices.customer_id` wird nullable, und ob ein Wert wirklich in der Datenbank landet,
beweist nur ein Neu-Laden aus ihr.
"""
import json
import uuid
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models.customer import Customer
from app.models.invoice import Invoice


def teardown_function():
    app.dependency_overrides.clear()


def _client(pg_session):
    app.dependency_overrides[get_db] = lambda: pg_session
    return TestClient(app, follow_redirects=False)


def _customer(pg_session, name="Spät Angelegt GmbH"):
    c = Customer(customer_number=f"K-{uuid.uuid4().hex[:8]}", name=name,
                 address_line1="Weg 1", zip_code="80331", city="München", country="DE")
    pg_session.add(c)
    pg_session.commit()
    return c


def _item(desc="Beratung", qty="2", price="150", rate="19"):
    return {"description": desc, "unit": "Stunde", "quantity": qty,
            "unit_price": price, "tax_rate": rate}


def _payload(customer_id="", items=None):
    """Was der Browser abschickt. `customer_id` ist leer, wenn im Auswahlfeld noch
    „– Kunde wählen –" steht: ein leerer String, nicht ein fehlender Schlüssel."""
    return {
        "customer_id": customer_id,
        "issue_date": "2026-06-11",
        "due_date": "2026-06-25",
        "tax_category": "S",
        "notes": "Angebotstext steht schon",
        "items_json": json.dumps(items if items is not None else [_item()]),
    }


def _zeile(inv) -> str:
    """Der Link, den NUR eine Ergebniszeile der Liste enthaelt.

    Nicht auf die Rechnungsnummer pruefen: bei einer Suche gibt die Seite den
    Suchbegriff im Eingabefeld zurueck (`value="{{ q }}"`). Die Nummer steht dann
    im HTML, ob die Rechnung gefunden wurde oder nicht — ein Test darauf ist gruen,
    auch wenn die Liste leer ist.
    """
    return f'href="/invoices/{inv.id}"'


def _frisch(pg_session, inv_id):
    """Wirklich aus der Datenbank laden, nicht aus der Identity Map."""
    pg_session.expunge_all()
    return pg_session.query(Invoice).filter(Invoice.id == inv_id).first()


def _entwurf_ohne_kunde(pg_session, client, items=None):
    r = client.post("/invoices/neu", data=_payload(items=items))
    assert r.status_code == 303, r.text
    inv_id = uuid.UUID(r.headers["location"].rsplit("/", 1)[-1])
    return _frisch(pg_session, inv_id)


# --------------------------------------------------------------------- speichern

def test_entwurf_ohne_kunde_wird_gespeichert(pg_session):
    """Der Kern: Speichern gelingt, die Arbeit ist nicht verloren."""
    client = _client(pg_session)

    inv = _entwurf_ohne_kunde(pg_session, client)

    assert inv is not None, "Der Entwurf wurde nicht gespeichert."
    assert inv.customer_id is None
    assert inv.status == "draft"


def test_eingetippte_arbeit_ueberlebt_das_speichern(pg_session):
    """Ohne diesen Test koennte `customer_id = None` auch dadurch entstehen, dass die
    Rechnung leer angelegt wird. Positionen und Summen muessen mitkommen."""
    client = _client(pg_session)

    inv = _entwurf_ohne_kunde(pg_session, client)

    assert [i.description for i in inv.items] == ["Beratung"]
    assert inv.net_total == Decimal("300.00")
    assert inv.gross_total == Decimal("357.00")
    assert inv.notes == "Angebotstext steht schon"


def test_die_rechnungsnummer_wird_trotzdem_vergeben(pg_session):
    """Sie haengt am Anlegen des Entwurfs, nicht am Kunden. Bliebe sie leer, waere die
    Nummernfolge spaeter nicht mehr erklaerbar (siehe `discarded`)."""
    client = _client(pg_session)

    inv = _entwurf_ohne_kunde(pg_session, client)

    assert inv.invoice_number


# ----------------------------------------------------------------- nachtragen

def test_kunde_laesst_sich_nachtraeglich_zuweisen(pg_session):
    """Der Ablauf aus dem Anlass, ganz: Entwurf sichern, Kunden anlegen, zurueckkehren,
    zuweisen. Die Positionen duerfen dabei nicht verloren gehen."""
    client = _client(pg_session)
    inv = _entwurf_ohne_kunde(pg_session, client)
    inv_id = inv.id

    kunde = _customer(pg_session)
    # Vor dem `expunge_all()` in `_frisch` festhalten: danach ist `kunde` abgehängt und
    # jeder Attributzugriff wäre ein Refresh ohne Session.
    kunde_id = kunde.id

    r = client.post(f"/invoices/{inv_id}/bearbeiten",
                    data=_payload(customer_id=str(kunde_id)))
    assert r.status_code == 303, r.text

    neu = _frisch(pg_session, inv_id)
    assert neu.customer_id == kunde_id
    assert neu.customer.name == "Spät Angelegt GmbH"
    assert [i.description for i in neu.items] == ["Beratung"]


def test_zuweisung_laesst_sich_wieder_loesen(pg_session):
    """Solange der Beleg Entwurf ist, ist auch das Entfernen erlaubt. Sonst waere die
    erste Auswahl unumkehrbar, und ein Vertipper zwaenge zum Verwerfen."""
    client = _client(pg_session)
    kunde = _customer(pg_session)
    r = client.post("/invoices/neu", data=_payload(customer_id=str(kunde.id)))
    inv_id = uuid.UUID(r.headers["location"].rsplit("/", 1)[-1])

    r = client.post(f"/invoices/{inv_id}/bearbeiten", data=_payload(customer_id=""))
    assert r.status_code == 303, r.text

    assert _frisch(pg_session, inv_id).customer_id is None


# ------------------------------------------------------------------- die Grenze

def test_finalisieren_ohne_kunde_bleibt_verboten(pg_session):
    """Die eigentliche Sicherung dieser Lockerung. § 14 Abs. 4 Nr. 1 UStG verlangt den
    Empfaenger auf der Rechnung; `BUYER_MISSING` ist ein harter Fehler, und Finalisieren
    ist fail-closed. Faellt dieser Test, ist aus der Erleichterung eine Luecke geworden."""
    client = _client(pg_session)
    inv = _entwurf_ohne_kunde(pg_session, client)
    inv_id = inv.id

    r = client.post(f"/invoices/{inv_id}/finalisieren")

    assert r.status_code == 400, f"Finalisieren ohne Kunden lieferte {r.status_code}."
    neu = _frisch(pg_session, inv_id)
    assert neu.status == "draft"
    assert neu.zugferd_xml is None
    assert neu.pdf_filename is None


def test_pruefen_meldet_den_fehlenden_kunden(pg_session):
    """Der Nutzer soll es vor dem Finalisieren erfahren, nicht erst danach."""
    client = _client(pg_session)
    inv = _entwurf_ohne_kunde(pg_session, client)

    r = client.post(f"/invoices/{inv.id}/pruefen")
    assert r.status_code == 303, r.text

    neu = _frisch(pg_session, inv.id)
    codes = [f["code"] for vr in neu.validations for f in vr.errors]
    assert "BUYER_MISSING" in codes


# ---------------------------------------------------------------- Anzeigewege

def test_formular_erzwingt_den_kunden_nicht(pg_session):
    """Der Server duerfte den Entwurf annehmen und der Browser ihn trotzdem nicht
    abschicken: `required` im Auswahlfeld blockiert clientseitig, bevor je ein Request
    entsteht. Beide Seiten muessen mitwandern."""
    client = _client(pg_session)

    html = client.get("/invoices/neu").text

    feld = html[html.index('name="customer_id"'):]
    feld = feld[:feld.index(">") + 1]
    assert "required" not in feld, f"Das Kundenfeld ist weiterhin Pflicht: {feld}"


def test_liste_und_detail_ueberstehen_den_fehlenden_kunden(pg_session):
    """Beide Vorlagen fangen `None` bereits ab. Der Test haelt das fest, denn ab jetzt
    kann der Fall wirklich eintreten und nicht nur theoretisch."""
    client = _client(pg_session)
    inv = _entwurf_ohne_kunde(pg_session, client)

    assert client.get("/invoices/").status_code == 200
    assert client.get(f"/invoices/{inv.id}").status_code == 200


def test_entwurf_ohne_kunde_steht_in_der_liste(pg_session):
    """Dass die Seite laedt, sagt noch nicht, dass der Entwurf darauf steht.

    Die Liste verbindet Rechnungen mit Kunden, um nach dem Kundennamen suchen zu
    koennen. Ein INNER JOIN wirft dabei jede Rechnung ohne Kunden lautlos heraus:
    Status 200, Seite vollstaendig, Entwurf weg. Das waere dieselbe Sackgasse wie
    das alte Pflichtfeld, nur einen Schritt spaeter und schwerer zu bemerken, denn
    der Nutzer sieht keinen Fehler, sondern eine Liste ohne seine Arbeit.
    """
    client = _client(pg_session)
    inv = _entwurf_ohne_kunde(pg_session, client)

    html = client.get("/invoices/").text

    assert _zeile(inv) in html, (
        f"Entwurf {inv.invoice_number} fehlt in der Rechnungsliste — ohne Kunden "
        "faellt er aus der Verbindung heraus und ist nicht mehr auffindbar."
    )


def test_suche_findet_den_kundenlosen_entwurf_ueber_die_nummer(pg_session):
    """Der Suchzweig verknuepft zusaetzlich `Customer.name`. Auch dort darf ein
    fehlender Kunde die Rechnung nicht aus dem Ergebnis draengen: gesucht wurde
    nach der Nummer, und die hat sie."""
    client = _client(pg_session)
    inv = _entwurf_ohne_kunde(pg_session, client)

    html = client.get(f"/invoices/?q={inv.invoice_number}").text

    assert _zeile(inv) in html, (
        "Die Suche nach der Rechnungsnummer findet den kundenlosen Entwurf nicht."
    )


def test_detail_weist_den_weg_zum_kunden(pg_session):
    """Hier landet man nach dem Speichern. Wenn die Seite den fehlenden Kunden nur
    verschweigt, ist der Ablauf wieder eine Sackgasse, nur eine spaetere."""
    client = _client(pg_session)
    inv = _entwurf_ohne_kunde(pg_session, client)

    html = client.get(f"/invoices/{inv.id}").text

    assert "/customers/neu" in html, "Kein Weg zum Anlegen des Kunden auf der Detailseite."


def test_vorschau_seite_ohne_kunde_rendert(pg_session):
    """Die Vorschau zeigt auch die XML, und deren Erzeugung ist bereits `None`-fest."""
    client = _client(pg_session)
    inv = _entwurf_ohne_kunde(pg_session, client)

    assert client.get(f"/invoices/{inv.id}/vorschau").status_code == 200


def test_vorschau_pdf_ohne_kunde_sagt_es_statt_abzustuerzen(pg_session):
    """`generate_pdf` besteht zu Recht auf einem Empfaenger: ein PDF ohne Anschrift
    waere kein Brief. Das darf aber kein 500 mit Stapelspur sein, sondern ein Satz."""
    client = _client(pg_session)
    inv = _entwurf_ohne_kunde(pg_session, client)

    r = client.get(f"/invoices/{inv.id}/vorschau.pdf")

    assert r.status_code == 400, f"Erwartet 400 mit Erklaerung, bekommen {r.status_code}."
    assert "Kunde" in r.text
