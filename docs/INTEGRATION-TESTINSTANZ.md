# Ketten-Testinstanz (abgehakt)

Parallele Installation für Kettenproben, **nicht** die Live-Instanz auf Port 3000.

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
# integration.env: TESTINSTANZ_MAIL_TO, Passwoerter, SMTP, UEBERGABEN_ORDNER

mkdir -p ~/uebergaben-test/tantiemen-app-nach-abgehakt
mkdir -p ~/uebergaben-test/abgehakt-nach-tantiemen-app
# UEBERGABEN_ORDNER in integration.env auf diesen Pfad setzen

docker compose -p abgehakt-test \
  -f docker-compose.yml -f docker-compose.integration.yml \
  --env-file integration.env up -d --build
```

Öffnen: http://127.0.0.1:3001

## Nach dem Start: der Klon bekommt Probe-Kunden, keine Livedaten

**Klon der Anwendung, nicht der Daten.** Die Live-Datenbank hierher zu kopieren hieße,
Steuernummern, Anschriften und Bankverbindungen der Beteiligten ein zweites Mal abzulegen,
für eine Probe, die sie nicht braucht. Der Klon startet leer und bekommt von Hand
Probe-Kunden, deren **Schnittstellen-ID** genau die `partner_id` aus den Auftragsvektoren
ist. Wenn eine Probe doch echte Stammdaten braucht, ist das eine Entscheidung und keine
Nebenwirkung.

Reihenfolge, und die erste Zeile vergisst man genau einmal:

1. **Einstellungen, Beleg-Integration einschalten.** Ohne den Schalter gibt es weder den
   Menüpunkt BELEGE noch die Schnittstellen-ID, und `/uebergaben` antwortet mit 404.
2. Firmendaten ausfüllen (Ersteinrichtung), sonst entsteht keine formgerechte Gutschrift.
3. Je Beteiligtem einen Kunden anlegen. Danach beim Kunden die **Schnittstellen-ID**
   ablesen und die Gegenseite darauf zeigen lassen; für die gelieferten Auftragsvektoren
   muss umgekehrt die ID des Probe-Kunden auf die `partner_id` des Vektors gesetzt werden.
4. Umsatzsteuerlichen Status je Kunde setzen (regelbesteuert oder Kleinunternehmer). Er
   entscheidet über die Steuer auf der Gutschrift; der Auftrag trägt sie nicht.
5. Beleg in `~/uebergaben-test/tantiemen-app-nach-abgehakt/` legen, im Menü **BELEGE**
   ansehen, Befund lesen, erst dann **ALS RECHNUNG ANLEGEN**.

Ansehen ändert nichts: keine Zeile in der Datenbank, und in den Belegordner schreibt diese
Anwendung nie. Erst der Knopf legt Entwürfe an und merkt den Beleg als verarbeitet.

## Finalisieren nur hier

Ein Entwurf aus einem Beleg wird in der Testinstanz geprüft und, wenn überhaupt, hier
finalisiert. Die gesperrten Felder (Netto-Beträge, Beteiligter, Leistungszeitraum) sind im
Formular als „aus dem Beleg übernommen" gekennzeichnet; ist ein Betrag falsch, ist der
Beleg falsch, und die Gegenseite erzeugt einen neuen.

## Wegwerfen

```bash
docker compose -p abgehakt-test \
  -f docker-compose.yml -f docker-compose.integration.yml down -v
rm -rf storage-integration
```

## Live-Installation

Der Stack auf **3000/5432** (`docker compose up` ohne `-p abgehakt-test`) bleibt
unverändert. Zwei Compose-Dateien, anderer Projektname; siehe `docs/docker-issues.md`.
