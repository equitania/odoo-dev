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
`~/.config/odoodev/config.yaml`), beginnt der Assistent mit **„Sprache / Language?“**
(Deutsch/English, Vorbelegung aus der Shell-Locale) und bietet an, die Wahl als
odoodev-weiten Standard zu speichern. Danach führt er in nummerierten Schritten durch
den Ablauf („Schritt 1/6 — Grundlagen“ … „Schritt 6/6 — Zusammenfassung“;
Dev-Zweig: 4 Schritte).

#### Auf einem ownERP-Server: wählen statt tippen (seit v0.73.0)

Läuft der Assistent auf einem Server, den myodoo-docker eingerichtet hat, liest er dessen
eigene Konfiguration und fragt nur noch, was dort nicht steht:

- **`~/docker2update.yaml`** — Quelle und Ziel werden als Auswahl angeboten, etwa
  „live-odoo — Datenbank acme_prod (DB-Container live-db)“. Odoo-Container, Datenbank,
  DB-Container, Datenbankbenutzer und Datenverzeichnis kommen aus dem Eintrag. Die als
  Quelle gewählte Instanz wird nicht als Ziel angeboten. „Anderes Container-Paar“ führt
  zur Handeingabe. Die Versionsfrage ist mit der Version aus der Datei vorbelegt; weicht
  eine gewählte Instanz davon ab, sagt der Assistent das sofort.
- **`~/container2backup.yaml`** — das Backup-Verzeichnis (`defaults.backup_path` +
  `docker`) ist der Vorschlag für Quell-Backup, Sicherung des Ziels und die Suche nach
  der neuesten Datei.
- **Vorhandene Backups** — bei „Bestehende Backup-Datei“ erscheinen die neuesten Archive
  dieses Verzeichnisses mit Datum und Größe zur Auswahl; „Andere Datei“ fragt den Pfad.
- **Prüfung am Ende** — nach dem Schreiben läuft die Vorabprüfung (siehe unten) gegen
  diesen Server. Befunde werden angezeigt, das Playbook ist trotzdem geschrieben.

Fehlen die beiden Dateien, fragt der Assistent wie bisher jeden Wert ab.

#### Server-Branch: Quelle → Ziel → Optionen (seit v0.55.0)

Der Server-Zweig folgt dem Mirror-Modell **Quelle → Ziel**: erst die Quelle, dann das
Ziel, dann die Optionen — `server.restore` ist immer Teil des Mirrors. Der Quell-Block
fragt „Quell-Name“, der Ziel-Block „Ziel-Name“; das generische „Target-Name“ gibt es
nur noch für optionale Zusatz-Targets:

1. **„Was ist die QUELLE des Mirrors?“** (Auswahl):
   - **Frisches Backup vom laufenden Quellsystem** — fragt das Quell-Target
     (z. B. `live` / `live-db` / `live-odoo`) und das Backup-Verzeichnis; der
     Restore verwendet automatisch die in diesem Lauf erzeugte Backup-Datei
     (`backup_source.mode: from_backup_step`, seit v0.57.0) — keine Pattern-Fragen.
     Erzeugt den `server.backup`-Step.
   - **Bestehende Backup-Datei** — fragt nur den Pfad; kein Backup-Step.
   - **Neueste Backup-Datei aus einem Verzeichnis** — fragt Verzeichnis + Pattern;
     kein Backup-Step.
2. **„Was ist das ZIEL?“** — das Ziel-Target (z. B. `test` / `test-db` / `test-odoo`).
   **Self-Mirror-Guard:** Nutzt das Ziel denselben DB-Container wie die Quelle,
   warnt der Assistent und fragt explizit nach (Default: Nein → Ziel neu eingeben) —
   sonst würde der Restore das gerade gesicherte System überschreiben.
3. **Options-Checkbox** (Restore ist immer dabei; nur Infrastruktur-Schritte, in der
   Reihenfolge, in der sie laufen):
   **Sicherung des Ziels** (`server.backup` mit `safety: true`) — sichert die
   Datenbank, die gleich ersetzt wird; hat das Ziel noch keine, ist der Schritt
   ein Leerlauf · `container.stop` ·
   `sql.execute` (Statement-Builder mit Presets: **Enterprise-Code setzen**
   (`{{ env.PARTNER_ENTERPRISE_CODE }}`), **eq_cloud-Connector-Parameter leeren**,
   **Website-Domain tauschen**, freies SQL) ·
   `server.rebuild` — die Update-Routine des Servers (`update_docker_odoo.py`):
   Release-Abruf per Access-Code aus `release.txt`, `docker build`, Modul-Update,
   Start. Steht seit 0.72.0 **hinter** dem Restore, damit sie die eingespielte
   Datenbank aktualisiert und nicht die, die gleich ersetzt wird ·
   `container.start` (entfällt, wenn der Rebuild gewählt ist — der startet selbst) ·
   `server.update-all` (Ausnahme für Hosts ohne `update_docker_odoo.py`) ·
   `server.verify` — prüft, ob Odoo die Datenbank wirklich ausliefert ·
   `rpc.execute`
4. **Restore-Details** — `template`, `drop`, dann die EINE Frage **„Was soll mit
   der wiederhergestellten Datenbank passieren?“** (`deactivate_cron`,
   `neutralize`, `anonymize`, `wipe`, `purge_transactions`; seit v0.57.0 deckt
   `neutralize` hier die komplette Neutralisierung ab — psql-Sanitize-Flag UND
   der `server.neutralize`-Step nach `container.start`; ohne „nach dem Restore
   starten“ entfällt der Step mit Warnung) plus separater Confirm für
   `purge_master_data`

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
  "schema_version": 4,
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
    "safety_backup": {"enabled": true, "backup_dir": "/opt/backups/docker"},
    "rebuild": {"enabled": true, "target": "test", "position": "after_restore",
                "script_path": "~/update_docker_odoo.py",
                "config": "~/docker2update.yaml", "timeout": 7200},
    "stop_before_restore": true,
    "restore": {
      "enabled": true, "target": "test",
      "backup_source": {"mode": "from_backup_step"},
      "template": "template0", "drop": true,
      "sanitize_flags": ["deactivate_cron", "neutralize"],
      "purge_master_data": false
    },
    "sql_after_restore": {"enabled": true, "on_error": "continue", "statements": ["..."]},
    "start_after_restore": true,
    "neutralize": {"enabled": true},
    "update_all": {"enabled": false},
    "verify": {"enabled": true},
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

- `schema_version`: currently `4` (v0.72.0); `1` (v0.54.0), `2` (v0.55.0) and `3`
  (v0.57.0) are still accepted — the answers format is backward compatible across
  all four. The version decides one default: **where `server.rebuild` goes.** A
  file with `schema_version` 1–3 keeps the step order it was written for (rebuild
  before the restore), a v4 file gets it after the restore. `recipe.rebuild.position`
  (`"after_restore"` / `"before_restore"`) overrides that in either direction.
- With the rebuild after the restore no `container.start` step is generated even
  when `start_after_restore` is true — `update_docker_odoo.py` starts the container.
- `recipe.safety_backup` (`enabled`, `backup_dir`, optional `compression_level`): a
  `server.backup` of the DESTINATION with `safety: true`, generated as the very
  first step — before the source backup, so that `from_backup_step` still receives
  the source's file.
- `recipe.verify` (`enabled`, optional `timeout`): a `server.verify` step behind the
  last step that touches the instance. Generated only when something starts Odoo
  (rebuild after the restore, or `start_after_restore`).
- `recipe.restore.backup_source.mode`: `"from_backup_step"` (use the exact file the
  `server.backup` step of the same run creates — requires `recipe.backup.enabled`),
  `"file"` (`path`) or `"newest_in_dir"` (`dir` + `pattern` + optional `select_by`).
- `recipe.neutralize` is still accepted in answers files; the wizard derives it from
  the `neutralize` sanitize flag (one decision covers psql flag + odoo-bin step).
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

Runs the server's own update routine by shelling out to the deployed
`update_docker_odoo.py` (myodoo-docker): release info is fetched via the access code in
`release.txt` inside the build folder, the image is rebuilt with `docker build`, the
modules of the database named for this container in `docker2update.yaml` are updated, and
the container is started under the same name.

| Arg | Default | Meaning |
|---|---|---|
| `container` | target's `odoo_container` | passed as `-s` (single-container update) |
| `script_path` | `~/update_docker_odoo.py` | script location on the server |
| `config` | `~/docker2update.yaml` | passed as `-c` |
| `timeout` | `7200` | seconds (script-internal build/update timeouts are hardcoded) |
| `extra_args` | `[]` | e.g. `--verbose` |
| `trust_exit_code` | `false` | `true` skips the check of the script's output described below |

**Place it after `server.restore`.** It is the step that brings the restored database to
the module state of the image; before the restore it updates the database that is about
to be replaced. The script starts the container itself, so no `container.start` follows.

**Exit code 0 is not the whole contract.** The script has reported a successful update
while Odoo could not load the database at all (an image whose modules were newer than
its kernel). The step therefore fails when the output carries `Failed to initialize
database`, `Failed to load registry` or `Couldn't load module`, and quotes those lines.

Caveats: the script prunes dangling images and the build cache host-wide and has no lock
file — never run two rebuilds on the same host in parallel. The container must be an
**active** entry in `docker2update.yaml`, with the `database_name` of the target and the
`odoo_version` of the playbook; the preflight below stops the run otherwise.

### The `server.restore` step: nothing is dropped before the restore succeeded

The dump is restored into a staging database `<db>__odoodev_new`, the filestore into
`filestore/<db>.odoodev_new`. Only when both are complete are they renamed into place;
the previous database and filestore are moved to `…_old` for the moment of the swap and
removed afterwards. A broken archive, a full disk or a missing extension therefore leave
the existing database exactly as it was.

- It needs room for the old and the new database side by side while the step runs.
- `psql` exits 0 even when statements of the dump failed. The step therefore reads what
  psql reported: an error that means incomplete data (disk full, lost connection,
  truncated or mis-encoded dump) fails the restore; any other SQL error is counted and
  quoted in the step's message. And before the swap the restored copy must have installed
  modules in `ir_module_module` — a dump that broke off early never replaces a working
  database. `check_restored: false` switches that last check off for a non-Odoo dump.
- `drop: false` refuses an existing database instead of replacing it.
- A backup that uses pgvector stops the step before any change when the database server
  does not offer the `vector` extension; `without_pgvector: true` restores without the
  AI tables.
- A database `<db>__odoodev_old` or a directory `filestore/<db>.odoodev_old` found at the
  start is the previous state kept by an interrupted restore and may be the only copy.
  The step stops and names it; rename it back or remove it by hand.
- The `filestore` directory itself is handed to the Odoo user (`chown_uid`/`chown_gid`,
  default 1000:1000), not only the database's folder in it.
- Database names may contain letters, digits, `_`, `-`, `.` and `$`, up to 50 characters.

### The `server.verify` step

A started container and an update that exited 0 say little: Odoo can be running while
every page answers 500. The step checks, in this order:

1. the container reports `healthy` (waits while it is `starting`, up to `timeout`);
2. no module of the database is left in `to upgrade`, `to install` or `to remove`;
3. the login page of the database answers below HTTP 500 (skipped, and said so, when
   port 8069 is not published);
4. the image's kernel is not older than the one named in the restored backup's manifest.

| Arg | Default | Meaning |
|---|---|---|
| `timeout` | `300` | seconds to wait for `healthy` and for the first HTTP answer |
| `check_modules` | `true` | check 2 |
| `http_check` | `true` | check 3 |
| `http_port` | `8069` | container port whose published address is used |

### Preflight: checks before the first step

A playbook containing `server.restore` or `server.rebuild` is held against the host
before anything runs. `odoodev run --dry-run` performs the same checks and exits 1 on an
error; `--no-preflight` skips them.

| Finding | Level |
|---|---|
| `docker2update.yaml` updates another database for the container than the playbook's target | error |
| `docker2update.yaml` has another `odoo_version` than the playbook | error |
| the container is not defined in `docker2update.yaml` | error |
| the image is another Odoo major version than the playbook (warning if the playbook rebuilds it) | error |
| the image's kernel is older than the one in the backup's manifest, and no rebuild follows | error |
| … and a rebuild follows the restore | warning |
| the database exists and the restore has `drop: false` | error |
| the database exists and no `server.backup` of it precedes the restore | warning |
| the container is `active: false` in `docker2update.yaml` | warning |
| `server.rebuild` sits before the restore, or nothing updates the restored database | warning |

An error stops the run before step 1. What cannot be read — no Docker, no
`docker2update.yaml`, no manifest next to the backup — produces no finding, so a dry run
on a workstation stays clean. Findings appear as one leading result named `Preflight`
(NDJSON: `step_done` with `command: "preflight"`), and only when there is something to
report.

The kernel comparison relies on the manifest `server.backup` writes next to its archive
(`<file>.manifest`, `odoo_build=26.09.29`). A manifest from other tooling is read too
(`<file>.manifest` or `<file without .tar.zst>.manifest`, `key=value` lines); without an
`odoo_build` line there is nothing to compare.

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
