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
# Geprueft werden: docker-compose.yml allein, mit docker-compose.uebergabe.yml, mit
# docker-compose.db-port.yml und mit docker-compose.integration.yml, soweit vorhanden.
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
for f in docker-compose.yml docker-compose.uebergabe.yml docker-compose.db-port.yml \
         docker-compose.integration.yml; do
    [ -f "$f" ] && cp "$f" "$tmp/$f"
done
: > "$tmp/.env"
: > "$tmp/integration.env"
: > "$tmp/funde.txt"

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
    python3 "$here/compose_ports_pruefen.py" "$tmp/out.json" "$name" >> "$tmp/funde.txt"
    rc=$?
    [ "$rc" -eq 2 ] && nicht_gemessen "Ergebnis von $name nicht lesbar."
    return 0
}

messen "docker-compose.yml" -f "$tmp/docker-compose.yml"
for zusatz in uebergabe db-port integration; do
    [ -f "docker-compose.$zusatz.yml" ] || continue
    messen "docker-compose.yml + $zusatz" \
        -f "$tmp/docker-compose.yml" -f "$tmp/docker-compose.$zusatz.yml"
done

if [ -s "$tmp/funde.txt" ]; then
    {
        echo ""
        echo "netz: ROT - Port ohne 127.0.0.1 veroeffentlicht."
        echo "  Erlaubt ist nur host_ip 127.0.0.1 (auch \"[::]\", Langform, network_mode: host zaehlen)."
        echo "  Die Anwendung hat keine Anmeldung; gemeint ist fast immer \"127.0.0.1:3000:3000\"."
        cat "$tmp/funde.txt"
    } >&2
    exit 1
fi
exit 0
