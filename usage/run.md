# Playbook Automation (run)

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

### Playbook-Automation

Der `run`-Befehl fuehrt YAML-basierte Playbooks oder Inline-Steps aus — ideal fuer AI-Agenten und wiederkehrende Workflows.

```bash
# YAML-Playbook ausfuehren
odoodev run playbook.yaml

# Dry-Run — Schritte anzeigen ohne auszufuehren
odoodev run playbook.yaml --dry-run

# JSON-Output (NDJSON) fuer maschinelle Verarbeitung
odoodev run playbook.yaml --output json

# Inline-Steps ohne YAML-Datei
odoodev run --step docker.up --step pull -V 18

# Version ueberschreiben
odoodev run playbook.yaml -V 19

# vars-Werte per CLI ueberschreiben
odoodev run playbook.yaml -D db_name=v18_staging -D backup_dir=/tmp

# Verfuegbare Playbooks auflisten
odoodev run --list
odoodev run --list -V 18
odoodev run --list --output json

# Interaktiv (ohne Argumente): Modus-Auswahl
odoodev run
```

### Playbook-Format

```yaml
version: "18"
on_error: stop          # stop | continue

steps:
  - name: "Start Docker"
    command: docker.up
  - name: "Pull code"
    command: pull
  - name: "Generate config"
    command: repos
    args:
      config-only: true
  - name: "Start Odoo"
    command: start
    on_error: continue  # Per-Step Override
```

### Variablen & Jinja2-Templating

Playbooks unterstuetzen ein optionales `vars:`-Objekt auf oberster Ebene sowie ein
optionales `description:`-Feld. Step-`args` koennen Jinja2-Ausdruecke enthalten:

| Kontext | Beschreibung |
|---------|-------------|
| `{{ vars.x }}` | Wert aus dem `vars:`-Block |
| `{{ env.HOME }}` | Umgebungsvariable |
| `{{ date }}` | Heutiges Datum (ISO 8601, z.B. `2026-06-11`) |

Template-Fehler brechen den Step ab (`on_error` gilt). CLI-Flag `-D`/`--var` (wiederholbar)
ueberschreibt `vars:`-Werte zur Laufzeit.

```yaml
version: "18"
description: "Daily backup"
vars:
  db_name: v18_prod
steps:
  - name: Backup
    command: db.backup
    args:
      name: "{{ vars.db_name }}"
```

CLI-Override:

```bash
odoodev run daily-backup.yaml -D db_name=v18_staging
```

### Playbooks auflisten (`odoodev run --list`)

```bash
odoodev run --list              # alle gefundenen Playbooks
odoodev run --list -V 18        # auf Version 18 einschraenken
odoodev run --list --output json
```

Sucht nach `*.yaml`/`*.yml` in `./playbooks/` und
`<native_dir>/scripts/playbooks/`. Ausgabe: Name, Description, Quelle, Pfad.

### Verfuegbare Commands

| Command | Beschreibung |
|---------|-------------|
| `docker.up` | Docker-Services starten |
| `docker.down` | Docker-Services stoppen |
| `docker.status` | Docker-Status anzeigen |
| `pull` | Git pull fuer alle Repos |
| `repos` | Repositories klonen/aktualisieren |
| `start` | Odoo-Server starten (als Hintergrundprozess) |
| `stop` | Odoo-Server stoppen |
| `db.list` | Datenbanken auflisten |
| `db.backup` | Datenbank-Backup erstellen |
| `db.restore` | Datenbank wiederherstellen |
| `db.drop` | Datenbank loeschen |
| `env.check` | .env-Status pruefen |
| `venv.check` | Venv-Status pruefen |
| `venv.setup` | Venv erstellen/aktualisieren |
| `container.stop` / `container.start` | Docker-Container eines Targets stoppen/starten (idempotent) |
| `server.backup` | Frisches Backup eines Container-Paars (container2backup-kompatibles `.tar.zst`); `safety: true` sichert das Ziel eines Restores |
| `server.restore` | Backup einspielen: erst in eine Zwischen-Datenbank, dann Tausch per Umbenennen; Filestore-Tausch, Sanitize |
| `server.rebuild` | Update-Routine des Servers (`update_docker_odoo.py`): Image bauen, Module aktualisieren, Odoo starten — gehört **hinter** den Restore |
| `server.neutralize` | `odoo-bin neutralize` im laufenden Odoo-Container |
| `server.update-all` | `odoo-bin -u all --stop-after-init` im laufenden Odoo-Container (+ Neustart) — Ausnahme für Hosts ohne `update_docker_odoo.py` |
| `server.verify` | Prüft, ob Odoo die Datenbank wirklich ausliefert: Container healthy, keine hängenden Modulzustände, Login-Seite lädt |
| `sql.execute` | SQL-Statements/-Datei gegen Target- oder Dev-Datenbank |
| `rpc.execute` | Deklarativer Odoo-RPC-Aufruf via odoorpc-toolbox (`odoodev-equitania[rpc]`) |

### Server-Modus (Live→Test-Spiegelung auf Kundenservern)

Playbooks laufen auch auf Produktivservern, auf denen Odoo/PostgreSQL nur als
Docker-Container existieren (`live-odoo`/`live-db`, `test-odoo`/`test-db`) — ohne
Dev-Layout, ohne Host-psql, ohne publizierte DB-Ports (Zugriff via `docker exec`).
Drei neue Top-Level-Sektionen:

```yaml
env_file: /root/.config/odoodev/mirror.env   # Secrets, chmod 600 — {{ env.X }} liest sie
targets:
  test:
    db_container: test-db
    odoo_container: test-odoo
    db_name: production
    data_dir: /opt/odoo/test                 # leer = Auflösung via docker inspect
rpc:                                          # Fallbacks: ODOO_URL/PORT/USER/PASSWORD/DATABASE
  host: "{{ env.ODOO_URL }}"
```

Steps referenzieren ein Target per `target: test`. Die Reihenfolge eines Mirrors:
Ziel sichern (`server.backup` mit `safety: true`) → Quelle sichern → `container.stop`
→ `server.restore` → kundenspezifisches SQL (Enterprise-Code, Website-Domain,
Connector-Resets) → `server.rebuild` → `server.neutralize` → `server.verify`.

- `server.restore` verlangt einen **gestoppten** Odoo-Container. Die bestehende
  Datenbank bleibt unangetastet, bis der Dump vollständig eingespielt ist; erst dann
  wird getauscht.
- `server.rebuild` gehört **hinter** den Restore: Der Schritt aktualisiert die Module
  der eingespielten Datenbank und startet den Container selbst. Ein `container.start`
  davor ist überflüssig.
- `server.neutralize`, `server.update-all` und `server.verify` brauchen den
  **laufenden** Container.

Vor dem ersten Schritt prüft odoodev den Server gegen das Playbook: ob
`docker2update.yaml` dieselbe Datenbank und dieselbe Odoo-Version nennt, ob das Image
zur Version passt, ob eine bestehende Datenbank ungesichert ersetzt würde. Ein Fehler
stoppt den Lauf, bevor etwas verändert wird; `--dry-run` meldet dieselben Befunde,
`--no-preflight` überspringt die Prüfung. Details und vollständiges Beispiel:
`usage/playbook.md`, `server-mirror.yaml`.

### Beispiel-Playbooks

Mitgelieferte Playbooks unter `odoodev/data/examples/playbooks/`:

| Datei | Zweck |
|-------|-------|
| `daily-update.yaml` | Taegliches Update (Docker, Pull, Config) |
| `start-dev.yaml` | Entwicklungsumgebung starten |
| `full-refresh.yaml` | Komplette Umgebung neu aufsetzen |
| `restore-db.yaml` | Datenbank aus Backup wiederherstellen |
| `server-mirror.yaml` | Live→Test-Spiegelung auf einem Kundenserver |

### NDJSON-Output

Mit `--output json` wird pro Event eine JSON-Zeile ausgegeben:

```json
{"event": "playbook_start", "version": "18", "steps": 3}
{"event": "step_start", "index": 1, "total": 3, "name": "Start Docker", "command": "docker.up"}
{"event": "step_done", "name": "Start Docker", "command": "docker.up", "status": "ok"}
{"event": "step_start", "index": 2, "total": 3, "name": "Rebuild", "command": "server.rebuild"}
{"event": "step_progress", "index": 2, "total": 3, "name": "Rebuild", "command": "server.rebuild", "message": "build image odoo/live"}
{"event": "step_done", "name": "Rebuild", "command": "server.rebuild", "status": "ok"}
{"event": "playbook_done", "status": "ok", "steps_ok": 3, "steps_failed": 0}
```

`step_start` und `step_progress` gibt es seit 0.74.0, nicht im `--dry-run`. `step_done.name`
ist der Name des Schritts aus dem Playbook. Ein Empfänger sollte unbekannte Ereignisse
überspringen.

### Fortschritt im Terminal

Jeder Schritt wird beim Start angekündigt (`[2/5] Name`). Am Terminal ist das eine Zeile
mit Spinner und verstrichener Zeit; was der Schritt meldet, bleibt darüber stehen. In
einer Pipe oder einem Cron-Log erscheinen dieselben Meldungen als einfache Zeilen.
`server.rebuild` reicht die Zeilen des Update-Skripts durch, `server.restore` nennt seine
Phasen (entpacken, in die Zwischen-Datenbank einspielen, Filestore, Tausch, Sanitize).

---

## English Documentation

### Playbook Automation

The `run` command executes YAML-based playbooks or inline steps — ideal for AI agents and recurring workflows.

```bash
# Execute YAML playbook
odoodev run playbook.yaml

# Dry-run — show steps without executing
odoodev run playbook.yaml --dry-run

# JSON output (NDJSON) for machine processing
odoodev run playbook.yaml --output json

# Inline steps without YAML file
odoodev run --step docker.up --step pull -V 18

# Override version
odoodev run playbook.yaml -V 19

# Override vars values via CLI
odoodev run playbook.yaml -D db_name=v18_staging -D backup_dir=/tmp

# List available playbooks
odoodev run --list
odoodev run --list -V 18
odoodev run --list --output json

# Interactive (no arguments): mode selection
odoodev run
```

### Playbook Format

```yaml
version: "18"
on_error: stop          # stop | continue

steps:
  - name: "Start Docker"
    command: docker.up
  - name: "Pull code"
    command: pull
  - name: "Generate config"
    command: repos
    args:
      config-only: true
  - name: "Start Odoo"
    command: start
    on_error: continue  # Per-step override
```

### Variables & Jinja2 Templating

Playbooks support an optional top-level `vars:` object and an optional `description:`
field. Step `args` values may contain Jinja2 expressions:

| Context | Description |
|---------|-------------|
| `{{ vars.x }}` | Value from the `vars:` block |
| `{{ env.HOME }}` | Environment variable |
| `{{ date }}` | Today's date (ISO 8601, e.g. `2026-06-11`) |

Template errors fail the step (`on_error` applies). The CLI flag `-D`/`--var`
(repeatable) overrides `vars:` values at runtime.

```yaml
version: "18"
description: "Daily backup"
vars:
  db_name: v18_prod
steps:
  - name: Backup
    command: db.backup
    args:
      name: "{{ vars.db_name }}"
```

CLI override:

```bash
odoodev run daily-backup.yaml -D db_name=v18_staging
```

### List Playbooks (`odoodev run --list`)

```bash
odoodev run --list              # all discovered playbooks
odoodev run --list -V 18        # filter to version 18
odoodev run --list --output json
```

Discovers `*.yaml`/`*.yml` files in `./playbooks/` and
`<native_dir>/scripts/playbooks/`. Output: name, description, source, path.

### Available Commands

| Command | Description |
|---------|-------------|
| `docker.up` | Start Docker services |
| `docker.down` | Stop Docker services |
| `docker.status` | Show Docker status |
| `pull` | Git pull for all repos |
| `repos` | Clone/update repositories |
| `start` | Start Odoo server (as background process) |
| `stop` | Stop Odoo server |
| `db.list` | List databases |
| `db.backup` | Create database backup |
| `db.restore` | Restore database |
| `db.drop` | Drop database |
| `env.check` | Check .env status |
| `venv.check` | Check venv status |
| `venv.setup` | Create/update venv |
| `container.stop` / `container.start` | Stop/start a target's Docker container (idempotent) |
| `server.backup` | Fresh backup of a container pair (container2backup-compatible `.tar.zst`); `safety: true` saves the destination of a restore |
| `server.restore` | Restore a backup: into a staging database first, then swapped in by renaming; filestore swap, sanitize |
| `server.rebuild` | The server's own update routine (`update_docker_odoo.py`): build the image, update the modules, start Odoo — belongs **after** the restore |
| `server.neutralize` | `odoo-bin neutralize` inside the running Odoo container |
| `server.update-all` | `odoo-bin -u all --stop-after-init` inside the running Odoo container (+ restart) — the exception for hosts without `update_docker_odoo.py` |
| `server.verify` | Checks that Odoo really serves the database: container healthy, no module stuck between states, login page loads |
| `sql.execute` | SQL statements/file against a target or dev database |
| `rpc.execute` | Declarative Odoo RPC call via odoorpc-toolbox (`odoodev-equitania[rpc]`) |

### Server Mode (live→test mirroring on customer servers)

Playbooks also run on production servers where Odoo/PostgreSQL exist only as
Docker containers (`live-odoo`/`live-db`, `test-odoo`/`test-db`) — no dev layout,
no host psql, no published DB ports (access via `docker exec`). Three new
top-level sections:

```yaml
env_file: /root/.config/odoodev/mirror.env   # secrets, chmod 600 — read via {{ env.X }}
targets:
  test:
    db_container: test-db
    odoo_container: test-odoo
    db_name: production
    data_dir: /opt/odoo/test                 # empty = resolved via docker inspect
rpc:                                          # fallbacks: ODOO_URL/PORT/USER/PASSWORD/DATABASE
  host: "{{ env.ODOO_URL }}"
```

Steps reference a target via `target: test`. The order of a mirror: save the
destination (`server.backup` with `safety: true`) → back up the source →
`container.stop` → `server.restore` → customer-specific SQL (enterprise code, website
domain, connector resets) → `server.rebuild` → `server.neutralize` → `server.verify`.

- `server.restore` requires a **stopped** Odoo container. The existing database stays
  untouched until the dump has restored completely; only then is it swapped.
- `server.rebuild` belongs **after** the restore: it updates the modules of the restored
  database and starts the container itself. A `container.start` before it is redundant.
- `server.neutralize`, `server.update-all` and `server.verify` need the **running**
  container.

Before the first step odoodev holds the server against the playbook: whether
`docker2update.yaml` names the same database and the same Odoo version, whether the
image matches the version, whether an existing database would be replaced without a
backup. An error stops the run before anything is changed; `--dry-run` reports the same
findings, `--no-preflight` skips the check. Details and the full example:
`usage/playbook.md`, `server-mirror.yaml`.

### Example Playbooks

Bundled playbooks in `odoodev/data/examples/playbooks/`:

| File | Purpose |
|------|---------|
| `daily-update.yaml` | Daily update (Docker, pull, config) |
| `start-dev.yaml` | Start development environment |
| `full-refresh.yaml` | Full environment refresh |
| `restore-db.yaml` | Restore database from backup |
| `server-mirror.yaml` | Live→test mirroring on a customer server |

### NDJSON Output

With `--output json`, one JSON line is emitted per event:

```json
{"event": "playbook_start", "version": "18", "steps": 3}
{"event": "step_start", "index": 1, "total": 3, "name": "Start Docker", "command": "docker.up"}
{"event": "step_done", "name": "Start Docker", "command": "docker.up", "status": "ok"}
{"event": "step_start", "index": 2, "total": 3, "name": "Rebuild", "command": "server.rebuild"}
{"event": "step_progress", "index": 2, "total": 3, "name": "Rebuild", "command": "server.rebuild", "message": "build image odoo/live"}
{"event": "step_done", "name": "Rebuild", "command": "server.rebuild", "status": "ok"}
{"event": "playbook_done", "status": "ok", "steps_ok": 3, "steps_failed": 0}
```

`step_start` and `step_progress` exist since 0.74.0, not in `--dry-run`. `step_done.name`
is the step's name from the playbook. A consumer should skip events it does not know.

### Progress on the terminal

Every step is announced when it starts (`[2/5] name`). On a terminal that is a line with a
spinner and the elapsed time; what the step reports stays above it. Into a pipe or a cron
log the same reports appear as plain lines. `server.rebuild` passes on the lines of the
update script, `server.restore` names its phases (extract, restore into the staging
database, filestore, swap, sanitize).
