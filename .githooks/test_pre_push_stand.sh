#!/bin/sh
# Charakterisierung: pre-push prueft den gepushten Commit, nicht den Checkout (#219).
#
# Typischer Fehlablauf: aus einem geparkten Worktree `git push origin feature`,
# waehrend HEAD ein anderer (gruener) Stand ist. Ohne Export prueft der Hook den
# Checkout und winkt roten Code durch.
#
# Suite ueber PRE_PUSH_TEST_CMD als Attrappe (Naht nur fuer Tests); Wachen echt.

set -u
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
      GIT_COMMON_DIR GIT_NAMESPACE GIT_QUARANTINE_PATH

hier=$(cd "$(dirname "$0")" && pwd)
fehl=0
leer=0000000000000000000000000000000000000000

werkstatt=$(mktemp -d "${TMPDIR:-/tmp}/pre-push-stand.XXXXXX") \
    && [ -n "$werkstatt" ] && [ -d "$werkstatt" ] || {
    echo "ABBRUCH: keine Werkstatt anlegbar (mktemp) - nichts gemessen." >&2
    exit 2
}
trap 'rm -rf "$werkstatt"' EXIT

# Minimaldateien, unter denen wachen.sh gruen bleibt (vgl. test_wachen.sh).
schreib_gruen() {
    root=$1
    mkdir -p "$root/backend" "$root/.githooks"
    printf '%s\n' 'services: {}' > "$root/docker-compose.yml"
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
        '    ports:' \
        '      - "3000:3000"' \
        > "$1/docker-compose.yml"
}

neues_repo() {
    d=$(mktemp -d "$werkstatt/repo.XXXXXX") && [ -n "$d" ] && [ -d "$d" ] || {
        echo "ABBRUCH: kein Wegwerf-Repo anlegbar." >&2
        exit 2
    }
    git -C "$d" init -q
    git -C "$d" config user.name probe
    git -C "$d" config user.email probe@example.invalid
    git -C "$d" config core.hooksPath "$werkstatt/keine-hooks"
    mkdir -p "$werkstatt/keine-hooks"
    # Hook unter Test: lebende Skripte, nicht eine zweite Abschrift der Regeln.
    mkdir -p "$d/.githooks"
    cp "$hier/pre-push" "$d/.githooks/pre-push"
    cp "$hier/datenwache.sh" "$d/.githooks/datenwache.sh"
    cp "$hier/wachen.sh" "$d/.githooks/wachen.sh"
    # Hilfsskript, sobald vorhanden (nach Implementierung); fehlend = alter Hook.
    if [ -f "$hier/pre-push-stand.sh" ]; then
        cp "$hier/pre-push-stand.sh" "$d/.githooks/pre-push-stand.sh"
        chmod +x "$d/.githooks/pre-push-stand.sh"
    fi
    chmod +x "$d/.githooks/pre-push" "$d/.githooks/datenwache.sh" "$d/.githooks/wachen.sh"
    printf '%s\n' "$d"
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

# --- Fall A: Checkout gruen, gepushter Commit rot → Push muss fallen ----------
repo_a=$(neues_repo)
schreib_gruen "$repo_a"
git -C "$repo_a" add -A
git -C "$repo_a" commit -qm gruen-checkout
# Feature-Commit mit offenem Port, HEAD bleibt auf gruenem Checkout.
git -C "$repo_a" checkout -q -b feature
schreib_rot_netz "$repo_a"
git -C "$repo_a" add docker-compose.yml
git -C "$repo_a" commit -qm rot-feature
rot_sha=$(git -C "$repo_a" rev-parse HEAD)
git -C "$repo_a" checkout -q main 2>/dev/null \
    || git -C "$repo_a" checkout -q master
# HEAD ist gruen; feature liegt nur als Ref vor.
kopf_a=$(git -C "$repo_a" rev-parse HEAD)
[ "$kopf_a" != "$rot_sha" ] || {
    echo "ABBRUCH: Fall A, HEAD und Feature sind gleich - nichts gemessen." >&2
    exit 2
}
# Kontrolle: Checkout allein waere gruen.
if ! ( cd "$repo_a" && DATENWACHE_UEBERSTIMMT=1 .githooks/wachen.sh ); then
    echo "ABBRUCH: Fall A, Checkout ist unerwartet rot - Fixture kaputt." >&2
    exit 2
fi
rufe_hook checkout_gruen_feature_rot_wird_abgewiesen \
    "$repo_a" "$rot_sha" 1 "netz: ROT"
# Meldung nennt den geprueften Commit (Kurzform reicht).
kurz_rot=$(printf '%s' "$rot_sha" | cut -c1-7)
if ! grep -qF -- "$kurz_rot" "$werkstatt/checkout_gruen_feature_rot_wird_abgewiesen.aus" \
    && ! grep -qF -- "$rot_sha" "$werkstatt/checkout_gruen_feature_rot_wird_abgewiesen.aus"; then
    echo "ROT  meldung_nennt_commit: weder Kurz- noch Voll-SHA in der Ausgabe" >&2
    fehl=1
else
    echo "gruen meldung_nennt_commit"
fi

# --- Fall B: Checkout rot, gepushter Commit gruen → Push darf durch ----------
repo_b=$(neues_repo)
schreib_gruen "$repo_b"
git -C "$repo_b" add -A
git -C "$repo_b" commit -qm gruen-basis
git -C "$repo_b" branch feature-gruen
git -C "$repo_b" checkout -q -b rot-checkout
schreib_rot_netz "$repo_b"
git -C "$repo_b" add docker-compose.yml
git -C "$repo_b" commit -qm rot-checkout
# feature-gruen zeigt auf den gruenen Commit; HEAD ist rot.
gruen_sha=$(git -C "$repo_b" rev-parse feature-gruen)
kopf_b=$(git -C "$repo_b" rev-parse HEAD)
[ "$kopf_b" != "$gruen_sha" ] || {
    echo "ABBRUCH: Fall B, HEAD und Feature sind gleich - nichts gemessen." >&2
    exit 2
}
if ( cd "$repo_b" && DATENWACHE_UEBERSTIMMT=1 .githooks/wachen.sh ); then
    echo "ABBRUCH: Fall B, Checkout ist unerwartet gruen - Fixture kaputt." >&2
    exit 2
fi
rufe_hook checkout_rot_feature_gruen_wird_erlaubt \
    "$repo_b" "$gruen_sha" 0 ""

# --- Fall C: gepushter Commit verschaerft wachen.sh, Checkout hat die alte Fassung ---
# Die neue Regel greift nur, wenn der Hook die Wache aus dem gepushten Baum laufen
# laesst. Mit "$hook_home/wachen.sh" (Checkout) ginge der Push still durch.
repo_c=$(neues_repo)
schreib_gruen "$repo_c"
git -C "$repo_c" add -A
git -C "$repo_c" commit -qm checkout-alte-wache
git -C "$repo_c" checkout -q -b feature-wache
{
    printf '%s\n' '#!/bin/sh'
    printf '%s\n' 'echo "" >&2'
    printf '%s\n' 'echo "verschaerfung: ROT - absichtliche Probe im gepushten Stand." >&2'
    printf '%s\n' 'exit 1'
} > "$repo_c/.githooks/wachen.sh"
chmod +x "$repo_c/.githooks/wachen.sh"
git -C "$repo_c" add .githooks/wachen.sh
git -C "$repo_c" commit -qm wache-verschaerft
wache_sha=$(git -C "$repo_c" rev-parse HEAD)
git -C "$repo_c" checkout -q main 2>/dev/null \
    || git -C "$repo_c" checkout -q master
kopf_c=$(git -C "$repo_c" rev-parse HEAD)
[ "$kopf_c" != "$wache_sha" ] || {
    echo "ABBRUCH: Fall C, HEAD und Feature sind gleich - nichts gemessen." >&2
    exit 2
}
# Checkout-Wache allein: Baum gruen (sonst misst Fall C die Netz-Wache).
if ! ( cd "$repo_c" && DATENWACHE_UEBERSTIMMT=1 .githooks/wachen.sh ); then
    echo "ABBRUCH: Fall C, Checkout-Wache ist unerwartet rot - Fixture kaputt." >&2
    exit 2
fi
rufe_hook feature_verschaerft_wache_wird_abgewiesen \
    "$repo_c" "$wache_sha" 1 "verschaerfung: ROT"

# --- Datenwache bekommt dieselben stdin-Zeilen (einmal lesen, weiterreichen) ---
repo_d=$(neues_repo)
schreib_gruen "$repo_d"
git -C "$repo_d" add -A
git -C "$repo_d" commit -qm basis
# Private-Key-Marke nur im gepushten Commit; Checkout bleibt sauber.
git -C "$repo_d" checkout -q -b mit-schluessel
# Marke zusammengesetzt wie in test_datenwache.sh: als Literal im Quelltext
# wuerde die Datenwache diesen Test selbst beim Push abweisen.
_a="-----BEGIN "; _b="PRIVATE KEY-----"; _c="-----END "
printf '%s\n' "$_a$_b" 'probe' "$_c$_b" \
    > "$repo_d/geheim.txt"
git -C "$repo_d" add geheim.txt
git -C "$repo_d" commit -qm schluessel
key_sha=$(git -C "$repo_d" rev-parse HEAD)
git -C "$repo_d" checkout -q main 2>/dev/null \
    || git -C "$repo_d" checkout -q master
aus_d="$werkstatt/datenwache_sieht_stdin.aus"
( cd "$repo_d" && printf 'refs/heads/mit-schluessel %s refs/heads/mit-schluessel %s\n' \
    "$key_sha" "$leer" \
    | env PRE_PUSH_TEST_CMD='echo suite-attrappe' \
        bash .githooks/pre-push origin unused-url ) >"$aus_d" 2>&1
rc_d=$?
if [ "$rc_d" -eq 0 ] || ! grep -qF -- "datenwache:" "$aus_d"; then
    echo "ROT  datenwache_sieht_stdin: Push muss an der Datenwache scheitern" >&2
    sed 's/^/      /' "$aus_d" | tail -20 >&2
    fehl=1
else
    echo "gruen datenwache_sieht_stdin"
fi

[ "$fehl" -eq 0 ] && echo "test_pre_push_stand: alle gruen"
exit "$fehl"
