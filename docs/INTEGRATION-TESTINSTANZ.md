# Ketten-Testinstanz (abgehakt)

Parallele Installation für ZEMP-Kettenproben, **nicht** die Live-Instanz auf Port 3000.

## Was sie tut

- GUI zeigt **TESTINSTANZ** (Banner + Sidebar)
- Jeder SMTP-Versand geht **nur** an `TESTINSTANZ_MAIL_TO` (deine Postbox)
- Kunden- und DATEV-Adressen erscheinen nur im Mailtext als „geplant an …"
- Eigene Daten: `storage-integration/`, Postgres-Volume `postgres_data_integration`
- Eigene Ports: **3001** (App), **5433** (DB)

Ohne `TESTINSTANZ_MAIL_TO` startet die App nicht (`fail-closed`).

## Einrichtung

```bash
cd abgehakt-e-rechnung
cp integration-env.example integration.env
# integration.env: TESTINSTANZ_MAIL_TO, Passwörter, SMTP, ZEMP_UEBERGABEN

mkdir -p ~/zemp-uebergaben-test/tantiemen-app-nach-abgehakt
mkdir -p ~/zemp-uebergaben-test/abgehakt-nach-tantiemen-app
# ZEMP_UEBERGABEN in integration.env auf diesen Pfad setzen

docker compose -p abgehakt-test \
  -f docker-compose.yml -f docker-compose.integration.yml \
  --env-file integration.env up -d --build
```

Öffnen: http://127.0.0.1:3001

## Wegwerfen

```bash
docker compose -p abgehakt-test \
  -f docker-compose.yml -f docker-compose.integration.yml down -v
rm -rf storage-integration
```

## Live-Installation

Der Stack auf **3000/5432** (`docker compose up` ohne `-p abgehakt-test`) bleibt
unverändert. Zwei Compose-Dateien, anderer Projektname; siehe `docs/docker-issues.md`.
