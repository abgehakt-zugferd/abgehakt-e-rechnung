# Architektur und verbindliche Regeln

Dieses Dokument ist der Einstieg für alle, die am Code arbeiten. Es beschreibt den Aufbau
und, wichtiger, die Regeln, die **nicht** gebrochen werden dürfen, weil hinter ihnen
Aufbewahrungs- und Steuerpflichten stehen und nicht Geschmack.

Nicht offensichtliche technische Erkenntnisse (Bibliotheks-Eigenheiten, Reihenfolge-Zwänge,
Umgebungsfallen) stehen in [`DEV-DOCU.md`](DEV-DOCU.md). Hier stehen die fachlichen Regeln
und die Zeiger dorthin.

## Was das Programm tut

Es erstellt Ausgangsrechnungen als **ZUGFeRD/Factur-X nach EN 16931**, also ein PDF/A-3 mit
eingebetteter, maschinenlesbarer XML, und bewahrt sie GoBD-konform auf. Es läuft lokal,
ohne Cloud, und hält seine Daten in einer PostgreSQL-Datenbank plus einem
Dateiarchiv (`storage/`).

## Tech-Stack

- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2.0, Alembic
- **Datenbank:** PostgreSQL (Docker), kein SQLite
- **ZUGFeRD:** Mustang CLI (Java), im Container unter `/app/lib/Mustang-CLI.jar`
- **PDF:** ReportLab erzeugt das sichtbare PDF, Ghostscript hebt es auf PDF/A-3,
  Mustang bettet die XML ein
- **Frontend:** Jinja2-Templates + Tailwind + Alpine.js, kein Build-Schritt. Beide Bündel
  liegen im Image (`app/static/js/`), ebenso die Schriften (`app/static/fonts/`): die
  Oberfläche lädt beim Seitenaufbau nichts aus dem Netz nach.
- **Betrieb:** Docker Compose

**Hier stehen bewusst keine Versionsnummern.** Jede Nummer in einer Doku ist eine Kopie, die
niemand prüft, und sie driftet. Genau eine Quelle je Sache, jede mit einem Gate, das den Bau
abbricht, wenn sie nicht stimmt:

| Was | Quelle der Wahrheit | Was Drift verhindert |
|---|---|---|
| Mustang CLI | `backend/Dockerfile` (`ARG MUSTANG_VERSION` + `MUSTANG_SHA256`) | `sha256sum -c` bricht den Bau ab |
| Basis-Image, JRE, Ghostscript | `backend/Dockerfile` (`FROM …@sha256:…`) | Digest-Pin |
| Python-Pakete | `backend/pyproject.toml` + `backend/uv.lock` | `uv sync --locked` im Dockerfile |
| Programmversion | `backend/VERSION` → `settings.app_version` (`--build-arg APP_VERSION` sticht sie) | `.github/workflows/release.yml` vergleicht Datei und Tag |
| Datenbankschema | `backend/alembic/versions/` | `alembic upgrade head` |

## Aufbau

```
backend/app/
├── main.py                   # FastAPI-App, Startseite, Registrierung der Guards
├── config.py                 # Einstellungen aus .env (pydantic-settings)
├── database.py               # SQLAlchemy-Engine + get_db()
├── branding.py               # AGPL-§13-Hinweis im Footer (nicht abschaltbar)
├── db/
│   ├── roles.py              # Owner-/App-Rolle provisionieren
│   └── immutability_triggers.py  # GoBD-Trigger, einzige Quelle dieser DDL
├── models/                   # ORM-Modelle
│   ├── company.py            # eigene Firma (Singleton id=1)
│   ├── customer.py           # Kundenstamm
│   ├── invoice.py            # Invoice, InvoiceItem, ValidationResult, AuditLog
│   └── app_config.py         # Betriebseinstellungen (Singleton id=1)
├── routers/                  # HTTP-Handler
│   ├── setup.py              # Ersteinrichtung, Tor vor allem anderen
│   ├── customers.py
│   ├── invoices.py           # anlegen, bearbeiten, prüfen, finalisieren, senden
│   ├── export.py             # GoBD-Datenexport (Z3)
│   ├── archive.py            # Archivansicht storage/{pdfs,xml}
│   ├── updates.py            # Update-Hinweis (nur auf Klick)
│   └── settings.py           # Firmendaten, SMTP-Test
├── services/                 # Fachlogik, framework-unabhängig
│   ├── zugferd_xml.py        # CII-XML nach EN 16931
│   ├── pdf_generator.py      # sichtbares PDF (ReportLab)
│   ├── pdf_fonts.py          # Schriften registrieren; ohne Einbettung kein PDF/A-3
│   ├── pdfa.py               # PDF/A-3 via Ghostscript
│   ├── mustang.py            # Mustang-CLI als Subprozess
│   ├── validator.py          # § 14 UStG, regelbasiert
│   ├── invoice_number.py     # fortlaufende Nummern
│   ├── customer_number.py    # Vorschlag für Kundennummern, überschreibbar
│   ├── storno.py             # Gutschrift zum Original (TypeCode 381), reine Logik
│   ├── audit.py              # automatisches Audit-Log über Session-Events
│   ├── aenderungsprotokoll.py  # dasselbe Log, als lesbare Sätze für die Oberfläche
│   ├── invoice_guard.py      # Statusmaschine + Unveränderlichkeit
│   ├── customer_guard.py     # kein Hard-Delete von Kunden
│   ├── gobd_export.py        # ZIP-Export (CSV + Belege + Audit-Log)
│   ├── datev_email.py        # SMTP-Versand + DATEV-BCC
│   ├── crypto.py             # verschlüsselt Secrets in der Datenbank (SMTP-Passwort)
│   ├── secret_key.py         # Schlüssel dafür, als Datei im storage-Volume
│   ├── update_check.py       # Versionsabruf, ausschließlich auf Klick
│   └── update_banner.py      # was daraus im Seitenkopf erscheint, rein und testbar
├── dependencies/             # was jede Route braucht
│   └── update_banner_dep.py  # legt den Hinweis auf request.state, fängt jeden Fehler
├── static/                   # Schriften und JavaScript, lokal ausgeliefert, kein CDN
├── assets/                   # Schriftdateien für das PDF
└── templates/                # Jinja2
```

Laufzeitdaten liegen unter `storage/{pdfs,xml,temp}/`, als Docker-Volume und nicht im Repo.

## Kritische Regeln, niemals brechen

### Aufbewahrung (GoBD, 8 Jahre nach § 14b UStG i. d. F. BEG IV ab 2025)

- Rechnungen (`invoices`) werden **nie hart gelöscht**, nur der Status wird gesetzt.
- Kunden (`customers`) werden **nie hart gelöscht**, gesetzt wird nur `deleted_at`.
- Finalisierte Rechnungen (`issued`/`paid`/`cancelled`) sind **unveränderlich**.
- `archive_until` ist immer `issue_date` + 8 Jahre. Ändert sich das Rechnungsdatum, muss die
  Frist mitwandern (`_apply_totals`), sonst driftet sie gegen den Beleg.
- Der Betriebsprüfungs-Export (Z3) liegt unter `GET /export/gobd?von=…&bis=…`.
- Das Audit-Log füllt sich automatisch über Session-Events (`services/audit.py`, registriert
  in `main.py`). **Nie von Hand hineinschreiben.**

### Zwei Verteidigungslinien, nicht eine

**Erste Linie: Guards auf Session-Ebene** (`before_flush`, in `main.py` registriert **vor**
dem Audit-Listener). Sie greifen auf **jeder** Session, ob Web, Skript oder Shell; kein
Codepfad kommt daran vorbei. Die Reihenfolge Guards → Audit ist Pflicht, sonst schreibt das
Audit-Log Einträge für einen Flush, der anschließend abbricht.

- `services/invoice_guard.py`: Statusmaschine, Hard-Delete-Verbot, Unveränderlichkeit
  finalisierter Rechnungen (nur `status`, `datev_sent_at`, `updated_at` dürfen sich noch
  ändern). Deckt **auch `InvoiceItem`** ab: Positionen finalisierter Rechnungen lassen sich
  nicht ändern, löschen oder nachschieben. In derselben Transaktion neu erzeugte Rechnungen
  (Storno-Muster) bleiben frei befüllbar. `audit.py` auditiert `InvoiceItem` bewusst
  **nicht**; hier ist der Guard die einzige Verteidigung.
- `services/customer_guard.py`: Hard-Delete verboten, Bearbeiten erlaubt.

**Zweite Linie: Datenbank-Trigger.** `BEFORE DELETE`/`BEFORE TRUNCATE` auf `invoices` und
`customers` (plus `TRUNCATE` auf `invoice_items`) blocken rollenunabhängig, auch bei einem
manuellen `psql` als Eigentümer. Die DDL steht **nur** in
`app/db/immutability_triggers.py`; die Migration führt sie von dort aus. Die Anwendung selbst
läuft als Rolle mit geringstem Recht (`APP_DATABASE_URL`, fail-closed) und hat auf den
geschützten Tabellen kein DELETE und kein TRUNCATE. Die UPDATE-Statusmaschine bleibt
ORM-seitig: eine bewusst dokumentierte Restlücke, abgesichert über Audit-Log und Backups.

Rollen und ihre Aufgaben: siehe [`DEV-DOCU.md`](DEV-DOCU.md), Abschnitt „Rollen-Topologie".

### Finalisieren ist fail-closed

`POST /invoices/{id}/finalisieren` läuft **zuerst** durch `validator.validate_invoice`. Harte
§-14-Fehler (fehlende Positionen, falsche Summen) ⇒ `400`, kein Statuswechsel, keine Dateien.
Ein rechtswidriger Entwurf kommt so nicht ins Archiv.

Danach gilt: `issued` wird **nur** gesetzt, wenn die ZUGFeRD-XML wirklich ins PDF eingebettet
werden konnte (PDF/A-3 über Ghostscript **und** `mustang.combine` erfolgreich). Schlägt das
fehl, bleibt die Rechnung `draft`, es gibt `400`, alle Zwischen-PDFs werden entfernt und die
Transaktion wird zurückgerollt. **Es gibt keinen Rückfall auf ein reines Sicht-PDF.** Das
würde eine unvollständige E-Rechnung zementieren. Als zusätzliche Absicherung verweigert
`POST /datev-senden` jedes `*_visual.pdf`.

### ZUGFeRD

- Die Profile `MINIMUM` und `BASIC-WL` sind **nicht rechtskonform**, es gilt immer mindestens
  `EN16931`. Kein stiller Fallback auf ein schwächeres Profil.
- Seit 01.01.2025 hat der XML-Teil rechtlich **Vorrang** vor dem sichtbaren PDF.
- Die XML wird in `invoices.zugferd_xml` **und** als Datei in `storage/xml/` gehalten. Die
  Datenbank ist der Primärspeicher, die Datei die Zweitablage.
- Erfolg von `mustang.combine` wird an `rc == 0 **und** Existenz der Ausgabedatei` geprüft,
  nie am Rückgabewert allein. Warum, steht in [`DEV-DOCU.md`](DEV-DOCU.md).

### DATEV-Upload-Mail

- Akzeptiert **nur PDF**, niemals reine XML.
- Maximal 20 MB pro Datei (wird geprüft).
- Der Versandnachweis ist zweigeteilt: `invoices.datev_sent_at` ist der **Erst**versand und
  wird nur gesetzt, solange er `NULL` ist. Er ist **forward-only**: der Guard verbietet
  Löschen und Umdatieren; ein einmal belegter Versand lässt sich nicht nachträglich
  bestreiten. **Alle** Versuche stehen in `invoice_send_log`, auch gescheiterte samt
  SMTP-Fehlertext. Ein Aufruf, der an den Vorprüfungen scheitert, hat nie gesendet und darf
  **keine** Protokollzeile schreiben.

### Statusmaschine

```
draft → [prüfen] → [finalisieren] → issued → paid
  ↕                                        ↘ cancelled
discarded
```

- `draft`: Entwurf, bearbeitbar
- `issued`: finalisiert, ZUGFeRD-PDF existiert, ab hier unveränderlich
- `paid` / `cancelled`: Endstatus, Dokumente bleiben erhalten
- `discarded`: verworfener **Entwurf**, nie gestellt, kein PDF, keine XML

**`discarded` ist nicht `cancelled`.** `cancelled` ist ein gestellter, stornierter Beleg mit
Nummer, PDF und XML; `discarded` ist ein nie gestellter Entwurf. In Listen, Zählern und
Exporten dürfen die beiden nie zusammenfallen. `discarded` existiert, weil Rechnungen nie hart
gelöscht werden dürfen und die Nummer schon beim Anlegen des Entwurfs vergeben wird: der
verbliebene Datensatz ist das Einzige, was die Lücke in der Nummernfolge später erklärt. Aus
`discarded` führt kein direkter Weg in einen Belegstatus: erst zurückholen, dann finalisieren.

### Entwürfe bearbeiten, nur `draft`

`GET/POST /invoices/{id}/bearbeiten`. Die Grenze ist doppelt gesichert: der Router antwortet
bei `issued`/`paid`/`cancelled` mit `400`, verbindlich ist aber der `invoice_guard`.
Korrektur eines gestellten Belegs ausschließlich per Storno.

Drei Punkte, die dabei nicht auseinanderlaufen dürfen:

- **Positionen werden ersetzt, nicht zusammengeführt.** Alte Zeilen gehen **einzeln** über
  `db.delete()`. Ein Bulk-`query().delete()` umginge Guard und Audit-Log stillschweigend.
- **`archive_until` folgt `issue_date`.**
- **`invoice_number`, `id`, `status`, `created_at` sind unveränderlich.**

### Ein Entwurf hat keine Pflichtfelder, auch keinen Kunden

`invoices.customer_id` ist **nullable** (Migration 004), und das Auswahlfeld im Formular trägt
kein `required`. Beides gehört zusammen: nähme der Server den Entwurf an und bliebe das
`required` stehen, verweigerte schon der Browser das Abschicken.

Der Grund ist ein Ablauf, kein Geschmack. Wer eine Rechnung für einen noch nicht angelegten
Kunden vorbereitet, tippt zuerst Positionen und Termine. Eine Pflichtfeldmeldung beim
Speichern wirft diese Arbeit weg und zwingt dazu, sie nach dem Anlegen des Kunden noch einmal
zu tippen. Jetzt gilt: speichern, Kunden anlegen, zurückkehren, zuweisen.

**Die Pflicht ist damit nicht weg, sie steht an der richtigen Stelle.** § 14 Abs. 4 Nr. 1 UStG
verlangt den Empfänger auf der *Rechnung*, nicht auf dem Entwurf. Durchgesetzt wird das von
`validator.validate_invoice` (`BUYER_MISSING`, harter Fehler) vor dem fail-closed
Finalisieren: ein Entwurf ohne Kunden lässt sich speichern und **niemals** finalisieren. Wer
die Spalte wieder auf NOT NULL zieht, gewinnt nichts an Sicherheit und nimmt nur den Ablauf
zurück. Der Test, der diese Grenze hält, ist
`test_entwurf_ohne_kunde.py::test_finalisieren_ohne_kunde_bleibt_verboten`.

Die PDF-Vorschau ist die eine Stelle, die den Kunden wirklich braucht: ohne Empfänger gibt es
keine Anschrift. Sie antwortet deshalb mit `400` und einem Satz statt mit einem Fehlerbericht.
Die XML-Vorschau daneben kommt ohne Kunden aus, `zugferd_xml` ist durchgehend `None`-fest.

### Die Entwurfs-Vorschau schreibt nichts

`GET /invoices/{id}/vorschau` (und `/vorschau.pdf`), nur für `draft`: kein Schreiben nach
`storage/`, kein `commit()`, kein `ValidationResult`, keine Zuweisung an `zugferd_xml`.
`storage/pdfs/` ist das GoBD-Archiv; ein Vorschau-PDF dort wäre später von einem echten Beleg
nicht mehr zu unterscheiden. Das PDF entsteht in einer Wegwerf-Datei und trägt ein
`ENTWURF`-Wasserzeichen: es hat schon die endgültige Nummer, aber keine eingebettete XML
(§-14c-Risiko, falls es jemand weitergibt).

### Solange etwas nicht bearbeitbar ist, darf der Zurück-Button es nicht vortäuschen

`GET /invoices/neu` liefert `Cache-Control: no-store`, und das Makro
`templates/partials/formular_zurueck_guard.html` entwertet einen bereits abgeschickten
History-Eintrag. Sonst käme das ausgefüllte Anlageformular als Schein-Editor zurück und legte
beim Absenden eine **zweite** Rechnung mit neuer Nummer an. Serverregeln allein genügen nicht:
bei einer Rückkehr aus dem bfcache stellt der Browser **keinen** Request. Gilt gleichlautend
für `/customers/neu`; **jedes neue Anlegeformular bindet das Makro im Anlege-Modus ein** (im
Bearbeiten-Modus bewusst nicht).

### Ersteinrichtung ist ein Tor, kein Hinweis

Eine frische Installation hat eine leere Firmenzeile und `setup_completed_at IS NULL`.
`/dashboard` leitet dann auf `/setup` um, und die Rechnungserzeugung verweigert unabhängig
davon mit `400` (`_get_company`). Ohne Firmenname, Anschrift und Steuernummer **oder**
USt-IdNr. entsteht keine Rechnung, sie wäre nach § 14 UStG fehlerhaft.

### Update-Prüfung

Sie läuft **ausschließlich auf Nutzerklick**: kein Scheduler, kein Start-Hook, kein Abruf im
Hintergrund. Vor dem ersten Abruf ist eine einmalige Bestätigung nötig
(`app_config.update_consent_at`); ohne sie wird nichts abgerufen. Aus der Serverantwort wird
**kein Verhalten** übernommen: ob ein Banner schließbar ist, entscheidet allein
`services/update_banner.py`.

**Quelle sind die GitHub-Releases dieses Repos** (`services/update_check.py`, `ENDPOINT`),
also kein selbst betriebener Server, der jahrelang laufen müsste, damit eine Installation im Feld
ihre Version prüfen kann. Wer einen Release veröffentlicht, hat die Prüfung bedient. Zwei
Dinge, die dabei nicht offensichtlich sind:

- **GitHub kennt weder Dringlichkeit noch freien Hinweis.** Beides kommt aus Kopfzeilen im
  Release-Text: `severity: security|legal` und `hinweis:` / `hinweis-url:`. Nur die ersten
  Zeilen werden gelesen, sonst löst ein „severity:" mitten im Änderungstext ein nicht
  wegklickbares Banner aus. Ein unbekannter Wert fällt auf `normal` zurück.
- **Abgerufen wird von `api.github.com`, die Release-Seite liegt auf `github.com`.** `safe_link`
  prüft deshalb gegen eine Liste erlaubter Hosts (`LINK_HOSTS`), nicht nur gegen den
  Endpunkt-Host; sonst würde jeder Link verworfen.

Der Abruf überträgt **nichts über die Installation**: keine Version, keine Ausgabe, keine
Kennung. Version und Ausgabe stehen weiter in der Signatur von `fetch_update_info`, werden
aber nicht gesendet, der Vergleich passiert lokal. Test:
`test_update_fetch.py::test_abruf_verraet_nichts_ueber_die_installation`.

### USt-IdNr.-Prüfung über VIES

Sie läuft **ausschließlich auf Nutzerklick**: kein Scheduler, kein Start-Hook, kein Abruf beim
Speichern von Kunden oder Firmendaten. Vor jedem Abruf zeigt ein Modal (`partials/
ust_id_vies_dialog.html`) die Ziel-URL (`VIES_ENDPOINT`) und die übertragenen Felder; ohne
`bestaetigt=1` im POST wird nichts aufgerufen.

Der Server sendet an `ec.europa.eu` nur die zu prüfende USt-IdNr., optional `traderName` und
optional die eigene USt-IdNr. als Requester; keine Rechnungen, keine weiteren Stammdaten.
Ergebnis und Zeitpunkt landen in `customers` bzw. `company` (`vat_id_checked_at`,
`vat_id_check_valid`, `vat_id_vies_name`, `vat_id_name_match`). Änderung der USt-IdNr. beim
Speichern setzt den Prüfstand zurück (`zuruecksetzen` in `ust_id_pruefung.py`).

Der Validator (`validator._ust_id_validator_issues`) mappt den Prüfstand auf Warnungen und
Fehler beim Finalisieren. Tests: `test_ust_id_pruefung.py`, `test_ust_id_zustimmung.py`.

## Datenbankmigrationen

```bash
# Entwicklungsstack, sonst landet die erzeugte Datei nur im Container
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
docker compose exec -T app alembic revision --autogenerate -m "kurze Beschreibung" < /dev/null
docker compose exec -T app alembic upgrade head < /dev/null
```

Der Entwicklungsstack ist hier Pflicht, nicht Geschmack: Nur er mountet `backend/alembic` ins
Arbeitsverzeichnis. Im Auslieferungsstack schreibt `--autogenerate` die neue Migration in das
Dateisystem des Containers, und sie ist beim nächsten `up` verschwunden.

**Es gibt genau eine Migration: `001_initial_schema.py`.** Sie ist aus den Modellen erzeugt
und legt das vollständige Schema an, dazu die GoBD-Trigger (aus
`app/db/immutability_triggers.py`, deren einzige Quelle) und die beiden Singleton-Zeilen
`company` und `app_config`. Ab hier gilt der normale Ablauf: jede weitere Änderung ist eine
**neue** Migration, `001` wird nie editiert.

**`alembic check` ist hier ein echtes Gate** und muss grün bleiben. Modelle und Migrationen
sind deckungsgleich, und `tests/test_migrationskette.py` prüft das bei jedem Lauf gegen eine
frisch migrierte Wegwerf-Datenbank. Wer eine Migration schreibt, deren Ergebnis vom Modell
abweicht, bekommt das dort rot; ein „das ist bei uns immer rot" gibt es nicht.

Die Owner-Rolle legt der Entrypoint beim Start selbst an (`scripts/bootstrap_owner.py`), bevor
Alembic läuft. Von Hand ist dafür nichts zu tun.

## Tests

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
docker compose exec -T app python -m pytest tests/ < /dev/null   # laufender Stack
backend/run-tests.sh                                             # Baseline = das, was die CI fährt
```

Tests laufen **nur im Container**. Auf dem Host fehlen die Abhängigkeiten, und ein Lauf dort
ist ein falsches Rot. In einem zweiten Compose-Stack immer `-T` und `< /dev/null` anhängen,
sonst kann ein Subprozess (Mustang) am offenen stdin hängen bleiben.

Der erste Befehl ist keine Bequemlichkeit: `docker-compose.yml` allein baut das
Auslieferungsabbild, und darin liegt kein pytest. Siehe `docker-compose.dev.yml` und den
Abschnitt „Auslieferung und Entwicklung" in `docs/DEV-DOCU.md`.

**Zwei Schichten, die nicht verwechselt werden dürfen:** Router- und Serviceverhalten mit
echter Datenbanksemantik (Guards, Commit-Persistenz, Statusmaschine, Schema) gehört in
Integrationstests mit der `pg_session`-Fixture, **nicht** in Tests mit einer nachgebauten
Mock-Datenbank. Letztere bleiben grün, wenn echter Code bricht (ein fehlender Commit, ein
ausgehebelter Guard), und sind damit falsch-grün. Ein nicht gestubbtes Query im Handler bricht
einen Mock-Test nicht; es liefert stillschweigend „leer".

**Neue Tests mit Datenbankwirkung gehören in `pg_session`.** Prüfmittel für einen Test, dem
man nicht traut: den Produktivcode kaputt machen und nachsehen, ob der Test wirklich rot wird.

**Test-driven ist Pflicht.** Kein Produktivcode ohne vorher fehlschlagenden Test. Ein
Pre-Push-Hook (`.githooks/pre-push`, aktiviert über `core.hooksPath`) und die CI
(`.github/workflows/tdd.yml`) fahren dieselbe Baseline; beide behandeln übersprungene Tests
als Fehler, damit fehlende Werkzeuge im Container nicht unbemerkt den kritischen
E-Rechnungs-Pfad verbergen.

## Validierungsregeln erweitern

Alle Regeln nach § 14 UStG stehen in `services/validator.py` → `validate_invoice()`:

```python
if <bedingung>:
    errors.append(Issue("CODE", "error", "Meldung auf Deutsch.", "feldname"))
    warnings.append(Issue("CODE", "warning", "Meldung.", "feldname"))
```

Fehler blockieren das Finalisieren, Warnungen nicht.

## Neue Python-Abhängigkeit

Quelle der Wahrheit ist `backend/pyproject.toml`; `backend/uv.lock` hält die vollständige
Auflösung inklusive Transitiven und Prüfsummen. Auf dem Host wird kein `uv` installiert.

```bash
# 1. backend/pyproject.toml editieren (exakter Pin, z. B. "foo==1.2.3")
cd backend && ./uv.sh lock && cd ..
docker compose build app && docker compose up -d app
```

`uv.lock` **nie von Hand editieren.** Der Bau erzwingt die Übereinstimmung: `uv sync --locked`
bricht ab, wenn Lock und `pyproject.toml` auseinanderlaufen. Schlägt das an, wird der Lock neu
erzeugt und eingecheckt, nicht mit `--frozen` umgangen.

## Fremde XML immer mit `defusedxml` parsen

Hochgeladene oder zugesandte XML nie mit der Standardbibliothek (`xml.etree`) parsen:
`import defusedxml.ElementTree as ET`, `DefusedXmlException` als fachlichen Fehler behandeln
(fail-closed). Sonst sind XXE und „Billion Laughs" offen.
