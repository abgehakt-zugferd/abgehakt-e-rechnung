# Abgehakt

## Overview

Rechnungsprogramm für E-Rechnungen nach ZUGFeRD/Factur-X (Profil `EN16931`, PDF/A-3 mit
eingebetteter XML). Läuft lokal, ohne Cloud, ohne Konto, ohne Nutzeranmeldung. Gestellte
Belege sind unveränderlich; korrigiert wird ausschließlich über eine Stornorechnung.

Ausführliche Einordnung (Rechtsrahmen, GoBD, Grenzen) steht in `README.md`. Die Regeln für
Beiträge stehen in `CONTRIBUTING.md`. Diese Datei ist die Kurzfassung für Agenten plus der
Enforcement-Vertrag.

## Tech Stack

- Sprache: Python 3.11 (Produktion läuft genau auf dieser Fassung, siehe `backend/Dockerfile`)
- Framework: FastAPI, Jinja2-Templates, Alpine.js und Tailwind (beide lokal ausgeliefert)
- Datenbank: PostgreSQL 16, SQLAlchemy 2 mit Alembic
- Belegkette: Ghostscript und Mustang-CLI (Java) für Einbettung und Prüfung
- Paketverwaltung: `uv` (`backend/uv.lock`)
- Betrieb: Docker Compose

## Commands

```bash
# Entwicklungsstack, einmal pro Sitzung
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# Suite gegen den laufenden Stack (schnelle Schleife)
docker compose exec -T app python -m pytest tests/ < /dev/null

# Kanonische Baseline, identisch zur CI
backend/run-tests.sh
backend/run-tests.sh -k storno    # pytest-Argumente werden durchgereicht
```

Tests laufen **nur im Container**. Auf dem Host fehlen JRE, Ghostscript und Mustang; ein Lauf
dort ist ein falsches Rot.

## Architecture

```
backend/app/
  models/      Company, Customer, Invoice (+ InvoiceItem, ValidationResult,
               InvoiceSendLog, AuditLog), AppConfig
  routers/     invoices, customers, archive, export, settings, setup, updates
  services/    Fachlogik, siehe unten
  db/          immutability_triggers.py, roles.py (Sperren auf Datenbankebene)
  templates/   Jinja2-Oberfläche
backend/alembic/versions/   Migrationskette
backend/tests/              pytest-Suite
.githooks/                  pre-push, wachen.sh
```

Die Fachlogik in `services/` gliedert sich in vier Gruppen:

- **Nummernkreise:** `invoice_number.py`, `customer_number.py`
- **Unveränderbarkeit:** `invoice_guard.py`, `customer_guard.py`, `storno.py`, dazu
  `db/immutability_triggers.py`. Die Wächter in der Anwendung und die Auslöser in der
  Datenbank sind zwei Schichten derselben Zusage; wer eine ändert, prüft die andere mit.
- **Belegerzeugung und Prüfung:** `zugferd_xml.py`, `pdf_generator.py`, `pdfa.py`,
  `mustang.py`, `validator.py`, `pdf_fonts.py`
- **Nachweise:** `aenderungsprotokoll.py`, `audit.py`, `gobd_export.py`, `datev_email.py`

## Environment Variables

Die vollständige Liste mit Erklärungen steht in `.env.example`; sie wird hier bewusst nicht
abgeschrieben, damit nicht zwei Fassungen auseinanderlaufen. `.env` gehört nie ins Repository.

Der Anwendungsschlüssel verwaltet sich selbst über `storage/secret.key` und wird **nicht**
als Umgebungsvariable gesetzt.

---

<!-- tdd-enforcement-contract -->
## TDD-Enforcement-Vertrag

**NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST.** Rot, dann grün, dann aufräumen. In
diesem Repository ist das keine Empfehlung: Der Code entscheidet, ob ein
aufbewahrungspflichtiger Beleg korrekt und unveränderlich festgehalten wird, und ein Fehler
darin fällt frühestens bei der Betriebsprüfung auf.

### Geltungsbereich

Produktivcode ist alles unter `backend/app/`, `backend/alembic/` und `.githooks/`. Änderungen
an Markdown im Wurzelverzeichnis, an `LICENSE`, `CLA.md` und an den Vorlagen unter `.github/`
sind Dokumentation und brauchen keinen Test; für sie greifen die Wachen im Hook.

### Wie dieses Repo scharf gestellt ist

| Baustein | Datei | Zustand |
|---|---|---|
| Pre-Push-Hook | `.githooks/pre-push` | vorhanden, projektspezifisch |
| Hook aktiviert | `git config core.hooksPath .githooks` | gesetzt am 2026-08-23 |
| CI-Gate | `.github/workflows/tdd.yml` | vorhanden, baut Prod-Abbild |
| Vertrag | dieser Abschnitt | vorhanden |

Aktivierung nach einem frischen Klon:

```bash
git config core.hooksPath .githooks
```

### Container-Läufer, und warum der Kit-Standard hier falsch wäre

Der Standard-Läufer des TDD-Kits ist `python3 -m pytest` auf dem Host. Hier wäre das ein
falsches Rot, das **jeden** Push blockiert: Auf dem Host liegen weder die Abhängigkeiten der
Anwendung noch JRE, Ghostscript oder Mustang. Der Hook wählt deshalb selbst:

1. Läuft der Entwicklungsstack **und** hat der `app`-Container pytest, dann Suite dort.
2. Sonst die kanonische Baseline `backend/run-tests.sh`, die sich alles selbst baut.

Beide Bedingungen werden geprüft, nicht nur die erste: Seit `docker-compose.yml` das
Auslieferungsabbild baut, läuft im Normalfall ein `app`-Container **ohne** pytest.

### Nicht durch Kit-Vorlagen ersetzen

`~/.claude/skills/tdd/enforcement/tdd-init.sh` darf in diesem Repository **nicht** ausgeführt
werden. `tdd_install` überschreibt bedingungslos:

- `.githooks/pre-push` mit der Kit-Vorlage. Dabei gingen der Container-Läufer, der
  Skip-Guard, die Gedankenstrich-Wache und der Aufruf von `wachen.sh` verloren.
- `.github/workflows/tdd.yml` mit der generischen `python-uv`-Vorlage (der Stack wird wegen
  `backend/uv.lock` so erkannt). Dabei ginge der Bau des Prod-Abbilds samt Mustang und
  Ghostscript verloren, und die vier ZUGFeRD-Integrationstests würden in der CI still
  überspringen.

Fehlt etwas an der Armierung, wird es **von Hand** ergänzt.

### Zwei Regeln, an denen Beiträge sonst scheitern

- **Alles mit Datenbankwirkung gehört in einen Integrationstest** mit der `pg_session`-Fixture,
  nicht in einen Test mit nachgebauter Mock-Datenbank. Solche Tests bleiben grün, wenn echter
  Code bricht.
- **Übersprungene Tests gelten als Fehlschlag.** Hook und CI brechen ab, sobald ein Test
  übersprungen wird. Ein fehlendes Werkzeug im Container darf den E-Rechnungs-Pfad nicht
  unbemerkt verbergen.

### Grün ist verdächtig nach jedem Test-Umbau

Nach einem größeren Umbau an der Teststruktur einen winzigen Fehler in den Produktivcode
einbauen und sicherstellen, dass **mindestens ein Test rot** wird; danach zurücknehmen. Bei
regulären Ausdrücken mit `|`, mehreren Zweigen zum selben Ergebnis oder Fallback-Ketten den
**gesamten** Entscheidungsweg brechen, nicht eine Alternative.

Den Exit-Code des Hooks dabei **direkt** abgreifen, nie durch eine Pipe:

```bash
bash .githooks/pre-push origin URL </dev/null >out 2>&1; rc=$?
```

`hook | tail -4; echo $?` liefert den Exit von `tail` und damit immer 0.

Letzte Verifikation am 2026-08-23: grün mit 839 bestandenen Tests und ohne Übersprungene;
rot mit 2 Fehlschlägen und Hook-Exit 1 nach einer eingebauten Regression im Nummernkreis.

### Keine Gedankenstriche in Markdown

U+2013 und U+2014 brechen den Push. Komma, Doppelpunkt, Strichpunkt oder zwei Sätze sagen
dasselbe. Zwischen zwei Ziffern, also in einer Jahres- oder Paragraphenspanne, bleibt der
Strich erlaubt. Die Wache steht im Hook und nicht in der Suite, weil der Testcontainer nur
`backend/` sieht und ein Test dafür still überspringen würde.
