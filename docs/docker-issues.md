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
**Hinweis:** `5432:5432` bleibt für direkten `psql`-Zugriff (lokale Entwicklung). Kein Sicherheitsrisiko auf Localhost.

---

## ⚠️ Isolierter Zweit-Stack (Git-Worktree): Fallstricke (2026-07-12)

Beim parallelen Testen eines Feature-Branches in einem Git-Worktree neben dem
laufenden Haupt-Stack (z. B. für `subagent-driven-development`) drei nicht
offensichtliche Punkte:

1. **`container_name` in `docker-compose.yml` ist hardcodiert** (`abgehakt_db`,
   `abgehakt_app`, `abgehakt_db_backup`). Ein zweiter `docker compose up` (auch mit
   anderem `-p <project>`) schlägt fehl, weil Docker Container-Namen global
   eindeutig sein müssen, unabhängig vom Compose-Projektnamen. `ports:` sind
   ebenso fest (`3000:3000`, `5432:5432`) und kollidieren genauso.
2. **`docker-compose.override.yml` merged Listen-Felder (`ports:`) additiv,
   nicht ersetzend.** `ports: []` in einem Override hebt eine bestehende
   `ports: ["5432:5432"]` NICHT auf; sie werden zusammengeführt (Ergebnis:
   der alte Port bleibt aktiv → `Bind for 0.0.0.0:5432 failed: port is
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
