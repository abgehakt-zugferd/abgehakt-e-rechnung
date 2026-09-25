# Auftrag 1: Einheiten aus einer Quelle

Stand: 25.09.2026. Spezifikation fuer einen getrennten, spaeter test-first auszufuehrenden Auftrag. Keine Implementierung. Bestand aus dem Brief wird vorausgesetzt.

## Ergebnis und fachlicher Umfang

Formular, Eingabepruefung und XML benutzen denselben Einheitenkatalog. Personen sind eine eigene Zaehleinheit. Die Bezeichnung auf dem Beleg und der technische Code sind verschiedene Eigenschaften derselben Einheit. Unbekannte Werte werden niemals zu Stueck umgedeutet.

Der Anlass braucht zwei Positionen fuer zwei Preisklassen, zusammen acht Personen. Die Aufteilung auf die Preisklassen und deren Preise sind nicht genannt und werden nicht erfunden. Fuer Abnahmebeispiele sind 3 und 5 Personen synthetische Daten. Beide Positionen behalten die volle Teilnehmerzahl; fuer eine Rate werden die vereinbarten anteiligen Preise eingegeben. Dieses Feature berechnet weder Raten noch Rabatte.

**Codeentscheidung:** Person und Personen erhalten `IE`. Recommendation 20, gelesene Fassung **Revision 11e**, veroeffentlicht in der Einheitenliste von Peppol BIS Billing 3.0, Release Mai 2026: `IE`, Name `person`, Definition: "A unit of count defining the number of persons." Damit existiert ein passender Code; `C62` ist hier keine notwendige Ersatzwahl. [Recommendation 20, Eintrag IE](https://docs.peppol.eu/poacc/billing/3.0/codelist/UNECERec20/)

Die Veroeffentlichung enthaelt auch Recommendation-21-Codes mit X-Praefix; `IE` gehoert zu Recommendation 20. Die neuere UNECE-Datei [Revision 17, 2021](https://unece.org/sites/default/files/2023-10/rec20_Rev17e-2021.xlsx) konnte nicht gelesen werden. Ihr Inhalt und ihr Aenderungsstand zu IE sind **nicht belegt**. Der Code wird deshalb auf die tatsaechlich gelesene Fassung gestuetzt, nicht auf eine behauptete Pruefung der Excel-Datei. Die [UNECE-Vokabularseite](https://service.unece.org/trade/uncefact/vocabulary/rec20/) war ebenfalls nicht vollstaendig abrufbar.

## Naht und vollstaendiger Vertrag

Die Naht liegt zwischen fachlicher Einheitenidentitaet und ihren Darstellungen. Vorgesehener Ort: `backend/app/services/einheiten.py`. Keine Abhaengigkeit auf HTTP, Jinja, XML, Datenbank oder das Invoice-Modell.

Schnittstelle als Spezifikation, nicht als auszufuehrender Code:

- `einheiten() -> tuple[Einheit, ...]`
- `resolve_einheit(wert: str) -> Einheit`, wirft `UnknownUnitError(wert)`.
- `Einheit`: unveraenderlicher Datensatz mit `key`, `un_code` und geordneter Folge `bezeichnungen`.

**Invarianten:** Jede akzeptierte Bezeichnung gehoert genau einer Einheit. Jede Einheit hat genau einen expliziten UN/ECE-Code. Alle Bezeichnungen im Formular stammen aus `einheiten()`. Jeder angebotene Wert ist durch `resolve_einheit` aufloesbar; umgekehrt sind alle katalogisierten Bezeichnungen waehlbar. Singular, Plural und englische Schreibweise teilen denselben Code. Es gibt keine zweite Liste im Template, JavaScript oder Generator. Die Reihenfolge ist stabil und entspricht der folgenden Tabelle.

| key | Bezeichnungen, zugleich gespeicherte Formularwerte | Code |
|---|---|---|
| piece | Stück | C62 |
| person | Person, Personen, Persons | IE |
| hour | Stunde, Stunden | HUR |
| day | Tag, Tage | DAY |
| month | Monat, Monate | MON |
| kilometre | Kilometer | KMT |
| metre | Meter | MTR |
| kilogram | kg | KGM |
| litre | Liter | LTR |
| lump_sum | Pauschal, Pauschale | LS |

Die vorhandenen 13 Zuordnungen bleiben kompatibel; sie werden zusammengefuehrt, nicht fachlich neu definiert. Fuer Personen kommen drei Bezeichnungen hinzu. Die Tabelle ist eine Vorgabe fuer den Katalog, keine zweite Laufzeitquelle. Eingaben werden aussen getrimmt, danach exakt verglichen; keine freie Gross-/Kleinschreibungsheuristik, kein Default fuer leere oder unbekannte Werte. Das Formular setzt fuer eine neue Position weiterhin explizit `Stück` vor. Ein manipulierter leerer Wert ist kein solcher Default.

`InvoiceItem.unit` bleibt der gewaehlt gespeicherte Text. PDF und Ansicht zeigen ihn unveraendert, XML loest ihn ueber den Katalog auf. Fuer einen englischen Beleg waehlt man `Person` oder `Persons`; es gibt keine automatische Sprachwahl aus dem Kundenland. Eine vollstaendige englische Rechnungsoberflaeche ist ausserhalb dieses Auftrags. Das ist eine bewusste kleine Loesung fuer die englische Positionsbezeichnung ohne neues Sprachmodell und ohne Umschreiben alter Rechnungen.

Es besteht kein Konfigurationsbedarf im empfohlenen festen Katalog. Kein Netzabruf zur Laufzeit. Der Aufrufer muss weder Aliasregeln noch Codezuordnungen kennen.

**Zwei reale Adapter:** Das Formular erzeugt Wahlmoeglichkeiten und der CII-Generator erzeugt `BilledQuantity/@unitCode`. Beide brauchen heute dieselben Informationen in verschiedener Form. Der Validator ist ein weiterer Verbraucher. Eine austauschbare Datenquellen-Schnittstelle mit Code- und SQL-Implementierungen wird dagegen nicht vorsorglich eingefuehrt: davon existiert nur eine Variante.

**Loeschtest:** Ohne den Katalog tauchen Zuordnung, Altbezeichnungen und Fehlerpolitik mindestens bei Formular, Validator und XML wieder auf. Das Modul traegt diese Komplexitaet. Ein zusaetzlicher `get_units`-Service, der nur eine bereits vollstaendige Liste durchreicht, bestuende den Test nicht.

## Freie Konfiguration: Entscheidung beim Auftraggeber

Der Wunsch nach freier Konfiguration ist ausdruecklich aufgenommen. Die folgende Empfehlung ersetzt diese Produktentscheidung nicht.

| Option | Folgen und Kosten |
|---|---|
| A: fester zentraler Katalog, Empfehlung fuer diesen Anlass | Keine Verwaltungsoberflaeche, keine Migration, neue Einheit per Release. Personen und englische Bezeichnung sind sofort abgedeckt. Erfuellt keine beliebige freie Anlage durch Anwender. |
| B: eigene Bezeichnungen mit Auswahl eines Codes aus einer lokal versionierten Recommendation-20-Liste | Erfuellt den Konfigurationswunsch. Braucht Suche mit Code, Name und Definition, Pflichtzuordnung, Eindeutigkeitspruefung, Pflege der Codelistenfassung, Deaktivieren statt Loeschen sowie unveraenderliche Zuordnungen bereits verwendeter Einheiten. Anwender entscheiden die fachliche Passung. |
| C: eigener Name und frei einzutippender Code | Gleiche Persistenzkosten wie B; zusaetzlich Tippfehler und hoehere Fachkenntnis. Selbst hier muss der Code gegen die gewaehlte Liste geprueft werden. Ein syntaktisch gueltiger, fachlich falscher Code bleibt moeglich. Nicht empfohlen. |

**Empfehlung A:** Der belegte Bedarf sind Teilnehmer, nicht eine neue Mengendimension. Ein fester Katalog beseitigt die vorhandene Drift mit kleinerer Schnittstelle. **Falls freie Konfiguration eine verbindliche Anforderung bleibt, Empfehlung B.** A/B/C entscheidet der Auftraggeber vor der Implementierung; diese Spec erklaert A nicht stillschweigend zum genehmigten Ersatz fuer B.

Bei B/C reicht die vorhandene Textspalte nicht als Identitaet: zwei gleichnamige Einheiten oder spaeter geaenderte Zuordnungen duerfen alte Belege nicht umdeuten. Noetig waeren ein Einheitenstamm mit stabiler ID, eindeutigen Bezeichnungen und versionierter Codeherkunft sowie Positions-Snapshots von Text und Code. Verwendete Zuordnungen werden nicht umgeschrieben; eine neue Zuordnung ist eine neue Einheit. Deaktivierte Einheiten bleiben fuer Bestandsbelege lesbar, sind fuer neue Eingaben gesperrt. Der Konfigurationsvertrag braucht dazu `anlegen`, `deaktivieren` und `auswaehlbare_einheiten` getrennt vom Bestands-Resolver. Das ist ein groesserer Zuschnitt innerhalb dieses Auftrags und muss vor dessen test-first Start konkretisiert werden, falls B/C gewaehlt wird.

Auch dort besteht der Loeschtest: nimmt man die Verwaltung weg, bleiben Pflege, Snapshot und Referenzintegritaet bei jedem Verbraucher liegen. Eine beliebige Freitextliste ohne verpflichtenden Code haette dagegen keine tragfaehige Fachgrenze.

## Fehler, Bestand und Reihenfolge

1. Formularwerte und alle Positionen serverseitig vor Nummernvergabe beziehungsweise vor Aenderung eines Entwurfs pruefen. Unbekannt: HTTP 400 mit Position und eingegebenem Wert, keine Teilpersistenz. Bei anderen Eingangswegen gilt dieselbe Aufloesung vor dem Speichern.
2. Bereits vorhandene unbekannte Werte werden beim Oeffnen sichtbar als ungueltiger Bestandswert angezeigt. Nicht als `Stück` anzeigen, nicht automatisch reparieren. Der Entwurf kann durch explizite Wahl korrigiert werden.
3. `validate_invoice` meldet `UNIT_UNKNOWN` als harten Fehler pro betroffener Position. Finalisierung bleibt gesperrt. Dadurch faellt ein Altbestand auch ohne erneutes Speichern auf.
4. Der direkte XML-Generator wirft `UnknownUnitError`, falls jemand den Validator umgeht. Keine XML mit erfundenem C62; Vorschau und Finalisierung uebersetzen den Fehler in eine verstaendliche Meldung und hinterlassen kein fertiges Artefakt.
5. Bereits finalisierte PDF/XML bleiben unveraendert abrufbar. Keine historische Neuvalidierung oder Neugenerierung beim Lesen. Ein unbekannter Altwert in einem neuen Kopierentwurf bleibt sichtbar und blockiert dessen Finalisierung.

Mustang kann den bisherigen Fehler nicht verlaesslich erkennen: C62 ist ein gueltiger Code, auch wenn er sachlich die falsche Einheit beschreibt. Deshalb prueft die Anwendung die Aufloesung selbst.

## Abnahmekriterien fuer Option A

Alle Kriterien sind Vorgaben fuer spaetere Tests. Datenbankwirkung wird mit `pg_session` geprueft. Die Mutationen sind erst im spaeteren Auftrag einzubauen und zurueckzunehmen.

| ID | Ausfuehrbare Abnahme | Roter Fall: Mutation im Produktivcode |
|---|---|---|
| E1 | Neu- und Bearbeitungsformular rendern; Optionswerte sind exakt die 16 katalogisierten Bezeichnungen in Katalogreihenfolge. Alle sind aufloesbar. Ein zusaetzlicher gueltiger Eintrag im Katalog erscheint ohne Templateaenderung. | Template wieder auf sieben feste Optionen begrenzen oder eine unabhaengige JS-Liste verwenden. |
| E2 | Jede der 13 Altbezeichnungen durch Resolver und XML schicken; Codes entsprechen obiger Tabelle. Person, Personen und Persons ergeben jeweils IE. | Gesamte Aufloesung durch C62 ersetzen oder IE auf C62 setzen. |
| E3 | Zwei Positionen mit 3 und 5 Persons speichern, XML parsen und PDF-Text lesen: Mengen 3 und 5, Code IE an beiden Positionen, sichtbarer Text Persons. Kein Stück fuer diese Positionen. | PDF setzt Einheit pauschal auf Stück oder XML schreibt LS fuer Personen. |
| E4 | POST mit unbekanntem, leerem und nur aus Leerzeichen bestehendem Einheitenwert jeweils anlegen und bearbeiten versuchen: 400, Position benannt, keine Aenderung an Rechnung, Positionen oder Zaehler. | Fehler schlucken oder Nummernvergabe separat committen, bevor Einheiten validiert sind. |
| E5 | Altentwurf mit unbekanntem Wert laden: ungueltiger Wert sichtbar; Pruefen meldet UNIT_UNKNOWN; Finalisieren bleibt draft und erzeugt keine fertigen Dateien. Direkter Generatoraufruf wirft UnknownUnitError. | Validatorpruefung entfernen; separat den Generator-Fallback `.get(wert, 'C62')` wieder einsetzen. Beide Teilpruefungen muessen jeweils rot werden. |
| E6 | Entwurf mit Pauschal speichern und erneut oeffnen: Wert bleibt Pauschal, Code LS. Mit expliziter Wahl Personen korrigierten Altentwurf erneut pruefen: UNIT_UNKNOWN verschwunden. | Beim Lesen jeden Wert auf erste Option setzen oder bei Korrektur den alten Wert beibehalten. |
| E7 | Committierte issued-Rechnung ueber ORM an der Einheit aendern: Guardfehler; gespeicherte XML/PDF nach Katalogerweiterung unveraendert lesen. | Item-Guard umgehen oder Archivabruf neu generieren lassen. |

Bei Wahl B/C sind zusaetzlich rote Kriterien fuer fehlenden/fremden Code, Kollisionen, Deaktivierung und Snapshotstabilitaet zu spezifizieren; diese Verwaltungsoptionen sind mit E1 bis E7 allein ausdruecklich nicht abgenommen.

## Migration, Unveraenderbarkeit und Nachweisgrenzen

Option A braucht **keine Alembic-Migration**, kein Backfill, keine Aenderung an Kopf 014. B/C braucht Migrationen fuer Stamm und Positions-Snapshots samt belegschonendem Bestandskonzept; keine Nummer vorab reservieren, sondern vom dann geltenden Head ableiten.

Inhaltliche Unveraenderbarkeit wird beruehrt, weil Einheit Rechnungsinhalt ist; `MUTABLE_AFTER_FINALIZE` und Statusuebergaenge bleiben unveraendert. **Abweichung zum Brief, Quelltextbefund:** `immutability_triggers.py` schuetzt DELETE/TRUNCATE, nicht UPDATE. `docs/ARCHITEKTUR.md` dokumentiert die UPDATE-Statusmaschine als ORM-only. Es wird hier keine gleichwertige DB-UPDATE-Sicherung behauptet und keine neue eingefuehrt. Beide vorhandenen Schichten sind im Umsetzungsreview zu beachten.

Nicht ausgefuehrt: Suite, einzelne Tests, Mustang, Datenbankabfragen, Migrationen, PDF-Erzeugung und Mutationsproben. Nicht geprueft: reale Altwerte der Installation, Annahme durch den finnischen Empfaenger, aktuelle Excel-Fassung Revision 17. Ein spaeterer Containerlauf muss IE in einer echten EN16931-CII samt eingebettetem PDF validieren; dessen Erfolg ist hier **nicht belegt**.
