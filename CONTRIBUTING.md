# Mitarbeit

## Fehlermeldungen sind ausdrücklich willkommen

Am hilfreichsten ist eine Meldung, die sich nachstellen lässt: was wurde getan, was wurde
erwartet, was ist stattdessen passiert. Dazu die Ausgabe von `docker compose logs app`, soweit
sie zum Vorfall gehört.

**Bitte keine echten Rechnungs- oder Kundendaten** in Issues, weder als Text noch als PDF
oder Screenshot. Ein anonymisiertes Beispiel genügt in aller Regel.

Sicherheitslücken gehören **nicht** in ein öffentliches Issue, sondern nach
[SECURITY.md](SECURITY.md).

## Code-Beiträge nur gegen CLA

Pull Requests werden nur angenommen, wenn du der Vereinbarung in [CLA.md](CLA.md) zustimmst.
Ein Kommentar im Pull Request genügt, der Wortlaut steht dort in Abschnitt 6.

Der Grund, offen gesagt: sobald der erste fremde Beitrag ohne diese Vereinbarung gemergt ist,
ist eine spätere kommerzielle Zweitlizenz dauerhaft versperrt; sie ließe sich nur noch mit
Zustimmung jedes einzelnen Beitragenden erteilen. Das Projekt hält sich diese Möglichkeit
offen; sie steht allein ihm zu.

Du gibst dabei **nichts auf**: das eingeräumte Recht ist einfach, nicht ausschließlich. Dein
Beitrag bleibt deiner, und du darfst ihn weiterhin überall sonst verwenden. Wer gar nichts
unterschreiben will, ist von der AGPL vollständig gedeckt: das Programm darf genutzt,
verändert und weitergegeben werden. Nur der Weg zurück ins Hauptprojekt führt über die
Vereinbarung.

Vor größerer Arbeit bitte erst ein Issue eröffnen. Ein Pull Request, der an einer
Grundsatzentscheidung vorbeiläuft, kostet beide Seiten Zeit.

## Test-driven ist Pflicht

Kein Produktivcode ohne vorher fehlschlagenden Test. Rot, dann grün, dann aufräumen. Das ist
in diesem Projekt keine Empfehlung: Der Code entscheidet darüber, ob ein Beleg
aufbewahrungspflichtige Daten korrekt und unveränderlich festhält, und ein Fehler darin fällt
frühestens bei der Betriebsprüfung auf.

```bash
# Entwicklungsstack, einmal pro Sitzung
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

docker compose exec -T app python -m pytest tests/ < /dev/null   # gegen den laufenden Stack
backend/run-tests.sh                                             # Baseline, identisch zur CI
```

Tests laufen **nur im Container**. Auf dem Host fehlen die Abhängigkeiten; ein Lauf dort ist
ein falsches Rot.

**Warum zwei Compose-Dateien.** `docker-compose.yml` allein ist das, was eine Installation
ausführt: das gebaute Abbild ohne pytest, ein Serverprozess, kein Dateiwächter.
`docker-compose.dev.yml` legt zurück, was beim Entwickeln gebraucht wird, nämlich das Abbild
mit Testwerkzeug, den Quellcode aus dem Arbeitsverzeichnis und das Nachladen bei Änderungen.
Ohne die zweite Datei findet der Testbefehl oben kein pytest, und das sieht wie eine kaputte
Suite aus, obwohl nur das falsche Abbild läuft. `backend/run-tests.sh` ist davon unberührt,
es baut sich alles selbst.

Zwei Regeln, an denen Beiträge sonst regelmäßig scheitern:

- **Alles mit Datenbankwirkung gehört in einen Integrationstest** mit der
  `pg_session`-Fixture, nicht in einen Test mit nachgebauter Mock-Datenbank. Solche Tests
  bleiben grün, wenn echter Code bricht.
- **Übersprungene Tests gelten als Fehler.** Sowohl der Pre-Push-Hook als auch die CI brechen
  ab, sobald ein Test übersprungen wird; ein fehlendes Werkzeug im Container darf den
  E-Rechnungs-Pfad nicht unbemerkt verbergen.

Vor dem ersten Push einmal die Hooks aktivieren:

```bash
git config core.hooksPath .githooks
```

### Was der Hook außer den Tests noch prüft

Vor der Suite brechen Wachen den Push ab. Sie stehen im Hook und nicht in der Suite, weil
sie Dateien im Wurzelverzeichnis lesen und der Testcontainer nur `backend/` sieht: ein Test
dafür würde still übersprungen, und ein übersprungener Test gilt hier als Fehlschlag. Der
Reihe nach laufen die Datenwache, die Gedankenstrich-Wache und die sechs Wachen aus
`.githooks/wachen.sh`; auf die Suite folgt der Skip-Guard.

**Geprüft wird der gepushte Commit, nicht der Checkout.** `git push origin <branch>` aus
einem anderen Worktree oder bei ausgechecktem anderem Stand liefert dem Hook auf stdin je
Ref die lokale SHA. Suite, Gedankenstrich-Wache und `.githooks/wachen.sh` laufen gegen
genau diesen Stand (Wegwerf-Worktree unter `$TMPDIR`, Abräumen per trap). Entspricht
`HEAD` bereits der lokalen SHA, bleibt der schnelle Weg im Arbeitsbaum: Export wäre
derselbe Baum und kostet nur Zeit. Löschungen (SHA aus Nullen) werden übersprungen;
mehrere Refs werden nacheinander geprüft. Die Meldung nennt den geprüften Commit.
`backend/run-tests.sh` braucht nur `backend/` plus optional `UEBERGABE_VEKTOREN` (absoluter
Pfad); `.githooks` liest es nicht. stdin wird einmal gelesen und an die Datenwache sowie
die Stand-Prüfung weitergereicht, damit nichts die Ref-Zeilen vorher verbraucht.

- **Datenwache** (`.githooks/datenwache.sh`): prüft je gepuschtem Commit nur die neu
  hinzukommenden Zeilen und zusätzlich die Commit-Nachricht auf Muster echter Daten, nämlich
  private Schlüssel, die Formate von IBAN, USt-IdNr. und Steuernummer, neu hinzukommende
  `.env`-Dateien und Zusatzmuster aus einer privaten Musterdatei außerhalb des Repos. Neben
  der gemeinsamen Musterdatei (`~/.zemp/echtdaten-muster.txt`, Pfad über `ZEMP_ECHTDATEN_MUSTER`)
  liest die Wache eine repo-eigene Datei (`~/.zemp/echtdaten-muster.abgehakt.txt`, Pfad über
  `ZEMP_ECHTDATEN_MUSTER_REPO`) für Begriffe, die nur in diesem Repo verboten sind; fehlt sie,
  ist das kein Fehler. Bei
  einem Fund bricht der Push ab; einen bewussten Fehlalarm überstimmt man einmalig mit
  `DATENWACHE_UEBERSTIMMT=1`. Issues und Pull Requests auf GitHub prüft dieselbe Regel
  (`.github/workflows/issue-wache.yml`): bei einem Fund erhalten sie ein Label und einen
  Hinweiskommentar, der nur die Musterklasse nennt.
- **Sechs Wachen aus `.githooks/wachen.sh`:**
  - **Kein veröffentlichter Port ohne `127.0.0.1:`** in einer Compose-Datei. `"3000:3000"`
    hängt an allen Schnittstellen, und die Anwendung bringt keine Anmeldung mit: wer im
    selben Netz sitzt, sähe damit alle Rechnungen und lüde den GoBD-Export samt
    Kundendaten herunter.
  - **`docker-compose.yml` bleibt die Auslieferung.** Kein `target: test`, kein Mount aus
    `./backend/`. Beides gehört in `docker-compose.dev.yml`, das die Wache bewusst nicht
    prüft.
  - **UID und GID stehen im Dockerfile fest** und müssen mit der `chown`-Zahl im README
    übereinstimmen, sonst wird die Anweisung für `storage/` still falsch.
  - **Die Gruppe der Belegordner** (`EXTRA_GROUP_GID=2000`, Name `belegordner`) muss im
    Dockerfile stehen, damit alle Stacks dieselbe Gruppenkennung tragen.
  - **Keine Postgres-Passwörter mit stiller Vorgabe** in `docker-compose.yml`: fehlende
    Werte müssen den Start abbrechen, nicht unbemerkt einen Zufallswert annehmen.
  - **Ketten-Testinstanz hängt `./schluessel-integration` als `/app/schluessel` ein**, nicht
    `./backend/schluessel`. Probeschlüssel liegen bewusst neben `backend/`, damit sie nicht
    ins Auslieferungsabbild geraten; fehlt der Mount oder zeigt er woanders hin, endet jede
    Kettenprobe mit `SCHLUESSEL_UNBEKANNT`.
- **Keine Gedankenstriche in Markdown** (U+2013, U+2014). Komma, Doppelpunkt, Strichpunkt
  oder zwei Sätze sagen dasselbe und überstehen jede Schrift und jedes Terminal. Zwischen
  zwei Ziffern, also in einer Jahres- oder Paragraphenspanne, bleibt der Strich erlaubt.
- **Skip-Guard:** übersprungene Tests brechen den Push ab, genau wie in der CI; ein
  fehlendes Werkzeug im Container darf den E-Rechnungs-Pfad nicht unbemerkt verbergen.

Die sechs Wachen aus `wachen.sh` laufen auch in der CI (`.github/workflows/tdd.yml`), denn
ein Hook greift nur bei dem, der ihn aktiviert hat. Die Datenwache selbst läuft nur im Hook,
in der CI werden ihre Tests gefahren. Die Gedankenstrich-Wache bleibt bewusst lokal im
Hook: eine Schreibregel dieses Projekts ist kein Grund, einen fremden Pull Request
abzuweisen. Wer sie beim Schreiben vergisst, hört es vor dem Push und nicht als rote CI.

## Migrationen und neue Pakete

Beides gehört in den Entwicklungsstack, nicht in den Auslieferungsstack.

```bash
# Schemaänderung: erst das Modell ändern, dann erzeugen lassen
docker compose exec -T app alembic revision --autogenerate -m "kurze Beschreibung" < /dev/null
docker compose exec -T app alembic upgrade head < /dev/null

# Neues Paket: exakten Pin in backend/pyproject.toml eintragen, dann
cd backend && ./uv.sh lock
```

Nur der Entwicklungsstack mountet `backend/alembic` aus dem Arbeitsverzeichnis. Im
Auslieferungsstack schreibt `--autogenerate` die neue Migration in das Dateisystem des
Containers, und sie ist beim nächsten Start verschwunden. `backend/uv.lock` wird nie von Hand
bearbeitet; auf dem Rechner muss dafür kein uv installiert sein, `./uv.sh` bringt es mit. Der
Bau des Abbilds bricht ab, sobald Lock und `pyproject.toml` auseinanderlaufen.

## Was vor dem Code zu lesen ist

[`docs/ARCHITEKTUR.md`](docs/ARCHITEKTUR.md): der Aufbau und die Regeln, die nicht gebrochen
werden dürfen (Aufbewahrung, Statusmaschine, fail-closed-Finalisierung). Wer eine davon
antastet, sollte im Pull Request begründen, warum sie an dieser Stelle nicht gilt.

[`docs/DEV-DOCU.md`](docs/DEV-DOCU.md): technische Eigenheiten, die Zeit gekostet haben:
Mustang-Aufrufe, PDF/A-Erzeugung, Schrifteinbettung, Testumgebung.

## Keine Steuerberatung

Der Issue-Tracker beantwortet keine Fragen zur eigenen Steuerpflicht, weder zur
Kleinunternehmerregelung noch zum Reverse-Charge-Verfahren oder zu Aufbewahrungsfristen im
Einzelfall. Fragen zum **Verhalten des Programms** dagegen gerne, auch fachliche: wenn eine
Prüfregel etwas anderes tut, als das Gesetz verlangt, ist das ein Fehler und gehört gemeldet.
