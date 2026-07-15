# Playbook Assistant (playbook)

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

### Der Playbook-Assistent

`odoodev playbook create` führt interaktiv durch alle Fragen und erzeugt am Ende eine
lauffähige Playbook-YAML für `odoodev run` — inklusive optionaler Secrets-Datei (env_file,
Rechte 600). Für die GUI (odoodev-gui) und Agenten gibt es denselben Generator ohne Prompts
über eine Answers-JSON-Datei.

```bash
# Interaktiver Assistent (Dev- oder Server-Mode)
odoodev playbook create

# Non-interaktiv aus einer Answers-Datei (GUI-/Agent-Modus)
odoodev playbook create --answers answers.json --non-interactive

# Ausgabepfad überschreiben, bestehende Dateien überschreiben
odoodev playbook create --answers answers.json --non-interactive -o playbooks/mirror.yaml --force

# Feldschema für GUI-Formulare (maschinenlesbar)
odoodev playbook schema --json

# Playbook prüfen ohne Ausführung
odoodev playbook validate playbooks/mirror.yaml
odoodev playbook validate playbooks/mirror.yaml --json
```

#### Sprachwahl (seit v0.56.0)

Ist keine Sprache explizit konfiguriert (`--lang`, `ODOODEV_LANG`, `cli.language` in
`~/.config/odoodev/config.yaml`), beginnt der Assistent mit **„Sprache / Language?"**
(Deutsch/English, Vorbelegung aus der Shell-Locale) und bietet an, die Wahl als
odoodev-weiten Standard zu speichern. Danach führt er in nummerierten Schritten durch
den Ablauf („Schritt 1/6 — Grundlagen" … „Schritt 6/6 — Zusammenfassung";
Dev-Zweig: 4 Schritte).

#### Server-Branch: Quelle → Ziel → Optionen (seit v0.55.0)

Der Server-Zweig folgt dem Mirror-Modell **Quelle → Ziel**: erst die Quelle, dann das
Ziel, dann die Optionen — `server.restore` ist immer Teil des Mirrors. Der Quell-Block
fragt „Quell-Name", der Ziel-Block „Ziel-Name"; das generische „Target-Name" gibt es
nur noch für optionale Zusatz-Targets:

1. **„Was ist die QUELLE des Mirrors?"** (Auswahl):
   - **Frisches Backup von einem laufenden Container-Paar** — fragt das Quell-Target
     (z. B. `live` / `live-db` / `live-odoo`) und das Backup-Verzeichnis; die
     Restore-Quelle wird automatisch aus der Backup-Namenskonvention abgeleitet
     (`{db}_{container}_dockerbackup_*.tar.zst`, neueste Datei) und kann auf Wunsch
     angepasst werden. Erzeugt den `server.backup`-Step.
   - **Bestehende Backup-Datei** — fragt nur den Pfad; kein Backup-Step.
   - **Neuestes Backup nach Muster** — fragt Verzeichnis + Pattern; kein Backup-Step.
2. **„Was ist das ZIEL?"** — das Ziel-Target (z. B. `test` / `test-db` / `test-odoo`).
   **Self-Mirror-Guard:** Nutzt das Ziel denselben DB-Container wie die Quelle,
   warnt der Assistent und fragt explizit nach (Default: Nein → Ziel neu eingeben) —
   sonst würde der Restore das gerade gesicherte System überschreiben.
3. **Options-Checkbox** (Restore ist immer dabei):
   `server.rebuild` (optional) — Ziel-Container komplett neu aufbauen via
   `update_docker_odoo.py` (Release-Abruf per Access-Code aus `release.txt`,
   `docker build`, Container-Neuerstellung; steht **vor** stop/restore, weil das
   Skript den Container am Ende selbst startet) · `container.stop` ·
   `sql.execute` (Statement-Builder mit Presets: **Enterprise-Code setzen**
   (`{{ env.PARTNER_ENTERPRISE_CODE }}`), **eq_cloud-Connector-Parameter leeren**,
   **Website-Domain tauschen**, freies SQL) · `container.start` ·
   `server.neutralize` · `server.update-all` · `rpc.execute`
4. **Restore-Details** — `template`, `drop`, Sanitize-Checkbox (`deactivate_cron`,
   `neutralize`, `anonymize`, `wipe`, `purge_transactions`) plus separater Confirm
   für `purge_master_data`

Danach: freie Zusatz-Schritte (Escape-Hatch), RPC-Verbindungsblock, Variablen,
Secrets-Datei, Ausgabepfad, Zusammenfassung (zeigt Quelle → Ziel) mit Bestätigung.

**Wichtig — Server-Pfade:** Alle Pfade, die im Playbook landen und auf dem Server
ausgewertet werden (`backup_dir`, `script_path`, Backup-Datei etc.), werden vom
Assistenten NICHT lokal expandiert — `~/update_docker_odoo.py` bleibt wörtlich in
der YAML und wird erst auf dem Server aufgelöst.

#### Secrets

Secrets landen nie in der YAML. Der Assistent erkennt alle `{{ env.X }}`-Referenzen im
erzeugten Playbook automatisch, fragt die Werte ab (maskiert bei `PASSWORD`/`SECRET`/
`TOKEN`/`KEY`/`CODE` im Namen) und schreibt sie mit Rechten 600 in die env_file.
Existiert die Datei bereits, wird gemergt (Bestand bleibt, neue Keys gewinnen) — niemals
still überschrieben. RPC-Zugangsdaten gehören als `ODOO_URL`/`ODOO_USER`/`ODOO_PASSWORD`
(+ optional `ODOO_DATABASE`/`ODOO_PORT`/`ODOO_PROTOCOL`) in die env_file.

**Achtung:** Auch die Answers-Datei kann Secrets enthalten (`env_file.secrets`) — wie die
env_file behandeln: 0600, niemals committen, nach Gebrauch löschen. Alternativ
`"generate": false` setzen und die env_file manuell befüllen.

#### Cron-Einbindung

Am Ende gibt der Assistent einen Crontab-Vorschlag aus, z. B.:

```
0 2 * * * odoodev run /root/playbooks/live-test-mirror.yaml >> /var/log/odoodev-mirror.log 2>&1
```

In Cron immer absolute Pfade verwenden (Playbook, env_file, backup_dir).

---

## English Documentation

### The playbook assistant

`odoodev playbook create` interviews you and writes a runnable playbook YAML for
`odoodev run`, including an optional 0600 secrets env_file. The GUI (odoodev-gui) and
agents use the identical generator without prompts via an answers JSON file — one shared
core (`odoodev/core/playbook_builder.py`), so the two frontends can never drift.

### Answers JSON reference (`--answers`)

```json
{
  "schema_version": 1,
  "playbook_type": "server",
  "name": "live-test-mirror",
  "description": "Mirror the live database to the test system",
  "version": "18",
  "on_error": "stop",
  "targets": {
    "live": {"db_container": "live-db", "odoo_container": "live-odoo", "db_name": "production"},
    "test": {"db_container": "test-db", "odoo_container": "test-odoo", "db_name": "production",
             "data_dir": "/opt/odoo/test"}
  },
  "rpc": {"enabled": true, "host": "{{ env.ODOO_URL }}", "db": "production"},
  "vars": {"customer": "acme"},
  "recipe": {
    "destination": "test",
    "backup": {"enabled": true, "target": "live", "backup_dir": "/opt/backups/docker",
               "compression_level": 5, "only_sql": false},
    "rebuild": {"enabled": true, "target": "test", "script_path": "~/update_docker_odoo.py",
                "config": "~/docker2update.yaml", "timeout": 7200},
    "stop_before_restore": true,
    "restore": {
      "enabled": true, "target": "test",
      "backup_source": {"mode": "newest_in_dir", "dir": "/opt/backups/docker",
                        "pattern": "production_*_dockerbackup_*.tar.zst", "select_by": "mtime"},
      "template": "template0", "drop": true,
      "sanitize_flags": ["deactivate_cron", "neutralize"],
      "purge_master_data": false
    },
    "sql_after_restore": {"enabled": true, "on_error": "continue", "statements": ["..."]},
    "start_after_restore": true,
    "neutralize": {"enabled": true},
    "update_all": {"enabled": true, "restart": true, "on_error": "continue"},
    "rpc_call": {"enabled": true, "model": "ir.config_parameter", "mode": "method",
                 "method": "set_param",
                 "args": ["mail.catchall.domain", "{{ vars.customer }}-test.ownerp.app"]}
  },
  "extra_steps": [],
  "env_file": {"path": "/root/.config/odoodev/mirror.env", "generate": true,
               "secrets": {"ODOO_URL": "https://acme-test.ownerp.app",
                           "PARTNER_ENTERPRISE_CODE": "XXXX"}},
  "output_path": "./playbooks/live-test-mirror.yaml"
}
```

Notes:

- `schema_version`: currently `2` (v0.55.0, source-first wizard flow); `1` (v0.54.0)
  is still accepted — the answers format itself is unchanged between the two.
- `playbook_type`: `"server"` or `"dev"`. Dev playbooks use `dev_steps` instead of
  `targets`/`recipe`: a list of `{"command": "pull", "args": {...}}` entries (plain
  strings allowed); the builder orders them canonically (docker.up → pull → repos →
  db.* → start → stop → docker.down).
- `recipe.destination` (optional) pins the mirror destination target; otherwise it is
  derived from `restore.target` → `rebuild.target` → first non-backup target.
- `recipe.rpc_call.mode`: `"method"` (`method` + optional `args`/`kwargs`),
  `"domain_values"` (`domain` + `values` → search-then-write) or
  `"domain_method"` (`domain` + `method`).
- Validation collects **all** structural problems into one error report.
- Non-interactive mode refuses to overwrite an existing playbook or env_file without
  `--force` (a cron-deployed production secrets file must never be clobbered silently).

### Schema JSON (`playbook schema --json`)

One JSON line on stdout; the GUI renders its form from it — no hardcoding:

- `schema_version`, `playbook_types`
- `sections[]` with `key`, `applies_to` (dev/server), `fields[]`
  (`key`, `type`, `label_key`, `required`, `default`, `choices`,
  `depends_on`/`depends_value` — flat single-condition model) or `item_fields[]` for
  repeatable sections (`server_targets`, `server_extra_steps`)
- Field types: `text | password | select | checkbox | confirm | path | int | json |
  list[str] | list[sql] | map[str] | map[secret_text]`
- `choices_source` entries are resolved inline where statically possible
  (`available_versions`, `server_commands`); `targets` stays a reference because it
  depends on the user's own target answers
- `sql_presets`, `rpc_env_keys`, `dev_step_groups`
- `step_args`: descriptive argument specs for every playbook step command
  (the same data drives the wizard's dev-branch prompts)

### The `server.rebuild` step

Rebuilds a target's Odoo container from scratch by shelling out to the deployed
`update_docker_odoo.py` (myodoo-docker): release info is fetched via the access code in
`release.txt` inside the build folder, the image is rebuilt with `docker build`, and the
container is recreated under the same name.

| Arg | Default | Meaning |
|---|---|---|
| `container` | target's `odoo_container` | passed as `-s` (single-container update) |
| `script_path` | `~/update_docker_odoo.py` | script location on the server |
| `config` | `~/docker2update.yaml` | passed as `-c` |
| `timeout` | `7200` | seconds (script-internal build/update timeouts are hardcoded) |
| `extra_args` | `[]` | e.g. `--verbose` |

Caveats: the script **starts the container itself** at the end — place `server.rebuild`
before `container.stop` + `server.restore`. It runs a host-wide `docker system prune -f`
and has no lock file — never run two rebuilds on the same host in parallel. The container
must be an **active** entry in `docker2update.yaml`.

### Env-file variables

| Variable | Used by |
|---|---|
| `ODOO_URL`, `ODOO_USER`, `ODOO_PASSWORD` | `rpc:` block / `rpc.execute` fallbacks |
| `ODOO_DATABASE`, `ODOO_PORT`, `ODOO_PROTOCOL` | optional RPC fallbacks |
| `PARTNER_ENTERPRISE_CODE` | enterprise-code SQL preset |
| any custom `{{ env.X }}` | your own SQL/steps — auto-detected by the assistant |

### GUI integration (odoodev-gui)

Round trip: `playbook schema --json` → render form → collect answers →
`playbook create --answers f.json --non-interactive [-o path] [--force]` →
`playbook validate path --json` → `odoodev run path --output json` (NDJSON stream).
Write the answers file with 0600 permissions and delete it after use when it contains
inline secrets.
