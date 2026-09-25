#!/usr/bin/env bash
# Host-Test: Aufraeumen des Wegwerf-Postgres entfernt auch das anonyme Volume
# (Issue #97). Laeuft auf dem Host, nicht in der pytest-Suite: der Suite-Container
# sieht den Docker-Dienst des Hosts nicht.
#
# Pruefbefehl: .githooks/test_run_tests_aufraeumen.sh

set -uo pipefail

hier=$(cd "$(dirname "$0")" && pwd)
wurzel=$(cd "$hier/.." && pwd)
# shellcheck source=../backend/run-tests-aufraeumen.sh
source "$wurzel/backend/run-tests-aufraeumen.sh"

fehl=0

NETWORK="abgehakt-cleanup-test-net-$$"
PG_CONTAINER="abgehakt-cleanup-test-db-$$"

# Notausstieg: Container und Netz wegraeumen, falls der Test vor cleanup() stirbt.
# Kein docker volume rm und kein prune: produktive Volumes auf dem Host bleiben unangetastet.
# Mit -v am Container-rm nimmt Docker nur das Volume dieses Wegwerf-Containers mit.
notausstieg() {
  docker rm -fv "${PG_CONTAINER}" >/dev/null 2>&1 || true
  docker network rm "${NETWORK}" >/dev/null 2>&1 || true
}
trap notausstieg EXIT

docker network create "${NETWORK}" >/dev/null
docker run -d --name "${PG_CONTAINER}" --network "${NETWORK}" \
  -e POSTGRES_USER=abgehakt_admin -e POSTGRES_PASSWORD=changeme -e POSTGRES_DB=abgehakt \
  postgres:16-alpine >/dev/null

vol=$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Name}}{{end}}{{end}}' \
  "${PG_CONTAINER}")

if [ -z "$vol" ]; then
  echo "ROT  aufraeumen_nimmt_volume: kein Volume an /var/lib/postgresql/data" >&2
  exit 1
fi

# Gegenstand unter Test: dieselbe cleanup()-Naht wie im Laeufer.
cleanup

# Trap nicht mehr noetig: cleanup hat Container und Netz bereits bedient.
trap - EXIT

if docker volume inspect "$vol" >/dev/null 2>&1; then
  echo "ROT  aufraeumen_nimmt_volume: Volume $vol existiert nach cleanup noch" >&2
  fehl=1
else
  echo "gruen aufraeumen_nimmt_volume"
fi

if [ "$fehl" -ne 0 ]; then
  echo "test_run_tests_aufraeumen: ROT ($fehl Fall)" >&2
  exit 1
fi
echo "test_run_tests_aufraeumen: alle gruen"
