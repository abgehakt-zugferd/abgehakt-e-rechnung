# Abgehakt in fünf Minuten

Abgehakt ist ein selbst gehostetes Rechnungsprogramm für deutsche Unternehmer. Es erzeugt
E-Rechnungen nach ZUGFeRD (Profil EN 16931, PDF/A-3 mit eingebetteter CII-XML), schickt sie
per Mail an Kunden und Buchhaltung und hält sie GoBD-gerecht unveränderbar vor.

**Die zehn Sätze, die man kennen muss:**

1. Ein Beleg läuft `draft` → `issued` → `paid` oder `issued` → `cancelled`. Nur ein Entwurf
   ist bearbeitbar. Ein verworfener Entwurf heißt `discarded` und lässt sich zurückholen;
   gelöscht wird nie, weil die Nummer schon beim Entwurf vergeben ist
   (`ALLOWED_TRANSITIONS` in `services/invoice_guard.py`).
2. Finalisieren ist fail-closed: Prüfung nach § 14 UStG, XML, PDF, PDF/A-3, Einbetten und
   Validieren mit der Mustang-CLI. Erst wenn Mustang `XML:valid` meldet, wird der Beleg `issued`.
3. Ein gestellter Beleg ist doppelt geschützt: im ORM durch Session-Guards, in der Datenbank
   durch Trigger und eine App-Rolle ohne `DELETE`/`TRUNCATE`.
4. Korrigiert wird nie durch Ändern, sondern per Gutschrift (381) und, wenn nötig, einer
   Ersatzrechnung mit Verweis auf die Vorgängerrechnung (BT-25).
5. Belegarten: Standardrechnung (380), Anzahlungsrechnung (386), Gutschrift/Storno (381),
   Gutschriftverfahren (389, teilweise umgesetzt). Eine Quelle: `services/belegart.py`.
6. Die XML hat rechtlich Vorrang. PDF und XML entstehen aus denselben Daten, Summen aus
   genau einer Stelle (`services/belegsummen.py`).
7. Die Belegsprache (Deutsch/Englisch) steuert PDF und Mailtext sowie die Beschriftungen
   der Pflichtangaben in der XML (BT-33). Codes, Datumsformate (`YYYYMMDD`), Beträge und
   die Steuerbefreiungstexte E/K/O bleiben sprachunabhängig; AE bleibt zweisprachig.
8. Außer dem Mailversand über Ihren SMTP-Server geht Abgehakt nur auf Klick und nach
   Einwilligung ins Netz: USt-IdNr.-Prüfung bei VIES und die Suche nach Updates.
9. Optional nimmt Abgehakt signierte Abrechnungsaufträge eines vorgelagerten Systems aus einem
   Ordner an und legt daraus Entwürfe an (Beleg-Integration, hinter einem Schalter).
10. Kein Produktivcode ohne roten Test zuerst; der Pre-Push-Hook fährt die ganze Suite im
    Container, ein übersprungener Test gilt als Fehlschlag.

## Wo steht was

Alle Pfade unter `backend/app/`, sofern nicht anders angegeben.

| Wenn Sie … | … schauen Sie in |
|---|---|
| eine Seite oder einen Knopf suchen | `routers/` (Routen) und `templates/` (Oberfläche) |
| den Rechnungsablauf verstehen wollen | `routers/invoices/` (Routen) und `services/rechnung/` (Prüfen, Finalisieren, Versenden, Storno) |
| eine Pflichtangabe prüfen oder ergänzen | `services/validator.py` (Fehler sperren das Finalisieren) |
| die E-Rechnung (CII-XML) ändern | `services/zugferd_xml/` |
| das PDF ändern | `services/pdf_generator/`, `pdf_fuss.py`, `pdf_spalten.py`, `pdf_fonts.py` |
| die PDF/A-Kette nachvollziehen | `services/pdfa.py` (Ghostscript), `services/mustang.py` (Einbetten, Validieren) |
| Belegarten, Typcodes, Wählbarkeit | `services/belegart.py` |
| Summen, Rundung, Abzug auf Belegebene | `services/belegsummen.py` |
| Storno, Gutschrift, Ersatzrechnung | `services/storno.py`, `storno_wirkung.py`, `ersatzrechnung.py` |
| Unveränderbarkeit (GoBD) | `services/invoice_guard.py`, `customer_guard.py`, `db/immutability_triggers.py`, `db/roles.py` |
| das Änderungsprotokoll | `services/audit.py` (schreiben), `aenderungsprotokoll.py` (anzeigen) |
| Kennzahlen der Übersicht | `services/dashboard_kennzahlen.py`, `main.py` (Route `/dashboard`) |
| Mailversand an Kunde und Buchhaltung | `services/datev_email.py`, `empfaenger.py`, `mailtext.py` |
| Sprache und Beschriftungen des Belegs | `services/belegsprache/` |
| Steuerstatus des Kunden, Kategorie gegen Land | `services/steuerstatus.py`, `steuerkategorie_land.py` |
| Rechnungs- und Kundennummern | `services/invoice_number.py`, `customer_number.py` |
| GoBD-Export und Archiv | `services/gobd_export.py`, `routers/export.py`, `routers/archive.py`, `services/archive_frist.py` |
| Beleg-Integration (Übergaben) | `routers/uebergaben.py`, `services/uebergabe_befund.py`, `uebergabebeleg.py`, `abrechnungsauftrag_wirkung.py`, `belegsperre.py`, `protokoll.py` |
| VIES-Prüfung, Update-Hinweis | `services/ust_id_pruefung.py`, `update_check.py`, `update_banner.py` |
| Einstellungen und Umgebungsvariablen | `config.py` (Umgebung), `models/app_config.py` und `models/company.py` (in der Datenbank) |
| das Datenmodell | `models/` und `backend/alembic/versions/` (Migrationen, laufen beim Start) |
| Werkzeuge außerhalb der Oberfläche | `backend/scripts/` (Migration aus XML, Rollen, Länder- und IBAN-Daten) |
| Tests und Hooks | `backend/tests/`, `backend/run-tests.sh`, `.githooks/`, `.github/workflows/` |

## Weiterlesen

- [README.md](../README.md): Installation, Sicherung, Grenzen, Datenschutz.
- [ANWENDUNG.md](ANWENDUNG.md): Bedienung, Schritt für Schritt.
- [ARCHITEKTUR.md](ARCHITEKTUR.md): Schichten, Regeln und warum sie so sind.
- [DEV-DOCU.md](DEV-DOCU.md): gesammelte Lehren, Fallstricke, Abhängigkeiten.
- [specs/](specs/): ein Dokument je Funktion, mit Status oben.
- [CHANGELOG.md](../CHANGELOG.md): was sich zwischen den Fassungen geändert hat.
