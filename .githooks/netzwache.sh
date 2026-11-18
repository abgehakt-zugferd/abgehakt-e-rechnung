#!/bin/sh
# Netz-Wache: veroeffentlicht eine Compose-Kombination einen Port an etwas anderes als
# 127.0.0.1? Die Anwendung hat keine Anmeldung (SECURITY.md); wer im selben Netz sitzt,
# saehe die Rechnungen und lade den GoBD-Export.
#
# Gemessen wird die NORMALFORM, nicht der Text: die JSON-Ausgabe von `compose config`
# loest Kurz- und Langform, beide Anfuehrungszeichen, "[::]:", Variablen und
# `network_mode: host` selbst auf. Ein Textmuster (awk) sah das nicht. Die Regel ist eine
# Positivliste (compose_ports_pruefen.py): nur host_ip 127.0.0.1 ist gruen.
#
# Das Inventar kommt aus `git ls-files` (Muster *compose*.yml und *compose*.yaml). Jede
# Datei braucht eine Zuordnung (Funktion zuordnung unten): "basis" (docker-compose.yml,
# wird allein geprueft), "zusatz" (wird zusammen mit der Basis geprueft) oder "ausgenommen"
# mit Grund. Eine Datei ohne Zuordnung ist ROT: wer eine neue Compose-Datei anlegt, muss
# hier entscheiden, ob sie geprueft wird. docker-compose.dev.yml ist "zusatz": sie
# veroeffentlicht heute keinen Port, und ein kuenftiger faende die Wache.
#
# Gemessen wird, was AUSGELIEFERT wird: die Variablen APP_BIND, APP_PORT, DB_BIND,
# DB_PORT und COMPOSE_FILE des Aufrufers werden bewusst entfernt, damit die Vorgabe der
# Dateien zaehlt. Die Umgebung eines Betreibers ist seine Entscheidung (docs/BETRIEB-UMZUG.md)
# und soll keinen Push blockieren oder das Ergebnis von Rechner zu Rechner aendern.
# Wer seine eigene Umgebung messen will: NETZWACHE_MIT_UMGEBUNG=1.
#
# Die Dateien werden in ein Wegwerf-Verzeichnis kopiert, mit leeren `.env` und
# `integration.env`: die echte Umgebungsdatei wird weder gelesen noch gebraucht.
# Pflichtvariablen (`${X:?...}`) bekommen Platzhalter nur in der Umgebung dieses Aufrufs.
#
# Nicht gemessen (docker, compose, python3 oder die Compose-Datei fehlen, der Aufruf
# scheitert) ist NICHT gruen: Meldung "netz: NICHT GEMESSEN" und Exit 1.

here=$(CDPATH= cd "$(dirname "$0")" && pwd)

nicht_gemessen() {
    echo "" >&2
    echo "netz: NICHT GEMESSEN - $1" >&2
    echo "  Die Netzbindung ist ungeprueft; das zaehlt nicht als bestanden." >&2
    exit 1
}

[ -f docker-compose.yml ] || nicht_gemessen "docker-compose.yml fehlt."
command -v docker >/dev/null 2>&1 || nicht_gemessen "docker fehlt im PATH."
docker compose version >/dev/null 2>&1 || nicht_gemessen "docker compose ist nicht verfuegbar."
command -v python3 >/dev/null 2>&1 || nicht_gemessen "python3 fehlt im PATH."

tmp=$(mktemp -d "${TMPDIR:-/tmp}/netzwache.XXXXXX") && [ -d "$tmp" ] \
    || nicht_gemessen "keine Werkstatt anlegbar (mktemp)."
trap 'rm -rf "$tmp"' EXIT

# Zuordnung je Compose-Datei: basis | zusatz | ausgenommen:<Grund> | unbekannt
zuordnung() {
    case "$1" in
        docker-compose.yml) echo basis ;;
        docker-compose.dev.yml | docker-compose.uebergabe.yml | \
        docker-compose.db-port.yml | docker-compose.integration.yml) echo zusatz ;;
        # Bewusst ausgenommene Dateien hier eintragen, mit nicht leerem Grund:
        #   datei.yml) echo "ausgenommen:Grund" ;;
        *) echo unbekannt ;;
    esac
}

inventar=$(git ls-files '*compose*.yml' '*compose*.yaml') \
    || nicht_gemessen "git ls-files scheiterte (kein Git-Repository?)."
: > "$tmp/funde.txt"
: > "$tmp/zusaetze.txt"
: > "$tmp/ohne_zuordnung.txt"
for f in $inventar; do
    art=$(zuordnung "$f")
    case "$art" in
        basis) ;;
        zusatz) printf '%s\n' "$f" >> "$tmp/zusaetze.txt" ;;
        ausgenommen:*)
            # Eine Ausnahme ohne Grund ist keine Entscheidung, sondern eine Luecke.
            grund=${art#ausgenommen:}
            if [ -z "$(printf '%s' "$grund" | tr -d '[:space:]')" ]; then
                printf '  %s (ausgenommen ohne Grund)\n' "$f" >> "$tmp/ohne_zuordnung.txt"
            fi
            continue ;;
        *) printf '  %s\n' "$f" >> "$tmp/ohne_zuordnung.txt"; continue ;;
    esac
    # In git eingetragen, aber nicht auf der Platte: nichts gemessen, nicht uebersprungen.
    [ -f "$f" ] || nicht_gemessen "$f steht in git, fehlt aber auf der Platte."
    cp "$f" "$tmp/$f"
done
: > "$tmp/.env"
: > "$tmp/integration.env"

# $1 Bezeichnung, weitere Argumente: -f Datei ...
messen() {
    name=$1
    shift
    if [ "${NETZWACHE_MIT_UMGEBUNG:-0}" = "1" ]; then
        loeschen="-u NETZWACHE_LEER"
    else
        loeschen="-u APP_BIND -u APP_PORT -u DB_BIND -u DB_PORT -u COMPOSE_FILE -u COMPOSE_PROFILES"
    fi
    # shellcheck disable=SC2086
    env $loeschen \
        DB_BOOTSTRAP_PASSWORD=platzhalter DB_PASSWORD=platzhalter DB_APP_PASSWORD=platzhalter \
        ZEMP_UEBERGABEN=/platzhalter UEBERGABEN_ORDNER=/platzhalter \
        TESTINSTANZ_MAIL_TO=platzhalter@example.invalid \
        docker compose --project-directory "$tmp" "$@" config --format json \
        > "$tmp/out.json" 2> "$tmp/err.txt" \
        || nicht_gemessen "der Compose-Aufruf scheiterte ($name): $(head -n 3 "$tmp/err.txt")"
    python3 "$here/compose_ports_pruefen.py" "$tmp/out.json" "$name" \
        > "$tmp/neu.txt" 2> "$tmp/pyerr.txt"
    rc=$?
    # Exit-Code und Ausgabe muessen zusammenpassen: 0 ohne Ausgabe = gruen, 1 mit
    # Fundzeile = Fund; alles andere (auch ein Traceback mit Exit 1) ist nicht gemessen.
    case "$rc" in
        0) [ ! -s "$tmp/neu.txt" ] \
            || nicht_gemessen "Pruefer meldete Ausgabe bei Exit 0 ($name)." ;;
        1) [ -s "$tmp/neu.txt" ] \
            || nicht_gemessen "Pruefer endete mit Exit 1 ohne Fundzeile ($name): $(head -n 3 "$tmp/pyerr.txt")"
           cat "$tmp/neu.txt" >> "$tmp/funde.txt" ;;
        *) nicht_gemessen "Pruefer endete mit Exit $rc ($name): $(head -n 3 "$tmp/pyerr.txt")" ;;
    esac
    return 0
}

messen "docker-compose.yml" -f "$tmp/docker-compose.yml"
while IFS= read -r zusatz; do
    [ -n "$zusatz" ] || continue
    [ -f "$tmp/$zusatz" ] || continue
    messen "docker-compose.yml + $zusatz" -f "$tmp/docker-compose.yml" -f "$tmp/$zusatz"
done < "$tmp/zusaetze.txt"

rot=0
if [ -s "$tmp/ohne_zuordnung.txt" ]; then
    {
        echo ""
        echo "netz: ROT - Compose-Datei ohne Zuordnung:"
        cat "$tmp/ohne_zuordnung.txt"
        echo "  In .githooks/netzwache.sh (zuordnung) als zusatz eintragen oder mit Grund ausnehmen."
    } >&2
    rot=1
fi
if [ -s "$tmp/funde.txt" ]; then
    {
        echo ""
        echo "netz: ROT - Port ohne 127.0.0.1 veroeffentlicht."
        echo "  Erlaubt ist nur host_ip 127.0.0.1 (auch \"[::]\", Langform, network_mode: host zaehlen)."
        echo "  Die Anwendung hat keine Anmeldung; gemeint ist fast immer \"127.0.0.1:3000:3000\"."
        cat "$tmp/funde.txt"
    } >&2
    rot=1
fi
exit "$rot"
