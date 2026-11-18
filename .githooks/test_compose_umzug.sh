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

# --- Teil A: die Netz-Wache misst die Normalform (netzwache.sh) ---------------------
# Die Wache fragt Compose nach der JSON-Normalform; die Fixtures sind deshalb gueltige
# Compose-Dateien (mit image). Rot heisst: Meldung "netz: ROT".

neues_repo() {
    repo=$(mktemp -d "$werkstatt/repo.XXXXXX") && [ -d "$repo" ] || exit 2
    git -C "$repo" init -q
    git -C "$repo" config user.name probe
    git -C "$repo" config user.email probe@example.invalid
    mkdir -p "$repo/backend"
    printf 'FROM scratch\n' > "$repo/backend/Dockerfile"
    printf 'chown -R 100:101 storage\n' > "$repo/README.md"
}

# $1 Name  $2 erwartet (rot|gruen)  $3 Dienstkoerper (YAML, eingerueckt unter app:)
# Zusatzumgebung: ENV_ZUSATZ (z. B. "APP_BIND=0.0.0.0 NETZWACHE_MIT_UMGEBUNG=1")
pruefe_dienst() {
    neues_repo
    printf 'services:\n  app:\n    image: probe\n%s\n' "$3" > "$repo/docker-compose.yml"
    git -C "$repo" add -A
    git -C "$repo" commit -q -m probe
    # shellcheck disable=SC2086
    aus=$( cd "$repo" && env ${ENV_ZUSATZ:-NETZWACHE_X=1} "$wache" 2>&1 )
    if printf '%s' "$aus" | grep -qF -- "netz: ROT"; then ist=rot
    elif printf '%s' "$aus" | grep -qF -- "NICHT GEMESSEN"; then ist=ungemessen
    else ist=gruen; fi
    if [ "$ist" = "$2" ]; then ergebnis "$1" 0 ""; else
        ergebnis "$1" 1 "erwartet $2, war $ist: $aus"; fi
}

p() { printf '    ports:\n      - %s' "$1"; }

pruefe_dienst variable_mit_loopback_vorgabe_ist_gruen gruen \
    "$(p '"${APP_BIND:-127.0.0.1}:${APP_PORT:-3000}:3000"')"
pruefe_dienst variable_mit_offener_vorgabe_ist_rot rot \
    "$(p '"${APP_BIND:-0.0.0.0}:${APP_PORT:-3000}:3000"')"
pruefe_dienst variable_ohne_vorgabe_ist_rot rot "$(p '"${APP_BIND}:${APP_PORT:-3000}:3000"')"
pruefe_dienst variable_mit_leerer_vorgabe_ist_rot rot "$(p '"${APP_BIND:-}:${APP_PORT:-3000}:3000"')"
pruefe_dienst offener_port_bleibt_rot rot "$(p '"3000:3000"')"
pruefe_dienst loopback_literal_bleibt_gruen gruen "$(p '"127.0.0.1:3000:3000"')"
# Die drei Luecken des alten Textmusters:
pruefe_dienst ipv6_alle_schnittstellen_ist_rot rot "$(p '"[::]:3000:3000"')"
pruefe_dienst einfache_anfuehrung_mit_variable_ist_rot rot "$(p "'\${X:-0.0.0.0}:3000:3000'")"
pruefe_dienst langform_target_published_ist_rot rot \
    "$(printf '    ports:\n      - target: 3000\n        published: "3000"')"
# Weitere Wege nach aussen:
pruefe_dienst langform_mit_fremder_host_ip_ist_rot rot \
    "$(printf '    ports:\n      - target: 3000\n        published: "3000"\n        host_ip: 192.0.2.1')"
pruefe_dienst langform_mit_loopback_ist_gruen gruen \
    "$(printf '    ports:\n      - target: 3000\n        published: "3000"\n        host_ip: 127.0.0.1')"
pruefe_dienst port_ohne_host_angabe_ist_rot rot "$(p '"3000"')"
pruefe_dienst network_mode_host_ist_rot rot "    network_mode: host"

# Verhalten bei gesetzter Umgebung: Standard misst die Vorgabe der Dateien (eine
# Betreiberumgebung blockiert keinen Push); mit NETZWACHE_MIT_UMGEBUNG=1 wird sie
# mitgemessen, und APP_BIND=0.0.0.0 ist dann rot.
LOOP='"${APP_BIND:-127.0.0.1}:${APP_PORT:-3000}:3000"'
ENV_ZUSATZ="APP_BIND=0.0.0.0" pruefe_dienst \
    gesetztes_app_bind_wird_standardmaessig_nicht_gemessen gruen "$(p "$LOOP")"
ENV_ZUSATZ="APP_BIND=0.0.0.0 NETZWACHE_MIT_UMGEBUNG=1" pruefe_dienst \
    gesetztes_app_bind_0000_ist_mit_umgebung_rot rot "$(p "$LOOP")"
ENV_ZUSATZ="NETZWACHE_MIT_UMGEBUNG=1" pruefe_dienst \
    ungesetztes_app_bind_ist_mit_umgebung_die_vorgabe_gruen gruen "$(p "$LOOP")"

# Zusatzdateien: die Wache misst auch die Kombinationen.
neues_repo
printf 'services:\n  db:\n    image: probe\n' > "$repo/docker-compose.yml"
printf 'services:\n  db:\n    ports:\n      - "5432:5432"\n' > "$repo/docker-compose.db-port.yml"
git -C "$repo" add -A
git -C "$repo" commit -q -m probe
aus=$( cd "$repo" && "$wache" 2>&1 )
printf '%s' "$aus" | grep -qF -- "netz: ROT"
ergebnis offene_zusatzdatei_db_port_ist_rot $? "$aus"

# Nicht gemessen ist nicht gruen: PATH ohne docker.
neues_repo
printf 'services:\n  app:\n    image: probe\n' > "$repo/docker-compose.yml"
git -C "$repo" add -A
git -C "$repo" commit -q -m probe
ohne="$werkstatt/ohne-docker"
mkdir -p "$ohne"
for pfad in /usr/bin/* /bin/*; do
    name=${pfad##*/}
    [ "$name" = docker ] && continue
    [ -e "$ohne/$name" ] || ln -s "$pfad" "$ohne/$name"
done
# Direkt netzwache.sh: ueber wachen.sh waere rc!=0 schon durch andere Wachen erfuellt.
aus=$( cd "$repo" && PATH="$ohne" /bin/sh "$hier/netzwache.sh" 2>&1 )
rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$aus" | grep -qF -- "NICHT GEMESSEN" \
   && ! printf '%s' "$aus" | grep -qF -- "netz: ROT"; then r=0; else r=1; fi
ergebnis fehlendes_docker_ist_nicht_gemessen_und_nicht_gruen $r "rc=$rc: $aus"

# Fehlende Messgrundlage ist nicht gruen: ein JSON ohne Dienste hat nichts gemessen.
# $1 Name  $2 JSON-Text
pruefe_ohne_messgrundlage() {
    datei="$werkstatt/grundlage.json"
    printf '%s' "$2" > "$datei"
    aus=$( python3 "$hier/compose_ports_pruefen.py" "$datei" probe 2>&1 )
    rc=$?
    if [ "$rc" -ne 0 ] && printf '%s' "$aus" | grep -qF -- "NICHT GEMESSEN"; then r=0; else r=1; fi
    ergebnis "$1" $r "rc=$rc: $aus"
}
pruefe_ohne_messgrundlage json_ohne_services_ist_nicht_gemessen '{}'
pruefe_ohne_messgrundlage json_mit_leeren_services_ist_nicht_gemessen '{"services": {}}'
pruefe_ohne_messgrundlage json_mit_services_als_liste_ist_nicht_gemessen '{"services": []}'

# netzwache.sh gibt das als "nicht gemessen" weiter, nicht als Fund und nicht als gruen.
neues_repo
printf 'services:\n  app:\n    image: probe\n' > "$repo/docker-compose.yml"
git -C "$repo" add -A
git -C "$repo" commit -q -m probe
attrappe="$werkstatt/attrappe-docker"
mkdir -p "$attrappe"
printf '%s\n' '#!/bin/sh' '[ "$2" = "version" ] && exit 0' "printf '{}'" > "$attrappe/docker"
chmod +x "$attrappe/docker"
aus=$( cd "$repo" && PATH="$attrappe:$PATH" /bin/sh "$hier/netzwache.sh" 2>&1 )
rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$aus" | grep -qF -- "NICHT GEMESSEN" \
   && ! printf '%s' "$aus" | grep -qF -- "netz: ROT"; then r=0; else r=1; fi
ergebnis netzwache_meldet_leere_messgrundlage_als_nicht_gemessen $r "rc=$rc: $aus"

# F1: das Inventar kommt aus git ls-files; jede Compose-Datei braucht eine Zuordnung.
# $1 Name  $2 erwartet (rot|gruen)  $3 Dateiname  $4 Inhalt (YAML)
pruefe_zusatzdatei() {
    neues_repo
    printf 'services:\n  app:\n    image: probe\n' > "$repo/docker-compose.yml"
    printf '%s\n' "$4" > "$repo/$3"
    git -C "$repo" add -A
    git -C "$repo" commit -q -m probe
    aus=$( cd "$repo" && "$wache" 2>&1 )
    if printf '%s' "$aus" | grep -qF -- "netz: ROT"; then ist=rot; else ist=gruen; fi
    if [ "$ist" = "$2" ]; then ergebnis "$1" 0 ""; else
        ergebnis "$1" 1 "erwartet $2, war $ist: $aus"; fi
}
LAN='services:
  app:
    ports:
      - "0.0.0.0:3000:3000"'
pruefe_zusatzdatei neue_lan_datei_mit_offenem_port_ist_rot rot docker-compose.lan.yml "$LAN"
pruefe_zusatzdatei neue_lan_datei_im_yaml_format_ist_rot rot docker-compose.lan.yaml "$LAN"
pruefe_zusatzdatei unbekannte_datei_ohne_ports_hat_keine_zuordnung_und_ist_rot rot \
    compose.override.yml 'services: {}'
pruefe_zusatzdatei dev_datei_ohne_ports_ist_gruen gruen docker-compose.dev.yml \
    'services:
  app:
    command: ["true"]'
pruefe_zusatzdatei dev_datei_mit_offenem_port_ist_rot rot docker-compose.dev.yml \
    'services:
  app:
    ports:
      - "3000:3000"'

# F3: Exit-Code und Ausgabe des Pruefers muessen zusammenpassen.
# $1 Name  $2 Exit-Code der Python-Attrappe (sie schreibt nur auf stderr)
pruefe_pruefer_attrappe() {
    neues_repo
    printf 'services:\n  app:\n    image: probe\n' > "$repo/docker-compose.yml"
    git -C "$repo" add -A
    git -C "$repo" commit -q -m probe
    py="$werkstatt/py-$2"
    mkdir -p "$py"
    printf '%s\n' '#!/bin/sh' 'echo "Traceback (simuliert)" >&2' "exit $2" > "$py/python3"
    chmod +x "$py/python3"
    aus=$( cd "$repo" && PATH="$py:$PATH" /bin/sh "$hier/netzwache.sh" 2>&1 )
    rc=$?
    if [ "$rc" -ne 0 ] && printf '%s' "$aus" | grep -qF -- "NICHT GEMESSEN" \
       && ! printf '%s' "$aus" | grep -qF -- "netz: ROT"; then r=0; else r=1; fi
    ergebnis "$1" $r "rc=$rc: $aus"
}
pruefe_pruefer_attrappe pruefer_rc1_ohne_fundzeile_ist_nicht_gemessen 1
pruefe_pruefer_attrappe pruefer_rc7_ist_nicht_gemessen 7

# U-R3-1: Exit 0 MIT Ausgabe widerspricht sich: nicht gemessen.
py0="$werkstatt/py-exit0-mit-ausgabe"
mkdir -p "$py0"
printf '%s\n' '#!/bin/sh' 'echo "  Fundzeile trotz Exit 0"' 'exit 0' > "$py0/python3"
chmod +x "$py0/python3"
neues_repo
printf 'services:\n  app:\n    image: probe\n' > "$repo/docker-compose.yml"
git -C "$repo" add -A
git -C "$repo" commit -q -m probe
aus=$( cd "$repo" && PATH="$py0:$PATH" /bin/sh "$hier/netzwache.sh" 2>&1 )
rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$aus" | grep -qF -- "NICHT GEMESSEN" \
   && ! printf '%s' "$aus" | grep -qF -- "netz: ROT"; then r=0; else r=1; fi
ergebnis pruefer_exit0_mit_ausgabe_ist_nicht_gemessen $r "rc=$rc: $aus"

# U-R3-2: eine in git eingetragene, aber auf der Platte fehlende Zusatzdatei ist nicht gemessen.
neues_repo
printf 'services:\n  app:\n    image: probe\n' > "$repo/docker-compose.yml"
printf 'services:\n  db:\n    image: probe\n' > "$repo/docker-compose.db-port.yml"
git -C "$repo" add -A
git -C "$repo" commit -q -m probe
rm "$repo/docker-compose.db-port.yml"
aus=$( cd "$repo" && /bin/sh "$hier/netzwache.sh" 2>&1 )
rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$aus" | grep -qF -- "NICHT GEMESSEN" \
   && ! printf '%s' "$aus" | grep -qF -- "netz: ROT"; then r=0; else r=1; fi
ergebnis fehlende_zusatzdatei_auf_der_platte_ist_nicht_gemessen $r "rc=$rc: $aus"

# "ausgenommen" braucht einen Grund. Die Zuordnung steht im Skript; der Test arbeitet an
# einer Kopie, in die er eine Zeile einfuegt.
# $1 Name  $2 Zeile fuer die Zuordnung  $3 erwartet (rot|gruen)
pruefe_ausnahme() {
    kopie="$werkstatt/hook-$1"
    mkdir -p "$kopie"
    cp "$hier/netzwache.sh" "$hier/compose_ports_pruefen.py" "$kopie/"
    awk -v zeile="$2" '/^        \*\) echo unbekannt/ { print zeile } { print }' \
        "$hier/netzwache.sh" > "$kopie/netzwache.sh"
    neues_repo
    printf 'services:\n  app:\n    image: probe\n' > "$repo/docker-compose.yml"
    printf '%s\n' "$LAN" > "$repo/docker-compose.lan.yml"
    git -C "$repo" add -A
    git -C "$repo" commit -q -m probe
    aus=$( cd "$repo" && /bin/sh "$kopie/netzwache.sh" 2>&1 )
    if printf '%s' "$aus" | grep -qF -- "netz: ROT"; then ist=rot; else ist=gruen; fi
    if [ "$ist" = "$3" ]; then ergebnis "$1" 0 ""; else
        ergebnis "$1" 1 "erwartet $3, war $ist: $aus"; fi
}
pruefe_ausnahme ausgenommen_mit_grund_wird_nicht_gemessen \
    '        docker-compose.lan.yml) echo "ausgenommen:nur im Labor" ;;' gruen
pruefe_ausnahme ausgenommen_mit_leerem_grund_ist_rot \
    '        docker-compose.lan.yml) echo "ausgenommen:" ;;' rot
pruefe_ausnahme ausgenommen_mit_blankem_grund_ist_rot \
    '        docker-compose.lan.yml) echo "ausgenommen:   " ;;' rot

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

grep -qF 'http://localhost:3000/gesundheit' "$compose"
ergebnis healthcheck_ruft_gesundheit $? "Healthcheck ruft nicht /gesundheit"

grep -q '"${DB_BIND:-127.0.0.1}:${DB_PORT:-5432}:5432"' "$zusatz" 2>/dev/null
ergebnis zusatzdatei_oeffnet_db_port_nur_loopback $? "docker-compose.db-port.yml fehlt oder falsch"

grep -q '^#\?[[:space:]]*DB_BIND=' "$beispiel" && grep -q '^#\?[[:space:]]*DB_PORT=' "$beispiel"
ergebnis env_beispiel_nennt_db_bind_und_port $? "DB_BIND/DB_PORT fehlen in der Beispieldatei"

# F4: das echte Repo. Gruen nur bei Exit 0 und ohne NICHT GEMESSEN; ohne docker meldet
# sich der Test ausdruecklich als "nicht gemessen" und ist nicht gruen.
# $1 Name  $2 PATH fuer den Lauf  $3 erwartet (gruen|ungemessen)
pruefe_wurzel() {
    aus=$( cd "$wurzel" && PATH="$2" /bin/sh "$hier/netzwache.sh" 2>&1 )
    rc=$?
    if printf '%s' "$aus" | grep -qF -- "NICHT GEMESSEN"; then ist=ungemessen
    elif [ "$rc" -eq 0 ]; then ist=gruen
    else ist=rot; fi
    if [ "$ist" = "$3" ]; then ergebnis "$1" 0 ""; else
        ergebnis "$1" 1 "erwartet $3, war $ist (rc=$rc): $aus"; fi
}
if command -v docker >/dev/null 2>&1; then
    pruefe_wurzel echte_wurzel_netz_gemessen_und_gruen "$PATH" gruen
else
    echo "NICHT GEMESSEN echte_wurzel_netz_gemessen_und_gruen: docker fehlt, Test nicht gruen" >&2
    fehl=1
fi
# Der Test selbst: ohne docker darf er nie gruen werden.
pruefe_wurzel echte_wurzel_ohne_docker_ist_nicht_gemessen "$ohne" ungemessen

[ "$fehl" -eq 0 ] && echo "test_compose_umzug: alle gruen"
exit "$fehl"
