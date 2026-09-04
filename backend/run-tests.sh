#!/usr/bin/env bash
# Kanonische, reproduzierbare Test-Baseline für abgehakt.
#
# WARUM Docker: Produktion läuft auf Python 3.11 (siehe Dockerfile). Nur im Container sind
# JRE + Ghostscript + Mustang-CLI.jar vorhanden — d. h. die 4 ZUGFeRD-/PDF-Integrationstests
# SKIPPEN NICHT und der rechtlich kritische validierte-E-Rechnung-Pfad wird wirklich geprüft.
# Ein lokaler venv-Lauf (Python != 3.11, ohne Mustang/GS) ist NUR eine schnelle Dev-Schleife
# und liefert KEIN vertrauenswürdiges Baseline-Grün ("grün ist verdächtig nach Env-Wechsel").
#
# Nutzung:
#   ./run-tests.sh            # baut Image (falls nötig) und läuft volle Suite im 3.11-Container
#   ./run-tests.sh -k storno  # zusätzliche pytest-Argumente werden durchgereicht
set -euo pipefail
cd "$(dirname "$0")"

IMAGE="abgehakt-backend:test"
NETWORK="abgehakt-test-net-$$"
PG_CONTAINER="abgehakt-test-db-$$"

echo ">> Baue Image ${IMAGE} (Python 3.11 + JRE + Ghostscript + Mustang) ..."
docker build --target test -t "${IMAGE}" . >/dev/null

# Die prod-Stage ist das, was `docker-compose.yml` startet, also das Abbild jeder
# Installation. Getestet wird trotzdem in der test-Stage, weil nur dort pytest liegt.
# Dieser Bauversuch schliesst die Luecke dazwischen: er faellt auf, wenn prod nicht mehr
# baut. set -euo pipefail laesst das Skript dann hier abbrechen.
echo ">> Baue prod-Stage (Auslieferungsabbild, hier nur Bauprobe) ..."
docker build --target prod -t "abgehakt-backend:prod-smoke" . >/dev/null

echo ">> Starte Wegwerf-Postgres (${PG_CONTAINER}) für die pg_engine/pg_session-Fixtures ..."
docker network create "${NETWORK}" >/dev/null
docker run -d --name "${PG_CONTAINER}" --network "${NETWORK}" \
  -e POSTGRES_USER=abgehakt_admin -e POSTGRES_PASSWORD=changeme -e POSTGRES_DB=abgehakt \
  postgres:16-alpine >/dev/null

cleanup() {
  docker rm -f "${PG_CONTAINER}" >/dev/null 2>&1 || true
  docker network rm "${NETWORK}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo ">> Warte auf Postgres ..."
for _ in $(seq 1 30); do
  if docker exec "${PG_CONTAINER}" pg_isready -U abgehakt_admin -d abgehakt >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

# Formatvektoren (abgehakt#72): der Ordner liegt ausserhalb dieses Repositoriums und
# wird nicht mitgeliefert. Pfad aus UEBERGABE_VEKTOREN; ohne die Variable wird nicht
# gemessen, und tests/vektoren/ sammelt nichts ein - kein Skip, denn ein fehlender
# Ordner ist kein fehlgeschlagener Test, und der Skip-Guard wuerde sonst jeden Lauf
# blockieren. Dass nicht gemessen wurde, sagt pytest am Ende jedes Laufs.
vektor_args=()
if [ -n "${UEBERGABE_VEKTOREN:-}" ] && [ -f "${UEBERGABE_VEKTOREN}/protokoll.json" ]; then
  echo ">> Formatvektoren gefunden, read-only gemountet."
  vektor_args=(-v "$(cd "${UEBERGABE_VEKTOREN}" && pwd):/vektoren:ro" -e UEBERGABE_VEKTOREN=/vektoren)
else
  echo ">> Formatvektoren nicht gesetzt (UEBERGABE_VEKTOREN): tests/vektoren/ laeuft nicht."
fi

echo ">> Läuft Suite im Container (Working-Tree app/ + tests/ gemountet, read-only) ..."
# -rs zeigt Skip-Gründe: im Container sollte NICHTS wegen fehlendem Mustang/GS/Postgres skippen.
docker run --rm \
  --network "${NETWORK}" \
  -e DATABASE_URL="postgresql://abgehakt_admin:changeme@${PG_CONTAINER}:5432/abgehakt" \
  -e APP_DATABASE_URL="postgresql://abgehakt_app:test-app-passwort-nur-fuer-testlauf@${PG_CONTAINER}:5432/abgehakt" \
  `# KEIN -e SECRET_KEY mehr (#99 §5.4): der Schlüssel verwaltet sich über` \
  `# storage/secret.key selbst. Genau das soll die Baseline mitprüfen — der` \
  `# Wegwerf-Container liest kein .env, ist also der ehrlichste Testfall dafür.` \
  -e DB_APP_PASSWORD="test-app-passwort-nur-fuer-testlauf" \
  -v "$(pwd)/app:/app/app:ro" \
  -v "$(pwd)/tests:/app/tests:ro" \
  ${vektor_args[@]+"${vektor_args[@]}"} \
  "${IMAGE}" python -m pytest -q -rs "$@"
