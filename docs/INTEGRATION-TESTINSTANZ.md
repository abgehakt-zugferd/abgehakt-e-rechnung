# Ketten-Testinstanz (abgehakt)

Parallele Installation für Kettenproben, **nicht** die Live-Instanz auf Port 3000.

## Was sie tut

- GUI zeigt **TESTINSTANZ** (Banner + Sidebar)
- Jeder SMTP-Versand geht **nur** an `TESTINSTANZ_MAIL_TO` (deine Postbox)
- Kunden- und DATEV-Adressen erscheinen nur im Mailtext als „geplant an …"
- Eigene Daten: `storage-integration/`, Postgres-Volume `postgres_data_integration`
- Eigene Ports: **3001** (App), **5433** (DB)
- Der Backup-Dienst läuft nicht: `docker-compose.integration.yml` versieht `db-backup`
  mit dem Profil `integration-off`, also startet der Teststack ohne ihn. Die Probe
  schreibt nichts Aufbewahrungswürdiges, und ein Backup der Testinstanz wäre eines von
  Wegwerfdaten.

Ohne `TESTINSTANZ_MAIL_TO` startet die App nicht (`fail-closed`).

## Einrichtung

```bash
cd abgehakt-e-rechnung
cp integration-env.example integration.env
# integration.env: TESTINSTANZ_MAIL_TO, Passwoerter, SMTP, UEBERGABEN_ORDNER

mkdir -p ~/uebergaben-test/tantiemen-app-nach-abgehakt
mkdir -p ~/uebergaben-test/abgehakt-nach-tantiemen-app
# UEBERGABEN_ORDNER in integration.env auf diesen Pfad setzen

# Öffentliche Schlüssel der Übergabe-Absender bereitstellen, je Absender ein
# Unterordner mit je Schlüssel zwei Dateien (schluessel-integration/, nicht
# unter backend/: Probeschlüssel sollen nicht ins Auslieferungsabbild geraten):
#   schluessel-integration/<absender>/<schluessel_id>.pub    (PEM)
#   schluessel-integration/<absender>/<schluessel_id>.json   (Beiblatt, siehe unten)

docker compose -p abgehakt-test \
  -f docker-compose.yml -f docker-compose.integration.yml \
  --env-file integration.env up -d --build
```

Das Beiblatt (`<schluessel_id>.json`) hat seit #166 einen geschlossenen Feldbestand
(`services/uebergabe_schluessel.py`): Pflicht sind `schluessel_id`, `absender`,
`verfahren`, `gueltig_von` und `gueltig_bis`; dazu ist `notizen` erlaubt und muss
ein Objekt sein. Schluessel in `notizen` duerfen nicht wie Beiblattfelder heissen
und nicht `probe`, `warum_probe` oder `hinweis`. Die Zeitform ist genau
`YYYY-MM-DDTHH:MM:SSZ` (UTC, sekundengenau, ohne Bruchteile). `gueltig_bis: null`
heißt ohne Ablauf. Ein Beiblatt ohne das Feld `gueltig_bis` gilt seit #210 nicht
mehr als unbegrenzt, sondern als unbrauchbar.

`docker-compose.integration.yml` bindet `./schluessel-integration` nur lesend als
`/app/schluessel` ein, nicht `./backend/schluessel`: Probeschlüssel liegen bewusst
neben `backend/`, damit sie nicht ins Auslieferungsabbild geraten. Ein Beleg ist
nur mit dem öffentlichen Schlüssel seines Absenders annehmbar: fehlt er, scheitert
der Befund am Code `SCHLUESSEL_UNBEKANNT` (`services/uebergabe_schluessel.py`), und
**ALS RECHNUNG ANLEGEN** bleibt gesperrt.
Ein Probeschlüssel ist am Namen erkennbar (Kennzeichen `-probe-`) und gilt nur in
einer Testinstanz, nie im Echtlauf.

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

## Uebergabekette eines Absenders neu beginnen

In der Testinstanz kann die gemerkte Kette eines Absenders zurueckgesetzt werden,
ohne die Datenbank zu leeren: das Wartungsskript entfernt nur die Eingaenge dieses
Absenders (`uebergabe_eingaenge`). Rechnungen, Entwuerfe, Aufstellungen, Kunden und
Firmendaten bleiben. Ausserhalb der Testinstanz verweigert das Skript den Lauf
(Exit-Code ungleich 0, keine Datenbankaenderung).

```bash
docker compose -p abgehakt-test \
  -f docker-compose.yml -f docker-compose.integration.yml \
  --env-file integration.env exec app \
  python -m scripts.uebergabe_kette_neu_beginnen <absender>
```

`<absender>` ist die Kennung wie im Beleg (zum Beispiel `absender`). Danach liefert
`zuletzt_angenommen` fuer diesen Absender wieder `None`, und die Kette kann von
vorn gelesen werden.

## Wegwerfen

```bash
docker compose -p abgehakt-test \
  -f docker-compose.yml -f docker-compose.integration.yml \
  --env-file integration.env down -v
rm -rf storage-integration
```

## Live-Installation

Der Stack auf **3000/5432** (`docker compose up` ohne `-p abgehakt-test`) bleibt
unverändert. Zwei Compose-Dateien, anderer Projektname. Der eigene Projektname ist Pflicht,
reicht aber allein nicht: `container_name` und `ports` stehen in `docker-compose.yml` fest,
und Container-Namen müssen auf dem Rechner global eindeutig sein, unabhängig vom
Projektnamen. Deshalb überschreibt `docker-compose.integration.yml` beides.
