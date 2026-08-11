#!/bin/sh
set -e
# Owner-Rolle sicherstellen (#151) — MUSS vor Alembic laufen: `alembic upgrade head`
# verbindet ALS diese Rolle. Auf einer frischen Datenbank gibt es sie nicht, weil
# Postgres beim ersten Start nur den Bootstrap-Superuser anlegt.
python scripts/bootstrap_owner.py
alembic upgrade head
# abgehakt_app + Grants sicherstellen (idempotent) — NACH den Migrationen, damit die
# Grants auf die bereits existierenden Tabellen greifen (B2, Spec §5).
python scripts/bootstrap_roles.py
# Ohne Argumente startet hier ein Produktionsserver: ein Prozess, kein Dateiwaechter.
# Das Nachladen (`--reload`) stand frueher fest in dieser Zeile und lief damit in jeder
# Installation mit. Es kostete einen zweiten Prozess, startete den Server bei jeder
# geschriebenen Python-Datei neu (auch bei Testdateien) und liess sich beim Stoppen nicht
# beenden, was als Exit 137 endete und wie ein Aufhaenger aussah.
#
# Entwicklung haengt sich die Schalter ueber `docker-compose.dev.yml` an ("$@"). Sie ruft
# dabei diesen Entrypoint auf und nicht direkt uvicorn, damit die Migrationen oben
# weiterhin vor dem Server laufen.
exec uvicorn app.main:app --host 0.0.0.0 --port 3000 "$@"
