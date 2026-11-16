#!/bin/sh
# Tests fuer die Umzugsfaehigkeit der Compose-Dateien: Adresse und Port der App aus der
# Umgebung (Vorgabe 127.0.0.1), kein Host-Port fuer die Datenbank, Zusatzdatei fuer den
# DB-Port, Gesundheitsroute im Healthcheck. Die Dateien liegen in der Repo-Wurzel, der
# Testcontainer sieht nur backend/ - deshalb ein Shell-Test wie test_wachen.sh.

set -u
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
      GIT_COMMON_DIR GIT_NAMESPACE GIT_QUARANTINE_PATH

hier=$(cd "$(dirname "$0")" && pwd)
wache="$hier/wachen.sh"
wurzel=$(cd "$hier/.." && pwd)
fehl=0

werkstatt=$(mktemp -d "${TMPDIR:-/tmp}/umzug.XXXXXX") \
    && [ -n "$werkstatt" ] && [ -d "$werkstatt" ] || {
    echo "ABBRUCH: keine Werkstatt anlegbar (mktemp) - die Suite laeuft nicht." >&2
    exit 2
}
trap 'rm -rf "$werkstatt"' EXIT

ergebnis() { # $1 Name  $2 0=gruen 1=rot  $3 Hinweis
    if [ "$2" -eq 0 ]; then
        echo "gruen $1"
    else
        echo "ROT  $1: $3" >&2
        fehl=1
    fi
}

# --- Teil A: die Netz-Wache versteht die Variablenform ------------------------------
# $1 Name  $2 erwartet (rot|gruen)  $3 Portzeile
pruefe_netzwache() {
    repo=$(mktemp -d "$werkstatt/repo.XXXXXX") && [ -d "$repo" ] || exit 2
    git -C "$repo" init -q
    git -C "$repo" config user.name probe
    git -C "$repo" config user.email probe@example.invalid
    mkdir -p "$repo/backend"
    printf 'FROM scratch\n' > "$repo/backend/Dockerfile"
    printf 'chown -R 100:101 storage\n' > "$repo/README.md"
    printf 'services:\n  app:\n    ports:\n      - %s\n' "$3" > "$repo/docker-compose.yml"
    git -C "$repo" add -A
    git -C "$repo" commit -q -m probe
    aus=$( cd "$repo" && "$wache" 2>&1 )
    if printf '%s' "$aus" | grep -qF -- "netz: ROT"; then ist=rot; else ist=gruen; fi
    if [ "$ist" = "$2" ]; then ergebnis "$1" 0 ""; else
        ergebnis "$1" 1 "erwartet $2, war $ist"; fi
}

pruefe_netzwache variable_mit_loopback_vorgabe_ist_gruen gruen \
    '"${APP_BIND:-127.0.0.1}:${APP_PORT:-3000}:3000"'
pruefe_netzwache variable_mit_offener_vorgabe_ist_rot rot \
    '"${APP_BIND:-0.0.0.0}:${APP_PORT:-3000}:3000"'
pruefe_netzwache variable_ohne_vorgabe_ist_rot rot \
    '"${APP_BIND}:${APP_PORT:-3000}:3000"'
pruefe_netzwache variable_mit_leerer_vorgabe_ist_rot rot \
    '"${APP_BIND:-}:${APP_PORT:-3000}:3000"'
pruefe_netzwache offener_port_bleibt_rot rot '"3000:3000"'
pruefe_netzwache loopback_literal_bleibt_gruen gruen '"127.0.0.1:3000:3000"'

# --- Teil B: die lebenden Dateien -----------------------------------------------------
compose="$wurzel/docker-compose.yml"
zusatz="$wurzel/docker-compose.db-port.yml"
beispiel="$wurzel/.env.example"

app_ports=$(awk '/^  app:/{a=1;next} /^  [a-z]/{a=0} a&&/^      - "/{print}' "$compose")
[ "$app_ports" = '      - "${APP_BIND:-127.0.0.1}:${APP_PORT:-3000}:3000"' ]
ergebnis app_port_aus_der_umgebung_mit_loopback $? "Portzeile der App: $app_ports"

grep -q '^#\?[[:space:]]*APP_BIND=127.0.0.1' "$beispiel" && grep -q '^#\?[[:space:]]*APP_PORT=3000' "$beispiel"
ergebnis env_beispiel_nennt_app_bind_und_port $? "APP_BIND/APP_PORT fehlen in der Beispieldatei"

db_ports=$(awk '/^  db:/{d=1;next} /^  [a-z]/{d=0} d&&/^    ports:/{print}' "$compose")
[ -z "$db_ports" ]
ergebnis db_hat_keinen_host_port $? "db-Dienst hat noch ports:"

grep -q '"${DB_BIND:-127.0.0.1}:${DB_PORT:-5432}:5432"' "$zusatz" 2>/dev/null
ergebnis zusatzdatei_oeffnet_db_port_nur_loopback $? "docker-compose.db-port.yml fehlt oder falsch"

grep -q '^#\?[[:space:]]*DB_BIND=' "$beispiel" && grep -q '^#\?[[:space:]]*DB_PORT=' "$beispiel"
ergebnis env_beispiel_nennt_db_bind_und_port $? "DB_BIND/DB_PORT fehlen in der Beispieldatei"

aus=$( cd "$wurzel" && "$wache" 2>&1 )
if printf '%s' "$aus" | grep -qF -- "netz: ROT"; then rc=1; else rc=0; fi
ergebnis echte_wurzel_ohne_netz_rot $rc "$aus"

[ "$fehl" -eq 0 ] && echo "test_compose_umzug: alle gruen"
exit "$fehl"
