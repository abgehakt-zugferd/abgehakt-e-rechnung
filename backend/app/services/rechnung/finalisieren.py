import os
import shutil
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.company import Company
from app.models.invoice import Invoice
from app.services import auftragsschluessel, mustang, pdf_generator, pdfa, validator, zugferd_xml
from app.services.archive_frist import berechne_archive_until
from app.services.rechnung.fehler import RechnungFehler
from app.services.rechnung.firma import get_company
from app.zeit import heute


def arbeitswurzel() -> Path:
    """`storage/temp/` als Arbeitsplatz der Belegerzeugung.

    Bewusst NICHT das Temp-Verzeichnis des Betriebssystems: das Veröffentlichen
    unten ist ein `os.replace` und damit nur innerhalb desselben Dateisystems ein
    atomares Umbenennen. `storage` ist ein eigener Mount, über die Grenze hinweg
    scheitert es mit `Invalid cross-device link`.

    `temp/` ist aus der Archivansicht ausgenommen (`routers/archive.BEREICHE` kennt
    nur `pdfs` und `xml`) und war dort schon vorher als Platz für Zwischendateien
    beschrieben.
    """
    wurzel = get_settings().storage_path / "temp"
    wurzel.mkdir(parents=True, exist_ok=True)
    return wurzel


def veroeffentliche(pdf_quelle: Path, xml_quelle: Path) -> list[Path]:
    """Fertigen Beleg aus dem Arbeitsverzeichnis ins Archiv übernehmen.

    `os.replace` statt Kopieren: innerhalb desselben Dateisystems ist das ein
    atomares Umbenennen. Im Archiv erscheint deshalb nie eine halb geschriebene
    Datei, und die Archivansicht, die das Verzeichnis ungefiltert vorliest, sieht
    entweder nichts oder den vollständigen Beleg.

    Bricht der zweite Zug ab, wird der erste zurückgenommen. Ein PDF ohne seine XML
    im Archiv wäre eine E-Rechnung, der genau der Teil fehlt, der seit 2025 den
    Vorrang hat.
    """
    storage_path = get_settings().storage_path
    ziele = [
        (pdf_quelle, storage_path / "pdfs" / pdf_quelle.name),
        (xml_quelle, storage_path / "xml" / xml_quelle.name),
    ]
    fertig: list[Path] = []
    try:
        for quelle, ziel in ziele:
            ziel.parent.mkdir(parents=True, exist_ok=True)
            os.replace(quelle, ziel)
            fertig.append(ziel)
    except OSError:
        for ziel in fertig:
            ziel.unlink(missing_ok=True)
        raise
    return fertig


def entwurf_sperren(db: Session, invoice_id) -> Invoice:
    """Entwurf mit Zeilensperre laden; alles andere wird abgewiesen."""
    # Zeilensperre vor der ersten teuren Zeile (#6). Zwei gleichzeitige Anfragen lasen
    # denselben Entwurf, sahen beide `draft` und starteten beide Ghostscript und
    # Mustang für denselben Beleg; am Ende veröffentlichte der zweite Lauf über den
    # fertigen Beleg des ersten hinweg. `FOR UPDATE` hält den zweiten hier fest, bis
    # der erste committet hat, und die Statusprüfung darunter liest dann den neuen
    # Stand: kein Entwurf mehr, also eine saubere Absage statt einer zweiten Pipeline.
    #
    # Die Sperre steht bis zum Commit am Ende von `ausfuehren`, deckt also die gesamte
    # Belegerzeugung ab. Das Warten ist gewollt: die Alternative wäre `NOWAIT` und
    # damit eine Fehlermeldung an einen Nutzer, der nur zweimal geklickt hat.
    invoice = (
        db.query(Invoice)
        .filter(Invoice.id == invoice_id)
        .with_for_update()
        .first()
    )
    if not invoice:
        raise RechnungFehler(404)
    if invoice.status != "draft":
        raise RechnungFehler(400, "Nur Entwürfe können finalisiert werden.")
    return invoice


def stelltag_verschieben(invoice: Invoice) -> None:
    """Auftragsentwurf: Ausstellungs- und Fälligkeitsdatum auf den Finalisierungstag."""
    # Festlegung 14: Ein Entwurf aus einem Auftrag trägt sein Ausstellungsdatum
    # nur vorläufig (Kalendertag von erzeugt_am); gestellt wird die Rechnung am
    # Tag des Finalisierens. Die Verschiebung steht VOR dem Validierungs-Gate,
    # damit der Warnbefund AUSSTELLUNGSFRIST_14A (pruefregeln/kopf.py) den Tag
    # sieht, der wirklich auf dem Beleg steht — die Frist des § 14a Abs. 1
    # Satz 2 UStG hängt am Ausstellungsdatum. Das Fälligkeitsdatum wandert um
    # denselben Abstand mit (14 Tage bleiben 14 Tage), und die Archivfrist
    # wird erst danach berechnet, denn sie hängt am neuen Tag.
    if invoice.auftragsschluessel is not None:
        stelltag = heute()
        abstand = stelltag - invoice.issue_date
        invoice.issue_date = stelltag
        if invoice.due_date is not None:
            invoice.due_date += abstand
        invoice.archive_until = berechne_archive_until(invoice.issue_date)


def rechtskonform_pruefen(invoice: Invoice, company: Company) -> None:
    """Validierungs-Gate: harte Fehler stoppen das Finalisieren."""
    # Validierungs-Gate (§ 14 UStG): eine Rechnung mit harten Fehlern (z. B. keine
    # Positionen, falsche Summen) darf NICHT finalisiert und archiviert werden —
    # sonst wanderte ein rechtswidriger Beleg unveränderlich ins GoBD-Archiv.
    errors, _ = validator.validate_invoice(invoice, company)
    if errors:
        raise RechnungFehler(
            400,
            "Rechnung ist nicht rechtskonform und kann nicht finalisiert werden: "
            + "; ".join(e.message for e in errors),
        )


def xml_erzeugen(invoice: Invoice, company: Company) -> str:
    # 1. ZUGFeRD XML erzeugen
    try:
        return zugferd_xml.generate_xml(invoice, company)
    except ValueError as fehler:
        raise RechnungFehler(400, str(fehler)) from fehler


def arbeitsverzeichnis_anlegen(invoice: Invoice) -> Path:
    # Die gesamte Belegerzeugung läuft in einem Wegwerf-Verzeichnis, NICHT im Archiv
    # (#12, #13, Dateiteil von #6). `storage/pdfs/` und `storage/xml/` sind zugleich
    # das GoBD-Archiv und das, was `routers/archive.py` ungefiltert aus dem
    # Dateisystem vorliest; was dort liegt, ist für den Betrachter ein Beleg. Solange
    # die Zwischenstufen dort entstanden, war jede halbfertige Stufe sekundenlang
    # sichtbar und herunterladbar, und ein gescheiterter Commit ließ ein PDF mit
    # echter Rechnungsnummer zurück, das die Datenbank nicht kannte.
    return Path(tempfile.mkdtemp(
        prefix=f"finalisieren-{invoice.invoice_number}-", dir=arbeitswurzel()))


def visuelles_pdf_erzeugen(invoice: Invoice, company: Company, arbeitsverzeichnis: Path) -> Path:
    # 2. Visuelles PDF erzeugen
    visual_pdf = arbeitsverzeichnis / f"{invoice.invoice_number}_visual.pdf"
    try:
        pdf_generator.generate_pdf(invoice, company, visual_pdf)
    except ValueError as fehler:
        raise RechnungFehler(400, str(fehler)) from fehler
    return visual_pdf


def mustang_einbettung_pruefen(zugferd_pdf: Path) -> tuple[bool, str]:
    """Mustang-Gegenprobe des kombinierten PDFs: (gültig, erster Prüffehler)."""
    # E1 (#98 Hardness): `combine` liefert True (rc=0 + Datei existiert) auch
    # für ein PDF, das ein Empfänger-/Prüfer-System ablehnen würde. Mustang
    # ist die Wahrheit — nur ein Ergebnis mit is_valid UND XML:valid (PDF/A +
    # Schema + Schematron griffen) gilt als gültige E-Rechnung. Sonst
    # fail-closed: die Rechnung bleibt draft (unten), kein Commit.
    result = mustang.validate(zugferd_pdf)
    if result["is_valid"] and "XML:valid" in result["raw"]:
        return True, ""
    fehler = result.get("errors") or []
    return False, str(fehler[0]).strip() if fehler else ""


def einbettung_versuchen(invoice: Invoice, visual_pdf: Path, xml_path: Path,
                         zugferd_pdf: Path, arbeitsverzeichnis: Path) -> tuple[bool, str]:
    """PDF/A-3-Wandlung und XML-Einbettung; liefert (eingebettet, Prüfgrund)."""
    # Pipeline: visuelles PDF → PDF/A-3 (Ghostscript) → Mustang bettet XML ein.
    # FAIL-CLOSED (#98 P0.1): eine E-Rechnung OHNE eingebettete ZUGFeRD-XML ist seit
    # 2025 rechtlich unvollständig (der XML-Teil hat Vorrang). Gelingt die Einbettung
    # nicht, wird NICHT als reines Visual-PDF „issued" — die Rechnung bleibt draft.
    # Es geht nichts verloren: kein Commit, und das Arbeitsverzeichnis fällt im
    # `finally` samt allen Zwischenstufen weg (die Datenverlust-Regression
    # 2026-07-08 betraf das Löschen eines bereits finalisierten PDFs — hier wird
    # gar nichts finalisiert).
    combined = False
    pruefgrund = ""      # erster Prüffehler, wandert in die Fehlermeldung (s. u.)
    if pdfa.gs_available() and mustang.jar_available():
        pdfa_pdf = arbeitsverzeichnis / f"{invoice.invoice_number}_pdfa.pdf"
        if pdfa.to_pdfa3(visual_pdf, pdfa_pdf, title=invoice.invoice_number) and \
                mustang.combine(pdfa_pdf, xml_path, zugferd_pdf):
            combined, pruefgrund = mustang_einbettung_pruefen(zugferd_pdf)
    return combined, pruefgrund


def einbettung_abweisen(db: Session, pruefgrund: str) -> None:
    """Einbettung gescheitert: Rollback, Rechnung bleibt Entwurf."""
    db.rollback()
    # Der Prüfbericht gehört in die Meldung: ohne ihn bleibt dem Menschen nur
    # „nochmal versuchen", und der zweite Versuch scheitert an derselben Regel
    # (Abnahme 2026-08-09: BR-CO-26, fehlende Verkäufer-Kennung — nicht erratbar).
    # Auf 400 Zeichen gekürzt, Mustang hängt ganze Schematron-Pfade an.
    grund = f" Grund der Prüfung: {pruefgrund[:400]}" if pruefgrund else ""
    raise RechnungFehler(
        400,
        "E-Rechnung konnte nicht erzeugt werden: die ZUGFeRD-XML ließ sich nicht "
        "ins PDF einbetten (PDF/A- oder Mustang-Schritt fehlgeschlagen). Die "
        f"Rechnung bleibt Entwurf — bitte erneut finalisieren.{grund}",
    )


def beleg_im_arbeitsverzeichnis(db: Session, invoice: Invoice, company: Company,
                                arbeitsverzeichnis: Path, xml_content: str) -> tuple[Path, Path]:
    """Visuelles PDF, XML und ZUGFeRD-PDF im Arbeitsverzeichnis; liefert (PDF, XML)."""
    visual_pdf = visuelles_pdf_erzeugen(invoice, company, arbeitsverzeichnis)

    # 3. Mustang: XML in PDF einbetten → ZUGFeRD PDF
    xml_path = arbeitsverzeichnis / f"{invoice.invoice_number}.xml"
    xml_path.write_text(xml_content, encoding="utf-8")

    zugferd_pdf = arbeitsverzeichnis / f"{invoice.invoice_number}.pdf"
    combined, pruefgrund = einbettung_versuchen(
        invoice, visual_pdf, xml_path, zugferd_pdf, arbeitsverzeichnis)

    if not combined:
        einbettung_abweisen(db, pruefgrund)
    return zugferd_pdf, xml_path


def als_gestellt_markieren(invoice: Invoice, zugferd_pdf: Path) -> None:
    """PDF-Name und Status setzen; eine gestellte Gutschrift gibt ihr Original frei."""
    invoice.pdf_filename = zugferd_pdf.name
    invoice.status = "issued"

    # Festlegung 12: Erst die GESTELLTE Stornorechnung hebt das Original
    # auf — nicht ihr Entwurf, denn ein verworfener Storno bleibt
    # folgenlos. Das Original behaelt seinen Status ('issued'/'paid'),
    # nur seine Sperre weicht; der Nachweis bleibt fuer die Akte.
    if invoice.invoice_type in {"credit_note", "self_billing_storno"} \
            and invoice.original_invoice_id is not None:
        original = invoice.original_invoice
        if original is not None:
            auftragsschluessel.freigeben(original)


def archivieren_und_committen(db: Session, zugferd_pdf: Path, xml_path: Path) -> None:
    # Erst ins Archiv, dann committen. Die umgekehrte Reihenfolge wäre der
    # schlechtere Fehler: eine gestellte Rechnung ohne Beleg auf der Platte ist
    # unveränderlich und damit nicht mehr reparierbar, während ein Beleg ohne
    # Datenbankzeile sich durch erneutes Finalisieren auflöst. Scheitert der
    # Commit, wird das eben Veröffentlichte wieder eingesammelt.
    veroeffentlicht = veroeffentliche(zugferd_pdf, xml_path)
    try:
        db.commit()
    except Exception:
        for ziel in veroeffentlicht:
            ziel.unlink(missing_ok=True)
        db.rollback()
        raise


def ausfuehren(db: Session, invoice_id) -> Invoice:
    """Entwurf finalisieren: prüfen, Beleg erzeugen, archivieren, committen."""
    invoice = entwurf_sperren(db, invoice_id)
    stelltag_verschieben(invoice)
    company = get_company(db)
    rechtskonform_pruefen(invoice, company)

    xml_content = xml_erzeugen(invoice, company)
    invoice.zugferd_xml = xml_content

    arbeitsverzeichnis = arbeitsverzeichnis_anlegen(invoice)
    try:
        zugferd_pdf, xml_path = beleg_im_arbeitsverzeichnis(
            db, invoice, company, arbeitsverzeichnis, xml_content)
        als_gestellt_markieren(invoice, zugferd_pdf)
        archivieren_und_committen(db, zugferd_pdf, xml_path)
    finally:
        shutil.rmtree(arbeitsverzeichnis, ignore_errors=True)
    return invoice
