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

# Die Git-Fixture (gleichlauf_repo_anlegen, quelle_anlegen, schreib_attrappe,
# q_klonieren, argv_felder_ok) steht in pre_push_testhilfe.sh (300er-Grenze).

# $1 Repo  $2 Q  $3 HOME (leer=normal)  $4 Ref-Zeilen  $5 Ausgabedatei
# Loescht die Spuren und laesst den Hook laufen; rc steht danach in $rc.
fall_ausfuehren() {
    repo=$1
    q=$2
    home_ort=$3
    refzeilen=$4
    aus=$5
    rm -f "$werkstatt/spur.datenwache" "$werkstatt/spur.stand" \
        "$werkstatt/argv.txt" "$werkstatt/arbeitsbaum-lief.txt"
    # Quotiert ueber set --: unquotiert wuerde ein Pfad mit Leerzeichen
    # gesplittet; ein quotiertes leeres HOME-Argument ginge als leeres
    # Argument an env und der Hook startete nicht.
    set -- env "PIPAUDIT_QUELLE=$q"
    [ -n "$home_ort" ] && set -- env "PIPAUDIT_QUELLE=" "HOME=$home_ort"
    ( cd "$repo" && printf '%s\n' "$refzeilen" \
        | "$@" bash .githooks/pre-push origin unused-url ) >"$aus" 2>&1
    rc=$?
}

# rc und Spuren gegen die Erwartung. $1 Name  $2 erw_rc  $3 Wortlaut
# $4 Wortlaut-verboten (leer=keiner)  $5 suite_erwartet (0|1);
# liest $rc und $werkstatt/$1.aus.
fall_bewerten() {
    aus="$werkstatt/$1.aus"
    ok=1
    [ "$rc" -eq "$2" ] || ok=0
    [ -z "$3" ] || grep -qF -- "$3" "$aus" || ok=0
    [ -z "$4" ] || ! grep -qF -- "$4" "$aus" || ok=0
    if [ "$5" -eq 1 ]; then
        [ -e "$werkstatt/spur.datenwache" ] || ok=0
        [ -e "$werkstatt/spur.stand" ] || ok=0
    else
        [ ! -e "$werkstatt/spur.datenwache" ] || ok=0
        [ ! -e "$werkstatt/spur.stand" ] || ok=0
    fi
    # Zusicherung: die abweichende Attrappe im Arbeitsbaum von Q lief nie.
    [ ! -e "$werkstatt/arbeitsbaum-lief.txt" ] || ok=0
    if [ "$ok" -eq 1 ]; then
        echo "gruen $1"
    else
        echo "ROT  $1: rc=$rc (erwartet $2), suite_erwartet=$5" >&2
        [ ! -e "$werkstatt/arbeitsbaum-lief.txt" ] \
            || echo "      arbeitsbaum-attrappe lief!" >&2
        sed 's/^/      /' "$aus" | tail -30 >&2
        fehl=1
    fi
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
    if [ -n "$schalter" ]; then
        git -C "$repo" config --local pipaudit.gleichlauf "$schalter"
    else
        git -C "$repo" config --local --unset-all pipaudit.gleichlauf 2>/dev/null || true
    fi
    if [ -z "$refzeilen" ]; then
        sha=$(git -C "$repo" rev-parse HEAD)
        refzeilen=$(printf 'refs/heads/main %s refs/heads/main %s\n' "$sha" "$leer")
    fi
    fall_ausfuehren "$repo" "$q" "$home_ort" "$refzeilen" "$werkstatt/$name.aus"
    fall_bewerten "$name" "$erw_rc" "$wortlaut" "$verboten" "$suite_erwartet"
}

repo=$(gleichlauf_repo_anlegen)
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

# Quellpfad mit Leerzeichen: der env-Aufruf in fall darf die Zuweisung
# PIPAUDIT_QUELLE=... nicht am Leerzeichen splitten (unquotiert kaeme der
# zweite Teil als env-Befehl durch und der Hook stuerbe nie am Gleichlauf).
schreib_attrappe "$saat" 0
q_space=$(q_klonieren "$werkstatt/hauptquelle/origin.git" \
    "$werkstatt/q mit leerzeichen")
fall quellpfad_mit_leerzeichen_laesst_durch "$repo" "$q_space" "" 0 "" "" 1

# Leeres stdin: null Refs. Ohne Leer-Waechter liefe das Heredoc genau einmal
# mit leerem local_sha, also --push "" gegen die Attrappe. Der Pruefer darf
# nicht gerufen werden, der Hook endet mit 0 und erreicht die Datenwache.
zahl=$((zahl + 1))
schreib_attrappe "$saat" 0
rm -f "$werkstatt/spur.datenwache" "$werkstatt/spur.stand" \
    "$werkstatt/argv.txt" "$werkstatt/arbeitsbaum-lief.txt"
aus_leer="$werkstatt/leeres-stdin.aus"
( cd "$repo" && printf '' \
    | env "PIPAUDIT_QUELLE=$q_mit" bash .githooks/pre-push origin unused-url ) \
    >"$aus_leer" 2>&1
rc_leer=$?
if [ "$rc_leer" -eq 0 ] && [ ! -e "$werkstatt/argv.txt" ] \
    && [ -e "$werkstatt/spur.datenwache" ] \
    && [ ! -e "$werkstatt/arbeitsbaum-lief.txt" ]; then
    echo "gruen leeres_stdin_ruft_pruefer_nicht"
else
    echo "ROT  leeres_stdin_ruft_pruefer_nicht: rc=$rc_leer" >&2
    [ ! -e "$werkstatt/argv.txt" ] || echo "      pruefer lief mit: $(cat "$werkstatt/argv.txt")" >&2
    sed 's/^/      /' "$aus_leer" | tail -20 >&2
    fehl=1
fi

# Loesch-Ref (local_sha aus Nullen): der echte Pruefer wertet Nullen als
# Loesch-Push mit Exit 0; die Attrappe (Exit 0) bildet das nach. Der Block
# reicht die Zeile durch: --push 0...0 muss in der Spur stehen. Die
# Stand-Pruefung dahinter ueberspringt Nullen (kein spur.stand), die
# Datenwache laeuft (spur.datenwache).
zahl=$((zahl + 1))
schreib_attrappe "$saat" 0
rm -f "$werkstatt/spur.datenwache" "$werkstatt/spur.stand" \
    "$werkstatt/argv.txt" "$werkstatt/arbeitsbaum-lief.txt"
aus_loesch="$werkstatt/loesch-ref.aus"
( cd "$repo" && printf 'refs/heads/main %s refs/heads/main %s\n' \
    "$leer" "$(git -C "$repo" rev-parse HEAD)" \
    | env "PIPAUDIT_QUELLE=$q_mit" bash .githooks/pre-push origin unused-url ) \
    >"$aus_loesch" 2>&1
rc_loesch=$?
if [ "$rc_loesch" -eq 0 ] && [ -e "$werkstatt/spur.datenwache" ] \
    && [ ! -e "$werkstatt/spur.stand" ] \
    && [ ! -e "$werkstatt/arbeitsbaum-lief.txt" ] \
    && [ -f "$werkstatt/argv.txt" ] \
    && [ "$(wc -l < "$werkstatt/argv.txt" | tr -d ' ')" -eq 1 ] \
    && argv_felder_ok "$(sed -n '1p' "$werkstatt/argv.txt")" "$leer" "$repo_phys" "$q_mit"; then
    echo "gruen loesch_ref_wird_als_loeschung_durchgereicht"
else
    echo "ROT  loesch_ref_wird_als_loeschung_durchgereicht: rc=$rc_loesch" >&2
    sed 's/^/      /' "$aus_loesch" | tail -20 >&2
    fehl=1
fi

# stdin aus einem Verzeichnis: der Lese-Fehler von cat muss den Hook mit
# Meldung abbrechen. `push_refs=$(cat; printf x)` verschluckte ihn, weil nur
# der Status von printf zaehlte; der Hook lief mit leerer Ref-Liste weiter.
# (Geschlossenes stdin loest den Fehler nicht aus: in der Kommandoersetzung
# landet der Auffang-Pipe auf fd 0 und cat haengt, statt zu scheitern.)
zahl=$((zahl + 1))
mkdir -p "$werkstatt/stdin-als-verzeichnis"
rm -f "$werkstatt/spur.datenwache" "$werkstatt/spur.stand" \
    "$werkstatt/argv.txt" "$werkstatt/arbeitsbaum-lief.txt"
aus_cat="$werkstatt/stdin-zu.aus"
( cd "$repo" && env "PIPAUDIT_QUELLE=$q_mit" \
    bash .githooks/pre-push origin unused-url \
    < "$werkstatt/stdin-als-verzeichnis" ) >"$aus_cat" 2>&1
rc_cat=$?
if [ "$rc_cat" -ne 0 ] && grep -qF -- "stdin" "$aus_cat" \
    && [ ! -e "$werkstatt/argv.txt" ] \
    && [ ! -e "$werkstatt/spur.datenwache" ]; then
    echo "gruen stdin_unlesbar_bricht_mit_meldung_ab"
else
    echo "ROT  stdin_unlesbar_bricht_mit_meldung_ab: rc=$rc_cat" >&2
    sed 's/^/      /' "$aus_cat" | tail -20 >&2
    fehl=1
fi

[ "$fehl" -eq 0 ] && echo "test_gleichlauf_tor: alle gruen ($zahl Faelle)"
exit "$fehl"
