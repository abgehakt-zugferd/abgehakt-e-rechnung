#!/bin/sh
# Charakterisierungstests fuer die Schluessel-Wachen in wachen.sh
# (#204 Mount der Testinstanz, #236 nichts unter backend/schluessel/ versioniert
# ausser README.md). Die Wachen lesen Dateien in der Repo-Wurzel; der
# Testcontainer sieht nur backend/. Deshalb Wegwerf-Repos wie bei
# test_datenwache.sh, nicht pytest.

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

# $1 Name  $2 erwartet Wortlaut (leer = keine Zeile schluessel: ROT)
# Weitere Argumente: Mount-Zeilen fuer /app/schluessel (keine = Mount fehlt).
pruefe_schluessel_meldung() {
    name=$1
    erwartet=$2
    shift 2
    repo=$(neues_repo)
    {
        echo "services:"
        echo "  app:"
        echo "    volumes:"
        echo "      - ./storage-integration:/app/storage"
        for m in "$@"; do
            echo "      - $m"
        done
    } > "$repo/docker-compose.integration.yml"
    aus=$( cd "$repo" && "$wache" 2>&1 )
    rc=$?
    if [ -n "$erwartet" ]; then
        if [ "$rc" -eq 0 ] || ! printf '%s' "$aus" | grep -qF -- "$erwartet"; then
            echo "ROT  $name: erwartet Meldung '$erwartet' und rc!=0 (rc=$rc)" >&2
            echo "$aus" >&2
            fehl=1
            return
        fi
        echo "gruen $name"
    else
        if printf '%s' "$aus" | grep -qF -- "schluessel: ROT"; then
            echo "ROT  $name: unerwartete schluessel: ROT" >&2
            echo "$aus" >&2
            fehl=1
            return
        fi
        echo "gruen $name"
    fi
}

pruefe_schluessel_meldung falscher_mount_ist_rot \
    "schluessel: ROT" \
    "./backend/schluessel:/app/schluessel:ro"
pruefe_schluessel_meldung fehlender_mount_ist_rot \
    "schluessel: ROT"
pruefe_schluessel_meldung richtiger_mount_ist_gruen \
    "" \
    "./schluessel-integration:/app/schluessel:ro"
pruefe_schluessel_meldung richtiger_mount_mit_anfuehrungszeichen_ist_gruen \
    "" \
    '"./schluessel-integration:/app/schluessel:ro"'
pruefe_schluessel_meldung zwei_mounts_einer_falsch_ist_rot \
    "schluessel: ROT" \
    "./schluessel-integration:/app/schluessel:ro" \
    "./backend/schluessel:/app/schluessel:ro"

# #236: unter backend/schluessel/ darf ausser README.md nichts versioniert sein.
# $1 Name  $2 erwartet Wortlaut (leer = keine Zeile schluesselordner: ROT)
# $3 relativer Pfad unter backend/schluessel/ (Dateiinhalt egal)
# Gruen heisst nur: keine schluesselordner: ROT-Zeile. rc und andere Wachen
# (kennungen/gruppe am Minimal-Dockerfile) bleiben bewusst ungeprueft.
pruefe_schluesselordner_meldung() {
    name=$1
    erwartet=$2
    rel=$3
    repo=$(neues_repo)
    {
        echo "services:"
        echo "  app:"
        echo "    volumes:"
        echo "      - ./storage-integration:/app/storage"
        echo "      - ./schluessel-integration:/app/schluessel:ro"
    } > "$repo/docker-compose.integration.yml"
    mkdir -p "$repo/backend/schluessel/$(dirname "$rel")"
    printf 'probe\n' > "$repo/backend/schluessel/$rel"
    git -C "$repo" add "backend/schluessel/$rel"
    git -C "$repo" commit -q -m "probe"
    aus=$( cd "$repo" && "$wache" 2>&1 )
    rc=$?
    if [ -n "$erwartet" ]; then
        if [ "$rc" -eq 0 ] || ! printf '%s' "$aus" | grep -qF -- "$erwartet"; then
            echo "ROT  $name: erwartet Meldung '$erwartet' und rc!=0 (rc=$rc)" >&2
            echo "$aus" >&2
            fehl=1
            return
        fi
        echo "gruen $name"
    else
        if printf '%s' "$aus" | grep -qF -- "schluesselordner: ROT"; then
            echo "ROT  $name: unerwartete schluesselordner: ROT" >&2
            echo "$aus" >&2
            fehl=1
            return
        fi
        echo "gruen $name"
    fi
}

pruefe_schluesselordner_meldung versionierte_pub_ist_rot \
    "schluesselordner: ROT" \
    "absender/probe.pub"
pruefe_schluesselordner_meldung nur_readme_ist_gruen \
    "" \
    "README.md"

# Lebende Wurzel: dieselbe Wache wie in CI und Hook, kein zweiter Parser.
aus_wurzel=$( cd "$wurzel" && "$wache" 2>&1 )
if printf '%s' "$aus_wurzel" | grep -qF -- "schluessel: ROT"; then
    echo "ROT  echte_wurzel_ohne_schluessel_rot: schluessel: ROT in der Repo-Wurzel" >&2
    echo "$aus_wurzel" >&2
    fehl=1
elif printf '%s' "$aus_wurzel" | grep -qF -- "schluesselordner: ROT"; then
    echo "ROT  echte_wurzel_ohne_schluessel_rot: schluesselordner: ROT in der Repo-Wurzel" >&2
    echo "$aus_wurzel" >&2
    fehl=1
else
    echo "gruen echte_wurzel_ohne_schluessel_rot"
fi

[ "$fehl" -eq 0 ] && echo "test_wachen: alle gruen"
exit "$fehl"
