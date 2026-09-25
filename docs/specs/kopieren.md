# Auftrag: Bestehende Rechnung als Vorlage

Stand: 25.09.2026. Spezifikation fuer einen getrennten, spaeter test-first auszufuehrenden Auftrag. Keine Implementierung. Bestand aus dem Brief wird vorausgesetzt.

## Ergebnis und fachlicher Umfang

Eine bestehende Rechnung oeffnet das Anlegeformular vorbefuellt. Der Nutzer aendert nur, was sich aendert, und speichert wie bei jeder anderen Neuanlage. Beim Oeffnen entsteht kein Datensatz. Das ist unabhaengig vom XML: Vorbefuellen betrifft nur die Formularfelder.

Anlass: erste von zwei Raten ist gestellt; die zweite braucht dieselben Positionen, denselben Kunden, dieselbe Bestellnummer, denselben Leistungszeitraum. Betraege, Beschreibungstext und Belegdaten aendert der Nutzer.

**Codeentscheidung (Loeschtest):** Vorbefuellen ist ein duenner Durchreicher auf den bestehenden Anlageweg. `GET /invoices/neu` uebernimmt die Vorbelegung in denselben Template-Kontext; gespeichert wird weiter ueber `POST /invoices/neu` (`create_invoice` in `backend/app/routers/invoices.py`). Positionen laufen ueber das vorhandene `items_json` und `_items_as_json`. **Kein Fachmodul.** Ein Service, der nur Felder umbenennt und weiterreicht, bestuende den Loeschtest nicht: ohne ihn bleibt dieselbe Logik im Router und Template.

## Naht und vollstaendiger Vertrag

Die Naht liegt zwischen der gelesenen Vorlagenrechnung und den Vorbelegungswerten der Anlegeansicht. Sie schreibt nicht. Persistenz und Nummernvergabe bleiben ausschliesslich beim bestehenden POST.

**Invarianten**

1. Genau eine Formularvorlage: `backend/app/templates/invoices/form.html`. Eine zweite Vorlage waere derselbe Fehler wie zwei Einheitenlisten.
2. Die Template-Variable `invoice` bestimmt das Speicherziel (`action`): gesetzt bedeutet Bearbeiten, `None` bedeutet Neuanlage. Die Vorlage darf hier **nie** eingesetzt werden. Wer die Vorlage als `invoice` uebergibt, speichert auf die Vorlage (`POST /invoices/{id}/bearbeiten`). Das ist der gefaehrliche Punkt dieses Features.
3. Vorbelegung nutzt eine eigene Kontextgroesse (Arbeitstitel `vorbelegung`) oder gleichwertige Einzelwerte fuer Felder und `items_json`. `invoice` bleibt `None`.
4. Der Aufruf aendert nichts: keinen Nummernzaehler, keinen Protokoll- oder Audit-Eintrag, keine Datei, keinen `updated_at` der Vorlage.

**Feldweiser Vertrag**

| Feld | Vorbelegt? | Begruendung |
|---|---|---|
| Kunde (`customer_id`) | ja | Anlass: derselbe Empfaenger. |
| Positionen: Beschreibung, Menge, Einheit, Einzelpreis, Steuersatz | ja | Kern des Anlasses; Format wie `_items_as_json`. Betraege und Texte bleiben editierbar. |
| Steuerkategorie (`tax_category`) | ja | Gehoert zur fachlichen Konstellation der Positionen. |
| Bestellnummer (`buyer_order_reference`, BT-13) | ja | Anlass: dieselbe Bestellung. |
| Kaeuferreferenz (`buyer_reference`, BT-10) | ja | Bleibt gueltig fuer denselben Kunden/Auftrag. |
| Leistungszeitraum (`service_period_start` / `_end`) | ja | Anlass: fuer beide Raten derselbe Zeitraum; der Nutzer prueft vor dem Speichern. |
| Leistungsdatum (`delivery_date`) | ja, wenn gesetzt | Gehoert zu den Leistungsangaben; abweichend von Belegdatum und Faelligkeit. Fehlt es in der Vorlage, gilt das Neuanlage-Default (heute), wie `GET /neu` heute. |
| Zahlungsbedingungen (`payment_terms`) | ja | Typischerweise unveraendert; sonst kurz aenderbar. |
| Bemerkungen (`notes`) | ja | Oft Ratenhinweis; Nutzer streicht oder passt an. |
| Belegsprache (`document_language`) | ja | Darstellungsabsicht des kopierten Entwurfs (docs/specs/belegsprache.md). Keine Storno-, Gutschrift- oder Anzahlungswirkung; deshalb vererbt, anders als `invoice_type`. |
| Rechnungsdatum (`issue_date`) | nein | Heutiger Tag, wie reine Neuanlage (`today`). Ein geerbtes Altdatum wuerde den neuen Beleg falsch datieren. |
| Faelligkeitsdatum (`due_date`) | nein | Aus heute wie bei Neuanlage (`due_default`, Bestand: heute + 14 Tage). |
| Status | nein | Neuanlage ist Entwurf; Status ist kein Formularfeld der Neuanlage. |
| Rechnungsnummer | nein | Erst beim Speichern vergeben; Anzeige nur wenn `invoice` gesetzt (Bearbeiten). |
| Belegart (`invoice_type`) | nein, nie | Wer Gutschrift, Korrektur, Gutschriftverfahren oder spaeter Vorausrechnung als Vorlage nimmt, will Positionen und Kopfdaten, nicht den Typ. Ein still geerbtes `credit_note` (oder `prepayment`) faellt erst beim Empfaenger auf. Der bestehende POST setzt keine Belegart; das bleibt so. |
| Waehrung, Profil, Summen, XML/PDF, DATEV, Archivfrist | nein | Werden beim Speichern bzw. Finalisieren gesetzt, nicht im Anlegeformular vorgegeben. |
| `original_invoice_id`, `uebergabe_beleg_*` | nein | Keine Formularfelder; Uebernahme wuerde die neue Rechnung an Storno- oder Belegketten haengen und die Belegsperre faelschlich aktivieren. |

**Einstieg**

- Aufruf: `GET /invoices/neu?vorlage=<uuid>`.
- Einstiegsknopf auf der Detailseite der Vorlage (sichtbar unabhaengig vom Status, solange die Vorlage lesbar ist). Ob zusaetzlich die Liste denselben Link zeigt, entscheidet der Auftraggeber; fachlich reicht die Detailseite.
- Werte erreichen die Ansicht ueber den erweiterten Handler von `new_invoice_form`: Vorlage laden, Vorbelegung bauen, `invoices/form.html` mit `invoice=None` rendern. Keine zweite Formularvorlage.

**Schreibfreiheit, messbar**

Vor und nach dem GET derselben Vorlagen-UUID, ohne anschliessendes Speichern:

- `Company.invoice_counter` unveraendert.
- Anzahl Zeilen in `invoices`, `invoice_items`, `audit_logs` und Aenderungsprotokoll unveraendert.
- Keine neue Datei unter dem PDF-/Archivspeicher.
- Vorlagenzeile bitgleich in den fachlichen Spalten (mindestens `updated_at`, Status, Nummern, Positionen).

**Fehlende oder manipulierte Kennung**

Unbekannte UUID, syntaktisch ungueltiger Wert oder nicht lesbare Vorlage: kein leeres Formular ohne Hinweis. Antwort mit sichtbarer Fehlermeldung (HTTP 404 oder Redirect auf `/invoices/neu` mit Fehlertext). Messbar: Antwortkoerper enthaelt den Hinweis; es wurde nichts angelegt.

**Kunde nicht in der Auswahlliste**

Die Neuanlage listet nur aktive, nicht geloeschte Kunden. Ist der Vorlagenkunde dort nicht enthalten: Positionen und uebrige Felder trotzdem vorbelegen, Kundenfeld leer, sichtbarer Hinweis. Stillschweigend `customer_id` ohne sichtbare Option waere Datenverlust beim Absenden.

## Zulaessige Quellen

Beim blossen Vorbefuellen entsteht kein Datensatz. Verbote, die nur das Anlegen oder Finalisieren schuetzen, greifen hier nicht.

Durchgang Entwurf, gestellt, bezahlt, storniert, verworfen, Gutschrift, Korrektur, Gutschriftverfahren, aus signierter Uebergabe: **kein Fall bleibt beim Vorbefuellen allein schaedlich**, sofern der Feldvertrag eingehalten wird (keine Belegart, keine Uebergabe-Kennungen, `invoice is None`). Die Verbotsliste fuer Quellen ist deshalb **leer**.

Schaden entstuende erst durch Vertragsbruch (Vorlage als `invoice`, geerbte Belegart, kopierte `uebergabe_beleg_*`), nicht durch den Status der Quelle.

## Bestand und Reihenfolge (Nachpruefung)

1. `create_invoice` liest Leistungsdaten nur ueber `parse_leistungszeit_from_form` und speichert sie. Eine fachliche Pruefung des Zeitraums vor dem Speichern ist im Anlageweg **nicht belegt**; sie liegt in `validate_invoice` (Finalisieren). Vorbefuellen aendert das nicht.
2. Ob der Browser-Cache/`no-store`-Schutz von `GET /neu` und die Zurueck-Erkennung in `form.html` mit Query-Parametern identisch greifen, ist **nicht belegt**. Zu messen: nach Speichern Zurueck auf die vorbefuellte History-URL; erwartet dasselbe Verhalten wie reine Neuanlage (kein zweites Anlegen ueber Cache).

## Abnahmekriterien

Alle Kriterien sind Vorgaben fuer spaetere Tests. Datenbankwirkung mit `pg_session`. Mutationen erst im spaeteren Auftrag einbauen und zuruecknehmen.

| ID | Ausfuehrbare Abnahme | Roter Fall: Mutation im Produktivcode |
|---|---|---|
| K1 | Gestellte Rechnung als `vorlage`: GET liefert 200, Formularaktion `/invoices/neu`, Titel Neuanlage, keine Rechnungsnummer der Vorlage sichtbar. Kunde, Positionen (Menge, Einheit, Preis, Beschreibung), Steuerkategorie, BT-13, BT-10, Leistungszeitraum, Zahlungsbedingungen, Bemerkungen vorbelegt. `issue_date` = heute, `due_date` = Neuanlage-Default. | Vorlage als `invoice` in den Template-Kontext legen (Aktion wird Bearbeiten) oder Datumsfelder aus der Vorlage fuellen. |
| K2 | Nach K1 speichern (POST `/invoices/neu`): neuer Entwurf, neue Nummer, Zaehler +1. Vorlage unveraendert (Nummer, Status, Positionstexte). Neue Rechnung hat `invoice_type` wie reine Neuanlage (kein geerbter Typ), keine `original_invoice_id`, keine `uebergabe_beleg_*`. | POST auf Bearbeiten der Vorlage umbiegen; oder `invoice_type` / Uebergabe-Felder aus der Vorlage setzen. |
| K3 | GET mit Vorlagen-UUID, Zaehler und Zeilenzahlen vorher merken: nach GET Zaehler und Zeilenzahlen gleich, Vorlage `updated_at` gleich, kein neues PDF. | Im GET `generate_next_invoice_number` aufrufen oder einen Audit-/Protokollschreibweg ausloesen. |
| K4 | Unbekannte UUID und ungueltiger Parameter: sichtbarer Fehler, kein neuer Datensatz. | Still auf leeres `/neu` ohne Meldung umleiten. |
| K5 | Vorlage mit `invoice_type='credit_note'`: Formular ohne Gutschrift-Kennzeichnung der Neuanlage; nach Speichern neuer Entwurf ohne `credit_note`. | `invoice_type` der Vorlage in den neuen Datensatz oder in ein verstecktes Formularfeld uebernehmen. |
| K6 | Genau eine Formularvorlage: Vorbelegung aendert `form.html` nur so, dass Feldwerte bei `invoice is None` aus der Vorbelegung kommen; kein zweites Formular-Template unter `templates/invoices/`. | Zweite Datei `form_kopie.html` (oder gleichwertig) einfuehren und nur fuer Vorbelegung rendern. |

## Migration, Unveraenderbarkeit und Nachweisgrenzen

**Keine Alembic-Migration.** Keine neue Spalte, kein Backfill.

**Unveraenderbarkeit wird nicht beruehrt:** Der GET schreibt nicht. Der POST ist die bestehende Neuanlage und aendert finalisierte Belege nicht. Vorlage bleibt unangetastet, wenn der Vertrag zu `invoice is None` gehalten wird.

Nicht ausgefuehrt: Suite, Mutationsproben, Browser-History mit Query-String. Nicht geprueft: ob inaktive Vorlagenkunden in bestehenden Installationen vorkommen. Abnahme K1 bis K6 gilt ohne zusaetzliche Quellenfilter.
