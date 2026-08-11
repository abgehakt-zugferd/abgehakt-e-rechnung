#!/usr/bin/env bash
# uv ohne Host-Installation ausführen.
#
# WARUM dieser Umweg: Das offizielle uv-Image (ghcr.io/astral-sh/uv) ist distroless
# und enthält KEIN Python. `uv lock` bricht dort ab mit
#   "Failed to discover managed Python installations"
# und liefert dabei rc=0 UND keine Lockdatei — ein stiller Fehlschlag.
# Deshalb: Binary aus dem uv-Image ziehen, in python:3.11-slim ausführen.
#
# Die beiden Digests sind dieselben wie in backend/Dockerfile. Bei einem uv- oder
# Base-Image-Bump MÜSSEN beide Stellen gemeinsam wandern — sonst lockt dieses Skript
# mit einer anderen uv-Version, als der Build anschliessend prüft.
#
# Nutzung (aus backend/):
#   ./uv.sh lock                            # Lock aus pyproject.toml erzeugen
#   ./uv.sh lock --check                    # Drift prüfen, ohne zu schreiben
#   ./uv.sh lock --upgrade-package jinja2   # gezielt EIN Paket anheben
set -euo pipefail
cd "$(dirname "$0")"

UV_IMAGE="ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c"
PY_IMAGE="python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93"

TMP="$(mktemp -d)"
CID=""
cleanup() {
  [ -n "${CID}" ] && docker rm -f "${CID}" >/dev/null 2>&1 || true
  rm -rf "${TMP}"
}
trap cleanup EXIT

CID="$(docker create "${UV_IMAGE}")"
docker cp "${CID}:/uv" "${TMP}/uv" >/dev/null
docker rm "${CID}" >/dev/null
CID=""

# KEIN `exec`: das ersetzt den Shell-Prozess, wodurch der EXIT-Trap entfaellt
# und ${TMP} mit der 61-MB-uv-Binary liegen bleibt. Rueckgabewert selbst durchreichen.
rc=0
docker run --rm \
  -v "$(pwd):/w" \
  -v "${TMP}/uv:/usr/local/bin/uv:ro" \
  -w /w "${PY_IMAGE}" uv "$@" || rc=$?
exit "${rc}"
