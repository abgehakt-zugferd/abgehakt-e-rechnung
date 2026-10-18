"""Finalize-End-to-End einer Ausgangsrechnung aus einem rechnungsauftrag (§ 8a).

Voller Weg gegen die echte Datenbank und die ECHTE Pipeline (ReportLab,
Ghostscript, Mustang), angefangen beim Belegordner: angenommener Auftrag →
Knopf → Entwurf 380 mit Reverse Charge und einer NEGATIVEN Position (Festlegung
11) → prüfen → finalisieren → Archiv. Mustang ist die Wahrheit: gefordert sind
is_valid UND XML:valid, genau wie im Finalisieren (services/rechnung/finalisieren.py).

Übersprungene Tests gelten hier als Fehlschlag; fehlt Mustang, ist der Lauf
rot (deshalb kein stiller Skip im Container-Lauf von run-tests.sh).
"""
import uuid

import pytest

from app.config import get_settings
from app.models.app_config import AppConfig
from app.models.customer import Customer
from app.models.invoice import Invoice, ValidationResult
from app.services import mustang, pdfa
from tests.helpers.uebergabe import PARTNER_A, rechnungsauftrag, beleg

settings = get_settings()

pytestmark = pytest.mark.skipif(
    not (mustang.jar_available() and pdfa.gs_available()),
    reason="Mustang-JAR oder Ghostscript nicht verfügbar",
)

RICHTUNG = "tantiemen-app-nach-abgehakt"


@pytest.fixture
def belegordner(tmp_path):
    """Ein Wegwerf-Belegordner samt Schluessel, an den die Anwendung zeigt."""
    from tests.helpers.uebergabe import schluesselpaar

    ordner = tmp_path / "uebergaben"
    (ordner / RICHTUNG).mkdir(parents=True)
    signieren, schluessel = schluesselpaar(tmp_path / "schluessel")

    einstellungen = get_settings()
    vorher = (einstellungen.uebergaben_ordner, einstellungen.schluessel_pfad)
    einstellungen.uebergaben_ordner = str(ordner)
    einstellungen.schluessel_pfad = str(schluessel)
    yield ordner / RICHTUNG, signieren
    einstellungen.uebergaben_ordner, einstellungen.schluessel_pfad = vorher


def test_380_aus_einem_auftrag_bis_zum_archiv_durch_die_echte_pipeline(
    client, pg_session, belegordner,
):
    ordner, signieren = belegordner

    # Kunde mit der Steuervorgabe (Festlegung 13): AE verlangt die USt-IdNr.,
    # das Land liegt in der EU - sonst warnte die Plausibilitaet.
    kunde = Customer(
        customer_number=f"K-{uuid.uuid4().hex[:8]}",
        name="Plattform Beispiel GmbH",
        address_line1="Platz 1", zip_code="1015", city="Amsterdam", country="NL",
        auftrag_steuer="AE", vat_id="NL123456789B01",
        kopftext="Vereinbarung vom 1. Januar 2026, Abrechnungsmonat {leistungsmonat}.",
        fusstext="Der Abrechnungsbericht ist die Einzelaufstellung.",
        zahlungshinweis="Zahlung folgt dem Auszahlungsbericht der Plattform.",
    )
    kunde.id = uuid.UUID(PARTNER_A)
    pg_session.add(kunde)
    cfg = pg_session.query(AppConfig).filter(AppConfig.id == 1).first()
    if cfg is None:
        cfg = AppConfig(id=1)
        pg_session.add(cfg)
    cfg.beleg_integration_aktiv = True
    pg_session.commit()

    (ordner / "auftrag.json").write_bytes(
        beleg(signieren, rechnungsauftrag(), nutzlast_art="rechnungsauftrag")
    )

    # 1. Der Knopf: aus dem angenommenen Auftrag wird der Entwurf.
    anlage = client.post("/uebergaben/auftrag.json/rechnung-anlegen")
    assert anlage.status_code == 303, anlage.text
    entwurf = pg_session.query(Invoice).one()
    nummer = entwurf.invoice_number
    assert anlage.headers["location"] == f"/invoices/{entwurf.id}/vorschau"
    assert entwurf.tax_category == "AE"
    assert entwurf.due_date is None

    try:
        # 2. Prüfen: echter Validator, echtes Mustang auf der erzeugten XML.
        r_pruef = client.post(f"/invoices/{entwurf.id}/pruefen")
        assert r_pruef.status_code == 303, r_pruef.text
        pg_session.expire_all()
        vr = (pg_session.query(ValidationResult)
              .filter(ValidationResult.invoice_id == entwurf.id)
              .order_by(ValidationResult.validated_at.desc())
              .first())
        assert vr is not None and vr.is_valid, vr.mustang_output if vr else None

        # 3. Finalisieren: echte Pipeline, kein Attrappen-Mustang. Das
        # Ausstellungsdatum kommt auf heute (Festlegung 14), die negative
        # Position bleibt (Festlegung 11).
        r = client.post(f"/invoices/{entwurf.id}/finalisieren")
        assert r.status_code == 303, r.text
        pg_session.expire_all()
        row = pg_session.get(Invoice, entwurf.id)
        assert row.status == "issued"
        assert "<ram:TypeCode>380</ram:TypeCode>" in row.zugferd_xml
        # Die negative Position ist als solche kodiert: Das Vorzeichen sitzt
        # auf der Menge (BR-27 verbietet negative Einzelpreise), der
        # Positionsbetrag bleibt negativ.
        assert "-1.0000" in row.zugferd_xml
        assert "-3.10" in row.zugferd_xml
        assert row.pdf_filename == f"{nummer}.pdf"

        # 4. Beleg liegt physisch im Archiv, Mustang nimmt ihn an: UND-Bedingung.
        pdf_path = settings.storage_path / "pdfs" / row.pdf_filename
        assert pdf_path.exists(), "Finalisiertes PDF fehlt auf der Platte"
        result = mustang.validate(pdf_path)
        assert result["is_valid"], (
            f"Mustang lehnt die 380 ab:\nFehler: {result['errors']}\n"
            f"Rohbericht:\n{result['raw']}\nXML:\n{row.zugferd_xml}"
        )
        assert "XML:valid" in result["raw"], result["raw"]
    finally:
        if pg_session.get(Invoice, entwurf.id) is not None:
            pdf_name = pg_session.get(Invoice, entwurf.id).pdf_filename
            if pdf_name:
                (settings.storage_path / "pdfs" / pdf_name).unlink(missing_ok=True)
        (settings.storage_path / "pdfs" / f"{nummer}_visual.pdf").unlink(missing_ok=True)
        (settings.storage_path / "xml" / f"{nummer}.xml").unlink(missing_ok=True)
