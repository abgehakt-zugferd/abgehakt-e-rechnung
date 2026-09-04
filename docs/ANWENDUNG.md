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

---

## Stammdaten: Kunden und Firma

### Kunden

Jeder Kunde hat eine **Kundennummer** (Pflicht), einen Namen und optional Adresse, E-Mail,
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
| Offene Rechnungen | Finalisiert (`gestellt`), noch nicht bezahlt, ohne Gutschriften |
| Bezahlt diesen Monat | Brutto-Summe der Rechnungen, die **in diesem Kalendermonat** als bezahlt vermerkt wurden (nicht Ausstellungsdatum) |
| Umsatz lfd. Jahr | Brutto-Umsatz gestellter und bezahlter Rechnungen seit Jahresanfang (ohne Gutschriften) |
| Schuldige Umsatzsteuer | Summe der auf gestellten Belegen **ausgewiesenen USt** im laufenden Jahr, abzüglich Gutschriften, **ohne Vorsteuerabzug** (das Programm kennt keine Eingangsrechnungen) |
| Gesch. Steuerabgaben | Schuldige USt plus pauschale **KSt/GewSt-Rücklage** auf den Nettoumsatz (Anteil in den Einstellungen) |

In der Rechnungsliste und auf der Detailseite unterscheidet der Status **Versendet** und
**Nicht versendet** bei finalisierten Belegen. **Bezahlt** bleibt der Endzustag nach Zahlungseingang.

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

Das Skript setzt, sofern noch leer:

- `datev_sent_at` auf das **Rechnungsdatum** (Erstversand),
- den Status **bezahlt** (falls noch `gestellt`),
- einen Eintrag im **Versandprotokoll** (Hinweis: historischer Versand, kein erneuter Mailversand),
- den Bezahlt-Zeitpunkt (`updated_at`) auf das **Fälligkeitsdatum**, damit „Bezahlt diesen Monat“
  nicht fälschlich den Umzugmonat zeigt.

Exakte Versand- oder Zahlungsdaten aus dem alten System können nur per Skript-Anpassung oder
direkter Datenbankkorrektur gesetzt werden; die Standard-Schätzung ist bewusst aus
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
