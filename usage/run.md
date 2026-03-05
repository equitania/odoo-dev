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

### Beispiel-Playbooks

Mitgelieferte Playbooks unter `odoodev/data/examples/playbooks/`:

| Datei | Zweck |
|-------|-------|
| `daily-update.yaml` | Taegliches Update (Docker, Pull, Config) |
| `start-dev.yaml` | Entwicklungsumgebung starten |
| `full-refresh.yaml` | Komplette Umgebung neu aufsetzen |
| `restore-db.yaml` | Datenbank aus Backup wiederherstellen |

### NDJSON-Output

Mit `--output json` wird pro Event eine JSON-Zeile ausgegeben:

```json
{"event": "playbook_start", "version": "18", "steps": 3}
{"event": "step_done", "name": "Start Docker", "command": "docker.up", "status": "ok"}
{"event": "step_done", "name": "Pull code", "command": "pull", "status": "ok"}
{"event": "playbook_done", "status": "ok", "steps_ok": 3, "steps_failed": 0}
```

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

### Example Playbooks

Bundled playbooks in `odoodev/data/examples/playbooks/`:

| File | Purpose |
|------|---------|
| `daily-update.yaml` | Daily update (Docker, pull, config) |
| `start-dev.yaml` | Start development environment |
| `full-refresh.yaml` | Full environment refresh |
| `restore-db.yaml` | Restore database from backup |

### NDJSON Output

With `--output json`, one JSON line is emitted per event:

```json
{"event": "playbook_start", "version": "18", "steps": 3}
{"event": "step_done", "name": "Start Docker", "command": "docker.up", "status": "ok"}
{"event": "step_done", "name": "Pull code", "command": "pull", "status": "ok"}
{"event": "playbook_done", "status": "ok", "steps_ok": 3, "steps_failed": 0}
```
