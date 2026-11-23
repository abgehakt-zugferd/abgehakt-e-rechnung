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

# Spiegel mit lebenden Hook-Skripten aus $hier (von der Testdatei gesetzt).
# Gibt den Repo-Pfad aus. pipaudit.gleichlauf aus: fehlt-Checkout warnt nur.
stand_neues_repo() {
    d=$(spiegel_repo_anlegen)
    mkdir -p "$d/.githooks"
    cp "$hier/pre-push" "$d/.githooks/pre-push"
    cp "$hier/datenwache.sh" "$d/.githooks/datenwache.sh"
    cp "$hier/wachen.sh" "$d/.githooks/wachen.sh"
    cp "$hier/netzwache.sh" "$d/.githooks/netzwache.sh"
    cp "$hier/compose_ports_pruefen.py" "$d/.githooks/compose_ports_pruefen.py"
    if [ -f "$hier/pre-push-stand.sh" ]; then
        cp "$hier/pre-push-stand.sh" "$d/.githooks/pre-push-stand.sh"
        chmod +x "$d/.githooks/pre-push-stand.sh"
    fi
    chmod +x "$d/.githooks/pre-push" "$d/.githooks/datenwache.sh" "$d/.githooks/wachen.sh"
    git -C "$d" config --local pipaudit.gleichlauf aus
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

# --- Git-Fixture des Gleichlauf-Tors (nur test_gleichlauf_tor.sh) ------------
# Steht hier wegen der 300-Zeilen-Grenze der Testdatei. Heisst nicht
# neues_repo, damit die lokale Fassung in test_pre_push_stand.sh nichts
# maskiert und umgekehrt.

# Spiegel der App: Hook unter Test, teure Suite nur als Spur.
gleichlauf_repo_anlegen() {
    d=$(spiegel_repo_anlegen)
    mkdir -p "$d/.githooks/pip-audit-auswerter"
    cp "$hier/pre-push" "$d/.githooks/pre-push"
    chmod +x "$d/.githooks/pre-push"
    printf '#!/bin/sh\ntouch "%s/spur.datenwache"\nexit 0\n' "$werkstatt" \
        > "$d/.githooks/datenwache.sh"
    printf '#!/bin/sh\ntouch "%s/spur.stand"\nexit 0\n' "$werkstatt" \
        > "$d/.githooks/pre-push-stand.sh"
    chmod +x "$d/.githooks/datenwache.sh" "$d/.githooks/pre-push-stand.sh"
    printf 'probe\n' > "$d/README"
    git -C "$d" add README
    git -C "$d" commit -qm probe
    printf '%s\n' "$d"
}

# Quelle: bare origin unter $1/origin.git plus Saat-Klon, dessen Pfad
# ausgegeben wird (schreib_attrappe arbeitet in ihm).
quelle_anlegen() {
    git init -q --bare "$1/origin.git"
    git -C "$1/origin.git" symbolic-ref HEAD refs/heads/main
    saat=$(mktemp -d "$werkstatt/saat.XXXXXX")
    git -C "$saat" init -q
    git -C "$saat" config user.name probe
    git -C "$saat" config user.email probe@example.invalid
    git -C "$saat" checkout -q -b main
    git -C "$saat" remote add origin "$1/origin.git"
    printf '%s\n' "$saat"
}

# Attrappe mit Exit $2 in der Saat committen und per force-push auf
# origin/main legen (der Hook holt sie per fetch + archive daraus).
schreib_attrappe() {
    mkdir -p "$1/pip-audit-auswerter"
    cat > "$1/pip-audit-auswerter/gleichlauf.py" <<ATT
import sys
with open("$werkstatt/argv.txt", "a", encoding="utf-8") as f:
    f.write(" ".join(sys.argv[1:]) + "\n")
sys.exit($2)
ATT
    git -C "$1" add pip-audit-auswerter/gleichlauf.py
    git -C "$1" commit -qm "attrappe $2"
    git -C "$1" push -q -f origin main
}

# Klon von $1 nach $2; legt danach die ABWEICHENDE Attrappe uncommittet in
# den Arbeitsbaum. Gibt den physikalischen Klonpfad aus.
q_klonieren() {
    git clone -q "$1" "$2"
    mkdir -p "$2/pip-audit-auswerter"
    cat > "$2/pip-audit-auswerter/gleichlauf.py" <<ATT
import sys
with open("$werkstatt/arbeitsbaum-lief.txt", "a", encoding="utf-8") as f:
    f.write("arbeitsbaum\n")
sys.exit(9)
ATT
    (cd "$2" && pwd -P)
}

# argv-Zeile der Attrappe gegen den Vertrag pruefen:
# --push <sha> --repo <wurzel> .githooks/pip-audit-auswerter --checkout <Q>
# $1 Zeile  $2 erwartete sha  $3 Repo physikalisch  $4 Q physikalisch
argv_felder_ok() {
    s=$2
    rp=$3
    qp=$4
    set -- $1
    [ "$1" = "--push" ] && [ "$2" = "$s" ] && [ "$3" = "--repo" ] \
        && [ "$(cd "$4" 2>/dev/null && pwd -P)" = "$rp" ] \
        && [ "$5" = ".githooks/pip-audit-auswerter" ] \
        && [ "$6" = "--checkout" ] && [ "$(cd "$7" 2>/dev/null && pwd -P)" = "$qp" ]
}
