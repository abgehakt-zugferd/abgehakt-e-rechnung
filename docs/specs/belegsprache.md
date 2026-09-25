# Auftrag: Belegsprache Deutsch und Englisch

Stand: 25.09.2026. Spezifikation fuer einen getrennten, spaeter test-first auszufuehrenden Auftrag. Keine Implementierung. Kein Produktivcode, keine Tests und keine Migration sind Teil dieses Auftrags.

## Ergebnis und fachlicher Umfang

Jede Rechnung traegt genau eine Belegsprache: `de` oder `en`. Sie steuert ausschliesslich die maschinell erzeugte menschliche Darstellung des Belegs, insbesondere das PDF und dessen Zahlen- und Datumsdarstellung. Sie haengt weder am Kundenland noch an einer globalen Laufzeitsprache.

**Auftraggeberentscheidung:** Die Sprache gehoert zur Rechnung, nicht zur globalen Einstellung. Ein Entwurf zeigt damit weiterhin, in welcher Sprache er gedacht ist; ein fertiges PDF bleibt ohnehin eingefroren.

**Quelltextbefund:** `pdf_generator.py` erzeugt heute das deutsche PDF, `darstellung.py` formatiert Betrage als `1.050,00 €` und Mengen mit Dezimalkomma. `belegart.py` liefert heute die deutschen Titel `RECHNUNG`, `ANZAHLUNGSRECHNUNG`, `GUTSCHRIFT` und `KORREKTURRECHNUNG`.

**Quelltextbefund:** Neben den im Anlass genannten Texten stehen im PDF auch `Leistungsdatum`, `Voraussichtlicher Leistungszeitraum`, `Ihre Referenz`, `MwSt.`, `Gutschriftbetrag`, `USt-IdNr.`, `Steuernummer`, die Steuerhinweise, die drei Fallback-Zahlungstexte und der Entwurfsstempel `ENTWURF`. Sie gehoeren zum Sprachumfang. Firmen-, Kunden- und Bankdaten werden dagegen als Daten ausgegeben, nicht als Schablonentexte.

**Vorgabe:** Der englische Beleg verwendet mindestens diese Bezeichnungen: `INVOICE`, `PREPAYMENT INVOICE`, `CREDIT NOTE`, `CORRECTIVE INVOICE`, `Invoice number`, `Invoice date`, `Date of supply`, `Period of supply`, `Expected period of supply`, `Due date`, `Customer number`, `Your reference`, `Purchase order number`, `Customer VAT ID`, `No.`, `Description`, `Quantity`, `Unit`, `Unit price`, `VAT`, `Amount`, `Net amount`, `Credit note amount`, `Invoice total`, `Reference`, `Scan to pay`, `VAT ID`, `Tax number` und `DRAFT`.

**Vorgabe:** Die Steuerzeile lautet auf Englisch `plus {satz} % VAT on {basis}`. Die deutschen Fassungen bleiben `zzgl. {satz} % MwSt. auf {basis}`. Die englischen Fallback-Texte lauten `Please transfer the credit note amount to the bank account below.`, `Credit note without payment request.` und `Payable without deduction.`. Diese Texte sind Schablone, nicht Nutzereingabe.

**Vorgabe:** Positionsbeschreibungen, Bemerkungen, Zahlungsbedingungen sowie Kunden-, Firmen- und Bankdaten werden nie uebersetzt. Es gibt keine maschinelle Uebersetzung und keine Sprachableitung aus Adresse, Land oder USt-IdNr. Ein englischer Beleg kann deshalb deutsche Nutzereingaben enthalten und umgekehrt.

## Naht und vollstaendiger Vertrag

Die Naht liegt zwischen einem gespeicherten Sprachcode und der vollstaendigen Belegdarstellung. Vorgesehener Ort: `backend/app/services/belegsprache.py`. Das Modul hat keine Abhaengigkeit auf HTTP, Jinja, Datenbank, ReportLab, XML oder das `Invoice`-Modell.

Schnittstelle als Spezifikation, nicht als auszufuehrender Code:

- `resolve_belegsprache(wert: str | None) -> Belegsprache`, akzeptiert nur `de` und `en`, wirft bei jedem anderen gespeicherten oder uebermittelten Wert `UnknownDocumentLanguageError(wert)`.
- `darstellung(sprache: Belegsprache) -> Belegdarstellung`.
- `Belegdarstellung`: unveraenderlicher Datensatz mit allen PDF-Schablonentexten, `format_betrag(wert)`, `format_menge(wert)`, `format_datum(datum)`, `titel(belegart_intern)` und `steuerhinweis(kategorie)`.

**Invarianten:** `de` und `en` sind die einzigen Codes. Die Auswahl, die serverseitige POST-Pruefung, die PDF-Erzeugung, die Titel der Belegarten, die Fallback-Zahlungstexte und alle Zahlen- und Datumsformate lesen dieselbe `Belegdarstellung`. Ein unbekannter Code faellt nicht auf Deutsch zurueck, weil ein fremdsprachiger Beleg sonst unbemerkt falsch beschriftet wuerde. Der alleinige Kompatibilitaetsdefault ist der beim Anlegen noch fehlende Formularwert `de`; ein bereits gespeicherter ungueltiger Wert ist ein harter Fehler vor Nummernvergabe und vor PDF/XML-Erzeugung.

**Vorgabe:** `belegart.py` behaelt die fachlichen Werte, BT-3-Codes und die manuelle Waehlbarkeit. Der sichtbare Titel ist keine weitere feste Zeichenkette in `belegart.py`, sondern wird mit dem fachlichen internen Wert durch `Belegdarstellung.titel(...)` aufgeloest. Damit bleibt Belegart Fachlogik und Sprache Darstellung.

**Loeschtest:** Ohne `belegsprache.py` tauchen Labels, vier Belegtitel, Fallback-Texte, Steuerhinweise, Geld-, Mengen- und Datumsregeln in PDF-Generator, `darstellung.py`, Belegart und Router wieder auf. Das Modul traegt diese gemeinsame Komplexitaet hinter einer kleinen Schnittstelle. Ein `get_language(invoice)`-Durchreicher, der nur `invoice.document_language` zurueckgibt, bestuende den Test nicht.

**Ein realer Adapter:** Das PDF ist der einzige heutige Verbraucher der lokalisierten Schablone. Die XML ist kein zweiter Adapter fuer dieselbe Darstellung, siehe Abschnitt XML. Die Weboberflaeche bleibt deutsch und ist ausdruecklich kein zweiter lokalisierter Ausgabekanal; sie bietet nur die deutsche Eingabeauswahl `Belegsprache` mit Deutsch und Englisch. Eine austauschbare PDF-, HTML- oder XML-Ausgabeschnittstelle wird nicht vorsorglich erfunden.

## Zahlen, Daten und Schablonentexte

| Sprache | Betrag | Menge | Datum | Waehrung |
|---|---|---|---|---|
| `de` | `1.050,00` | `2,5` | `09.10.2026` | nachgestellt: `1.050,00 €` |
| `en` | `1,050.00` | `2.5` | `2026-10-09` | vorangestellt: `EUR 1,050.00` |

**Quelltextbefund:** Die heutige deutsche Funktion rundet Geld kaufmaennisch auf zwei Nachkommastellen, Mengen nicht auf feste Nachkommastellen, und nutzt keinen prozessweiten Locale-Zustand. Diese Rechen- und Zustandsregeln bleiben fuer beide Sprachen erhalten.

**Vorgabe:** Englisch verwendet Punkt als Dezimal- und Komma als Tausendertrennzeichen. Das Waehrungszeichen wird nicht als `$` oder `€` geraten, sondern die bestehende Rechnungswaehrung als Code vorangestellt. Der derzeit einzige erzeugte Waehrungscode ist `EUR`; daher lautet das Abnahmebeispiel `EUR 1,050.00`.

**Entscheidung mit Begruendung:** Englisch verwendet ISO `YYYY-MM-DD`, nicht `DD.MM.YYYY` und nicht ein amerikanisches Monatsformat. `09.10.2026` ist fuer einen amerikanischen Leser mehrdeutig; `2026-10-09` ist es nicht, bleibt sprachneutral und sortiert lexikografisch chronologisch. Die XML behaelt ihr normgerechtes `YYYYMMDD` und wird davon nicht beruehrt.

**Vorgabe:** Die PDF-Steuerhinweise fuer E, K und O erhalten englische Schablonen. Der Reverse-Charge-Hinweis AE bleibt in beiden Sprachmodi exakt zweisprachig: `Steuerschuldnerschaft des Leistungsempfängers / reverse charge, Art. 196 Council Directive 2006/112/EC`. Er wird nicht gekuerzt, uebersetzt oder durch einen Code ersetzt.

**Quelltextbefund:** Der Stornoweg erzeugt heute deutsche Zahlungsbedingungen und Bemerkungen mit Rechnungsnummer und Datum. Diese beiden automatisch erzeugten Texte muessen aus `Belegdarstellung` stammen, damit ein Storno einer englischen Rechnung englisch bleibt. Positionen, Referenzen und andere kopierte Nutzerdaten bleiben unveraendert.

## Eingabe, Vorgaben und Vorlage

**Vorgabe:** Neu- und Bearbeitungsformular speichern `document_language` serverseitig. Neu ohne Feld bedeutet `de` zur Abwaertskompatibilitaet; jeder andere POST-Wert ergibt HTTP 400 vor Nummernvergabe oder Aenderung. Ein Entwurf darf seine Sprache aendern. Ein finalisierter Beleg nicht.

**Auftraggeberentscheidung:** Die Einstellungen enthalten zwei sprachgebundene Standard-Zahlungsbedingungen, eine deutsche und eine englische. Beide Felder sind Pflichtfelder beim Speichern der Einstellungen. Eine Bestandsinstallation ohne englische Vorgabe darf weiter deutsche Entwuerfe anlegen, aber keine englische Rechnung anlegen oder speichern, bis die englische Vorgabe ausgefuellt ist. Die Migration erfindet keinen Vertragstext.

**Vorgabe:** Beim Anlegen erhaelt ein leeres Zahlungsbedingungen-Feld die Vorgabe der gewaehlten Sprache. Ein Sprachwechsel im Entwurf ueberschreibt nie vorhandene Zahlungsbedingungen, weder eigene noch aus einer Vorlage. Das vermeidet die stillschweigende Uebersetzung oder Vernichtung von Nutzereingabe; der Nutzer kann das Feld leeren, um die passende Vorgabe zu verwenden.

**Entscheidung:** `GET /invoices/neu?vorlage=<uuid>` vererbt die Sprache. `kopieren.md` schliesst die Belegart aus, weil sie einen fachlichen Vorgang mit eigenen Erzeugungswegen und Wirkungen ausloest. Die Sprache ist dagegen Inhalt und Darstellungsabsicht des kopierten Entwurfs, gerade der vom Auftraggeber genannte Grund gegen eine globale Einstellung. Sie hat keine Storno-, Gutschrift- oder Anzahlungswirkung. Der Feldvertrag von `kopieren.md` wird deshalb um `document_language` erweitert; `invoice_type` bleibt weiterhin nie geerbt.

**Quelltextbefund:** Die heutige Vorbelegung transportiert `payment_terms`, aber weder `invoice_type` noch `original_invoice_id` oder Uebergabekennungen. Die neue Sprache wird gleichartig als eigene Vorbelegungsinformation, nie als `invoice`, uebergeben.

## XML und Reverse Charge

**Quelltextbefund:** `zugferd_xml.py` schreibt keinen Sprachcode und kein Sprachattribut. Es schreibt strukturierte Codes, darunter BT-3, ISO-Waehrung, Laender, Steuerkategorie, VATEX-EU-AE und Einheitencode, sowie die Freitexte Positionsbeschreibung, Bemerkung, Zahlungsbedingungen und Befreiungsgrund.

**Normbefund:** EN16931 bindet semantische Geschaeftsterme an XML-Syntaxen; Peppol behandelt die CII-Ausgabe als derselben Regelmenge unterworfen. Die gelesene Peppol-Referenz nennt Sprachkennungen in UBL als nicht zu verwendende Zusatzattribute, nicht als Belegsprache des EN16931-Kerns. Daraus folgt fuer diesen CII-Generator: kein neues XML-Sprachfeld und keine Sprache in Codes. [Peppol BIS Billing, Anhang B und Syntaxregeln](https://docs.peppol.eu/poacc/billing/3.0/bis/)

**Normbefund:** Der Steuerbefreiungsgrund darf als Text in einer anderen Sprache vorliegen; die Peppol-Regel akzeptiert einen gleichwertigen Standardtext in anderer Sprache. Das bestaetigt die Lokalisierung des Freitextes, nicht einen neuen Sprachcode. [Peppol VAT exemption reason](https://docs.peppol.eu/poacc/billing/3.0/syntax/ubl-invoice/cac-TaxTotal/cac-TaxSubtotal/cac-TaxCategory/cbc-TaxExemptionReason/)

**Auftraggeberentscheidung:** Fuer AE bleibt der oben zitierte zweisprachige Wortlaut in PDF und XML auch im englischen Modus. Der XML-Generator bekommt fuer E, K und O keine automatische Uebersetzung von Nutzertexten. Ob deren gesetzliche Befreiungstexte im englischen PDF zugleich in der XML englisch, deutsch oder zweisprachig stehen sollen, ist nicht entschieden: nur PDF-englisch laesst XML beim bisherigen deutschen Rechtstext; eine gemeinsame englische Fassung aendert auch die XML-Freitexte. Beide Wege sind normseitig nicht durch einen Sprachcode unterscheidbar.

**Auftraggeberentscheidung, 25.09.2026:** Die XML behaelt fuer E, K und O den deutschen Rechtstext, auch wenn das PDF englisch ist. Begruendung: die XML liest eine Maschine, und der deutsche Wortlaut ist der, den eine Betriebspruefung erwartet. Der englische Modus aendert damit ausschliesslich das PDF. Praktisch beruehrt das den Anlassfall nicht, der auf AE laeuft; dort bleibt der Hinweis ohnehin in beiden Ausgaben zweisprachig.

## Migration, Unveraenderbarkeit und Archiv

**Quelltextbefund:** Alembic-Kopf ist `014`; `Invoice.invoice_type` ist eine normale Modellspalte und `MUTABLE_AFTER_FINALIZE` erlaubt ausschliesslich `status`, `datev_sent_at` und `updated_at`. Der ORM-Guard sperrt damit jedes neue Rechnungsinhaltsfeld nach `issued`, `paid` oder `cancelled`.

**Vorgabe:** Die naechste, erst bei Umsetzung aus dem dann geltenden Kopf abgeleitete Migration fuegt `invoices.document_language` als nicht leeren Zweibuchstabencode mit Default `de` hinzu. Sie fuegt ausserdem die englische Zahlungsbedingungen-Vorgabe an `company` hinzu. Keine Nummer wird vorab reserviert.

**Vorgabe:** Die Migration setzt jeden Bestandsbeleg explizit auf `de`, weil der heutige PDF-Generator deutsch ist. Das ist ein Datenherkunftsbefund, keine nachtraegliche Deutung aus Kundenland oder Freitext. Sie erzeugt keine PDFs oder XML neu, aendert keine Datei und ersetzt keine Archivkopie. Die neue englische Firmenvorgabe bleibt fuer die Bestandskonfiguration leer, bis der Nutzer sie als Pflichtangabe speichert.

**Vorgabe:** `document_language` kommt nicht in `MUTABLE_AFTER_FINALIZE`. Ein ORM-Aenderungsversuch an einer finalisierten Rechnung muss denselben `InvoiceStateError` wie bei `invoice_type` ausloesen. Ein Entwurf darf wechseln. Der Stornobuilder uebernimmt die Sprache des Originals, setzt aber seine eigene Belegart und seine neue Nummer.

**Quelltextbefund:** Der Datenbank-Trigger schuetzt DELETE und TRUNCATE, nicht UPDATE. Die gleichwertige Sperre fuer `document_language` ist deshalb heute nur der ORM-Guard; eine DB-UPDATE-Sicherung wird in diesem Auftrag weder behauptet noch implizit eingefuehrt.

**Quelltextbefund:** Finalisieren erzeugt PDF und XML vor dem Commit, archiviert beide Dateien und speichert `pdf_filename`; der Download liest die archivierte Datei, nicht eine Neugenerierung. Ein spaeterer Sprachwechsel darf folglich alte PDFs weder neu erzeugen noch beim Lesen umformatieren.

## Abnahmekriterien

Alle Kriterien sind Vorgaben fuer spaetere Tests. Datenbankwirkung wird mit `pg_session` geprueft. Mutationen erst im spaeteren Auftrag einbauen und zuruecknehmen.

| ID | Ausfuehrbare Abnahme | Roter Fall: Mutation im Produktivcode |
|---|---|---|
| S1 | Mit `pg_session` einen deutschen und einen englischen Entwurf anlegen. Ungueltiger POST-Wert, leerer manipulierter Wert und ein direkt gesetztes unbekanntes `document_language` ergeben vor Zaehlererhoehung beziehungsweise PDF-Erzeugung einen harten Fehler. Fehlendes Feld bei Neuanlage ergibt `de`. | Resolver auf unbekanntes oder leeres `de` zurueckfallen lassen oder Validierung erst nach `generate_next_invoice_number` aufrufen. |
| S2 | Ein englisches PDF mit 1050, 2.5 und Datum 2026-10-09 textlich auslesen: `EUR 1,050.00`, `2.5`, `2026-10-09`, englische Kopfzeilen, Tabellenkopf, Summen, Zahlungsblock, Steuerzeile und englischer Titel sind vorhanden. Keine deutsche Schablone und kein `1.050,00 €` erscheinen. | Im englischen Zweig weiter `darstellung.euro`, `%d.%m.%Y` oder eine einzelne deutsche Kopfzeile verwenden. |
| S3 | Im selben Prozess erst einen englischen, danach einen deutschen Beleg erzeugen. Der zweite zeigt `1.050,00 €` und `09.10.2026`, der erste bleibt `EUR 1,050.00` und `2026-10-09`; kein Ergebnis haengt von der Reihenfolge ab. | `locale.setlocale` pro Beleg setzen oder eine globale aktuelle Sprache zwischenspeichern. |
| S4 | Standard, Anzahlung, Storno/Gutschrift und Korrektur je in `de` und `en` als PDF erzeugen. Alle acht Titel entsprechen der Sprachmatrix; ein Storno einer englischen Rechnung hat englische automatisierte Zahlungsbedingungen und Bemerkung, dieselben Positionen und `document_language='en'`. | Titel in `belegart.py` deutsch fest verdrahten oder `build_storno` die Sprache nicht kopieren lassen. |
| S5 | AE-Rechnung in beiden Sprachen erzeugen und PDF sowie XML lesen. Der Befreiungsgrund ist jeweils exakt `Steuerschuldnerschaft des Leistungsempfängers / reverse charge, Art. 196 Council Directive 2006/112/EC`; `VATEX-EU-AE` bleibt erhalten. | AE im englischen Zweig auf nur `reverse charge` kuerzen oder den VATEX-Code vom Sprachzweig abhaengig machen. |
| S6 | `GET /invoices/neu?vorlage=<uuid>` fuer englische Vorlage rendern: Sprachwahl ist Englisch, Positionen und Nutzereingaben bleiben wortgleich, Belegart startet Standard. Nach POST besitzt der neue Entwurf `document_language='en'`, aber nicht die Belegart, Originalreferenz oder Uebergabekennungen der Vorlage. GET selbst veraendert mit `pg_session` keine Zeile, keinen Zaehler und keine Datei. | `document_language` aus der Vorbelegung ausschliessen oder analog dazu `invoice_type` mitkopieren. |
| S7 | Englische Zahlungsbedingungen in den Einstellungen leer lassen: deutscher Entwurf bleibt moeglich, englisches Anlegen oder Speichern scheitert sichtbar ohne Nummer oder Teilpersistenz. Nach ausgefuellter englischer Vorgabe verwendet ein leeres englisches Feld diese Vorgabe; Sprachwechsel ueberschreibt einen vorhandenen Text nicht. | Englische Leervorgabe auf den deutschen Vertragstext zurueckfallen lassen oder bei Sprachwechsel stets `payment_terms` ersetzen. |
| S8 | Mit `pg_session` finalisierte Rechnung ueber ORM an `document_language` aendern: `InvoiceStateError`; derselbe Wechsel im Entwurf gelingt. Archiv-PDF und gespeicherte XML einer vorher finalisierten deutschen Rechnung nach einem spaeteren englischen Entwurf bytegleich lesen; Download ruft keinen Generator auf. | `document_language` zu `MUTABLE_AFTER_FINALIZE` hinzufuegen oder PDF-Download aus der Rechnung neu erzeugen. |
| S9 | Migration von Kopf 014 auf den dann erzeugten Nachfolger mit einer deutschen Bestandsrechnung ausfuehren. Ihre Zeile erhaelt `de`; `pdf_filename`, Archivdatei und `zugferd_xml` bleiben unveraendert. Die englische Firmenvorgabe wird nicht mit erfundenem Text gefuellt. | Kundenland zur Spracherkennung verwenden, PDF/XML in der Migration generieren oder englische Vorgabe mit deutschem Standard vorbelegen. |
| S10 | XML einer deutschen und englischen Rechnung parsen: TypeCode, Waehrungs-, Laender-, Steuer-, VATEX- und Einheitencodes sind gleich; Datumswerte bleiben `YYYYMMDD`. Nutzereingaben in Beschreibung, Bemerkung und Zahlungsbedingungen werden zeichengetreu ausgegeben. Kein neues XML-Element oder -Attribut fuer die Belegsprache entsteht. | Sprache in `TypeCode`, `InvoiceCurrencyCode` oder ein erfundenes CII-Sprachfeld schreiben; Nutzereingabe automatisch uebersetzen. |

## Nicht ausgefuehrt / nicht geprueft

Nicht ausgefuehrt: Suite, einzelne Tests, Docker, Datenbankabfragen mit `pg_session`, Migration, PDF-Erzeugung, Mustang, Archivzugriff und Mutationsproben. Nicht gemessen ist damit insbesondere, ob der bestehende CII/Mustang-Pfad englische E-, K- und O-Befreiungstexte annimmt. Der spaetere Containerlauf dafuer lautet `backend/run-tests.sh`, oder im gestarteten Entwicklungsstack `docker compose exec -T app python -m pytest tests/ < /dev/null`.

Nicht geprueft: reale Bestandsbelege und deren Freitexte, Akzeptanz durch die finnische Empfaengerbuchhaltung, die fachlich verbindliche englische Fassung der E-, K- und O-Befreiungstexte. Die Abnahme S1 bis S10 ersetzt keine Empfaenger- oder Steuerberatung.
