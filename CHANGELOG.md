# Änderungen

Hier steht, was sich zwischen zwei veröffentlichten Fassungen geändert hat, mit
dem Blick dessen, der Abgehakt betreibt: Was ist neu, was muss ich vor dem
Wechsel tun, was sieht danach anders aus. Die einzelnen Pull Requests stehen in
Klammern.

## Nächste Fassung (noch nicht veröffentlicht, Stand seit v1.1.0)

### Neu

- **Schlussrechnung verrechnet eine Anzahlung (#259, erster Teil).** Im Rechnungsformular lässt sich eine bezahlte Anzahlungsrechnung desselben Kunden auswählen. Die E-Rechnung führt sie als Vorauszahlung (BT-113) mit Verweis auf die Anzahlungsrechnung, das PDF zieht sie unter der Summe ab. Prüfungen vor dem Finalisieren verhindern doppelte, fremde oder unbezahlte Anzahlungen. Noch nicht enthalten: mehrere Anzahlungen je Rechnung und der Abzug in den Kennzahlen der Übersicht.

### Sicherheit

- **Python-Pakete mit bekannten Sicherheitslücken angehoben:** fastapi 0.162.0 mit starlette 1.10.0, python-multipart 0.0.33 (Formular- und Datei-Upload), cryptography 50.0.2, jinja2 3.1.6, pillow 13.0.0, python-dotenv 1.2.4, certifi 2026.10.23 und pypdf 7.0.0 (nur von den Tests benutzt). Für den Betrieb heißt das: nach dem Wechsel das Abbild neu bauen.
- **Mustang 2.26.0 statt 2.24.0.** Die Prüfbibliothek für E-Rechnungen schließt damit zwei Lücken in ihrem PDF-Prüfteil (CVE-2026-54078, CVE-2026-54079) und bringt die aktuellen Prüfregeln für EN 16931 mit. Für den Betrieb heißt das: nach dem Wechsel das Abbild neu bauen, sonst läuft die alte Fassung weiter.

## v1.1.0 (2026-11-04)

### Drittes Design: Terminal

Der Knopf „Design“ unten in der Seitenleiste schaltet jetzt reihum zwischen
Abgehakt, Pixel und Terminal. Terminal ist ein dunkles Design mit gedämpften
Pastellfarben. Oben liegt eine Stahlleiste mit der Wortmarke in Chromschrift. Karten
und Seitenleiste wirken wie Glas, mit leichter Rundung und weichem Glanz.

Lavendel steht für Text, Mint für Akzente und die aktive Auswahl. Zustände stehen als
Form und Wort in eigener Farbe:
- ● bezahlt in Mint
- ▲ gestellt oder offen in Pfirsich
- ■ überfällig in Rosé
- ◆ Entwurf in Hellblau
- ○ storniert in gedämpftem Lavendel

Überschriften stehen in Saira Condensed, Kennzahlen in VT323, Fließtext, Beträge und
Beschriftungen in IBM Plex Mono. Keine Schrift ist kleiner als 15 px. Jede Textfarbe
erreicht auf den dunklen Flächen einen Kontrast von mindestens 6:1, die Schrift auf der Stahlleiste mindestens 4,5:1.

Die Auswahl gilt je Browser und bleibt gespeichert. Vorgabe bleibt Abgehakt. PDF und
E-Rechnung sehen in jedem Design gleich aus. Alle Schriften liegen im Image, nichts wird
aus dem Netz nachgeladen.

### Zahlungsdatum: vor dem Rechnungsdatum bei Rechnungsaufträgen, protokollierte Korrektur (#278)

Bei einem Beleg aus einem Rechnungsauftrag darf das Zahlungsdatum vor dem Rechnungsdatum
liegen, aber nicht vor dem Beginn des Leistungszeitraums (ohne Zeitraum: Leistungsdatum;
fehlt beides: Rechnungsdatum) und nicht in der Zukunft. Alle anderen Belege behalten die
Untergrenze Rechnungsdatum. Das Datumsfeld auf der Belegseite folgt derselben Regel.
An einem bezahlten Beleg gibt es neu **Zahlungsdatum korrigieren** (neues Datum und Grund,
beide Pflicht). Die Korrektur steht im Änderungsprotokoll mit altem und neuem Datum, Grund
und Zeitpunkt; jede andere Änderung des Zahlungsdatums bleibt gesperrt. Keine Migration.
### VIES-Prüfung verwirft keine ungespeicherten Eingaben mehr (#274)

Der Dialog „Jetzt bei VIES prüfen“ in der Kundenbearbeitung und in den Firmeneinstellungen
schickte bisher nur USt-IdNr. und Name ab und lud die Seite aus der Datenbank neu: Land,
Anschrift und alle übrigen ungespeicherten Eingaben waren still verloren. Jetzt speichert
die Bestätigung („Einverstanden, speichern und prüfen“) zuerst das ganze Formular, mit
denselben Prüfungen und Fehlermeldungen wie beim normalen Speichern, und prüft danach bei
VIES. Scheitert das Speichern an einer Formularprüfung, gibt es keine Abfrage und die
Eingaben bleiben im Formular. Ohne Einwilligung entsteht keine Verbindung, und es wird auch
nichts gespeichert. Die Wege `/customers/{id}/ust-id-pruefen` und `/settings/ust-id-pruefen`
entfallen; die Prüfung läuft über die Speicherwege mit dem Feld `danach_vies=1`.
### Reverse Charge an einen Kunden in Deutschland mit ausländischer USt-IdNr. sperrt das Finalisieren (#275)

Ein Entwurf mit Steuerkategorie AE, dessen Kunde das Land DE und eine USt-IdNr. mit
einem anderen Ländercode trägt, lässt sich nicht mehr finalisieren. Die Meldung nennt
den Widerspruch und den Weg: Land und USt-IdNr. beim Kunden prüfen, speichern, neu
finalisieren. Inländischer Reverse Charge mit deutscher USt-IdNr. bleibt bei der
bisherigen Warnung. Gestellte Belege werden beim erneuten Prüfen nicht ungültig.

### Stornierte Belege zeigen „storniert durch“ (#269, #267)

Hat ein Beleg eine gestellte oder bezahlte Gutschrift (bei einer Gutschrift des Typs 389
den Storno dazu), steht in Belegansicht und Liste „storniert durch“ mit
Link auf diesen Beleg. Der Status des Originals bleibt unverändert; die Anzeige folgt
derselben Regel wie die Kennzahlen. Ein bezahlter und stornierter Beleg zeigt beides.
Der Knopf „ALS STORNIERT MARKIEREN“ erscheint nur noch, wenn es keinen gestellten oder
bezahlten Stornobeleg gibt; ein Stornobeleg als Entwurf ändert nichts. Der gestellte Storno
einer Gutschrift (389) trägt jetzt wie die Stornorechnung den Hinweis, dass er endgültig ist
und wie man einen Fehler korrigiert, in der Belegsprache (de oder en), mit Link zum Original.

### Gutschriften aus einem Abrechnungsauftrag sperren ihren Auftragsschlüssel (#264)

Beim Anlegen der Entwürfe aus einem Abrechnungsauftrag wird der Auftragsschlüssel je
Gutschrift jetzt als Nachweis und Sperre gespeichert, wie bei der Ausgangsrechnung. Ein
zweites Einlesen desselben Auftrags meldet AUFTRAG_SCHON_GERECHNET je Gutschrift und legt
keine doppelten Gutschriften mehr an. Verwerfen, Zurückholen, manuelles Stornieren und
der gestellte Storno geben die Sperre frei bzw. nehmen sie wieder auf, unabhängig von der
Belegart. Ein gleichzeitiges Einlesen endet mit einer Meldung statt mit einem Serverfehler.

### Platzhalter im Kopf- oder Fußtext sperren das Finalisieren (#270)

Ein Entwurf, dessen Kopf- oder Fußtext noch einen Platzhalter zum Ersetzen trägt
(`<M>`, `<MM/JJJJ>`, `<nr>`), wird beim Finalisieren mit einer Meldung abgelehnt, die
Feld und Platzhalter nennt, zum Beispiel „Kopftext enthält noch den Platzhalter <M>“.
Der Entwurf bleibt unverändert, Speichern geht weiter. Erkannt wird eine spitze Klammer
auf, 1 bis 16 Zeichen ohne Klammern (das erste kein Leerraum) und eine spitze Klammer
zu. „Menge < 5“, „a < b > c“ und „weniger als <10 €“ sperren nicht. Hinweis: auch ein
Text wie `<name@beispiel.de>` im Kopf- oder Fußtext sperrt, weil er dem Muster entspricht.

### Übergabeordner der Live-Installation als Zuschaltung, nur lesend

Neue Datei `docker-compose.uebergabe.yml`. Der Betreiber setzt in seiner lokalen
Umgebungsdatei `ZEMP_UEBERGABEN` (absoluter Pfad, Pflicht, ohne Vorgabe) und
`COMPOSE_FILE=docker-compose.yml:docker-compose.uebergabe.yml`; danach sieht die
Live-Installation die eingehende Richtung des Übergabeordners schreibgeschützt. Die
Gegenrichtung wird nicht eingehängt. Ohne Zuschaltung ändert sich nichts. Neubau ohne
`down -v`; Schritte und Prüfung stehen in `docs/INTEGRATION-TESTINSTANZ.md`.

### Zahlungstext folgt der Belegsprache auch beim Finalisieren (#260)

Beim Finalisieren eines Entwurfs wird die Zahlungsvorgabe der falschen Sprache jetzt
ersetzt, wie schon beim Speichern: Steht im Feld genau die Firmenvorgabe der anderen
Sprache, geht die Vorgabe der Belegsprache in PDF und XML (BT-20). Dabei hat ein
Zahlungshinweis des Kunden Vorrang vor der Firmenvorgabe, ebenso bei leerem Feld, auch beim Bearbeiten eines Entwurfs. Freitext
bleibt unverändert. Fehlt die englische Vorgabe und gibt es keinen Kundenhinweis, wird
das Finalisieren mit der Meldung des Speicherns blockiert, der Entwurf bleibt wie er war.
Rechnungsaufträge und Gutschriften behalten ihren Weg.

### Testsuite läuft parallel (Mutationsprüfung)

Nur für Entwickler: Mehrere pytest-Prozesse gegen denselben Postgres löschen sich nicht
mehr gegenseitig die Test-Datenbank. `ABGEHAKT_TEST_DB` setzt ihren Namen,
`ABGEHAKT_TEST_DB_JE_PROZESS=1` gibt jedem Prozess eine eigene. Die Provisionierung der
App-Rolle wird beim Start per Advisory-Sperre serialisiert; bei einem einzelnen Start
ändert sich nichts. Am Verhalten der Anwendung ändert sich nichts.

### Umsatz je Steuerkategorie auf der Übersicht (#256)

Die Übersicht zeigt eine Tabelle des laufenden Quartals mit Netto und Umsatzsteuer
je Steuerkategorie und Steuersatz. Das trennt Reverse Charge, innergemeinschaftliche
Lieferungen, nicht steuerbare und steuerfreie Umsätze für die Voranmeldung. Belegmenge
und Zeitlogik sind die der Kacheln; Belege in anderer Währung stehen getrennt.

### Korrektur zur Belegsprache (#245)

Unter *Rechnungs-PDF* stand bisher, die Belegsprache wirke nur auf das PDF und
die XML behalte die deutschen Rechtstexte. Das trifft so nicht zu: Die
Beschriftungen der Pflichtangaben des Geschäftsbriefs (BT-33) folgen der
Belegsprache auch in der CII-XML (`zugferd_xml/parteien.py` über
`pflichtangaben`). Unverändert sprachunabhängig bleiben Codes, Datumsformate
(`YYYYMMDD`), Beträge, Nutzereingaben und die Steuerbefreiungstexte E/K/O; der
Reverse-Charge-Hinweis AE bleibt in beiden Ausgaben zweisprachig. Der ältere
Eintrag unten bleibt als damalige Formulierung stehen.

### Vor dem Wechsel lesen

Der Wechsel bringt Schemaänderungen mit; die Kette steht unter
`backend/alembic/versions/`. Der Start führt sie selbst aus. **Vorher sichern**,
wie im README unter *Sicherung und Rücksicherung* beschrieben. Drei greifen in
Bestandsdaten ein oder können den Start anhalten:

- **Rechtsform nachtragen, sonst lässt sich nichts mehr stellen** (Migration 019,
  #133). Rechnungen tragen jetzt die Pflichtangaben für Geschäftsbriefe
  (Rechtsform, Sitz, Registergericht, Registernummer, Vertretung). Die Migration
  rät keine Rechtsform. Bis sie unter *Einstellungen* gewählt ist, sperrt die
  Prüfung das Finalisieren.
- **Steuerstatus der Kunden ist danach „ungeklärt“** (Migration 017, #126).
  Bisher stand er still auf „regelbesteuert“, ohne dass jemand gefragt wurde.
  Für gewöhnliche Rechnungen ändert das nichts. Wer selbst ausgestellte
  Gutschriften (Belegart 389) erzeugt, muss den Status des Empfängers vorher
  bewusst setzen. Kunden mit bereits angelegter Gutschrift dieser Art werden
  automatisch als Gutschriftempfänger markiert.
- **Doppelte Stornogutschriften halten den Start an** (Migration 013, #90).
  Gibt es zu einer Rechnung mehr als eine nicht verworfene Gutschrift, bricht
  die Migration mit einer Liste der betroffenen Nummern ab und ändert nichts.
  Den Bestand von Hand klären, dann neu starten.

Außerdem: Bereits bezahlte Rechnungen erhalten als Zahlungsdatum näherungsweise
den Tag ihrer letzten Änderung (Migration 018, #130). Die Umsatzkennzahlen der
Übersicht können sich dadurch in einen anderen Monat verschieben.

### Neue Belegarten und Belegwege

- **Gutschriftverfahren (389) nutzbar (#156)**: Rollenbesetzung in XML und PDF,
  Pflichtangabe „Gutschrift“, getrennte Titel, manuelle Anlage und Storno mit Bezug
  auf die 389. Die Stornoform (BT-3 261 und Titel) bleibt bis zur steuerlichen
  Prüfung vorläufig. Herleitung je Position wird gespeichert, bei Bearbeitung
  erhalten und im PDF getrennt vom Umsatzsteuersatz gezeigt. Eigene Listenfilter
  und die Kennzahl Offene Auszahlungen ergänzen die Vorsteuer.
  PostgreSQL- und Mustang-Abnahme erfolgen im Gateway.
- **Anzahlungsrechnung (386)** als bewusst wählbare Belegart (#108).
- **Ersatzrechnung** zu einer stornierten Rechnung, mit Verweis auf die
  Vorgängerrechnung (BT-25) (#140). Eine gestellte Gutschrift ist endgültig; das
  Programm zeigt stattdessen den Weg zur Ersatzrechnung (#144).
- **Bestehende Rechnung als Vorlage**: das Anlegeformular wird vorbefüllt (#107).
- **Abzug auf Belegebene** (EN 16931 BG-20), etwa für einen Rabatt auf die ganze
  Rechnung (#153).
- **Rechnungsentwürfe aus signierten Übergabebelegen** eines vorgelagerten
  Systems, hinter einem Schalter und nur lesend auf einen Ordner
  (`UEBERGABEN_ORDNER`, `SCHLUESSEL_PFAD`) (#69). Der Absender bestimmt die Belegart
  (381 oder 389); für 389 gelten die Grenzen oben.
- **Abrechnungsaufstellung** als eigenes Modell (kein TypeCode): Entwurf aus
  Aufstellungsauftrag, PDF/A, Versand an die Buchhaltung, Storno, Archivbereich
  und Aufnahme in den GoBD-Export.

### Inhalt der E-Rechnung

- Bestellnummer des Kunden (BT-13), Kundennummer (BT-46) und Artikelnummer
  (BT-155) (#102, #134).
- Eigener Leistungszeitraum je Position (BT-134/135) (#135).
- Einheiten aus einem Katalog; Personen werden als `IE` geführt, kein stiller
  Rückfall auf „Stück“ mehr (#106, #112).
- Reverse Charge nennt Art. 196 der Richtlinie 2006/112/EG als Rechtsgrund; die
  Pflichtangaben sind belegt und drei Lücken geschlossen (#79, #87).
  Kategorie K trägt ihre eigene UStG-Fundstelle (#99).
- Die Prüfung vor dem Stellen gleicht die Steuerkategorie mit dem Land des
  Kunden ab (#152).
- Beim Einspielen aus XML wird die Belegart aus dem TypeCode übernommen (#128).

### Rechnungs-PDF

- Belegsprache Deutsch oder Englisch je Rechnung. Sie wirkt nur auf das PDF:
  die XML behält die deutschen Rechtstexte, der Reverse-Charge-Hinweis steht in
  beiden Fassungen zweisprachig (#114). Der Mailtext lässt sich je Sprache einstellen (#116).
- Zahlungsblock, Summen rechtsbündig, Absenderzeile, Fuß und Seitenzahl auf
  jeder Seite, Spaltenbreiten nach Inhalt (#136, #137, #138).
- EPC-QR-Code für die Überweisung (#56).

### Kunden und Versand

- Landesauswahl mit 47 Ländern für Kunden und der vollen ISO-Liste für den
  Aussteller (#78, #83).
- CC-Empfänger je Kunde, Empfänger in der Kundenkarte auch im Entwurf,
  Bankverbindung am Kunden für Gutschriften, Schnittstellen-ID am Kunden für die
  Beleg-Integration (#59, #63, #67, #70).
- USt-IdNr.-Prüfung über VIES mit Einwilligungsdialog (#71, #98).

### Übersicht und Kennzahlen

- Kennzahlen mit Beträgen, Überfälligkeit und Listenfiltern (#115).
- Umsatz zählt nur bezahlte Nettobeträge nach Zahlungsdatum (#130); eine
  Stornierung per Gutschrift wirkt genau einmal (#143).

### Korrekturen

- **Anzahlungsrechnungen in Kennzahlen (#157)**: 386 zählt nach `bezahlt_am` zu
  Umsatz, Bezahlt und schuldiger Umsatzsteuer; gestellt und unbezahlt zu offenen
  Forderungen. Wirksame Stornos einer 389 heben Auszahlung und Vorsteuer einmal auf.

- „Heute“ ist Europe/Berlin, nicht die UTC-Uhr des Containers (#132).
- Zwei Klicks auf *Finalisieren* erzeugen nicht mehr zwei Belege; ein Beleg wird
  nur einmal storniert; ein stornierter Beleg ist weder bezahlt noch bearbeitbar.
- Genau 250 Euro gelten noch als Kleinbetrag (§ 33 UStDV).
- Die Aufbewahrungsfrist endet am Jahresende plus acht Jahre.
- Der Versandnachweis entsteht vor der Mail, nicht danach; SMTP-Verbindungen
  brechen nach 30 Sekunden ab, statt zu hängen.
- Eine Menge von 60 steht im Formular als 60, nicht als `6E+1` (#127).
- Eine Position lässt sich nicht mehr aus einer finalisierten Rechnung
  umhängen (#124).

### Betrieb

- Neue, optionale Umgebungsvariablen: `UEBERGABEN_ORDNER`, `SCHLUESSEL_PFAD`
  (Beleg-Integration), `INSTALLATION_MODE` und `TESTINSTANZ_MAIL_TO`
  (Testinstanz, siehe `docs/INTEGRATION-TESTINSTANZ.md`).
- Feste Gruppen-ID 2000 für den Belegordner, Datenbankpasswörter fail-closed (#68).
- Abbild auf aktuellem Debian-Sicherheitsstand (Ghostscript, curl) (#77, #151).
- Der Testläufer räumt sein Wegwerf-Volume weg (#100).
- Innerer Umbau ohne sichtbare Änderung: Rechnungs-Router, Prüfung, XML- und
  PDF-Erzeugung und die Belegsprache sind in kleinere Module geteilt. Erzeugte
  XML und PDF bleiben gleich (#161).

## v1.0.1 (2026-08-12)

- Geldbeträge stehen auch in der Oberfläche im deutschen Format (2.501,38 EUR).
- Eine Menge wie 120 stand im PDF als `1.2E+2`; jetzt steht dort 120.
- Vorlagen für Issues und Pull Requests.

## v1.0.0 (2026-08-11)

Erste veröffentlichte Fassung.
