#!/bin/sh
# Prueft NUR den Gleichlauf-Block in pre-push (nicht gleichlauf.py selbst).
#
# Der Block holt Pruefprogramm UND Quelle per fetch + archive aus origin/main
# der Quelle Q. Darum ist Q hier ein echter Klon eines lokalen bare Repos:
# dessen main traegt die Attrappe pip-audit-auswerter/gleichlauf.py (haengt je
# Aufruf eine argv-Zeile an eine Spurdatei, endet mit vorgegebenem Exit). Im
# ARBEITSBAUM von Q liegt eine ABWEICHENDE Attrappe (eigene Spur, Exit 9) —
# sie darf nie laufen; das prueft jeder Fall ueber arbeitsbaum-lief.txt mit.
#
# Wahl wie gehabt: Hook in einen Spiegel kopieren und mit Attrappen fuer die
# teure Suite laufen lassen, keine Abschrift des Blocks. Kein Netz: alle
# Remotes sind lokale Pfade.

set -u
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
      GIT_COMMON_DIR GIT_NAMESPACE GIT_QUARANTINE_PATH

hier=$(cd "$(dirname "$0")" && pwd)
. "$hier/pre_push_testhilfe.sh"
fehl=0
zahl=0
leer=0000000000000000000000000000000000000000

werkstatt_anlegen gleichlauf-tor

# Spiegel der App: Hook unter Test, teure Suite nur als Spur.
neues_repo() {
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

# $1 Name  $2 Repo  $3 Q  $4 Schalter (leer=unset, sonst Wert)  $5 erw_rc
# $6 Wortlaut  $7 Wortlaut-verboten (leer=keiner)  $8 suite_erwartet (0|1)
# $9 HOME (leer=normal)  ${10} Ref-Zeilen (leer=eine main-Zeile auf HEAD)
fall() {
    name=$1
    repo=$2
    q=$3
    schalter=$4
    erw_rc=$5
    wortlaut=$6
    verboten=${7:-}
    suite_erwartet=$8
    home_ort=${9:-}
    refzeilen=${10:-}
    zahl=$((zahl + 1))
    rm -f "$werkstatt/spur.datenwache" "$werkstatt/spur.stand" \
        "$werkstatt/argv.txt" "$werkstatt/arbeitsbaum-lief.txt"
    if [ -n "$schalter" ]; then
        git -C "$repo" config --local pipaudit.gleichlauf "$schalter"
    else
        git -C "$repo" config --local --unset-all pipaudit.gleichlauf 2>/dev/null || true
    fi
    if [ -z "$refzeilen" ]; then
        sha=$(git -C "$repo" rev-parse HEAD)
        refzeilen=$(printf 'refs/heads/main %s refs/heads/main %s\n' "$sha" "$leer")
    fi
    aus="$werkstatt/$name.aus"
    if [ -n "$home_ort" ]; then
        env_q='PIPAUDIT_QUELLE='
        env_home="HOME=$home_ort"
    else
        env_q="PIPAUDIT_QUELLE=$q"
        env_home=
    fi
    ( cd "$repo" && printf '%s\n' "$refzeilen" \
        | env $env_q $env_home bash .githooks/pre-push origin unused-url ) >"$aus" 2>&1
    rc=$?
    ok=1
    if [ "$rc" -ne "$erw_rc" ]; then
        ok=0
    fi
    [ -z "$wortlaut" ] || grep -qF -- "$wortlaut" "$aus" || ok=0
    [ -z "$verboten" ] || ! grep -qF -- "$verboten" "$aus" || ok=0
    if [ "$suite_erwartet" -eq 1 ]; then
        [ -e "$werkstatt/spur.datenwache" ] || ok=0
        [ -e "$werkstatt/spur.stand" ] || ok=0
    else
        [ ! -e "$werkstatt/spur.datenwache" ] || ok=0
        [ ! -e "$werkstatt/spur.stand" ] || ok=0
    fi
    # Zusicherung: die abweichende Attrappe im Arbeitsbaum von Q lief nie.
    [ ! -e "$werkstatt/arbeitsbaum-lief.txt" ] || ok=0
    if [ "$ok" -eq 1 ]; then
        echo "gruen $name"
    else
        echo "ROT  $name: rc=$rc (erwartet $erw_rc), suite_erwartet=$suite_erwartet" >&2
        [ ! -e "$werkstatt/arbeitsbaum-lief.txt" ] \
            || echo "      arbeitsbaum-attrappe lief!" >&2
        sed 's/^/      /' "$aus" | tail -30 >&2
        fehl=1
    fi
}

repo=$(neues_repo)
repo_phys=$(cd "$repo" && pwd -P)

# Hauptquelle: bare origin + Klon Q mit abweichender Arbeitsbaum-Attrappe.
saat=$(quelle_anlegen "$werkstatt/hauptquelle")
schreib_attrappe "$saat" 0
q_mit=$(q_klonieren "$werkstatt/hauptquelle/origin.git" "$werkstatt/q-klon")
q_leer=$(mktemp -d "$werkstatt/q-leer.XXXXXX")
q_leer=$(cd "$q_leer" && pwd -P)

# Attrappe 0 → Block laesst durch, Suite laeuft.
fall attrappe_0_laesst_durch "$repo" "$q_mit" "" 0 "" "" 1

# argv: --push <sha> --repo <wurzel> .githooks/pip-audit-auswerter --checkout <Q>.
zahl=$((zahl + 1))
sha=$(git -C "$repo" rev-parse HEAD)
if [ -f "$werkstatt/argv.txt" ] \
    && argv_felder_ok "$(sed -n '1p' "$werkstatt/argv.txt")" "$sha" "$repo_phys" "$q_mit" \
    && [ "$(wc -l < "$werkstatt/argv.txt" | tr -d ' ')" -eq 1 ]; then
    echo "gruen argv_ist_push_repo_kopie_checkout"
else
    echo "ROT  argv_ist_push_repo_kopie_checkout: $(cat "$werkstatt/argv.txt" 2>/dev/null)" >&2
    fehl=1
fi

# Attrappe 1/2/3 → rot, Suite nicht.
schreib_attrappe "$saat" 1
fall attrappe_1_ist_rot "$repo" "$q_mit" "" 1 "" "" 0
schreib_attrappe "$saat" 2
fall attrappe_2_ist_rot "$repo" "$q_mit" "" 1 "" "" 0
schreib_attrappe "$saat" 3
fall attrappe_3_ist_rot "$repo" "$q_mit" "" 1 "" "" 0

# Schalter pflicht bei vorhandener Quelle: Attrappe laeuft, ihr Exit zaehlt.
schreib_attrappe "$saat" 2
fall quelle_vorhanden_und_pflicht_nimmt_attrappen_exit "$repo" "$q_mit" "pflicht" 1 "" "" 0

# Quelle kein Git-Repo, kein Schalter → WARNUNG und durch.
fall fehlt_ohne_schalter_warnung_und_durch "$repo" "$q_leer" "" 0 \
    "WARNUNG: Gleichlauf NICHT GEMESSEN" "ROT: Gleichlauf" 1

# Quelle kein Git-Repo, Schalter pflicht → ROT.
fall fehlt_mit_pflicht_ist_rot "$repo" "$q_leer" "pflicht" 1 \
    "ROT: Gleichlauf NICHT GEMESSEN" "" 0

# Quelle kein Git-Repo, Schalter anderer Wert → WARNUNG und durch.
fall fehlt_mit_anderem_schalter_warnung_und_durch "$repo" "$q_leer" "aus" 0 \
    "WARNUNG: Gleichlauf NICHT GEMESSEN" "ROT: Gleichlauf" 1

# Fetch scheitert (origin zeigt ins Leere) → ROT mit eigenem Wortlaut.
q_fetch=$(q_klonieren "$werkstatt/hauptquelle/origin.git" "$werkstatt/q-fetch")
git -C "$q_fetch" remote set-url origin "$werkstatt/gibts-nicht.git"
fall fetch_scheitert_ist_rot "$repo" "$q_fetch" "" 1 \
    "ROT: Gleichlauf NICHT GEMESSEN: Fetch von origin/main" "" 0

# origin/main ohne pip-audit-auswerter → ROT mit eigener ROT-Zeile.
git -C "$saat" rm -rq pip-audit-auswerter
git -C "$saat" commit -qm "auswerter weg"
git -C "$saat" push -q -f origin main
fall archive_ohne_auswerter_ist_rot "$repo" "$q_mit" "" 1 \
    "ROT: Gleichlauf NICHT GEMESSEN: kein pip-audit-auswerter auf origin/main" \
    "Fetch von origin/main" 0

# Zwei gepushte Refs → die Attrappe laeuft je Ref einmal mit dessen sha.
schreib_attrappe "$saat" 0
git -C "$repo" checkout -q -b zweit
printf 'zwei\n' >> "$repo/README"
git -C "$repo" commit -qam zweit
sha1=$(git -C "$repo" rev-parse main)
sha2=$(git -C "$repo" rev-parse zweit)
git -C "$repo" checkout -q main
zwei_refs=$(printf 'refs/heads/main %s refs/heads/main %s\nrefs/heads/zweit %s refs/heads/zweit %s\n' \
    "$sha1" "$leer" "$sha2" "$leer")
fall zwei_refs_lassen_durch "$repo" "$q_mit" "" 0 "" "" 1 "" "$zwei_refs"
zahl=$((zahl + 1))
if [ -f "$werkstatt/argv.txt" ] \
    && [ "$(wc -l < "$werkstatt/argv.txt" | tr -d ' ')" -eq 2 ] \
    && argv_felder_ok "$(sed -n '1p' "$werkstatt/argv.txt")" "$sha1" "$repo_phys" "$q_mit" \
    && argv_felder_ok "$(sed -n '2p' "$werkstatt/argv.txt")" "$sha2" "$repo_phys" "$q_mit"; then
    echo "gruen zwei_refs_argv_je_ref"
else
    echo "ROT  zwei_refs_argv_je_ref:" >&2
    sed 's/^/      /' "$werkstatt/argv.txt" 2>/dev/null >&2
    fehl=1
fi

# Leere PIPAUDIT_QUELLE faellt auf \$HOME/Documents/... zurueck; dort liegt
# eine zweite, eigenstaendige Quelle (eigenes bare origin, eigener Klon).
home_q="$werkstatt/home"
home_saat=$(quelle_anlegen "$home_q/quelle")
schreib_attrappe "$home_saat" 0
home_klon=$(q_klonieren "$home_q/quelle/origin.git" \
    "$home_q/Documents/claude/claude-global-skills")
fall leere_quelle_nimmt_home_fallback "$repo" "" "" 0 "" "" 1 "$home_q"
zahl=$((zahl + 1))
if [ -f "$werkstatt/argv.txt" ] \
    && argv_felder_ok "$(sed -n '1p' "$werkstatt/argv.txt")" \
        "$(git -C "$repo" rev-parse HEAD)" "$repo_phys" "$home_klon"; then
    echo "gruen leere_quelle_verwendet_home_als_checkout"
else
    echo "ROT  leere_quelle_verwendet_home_als_checkout: $(cat "$werkstatt/argv.txt" 2>/dev/null)" >&2
    fehl=1
fi

[ "$fehl" -eq 0 ] && echo "test_gleichlauf_tor: alle gruen ($zahl Faelle)"
exit "$fehl"
