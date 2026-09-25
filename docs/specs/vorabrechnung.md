# Auftrag 2: Vorabrechnung und Belegart

Stand: 25.09.2026. Eigenstaendiger Spezifikationsauftrag fuer spaetere test-first Umsetzung. Kein Zahlungsbuch, keine Schlussrechnungsautomatik, keine automatische Halbierung von Positionen.

## Kernaussage und Entscheidung des Menschen

Eine Anzahlungsrechnung fordert eine Zahlung vor der Leistung an. TypeCode 386 kennzeichnet das maschinenlesbar; er macht den Beleg weder automatisch steuerlich richtiger noch professioneller. Die Wahl einer Belegart ersetzt keine korrekten Betraege, Leistungsbeschreibungen oder Steuerangaben.

**Die Lesart zur Restrechnung wird bestaetigt:** Das Tool braucht nicht allein wegen einer ersten Vorausrechnung zwingend eine Funktion zum Abzug erhaltener Anzahlungen. § 14 Abs. 5 Satz 2 UStG regelt den Fall einer Endrechnung. UStAE 14.8 Abs. 11 erlaubt stattdessen eine Rechnung nur ueber den Rest. Das ist keine Teilleistung allein deshalb, weil zwei Zahlungsraten vereinbart wurden. [UStG § 14, aktuelle abgerufene Fassung](https://www.gesetze-im-internet.de/ustg_1980/__14.html), [UStAE 14.8 Abs. 7 und 11, amtliche Ausgabe 2024](https://amtliche-handbuecher.bundesfinanzministerium.de/usth/2024/A-Umsatzsteuergesetz/IV-Steuer-und-Vorsteuer/Paragraf-14/inhalt.html)

**Aber:** Die Definition von 386 in UNTDID 1001 nennt auch den spaeteren Abzug von der Endrechnung. Wer nur den ersten Halbsatz als Definition verwendet, unterschlaegt eine fachliche Erwartung. Das ist kein nachgewiesener Zwang, in dieser Anwendung eine Schlussrechnung zu bauen, aber eine offene semantische Passungsfrage fuer genau den gewuenschten Ablauf ohne Endrechnung. Ein Schematron-Erfolg allein beantwortet sie nicht. [UNCL1001, D.16B, veroeffentlichtes Invoice-Subset](https://docs.peppol.eu/poacc/billing/3.0/codelist/UNCL1001-inv/)

| Produktentscheidung | Folge |
|---|---|
| A: Anlass weiter mit 380, Vorauscharakter in Beschreibung/Bemerkung ausdruecklich nennen | Empfehlung fuer den unveraenderten Ablauf, solange die Passung von 386 zur reinen Restrechnung nicht fachlich abgestimmt ist. Keine automatische Empfaengerklassifikation als Prepayment. |
| B: 386 als bewusste Wahl anbieten, erster Beleg 386 und zweiter Beleg 380 | Maschinelle Vorauskennzeichnung. Auftraggeber/Fachverantwortung klaert die genannte Erwartung mit dem Empfaenger. Implementierungsvertrag unten, ohne Schlussrechnungsmodul. |
| C: Gesamt-Schlussrechnung mit Abzug erhaltener Zahlungen | Aendert den ausdruecklich gewuenschten Ablauf. Eigenes groesseres Feature mit Zahlungszuordnung, Steueraufteilung und Abzugsdarstellung, nicht Teil dieses Auftrags. |

A/B ist eine Entscheidung des Auftraggebers, hier nicht getroffen. Die technische Spezifikation beschreibt B konkret, damit sie als getrennter Auftrag vergeben werden kann. Fuer A entfaellt die Freischaltung von 386; ein reines neues Titelwort ist kein Ersatz fuer diese Entscheidung. C wird nicht implizit mitbeauftragt. Die steuerliche Einordnung des Trainings in Finnland, etwa AE statt K, wird aus dem Kundenland nicht abgeleitet.

## Normen, Wirkung und Grenzen des Nachweises

Quellenstand: Abruf 25.09.2026. UNTDID 1001 **D.16B**, Peppol-Veroeffentlichung **Mai 2026**; EN16931-Regelartefakte von ConnectingEurope **validation-1.3.15**. Die gelesenen oeffentlichen Regelartefakte ersetzen keine behauptete Lektuere des vollstaendigen Normtexts EN 16931-1:2017.

| Frage | Beleg und Konsequenz |
|---|---|
| Was ist BT-3? | Dokumenttypcode. BR-04 verlangt ihn; BR-CL-01 bindet ihn an die rechnungsbezogenen Werte der UNTDID 1001. 386 ist ein zulaessiger Wert, kein neues XML-Profil. [BR-CL-01](https://docs.peppol.eu/poacc/billing/3.0/rules/ubl-tc434/BR-CL-01/), [CII-Modellregeln](https://raw.githubusercontent.com/ConnectingEurope/eInvoicing-EN16931/validation-1.3.15/cii/schematron/CII/EN16931-CII-model.sch) |
| Was bedeutet 386? | Zahlung fuer Waren/Dienstleistungen im Voraus; die Definition erwartet anschliessend einen Abzug in der finalen Rechnung. 380 ist die allgemeine Handelsrechnung. Die praktische Aenderung ist primaer die maschinelle Einordnung beim Empfaenger. Keine belegte Aussage ueber dessen konkreten Buchungsautomatismus. [UNCL1001 D.16B](https://docs.peppol.eu/poacc/billing/3.0/codelist/UNCL1001-inv/) |
| Ist BT-113 durch 386 Pflicht? | Nein, keine solche Bedingung in den gelesenen Regeln. BT-113 ist bereits gezahlter Betrag, nicht der jetzt angeforderte Anzahlungsbetrag. Kardinalitaet 0..1. BR-CO-16: Faelliger Betrag = Gesamtbetrag minus bereits gezahlter Betrag plus Rundung. [BT-113](https://docs.peppol.eu/poacc/billing/3.0/syntax/ubl-invoice/cac-LegalMonetaryTotal/cbc-PrepaidAmount/), [BR-CO-16](https://docs.peppol.eu/poacc/billing/3.0/rules/ubl-tc434/BR-CO-16/) |
| Leistungszeitpunkt bei 386? | Kein pauschal zusaetzliches Datumsfeld allein durch TypeCode 386 in den gelesenen CII-Modellregeln. Kategorieabhaengige Regeln bleiben, etwa BR-IC-11 fuer K. Ein noch nicht eingetretenes Ereignis darf nicht als tatsaechliche Lieferung ausgegeben werden. [CII-Regeln, BR-IC-11](https://raw.githubusercontent.com/ConnectingEurope/eInvoicing-EN16931/validation-1.3.15/cii/schematron/CII/EN16931-CII-model.sch) |
| Was gilt fachlich fuer die Vorabrechnung? | Vorauscharakter muss erkennbar sein. Nach UStAE 14.8 Abs. 4 ist der voraussichtliche Zeitpunkt beziehungsweise vereinbarte Zeitraum anzugeben; ist nichts vereinbart, muss dies erkennbar sein. [UStAE 14.8](https://amtliche-handbuecher.bundesfinanzministerium.de/usth/2024/A-Umsatzsteuergesetz/IV-Steuer-und-Vorsteuer/Paragraf-14/inhalt.html) |
| Schon bezahlt? | § 14 Abs. 4 Nr. 6 nennt fuer Absatz 5 den feststehenden Vereinnahmungszeitpunkt, sofern er vom Ausstellungsdatum abweicht. Das ist eine Sachverhaltsregel, keine Zusatzpflicht durch die Zahl 386. [UStG § 14](https://www.gesetze-im-internet.de/ustg_1980/__14.html) |

Die amtliche UStAE-Ausgabe 2024 wurde gelesen; die aktuelle konsolidierte PDF und die Ausgabe 2025 waren nicht lesbar. Eine lueckenlose Fortschreibung des Erlasses bis September 2026 ist **nicht belegt**. Die Restrechnungsbegruendung stuetzt sich auf den abgerufenen aktuellen Gesetzestext und den konkret genannten Erlassstand.

**Mustang:** Im Repo ist 2.24.0 im Dockerfile gepinnt, `EN16931` wird beim Kombinieren auf Profilflag E abgebildet. Der Validierungsaufruf erhaelt die Datei, kein frei erfundenes Profilargument. Welche mitgelieferten Factur-X-Regeln diese konkrete JAR zusaetzlich durchsetzt, ist ohne Artefaktpruefung und Lauf **nicht belegt**. Insbesondere nicht belegt: Erfolg einer 386 ohne BT-113, Erfolg ohne BT-72, Erfolg mit zukuenftigem BG-14 sowie Erfolg des eingebetteten PDF. Aus den gelesenen EN-Regeln ergibt sich keine 386-spezifische BT-113-Pflicht; das ist eine Quellenableitung, kein gemessener Mustang-Befund.

## Konkreter Vertrag fuer Option B

Naht: zwischen der internen Belegart und manueller Auswahl beziehungsweise den zwei Ausgaben PDF und CII. Eine zentrale Belegartbeschreibung soll zulaessige interne Werte, menschliche Auswahl und sichtbaren Titel zusammenhalten. Kein eigenes Modul fuer Raten oder Zahlungsverrechnung.

Schnittstelle, als Vertrag:

- `belegart(internal_value: str | None) -> Belegart`, sonst `UnknownInvoiceTypeError`.
- `manuelle_belegarten() -> tuple[Belegart, ...]`.
- `manuelle_belegart(form_value: str | None) -> str | None`, sonst `InvoiceTypeNotSelectable`.
- `Belegart` liefert kanonischen internen Wert, BT-3, PDF-Titel und manuelle Waehlbarkeit. Keine Laufzeitkonfiguration.

Die vorhandene `TYPE_CODE_MAP` kann dazu in eine fachliche Quelle umziehen; ihre bestehenden Aliase bleiben lesbar. Es soll kein zweites Mapping parallel entstehen. **Loeschtest:** Entfernt man diese Beschreibung, muessen Formular, PDF und XML getrennt ueber Typ, Titel und Auswahlrechte entscheiden. Entfernt man dagegen einen isolierten `prepayment_service`, der nur 386 zurueckgibt, verschwindet Komplexitaet. Einen solchen Durchreicher gibt es nicht.

**Zwei reale Adapter:** PDF-Titel und XML-BT-3 sind verschiedene Ausgaben derselben fachlichen Art; das Formular hat zusaetzlich eine engere Auswahl. Diese Variation besteht bereits bei 381 und 389. Es braucht keine hypothetischen austauschbaren Rechnungsanbieter, keine Repository-Abstraktion und keinen allgemeinen Workflow-Interpreter.

| Wert | Manuelle Auswahl | Interne Behandlung |
|---|---|---|
| fehlender Formularwert, `standard` | Ja, Standardrechnung; fehlender Wert bleibt abwaertskompatibel | Speicherung `None`, BT-3 380, Titel RECHNUNG |
| `prepayment` | Ja, Anzahlungsrechnung, nur bewusst gewaehlt | Speicherung `prepayment`, BT-3 386, Titel ANZAHLUNGSRECHNUNG |
| `invoice`, leere Zeichenfolge, rohe Codes wie `386` | Nein als POST-Wahl | Bestehender interner Alias `invoice` bleibt lesbar; leeres/missgebildetes Eingabefeld wird nicht still zu 380 |
| `credit_note`, `credit`, `storno` | Nein | 381 nur im Stornoweg, keine neue manuelle Gutschrift |
| `correction` | Nein | 384 systemreserviert; dieser Auftrag baut keinen Korrekturweg |
| `self_billing`, `self-billing` | Nein | 389 im bestehenden fachlichen Integrationsweg |
| unbekannter Wert | Nein | `INVOICE_TYPE_INVALID` im Validator und `UnknownInvoiceTypeError` im Generator bleiben fail-closed |

Reihenfolge beim Schreiben: bestehenden Entwurf und dessen Herkunft pruefen, manuelle Auswahl pruefen, Feldregeln pruefen, erst dann speichern beziehungsweise Nummer vergeben. Systembelege behalten ihre Art bei fehlendem Feld; mitgesendete manuelle Typaenderung wird abgelehnt, nicht ignoriert. Ein normaler draft darf zwischen Standard und Vorausrechnung wechseln. Ein finalisierter Beleg darf das nicht. Das Formular bietet fuer Systembelege kein editierbares Typfeld. Ein manipulierter POST scheitert serverseitig mit HTTP 400 und `INVOICE_TYPE_NOT_SELECTABLE`; der allgemeine Validator allein genuegt nicht, weil 381/389 allgemein gueltige Codes sind.

Vorgesehene Begrenzung des ersten 386-Schnitts: **noch nicht bezahlte Vorausforderung mit bekanntem geplantem Leistungszeitraum**. Formularhilfe nennt diese Begrenzung. Beginn und Ende werden ueber die bestehenden Periodenfelder erfasst, fuer einen einzelnen Tag gleich gesetzt. PDF bezeichnet sie bei 386 als voraussichtlichen Leistungszeitraum, XML schreibt BG-14. `delivery_date` bleibt leer; ein gesetztes tatsaechliches Lieferdatum bei 386 wird in diesem Schnitt als `PREPAYMENT_ACTUAL_DELIVERY` abgelehnt. Der Validator verlangt fuer 386 den vollstaendigen geordneten Zeitraum (`PREPAYMENT_PERIOD_REQUIRED` bei beidseitigem Fehlen); bestehende Fehler fuer Teilzeitraum und falsche Reihenfolge bleiben.

Diese Produktbegrenzung ist strenger als die allgemeinen Regeln und wird **nicht als EN16931-Pflicht verkauft**. Ein allgemeiner Modus fuer noch nicht vereinbarte Leistungszeitpunkte braucht eine ausdruecklich gespeicherte Erklaerung und eigene Ausgabe. Bereits vereinnahmte Zahlungen brauchen sachgerechte Datums- und Zahlungsabbildung. Beides ist ausserhalb dieses kleinen Schnitts. Nicht einfach alle Datumspruefungen fuer 386 abschalten oder das Rechnungsdatum als Lieferung einsetzen.

Beide Raten enthalten jeweils nur ihren eigenen Betrag. Im vorgeschlagenen Beispiel werden auf beiden Belegen die gleichen Teilnehmermengen und jeweils halbe vereinbarte Einzelpreise eingegeben. Der Belegtyp veraendert weder Vorzeichen noch Preise, Mengen, Steuerkategorie oder Zahlungsziel. Die Anwendung schreibt fuer diese unbezahlte Forderung kein `TotalPrepaidAmount`; `DuePayableAmount` entspricht dem eigenen Bruttobetrag. Insbesondere darf die zweite 380 nicht nochmals die erste Rate abziehen. Ein kuenftiges Schlussrechnungsfeature darf BT-113 nicht mit der gesamten steuerlichen Anzahlungsaufstellung verwechseln.

## Abnahmekriterien fuer Option B

Spaetere Tests ausschliesslich im Container, Datenbankwirkung mit `pg_session`. Beispielwerte sind kuenstlich: 3 Personen zu 100 EUR und 5 Personen zu 80 EUR als jeweilige halbe Preise, netto 700 EUR je Rate. Fuer isolierte Typpruefung zunaechst vorhandene Einheit Stück verwenden; IE ist kein Zwang zur Implementierungsreihenfolge der Auftraege. Steuerfall S mit 19 Prozent ergibt je 833 EUR brutto und zusammen 1666 EUR. Dies ist kein Vorschlag fuer die Besteuerung des finnischen Falls.

| ID | Ausfuehrbare Abnahme | Roter Fall: Mutation im Produktivcode |
|---|---|---|
| V1 | Neu- und normaler Entwurfseditor bieten exakt Standard und Anzahlung. Speichern und Neuladen erhaelt die Wahl. Fehlendes Feld bei Neuanlage ergibt 380. | Gesamte Typauswahl aus dem Mapping statt der manuellen Teilmenge rendern oder POST-Wert nicht speichern. |
| V2 | Anzahlung mit gueltigem Zeitraum: XML-BT-3 386, PDF-Titel ANZAHLUNGSRECHNUNG. Bei Standard: 380 und RECHNUNG. Positionen und Summen identisch. | prepayment auf 380 setzen, PDF-Titel auf Standard zurueckfallen lassen oder beim Typwechsel Preise halbieren. |
| V3 | Jede verbotene Wahl aus obiger Tabelle an Neu- und Edit-POST senden: 400, keine Daten-/Zaehleraenderung. Selbst 381-/389-Aliase werden nicht akzeptiert. | Manuelle Zulassung durch blosse Mitgliedschaft in TYPE_CODE_MAP ersetzen. |
| V4 | 389-Entwurf ohne Typfeld bearbeiten: Art bleibt 389. Mit `standard`/`prepayment` umtypisieren versuchen: 400, Art und Herkunft unveraendert. Storno bleibt im bestehenden gesperrten Editorweg. | Fehlenden Wert generell als None speichern oder Herkunftssperre nur im HTML ausfuehren. |
| V5 | Unbekannter intern gespeicherter Typ ergibt INVOICE_TYPE_INVALID; direkter XML-Aufruf wirft UnknownInvoiceTypeError. None und bisherige Aliase behalten ihre bisherigen Codes. | Gesamte Typaufloesung auf Default 380 umstellen. |
| V6 | Erste 386 und zweite 380 erzeugen: jeweils 700 netto, 833 brutto und zahlbar, kein BT-113, kein automatischer gegenseitiger Rechnungsbezug. | Bruttobetrag als TotalPrepaidAmount schreiben oder zweite Rate automatisch um 833 reduzieren. |
| V7 | 386 mit zukuenftigem vollstaendigem Zeitraum, ohne delivery_date: lokale Pruefung erfolgreich, PDF sagt voraussichtlich, XML enthaelt BG-14 und kein ActualDelivery-Ereignis. Fehlend/halb/umgekehrt sowie zusaetzliches delivery_date jeweils ablehnen. | BG-14 als ActualDelivery serialisieren, Periodenpflicht entfernen oder PDF als tatsaechliche Lieferung beschriften. |
| V8 | 380 oberhalb Kleinbetragsgrenze ohne Leistungszeitpunkt bleibt gesperrt; K ohne Datum/Zeitraum bleibt unabhaengig vom Betrag gesperrt. | Fuer alle Arten/Kategorien die Datumspruefung abschalten. |
| V9 | Nach Commit als issued oder paid jede Typaenderung ueber ORM versuchen: Guardfehler. Aenderung eines normalen draft zwischen den beiden manuellen Arten gelingt. | invoice_type in MUTABLE_AFTER_FINALIZE aufnehmen oder draft-Aenderungen pauschal sperren. |
| V10 | Mit der gepinnten JAR erzeugte 386-CII ohne BT-113 und BT-72, mit zukuenftigem BG-14, sowie daraus eingebettetes EN16931-PDF pruefen: beide gueltig. BT-3 separat als exakt 386 behaupten, nicht nur Validatorgrün. | Generator schreibt ungueltigen Typcode oder fehlerhafte Summen; alternativ mappt er auf 380, dann muss die explizite BT-3-Assertion rot werden. |

**Nachtrag 25.09.2026, gemessen:** V10 ist bei der Umsetzung im Container mit der gepinnten JAR 2.24.0 gelaufen und **gruen**. Die 386-CII ohne BT-113 und BT-72 mit zukuenftigem BG-14 validiert, das daraus eingebettete EN16931-PDF ebenfalls, und BT-3 ist getrennt als exakt 386 zugesichert. Dass Mustang dabei wirklich urteilt, ist gegengeprueft: ein ungueltiger Waehrungscode, den keine Python-Zusicherung des Tests anschaut, macht beide Faelle rot. Der folgende Absatz beschreibt den Stand der Spezifikation davor.

V10 war eine **noch nicht gemessene Integrationsannahme und Freigabebedingung**. Scheitert sie, konkreten Mustang-Regelcode, Rohbericht, JAR-Fassung und erzeugte XML untersuchen. Nicht mit erfundener Zahlung, falschem Lieferdatum oder schwaecherem Profil gruen machen. Der Befund kann eine Anpassung dieses Schnitts erfordern. Separate Messreihe mit ausgelassenem BG-14 darf die EN-Regelfrage isolieren, hebt aber die bewusst strengere Produktbegrenzung nicht auf.

## Migration, Unveraenderbarkeit und nicht ausgefuehrte Arbeit

**Keine Alembic-Migration** fuer Option B: `invoice_type` ist bereits nullable String und `prepayment` passt hinein; Periodenfelder existieren. Kein BT-113-Feld, kein Backfill, kein Eingriff in Kopf 014. Ein spaeteres Zahlungs-/Schlussrechnungsmodell waere neu zu schneiden.

Unveraenderbarkeit ist betroffen, weil die Art und der PDF-Titel Rechnungsinhalt sind. Keine Erweiterung von `MUTABLE_AFTER_FINALIZE`, keine neuen Statusuebergaenge. Quelltextabweichung zum Brief: DB-Trigger verhindern DELETE/TRUNCATE, inhaltliche UPDATEs werden derzeit nur vom ORM-Guard geschuetzt. Das ist in `docs/ARCHITEKTUR.md` dokumentiert; ein gleichwertiger DB-UPDATE-Schutz ist **nicht belegt und im gelesenen Triggercode nicht vorhanden**. Kein stiller Ausbau in diesem Feature.

Nicht ausgefuehrt: Suite, Mustang, PDF-Erzeugung, Migration, Datenbankzugriff und Mutationsproben. Nicht geprueft: Empfaengerbuchhaltung, konkreter Trainingsvertrag, tatsaechliche Zahlungseingaenge, steuerliche Behandlung des Finnlandfalls, vollstaendiger Normtext, genaue mitgelieferte Schematron-Fassung der installierten JAR. Der direkte Abruf der UNECE-D.16B-Seite war gesperrt; fuer deren Definition wird die ausdruecklich als D.16B ausgewiesene Peppol-Veroeffentlichung verwendet.
