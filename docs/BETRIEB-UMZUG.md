# Betrieb und Umzug auf einen anderen Rechner

Diese Anleitung richtet sich an Betreiber, die eine bestehende Installation auf einen
anderen Rechner oder eine virtuelle Maschine (Linux, Docker mit Compose) verlegen oder
dort neu aufsetzen. Sie ergänzt die Abschnitte „Sicherung und Rücksicherung" im
[README](../README.md); die dortigen Befehle für Sicherung und Rücksicherung gelten
unverändert.

> **Die Anwendung hat keine Anmeldung.** Wer die Oberfläche erreicht, kann alles:
> Rechnungen ansehen, anlegen, versenden und den GoBD-Export mit allen Kundendaten
> laden (siehe [SECURITY.md](../SECURITY.md)). Sie gehört nur hinter einen Proxy mit
> Anmeldung oder in ein VPN. Ab Werk lauscht sie nur auf `127.0.0.1`.

## 1. Zustand, der umzieht

Fünf Dinge tragen den Zustand einer Installation. Alle fünf gehören zusammen und sollten
vom selben Zeitpunkt stammen (die Datenbank nennt zu jeder Rechnung einen Dateinamen;
fehlt die Datei, ist der Beleg weg).

| Zustand | Im Container | Auf dem Wirt | Besitzer |
|---|---|---|---|
| Datenbank (Volume `postgres_data`) | `/var/lib/postgresql/data` im Dienst `db` | Docker-Volume `<projekt>_postgres_data`, unter Linux meist `/var/lib/docker/volumes/<projekt>_postgres_data/_data` | im Abbild `postgres:16-alpine` uid 70, gid 70 (`postgres`) |
| `./storage` | `/app/storage` im Dienst `app` | `./storage` neben `docker-compose.yml` | uid 100, gid 101 (`appuser:appgroup`, im `backend/Dockerfile` festgelegt) |
| Absenderschlüssel (nur bei Nutzung der Übergabe) | `/app/schluessel` | `./backend/schluessel/` (nicht in Git) | wie die übrigen Dateien im Abbild: uid 100, gid 101; auf dem Wirt der Bau-Benutzer |
| `.env` | wird von Compose gelesen und als `env_file` in den Dienst `app` gereicht | `./.env` neben `docker-compose.yml` (nicht in Git) | der Betreiber; Rechte `600` empfohlen |
| `docker-compose.uebergabe.yml` (optional) | hängt den Übergabeordner unter `/uebergaben/tantiemen-app-nach-abgehakt` ein, nur lesend | Datei im Repository; der Wirtsordner steht in `ZEMP_UEBERGABEN` | der Betreiber |

Zu den einzelnen Punkten:

- **Datenbank.** Sichern mit `docker compose exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME"`
  (Variablen zuvor aus der `.env` laden, Beispiel im README). Das Volume selbst nicht
  kopieren, solange die Datenbank läuft. Auf dem neuen Rechner zuerst den Stack mit
  **derselben `.env`** einmal starten, damit die Datenbankrollen entstehen, und dann in eine
  leere Datenbank einspielen. Das Vorgehen mit `ON_ERROR_STOP` steht im README.
- **`./storage`.** Enthält `pdfs/` (E-Rechnungen als PDF/A-3), `xml/` (zugehörige
  ZUGFeRD-XML), `aufstellungen/` (Abrechnungsaufstellungen), `temp/` (Zwischenstände der
  Belegerzeugung, nicht archivrelevant, kann leer bleiben), `imports/` (vom Abbild
  vorbereitet, derzeit nicht beschrieben) und `secret.key` (Rechte `600`).
  **`secret.key` gehört zur Datenbank:** mit ihm sind gespeicherte Zugangsdaten (etwa das
  SMTP-Passwort) verschlüsselt. Ein neuer Schlüssel macht sie unlesbar. Nach dem Kopieren
  auf dem Zielrechner: `chown -R 100:101 storage`.
- **Absenderschlüssel.** Öffentliche Schlüssel (`<absender>/<schluessel_id>.pub` mit
  Beiblatt `.json`) liegen in `backend/schluessel/`. Sie sind Instanzdaten und
  gehören nicht ins Repository. Der Ordner wird beim **Bau** in das Abbild kopiert; nach dem
  Umzug also zuerst den Ordner an seinen Platz legen, dann `docker compose build`. Wer
  `SCHLUESSEL_PFAD` setzt, hält sie stattdessen außerhalb des Abbilds. Private Schlüssel
  gehören nie hierher.
- **`.env`.** Die einzige Stelle der Datenbankpasswörter und der SMTP-Zugangsdaten. Auf
  einem anderen Weg als die Daten übertragen (nicht per Chat oder unverschlüsselter Mail)
  und nie in Git ablegen.
- **Übergabe-Overlay.** Nur nötig, wenn die Beleg-Übergabe genutzt wird. Auf dem Zielrechner
  `ZEMP_UEBERGABEN` (absoluter Pfad des Wirtsordners) und `COMPOSE_FILE` setzen:
  `COMPOSE_FILE=docker-compose.yml:docker-compose.uebergabe.yml`. Ob die Übergabe aktiv ist,
  steht in der Datenbank und zieht mit ihr um.

Zusätzlich liegen die täglichen Sicherungen des Dienstes `db-backup` in `./backups/` (Host)
bzw. `/backups` (Container). Sie sind eine Sicherung, kein Zustand: sie müssen nicht
mitziehen, aber auf dem neuen Rechner gilt dieselbe Aufbewahrungsüberlegung wie unten.

## 2. Was in die Langzeitaufbewahrung gehört

Zu sichern und aufzubewahren sind:

1. ein **Datenbank-Dump** (ohne ihn sind Zuordnungen, Protokoll und Änderungsverlauf weg),
2. **`storage/pdfs/`** und **`storage/xml/`** (die Belege selbst; bei E-Rechnungen ist die
   XML der maßgebliche Teil),
3. der **GoBD-Export** für den jeweiligen Zeitraum (Oberfläche, Bereich Export;
   Route `/export/gobd`).

Zur Dauer, bewusst vorsichtig und ohne Steuerberatung zu ersetzen:

| Belegklasse | Aufbewahrung mindestens | Grundlage |
|---|---|---|
| Rechnungen (Ausgang und Eingang) | 8 Jahre | § 14b UStG, § 147 AO |
| Bücher und Aufzeichnungen | 10 Jahre | § 147 AO, § 22 UStG, § 257 HGB |

Die Frist beginnt mit dem Ende des Kalenderjahres, in dem der Beleg entstanden ist. Das
Programm setzt bei jedem Beleg `archive_until` auf den 31.12. des Ausstellungsjahres plus
8 Jahre; das gilt nur für Rechnungen. Andere Fristen (etwa Handelsbriefe, laufende
Außenprüfung, Ablaufhemmung) bleiben unberührt. Welche Frist für welche Unterlage gilt und
wie sie bei einem Datenträgerwechsel nachzuweisen ist, klärt der Betreiber mit seiner
Steuerberatung. Aufbewahrte Daten müssen während der gesamten Frist lesbar bleiben:
den Dump gelegentlich in eine Wegwerf-Datenbank einspielen und prüfen.

## 3. Netz nach außen

Im Betrieb kontaktiert die Anwendung diese Ziele (Fundstellen im Code, Stand der Prüfung
per Suche über `backend/Dockerfile` und `backend/app`):

| Ziel | Wofür | Wann | Abschaltbar |
|---|---|---|---|
| SMTP-Server aus `SMTP_HOST`/`SMTP_PORT` (Einstellungen) | Versand von Rechnungen und DATEV-Kopie (`services/datev_email.py`) | nur beim Versand | ja: ohne SMTP-Angaben kein Versand |
| `ec.europa.eu` (VIES, Pfad `/taxation_customs/vies/rest-api/check-vat-number`) | Prüfung von USt-IdNr. (`services/ust_id_pruefung.py`) | nur nach Zustimmung und Klick | nur durch Nichtbenutzen |
| `api.github.com` | Update-Prüfung (`services/update_check.py`) | nur nach Klick auf „Jetzt suchen" | ja: `UPDATE_PRUEFUNG=aus` |

Die Oberfläche lädt keine Schriften oder Skripte von fremden Servern (alles liegt im
Abbild). Der Link zum Quelltext (`github.com`) wird nur vom Browser des Nutzers geöffnet,
nicht von der Anwendung.

Beim **Bau** des Abbilds (`docker compose build`) braucht der Rechner Zugriff auf:

| Ziel | Wofür |
|---|---|
| Docker Hub (`registry-1.docker.io`, `auth.docker.io`, `production.cloudflare.docker.com`) | Basisabbilder `python:3.11-slim`, `postgres:16-alpine`, `prodrigestivill/postgres-backup-local` |
| `ghcr.io` | `uv` (Paketwerkzeug, `COPY --from=ghcr.io/astral-sh/uv`) |
| Debian-Paketquellen (`deb.debian.org`, `security.debian.org`) | `default-jre-headless`, `ghostscript`, `curl` per `apt-get` |
| `repo1.maven.org` (Maven Central) | Mustang-CLI-JAR (Prüfsumme wird im Dockerfile geprüft) |
| `pypi.org` und `files.pythonhosted.org` | Python-Abhängigkeiten laut `backend/uv.lock` |

Läuft der Zielrechner ohne direkten Zugang, bauen Sie das Abbild auf einem Rechner mit
Zugang und übertragen es (`docker save` und `docker load`) oder nutzen einen Mirror.

## 4. Neue Einstellungen für den Betrieb hinter einem Proxy

Alle Werte stehen mit Erklärung in `.env.example`.

| Variable | Vorgabe | Wirkung |
|---|---|---|
| `APP_BIND` | `127.0.0.1` | Adresse, auf der der Port der Anwendung am Wirt lauscht. Läuft der Proxy auf demselben Rechner, bleibt es dabei. `0.0.0.0` hängt die Anwendung ohne Anmeldung an alle Schnittstellen und ist nirgends voreingestellt. |
| `APP_PORT` | `3000` | Port am Wirt (im Container immer 3000) |
| `UPDATE_PRUEFUNG` | `an` | `aus` schaltet die Update-Prüfung ab: kein Knopf, keine Erinnerung, kein Netzabruf; `POST /updates/pruefen` antwortet mit 403 und dem Hinweis „abgeschaltet". Groß- und Kleinschreibung und Leerzeichen am Rand sind egal; ein leerer Wert gilt als `an`; jeder andere Wert (auch ein Tippfehler wie `aus.`) bricht den Start ab. |
| `DB_BIND`, `DB_PORT` | `127.0.0.1`, `5432` | nur mit der Zusatzdatei unten wirksam |

Die Netz-Wache im Pre-Push und in der CI prüft die **Vorgaben der Compose-Dateien**, nicht
den laufenden Betrieb. Ein `APP_BIND=0.0.0.0` in der `.env` des Servers sieht sie nicht. Ob
der Server tatsächlich nur auf Loopback lauscht, misst man dort selbst, etwa mit
`ss -tlnp` oder `docker compose port app 3000`.

### Datenbank-Port

Die Datenbank hat in `docker-compose.yml` **keinen Host-Port**. Die Anwendung erreicht sie
im Compose-Netz (`db:5432`), Dumps laufen per `docker compose exec`. Wer von außen heran
muss (psql, ein GUI-Client), nimmt `docker-compose.db-port.yml` dazu. Sie öffnet den Port
vorgabegemäß nur auf `127.0.0.1`.

```bash
# ohne COMPOSE_FILE in der Umgebung
docker compose -f docker-compose.yml -f docker-compose.db-port.yml up -d

# mit COMPOSE_FILE (etwa zusammen mit dem Übergabe-Overlay): die Datei anhängen
COMPOSE_FILE=docker-compose.yml:docker-compose.uebergabe.yml:docker-compose.db-port.yml
```

Ein `-f` auf der Kommandozeile ersetzt `COMPOSE_FILE` vollständig; dann alle Dateien mit
`-f` nennen. Die Ketten-Testinstanz (`docker-compose.integration.yml`) setzt ihren eigenen
DB-Port 5433 und ist davon unberührt.

### Gesundheitsroute

`GET /gesundheit` liefert `{"status": "ok"}` (200), wenn eine Abfrage `SELECT 1` gegen die
Datenbank gelingt, sonst 503 mit `{"status": "db_nicht_erreichbar"}` ohne Fehlertext. Sie
gibt keine Daten aus, braucht keine Anmeldung und wird nicht auf `/setup` umgeleitet. Der
Healthcheck des Dienstes `app` in `docker-compose.yml` ruft sie auf; ein Proxy oder
Monitor kann sie ebenso nutzen. Die Ursache eines 503 steht im Log (`docker compose logs app`).

### Testdaten für eine Test-VM

`backend/scripts/seed_testdaten.py` legt erfundene Daten an: eine Firma (nur wenn keine
eingerichtete existiert), zwei Kunden (einen deutschen, einen österreichischen mit
Platzhalter-USt-IdNr.) und zwei Rechnungsentwürfe mit Positionen.

**Vorher die Anwendung stoppen.** Der Schutz des Skripts prüft zuerst, ob schon Daten da
sind, und schreibt erst danach. Legt jemand in der Oberfläche gleichzeitig einen Kunden
an, ist diese Lücke offen, und beide Wege vergeben Rechnungsnummern. Deshalb läuft das
Skript in einem eigenen, kurzlebigen Container, während der Dienst `app` steht (die
Datenbank muss laufen):

```bash
docker compose stop app
docker compose run --rm app python -m scripts.seed_testdaten                  # nur Entwürfe
docker compose run --rm app python -m scripts.seed_testdaten --finalisieren   # auch als E-Rechnung stellen
docker compose start app
```

Mit `--finalisieren` laufen die Entwürfe durch den normalen Dienstweg: PDF/A-3 mit
eingebetteter XML, Mustang-Prüfung, Ablage in `storage/pdfs` und `storage/xml`.
Enthält die Datenbank schon Kunden, Rechnungen oder eine Firma mit irgendeinem belegten
Feld (auch bei leerem Namen oder wenn die Einrichtung nicht abgeschlossen ist), bricht das Skript ab und schreibt nichts;
`--erzwingen` hebt den Schutz auf, eine eingerichtete Firma bleibt auch dann unberührt.
**Nicht in einer Live-Installation ausführen:** finalisierte Rechnungen sind
unveränderlich und verbrauchen Rechnungsnummern.

## 5. Checkliste für den Umzug

1. Auf dem Altsystem: `docker compose stop app`, dann Dump, `storage/`, `.env` und
   gegebenenfalls `backend/schluessel/` sichern (Abschnitt 1).
2. Auf dem Zielrechner: Repository auf denselben Stand bringen, `.env`, `storage/` und
   Schlüsselordner einspielen, `chown -R 100:101 storage`.
3. `APP_BIND`, `APP_PORT`, gegebenenfalls `UPDATE_PRUEFUNG=aus` in der `.env` setzen.
4. `docker compose up -d --build`, danach `curl -f http://127.0.0.1:3000/gesundheit`.
5. Dump in eine leere Datenbank einspielen (Vorgehen im README), `docker compose start app`.
6. Proxy mit Anmeldung davorsetzen, bevor irgendjemand die Adresse nutzt.
7. Stichprobe: Rechnungsliste mit der Zählung im Altsystem vergleichen, einige PDFs öffnen.
