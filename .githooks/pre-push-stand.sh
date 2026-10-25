#!/usr/bin/env bash
# Prueft einen Commit-Stand fuer pre-push (#219): Gedankenstrich-Wache, wachen.sh,
# Suite inkl. Skip-Guard. Aufruf aus der Repo-Wurzel mit einem lokalen SHA.
#
# Ist HEAD gleich dem SHA, bleibt der schnelle Weg (Arbeitsbaum). Sonst Wegwerf-
# Worktree unter TMPDIR, damit wachen.sh und git ls-files ein Toplevel haben
# (reines git archive haette keines). Immer Abraeumen per trap.
set -uo pipefail

sha="${1:?pre-push-stand: SHA fehlt}"
leer=0000000000000000000000000000000000000000
[ "$sha" = "$leer" ] && exit 0

wurzel=$(git rev-parse --show-toplevel) || exit 1
cd "$wurzel" || exit 1

stand_tmp=
raeume_stand() {
  if [ -n "${stand_tmp:-}" ] && [ -d "$stand_tmp" ]; then
    git -C "$wurzel" worktree remove --force "$stand_tmp" >/dev/null 2>&1 \
      || rm -rf "$stand_tmp"
  fi
  stand_tmp=
}
trap raeume_stand EXIT

gedankenstriche() {
  striche="$(git ls-files '*.md' | while read -r f; do
      perl -ne 's/(?<=\d)[\x{2013}\x{2014}](?=\d)//g; print "'"'"'$ARGV:$.: $_" if /[\x{2013}\x{2014}]/' -CSD "$f"
    done)"
  if [ -n "$striche" ]; then
    {
      echo ""
      echo "dokumente: ROT - Gedankenstrich in Markdown gefunden. Push blockiert."
      echo "  Komma, Doppelpunkt, Strichpunkt oder zwei Saetze statt dessen."
      echo "$striche"
    } >&2
    return 1
  fi
  return 0
}

run_tests() {
  if docker compose ps --services --status running 2>/dev/null | grep -qx app &&
     docker compose exec -T app python -c "import pytest" >/dev/null 2>&1 </dev/null; then
    echo "tdd: Entwicklungsstack laeuft, Suite im app-Container." >&2
    docker compose exec -T app python -m pytest tests/ -q </dev/null
  else
    echo "tdd: kein Entwicklungsstack, kanonische Baseline (backend/run-tests.sh)." >&2
    (cd backend && ./run-tests.sh)
  fi
}

run_suite() {
  if [ -n "${PRE_PUSH_TEST_CMD:-}" ]; then
    # Naht nur fuer Hook-Tests; Vorgabe ist die echte Suite oben.
    sh -c "$PRE_PUSH_TEST_CMD"
  else
    run_tests
  fi
}

pruefe_baum() {
  out=$(mktemp "${TMPDIR:-/tmp}/pre-push-suite.XXXXXX") \
    && [ -n "$out" ] && [ -f "$out" ] || {
    echo "pre-push: keine Ablage fuer Suite-Ausgabe (mktemp)." >&2
    return 1
  }

  if ! gedankenstriche; then
    rm -f "$out"
    return 1
  fi

  # Wachen aus dem geprueften Baum (cwd = Checkout oder Wegwerf-Worktree), nicht
  # aus dem Hook-Verzeichnis des Checkouts: sonst greifen neue/strengere Regeln
  # im gepushten Commit nicht (Fall C in test_pre_push_stand.sh).
  if [ ! -f .githooks/wachen.sh ]; then
    echo "pre-push: .githooks/wachen.sh fehlt im geprüften Stand $sha. Push blockiert." >&2
    rm -f "$out"
    return 1
  fi
  if ! ./.githooks/wachen.sh; then
    echo "  Push blockiert." >&2
    rm -f "$out"
    return 1
  fi

  if run_suite 2>&1 | tee "$out"; then
    if grep -qE "[1-9][0-9]* skipped" "$out"; then
      {
        echo ""
        echo "tdd: ROT, Tests wurden übersprungen (Skip-Guard). Push blockiert."
      } >&2
      rm -f "$out"
      return 1
    fi
    rm -f "$out"
    echo "tdd: grün, Stand $sha ok."
    return 0
  fi
  {
    echo ""
    echo "tdd: ROT, Push blockiert. Kein ungetesteter Code verlässt das Repo."
    echo "     Bewusste Ausnahme nur via:  git push --no-verify"
  } >&2
  rm -f "$out"
  return 1
}

kurz=$(git rev-parse --short "$sha" 2>/dev/null || printf '%s' "$sha" | cut -c1-7)
echo "tdd: prüfe Commit $kurz ($sha)." >&2

kopf=$(git rev-parse HEAD)
if [ "$sha" = "$kopf" ]; then
  # Schneller Weg: Checkout ist genau der gepushte Stand. Export waere identisch
  # und kostet Worktree plus Docker-Kontext; der Alltags-Push bleibt lokal.
  pruefe_baum
  ec=$?
  trap - EXIT
  exit "$ec"
fi

stand_tmp=$(mktemp -d "${TMPDIR:-/tmp}/pre-push-stand.XXXXXX") \
  && [ -n "$stand_tmp" ] && [ -d "$stand_tmp" ] || {
  echo "pre-push: kein Wegwerfverzeichnis fuer Stand $sha (mktemp)." >&2
  exit 1
}
if ! git worktree add --detach "$stand_tmp" "$sha" >/dev/null 2>&1; then
  echo "pre-push: Worktree fuer $sha nicht anlegbar." >&2
  exit 1
fi

ec=0
(
  cd "$stand_tmp" || exit 1
  unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE GIT_OBJECT_DIRECTORY \
        GIT_COMMON_DIR GIT_NAMESPACE GIT_QUARANTINE_PATH
  pruefe_baum
) || ec=$?

raeume_stand
trap - EXIT
exit "$ec"
