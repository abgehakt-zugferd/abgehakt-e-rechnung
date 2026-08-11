FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS base

COPY --from=ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c /uv /usr/local/bin/uv

RUN apt-get update && apt-get install -y --no-install-recommends \
        default-jre-headless=2:1.21-76 \
        ghostscript=10.05.1~dfsg-1+deb13u1 \
        curl=8.14.1-2+deb13u4 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Mustang CLI vor den Dependencies — aendert sich seltener als pyproject/uv.lock.
# SHA-256 ist Trust-on-First-Use: Maven Central publiziert fuer dieses Artefakt nur
# .sha1/.md5 (.sha256 -> HTTP 404). Einmalige Gegenkontrolle per GPG ist erfolgt.
ARG MUSTANG_VERSION=2.24.0
ARG MUSTANG_SHA256=e4904ffa0afdce3f5836dceb927c440a05ed5d60386fdd37e17a4b2f7652edbf
RUN mkdir -p /app/lib && \
    curl -fsSL "https://repo1.maven.org/maven2/org/mustangproject/Mustang-CLI/${MUSTANG_VERSION}/Mustang-CLI-${MUSTANG_VERSION}.jar" \
        -o /app/lib/Mustang-CLI.jar && \
    echo "${MUSTANG_SHA256}  /app/lib/Mustang-CLI.jar" | sha256sum -c -

# Kein venv: uv installiert ins System-Python des Images. Dadurch funktionieren
# entrypoint.sh, `python -m pytest` und jede dokumentierte `docker compose exec`-Zeile
# unveraendert weiter — kein `uv run`-Praefix noetig.
ENV UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# --locked bricht ab, wenn uv.lock nicht zu pyproject.toml passt. NICHT durch --frozen
# ersetzen: das prueft nie und installiert bei Drift still die alte Aufloesung.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-group test

# Versionsidentität. Steht bewusst HINTER den teuren Schichten: davor würde jedes
# Release JRE, Ghostscript, Mustang und die Dependencies neu bauen.
#
# BEWUSST ohne Default: ohne `--build-arg` bleibt die Variable leer, und dann liest
# die App die Datei VERSION (app/config.py). Stünde hier `=dev`, gewänne der Bau
# gegen die Datei und jede aus einem Archiv gebaute Installation hielte sich für
# eine Entwicklungsversion — die Update-Prüfung schweigt für 'dev'.
ARG APP_VERSION=
ENV APP_VERSION=${APP_VERSION}

COPY . .

# Kennungen ausdruecklich vergeben: der README weist Linux-Anwender an, `storage/` auf
# 100:101 zu uebereignen. Ohne --gid/--uid nimmt adduser die naechste freie Kennung, und
# die haengt am Basisabbild -- gid 100 ist dort bereits `users`, deshalb 101 fuer die
# Gruppe. Aendert sich das spaeter, waere die Zahl im README still falsch und der
# Anwender koennte seine eigenen Belege nicht schreiben. `.githooks/wachen.sh` haelt
# beide Stellen zusammen.
RUN addgroup --system --gid 101 appgroup && \
    adduser --system --uid 100 --ingroup appgroup appuser && \
    mkdir -p /app/storage/pdfs /app/storage/xml /app/storage/imports /app/storage/temp && \
    chown -R appuser:appgroup /app && \
    chmod +x /app/entrypoint.sh

CMD ["/app/entrypoint.sh"]

FROM base AS test
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --group test
USER appuser

# prod steht ABSICHTLICH als letzte Stage: `docker build` ohne --target baut die letzte.
FROM base AS prod
USER appuser
