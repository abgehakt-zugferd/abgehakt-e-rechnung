#!/bin/sh
# Schneller Weg oder Exportweg in pre-push-stand.sh (#308, #309).
#
# Der schnelle Weg prueft den Arbeitsbaum. Er gilt nur bei HEAD gleich SHA,
# ohne getrackte (auch gestagte) Aenderungen und ohne ungetrackte Dateien unter
# .githooks/. Jeder Fall hier faerbt den Arbeitsbaum rot, der Commit ist gruen:
# rc 0 heisst, der Hook hat den Exportweg genommen.
#
# Suite ueber PRE_PUSH_TEST_CMD als Attrappe (Naht nur fuer Tests); Wachen echt.

set -u
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
      GIT_COMMON_DIR GIT_NAMESPACE GIT_QUARANTINE_PATH

hier=$(cd "$(dirname "$0")" && pwd)
. "$hier/pre_push_testhilfe.sh"
fehl=0
leer=0000000000000000000000000000000000000000

werkstatt_anlegen pre-push-schnellweg
# Leerer Checkout-Pfad: Gleichlauf-Block darf keine echte gleichlauf.py rufen.
PIPAUDIT_QUELLE=$(mktemp -d "$werkstatt/q-leer.XXXXXX") || {
    echo "ABBRUCH: kein leerer PIPAUDIT_QUELLE-Ordner." >&2
    exit 2
}
export PIPAUDIT_QUELLE

# stand_neues_repo, schreib_gruen, schreib_rot_netz, rufe_hook: pre_push_testhilfe.sh
neues_repo() { stand_neues_repo; }

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

# --- Fall L: git ls-files scheitert → Exportweg (fail-safe, 309-1) -----------
# Repo aus Fall I (ungetracktes rotes Overlay). Attrappen-git laesst nur
# `ls-files --others` scheitern; leere Ausgabe darf nicht "sauber" heissen.
attrappe_l="$werkstatt/git-attrappe-l"
mkdir -p "$attrappe_l"
echtes_git=$(command -v git)
cat > "$attrappe_l/git" <<ATTRAPPE
#!/bin/sh
case " \$* " in *" ls-files "*"--others"*) : > "$attrappe_l/getroffen"; exit 128 ;; esac
exec "$echtes_git" "\$@"
ATTRAPPE
chmod +x "$attrappe_l/git"
pfad_vorher=$PATH
PATH="$attrappe_l:$PATH"; export PATH
rufe_hook ls_files_fehler_nimmt_exportweg "$repo_i" "$sha_i" 0 ""
PATH=$pfad_vorher; export PATH
[ -f "$attrappe_l/getroffen" ] || {
    echo "ABBRUCH: Fall L, Attrappe nie gerufen - nichts gemessen." >&2
    exit 2
}

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

[ "$fehl" -eq 0 ] && echo "test_pre_push_schnellweg: alle gruen"
exit "$fehl"
