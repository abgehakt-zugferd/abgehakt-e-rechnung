# Anwendung

Dieses Dokument beschreibt, wie mit Abgehakt gearbeitet wird. Es beantwortet keine
steuerlichen Fragen und ersetzt keine Beratung; es beschreibt nur, was das Programm tut und
warum es sich an manchen Stellen weigert.

Die Installation und die Ersteinrichtung stehen in [README.md](../README.md). Der innere
Aufbau steht in [ARCHITEKTUR.md](ARCHITEKTUR.md).

## Der Lebenslauf eines Belegs

| Zustand | Bedeutung |
|---|---|
| **Entwurf** | Frei änderbar. Die Rechnungsnummer ist bereits vergeben, der Beleg selbst existiert noch nicht. |
| **Verworfen** | Ein Entwurf, den Sie nicht mehr wollten. Er bleibt als Datensatz erhalten und erklärt später die Lücke im Nummernkreis. Zurückholen ist möglich. |
| **Gestellt** | Das ZUGFeRD-PDF ist erzeugt und liegt im Archiv. Ab hier ist nichts mehr änderbar. |
| **Bezahlt** | Das Geld ist eingegangen. Endzustand. |
| **Storniert** | Der Beleg wurde durch eine Gutschrift aufgehoben. Endzustand. |

Der Übergang vom Entwurf zum gestellten Beleg heißt **Finalisieren** und ist der einzige
Schritt, der sich nicht zurücknehmen lässt. Alles davor ist Arbeitsstand, alles danach ist
aufbewahrungspflichtig.

Finalisieren gelingt entweder ganz oder gar nicht. Lässt sich die E-Rechnungs-XML nicht
prüffähig ins PDF einbetten, bleibt die Rechnung Entwurf, und es entsteht keine Datei. Ein
PDF ohne eingebettete XML ist seit 2025 keine gültige Rechnung, und das Programm legt
lieber nichts ab als etwas Unbrauchbares.

Bei einem manuell angelegten Entwurf können Sie unter **Belegart** zwischen
**Standardrechnung** und **Anzahlungsrechnung** wählen. Gutschriften, Korrekturen und
Abrechnungsgutschriften entstehen auf ihren eigenen Wegen; bei ihnen zeigt das Formular
dieses Feld nicht, und ein mitgeschickter Wert wird abgelehnt. Die **Belegsprache**, Deutsch
oder Englisch, wählen Sie bei jedem Entwurf. Beides wird mit dem Entwurf gespeichert. Nach
dem Finalisieren sind Art und Sprache wie der übrige Beleginhalt nicht mehr änderbar.

---

## Stammdaten: Kunden und Firma

### Kunden

Jeder Kunde hat eine **Kundennummer** (bei leerer Eingabe automatisch vergeben), einen Namen
und eine Pflichtanschrift; optional sind E-Mail,
Telefon und USt-IdNr. Zusätzlich können Sie pro Kunde **CC-Adressen** hinterlegen: diese
erhalten jede Rechnung an diesen Kunden in Kopie und überlagern die Voreinstellung aus den
Einstellungen.

Unter **Bankverbindung (Auszahlung)** können IBAN, BIC und Bankname des Beteiligten stehen.
Diese Felder sind für **Gutschriften** und **Abrechnungsgutschriften** (Typ 389) gedacht, nicht
für normale Rechnungen: dort zahlt der Kunde an Ihre Firmen-IBAN in den Einstellungen.

Kunden werden nicht gelöscht, nur **inaktiv** gesetzt. Inaktive Kunden erscheinen nicht mehr in
der Auswahl beim Anlegen einer Rechnung.

### Firma

Die Firmendaten (Name, Anschrift, Steuernummer oder USt-IdNr., Bankverbindung für
**Eingänge**) stehen unter **Einstellungen**. Ohne vollständige Firmendaten bleibt die
Rechnungserstellung gesperrt.

Unter **Steuer-Rücklage (Übersicht)** legen Sie die pauschale GmbH-Schätzung für die Kennzahl
**Gesch. Steuerabgaben** fest: Körperschaftsteuer, Solidaritätszuschlag auf die KSt und
Gewerbehebesatz. Die Übersicht addiert daraus einen Anteil auf den Nettoumsatz (ohne
Betriebsausgaben im System = Gewinn-Schätzung). Das ist Planungshilfe, keine Steuerberatung.

---

<a id="uebersicht-kennzahlen"></a>

## Übersicht und Kennzahlen

Die Startseite **Übersicht** fasst den Stand zusammen:

| Kennzahl | Bedeutung |
|---|---|
| Rechnungen gesamt | Alle Belege in der Datenbank (jeden Status) |
| Offene Rechnungen | Finalisierte (`gestellt`), noch nicht bezahlte Rechnungen; Gutschriften zählen nicht mit |
| Bezahlt diesen Monat | Brutto-Summe bezahlter Standardrechnungen mit `updated_at` ab Monatsanfang (letzte Änderung, kein eigener Zahlungszeitpunkt; ohne obere Datumsgrenze) |
| Umsatz lfd. Jahr | Brutto-Umsatz gestellter und bezahlter Standardrechnungen seit Jahresanfang (ohne obere Datumsgrenze) |
| Schuldige Umsatzsteuer | Summe der **ausgewiesenen USt** gestellter und bezahlter Standardrechnungen seit Jahresanfang, abzüglich gestellter und bezahlter Gutschriften (`credit_note`), **ohne Vorsteuerabzug** und ohne obere Datumsgrenze (das Programm kennt keine fremden Eingangsrechnungen; die Vorsteuer aus selbst ausgestellten Honorargutschriften mindert erst die geschätzten Steuerabgaben) |
| Gesch. Steuerabgaben | Schuldige USt abzüglich der **Vorsteuer aus Honorargutschriften** (389, gestellt oder bezahlt, seit Jahresanfang) plus pauschale **KSt/GewSt-Rücklage** auf den positiven Nettosaldo aus Standardrechnungen und Gutschriften (Anteil in den Einstellungen) |
| Offene Forderungen | Anzahl und Bruttosumme der gestellten Standardrechnungen. Gutschriften zählen nicht mit. |
| Überfällige Forderungen | Davon jene, deren Fälligkeitsdatum vor heute liegt, mit Anzahl, Bruttosumme und dem Alter der ältesten in Tagen. |
| Nicht versendete Belege | Anzahl der gestellten Standardrechnungen ohne Erstversand. Diese Zahl wird in der Datenbank gezählt, nicht im Speicher. |
| Umsatzvergleich | Dem Umsatz des laufenden Jahres stellt die Übersicht den Umsatz zum selben Kalendertag des Vorjahres gegenüber und nennt die Abweichung in Prozent. Fehlt ein Vergleichswert, weil der Vorjahreswert null ist, entfällt die Prozentangabe. |

Die Belegzahlen je Status und die Forderungen sind Verweise; die Gesamtzahl ist kein Verweis.
Ein Klick öffnet die Rechnungsliste mit
genau der Auswahl, die die Zahl gezählt hat. Kennzahl und Liste zeigen deshalb dieselbe Menge.
Für die Umsatz- und Steuerkennzahlen gilt das nicht, sie summieren und verlinken nichts.

In der Rechnungsliste und auf der Detailseite unterscheidet der Status **Versendet** und
**Nicht versendet** bei gestellten Belegen. **Bezahlt** bleibt der Endzustand nach Zahlungseingang.

---

## Die Rechnungsliste filtern

Über der Rechnungsliste stehen fünf Filter, die sich kombinieren lassen:

| Filter | Auswahl |
|---|---|
| Suche | Rechnungsnummer oder Kundenname, als Teiltreffer |
| Status | Entwurf, Gestellt, Bezahlt, Storniert, Verworfen |
| Art | Rechnung oder Gutschrift |
| Frist | **Überfällig**: Fälligkeitsdatum liegt vor heute |
| Versand | **Ohne Versand**: ohne Erstversand, unabhängig vom Status |

**Ohne Versand** prüft nur den fehlenden Erstversand. Das Etikett **Nicht versendet** verlangt
zusätzlich den Status **Gestellt**, die Kennzahl auf der Übersicht außerdem die Art **Rechnung**.

Solange Sie keinen Status wählen, blendet die Liste verworfene Entwürfe aus; sie erscheinen nur
über **Verworfen**. Die gesetzten Filter stehen in der Adresse der Seite, eine gefilterte Liste
lässt sich also als Lesezeichen ablegen. Unbekannte Werte für Art, Frist oder Versand werden
ignoriert; andere Filter bleiben wirksam. Ein unbekannter Status liefert eine leere Liste.

---

<a id="migration-aus-altem-abgehakt"></a>

## Migration aus altem Abgehakt

Wer von einer früheren Abgehakt-Installation umzieht, braucht pro finalisiertem Beleg die
**XML** und das **ZUGFeRD-PDF** im Archiv (`storage/xml/` und `storage/pdfs/`). Die
Datenbank allein reicht nicht: die Dateien sind der GoBD-Beleg.

### Einspielen neuer Belege

Im Container (Entwicklungsstack mit gemountetem `backend/scripts/`):

```bash
docker exec abgehakt_app python scripts/beleg_aus_xml_einspielen.py Z-2026-002 Z-2026-004
```

Mit `--alt-system` werden nach dem Einspielen automatisch **Versand** und **Bezahlt** aus dem
alten System nachgezogen (siehe unten). Der Kunde muss bereits im Stamm stehen (Abgleich über
die USt-IdNr. aus der XML).

### Nachziehen bei bereits importierten Belegen

Der XML-Import legt Belege nur als **gestellt** an. Wer im alten Tool schon versendet und
bezahlt hat, nutzt:

```bash
docker exec abgehakt_app python scripts/beleg_migration_nachziehen.py Z-2026-002 Z-2026-004
```

Das Skript setzt:

- `datev_sent_at`, sofern noch leer, auf das **Rechnungsdatum** (Erstversand),
- den Status **bezahlt** (bei jedem anderen Status),
- einen Eintrag im **Versandprotokoll**, sofern noch keiner existiert (Hinweis: historischer
  Versand, kein erneuter Mailversand),
- bei jedem Aufruf den Bezahlt-Zeitpunkt (`updated_at`) auf das **Fälligkeitsdatum**, damit
  „Bezahlt diesen Monat“
  nicht fälschlich den Umzugmonat zeigt.

Exakte Versand- oder Zahlungsdaten aus dem alten System können über die Funktionsparameter
`versendet_am` und `bezahlt_am` von `nachziehen` gesetzt werden; die Standard-Schätzung ist
bewusst aus
Rechnungs- und Fälligkeitsdatum.

---

<a id="ust-idnr-bei-vies-prufen"></a>

## USt-IdNr. bei VIES prüfen

VIES (VAT Information Exchange System) ist die offizielle EU-Schnittstelle, mit der Sie
prüfen können, ob eine USt-IdNr. im jeweiligen Mitgliedstaat registriert und gültig ist. Das
Programm nutzt sie **nur auf Ihren Wunsch**, nicht beim Speichern, nicht im Hintergrund und
nicht automatisch vor jeder Rechnung.

### Wo und wann

- **Kunde bearbeiten:** unter der USt-IdNr. erscheint der VIES-Status und der Button **Jetzt
  bei VIES prüfen**. Beim **Anlegen** eines neuen Kunden gibt es den Button noch nicht; zuerst
  speichern, dann bearbeiten.
- **Einstellungen:** dieselbe Prüfung für die **eigene** Firmen-USt-IdNr.

### Ablauf

1. USt-IdNr. und Name im Formular eintragen oder prüfen (der Name dient dem Abgleich).
2. **Jetzt bei VIES prüfen** klicken. Es öffnet sich ein **Dialog auf derselben Seite** (kein
   Sprung zu einer anderen Seite).
3. Der Dialog zeigt die **Ziel-URL** der EU-Schnittstelle und genau, was übertragen wird:
   Ländercode und Nummer der zu prüfenden USt-IdNr., der Name für den Abgleich und optional
   Ihre eigene USt-IdNr. als Anfragender.
4. Mit **Einverstanden, jetzt prüfen** starten Sie die Abfrage. **Abbrechen** baut keine
   Verbindung auf.
5. Nach der Antwort bleiben Sie auf der Bearbeiten-Seite. Der Status unter der USt-IdNr. wird
   aktualisiert (gültig, ungültig, nicht erreichbar, Name stimmt / weicht ab / unbekannt).

**Speichern** des Kunden- oder Firmenformulars ruft VIES **nicht** auf. Wer nur die Nummer
ändern und speichern will, ohne zu prüfen, kann das tun; beim Finalisieren kann eine Warnung
erscheinen, dass noch nicht geprüft wurde.

### Was VIES liefert und was nicht

| Ergebnis im Programm | Bedeutung |
|---|---|
| Gültig | VIES meldet die Nummer als registriert und gültig. |
| Ungültig | VIES meldet die Nummer als ungültig oder nicht registriert. Beim Finalisieren ist das ein **Fehler**. |
| Nicht erreichbar | Netz- oder Serverproblem; Gültigkeit bleibt unbekannt. Warnung beim Finalisieren. |
| Noch nicht geprüft | Warnung beim Finalisieren, kein automatischer Abruf. |
| Name stimmt / weicht ab | Abgleich zwischen hinterlegtem Namen und VIES-Antwort. |
| Name unbekannt | VIES lieferte keinen Namen, bei **deutschen** Nummern häufig. Kein Fehler. |

VIES prüft **Existenz und Gültigkeit** der Nummer zum Zeitpunkt der Abfrage, keine
Steuerberatung und keinen vollständigen Identitätsnachweis des Geschäftspartners.

### Datenschutz und Zweck

Die Abfrage ist der **vorgesehene Zweck** von VIES: Geschäftspartner-USt-IdNr. verifizieren.
Übertragen werden nur die genannten Felder, keine Rechnungen und keine weiteren Stammdaten.
Die EU-Kommission und das zuständige nationale Register verarbeiten die Anfrage; für die
Gegenseite ist der Abruf sichtbar, inklusive der **IP-Adresse** des Anschlusses, von dem Ihr
Server die Anfrage stellt.

Wenn Sie die USt-IdNr. im Formular ändern und speichern, wird der alte Prüfstand verworfen.
Dann ist eine neue Prüfung nötig.

---

<a id="gutschriften-auszahlung"></a>

## Gutschriften und Auszahlung an Beteiligte

Bei einer **normalen Rechnung** zahlt der Empfänger an **Ihre Firma**. Der EPC-QR-Code auf dem
PDF verweist auf die Firmen-IBAN aus den Einstellungen.

Bei einer **Gutschrift** oder **Abrechnungsgutschrift** (389) zahlt **Sie** an den
**Beteiligten** (den Kunden). Dafür trägt der Kundenstamm optional IBAN, BIC und Bank unter
**Bankverbindung (Auszahlung)**.

| Beleg | Zahlungsempfänger im PDF | EPC-QR |
|---|---|---|
| Rechnung (380) | Firma | Firmen-IBAN, Rechnungsbetrag |
| Gutschrift / 389 | Kunde | Kunden-IBAN, Gutschriftbetrag |

Ohne Kunden-IBAN entsteht die Gutschrift ohne QR-Code; beim Finalisieren erscheint eine
**Warnung**, dass keine Bankverbindung des Kunden hinterlegt ist. Die Gutschrift ist dennoch
möglich, wenn alle Pflichtangaben stimmen.

---

## Einheiten in Positionen

Wenn Sie eine Position anlegen oder einen Entwurf ändern, wählen Sie unter **Einheit** die
Mengenbezeichnung. Der Katalog enthält Stück, Person, Personen, Persons, Stunde, Stunden,
Tag, Tage, Monat, Monate, Kilometer, Meter, kg, Liter, Pauschal und Pauschale. Singular,
Plural und die englische Schreibweise können dieselbe fachliche Einheit meinen. Die Auswahl
bestimmt den sichtbaren Text der Position, der technische Einheitencode der E-Rechnung wird
aus dem Katalog bestimmt.

Für eine neue Position ist **Stück** vorausgewählt. Eigene Bezeichnungen oder frei
eingegebene Codes bietet das Programm nicht an. Einen leeren oder unbekannten Einheitenwert
weist es beim Speichern zurück, bevor eine Rechnungsnummer vergeben oder eine Position
geändert wird. Beim Prüfen ist eine unbekannte Einheit ebenfalls ein Fehler und sperrt das
Finalisieren; die XML-Erzeugung deutet sie nicht als Stück um.

Ein älterer Entwurf mit einer nicht mehr bekannten Einheit zeigt diesen Wert im Auswahlfeld
als ungültig. Wählen Sie ausdrücklich eine Katalogeinheit, wenn Sie ihn korrigieren wollen.
Ein bereits gestellter Beleg bleibt unverändert mit seiner bisherigen Einheit erhalten; das
Programm schreibt seine PDF oder XML nicht wegen eines späteren Katalogstands um.

---

## Bestehende Rechnung als Vorlage verwenden

Wenn eine weitere Rechnung weitgehend dieselben Angaben braucht, öffnen Sie die vorhandene
Rechnung und wählen **ALS VORLAGE**. Das Programm öffnet das Formular **Neue Rechnung** mit
vorbelegtem Kunden, Positionen, Steuerkategorie, Kundenreferenz, Bestellnummer,
Leistungsangaben, Zahlungsbedingungen, Bemerkungen und Belegsprache. Beschreibung, Menge,
Einheit, Preis und Steuersatz der Positionen sind dabei nur Vorschläge und können geändert
werden.

Rechnungsdatum und Fälligkeitsdatum beginnen wie bei einer neuen Rechnung. Die Belegart wird
nicht übernommen und steht zunächst auf **Standardrechnung**. Prüfen Sie deshalb besonders
bei einer Vorlage für eine Anzahlung alle Belegdaten, bevor Sie speichern. Erst **ALS ENTWURF
SPEICHERN** legt eine neue Rechnung mit neuer Nummer an. Das bloße Öffnen der Vorlage legt
keinen Datensatz an, vergibt keine Nummer und ändert die Vorlage nicht.

Ist der Kunde der Vorlage inaktiv oder nicht mehr auswählbar, bleiben die übrigen Angaben
vorbelegt, der Kunde bleibt aber leer und das Formular weist darauf hin. Für eine ungültige
oder nicht vorhandene Vorlage zeigt das Programm einen Fehler statt eines still leeren
Neuanlageformulars.

---

## Anzahlungsrechnung

Wählen Sie beim Entwurf unter **Belegart** die **Anzahlungsrechnung**, wenn Sie eine Zahlung
vor der Leistung anfordern. Der Beleg erhält beim Finalisieren TypeCode 386 und im PDF den
Titel **ANZAHLUNGSRECHNUNG**, bei englischer Belegsprache **PREPAYMENT INVOICE**. Eine
Standardrechnung erhält weiterhin TypeCode 380.

Für eine Anzahlungsrechnung müssen Sie den geplanten Leistungszeitraum mit Beginn und Ende
angeben. Einen einzelnen geplanten Tag tragen Sie in beide Felder ein; das Programm füllt
das zweite nicht von selbst. Ein tatsächliches Leistungsdatum darf nicht zugleich gesetzt
sein. Fehlende, nur halb ausgefüllte oder zeitlich verkehrte Zeiträume sperren das
Finalisieren. Im PDF heißt der Zeitraum bei einer Anzahlungsrechnung **Voraussichtlicher
Leistungszeitraum**, auf Englisch **Expected period of supply**; er behauptet damit keine
bereits erbrachte Leistung. Die Detailseite im Programm schreibt unabhängig von der Belegart
**Leistungszeitraum**.

Die Belegart ist eine Kennzeichnung, keine Rechenhilfe. Das Programm halbiert keine Preise,
berechnet keine Raten und zieht eine Anzahlung nicht von einer späteren Schlussrechnung ab.
Es führt dafür auch keinen Zahlungsabzug in der E-Rechnung. Gutschriften, Korrekturen und
Abrechnungsgutschriften entstehen auf ihren jeweiligen eigenen Wegen und lassen sich nicht
über diese Auswahl erzeugen.

---

## Bestellnummer des Kunden

Tragen Sie im Rechnungsformular unter **Bestellnummer** die Nummer der Bestellung oder
Purchase Order Ihres Kunden ein, wenn der Auftrag eine solche Referenz verlangt. Das Feld
ist die Bestellnummer des Kunden, nicht Ihre Rechnungsnummer und nicht die
**Referenz des Kunden** für eine Leitweg-ID oder andere Käuferreferenz.

Die Bestellnummer wird mit dem Entwurf gespeichert, auf dem PDF unter **Bestellnummer**
beziehungsweise **Purchase order number** angezeigt und als BT-13 in die E-Rechnungs-XML
geschrieben. Bleibt das Feld leer, fügt das Programm diese Referenz nicht in PDF oder XML
ein. Beim Arbeiten mit einer Vorlage wird die Bestellnummer mit vorbelegt; Sie können sie
vor dem Speichern der neuen Rechnung ändern oder löschen.

---

## Belegsprache

Wählen Sie im Rechnungsformular unter **Belegsprache** für jede einzelne Rechnung
**Deutsch** oder **Englisch**. Neue Rechnungen beginnen auf Deutsch. Die Wahl gehört zum
Beleg, nicht zum Kundenland, zur Adresse oder zur USt-IdNr.; es gibt dafür keine globale
Einstellung. Eine Vorlage und eine Stornorechnung übernehmen die Sprache ihres Ausgangsbelegs,
eine aus Vorlage angelegte Rechnung kann sie vor dem Speichern noch ändern.

Die Belegsprache steuert den Mailtext und die menschenlesbare Darstellung im PDF: Belegtitel,
Beschriftungen, Zahlen und Datumsformate sowie die vom Programm erzeugten Hinweise. Sie
übersetzt weder Positionsbeschreibungen noch selbst eingegebene Zahlungsbedingungen. Die
Sprachkennzeichnung selbst wird nicht in die E-Rechnungs-XML geschrieben. Bleiben die
Zahlungsbedingungen leer, übernimmt das Programm jedoch die Standard-Zahlungsbedingungen
der gewählten Sprache und schreibt diesen Text auch in die XML. Wählen Sie eine englische
Rechnung ohne eigene Zahlungsbedingungen, braucht die Firma in den Einstellungen englische
Standard-Zahlungsbedingungen; fehlen sie, weist das Programm das Speichern zurück.

Nach dem Finalisieren ist die Sprache unveränderlich. Ein fremder oder manipulierter
Sprachwert wird ebenfalls vor der Nummernvergabe zurückgewiesen, statt still auf Deutsch
zurückzufallen.

---

## Mailtext der Rechnungsmail

Betreff und Rumpf der Mail, mit der eine Rechnung herausgeht, richten sich nach der
**Belegsprache dieser einen Rechnung**, nicht nach einer globalen Einstellung. Eine englische
Rechnung wird also mit einer englischen Mail versendet, auch wenn alle anderen deutsch sind.

Beide Texte sind unter Einstellungen hinterlegbar, getrennt für Deutsch und Englisch, also vier
Felder. Bleibt ein Feld leer, gilt die eingebaute Schablone der jeweiligen Sprache; Sie müssen
nichts eintragen, damit der Versand funktioniert.

Erlaubt sind genau fünf Platzhalter:

| Platzhalter | Bedeutung |
|---|---|
| {rechnungsnummer} | Die Rechnungsnummer |
| {kunde} | Der Kundenname |
| {betrag} | Der Rechnungsbetrag, in der Darstellung der Belegsprache |
| {faellig_am} | Das Fälligkeitsdatum, in der Darstellung der Belegsprache |
| {firma} | Der eigene Firmenname |

Betrag und Fälligkeitsdatum erscheinen in der Schreibweise der Belegsprache, ein deutscher Beleg
also mit Komma als Dezimaltrennung. Unbekannte Platzhalter aus kleinen ASCII-Buchstaben und
Unterstrichen in geschweiften Klammern werden beim Speichern abgelehnt; andere Schreibweisen
bleiben wörtlich stehen. Ein Betreff mit Zeilenumbruch wird ebenfalls abgelehnt: ein
Mail-Header kann keinen tragen. Im
Rumpf sind Umbrüche erlaubt.

Unter den Rumpf setzt das Programm eine Fußzeile mit der Anschrift Ihrer Firma, eingeleitet mit
„Verantwortlich:" auf Deutsch und „Responsible:" auf Englisch. Sind Firmenname, Straße, Postleitzahl
und Ort sämtlich leer oder fehlt die Firma, entfällt die Fußzeile; sonst erscheinen die
vorhandenen Teile.

---

## Anwendungsfall: eine gestellte Rechnung korrigieren

### Warum es keinen Knopf zum Ändern gibt

Ein gestellter Beleg ist unveränderlich. Das ist keine Bequemlichkeitsentscheidung des
Programms, sondern die Grundlage dafür, dass die Buchführung nachvollziehbar bleibt: eine
Rechnung, die sich nachträglich ändern lässt, beweist nichts. Wer den Empfänger, den Betrag
oder die Leistung korrigieren muss, hebt den alten Beleg auf und schreibt einen neuen.

Das Aufheben heißt hier **Stornierung** und erzeugt eine **Gutschrift**: einen eigenen
Beleg mit eigener Rechnungsnummer, der auf das Original verweist und es betragsgleich
neutralisiert. Beide Belege bleiben erhalten, und beide gehen an die Buchhaltung.

### Schritt für Schritt

1. Öffnen Sie die gestellte Rechnung.
2. **Stornorechnung erzeugen.** Es entsteht ein Entwurf einer Gutschrift, der die Beträge
   und Positionen des Originals unverändert übernimmt.
3. Prüfen Sie den Entwurf und **finalisieren** Sie ihn. Jetzt entsteht das ZUGFeRD-PDF der
   Gutschrift.
4. Senden Sie die Gutschrift an Ihre Kundin oder Ihren Kunden und an die Buchhaltung, so wie
   Sie es mit der Originalrechnung getan haben.
5. Setzen Sie das **Original** auf **storniert**. Dieser Schritt bleibt Ihnen überlassen,
   siehe unten.
6. Schreiben Sie, falls nötig, eine neue, korrekte Rechnung. Sie ist ein eigenständiger
   Beleg und bezieht sich nicht auf die Gutschrift.

### Was das Programm dabei verweigert, und warum

**Sie können eine Gutschrift nicht bearbeiten.**
Eine Gutschrift spiegelt ihr Original. Ließe sie sich ändern, entstünde eine „Gutschrift zu
RE-001" mit anderen Zahlen, und das ist keine Stornierung mehr, sondern eine Teilkorrektur.
Stimmt am Entwurf etwas nicht, verwerfen Sie ihn und beginnen neu.

**Sie können denselben Beleg nicht zweimal stornieren.**
Zwei Gutschriften zum selben Beleg würden die Forderung doppelt mindern, in der Offene-Posten-Liste
wie in der Buchhaltung. Auch ein noch offener Gutschrifts-Entwurf sperrt den zweiten
Versuch: sonst gäbe es zwei Entwürfe, die beide finalisierbar wären, und der Fehler fiele
erst auf, wenn schon ein Beleg im Archiv liegt.

Ein **verworfener** Gutschrifts-Entwurf sperrt dagegen nicht. Wer versehentlich storniert
und den Entwurf verwirft, kann den Beleg erneut stornieren; ein Fehlgriff ist nicht
endgültig.

**Sie können ein storniertes Original nicht als bezahlt markieren.**
Ein Beleg, der aufgehoben wurde, kann nicht gleichzeitig beglichen sein. Ist das Geld
tatsächlich geflossen und Sie erstatten es, gehört das an die Gutschrift: die dürfen Sie als
bezahlt markieren, und dort heißt bezahlt schlicht erstattet.

### Warum das Original nicht von selbst auf „storniert" springt

Das Programm setzt den Status des Originals nicht automatisch. Der Grund ist unangenehm
konkret: **bezahlt** ist ein Endzustand, aus dem kein Weg mehr herausführt, und eine bereits
bezahlte Rechnung darf storniert werden. Eine Automatik würde also für gestellte Rechnungen
greifen und für bezahlte stillschweigend nicht, also in genau der Hälfte der Fälle. Eine
Regel, die manchmal wirkt, ist schlimmer als keine, weil niemand ihr ansieht, wann sie
gewirkt hat.

Statt die Zustandsregeln aufzuweichen, bleibt der Schritt bei Ihnen. Solange Sie ihn nicht
tun, steht die stornierte Rechnung weiterhin als **gestellt** in der Liste und zählt auf dem
Dashboard mit.

### Der Sonderfall: die Rechnung war schon bezahlt

Eine bezahlte Rechnung lässt sich stornieren, ihr Status bleibt danach aber auf **bezahlt**
stehen. Aus dem Endzustand bezahlt führt kein Übergang mehr heraus. Die Gutschrift ist der
Beleg für die Aufhebung, und die Buchhaltung liest die Kombination aus beiden Belegen
richtig. Wenn Sie in der Liste dennoch sehen wollen, dass hier etwas rückgängig gemacht
wurde: die Gutschrift steht direkt darunter und verweist auf die Nummer des Originals.

### Was das Programm nicht kann

**Teilkorrekturen.** Eine Rechnung, von der nur eine Position falsch ist, wird hier
vollständig storniert und neu geschrieben. Der Belegtyp für eine echte Teilkorrektur
(Rechnungskorrektur, TypeCode 384) ist im Format vorgesehen, hat aber keinen Weg über die
Oberfläche. Eine Gutschrift mit abweichenden Beträgen wäre eine Teilkorrektur durch die
Hintertür, und genau deshalb wird sie abgewiesen.

**Löschen.** Weder Rechnungen noch Kunden werden je gelöscht. Ein Entwurf lässt sich
verwerfen, ein Kunde inaktiv setzen; die Datensätze bleiben, weil sonst Nummern fehlen
würden, die niemand mehr erklären kann.
