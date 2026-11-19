#!/bin/sh
# Gemeinsame Hilfen fuer test_pre_push_stand.sh und test_gleichlauf_tor.sh.
# Per source einbinden; die einbindende Datei setzt $hier, $fehl, $leer.
# Diese Datei hat absichtlich kein test_-Praefix (Auslagerung wegen der
# 300-Zeilen-Grenze) und wird darum von der Umweg-Probe in
# test_pre_push_stand.sh mit gelesen: hier keine Umweg-Muster nennen.

# Wegwerf-Werkstatt mit Aufraeum-Falle; setzt $werkstatt. $1 Namensprefix.
werkstatt_anlegen() {
    werkstatt=$(mktemp -d "${TMPDIR:-/tmp}/$1.XXXXXX") \
        && [ -n "$werkstatt" ] && [ -d "$werkstatt" ] || {
        echo "ABBRUCH: keine Werkstatt anlegbar (mktemp) - nichts gemessen." >&2
        exit 2
    }
    trap 'rm -rf "$werkstatt"' EXIT
}

# Leeres Wegwerf-Repo. Eigenes .git, damit pipaudit.gleichlauf nicht vom
# umgebenden Klon kommt; eigener hooksPath, damit keine Hooks erben.
# Gibt den Pfad aus.
spiegel_repo_anlegen() {
    d=$(mktemp -d "$werkstatt/repo.XXXXXX") && [ -n "$d" ] && [ -d "$d" ] || {
        echo "ABBRUCH: kein Wegwerf-Repo anlegbar." >&2
        exit 2
    }
    git -C "$d" init -q
    git -C "$d" config user.name probe
    git -C "$d" config user.email probe@example.invalid
    git -C "$d" checkout -q -b main
    git -C "$d" config core.hooksPath "$werkstatt/keine-hooks"
    mkdir -p "$werkstatt/keine-hooks"
    printf '%s\n' "$d"
}

# Minimaldateien, unter denen wachen.sh gruen bleibt (vgl. test_wachen.sh).
schreib_gruen() {
    root=$1
    mkdir -p "$root/backend" "$root/.githooks"
    printf '%s\n' 'services:' '  app:' '    image: probe' > "$root/docker-compose.yml"
    printf '%s\n' \
        'FROM scratch' \
        'RUN adduser --system --uid 100 --gid 101 x' \
        'ENV EXTRA_GROUP_GID=2000 EXTRA_GROUP_NAME=belegordner' \
        > "$root/backend/Dockerfile"
    printf 'chown -R 100:101 storage\n' > "$root/README.md"
    printf '%s\n' \
        'services:' \
        '  app:' \
        '    volumes:' \
        '      - ./schluessel-integration:/app/schluessel:ro' \
        > "$root/docker-compose.integration.yml"
    printf '# ok\n' > "$root/hinweis.md"
}

schreib_rot_netz() {
    # Offener Port: wachen.sh netz: ROT
    printf '%s\n' \
        'services:' \
        '  app:' \
        '    image: probe' \
        '    ports:' \
        '      - "3000:3000"' \
        > "$1/docker-compose.yml"
}

# $1 Name  $2 Repo  $3 local_sha (gepusht)  $4 erwartet rc (0 oder ungleich 0)
# $5 Wortlaut der erwartet wird (leer = egal)
rufe_hook() {
    name=$1
    repo=$2
    lokal_sha=$3
    erwartet_rc=$4
    wortlaut=$5
    aus="$werkstatt/$name.aus"
    ( cd "$repo" && printf 'refs/heads/feature %s refs/heads/feature %s\n' \
        "$lokal_sha" "$leer" \
        | env DATENWACHE_UEBERSTIMMT=1 PRE_PUSH_TEST_CMD='echo suite-attrappe' \
            bash .githooks/pre-push origin unused-url ) >"$aus" 2>&1
    rc=$?
    if [ "$erwartet_rc" -eq 0 ]; then
        if [ "$rc" -ne 0 ]; then
            echo "ROT  $name: rc=$rc, erwartet 0" >&2
            sed 's/^/      /' "$aus" | tail -20 >&2
            fehl=1
            return
        fi
    else
        if [ "$rc" -eq 0 ]; then
            echo "ROT  $name: rc=0, erwartet Abbruch" >&2
            sed 's/^/      /' "$aus" | tail -20 >&2
            fehl=1
            return
        fi
    fi
    if [ -n "$wortlaut" ] && ! grep -qF -- "$wortlaut" "$aus"; then
        echo "ROT  $name: Wortlaut fehlt: $wortlaut" >&2
        sed 's/^/      /' "$aus" | tail -20 >&2
        fehl=1
        return
    fi
    echo "gruen $name"
}
