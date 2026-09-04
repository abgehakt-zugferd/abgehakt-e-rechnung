#!/usr/bin/env bash
# Drei Wachen, die vor jedem Push und in der CI laufen.
#
# Sie stehen hier als Skript und nicht in der Testsuite, weil sie Dateien im
# Wurzelverzeichnis lesen: der Testcontainer wird aus `backend/` gebaut und sieht den
# Rest des Repos nicht. Ein pytest dafuer wuerde still ueberspringen, und ein
# uebersprungener Test gilt hier als Fehlschlag.
#
# Sie stehen als eigene Datei und nicht zweimal abgetippt, weil `.githooks/pre-push` und
# `.github/workflows/tdd.yml` sie beide aufrufen. Zwei Kopien derselben Regel laufen
# auseinander, und die CI-Kopie faellt dabei zuletzt auf.
#
# Die dritte Wache im Hook, keine Gedankenstriche in Markdown, ist bewusst NICHT hier:
# das ist eine Schreibregel dieses Projekts und kein Grund, einen fremden Pull Request
# abzuweisen. Sie bleibt lokal.
set -uo pipefail

cd "$(git rev-parse --show-toplevel)"

fehler=0

# Ein veroeffentlichter Port ohne `127.0.0.1:` haengt an ALLEN Schnittstellen. Bei dieser
# Anwendung heisst das: wer im selben Netz sitzt, sieht die Rechnungen, legt neue an und
# laedt den GoBD-Export samt Kundendaten herunter. Eine Anmeldung gibt es nicht
# (SECURITY.md). Wer bewusst aus dem Netz zugreifen will, aendert die Zeile und weiss
# dann, was er tut.
offen="$(git ls-files '*compose*.yml' | while read -r f; do
    awk -v datei="$f" '
      /^[[:space:]]*ports:/ { in_ports = 1; next }
      in_ports && /^[[:space:]]*-[[:space:]]*"?[0-9]/ &&
        $0 !~ /"?(127\.0\.0\.1|localhost):/ { print datei ":" NR ": " $0 }
      /^[[:space:]]*-?[[:space:]]*[a-zA-Z_]+:/ { if ($0 !~ /^[[:space:]]*ports:/) in_ports = 0 }
    ' "$f"
  done)"
if [ -n "$offen" ]; then
  {
    echo ""
    echo "netz: ROT - Port ohne 127.0.0.1 veroeffentlicht."
    echo "  \"3000:3000\" haengt an allen Schnittstellen; die Anwendung hat keine Anmeldung."
    echo "  Gemeint ist fast immer \"127.0.0.1:3000:3000\"."
    echo "$offen"
  } >&2
  fehler=1
fi

# `docker-compose.yml` ist das, was ein Anwender startet, und darf keine
# Entwicklungseinrichtung ausliefern:
#   `target: test`     baut die Stage MIT pytest und Testabhaengigkeiten hinein.
#   `- ./backend/...`  legt das Arbeitsverzeichnis ueber das gebaute Abbild; der Anwender
#                      laeuft dann auf einem Zwischenstand statt auf dem Release, und
#                      `docker compose up -d --build` aendert daran nichts.
# Entwicklung holt sich beides ueber `docker-compose.dev.yml` zurueck, das hier
# absichtlich NICHT geprueft wird.
auslieferung="$(awk '
    /^[[:space:]]*target:[[:space:]]*test[[:space:]]*(#.*)?$/ { print FILENAME ":" NR ": " $0 }
    /^[[:space:]]*-[[:space:]]*"?\.\/backend\// { print FILENAME ":" NR ": " $0 }
  ' docker-compose.yml)"
if [ -n "$auslieferung" ]; then
  {
    echo ""
    echo "auslieferung: ROT - docker-compose.yml liefert Entwicklungseinrichtung aus."
    echo "  Gemeint ist 'target: prod' und als einziger Mount './storage:/app/storage'."
    echo "  Nachladen, Quellcode-Mounts und pytest stehen in docker-compose.dev.yml."
    echo "$auslieferung"
  } >&2
  fehler=1
fi

# Auf einem Linux-Server muss `storage/` dem Benutzer im Container gehoeren, sonst kann
# das Programm weder Beleg noch Schluessel schreiben. Der README nennt dafuer eine feste
# Zahl (`chown -R 100:101 storage`). Vergibt das Dockerfile die Kennungen NICHT
# ausdruecklich, sucht `adduser --system` sich die naechste freie -- heute 100:101, nach
# einem neuen Basisabbild vielleicht 101:102. Die Anweisung im README wird dann still
# falsch, und der Fehler zeigt sich erst beim Anwender als Schreibfehler auf seine
# eigenen Daten. Deshalb: Kennungen festnageln und beide Stellen gegeneinander pruefen.
d_uid="$(grep -oE '\-\-uid[= ]+[0-9]+' backend/Dockerfile | grep -oE '[0-9]+' | head -1)"
d_gid="$(grep -oE '\-\-gid[= ]+[0-9]+' backend/Dockerfile | grep -oE '[0-9]+' | head -1)"
r_paar="$(grep -oE 'chown -R [0-9]+:[0-9]+' README.md | grep -oE '[0-9]+:[0-9]+' | head -1)"
if [ -z "$d_uid" ] || [ -z "$d_gid" ]; then
  {
    echo ""
    echo "kennungen: ROT - backend/Dockerfile nagelt uid/gid nicht fest."
    echo "  Ohne --uid/--gid vergibt adduser --system die naechste freie Kennung."
    echo "  Die Zahl im README (chown -R ${r_paar:-?}) ist dann geraten statt zugesichert."
  } >&2
  fehler=1
elif [ "$d_uid:$d_gid" != "$r_paar" ]; then
  {
    echo ""
    echo "kennungen: ROT - Dockerfile und README nennen verschiedene Kennungen."
    echo "  backend/Dockerfile: $d_uid:$d_gid"
    echo "  README.md:          ${r_paar:-keine gefunden}"
    echo "  Wer 'chown' nach der falschen Zahl ausfuehrt, kann nachher nicht schreiben."
  } >&2
  fehler=1
fi

# Geteilte Belegordner: dieselbe Gruppenkennung wie in den anderen Stacks (SYSTEMLANDSCHAFT § 8).
if ! grep -q 'EXTRA_GROUP_GID=2000' backend/Dockerfile || \
   ! grep -q 'EXTRA_GROUP_NAME=belegordner' backend/Dockerfile; then
  {
    echo ""
    echo "gruppe: ROT - backend/Dockerfile fehlt die gemeinsame Gruppe (GID 2000)."
    echo "  Stufe 6 braucht dieselbe Gruppenkennung in allen drei Abbildern."
  } >&2
  fehler=1
fi

# Ein Platzhalter, der als Vorgabe funktioniert, ist ein Kennwort im Quelltext.
if grep -qE '\$\{DB_[A-Z_]*PASSWORD:-' docker-compose.yml; then
  {
    echo ""
    echo "compose: ROT - docker-compose.yml setzt Postgres-Passwoerter still auf Vorgabe."
    echo "  Pflichtvariablen mit :? — s. .env.example (wie feiyr/tantiemen)."
  } >&2
  fehler=1
fi

exit "$fehler"
