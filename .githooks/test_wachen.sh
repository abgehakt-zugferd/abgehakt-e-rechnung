#!/bin/sh
# Charakterisierungstests fuer die Schluessel-Mount-Wache in wachen.sh (#204).
# Die Wache liest Dateien in der Repo-Wurzel; der Testcontainer sieht nur backend/.
# Deshalb Wegwerf-Repos wie bei test_datenwache.sh, nicht pytest.

set -u
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
      GIT_COMMON_DIR GIT_NAMESPACE GIT_QUARANTINE_PATH

hier=$(cd "$(dirname "$0")" && pwd)
wache="$hier/wachen.sh"
fehl=0
wurzel=$(cd "$hier/.." && pwd)

werkstatt=$(mktemp -d "${TMPDIR:-/tmp}/wachen.XXXXXX") \
    && [ -n "$werkstatt" ] && [ -d "$werkstatt" ] || {
    echo "ABBRUCH: keine Werkstatt anlegbar (mktemp) - die Suite laeuft nicht." >&2
    exit 2
}
trap 'rm -rf "$werkstatt"' EXIT

neues_repo() {
    d=$(mktemp -d "$werkstatt/repo.XXXXXX") && [ -n "$d" ] && [ -d "$d" ] || {
        echo "ABBRUCH: kein Wegwerf-Repo in der Werkstatt anlegbar." >&2
        exit 2
    }
    git -C "$d" init -q
    git -C "$d" config user.name probe
    git -C "$d" config user.email probe@example.invalid
    mkdir -p "$d/backend"
    # Minimaldateien, damit die anderen Wachen nicht an fehlenden Pfaden abbrechen.
    printf 'services: {}\n' > "$d/docker-compose.yml"
    printf 'FROM scratch\n' > "$d/backend/Dockerfile"
    printf 'chown -R 100:101 storage\n' > "$d/README.md"
    printf '%s\n' "$d"
}

# $1 Name  $2 Mount-Zeile (leer = kein Mount)  $3 erwartet Wortlaut (leer = darf nicht)
pruefe_schluessel_meldung() {
    repo=$(neues_repo)
    {
        echo "services:"
        echo "  app:"
        echo "    volumes:"
        echo "      - ./storage-integration:/app/storage"
        if [ -n "$2" ]; then
            echo "      - $2"
        fi
    } > "$repo/docker-compose.integration.yml"
    aus=$( cd "$repo" && "$wache" 2>&1 )
    rc=$?
    if [ -n "$3" ]; then
        if [ "$rc" -eq 0 ] || ! printf '%s' "$aus" | grep -qF -- "$3"; then
            echo "ROT  $1: erwartet Meldung '$3' und rc!=0 (rc=$rc)" >&2
            echo "$aus" >&2
            fehl=1
            return
        fi
        echo "gruen $1"
    else
        if printf '%s' "$aus" | grep -qF -- "schluessel: ROT"; then
            echo "ROT  $1: unerwartete schluessel: ROT" >&2
            echo "$aus" >&2
            fehl=1
            return
        fi
        echo "gruen $1"
    fi
}

pruefe_schluessel_meldung falscher_mount_ist_rot \
    "./backend/schluessel:/app/schluessel:ro" \
    "schluessel: ROT"
pruefe_schluessel_meldung fehlender_mount_ist_rot \
    "" \
    "schluessel: ROT"
pruefe_schluessel_meldung richtiger_mount_ohne_schluessel_rot \
    "./schluessel-integration:/app/schluessel:ro" \
    ""

# Lebende Compose-Datei: jeder Mount auf /app/schluessel muss die Probequelle haben.
# Fehlt der Mount, zaehlt das als ROT (kein stiller Erfolg bei leerer Treffermenge).
lebende_quellen=$(awk '
    /^[[:space:]]*#/ { next }
    match($0, /:\/app\/schluessel/) {
        zeile = $0
        sub(/^[[:space:]]*-[[:space:]]*"?/, "", zeile)
        sub(/:\/app\/schluessel.*/, "", zeile)
        sub(/"$/, "", zeile)
        print zeile
        gefunden = 1
    }
    END { if (!gefunden) exit 1 }
' "$wurzel/docker-compose.integration.yml")
awk_rc=$?
if [ "$awk_rc" -ne 0 ] || [ -z "$lebende_quellen" ]; then
    echo "ROT  lebende_compose_hat_schluessel_mount: kein Mount auf /app/schluessel" >&2
    fehl=1
else
    lebende_ok=1
    while IFS= read -r quelle; do
        [ -z "$quelle" ] && continue
        if [ "$quelle" != "./schluessel-integration" ]; then
            echo "ROT  lebende_compose_quelle: '$quelle' statt ./schluessel-integration" >&2
            lebende_ok=0
            fehl=1
        fi
    done <<EOF
$lebende_quellen
EOF
    [ "$lebende_ok" -eq 1 ] && echo "gruen lebende_compose_quelle"
fi

[ "$fehl" -eq 0 ] && echo "test_wachen: alle gruen"
exit "$fehl"
