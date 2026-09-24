# Docker-Issues: Abgehakt
**Analysiert:** 2026-06-11 (docker-expert Skill)  
**Status:** ✅ Behoben 2026-06-11

---

## ✅ Kritisch, behoben

### 1. App läuft als root
**Datei:** `backend/Dockerfile`  
**Fix:** Non-root User `appuser` mit `addgroup`/`adduser` erstellt, `chown -R appuser:appgroup /app`, `USER appuser` gesetzt.

### 2. Kein `.dockerignore`
**Fix:** `backend/.dockerignore` erstellt, es schließt aus: `__pycache__/`, `*.pyc`, `.pytest_cache/`, `tests/`, `.env`, `.git/`.

---

## ✅ Mittlere Priorität, behoben

### 3. `sh -c` als PID 1, kein Signal-Handling
**Fix:** `backend/entrypoint.sh` erstellt mit `exec uvicorn ...` → uvicorn ist PID 1, SIGTERM wird korrekt weitergeleitet.

### 4. Kein Healthcheck für den App-Container
**Fix:** `docker-compose.yml`, Healthcheck auf `/dashboard` mit 15s start_period hinzugefügt.

### 5. Mustang-JAR Cache-Reihenfolge suboptimal
**Status:** Bereits korrekt. JAR bleibt vor `uv sync`; ändert sich `uv.lock`, wird der JAR-Layer aus dem Cache bedient. Kein Fix nötig.

### 6. Keine Resource-Limits
**Fix:** `docker-compose.yml`, `memory: 1G` und `cpus: '1.0'` für den App-Container gesetzt.

---

## 🟢 Minor, offen (akzeptiert)

### 7. `--reload` in CMD
**Hinweis:** Bewusst behalten, das Setup ist rein lokal. Beim Deployment-Upgrade entfernen.

### 8. DB-Port nach außen exponiert
**Stand 2026-09:** erledigt. Die DB hängt an `127.0.0.1:5432:5432`, also nur am Loopback;
direkter `psql`-Zugriff vom Host bleibt unverändert möglich. Die Netzbindungs-Wache in
`.githooks/wachen.sh` blockiert eine Port-Angabe ohne `127.0.0.1:` seither im Push und in
der CI.

---

## ⚠️ Isolierter Zweit-Stack (Git-Worktree): Fallstricke (2026-07-12)

Beim parallelen Testen eines Feature-Branches in einem Git-Worktree neben dem
laufenden Haupt-Stack (z. B. für `subagent-driven-development`) drei nicht
offensichtliche Punkte:

1. **`container_name` in `docker-compose.yml` ist hardcodiert** (`abgehakt_db`,
   `abgehakt_app`, `abgehakt_db_backup`). Ein zweiter `docker compose up` (auch mit
   anderem `-p <project>`) schlägt fehl, weil Docker Container-Namen global
   eindeutig sein müssen, unabhängig vom Compose-Projektnamen. `ports:` sind
   ebenso fest (`127.0.0.1:3000:3000`, `127.0.0.1:5432:5432`) und kollidieren genauso.
2. **`docker-compose.override.yml` merged Listen-Felder (`ports:`) additiv,
   nicht ersetzend.** `ports: []` in einem Override hebt eine bestehende
   `ports: ["127.0.0.1:5432:5432"]` NICHT auf; sie werden zusammengeführt (Ergebnis:
   der alte Port bleibt aktiv → `Bind for 127.0.0.1:5432 failed: port is
   already allocated`). Fix: `ports: !override [...]` (Compose-Spec-Tag,
   ab Compose v2.24 unterstützt) statt einer normalen YAML-Liste.
3. **Compose erkennt „den bestehenden Container für Service X" über interne
   Labels, nicht über `container_name`.** Ein reines Umbenennen von
   `container_name` im Override reicht nicht; Compose versucht beim nächsten
   `up` trotzdem, den alten (namensverschiedenen) Container desselben Service-
   Slots im selben Projekt zu stoppen/ersetzen. Nur ein komplett **neuer
   Projektname** (`docker compose -p <anderer-name> up`) erzeugt einen wirklich
   unabhängigen Container-Satz.
4. **Ein Container kann trotz `--reload`/Signal-Handling-Fix (#3 oben)
   unkillbar werden**, wenn ein Subprocess im Inneren an einem offenen
   `stdin` hängt (siehe Mustang-Hinweis in `ARCHITEKTUR.md`): nicht nur
   `docker compose exec` ohne `-T`, sondern in diesem Fall auch `docker kill`/
   `docker exec .../docker top` schlagen mit `tried to kill container, but
   did not receive an exit event` fehl bzw. hängen selbst. Vermutlich ein
   Docker-Desktop-VM-Zustand, nicht app-seitig behebbar. Workaround: Container
   als Zombie stehen lassen, für den isolierten Testlauf einen **komplett
   neuen Projektnamen** verwenden (siehe Punkt 3) statt den alten Namen
   wiederzuverwenden. Volles Reclaim nur per Docker-Desktop-Neustart.

---

## ⚠️ Docker-Daemon hängt / antwortet erst nach vielen Minuten (2026-07-22)

Beim Test-Audit #98 hing `docker info` / `docker compose ps` / `./run-tests.sh` **10 bis 12 Minuten**,
bevor überhaupt Output kam (Exit danach ok, Daemon-Version 29.x). Symptom: Shell-Timeouts,
kein Suite-Ergebnis. Sah aus wie kaputtes Docker, war aber extreme Latenz.

**Folgen für Agenten-/CI-Arbeit:**
- Kanonische Baseline (`backend/run-tests.sh`) braucht einen **lebenden, antwortenden**
  Daemon; bei Hänger ist ein Audit nur noch statische Code-Analyse (so geschehen 2026-07-22).
- Workaround: Docker Desktop neu starten; kurz `docker info` prüfen (sollte < 5 s antworten),
  dann erst `./run-tests.sh` oder `docker compose exec …`.
- Nicht mit dem Mustang-`stdin`-Hänger (#4 oben / `ARCHITEKTUR.md`) verwechseln: dort hängt ein
  **einzelner Container-Prozess**, hier der **Daemon selbst**.

---

## ⚠️ Volle Suite OHNE `< /dev/null` → unkillbarer Mustang-Prozess verkeilt den app-Container (2026-07-22, #98)

Ein `docker compose exec -T app python -m pytest tests/ -q` **ohne** `< /dev/null` (im
Hintergrund gestartet, stdin also offen) traf beim ersten E2E-Test den Mustang-`stdin`-Hänger
(#4 oben). Der Java-Prozess landete in **uninterruptible sleep (D-state)**: `pkill` im
Container, `docker restart`, `docker rm -f` und selbst SIGKILL scheiterten alle mit
*„tried to kill container, but did not receive an exit event"*; der Container blieb `running
(unhealthy)`. Ein zweiter Suite-Lauf konkurrierte dann mit dem Zombie und wurde **extrem
langsam** (>19 min statt ~4 min). Sah wie Daemon-Latenz aus, war aber CPU-Sättigung durch
den nicht reapbaren Prozess. `docker ps` blieb dabei schnell (< 1 s), nur `docker compose
exec` hing → guter Diskriminator (Prozess-Sättigung, nicht Daemon).

**Nur ein Docker-Desktop-Neustart (VM-Reset) reapt den D-state-Prozess.** Danach `docker
compose up -d` (frischer Container) → volle Suite mit `< /dev/null` lief in **3:44 min,
666 passed**.

**Regel:** Der **volle** `pytest tests/`-Lauf (viele Mustang-E2E) IMMER mit
`-T … < /dev/null` starten, auch im normalen Compose-Stack und nicht nur im `-p`-Worktree.
Einzelne Nicht-Mustang-Dateien sind unkritisch; sobald ein `combine`/`validate` in der
Auswahl ist, ist der offene stdin die Falle.

---

## 🔴 Docker-Desktop-Ressourcen ändern löscht alle Named Volumes (2026-09-01)

**Was passiert ist:** Eine Änderung an den Resource-Settings von Docker Desktop
(Einstellungen → Resources), und danach war *alles* weg: Container, Images und
sämtliche Named Volumes, über alle Projekte auf dem Rechner hinweg. Kein
Fehlerdialog danach, kein Log. Docker Desktop startet einfach mit einer leeren
Umgebung, als wäre es frisch installiert.

**Ursache:** Wird die **Disk-Größe** verkleinert, legt Docker Desktop das
Disk-Image neu an, statt es zu verkleinern. Das Bestätigungsfenster weist darauf
hin, aber es erscheint im selben Zug wie „Apply & restart" und liest sich wie
eine Routinemeldung. **Eine Sicherung legt Docker Desktop dabei nicht an**, und
es gibt keine zweite Kopie: Das alte Image ist überschrieben, nicht verschoben.

**Woran man es erkennt:** der Unterschied zwischen scheinbarer und tatsächlich
belegter Größe des Disk-Images. Nur das beweist die Neuanlage; ein leeres
`docker ps -a` allein könnte auch ein vertauschter Context sein:

```bash
R=~/Library/Containers/com.docker.docker/Data/vms/0/data/Docker.raw
ls -lh "$R" | awk '{print "scheinbar:  " $5}'   # z. B. 24G
du  -h "$R" | awk '{print "belegt:     " $1}'   # 6,1M  → das Image ist leer
```

Weichen die beiden so weit auseinander, ist nichts mehr da. Sind sie ähnlich
groß, liegen die Daten noch und es ist ein anderes Problem; dann zuerst
`docker context ls` prüfen, ob überhaupt die richtige Umgebung aktiv ist
(ein zweiter Daemon wie `colima` ist ein häufiger Grund für „alles weg").

**Was überlebt und was nicht.** Die Grenze verläuft exakt zwischen den beiden
Mount-Arten im Compose:

| | Ort | Nach dem Vorfall |
|---|---|---|
| `postgres_data:/var/lib/postgresql/data` | Named Volume, **im** Disk-Image | weg |
| `./backups:/backups` | Bind Mount, im Projektordner | unversehrt |
| `./storage:/app/storage` | Bind Mount, im Projektordner | unversehrt |

Dass dieses Projekt den Vorfall ohne Datenverlust überstanden hat, liegt allein
daran: Der `db-backup`-Dienst schreibt nach `./backups`, also **außerhalb** des
Disk-Images. Der Dump von 02:00 enthielt die Rechnungen des Vortages; PDF und
XML lagen ohnehin in `./storage`. Ein Sicherungsdienst, der in ein Named Volume
schriebe, wäre mit demselben Schieberegler mitgelöscht worden.

**Wiederherstellung.** Der reguläre Weg steht in der README unter
„Im Ernstfall". Er setzt voraus, dass die Datenbankrollen existieren; sie
entstehen beim ersten Start des `app`-Containers. Ist nur die Datenbank
gefragt und soll das App-Image nicht erst gebaut werden, lassen sich die
Rollen vorab leer anlegen; `ensure_owner_role`/`ensure_app_role` in
`backend/app/db/roles.py` setzen Passwort und Rechte beim nächsten Start
ohnehin neu. Die Funktionen sind idempotent und ausdrücklich dafür gebaut:

```bash
docker compose up -d db

docker compose exec -T db psql -U "$DB_BOOTSTRAP_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 <<'SQL'
DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='abgehakt_admin')
  THEN CREATE ROLE abgehakt_admin LOGIN NOSUPERUSER CREATEROLE CREATEDB; END IF; END $$;
DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='abgehakt_app')
  THEN CREATE ROLE abgehakt_app  LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE; END IF; END $$;
SQL

gunzip -c backups/last/abgehakt-latest.sql.gz \
  | docker compose exec -T db psql -q -v ON_ERROR_STOP=1 -U "$DB_BOOTSTRAP_USER" -d "$DB_NAME"

docker compose up -d app     # setzt Passwörter und Rechte auf die Rollen
```

Ohne die beiden Rollen bricht das Einspielen bei der ersten `ALTER … OWNER TO`-
oder `GRANT`-Zeile ab: Der Dump enthält Rechtezuweisungen, aber kein
`CREATE ROLE`. Mit `ON_ERROR_STOP=1` sieht man das sofort; ohne läuft es scheinbar
durch und hinterlässt eine halbe Datenbank.

**Vorbeugung.** An den Resource-Settings nichts ändern, ohne vorher zu wissen,
was in Named Volumes liegt:

```bash
docker volume ls                      # was gäbe es zu verlieren
docker compose exec db-backup /backup.sh   # Sicherung von jetzt, vor der Änderung
```

Die Disk-Größe **nur vergrößern**. Ein Verkleinern gibt den Platz nicht frei,
den man sich davon erhofft; der Weg dahin ist `docker system prune` bei
laufendem Bestand, nicht der Schieberegler.
