# Abgehakt

Rechnungsprogramm für **E-Rechnungen nach ZUGFeRD/Factur-X (EN 16931)** mit einem Archiv, das
gestellte Rechnungen unveränderlich aufbewahrt. Läuft lokal auf dem eigenen Rechner oder
Server: keine Cloud, kein Konto, keine Übertragung von Rechnungsdaten an Dritte.

Eine erzeugte Rechnung ist ein PDF/A-3 mit eingebetteter, maschinenlesbarer XML: für Menschen
lesbar und für die Buchhaltungssoftware des Empfängers auswertbar, in einer Datei.

## Warum es das gibt

Mein Steuerberater hat mir von der E-Rechnungspflicht erzählt. Ich habe daraufhin nach einem
fertigen Programm gesucht, das Rechnungen offline auf dem eigenen Rechner erstellt, und keines
gefunden, das gepasst hätte. Aus dieser Handlungsnot ist Abgehakt entstanden.

Es hilft mir seitdem dabei, korrekte Rechnungen zu erstellen und sie an meine Kunden und an
das DATEV-Postfach zu versenden. Über jede Unterstützung freue ich mich.

Ich behalte mir vor, diesen Code als Kern einer größeren Anwendung zu verwenden, die
möglicherweise kommerziell vertrieben wird. Dieser Teil hier bleibt in jedem Fall frei. Ich
hoffe, er löst ein drängendes Problem.

## Rechtlicher Rahmen

- **§ 14 UStG** regelt die Pflichtangaben einer Rechnung. Das Programm prüft sie regelbasiert
  vor dem Finalisieren; fehlt eine Pflichtangabe, entsteht kein Beleg.
- **EN 16931** ist die europäische Norm für die elektronische Rechnung. ZUGFeRD/Factur-X ab
  Profil `EN16931` erfüllt sie. Die schwächeren Profile `MINIMUM` und `BASIC-WL` erfüllen sie
  **nicht** und werden von diesem Programm nicht erzeugt.
- **Seit 01.01.2025** hat bei einer E-Rechnung der XML-Teil rechtlich Vorrang vor dem
  sichtbaren PDF, und Unternehmen müssen E-Rechnungen **empfangen** können.
- **Ab 01.01.2027** müssen Aussteller mit mehr als 800.000 € Vorjahresumsatz im B2B
  E-Rechnungen senden, **ab 01.01.2028** alle. Ausnahmen bleiben unter anderem für
  Kleinbeträge bis 250 €, Fahrausweise, Kleinunternehmer nach § 34a UStDV und B2C.
- **Aufbewahrung:** acht Jahre nach § 14b UStG in der Fassung des Vierten
  Bürokratieentlastungsgesetzes. Das Programm setzt die Frist automatisch und sperrt das
  Löschen und das nachträgliche Ändern von Belegen (wie weit diese Sperren reichen, steht
  unter „Gewährleistung und Haftung").

Das ist eine Einordnung, keine Rechts- oder Steuerberatung.

## Was GoBD bedeutet, und warum hier kein Siegel steht

Die **GoBD** sind die Regeln des Bundesfinanzministeriums dafür, wie steuerlich relevante
Unterlagen geführt und aufbewahrt werden müssen: nachvollziehbar, vollständig, richtig,
zeitgerecht, geordnet und **unveränderbar**. Sie sind kein Gesetz mit eigenen Paragraphen,
sondern die Auslegung dessen, was §§ 145 bis 147 AO und § 14b UStG ohnehin verlangen.

Warum das zählt: Wer bei einer Betriebsprüfung nicht belegen kann, dass eine gestellte
Rechnung seit ihrer Erstellung unverändert ist, riskiert, dass die Buchführung verworfen und
der Gewinn geschätzt wird. Es geht nicht um ein Formblatt, sondern um die Beweiskraft der
eigenen Aufzeichnungen.

**Kein Programm kann GoBD-Konformität allein herstellen.** Sie ist eine Eigenschaft des
Verfahrens: Software plus Organisation plus eine Verfahrensdokumentation, die beschreibt, wie
im Betrieb tatsächlich gearbeitet wird, plus eine Sicherung, die auch schon einmal
zurückgespielt wurde. Deshalb steht in dieser Oberfläche **kein GoBD-Siegel**. Ein Abzeichen,
das auf jedem Bildschirm „konform" behauptet, verleitet dazu, sich darauf zu verlassen statt
auf ein Verfahren, und es wäre eine Zusage, die niemand einlösen kann.

Was das Programm dafür beiträgt:

- Gestellte Rechnungen lassen sich **nicht mehr ändern und nicht löschen**. Das erzwingen
  Wächter in der Anwendung und zusätzlich Auslöser in der Datenbank, die auch bei direktem
  Zugriff über `psql` greifen. Eine Korrektur läuft über eine Stornorechnung, nicht über eine
  Änderung.
- Jede Änderung an Rechnungen, Kunden und Firmendaten landet automatisch im
  **Änderungsprotokoll**. Für die einzelnen Rechnungspositionen führt das Programm kein
  eigenes Protokoll: Sobald eine Rechnung gestellt ist, lassen sich ihre Positionen
  überhaupt nicht mehr ändern, weder einzeln noch im Ganzen.
- Die **Aufbewahrungsfrist** wird bei jedem Beleg auf acht Jahre gesetzt.
- Der **Datenexport für die Betriebsprüfung** (Z3) liefert auf Knopfdruck ein Archiv mit den
  Belegen, den Stammdaten und dem Änderungsprotokoll für einen gewählten Zeitraum.
- Verworfene Entwürfe bleiben als Datensatz erhalten, damit eine **Lücke in der
  Rechnungsnummer** später erklärbar ist.

Was Sie selbst beitragen müssen: eine **Verfahrensdokumentation** (das Programm bringt keine
mit), eine **geprüfte Sicherung** samt einmal durchgespielter Rücksicherung, und die
Entscheidung, wo die Sicherung liegt. Siehe „Sicherung und Rücksicherung" sowie „Grenzen,
ehrlich benannt".

## Voraussetzungen

- Docker und Docker Compose
- 4 GB RAM Minimum, 8 GB empfohlen
- 2 Prozessorkerne Minimum, 4 empfohlen
- rund 1,5 GB Plattenplatz für das Image (Java-Laufzeitumgebung, Ghostscript, Mustang)

Das Programm selbst ist klein und braucht im Betrieb gut 100 MB Arbeitsspeicher. Alles
Weitere geht auf die Werkzeugkette für das Dateiformat: die XML wird von Ghostscript und
Mustang ins PDF eingebettet und anschließend von Mustang gegen Schema und Schematron
geprüft. Mustang ist die Referenzimplementierung für ZUGFeRD und läuft in einer
Java-Laufzeitumgebung; jedes Finalisieren startet sie zweimal und dauert deshalb auf einer
ruhigen Maschine rund zehn Sekunden. Das ist der Preis dafür, die Prüfung nicht selbst zu
schreiben und sich damit die eigenen Hausaufgaben zu benoten.

Ist die Maschine stark belastet, kann diese Prüfung in eine Zeitgrenze laufen. Dann bleibt
die Rechnung **Entwurf** und lässt sich erneut finalisieren; es entsteht kein halbfertiger
Beleg und es geht nichts verloren.

## Installation

Vier Schritte, danach läuft es.

**1. Docker installieren.** [Docker Desktop](https://www.docker.com/products/docker-desktop/)
für Windows oder macOS, auf einem Linux-Server Docker Engine mit dem Compose-Zusatz. Docker
muss laufen, bevor es weitergeht.

**2. Das Programm holen.** Auf der Seite
[Releases](https://github.com/abgehakt-zugferd/abgehakt-e-rechnung/releases) das Archiv
`Source code (zip)` der obersten Fassung herunterladen und entpacken. Wer Git benutzt, klont
stattdessen und wechselt auf den Versionsstand:

```bash
git clone https://github.com/abgehakt-zugferd/abgehakt-e-rechnung.git
cd abgehakt-e-rechnung && git checkout v1.0.1
```

Ohne Release-Archiv und ohne Tag (also direkt vom Hauptzweig) bekommt man einen
Zwischenstand: der kann Fehler enthalten, die in keiner veröffentlichten Fassung stehen.

**3. Passwörter setzen.** Im entpackten Verzeichnis:

```bash
cp .env.example .env
```

Dann `.env` in einem Texteditor öffnen und die **drei Datenbankpasswörter** ersetzen
(`DB_BOOTSTRAP_PASSWORD`, `DB_PASSWORD`, `DB_APP_PASSWORD`). Frei erfundene, lange
Zeichenketten genügen; sie werden nirgends eingetippt.

**Das dritte Passwort steht zweimal in der Datei** und muss an beiden Stellen gleich lauten:
einmal hinter `DB_APP_PASSWORD=`, und ein zweites Mal innerhalb der langen Adresse in der
Zeile darunter, zwischen dem Doppelpunkt und dem `@`:

```
DB_APP_PASSWORD=xB7kq2LmPw9dRt4v
APP_DATABASE_URL=postgresql://abgehakt_app:xB7kq2LmPw9dRt4v@db:5432/abgehakt
                                          ^^^^^^^^^^^^^^^^ dasselbe Passwort
```

Alles Weitere in dieser Datei ist optional und lässt sich später in der Oberfläche einstellen.
Die Datenbankrollen legt das Programm beim ersten Start selbst an.

**Diese Datei ist ab jetzt Teil Ihres Bestandes.** Sie gehört in jede Sicherung (siehe
*Sicherung und Rücksicherung*) und darf nicht gelöscht werden. Die drei Passwörter stehen
nirgendwo sonst: Das Programm legt die Datenbankrollen beim ersten Start damit an, und ohne die
Datei kommt weder das Programm noch Sie selbst an die eigenen Belege heran. Dass Schlüssel und
E-Mail-Einstellungen ausdrücklich **nicht** hier stehen, sondern in `storage/secret.key` und in
der Datenbank, ändert daran nichts.

**Nur auf einem Linux-Server:** Das Programm läuft im Container unter einem eigenen
Systembenutzer und schreibt Belege und Schlüssel nach `storage/`. Dieses Verzeichnis gehört
nach dem Entpacken dem angemeldeten Menschen, nicht jenem Benutzer. Deshalb einmalig:

```bash
sudo chown -R 100:101 storage
```

Auf Windows und macOS entfällt das, dort regelt Docker Desktop die Zuordnung selbst. Wird es
auf einem Linux-Server vergessen, startet das Programm nicht und nennt in
`docker compose logs app` genau diese Zeile.

**4. Starten.**

```bash
docker compose up -d --build
```

Der erste Bau dauert 5 bis 10 Minuten: Java-Laufzeitumgebung, Mustang-JAR (mit Prüfsumme),
Ghostscript und die Python-Abhängigkeiten werden geholt. Bei jedem weiteren Start entfällt das.

Der Befehl kehrt zurück, sobald die Container gestartet sind; das Programm selbst braucht danach
noch einen Moment. Woran Sie erkennen, dass es bereit ist:

```bash
docker compose ps
```

Steht bei `abgehakt_app` in der Spalte `STATUS` der Zusatz `(healthy)`, läuft alles. Bleibt dort
`(starting)` oder `(unhealthy)` stehen, zeigt `docker compose logs app` den Grund; die letzte
Zeile nennt ihn im Klartext.

### Auf eine neue Fassung wechseln

Zuerst sichern (siehe unten), dann den neuen Stand holen und neu bauen:

```bash
git fetch --tags
git checkout v1.2.3
docker compose up -d --build
```

`git pull` funktioniert hier nicht: Schritt 2 der Installation setzt Sie mit `git checkout`
auf einen Versionsstand statt auf einen Zweig, und `git pull` bricht dort mit *You are not
currently on a branch* ab. Wer das Archiv statt Git benutzt, entpackt das neue daneben und
übernimmt `.env`, `storage/` und `backups/` aus der alten Installation.

`--build` ist nicht optional: Der Dienst `app` wird aus dem Quelltext gebaut, es gibt kein
fertiges Abbild zum Herunterladen. Ein `docker compose pull` überspringt ihn deshalb wortlos
und meldet trotzdem Erfolg, während die alte Fassung weiterläuft.

Die Datenbank bleibt liegen, ausstehende Schemaänderungen führt der Start selbst aus.
Dieselbe Anleitung steht im Programm unter *Nach Updates suchen*.

## Ersteinrichtung

Ab hier arbeiten Sie nicht mehr im Terminal, sondern im **Webbrowser**: Öffnen Sie Chrome,
Firefox, Safari oder Edge und geben Sie **http://localhost:3000** in die Adresszeile ein. Das
Programm läuft auf Ihrem eigenen Rechner; die Adresse führt nicht ins Internet, sondern zum
gerade gestarteten Container.

Der erste Aufruf führt auf `/setup`. Ohne vollständige Firmendaten (Name, Anschrift und Steuernummer **oder** USt-IdNr.)
bleibt die Rechnungserstellung gesperrt: eine Rechnung ohne diese Angaben wäre nach § 14 UStG
fehlerhaft.

> **Das Programm hat keine Anmeldung, und das ist Absicht.** Es ist ein Werkzeug für einen
> Rechner, kein Dienst für mehrere Personen. Wer die Oberfläche erreicht, kann alles: Rechnungen
> ansehen, neue anlegen, versenden und den Datenexport mit sämtlichen Kundendaten herunterladen.
> Deshalb ist Port 3000 ab Werk **nur vom eigenen Rechner aus erreichbar** (`127.0.0.1:3000:3000`
> in `docker-compose.yml`). Ändern Sie diese Zeile nicht, um "mal eben vom Tablet" darauf zuzugreifen:
> im Hotel-WLAN oder im offenen Büronetz liegt Ihre Buchhaltung dann für alle offen. Wer den
> Zugriff aus dem Netz wirklich braucht, stellt eine Anmeldung davor, etwa einen Reverse Proxy
> mit Passwortschutz oder ein VPN.

## Tägliche Arbeit

Wie mit dem Programm gearbeitet wird, steht in [docs/ANWENDUNG.md](docs/ANWENDUNG.md): der
Lebenslauf eines Belegs vom Entwurf bis zum Archiv, und ausführlich der Fall, der die meisten
Rückfragen erzeugt, nämlich die **Korrektur einer bereits gestellten Rechnung**. Kurz gefasst:
Ein gestellter Beleg wird nie geändert, sondern durch eine Gutschrift aufgehoben und
gegebenenfalls neu geschrieben.

## Tests

```bash
backend/run-tests.sh
```

Das Skript baut das Abbild samt Testwerkzeug, baut das Auslieferungsabbild als Bauprobe
daneben und startet eine Wegwerf-Datenbank dazu, damit nichts übersprungen wird. Übersprungene
Tests gelten als Fehler. Sonst würde ein fehlendes Werkzeug im Container den rechtlich
kritischen E-Rechnungs-Pfad unbemerkt verbergen.

Der Stack aus `docker compose up` enthält kein pytest. Er baut das Abbild, das ausgeliefert
wird, und darin hat Testwerkzeug nichts zu suchen. Wer die Suite gegen einen laufenden
Container fahren will, startet den Entwicklungsstack, siehe [CONTRIBUTING.md](CONTRIBUTING.md).

## Sicherung und Rücksicherung

Drei Dinge müssen gesichert werden, und sie liegen an verschiedenen Orten:

- **Datenbank.** Ein Dienst im Compose-Stack legt täglich einen `pg_dump` nach `./backups/`
  (30 Tage, 8 Wochen, 12 Monate). Sofortige Sicherung:
  `docker compose exec db-backup /backup.sh`
- **`storage/`.** Die PDF- und XML-Belege sowie `secret.key`, mit dem verschlüsselte
  Einstellungen gelesen werden. Ohne diesen Schlüssel sind sie verloren.
- **`.env`.** Die Datei aus Schritt 3 der Installation. Sie ist die einzige Stelle, an der die
  drei Datenbankpasswörter stehen, und die Datenbank kennt keine zweite Möglichkeit, Sie
  hereinzulassen. Ohne sie lässt sich die Rücksicherung weiter unten nicht ausführen, denn
  jeder Befehl dort beginnt mit `. ./.env`.

Die ersten beiden gehören zusammen und müssen vom **selben Zeitpunkt** stammen. Die Datenbank
kennt zu jeder Rechnung einen Dateinamen; liegt die zugehörige PDF nicht in `storage/`, ist der
Beleg weg, auch wenn der Datensatz noch da ist. Die `.env` ändert sich dagegen fast nie; sie
muss nur vorhanden und dieselbe sein.

Eine Warnung, die in der Praxis öfter greift als jeder Festplattenschaden: Werkzeuge und
Aufräumbefehle, die „nicht versionierte Dateien entfernen" anbieten, löschen `.env` mit, weil
sie bewusst nicht im Repository liegt. `git clean -xdf` ist der bekannteste. Der laufende
Stack merkt davon nichts und arbeitet weiter; sichtbar wird der Verlust erst beim nächsten
Neustart, und dann steht das Programm.

### Die Rücksicherung einmal durchspielen, bevor Sie sie brauchen

Eine Sicherung, die nie zurückgespielt wurde, ist eine Vermutung. Der Notfall ist der
schlechteste Zeitpunkt, das erste Mal herauszufinden, ob sie taugt. Die folgende Probe
dauert wenige Minuten und läuft in einer **zweiten, weggeworfenen Datenbank**: Ihr echter
Bestand wird dabei nicht angefasst.

```bash
set -a; . ./.env; set +a          # Zugangsdaten aus der .env in die Sitzung laden

# 1. Sicherung von jetzt erzeugen
docker compose exec db-backup /backup.sh

# 2. Wegwerf-Datenbank anlegen
docker compose exec -T db createdb -U "$DB_BOOTSTRAP_USER" abgehakt_probe

# 3. Einspielen. ON_ERROR_STOP=1 ist der wichtigste Teil (Begründung unten)
gunzip -c backups/last/abgehakt-latest.sql.gz \
  | docker compose exec -T db psql -q -v ON_ERROR_STOP=1 -U "$DB_BOOTSTRAP_USER" -d abgehakt_probe

# 4. Nachzählen. Die Zahlen müssen zu Ihrem Bestand passen
docker compose exec -T db psql -U "$DB_BOOTSTRAP_USER" -d abgehakt_probe \
  -c "SELECT (SELECT count(*) FROM invoices) AS rechnungen, (SELECT count(*) FROM customers) AS kunden;"

# 5. Probe wieder entfernen
docker compose exec -T db dropdb -U "$DB_BOOTSTRAP_USER" abgehakt_probe
```

Sagt Schritt 4 dieselben Zahlen wie Ihre Oberfläche, ist die Sicherung nachweislich
brauchbar. Prüfen Sie zusätzlich, ob zu einer Handvoll Rechnungsnummern aus der Liste auch
die Dateien in `storage/pdfs/` liegen. Wiederholen Sie die Probe, wenn sich etwas an der
Einrichtung ändert, mindestens aber einmal im Jahr.

### Warum in eine zweite Datenbank und warum `ON_ERROR_STOP`

Eine Sicherung in eine Datenbank zu spielen, in der schon Tabellen stehen, funktioniert
**nicht**, sieht aber danach aus. `psql` läuft dann durch eine Reihe von Meldungen der Art
`relation "invoices" already exists`, überspringt sie, lässt die vorhandenen Daten
unverändert stehen und endet trotzdem mit Rückgabewert 0, also mit „erfolgreich". Wer im
Ernstfall so vorgeht, hält seine Wiederherstellung für gelungen und arbeitet auf dem alten
Stand weiter. Mit `-v ON_ERROR_STOP=1` bricht `psql` beim ersten Fehler ab und meldet ihn.

### Im Ernstfall

Die Rücksicherung braucht eine **leere** Datenbank. Wenn die vorhandene ersetzt werden soll,
wird sie verworfen und neu angelegt; die Schutzauslöser in der Datenbank verhindern nur das
Löschen einzelner Zeilen, nicht das Verwerfen der Datenbank selbst.

```bash
docker compose stop app                                     # niemand schreibt mehr hinein
docker compose exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" | gzip > vorher.sql.gz
docker compose exec -T db dropdb   -U "$DB_BOOTSTRAP_USER" "$DB_NAME"
docker compose exec -T db createdb -U "$DB_BOOTSTRAP_USER" "$DB_NAME"
gunzip -c backups/last/abgehakt-latest.sql.gz \
  | docker compose exec -T db psql -q -v ON_ERROR_STOP=1 -U "$DB_BOOTSTRAP_USER" -d "$DB_NAME"
docker compose start app
```

Die Zeile mit `vorher.sql.gz` sichert den Stand, den Sie gerade überschreiben. Auch ein
beschädigter Stand kann Daten enthalten, die in der Sicherung fehlen.

Danach `storage/` aus derselben Sicherung zurückholen, `secret.key` eingeschlossen.

**Auf einem neuen Rechner** zuerst den Stack mit **derselben `.env`** einmal starten und dann
erst zurücksichern: die Sicherung verweist auf die Datenbankrollen (`abgehakt_app` und die
Eigentümerrolle), und die entstehen beim ersten Start. Mit anderen Namen in der `.env` findet
die Rücksicherung sie nicht.

## Drittkomponenten

| Komponente | Lizenz | Bezug |
|---|---|---|
| Mustang CLI | Apache-2.0 | beim Bauen von Maven Central, SHA-256-geprüft |
| Saxon-HE (in Mustang enthalten) | MPL-2.0 | im JAR |
| Apache FOP, PDFBox (in Mustang enthalten) | Apache-2.0 | im JAR |
| Ghostscript | AGPL-3.0-or-later | Debian-Paket im Image |
| ReportLab | BSD-3-Clause | PyPI |
| PostgreSQL | PostgreSQL License | offizielles Image |
| FastAPI, SQLAlchemy, Alembic | MIT / MIT / MIT | PyPI |
| Tailwind CSS, Alpine.js | MIT | im Image unter `backend/app/static/js/` |
| Press Start 2P, VT323, Share Tech Mono, Staatliches | OFL-1.1 | im Image unter `backend/app/static/fonts/` |

Schriften und JavaScript liegen bewusst im Image: die Oberfläche lädt beim Seitenaufbau nichts
aus dem Netz nach und sieht ohne Internetverbindung genauso aus wie mit.

Die genauen Versionen stehen dort, wo sie gepinnt sind: in `backend/Dockerfile` und
`backend/uv.lock`. Bewusst nicht hier, denn eine Versionsnummer in einer Doku ist eine Kopie,
die niemand prüft.

## Grenzen, ehrlich benannt

- **`storage/` wird nicht atomar mit der Datenbank gesichert.** Datenbank-Dump und Dateiarchiv
  entstehen zu leicht unterschiedlichen Zeitpunkten. Wer produktiv geht, sollte eine
  Rücksicherung einmal vollständig durchgespielt haben, bevor er sie braucht.
- **Kleinunternehmer: Rechnung ja, Umsatzüberwachung nein.** Der Steuertyp
  „Kleinunternehmer (§ 19 UStG)" erzeugt eine vollständige Rechnung ohne Umsatzsteuer,
  mit dem vorgeschriebenen Hinweis auf die Steuerbefreiung auf dem Beleg und in der XML.
  Nicht enthalten ist die Überwachung der Umsatzgrenze: Das Programm sagt Ihnen **nicht**,
  wann Sie die Grenze reißen und in die Regelbesteuerung wechseln müssen. Diesen Wechsel
  müssen Sie selbst im Blick behalten. Der Steuertyp wird pro Rechnung gewählt, es gibt
  keine dauerhafte Einstellung dafür.
- **Nur deutsche Steuersätze.** Zulässig sind 0, 7 und 19 Prozent. Für Kunden im EU-Ausland
  deckt das die üblichen Fälle ab, weil dort in der Regel gar keine deutsche Umsatzsteuer
  anfällt: bei Geschäftskunden mit USt-IdNr. geht die Steuerschuld auf den Empfänger über,
  bei innergemeinschaftlichen Lieferungen ist der Umsatz steuerfrei. Beides kennt das Programm
  als eigenen Steuertyp. **Nicht** abgebildet ist der Fall, in dem Sie ausländische Umsatzsteuer
  ausweisen müssen, etwa 20 Prozent für österreichische Privatkunden. Wer digitale Leistungen
  an Privatpersonen in der EU verkauft und am One-Stop-Shop-Verfahren teilnimmt, kann diese
  Rechnungen hier nicht erstellen.
- **Kein E-Rechnungs-Empfang.** Das Programm erstellt Rechnungen; es liest keine eingehenden
  E-Rechnungen ein.
- **Die Update-Prüfung braucht einen veröffentlichten Release.** Sie vergleicht die eigene
  Version (aus der Datei `backend/VERSION` im Archiv) mit der obersten Fassung auf der
  Releases-Seite. Ein Bau direkt vom Hauptzweig kann deshalb eine Version melden, die es als
  Release noch nicht gibt. Geprüft wird ohnehin nur auf ausdrücklichen Klick und nach
  einmaliger Bestätigung. Im Hintergrund läuft nichts.
- **Kein Mandantenbetrieb.** Eine Installation, eine Firma.
- **Keine Steuerberatung.** Bei Fragen zur eigenen Steuerpflicht hilft nur eine
  Steuerberaterin oder ein Steuerberater.

## Datenschutz

Die Rechnungs- und Kundendaten liegen ausschließlich auf Ihrem Rechner: in der Datenbank des
Compose-Stacks und als Dateien unter `storage/`. Es gibt keine Anmeldung bei einem Dienst,
keine Synchronisierung und keine Nutzungsstatistik. Zugangsdaten für den E-Mail-Versand werden
verschlüsselt abgelegt (Schlüssel: `storage/secret.key`).

Auch die Oberfläche selbst holt nichts von außen: Schriften, das CSS-Werkzeug und die kleine
JavaScript-Bibliothek liegen im Image. Der Aufruf einer Seite erzeugt keine Verbindung zu
einem fremden Server.

Ihre Daten verlassen den Rechner an genau **drei** Stellen, und alle drei stoßen Sie selbst an:

1. **Rechnungsversand.** Die Mail geht an Ihren Kunden, auf Wunsch mit Kopie an die Kanzlei
   und als Blindkopie an die DATEV-Upload-Adresse. Über Ihren eigenen Mailserver.
2. **Update-Prüfung.** Sie ruft die Releases dieses Repos bei GitHub ab. Über Ihre
   Installation wird dabei **nichts** übermittelt: keine Versionsnummer, keine Kennung, keine
   Rechnungs-, Kunden- oder Firmendaten. Der Vergleich mit Ihrer Version passiert danach auf
   Ihrem Rechner. Was GitHub sieht, ist der Abruf selbst, also Ihre IP-Adresse wie bei jedem
   Aufruf einer Webseite. Die Prüfung läuft **nur auf Klick**, nie im Hintergrund und nie beim
   Start, und erst nach einer einmaligen Bestätigung.
3. **GoBD-Export.** Er erzeugt eine Datei auf Ihrem Rechner. Wohin die geht, entscheiden Sie.

Für die Daten Ihrer Kunden sind **Sie** verantwortlich im Sinne der DSGVO, nicht der Autor des
Programms. Dazu gehören die Auskunft an Betroffene, die Zugriffskontrolle auf den Rechner und
die Sicherungen, die ebenfalls personenbezogene Daten enthalten und deshalb nicht offen im
Netz liegen sollten.

## Gewährleistung und Haftung

Das Programm wird **unentgeltlich und ohne Gewähr** überlassen. Was es leistet, steht oben;
hier steht, wofür es nicht einsteht:

- **Richtigkeit der Belege.** Die Prüfung nach § 14 UStG ist regelbasiert: sie findet fehlende
  Pflichtangaben, rechnerische Abweichungen und Widersprüche in den Angaben, etwa ein
  Fälligkeitsdatum vor dem Rechnungsdatum oder eine Reverse-Charge-Rechnung mit ausgewiesener
  Steuer. Sie beurteilt **nicht**, ob ein Sachverhalt steuerlich zutreffend abgebildet ist:
  ob also der ermäßigte Satz anwendbar ist, ob das Reverse-Charge-Verfahren greift, ob eine
  Leistung überhaupt steuerbar ist. Das verantwortet die ausstellende Firma.
- **Steuerliche Beurteilung.** Das Programm ersetzt keine Steuerberatung. Es setzt um, was ihm
  vorgegeben wird.
- **Wie weit die Sperren reichen.** Sie sind unterschiedlich stark, und der Unterschied gehört
  benannt:
  - **Löschen von Belegen und Kunden** ist auf **zwei** Ebenen gesperrt: in der Anwendung und
    durch Trigger in der Datenbank selbst. Die greifen unabhängig davon, wer verbunden ist.
    Auch ein Datenbank-Administrator kommt an einer finalisierten Rechnung nicht vorbei.
  - **Das nachträgliche Ändern** finalisierter Rechnungen ist nur in der **Anwendung**
    gesperrt. Wer die Datenbank direkt mit `psql` bearbeitet, umgeht diese Sperre. Das ist
    eine bewusst in Kauf genommene Restlücke (siehe `docs/ARCHITEKTUR.md`); dagegen stehen das
    Änderungsprotokoll und die Sicherungen, nicht die Datenbank.
- **Sicherung.** Ob gesichert wird, wohin, und ob sich die Sicherung wiederherstellen lässt,
  verantwortet der Betreiber (siehe „Sicherung und Rücksicherung"). Ein Datenträger, den
  niemand sichert, ist auch mit Schreibschutz verloren.

Rechtlich maßgeblich sind die **Abschnitte 15 und 16 der [AGPL-3.0](LICENSE)**. Sie sind
englischsprachig; die Zusammenfassung hier erklärt sie, ersetzt sie aber nicht. Nach deutschem
Recht bleibt es unabhängig davon bei der Haftung für Vorsatz und grobe Fahrlässigkeit sowie
bei den zwingenden gesetzlichen Fällen. Daran ändert kein Lizenztext etwas, und das ist auch
nicht beabsichtigt.

Die begleitete Einrichtung ist eine **gesonderte, entgeltliche Leistung**. Für sie gilt, was
dafür vereinbart wird, nicht dieser Abschnitt.

## Begleitete Einrichtung

Wer das Programm einsetzen möchte, aber nicht selbst mit Docker arbeitet: eine begleitete
Einrichtung ist möglich, also Installation, Sicherung samt einmaliger Rücksicherung und
Einweisung. Umfang, Grenzen und der Datenschutz dabei stehen in [SERVICES.md](SERVICES.md).
Anfragen an **patrick@saleshero.training**.

## Freiwillige Unterstützung

Diese Fassung ist kostenlos und bleibt es, und zwar unter der AGPL-3.0, die niemand
nachträglich zurücknehmen kann. Der Download hängt an keiner Zahlung, es gibt keine Testphase,
keine gesperrte Funktion und keine Erinnerung im Programm. (Dass sich das Projekt eine
zusätzliche, kostenpflichtige Lizenz für Unternehmen offenhält, siehe [CLA.md](CLA.md), ändert
daran nichts: sie käme neben diese Fassung, nicht an ihre Stelle.)

Wer es danach nützlich findet, kann freiwillig etwas geben:

**[Unterstützen über PayPal](https://www.paypal.com/ncp/payment/V7RZ332PL6V68)**

Als Anhaltspunkt: **20 €**, **50 €** oder **100 €**. Jeder andere Betrag ist genauso
willkommen, eingetragen wird er im PayPal-Fenster, das sich über den Link öffnet.

Empfängerin ist die ZEMP Golden Goose GmbH. Die Beträge sind Bruttobeträge und enthalten
19 % Umsatzsteuer; wer eine Rechnung dafür braucht, schreibt eine Mail an
**patrick@saleshero.training** mit Datum und Betrag.

## Mitarbeit

Fehlermeldungen sind willkommen, siehe [CONTRIBUTING.md](CONTRIBUTING.md). Sicherheitslücken
bitte **nicht** als öffentliches Issue melden, sondern nach [SECURITY.md](SECURITY.md).

Technische Einführung für Mitwirkende: [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md).

## Lizenz

Copyright © 2026 ZEMP Golden Goose GmbH, Buchloe.

[AGPL-3.0](LICENSE). Wer das Programm verändert und über ein Netzwerk anderen zugänglich
macht, muss den geänderten Quellcode offenlegen (§ 13 AGPL). Der Hinweis im Seitenfuß ist
deshalb nicht abschaltbar.

Anbieterkennzeichnung: [IMPRESSUM.md](IMPRESSUM.md).
