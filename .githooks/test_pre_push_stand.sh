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
. "$hier/pre_push_testhilfe.sh"
. "$hier/test_umweg_hilfe.sh"
fehl=0
leer=0000000000000000000000000000000000000000

werkstatt_anlegen pre-push-stand
# Leerer Checkout-Pfad: Gleichlauf-Block darf keine echte gleichlauf.py rufen.
PIPAUDIT_QUELLE=$(mktemp -d "$werkstatt/q-leer.XXXXXX") || {
    echo "ABBRUCH: kein leerer PIPAUDIT_QUELLE-Ordner." >&2
    exit 2
}
export PIPAUDIT_QUELLE

# stand_neues_repo, schreib_gruen, schreib_rot_netz, rufe_hook: pre_push_testhilfe.sh
# umweg_empfehlungen, pruefe_umweg_probe: test_umweg_hilfe.sh
neues_repo() { stand_neues_repo; }

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

# --- Fall F: rote Suite, die Meldung empfiehlt keinen Umweg am Hook vorbei ---------
repo_f=$(neues_repo)
schreib_gruen "$repo_f"
git -C "$repo_f" add -A
git -C "$repo_f" commit -qm gruen-f
sha_f=$(git -C "$repo_f" rev-parse HEAD)
aus_f="$werkstatt/fall-f.aus"
( cd "$repo_f" && printf 'refs/heads/main %s refs/heads/main %s\n' "$sha_f" "$leer" \
    | env DATENWACHE_UEBERSTIMMT=1 PRE_PUSH_TEST_CMD='false' \
        bash .githooks/pre-push origin unused-url ) >"$aus_f" 2>&1
rc_f=$?
if [ "$rc_f" -eq 0 ] || ! grep -qF -- "tdd: ROT" "$aus_f"; then
    echo "ROT  rote_suite_blockiert: Push muss an der Suite scheitern (rc=$rc_f)" >&2
    sed 's/^/      /' "$aus_f" | tail -20 >&2
    fehl=1
elif grep -qF -- "no-verify" "$aus_f"; then
    echo "ROT  rote_suite_empfiehlt_keinen_umweg: die Meldung nennt --no-verify" >&2
    sed 's/^/      /' "$aus_f" | tail -20 >&2
    fehl=1
else
    echo "gruen rote_suite_blockiert_ohne_umweg_empfehlung"
fi

# --- Fall G: keine Hook-Meldung unter .githooks/ empfiehlt einen Umweg am Hook vorbei ---
# Gelesen werden die Hook-Skripte (nicht die test_*.sh, die das Wort pruefen). Zeilen, die
# nur Kommentar sind, zaehlen nicht; ein Verbot ("nicht --no-verify") ist erlaubt.
# Weitere Muster neben no-verify: hooksPath=/dev/null bzw. hooksPath /dev/null und HUSKY=0
# (gleicher Umweg). HUSKY="0" bleibt bewusst draußen (Text-Lint, siehe Kommentar oben).
# Text-Lint ist nie vollstaendig (z. B. SKIP=..., zerlegte Woerter); das bleibt bewusst so.
pruefe_umweg_probe empfehlung_hooksPath_ist_umweg \
    'echo "nutze git -c core.hooksPath=/dev/null push"' rot
pruefe_umweg_probe verbot_hooksPath_ist_kein_umweg \
    'echo "nicht hooksPath=/dev/null setzen"' gruen
pruefe_umweg_probe empfehlung_hooksPath_leerzeichen_ist_umweg \
    'echo "nutze git config core.hooksPath /dev/null"' rot
pruefe_umweg_probe verbot_hooksPath_leerzeichen_ist_kein_umweg \
    'echo "nicht hooksPath /dev/null setzen"' gruen
pruefe_umweg_probe fernes_nicht_entschuldigt_keine_empfehlung \
    'echo "nicht vergessen, sonst git -c core.hooksPath=/dev/null push"' rot
pruefe_umweg_probe empfehlung_HUSKY0_ist_umweg \
    'echo "HUSKY=0 git push"' rot
pruefe_umweg_probe verbot_HUSKY0_ist_kein_umweg \
    'echo "nicht HUSKY=0 setzen"' gruen

# --- Fall H: HEAD gleich SHA, aber getrackte Datei geaendert → Exportweg ------
# Schneller Weg (Arbeitsbaum) wuerde die uncommittete Aenderung mitpruefen und
# den Push an der roten Netz-Wache festhalten; der Export prueft genau den
# gepushten Stand und ist gruen.
repo_h=$(neues_repo)
schreib_gruen "$repo_h"
git -C "$repo_h" add -A
git -C "$repo_h" commit -qm gruen-h
sha_h=$(git -C "$repo_h" rev-parse HEAD)
# Getrackte, uncommittete Aenderung, die den Arbeitsbaum rot macht.
schreib_rot_netz "$repo_h"
rufe_hook uncommittete_aenderung_nimmt_exportweg "$repo_h" "$sha_h" 0 ""

# --- Fall I: HEAD gleich SHA, Baum sauber, ungetrackte Datei unter .githooks/ ---
# Committed Wache: vor exit optionales Overlay (nur Fixture). Ungetracktes Overlay
# faerbt den Arbeitsbaum rot; der Export enthaelt es nicht → gruen.
repo_i=$(neues_repo)
schreib_gruen "$repo_i"
overlay_naht='if [ -f .githooks/lokal-overlay.sh ]; then . .githooks/lokal-overlay.sh; fi'
awk -v naht="$overlay_naht" '
    /^exit "\$fehler"$/ { print naht }
    { print }
' "$repo_i/.githooks/wachen.sh" > "$repo_i/.githooks/wachen.sh.neu"
mv "$repo_i/.githooks/wachen.sh.neu" "$repo_i/.githooks/wachen.sh"
chmod +x "$repo_i/.githooks/wachen.sh"
git -C "$repo_i" add -A
git -C "$repo_i" commit -qm gruen-i
sha_i=$(git -C "$repo_i" rev-parse HEAD)
printf '%s\n' 'echo "untracked-overlay: ROT" >&2' 'exit 1' \
    > "$repo_i/.githooks/lokal-overlay.sh"
if ( cd "$repo_i" && DATENWACHE_UEBERSTIMMT=1 .githooks/wachen.sh ); then
    echo "ABBRUCH: Fall I, Arbeitsbaum unerwartet gruen - Fixture kaputt." >&2
    exit 2
fi
git -C "$repo_i" diff --quiet HEAD || {
    echo "ABBRUCH: Fall I, Baum nicht sauber - nichts gemessen." >&2
    exit 2
}
[ -n "$(git -C "$repo_i" ls-files --others --exclude-standard -- .githooks)" ] || {
    echo "ABBRUCH: Fall I, keine ungetrackte .githooks-Datei - nichts gemessen." >&2
    exit 2
}
rufe_hook ungetrackte_githooks_nimmt_exportweg "$repo_i" "$sha_i" 0 ""

# --- Fall J: HEAD gleich SHA, Aenderung nur gestagt → Exportweg ----------------
# Wie Fall H, aber nach git add (Index == Arbeitsbaum, beides ungleich HEAD).
# `git diff --quiet` ohne HEAD wuerde den schnellen Weg nehmen und rot werden.
repo_j=$(neues_repo)
schreib_gruen "$repo_j"
git -C "$repo_j" add -A
git -C "$repo_j" commit -qm gruen-j
sha_j=$(git -C "$repo_j" rev-parse HEAD)
schreib_rot_netz "$repo_j"
git -C "$repo_j" add docker-compose.yml
git -C "$repo_j" diff --quiet HEAD && {
    echo "ABBRUCH: Fall J, gestagte Aenderung unsichtbar - nichts gemessen." >&2
    exit 2
}
git -C "$repo_j" diff --quiet || {
    echo "ABBRUCH: Fall J, Index und Baum differieren - Fixture kaputt." >&2
    exit 2
}
rufe_hook gestagte_aenderung_nimmt_exportweg "$repo_j" "$sha_j" 0 ""

# --- Fall K: Ref-Zeile auf stdin ohne Schluss-Newline wird trotzdem geprueft ---
# Charakterisierung: pre-push liest per Markierung und heredoc; printf ohne \n.
# Mutation die rot macht: Stand-Schleife als process substitution
# `done < <(printf '%s' "$push_refs")` ohne `|| [ -n "${lokal_sha:-}" ]`
# (Pipe+while waere Subshell und wuerde zusaetzlich Exit 1 verschlucken).
repo_k=$(neues_repo)
schreib_gruen "$repo_k"
git -C "$repo_k" add -A
git -C "$repo_k" commit -qm gruen-k
sha_k=$(git -C "$repo_k" rev-parse HEAD)
kurz_k=$(printf '%s' "$sha_k" | cut -c1-7)
aus_k="$werkstatt/stdin-ohne-newline.aus"
( cd "$repo_k" && printf 'refs/heads/main %s refs/heads/main %s' "$sha_k" "$leer" \
    | env DATENWACHE_UEBERSTIMMT=1 PRE_PUSH_TEST_CMD='echo suite-attrappe' \
        bash .githooks/pre-push origin unused-url ) >"$aus_k" 2>&1
rc_k=$?
if [ "$rc_k" -ne 0 ] || ! grep -qF -- "tdd: prüfe Commit $kurz_k" "$aus_k"; then
    echo "ROT  stdin_ohne_newline_wird_geprueft: rc=$rc_k, Meldung fehlt" >&2
    sed 's/^/      /' "$aus_k" | tail -20 >&2
    fehl=1
else
    echo "gruen stdin_ohne_newline_wird_geprueft"
fi

umweg=$(umweg_empfehlungen "$hier")
if [ -n "$umweg" ]; then
    echo "ROT  hooks_empfehlen_keinen_umweg: Umweg in einer Hook-Meldung" >&2
    printf '%s\n' "$umweg" | sed 's/^/      /' >&2
    fehl=1
else
    echo "gruen hooks_empfehlen_keinen_umweg"
fi

[ "$fehl" -eq 0 ] && echo "test_pre_push_stand: alle gruen"
exit "$fehl"
