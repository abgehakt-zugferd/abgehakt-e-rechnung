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

## Vorschau eines Entwurfs

Solange eine Rechnung Entwurf ist, führt die Detailseite den Knopf **VORSCHAU**. Die
Vorschauseite zeigt das PDF, wie es beim Finalisieren entstünde, im Browser eingebettet,
daneben die berechnete ZUGFeRD-XML. Beides entsteht nur für diesen Blick: es wird nichts
gespeichert, im Archiv liegt keine Datei, und die XML wird nicht am Entwurf hinterlegt.
Der Hinweiskasten der Seite sagt genau das, denn ein Entwurf trägt bereits die endgültige
Nummer und könnte sonst wie eine Rechnung wirken.

Das Vorschau-PDF trägt deshalb diagonal den Stempel **ENTWURF**, bei englischem Beleg
**DRAFT** (services/pdf_generator.py, `_draft_watermark`), und heißt
`<Nummer>_ENTWURF.pdf`. Einem Entwurf ohne Kunde zeigt das Programm keine PDF-Vorschau:
ohne Empfänger gibt es keine Anschrift, und die Meldung sagt, was zu tun ist. Die
XML-Vorschau funktioniert auch ohne Kunden.

Ein finalisierter Beleg hat keine Vorschau mehr. Für ihn bietet die Detailseite
**PDF LADEN**: das ZUGFeRD-PDF aus dem Archiv, wie es auch versendet wird.

---

## Rechnung versenden

Nach dem Finalisieren geht der Beleg per E-Mail raus. Der Knopf dafür steht auf der
Detailseite und erscheint nur, wenn in den Einstellungen ein Postausgangsserver
hinterlegt ist. Er heißt **SENDEN**; ist zusätzlich die Upload-Adresse der Buchhaltung
hinterlegt, kündigt der Knopfname das an. Der aufklappbare Dialog fragt zwei Felder ab:

- **EMPFÄNGER**: vorbelegt mit der E-Mail-Adresse des Kunden, wenn dort eine steht.
  Bleibt das Feld leer und kennt der Kunde keine Adresse, weist das Programm den Versand
  ab („Keine E-Mail-Adresse des Kunden bekannt.").
- **KOPIE AN (CC)**: vorbelegt aus dem Kundenstamm oder, wenn der Kunde keine Adressen
  hinterlegt hat, aus der globalen Voreinstellung in den Einstellungen. Der Dialog nennt
  die Herkunft der Vorbelegung; wer sie ändert, ändert nur diesen einen Versand.

Ist die Upload-Adresse der Buchhaltung hinterlegt, geht jede gesendete Rechnung
zusätzlich als Blindkopie dorthin; der Dialog zeigt das vor dem Absenden an. Der
Posteingang der Buchhaltung verarbeitet nur den PDF-Anhang, nicht den Mailtext, und
nimmt Anhänge bis 20 MB an; größere Dateien versendet das Programm deshalb nicht.

Vor dem Absenden prüft das Programm das PDF selbst, nicht nur seinen Namen: nur ein PDF
mit gültig eingebetteter E-Rechnungs-XML geht raus (Route `POST
/invoices/{id}/datev-senden`). Ein Visual-PDF ohne Einbettung wird abgelehnt, mit der
Aufforderung, die Rechnung erneut zu finalisieren; steht das Prüfwerkzeug nicht bereit,
bricht der Versand ab, statt etwas Ungeprüftes zu schicken.

Erst wenn all das steht, wird gesendet, und ein Eintrag im **Versandprotokoll** auf der
Detailseite wird geschrieben: Datum, Empfänger, Kopien, ob die Buchhaltung Blindkopie
war, und der Ausgang. Schlägt der Versand fehl, steht die Meldung des Servers dort; blieb
der Ausgang offen, heißt es: „AUSGANG UNBEKANNT: der Versand wurde begonnen, das
Ergebnis kam nicht mehr an. Bitte im Postausgang nachsehen, bevor erneut gesendet wird."

Der Zeitpunkt des ersten Versands wird am Beleg festgehalten (Feld `datev_sent_at`): als
**Versendet am** auf der Detailseite, als Datum in der Versandspalte der Liste und als
Marke **Versendet** im Status. Ein weiterer Versand ändert ihn nicht, jede Wiederholung
steht nur im Versandprotokoll. Der Knopf heißt dann **ERNEUT SENDEN** und fragt noch
einmal: „Diese Rechnung wurde am <Datum> bereits versendet. Erneut senden?" Auch ein
bereits bezahlter Beleg lässt sich noch einmal versenden.

---

## Stammdaten: Kunden und Firma

### Kunden

Jeder Kunde hat eine **Kundennummer** (bei leerer Eingabe automatisch vergeben), einen Namen
und eine Pflichtanschrift; optional sind E-Mail,
Telefon, Steuernummer und USt-IdNr. Zusätzlich können Sie pro Kunde **CC-Adressen** hinterlegen: diese
erhalten jede Rechnung an diesen Kunden in Kopie und überlagern die Voreinstellung aus den
Einstellungen.

Unter **Bankverbindung (Auszahlung)** können IBAN, BIC und Bankname des Beteiligten stehen.
Diese Felder sind für **Gutschriften** und **Abrechnungsgutschriften** (Typ 389) gedacht, nicht
für normale Rechnungen: dort zahlt der Kunde an Ihre Firmen-IBAN in den Einstellungen.
Ist der Schalter **Gutschriftempfänger** gesetzt, ist die IBAN als empfohlen markiert: ohne sie
entsteht auf der Honorargutschrift kein EPC-QR-Code zum Überweisen. Speichern und Finalisieren
bleiben möglich; es bleibt bei der Warnung `CUSTOMER_BANK_MISSING`.

Für Honorargutschriften (Typ 389) gibt es am Kunden den Schalter **Gutschriftempfänger** und den
umsatzsteuerlichen Status (`ungeklaert`, `regelbesteuert`, `kleinunternehmer`). Die Voreinstellung
ist bewusst **ungeklärt**, keine ungeprüfte Annahme. Speichern bleibt bei ungeklärtem Status
möglich; blockiert wird erst das Finalisieren einer 389. Ohne Steuernummer und ohne USt-IdNr.
scheitert die Finalisierung ebenfalls (§ 14 Abs. 4 S. 1 Nr. 2 UStG). Die XML-Ausgabe mit
getauschten Rollen gehört nicht zu diesem Stand; das Feld `tax_number` ist gespeichert und
geprüft, noch nicht in die ZUGFeRD-XML geschrieben.

Es gibt zwei getrennte Wege, einen Kunden aus dem Tagesgeschäft zu nehmen, mit
unterschiedlicher Wirkung:

- **Inaktiv setzen.** In der Kundenbearbeitung steht der Status auf **Aktiv (in
  Rechnungsauswahl)** oder **Inaktiv (archiviert)**. Ein inaktiver Kunde bleibt in der
  Kundenliste sichtbar, erscheint aber nicht mehr in der Empfängerauswahl beim Anlegen
  und Bearbeiten von Rechnungen. Zurückschalten ist jederzeit möglich.
- **DEL.** Der Knopf **DEL** in der Spalte AKTIONEN der Kundenliste blendet den Kunden
  überall aus: aus der Kundenliste samt Suche, aus der Empfängerauswahl beim Anlegen und
  Bearbeiten von Rechnungen und aus der Zuordnung ankommender Übergabebelege (Route
  `POST /customers/{id}/loeschen`, Feld `deleted_at`). Der Bestätigungsdialog fragt
  „Kunde <Name> wirklich deaktivieren?"; er beschreibt die Wirkung zu harmlos: nach DEL
  fehlt nicht nur die Auswahl, sondern jeder Weg zurück über die Oberfläche, denn der
  Kunde ist nirgends mehr zu sehen und nicht wieder einzublenden.

Gelöscht wird in keinem der beiden Fälle etwas. Der Datensatz samt Kundennummer bleibt
erhalten, weil Rechnungen auf ihn verweisen; `services/customer_guard.py` erzwingt das
auf Session-Ebene, und im GoBD-Export erscheint der Kunde mit seinem Löschzeitpunkt
(Spalte `geloescht_am`). Rechnungen, die vor dem Ausblenden gestellt wurden, zeigen ihn
unverändert weiter.

### Firma

Die Firmendaten (Name, Anschrift, Steuernummer oder USt-IdNr., Bankverbindung für
**Eingänge**) stehen unter **Einstellungen**. Ohne vollständige Firmendaten bleibt die
Rechnungserstellung gesperrt.

Unter **Rechtsform und Register** stehen die Pflichtangaben für Geschäftsbriefe, die auch auf
jeder Rechnung stehen müssen (§ 35a GmbHG, § 80 AktG, §§ 37a, 125a HGB, § 7 Abs. 5 PartGG).
Die Rechtsform ist eine Pflichtauswahl. Je nach Rechtsform verlangt das Programm dazu:

| Rechtsform | Verlangt |
|---|---|
| Einzelunternehmen, Freiberuf, andere Rechtsform | nichts weiter |
| e.K., OHG, KG, PartG | Registergericht, Registernummer |
| GmbH, UG (haftungsbeschränkt) | dazu die gesamte Geschäftsführung; der Vorsitz eines Aufsichtsrats, falls einer gebildet ist |
| AG | dazu den gesamten Vorstand und den Vorsitz des Aufsichtsrats |

Der Sitz ist der Ort der Anschrift, solange kein abweichender Sitz eingetragen ist. Die Angaben
erscheinen im Fuß des PDFs und in der E-Rechnung (Registernummer als BT-30, alle Zeilen als
BT-33). Fehlt etwas, bleibt das Stellen gesperrt, und die Einstellungen sagen, was fehlt.
Bestehende Installationen haben nach dem Update noch keine Rechtsform; bis sie gewählt ist,
lassen sich Entwürfe anlegen, aber nicht stellen. Bereits gestellte Belege bleiben, wie sie
sind.

Nicht abgedeckt ist die GmbH & Co. KG: Sie muss zusätzlich die Angaben ihrer
Komplementär-GmbH nennen. Bis das eingebaut ist, die Rechtsform **Andere Rechtsform** wählen
und die Angaben selbst prüfen.

Unter **Steuer-Rücklage (Übersicht)** legen Sie die pauschale GmbH-Schätzung für die Kennzahl
**Gesch. Steuerabgaben** fest: Körperschaftsteuer, Solidaritätszuschlag auf die KSt und
Gewerbehebesatz. Die Übersicht addiert daraus einen Anteil auf den Nettoumsatz (ohne
Betriebsausgaben im System = Gewinn-Schätzung). Das ist Planungshilfe, keine Steuerberatung.

### Rechnungsnummern

Jede Rechnungsnummer entsteht beim ersten Speichern eines Entwurfs und bleibt danach
unveränderlich. Sie besteht aus einem Präfix, wahlweise der Jahreszahl und einem laufenden
Zähler, der dreistellig mit führenden Nullen geschrieben wird. Ohne Jahr lautet die
Nummer `RE-001`, mit Jahr `RE-2026-001`.

Beide Einstellungen stehen unter **Einstellungen** im Block **RECHNUNGSNUMMERN** der
Firmendaten: das Feld **Präfix** und der Schalter **Jahr in Nummer (RE-2026-001)**
(services/invoice_number.py, `generate_next_invoice_number`). Das Jahr stammt aus dem
Ausstellungsdatum beim Anlegen; ein später geändertes Datum biegt die Nummer nicht um.
Der Zähler läuft über das Kalenderjahr hinweg einfach weiter, der Jahresschalter ändert
nur die Schreibweise.

Der Präfix wird Teil der Rechnungsnummer und damit Teil des Dateinamens im Archiv. Deshalb
beschränkt ihn das Programm auf Buchstaben, Ziffern, Punkt, Bindestrich und Unterstrich
und auf höchstens 20 Zeichen; jeden anderen Wert lehnt es beim Speichern der Firmendaten
ab und nennt den Grund (`pruefe_praefix` in services/invoice_number.py).

---

<a id="uebersicht-kennzahlen"></a>

## Übersicht und Kennzahlen

Die Startseite **Übersicht** fasst den Stand zusammen. „Heute“ und alle davon
abhängigen Kalendergrenzen (Jahresanfang, Monatsanfang, Vorbelegung von
Beleg- und Zahlungsdatum) gelten fest in Europe/Berlin, unabhängig von der
Zeitzone des Servers.

| Kennzahl | Bedeutung |
|---|---|
| Rechnungen gesamt | Alle Belege in der Datenbank (jeden Status) |
| Offene Forderungen | Anzahl und Bruttosumme der gestellten (`issued`), noch nicht bezahlten Standardrechnungen. Gutschriften zählen nicht mit; Rechnungen, zu denen eine gestellte oder bezahlte Gutschrift existiert, ebensowenig, egal welchen Status das Original trägt (services/storno_wirkung.py, `WIRKSAM_STORNIERT`). |
| Bezahlt diesen Monat | Brutto-Summe bezahlter Standardrechnungen mit `bezahlt_am` ab Monatsanfang (Zahlungsdatum; ohne obere Datumsgrenze). Ausgezahlte Gutschriften mindern diese Zahl nicht. Die Kachel nennt zusätzlich den Wert des Vormonats. |
| Bezahlt Vormonat | Brutto-Summe bezahlter Standardrechnungen des vorherigen Kalendermonats nach `bezahlt_am`; steht als Zusatz unter der Zahl von „Bezahlt diesen Monat“ |
| Umsatz lfd. Jahr | Netto-Summe bezahlter Standardrechnungen mit `bezahlt_am` seit Jahresanfang (ohne obere Datumsgrenze). Gestellte, unbezahlte Rechnungen zählen nicht; sie bleiben offene Forderungen. Ausgezahlte Gutschriften (bezahlt, zu einem bezahlten Original) mindern ihn, gerechnet nach dem Zahlungsdatum der Gutschrift (dashboard_kennzahlen.py, `umsatz_im_zeitraum`). |
| Schuldige Umsatzsteuer | Summe der **ausgewiesenen USt** gestellter und bezahlter Standardrechnungen seit Jahresanfang, abzüglich gestellter und bezahlter Gutschriften (`credit_note`), **ohne Vorsteuerabzug** und ohne obere Datumsgrenze (das Programm kennt keine fremden Eingangsrechnungen; die Vorsteuer aus selbst ausgestellten Honorargutschriften mindert erst die geschätzten Steuerabgaben). Die Kachel zeigt daneben die schuldige USt des laufenden Kalenderquartals als eigene Zeile (`Q1` bis `Q4` mit Jahr). |
| Gesch. Steuerabgaben | Schuldige USt abzüglich der **Vorsteuer aus Honorargutschriften** (389, gestellt oder bezahlt, seit Jahresanfang) plus pauschale **KSt/GewSt-Rücklage** auf den positiven Nettosaldo aus Standardrechnungen und Gutschriften (Anteil in den Einstellungen). Unter der Zahl rechnet die Kachel die Bestandteile vor: USt, abzüglich Vorsteuer aus Honorargutschriften, plus KSt/GewSt-Rücklage mit ihrem Anteil in Prozent auf den Nettoumsatz. |
| Überfällige Forderungen | Davon jene (ohne wirksam stornierte), deren Fälligkeitsdatum vor heute liegt, mit Anzahl, Bruttosumme und dem Alter der ältesten in Tagen. |
| Nicht versendete Belege | Anzahl der gestellten Standardrechnungen ohne Erstversand. Diese Zahl wird in der Datenbank gezählt, nicht im Speicher. |
| Umsatzvergleich | Dem Umsatz des laufenden Jahres stellt die Übersicht den Umsatz zum selben Kalendertag des Vorjahres gegenüber und nennt die Abweichung in Prozent. Fehlt ein Vergleichswert, weil der Vorjahreswert null ist, entfällt die Prozentangabe. |
| Letzte Rechnungen | Unter den Kacheln listet die Seite die zehn neuesten Belege mit Nummer, Kunde, Datum, Betrag und Status; der Verweis **ALLE RECHNUNGEN** führt in die Liste. |

Die Belegzahlen je Status und die Forderungen sind Verweise; die Gesamtzahl ist kein Verweis.
Ein Klick öffnet die Rechnungsliste mit
genau der Auswahl, die die Zahl gezählt hat. Kennzahl und Liste zeigen deshalb dieselbe Menge.
Für die Umsatz- und Steuerkennzahlen gilt das nicht, sie summieren und verlinken nichts.

In der Rechnungsliste und auf der Detailseite unterscheidet der Status **Versendet** und
**Nicht versendet** bei gestellten Belegen. **Bezahlt** bleibt der Endzustand nach Zahlungseingang.

---

## Die Rechnungsliste filtern

Über der Rechnungsliste stehen sechs Filter, die sich kombinieren lassen:

| Filter | Auswahl |
|---|---|
| Suche | Rechnungsnummer oder Kundenname, als Teiltreffer |
| Status | Entwurf, Gestellt, Bezahlt, Storniert, Verworfen |
| Art | Rechnung oder Gutschrift |
| Frist | **Überfällig**: Fälligkeitsdatum liegt vor heute |
| Versand | **Ohne Versand**: ohne Erstversand, unabhängig vom Status |
| Stornostand | **Ohne Stornierte**: blendet Belege aus, zu denen eine gestellte oder bezahlte Gutschrift existiert (Parameter `storno=ohne`, dieselbe Bedingung wie die Kacheln der Übersicht) |

**Ohne Versand** prüft nur den fehlenden Erstversand. Das Etikett **Nicht versendet** verlangt
zusätzlich den Status **Gestellt**, die Kennzahl auf der Übersicht außerdem die Art **Rechnung**.

Solange Sie keinen Status wählen, blendet die Liste verworfene Entwürfe aus; sie erscheinen nur
über **Verworfen**. Die gesetzten Filter stehen in der Adresse der Seite, eine gefilterte Liste
lässt sich also als Lesezeichen ablegen. Unbekannte Werte für Art, Frist oder Versand werden
ignoriert; andere Filter bleiben wirksam. Ein unbekannter Status liefert eine leere Liste.

Die Liste zeigt höchstens 50 Belege je Seite (Konstante `SEITENGROESSE` in
routers/invoices.py). Darunter steht die Gesamtzahl, in der Datenbank gezählt und nicht
auf der angezeigten Seite, und bei mehreren Seiten blättern Sie mit **ZURÜCK** und
**WEITER**; die gesetzten Filter bleiben dabei stehen.

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
Programm schreibt seine PDF oder XML nicht wegen eines späteren Katalogstands um. Ein
solcher Beleg lässt sich dann aber auch nicht stornieren: die Gutschrift müsste die
unbekannte Einheit unverändert übernehmen und wäre weder bearbeitbar noch finalisierbar.
Das Programm lehnt deshalb vorab ab und nennt Position und Einheit, statt eine
Rechnungsnummer für einen Entwurf zu verbrauchen, der nie fertig wird (Storno-Route in
routers/invoices.py).

### Artikel- oder Leistungsnummer

Jede Position kann eine eigene Artikel- oder Leistungsnummer tragen, höchstens 50 Zeichen,
etwa für wiederkehrende Leistungen aus einer Vorlage. Sie steht im PDF klein unter der
Beschreibung („Art.-Nr.“, auf englischen Belegen „Item no.“), in der E-Rechnung als BT-155
und im GoBD-Export als letzte Spalte von `positionen.csv`. Vorlage und Storno übernehmen sie.
Leer bleibt sie einfach weg. Belege aus einer Übergabe bringen keine Artikelnummer mit; sie
lässt sich im Entwurf ergänzen.

Die Kundennummer, die das PDF im Kopf zeigt, steht ebenso in der E-Rechnung (BT-46).

### Leistungszeitraum je Position

Rechnen Sie mehrere Zeiträume auf einer Rechnung ab, etwa drei Monate eines Abonnements, kann
jede Position einen eigenen Leistungszeitraum tragen: Beginn und Ende, beide oder keines,
der Beginn nicht nach dem Ende. Er steht im PDF klein unter der Beschreibung, in der
E-Rechnung als BT-134/135 und im GoBD-Export in den Spalten `leistung_von` und
`leistung_bis`.

Der Leistungszeitraum oder das Leistungsdatum der Rechnung im Kopf bleibt die Pflichtangabe
nach § 14 Abs. 4 Nr. 6 UStG; die Positionszeiträume schlüsseln ihn nur auf und ersetzen ihn
nicht. Das Programm leitet ihn auch nicht aus den Positionen ab. Zwei Ausnahmen gibt es
(services/validator.py, Fehler `DELIVERY_DATE_MISSING`): eine Kleinbetragsrechnung bis
einschließlich 250,00 € Brutto kommt ohne Leistungszeitpunkt im Kopf aus (§ 33 UStDV), und
bei der Steuerkategorie K gilt diese Erleichterung nicht, weil die E-Rechnungs-Norm das
Lieferdatum unabhängig vom Betrag verlangt (EN 16931, BR-IC-11). Fehlt der Zeitpunkt im
übrigen Fall, sperrt der Fehler das Finalisieren. Storno übernimmt die
Positionszeiträume. Eine Vorlage lässt sie weg, denn die nächste Rechnung betrifft andere
Monate; verschoben wird nichts, weil das Programm Ihren Rhythmus nicht kennt.

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

<a id="belege-aus-uebergaben"></a>

## Belege aus Übergaben

In manchen Installationen hängt diesem Programm ein vorgelagertes System vor: es stellt
Abrechnungsaufträge auf, signiert sie und legt sie als Dateien in einen Belegordner, den
dieses Programm nur liest. Für solche Installationen gibt es unter **Einstellungen** den
Schalter **Beleg-Integration einschalten** (Route `POST /settings/beleg-integration`,
Feld `beleg_integration_aktiv`). Ohne den Schalter fehlt das Merkmal vollständig: kein
Menüpunkt, keine Spalte in der Kundenliste, und auch wer die Adresse kennt, erreicht
keine Seite. Eingeschaltet erscheint im Menü der Punkt **BELEGE**.

### Was die Seite zeigt

Die Seite BELEGE liest den Belegordner vor, mehr nicht. Ansehen hat keine Wirkung: kein
Datensatz entsteht, keine Zeile, und in den Ordner schreibt dieses Programm nie. Die
Tabelle nennt je Datei das Erzeugungsdatum, Abrechnungsquartal und Projekt, die Zahl der
Gutschriften, die Nettosumme und einen Befund:

- **ANGENOMMEN**: Signatur und Inhalt sind geprüft, der Beleg wartet auf den Knopf.
- **BEREITS VERARBEITET**: aus dieser Datei wurden schon Entwürfe angelegt; der Knopf
  fehlt, und ein erneuter Versuch meldet nur: „Dieser Beleg war schon verarbeitet.
  Zweimal eingelesen heißt einmal gewirkt."
- sonst der Befundcode der Ablehnung, etwa `FASSUNG_UNVERTRAEGLICH` bei einer
  Protokollfassung, die dieses Programm nicht kennt, samt dem Feld, das zur Last geht.

Abgelehnte Belege werden nicht gemerkt: sobald der Absender den Grund behoben hat, darf
derselbe Beleg wieder vorgelegt werden. Ist ein Nettobetrag falsch, ist der Beleg falsch;
die Rechnung wird nicht zurechtgebogen, der Absender erzeugt einen neuen.

### ALS RECHNUNG ANLEGEN

Erst der Knopf **ALS RECHNUNG ANLEGEN** schreibt. Aus einer Datei entsteht je Gutschrift
ein **Entwurf**, mit dem Typ, den der Absender bestimmt hat: 389 (Abrechnungsgutschrift)
oder 381 (Gutschrift). Danach landet die Seite auf der Vorschau des ersten Entwurfs.
Nichts wird automatisch finalisiert, nichts automatisch versendet.

Am Entwurf steht ein Teil des Inhalts aus dem signierten Beleg fest und lässt sich nicht
mehr ändern (services/belegsperre.py, `GESPERRTE_FELDER`): der Beteiligte, der
Leistungszeitraum und die Nettobeträge der Positionen, dazu Zahl, Einheit und
Positionszeiträume der Positionen. Steuersatz und Steuerkategorie stehen dagegen nicht im
Auftrag; sie entstehen erst hier aus dem umsatzsteuerlichen Status des Kunden und sind im
Entwurf korrigierbar, wenn die Ableitung nicht zur Leistung passt.

### Schnittstellen-ID

Das vorgelagerte System identifiziert seinen Beteiligten über die **Schnittstellen-ID**.
Das ist die interne Kennung des Kundendatensatzes in diesem Programm; eingeschaltete
Integration zeigt sie im Kundenformular und als Spalte in der Kundenliste, jeweils mit
einem Knopf zum Kopieren (templates/partials/schnittstellen_id.html). Sie muss beim
vorgelagerten System zum Beteiligten gehören, bevor ein Auftrag für diesen Kunden
ankommen kann. Ein Kunde entsteht aus einem Auftrag nicht: passt keine Kennung, oder
gehört sie zu einem per DEL ausgeblendeten Kunden, wird der Auftrag abgelehnt.

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

## Steuerkategorie

Unter **Steuertyp** im Rechnungsformular legen Sie fest, wie der Beleg umsatzsteuerlich
behandelt wird. Zur Auswahl stehen fünf Kategorien (services/validator.py,
`VALID_TAX_CATEGORIES`):

| Wert | Auswahl im Formular | Bedeutung |
|---|---|---|
| S | Inland (MwSt. 19 % / 7 %) | Regelbesteuerung: Sie weisen Umsatzsteuer aus, 19 oder 7 Prozent. |
| E | Kleinunternehmer (§ 19 UStG) | Sie weisen keine Steuer aus, der Steuersatz steht auf 0 Prozent. |
| AE | EU B2B: Reverse Charge (Art. 196 MwStSystRL) | Der Empfänger schuldet die Steuer; Steuersatz 0 Prozent, Ihre wie seine USt-IdNr. sind Pflicht. |
| K | EU: Innergemeinschaftliche Lieferung | Steuerfrei mit USt-IdNr. beider Seiten; der Leistungszeitpunkt ist hier auch bei Kleinbeträgen Pflicht. |
| O | Drittland / nicht steuerbar | Der Umsatz ist nicht im Inland steuerbar (§ 3a Abs. 2 UStG); dafür verlangt das Programm Ihre Steuernummer. |

In den Kategorien AE, K, O und E darf keine Position Steuer tragen; trägt eine trotzdem
einen Steuersatz über 0 Prozent, weist das Programm das Finalisieren ab. Einem
Kleinunternehmer (E), der trotzdem Steuer ausweist, schuldet sie nach § 14c Abs. 2 UStG
trotzdem, deshalb nennt der Fehler dort einen eigenen Text. Die Kategorie steht in der
E-Rechnung und im GoBD-Export; die Detailseite zeigt sie als Etikett am Kopf, außer bei S.

---

## Abzug auf Belegebene

Im Summenbereich des Entwurfs können Sie einen **Abzug (netto)** mit **Grund** eintragen,
etwa wenn eine bereits berechnete Leistung auf eine spätere Rechnung angerechnet wird. Betrag
und Grund gehören zusammen; ein Betrag ohne Grund wird nicht gespeichert. Der Abzug muss
größer als 0,00 € und kleiner als die Summe der Positionen sein.

Das Programm rechnet die Steuer dann auf der verminderten Basis: Positionssumme minus Abzug
ergibt den Nettobetrag, darauf der Steuersatz. Deshalb setzt ein Abzug voraus, dass alle
Positionen denselben Steuersatz tragen. Bei Anzahlungsrechnungen und Honorargutschriften
(Typ 389) ist kein Abzug möglich.

PDF und Detailseite zeigen Positionssumme, Abzug mit Grund, Nettobetrag, Steuer und
Endbetrag. In der E-Rechnung steht der Abzug als Nachlass auf Belegebene (EN 16931 BG-20),
im GoBD-Export in den letzten beiden Spalten von `rechnungen.csv`. Eine Stornorechnung und
eine Ersatzrechnung übernehmen den Abzug; eine Vorlage nicht, weil eine Anrechnung in der
Regel einmalig ist.

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

## Versand einrichten

Der Knopf zum Versenden erscheint erst, wenn ein Postausgangsserver hinterlegt ist. Der
Block **SMTP-KONFIGURATION** unter **Einstellungen** trägt Host, Port, Benutzername,
Passwort und Absenderadresse, dazu den Schalter **TLS aktivieren**; **SMTP SPEICHERN**
übernimmt die Angaben. Ein leeres Passwortfeld beim erneuten Speichern bedeutet
„unverändert". Was hier steht, gilt vor dem, was in der Serverkonfiguration hinterlegt
ist. Ist ein Host gespeichert, bietet der Block daneben **TEST SENDEN** an: eine Testmail
an eine Adresse Ihrer Wahl, mit dem Betreff „SMTP-Test erfolgreich". Misslingt der
Versand, steht die Meldung des Servers auf der Einstellungsseite.

Der Block darunter trägt die Anschriften für den Posteingang der Buchhaltung und für
Kopien:

- **Upload-Adresse** (Feld `datev_bcc_email`): jede gesendete Rechnung geht zusätzlich
  als Blindkopie dorthin. Der Posteingang der Buchhaltung verarbeitet nur den PDF-Anhang,
  nicht den Mailtext, und nimmt Anhänge bis 20 MB an.
- **Kopie an (CC)** (Feld `invoice_cc_email`): die globale Voreinstellung für das
  CC-Feld des Sende-Dialogs. Sie gilt für alle Kunden, wird aber überlagert, sobald beim
  Kunden eigene CC-Adressen hinterlegt sind. Mehrere Adressen trennen Sie mit Komma,
  höchstens fünf; die Kopie steht im Mailkopf und ist für den Kunden sichtbar, anders
  als die Blindkopie an die Buchhaltung.

Beide Felder prüft das Programm beim Speichern (services/empfaenger.py); eine unbrauchbare
Adresse wird gar nicht erst geschrieben, auch nicht die andere aus demselben Formular.

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
2. Wählen Sie **GUTSCHRIFT ERSTELLEN**. Es entsteht ein Entwurf einer Gutschrift, der die
   Beträge, Positionen und den Abzug des Originals unverändert übernimmt. Rechnungs- und
   Fälligkeitsdatum der Gutschrift stehen auf heute; Zahlungsbedingungen und Bemerkung
   ersetzt das Programm durch feste Texte in der Belegsprache des Originals
   („Gutschrift/Storno zur Rechnung <Nummer>." und „Storno zur Rechnung <Nummer> vom
   <Datum>.", services/storno.py, `build_storno`), damit niemand am Spiegel des Originals
   etwas Eigenes hineinschreibt.
3. Prüfen Sie den Entwurf und **finalisieren** Sie ihn. Jetzt entsteht das ZUGFeRD-PDF der
   Gutschrift.
4. Senden Sie die Gutschrift an Ihre Kundin oder Ihren Kunden und an die Buchhaltung, so wie
   Sie es mit der Originalrechnung getan haben.
5. Setzen Sie das **Original** auf **storniert**. Dieser Schritt bleibt Ihnen überlassen,
   siehe unten.
6. Schreiben Sie, falls nötig, eine neue, korrekte Rechnung. Der vorgesehene Weg ist die
   **Ersatzrechnung** im nächsten Abschnitt: sie verweist auf die stornierte Rechnung und
   übernimmt Positionen, Abzug und Belegart des Originals.

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

**Sie können eine gestellte Gutschrift nicht stornieren.**
Die Gutschrift ist selbst die Korrektur. Stornierte man sie, lebte das Original wieder
auf und ließe sich weder bezahlen noch erneut stornieren. Der Fehlercode heißt
`GUTSCHRIFT_NICHT_STORNIERBAR` (services/storno.py, `pruefe_stornierbar`), und die
Detailseite einer gestellten Gutschrift sagt dasselbe im Hinweiskasten: „Diese Gutschrift
ist endgültig; sie ist selbst die Korrektur und lässt sich nicht stornieren." Der
vorgesehene Weg bei einer falschen Gutschrift ist die Ersatzrechnung zum Original, der
Kasten verlinkt sie.

**Eine Rechnung mit unbekannter Einheit lässt sich nicht stornieren.**
Die Gutschrift erbt die Einheiten des Originals unverändert; kennt der Katalog eine davon
nicht, wäre der Entwurf weder bearbeitbar noch finalisierbar. Das Programm lehnt deshalb
vorab ab und nennt Position und Einheit (Storno-Route in routers/invoices.py); die
Einheit muss im Beleg berichtigt werden, und der Stornoweg bietet dafür keinen Eingriff.

**Sie können ein storniertes Original nicht als bezahlt markieren.**
Ein Beleg, der aufgehoben wurde, kann nicht gleichzeitig beglichen sein. Ist das Geld
tatsächlich geflossen und Sie erstatten es, gehört das an die Gutschrift: die dürfen Sie als
bezahlt markieren, und dort heißt bezahlt schlicht erstattet.

Für die Sperre genügt der bloße Gutschrift-Entwurf: solange er nicht verworfen ist,
blockiert er den Weg nach bezahlt (services/bezahlt_am.py, `aktive_gutschrift`), denn er
ist die erklärte Absicht zu korrigieren. Die Meldung nennt die Gutschrift mit ihrer
Nummer und die zwei Wege: das Original auf storniert setzen oder den versehentlichen
Entwurf verwerfen.

**Das Zahlungsdatum ist geprüft.**
Neben **ALS BEZAHLT MARKIEREN** tragen Sie das Datum des Zahlungseingangs ein; leer heißt
heute. Es darf weder in der Zukunft noch vor dem Rechnungsdatum liegen, beide Fälle weist
das Programm zurück („Das Zahlungsdatum darf nicht in der Zukunft liegen." und „Das
Zahlungsdatum darf nicht vor dem Rechnungsdatum liegen.").

### Warum das Original nicht von selbst auf „storniert" springt

Das Programm setzt den Status des Originals nicht automatisch. Der Grund ist unangenehm
konkret: **bezahlt** ist ein Endzustand, aus dem kein Weg mehr herausführt, und eine bereits
bezahlte Rechnung darf storniert werden. Eine Automatik würde also für gestellte Rechnungen
greifen und für bezahlte stillschweigend nicht, also in genau der Hälfte der Fälle. Eine
Regel, die manchmal wirkt, ist schlimmer als keine, weil niemand ihr ansieht, wann sie
gewirkt hat.

Statt die Zustandsregeln aufzuweichen, bleibt der Schritt bei Ihnen. Solange Sie ihn nicht
tun, steht die stornierte Rechnung weiterhin als **gestellt** in der Liste. Auf der Übersicht
zählt sie aber nicht mehr, sobald die Gutschrift gestellt ist: eine gestellte oder bezahlte
Gutschrift nimmt ihr Original aus den offenen und aus den überfälligen Forderungen
(services/storno_wirkung.py, `WIRKSAM_STORNIERT`). Liste und Kennzahlen können also
auseinanderfallen, und das ist Absicht: die Liste zeigt den Beleg, die Kennzahlen zeigen das
Geld.

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
verwerfen, ein Kunde lässt sich inaktiv setzen oder mit **DEL** aus allen Auswahlen
ausblenden (siehe den Abschnitt Kunden); die Datensätze bleiben, weil sonst Nummern fehlen
würden, die niemand mehr erklären kann.

---

## Ersatzrechnung

Die Stornierung hebt die falsche Rechnung auf, stellt aber noch keine richtige aus. Genau das
tut die **Ersatzrechnung**: eine gewöhnliche Rechnung mit neuer Nummer, die über den
Vorgängerbezug in der E-Rechnung (BT-25, Feld `ersetzt_invoice_id`) auf genau die stornierte
Rechnung zeigt und deren Inhalt als Ausgangslage mitbringt. Die Bücher bleiben lückenlos:
Rechnung, Gutschrift, Ersatzrechnung, jeder Beleg mit eigener Nummer und jeder Bezug
nachlesbar.

### Wann der Knopf erscheint

Auf der Detailseite einer Rechnung steht **ERSATZRECHNUNG ANLEGEN**, sobald alle drei
Vorbedingungen erfüllt sind (services/ersatzrechnung.py, `pruefe_ersetzbar`):

1. Die Rechnung ist finalisiert und eine eigenständige Rechnung, also Standardrechnung oder
   Anzahlungsrechnung. Ein Entwurf braucht keinen Ersatz, er ist noch frei; Gutschriften
   und Abrechnungsgutschriften haben ihren eigenen Korrekturweg.
2. Es gibt eine Gutschrift zu ihr, die nicht verworfen ist. Ein Gutschrift-Entwurf genügt
   für den Knopf.
3. Es gibt noch keine andere nicht verworfene Ersatzrechnung zu ihr.

Derselbe Knopf steht im Hinweiskasten einer gestellten Gutschrift, wenn deren Original noch
ersetzbar ist: von der falschen Gutschrift aus kommen Sie mit einem Klick zur neuen Rechnung
für die Leistung.

Der Knopf führt auf das gewohnte Formular (Route `GET /invoices/neu?ersetzt=...`), darüber
steht der Hinweis: „Ersetzt Rechnung <Nummer> vom <Datum>." Der Entwurf entsteht erst mit
dem Speichern und bekommt dabei seine eigene Nummer; auf seiner Detailseite und in der
E-Rechnung bleibt der Bezug zur stornierten Rechnung dauerhaft sichtbar.

### Was übernommen wird

Kunde, Positionen samt Einheiten und Steuersätzen, Abzug mit Grund, Steuerkategorie,
Bestellnummer und Referenz des Kunden, Leistungsdatum und Leistungszeitraum,
Zahlungsbedingungen, Bemerkung, Belegsprache und die Belegart des Originals. Anders als bei
einer Vorlage gehört der Abzug dazu: die Ersatzrechnung erbringt dieselbe Leistung, die
einmalige Anrechnung gilt weiter (routers/invoices.py, `_vorbelegung_aus` mit
`mit_abzug=True`). Rechnungs- und Fälligkeitsdatum setzt das Formular wie bei jeder neuen
Rechnung auf heute beziehungsweise heute plus 14 Tage; beide können Sie ändern.

### Was das Programm ablehnt

- **ERSATZ_OHNE_GUTSCHRIFT**: Zu der Rechnung gibt es keine Gutschrift. Ohne sie stünden
  zwei Rechnungen über dieselbe Leistung in den Büchern; erst die Stornierung räumt den
  Weg frei.
- **ERSATZ_SCHON_VORHANDEN**: Die Rechnung wird bereits ersetzt, und die Meldung nennt die
  Nummer der vorhandenen Ersatzrechnung. Es gibt nur eine je Original; ein verworfener
  Entwurf zählt nicht. Ist die vorhandene Ersatzrechnung selbst falsch, stornieren Sie sie
  und ersetzen sie wiederum.
- **ERSATZ_GUTSCHRIFT_NICHT_GESTELLT**: Die Gutschrift ist noch nicht gestellt. Diese
  Prüfung greift nicht beim Anlegen, sondern erst beim Finalisieren
  (services/ersatzrechnung.py, `pruefe_finalisierbar`), denn bis dahin kann die Gutschrift
  noch verworfen worden sein. Eine Ersatzrechnung neben einem ungeminderten Original wäre
  eine zweite Forderung über dieselbe Leistung.

Ist ein Ersatzrechnung-Entwurf verworfen worden, lässt er sich über **ZURÜCKHOLEN**
zurückholen; dabei laufen die Prüfungen erneut, denn inzwischen kann eine andere
Ersatzrechnung stehen oder die Gutschrift kann fehlen.

---

## Archiv

Unter **ARCHIV** liegen die abgelegten Dateien jedes finalisierten Belegs: das ZUGFeRD-PDF
und die E-Rechnungs-XML, beides acht Jahre aufbewahrungspflichtig. Die Seite zeigt zwei
Bereiche, **PDF** und **XML**, je als Tabelle mit Dateiname, Änderungszeitpunkt, Größe und
einem Link **laden** je Datei (routers/archive.py).

Über **Dateiname** suchen Sie, etwa nach einem Teil der Rechnungsnummer; die Suche trifft
einen Teil des Namens, unabhängig von Groß- und Kleinschreibung. **ZURÜCKSETZEN** leert das
Feld. Pro Bereich zeigt die Tabelle 100 Dateien, die neuesten zuerst; darüber blättern Sie
mit **ZURÜCK** und **WEITER**.

Sichtbar sind nur Dateien, zu denen ein Beleg der Datenbank gehört. Was auf der Platte liegt,
ohne dass ein Beleg darauf zeigt, bleibt unsichtbar; Reste der Vorschau und fremde Importe
erscheinen gar nicht erst. Wollen Sie alles auf einmal, mit Tabellen und Änderungsprotokoll
als Prüferpaket, führt die Seite unten zum GoBD-Export.

---

## GoBD-Export

Der Menüpunkt **GOBD-EXPORT** erzeugt die Datenträgerüberlassung für eine Prüfung: alle
Tabellen, alle Originalbelege und das Änderungsprotokoll in einer ZIP-Datei (routers/export.py,
services/gobd_export.py).

Wählen Sie den Zeitraum über **Von** und **Bis**, gemessen am Ausstellungsdatum der Belege;
vorausgefüllt sind der Jahresanfang und heute. Ein Enddatum vor dem Startdatum lehnt die
Seite ab („Das Enddatum darf nicht vor dem Startdatum liegen."). **ZIP HERUNTERLADEN**
liefert eine Datei namens `gobd-export_<von>_<bis>.zip` mit folgendem Inhalt:

- `rechnungen.csv`: alle Belege des Zeitraums außer Entwürfen, verworfene Entwürfe
  ausdrücklich mit dabei, weil ihre Nummer vergeben wurde und ihre Zeile die Lücke im
  Nummernkreis erklärt. Stornos nennen ihr Original in `original_rechnungsnummer`,
  Ersatzrechnungen die stornierte Rechnung in `ersetzt_rechnungsnummer`; der Abzug auf
  Belegebene steht in den letzten beiden Spalten (siehe den Abschnitt Abzug auf
  Belegebene).
- `positionen.csv`: alle Positionen, verknüpft über `rechnungsnummer`; die letzten Spalten
  sind Artikel- oder Leistungsnummer und Leistungszeitraum (siehe die Abschnitte Artikel-
  oder Leistungsnummer und Leistungszeitraum je Position).
- `kunden.csv`: Stammdaten der im Zeitraum berechneten Kunden, auch ausgeblendete, mit
  Löschzeitpunkt in `geloescht_am`.
- `audit_log.csv`: das Änderungsprotokoll des Zeitraums; Zeitpunkt, Tabelle, Datensatz,
  Aktion, alte und neue Werte, die Wertpaare als JSON.
- `index.xml` und `gdpdu.dtd`: die Beschreibungsdateien des GDPdU-Standards, damit die
  Prüfsoftware die Tabellen einlesen kann.
- `dokumente/`: von jedem Beleg das ZUGFeRD-PDF und die E-Rechnungs-XML.
- `dokumentation.txt`: Zeichensatz, Trennzeichen und Datumsformat der Tabellen. Fehlt eine
  Belegdatei, listet `fehlende_dateien.txt` sie auf.

---

## Update-Hinweis

Das Programm prüft nie von selbst nach, ob es eine neuere Fassung gibt: nicht beim Start und
nicht im Hintergrund. Die Prüfung läuft nur, wenn Sie sie anstoßen (routers/updates.py,
Route `POST /updates/pruefen`).

Das erste Mal fragt eine eigene Seite um Ihre Einwilligung („Nach Updates suchen"). Sie nennt
die einzige Adresse, die dabei aufgerufen wird, und sagt, was hinausgeht: nichts von dieser
Installation, keine Versionsnummer, keine Kennung, keine Beleg-, Kunden- oder Firmendaten.
Sichtbar wird der Gegenseite nur der Abruf selbst, also die IP-Adresse des Anschlusses, wie
beim Öffnen jeder Webseite. Die Bestätigung wird einmal gespeichert; auch danach wird nur
gesucht, wenn Sie klicken.

Die Ergebnisse erscheinen als Banner oben auf den Seiten:

- Liegt eine neuere Fassung vor, nennt das Banner sie, mit einem Link auf die Änderungen und
  mit **So einspielen** auf die Anleitung (`/updates/anleitung`): zuerst Datenbank und
  Belege sichern, dann die neue Fassung holen, dann `docker compose up -d --build`. Nur
  Herunterladen genügt nicht, der Dienst wird aus dem Quelltext gebaut.
- Ein solches Banner lässt sich mit **Schließen** beiseitelegen und merkt sich die abgewiesene
  Fassung; dieselbe Fassung erscheint danach nicht wieder.
- Als dringend eingestufte Fassungen, etwa bei einem Sicherheits- oder Rechtsproblem
  (services/update_check.py, `ESCALATED`), erscheinen rot und ohne **Schließen**; sie
  verschwinden erst mit dem Einspielen.
- Nach 30 Tagen ohne Prüfung erinnert das Banner ans Suchen („Du hast seit <Anzahl> Tagen
  nicht nach Updates gesucht. Bleib auf dem neuesten Stand."), mit Knopf **Jetzt suchen**.
  War die letzte Prüfung nicht möglich, steht stattdessen „Die letzte Update-Prüfung war
  nicht möglich.".
