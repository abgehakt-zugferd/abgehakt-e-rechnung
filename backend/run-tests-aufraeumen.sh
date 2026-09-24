# Aufraeumen fuer den Wegwerf-Postgres von run-tests.sh.
# Absichtlich sourcebar: der Host-Test in .githooks/ ruft nur diese Funktion,
# ohne Image-Bau und Suite. Erwartet PG_CONTAINER und NETWORK in der Umgebung.
#
# shellcheck shell=bash

cleanup() {
  # -v nimmt das anonyme Volume von /var/lib/postgresql/data mit (Issue #97).
  # Ohne -v bleibt pro Lauf ein verwaistes Volume und fuellt die Docker-Platte.
  docker rm -fv "${PG_CONTAINER}" >/dev/null 2>&1 || true
  docker network rm "${NETWORK}" >/dev/null 2>&1 || true
}
