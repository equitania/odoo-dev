<!--
  Capability Card — maintained via the `cli-capability-card` skill.
  Audience: an LLM/agent that wants to USE odoodev. Keep it dense and current.
  Regenerate the command table after CLI changes:
    .venv/bin/python <skill>/scripts/introspect_cli.py --import odoodev.cli:cli --root-name odoodev --out /tmp/cc-odoodev
-->
# odoodev — Agent Capability Card

> Unified CLI for native Odoo development across versions **16, 17, 18, 19**. Odoo runs natively on
> the host; PostgreSQL and Mailpit run on a switchable container runtime — **Docker** (default) or
> **Apple Container** (macOS 26 / Apple silicon). Generates `.env`, `docker-compose.yml`, `odoo.conf`.

- **Invoke:** `odoodev [--lang en|de] <command> [VERSION] [flags]`
- **Install:** `uv tool install odoodev` (or editable: `uv pip install -e ".[dev]"`)
- **Version:** 0.59.1  ·  **Framework:** Python / Click
- **Self-serve:** `odoodev capability-card` prints this card from the installed tool (live version injected)
- **Human docs:** `usage/*.md` (bilingual DE/EN handbook chapters)

**Version argument:** Almost every command takes an optional `[VERSION]` (`16`–`19`). If omitted, it
is **auto-detected from the current working directory** (`~/gitbase/vXX/...`). Outside a version dir,
you must pass it explicitly.

## Capabilities at a glance
- Start an Odoo server in several modes: normal, dev hot-reload, shell, test, prepare; optional TUI.
  `Ctrl+C` stops the server (and its forked workers) cleanly.
- Spin local side-services (PostgreSQL + Mailpit) up/down and tail their logs, on Docker or Apple
  Container (`--runtime`, persisted via `container_runtime`).
- Benchmark PostgreSQL on Docker vs Apple Container (`odoodev bench`).
- Full database lifecycle: list, backup (SQL/ZIP/tar.zst+filestore), restore (ZIP/7z/tar/tar.zst/gz/SQL), copy, rename, drop, neutralize, purge, recompute.
- **Untouched-by-default restore:** the DB is left as-is; opt in per flag (`--deactivate-cron`/`--neutralize`/`--anonymize`/`--wipe`/`--purge-master-data`, or `--sanitize` for all of them). Since v0.48.0 `--sanitize` includes `--purge-master-data`, a full template-DB reset that DELETES movement + customer/master data (escape with `--no-purge-master-data`). `--purge-transactions` (movement-only) and `--anonymize-users` remain separate opt-ins (not in `--sanitize`).
- **Space-aware, low-overhead restore:** pre-checks free disk space, moves the filestore instead of
  copying it (no triple data-holding), and can delete the original backup afterwards.
- Clone/update Git repos and (re)generate the dated `odoo_*.conf` addons_path.
- Manage per-version UV virtualenvs and `.env` files.
- Stand up a whole version environment from scratch (`init`) or via an interactive wizard (`setup`).
- Define and run cross-version migration groups.
- **Unattended automation for agents:** run YAML playbooks or inline steps with NDJSON output.
- **Server-mode playbooks (v0.50.0):** mirror a live DB to the test system on customer servers where
  Odoo/PostgreSQL exist only as Docker containers (no dev layout, no published DB ports) — backup,
  restore incl. filestore swap + sanitize, custom SQL, `odoo-bin neutralize`/`-u all` via docker exec,
  declarative Odoo RPC.

## Command reference
Notation: `[ARG]` optional positional · `ARG` required positional · `a|b` choice · `--flag` boolean.

| Command | Purpose | Args / Flags |
|---|---|---|
| `odoodev bench` | Benchmark PostgreSQL on Docker vs Apple Container (isolated container, dedicated port). | [VERSION], --runtime docker\|apple\|both, --duration INT, --scale INT, --port INT, --keep |
| `odoodev capability-card` | Print this capability card to stdout (raw Markdown, live version injected) — primary self-description surface for agents. | — |
| `odoodev config edit` | Open the global config file in $EDITOR (creates defaults if missing). | — |
| `odoodev config paths` | Show editable config file locations per version (.env, docker-compose.yml, requirements.txt, repos.yaml, postgresql.conf, odoo.conf template + latest generated). | [VERSION], --json |
| `odoodev config set` | Set a global configuration value. | KEY, VALUE (keys: base_dir, language, db.user, db.password, odoo_login.username, odoo_login.password, active_versions, **container_runtime** docker\|apple) |
| `odoodev config show` | Show current platform, global config, and environment information. | — |
| `odoodev config versions` | List all available Odoo versions with their configuration. | --plain, --json |
| `odoodev db backup` | Create a database backup (SQL dump, ZIP or tar.zst with filestore). | [VERSION], -n/--name TEXT, -t/--type sql\|zip\|tar.zst, -l/--level INT (1-22, tar.zst only, default 5), -o/--output PATH |
| `odoodev db copy` | Copy a database (incl. filestore) under a new name. | [VERSION], -s/--src TEXT, -d/--dst TEXT, --yes/-y, --terminate-connections |
| `odoodev db drop` | Drop one or more databases (bulk/multi-select). | [VERSION], -n/--name TEXT (repeatable), -m/--multi, --all, --filter TEXT, --terminate-connections, --yes/-y |
| `odoodev db list` | List all databases. | [VERSION], --json |
| `odoodev db cleanup` | Filestore <-> database consistency check: reports orphaned filestores (directory without DB) and DBs without filestore; report-only by default. | [VERSION], --delete-orphans, --json, -y/--yes |
| `odoodev db neutralize` | Neutralize a database via Odoo's native 'odoo-bin neutralize'. | [VERSION], -n/--name TEXT, --stdout |
| `odoodev db purge` | Delete transactional/movement data for a clean stress-test DB (keeps products, pricelists, partners, users, config). | [VERSION], -n/--name TEXT, --dry-run, -y/--yes |
| `odoodev db purge-master-data` | Full template-DB reset: delete movement + CRM/HR/helpdesk/mail data + customer/vendor/contact partners + their attachments; keep products, pricelists, users, companies, config. Superuser role required. | [VERSION], -n/--name TEXT, --dry-run, -y/--yes |
| `odoodev db recompute` | Recompute stored computed fields (e.g. `complete_name`) via `odoo-bin shell`. | [VERSION], -n/--name TEXT |
| `odoodev db rename` | Rename a database (incl. filestore directory). | [VERSION], -s/--src TEXT, -d/--dst TEXT, --yes/-y, --terminate-connections |
| `odoodev db restore` | Restore a database from backup file (post-processing OFF by default; `--sanitize` = full template reset incl. master-data deletion). | [VERSION], -n/--name TEXT, -z/--backup-file PATH, --drop/--no-drop, --sanitize, --deactivate-cron/--no-deactivate-cron, --neutralize/--no-neutralize, --anonymize/--no-anonymize, --wipe/--no-wipe, --purge-master-data/--no-purge-master-data, --anonymize-users/--no-anonymize-users, --user-password TEXT, --uninstall-modules TEXT, -y/--yes, --purge-transactions/--no-purge-transactions, --recompute/--no-recompute, --keep-temp, --check-space/--no-check-space, --delete-backup, --keep-backup, --dry-run (validate file/target/space + list planned steps, change nothing, exit 0/1) |
| `odoodev db uninstall` | Uninstall modules via `odoo-bin shell` (`button_immediate_uninstall`) — e.g. modules that conflict with the sanitize steps. | [VERSION], -n/--name TEXT, -m/--modules TEXT (comma-separated technical names), -y/--yes |
| `odoodev db users` | Interactive TUI: user list with 2FA status; reset passwords (pbkdf2_sha512) and disable TOTP 2FA. | [VERSION], -n/--name TEXT (DB picker inside the TUI if omitted) |
| `odoodev docker down` | Stop the local PostgreSQL service (data volume kept). | [VERSION], --runtime docker\|apple |
| `odoodev docker logs` | View the local PostgreSQL service logs. | [VERSION], -f/--follow, -n/--tail INTEGER, --runtime docker\|apple |
| `odoodev docker status` | Show the local PostgreSQL service status (Apple: names the expected container). | [VERSION], --runtime docker\|apple |
| `odoodev docker up` | Start the local PostgreSQL service. | [VERSION], -d/--detach, --runtime docker\|apple |
| `odoodev doctor` | Check the development environment health. | [VERSION] |
| `odoodev env check` | Check if .env file exists and is complete. | [VERSION] |
| `odoodev env dir` | Print the native environment directory path. | [VERSION] |
| `odoodev env setup` | Create or update .env file for a version. | [VERSION], --non-interactive |
| `odoodev env show` | Display current .env configuration. | [VERSION] |
| `odoodev export modules` | Export the module list as Releasemanager-compatible CSV via XML-RPC (needs a RUNNING Odoo; shares its core with the TUI `x` export). Empty result → `count: 0`, exit 0. | [VERSION], -d/--database TEXT (interactive picker when omitted), --user TEXT, --password TEXT (precedence: flags > `ODOODEV_ODOO_USER`/`ODOODEV_ODOO_PASSWORD` > stored `odoo_login` config > admin/admin), --scope all\|no-enterprise\|installed, --update-list, --cleanup, --output PATH, --host TEXT, --port INT (default: effective ODOO_PORT), --json (single-line result: version, database, scope, path, count, updated, cleaned), -y/--yes |
| `odoodev init` | Initialize a new Odoo development environment. | [VERSION], --non-interactive, --skip-repos, --skip-docker |
| `odoodev migrate activate` | Activate a migration group. | NAME |
| `odoodev migrate create` | Create a new migration group. | --from TEXT, --to TEXT, --name TEXT, --pg-version TEXT |
| `odoodev migrate deactivate` | Deactivate the current migration group. | — |
| `odoodev migrate list` | List all defined migration groups. | — |
| `odoodev migrate remove` | Remove a migration group definition. | NAME, --yes/-y |
| `odoodev migrate status` | Show migration status and active group details. | — |
| `odoodev playbook create` | Playbook assistant: interactive interview (dev or server mode) OR non-interactive generation from an answers JSON file — writes a validated playbook YAML + optional 0600 secrets env_file. | --answers FILE, --non-interactive, -o/--output PATH, --force |
| `odoodev playbook schema` | Print the assistant's field schema (sections, fields, types, conditionals, step arg specs) — the GUI form-rendering contract. | --json |
| `odoodev playbook validate` | Validate a playbook file without executing it (same validation as `odoodev run`). | PLAYBOOK, --json |
| `odoodev pull` | Pull (update) all existing repositories. | [VERSION], -c/--config PATH, -v/--verbose, --no-config, --select, --no-enterprise-prompt |
| `odoodev repos` | Clone/update repositories and generate Odoo configuration. | [VERSION], -c/--config PATH, --init, --server-only, --config-only, --skip-access-check, --select, --no-enterprise-prompt, -v/--verbose |
| `odoodev run` | Execute a playbook or inline steps for automated Odoo development. | [PLAYBOOK], --step/-s TEXT, --version/-V TEXT, --output/-o text\|json, --dry-run, --list, --steps, --var/-D TEXT |
| `odoodev setup` | Interactive setup wizard for odoodev configuration. | --non-interactive, --reset |
| `odoodev shell-setup` | Install odoodev shell wrapper function. | --shell fish\|bash\|zsh\|auto |
| `odoodev start` | Start Odoo server for the given version. Since v0.59.0: instance-info table (ports, database, config, dirs) prints FIRST, then ONE confirmation, then the side-effecting preflight checks — `-y/--yes` skips only the prompt (info still prints). | [VERSION], --dev, --shell, --test, --prepare, --no-confirm, --tui, --load-language TEXT, --i18n-overwrite, --clean-sessions, -d/--database TEXT, -u/--update TEXT, -i/--init TEXT, --host TEXT, --runtime docker\|apple, -c/--config PATH (v0.46.1, explicit config override), --allow-default-credentials, -y/--yes (alias for --no-confirm), [EXTRA_ARGS] |
| `odoodev stop` | Stop Odoo server and Docker services for the given version. | [VERSION], --keep-docker, --force |
| `odoodev venv activate` | Print the venv activation command for current shell. | [VERSION] |
| `odoodev venv check` | Check venv status and requirements freshness. | [VERSION], --json |
| `odoodev venv path` | Print the venv directory path. | [VERSION] |
| `odoodev venv remove` | Remove the virtual environment for a version. | [VERSION], --yes/-y |
| `odoodev venv setup` | Create virtual environment with UV and install requirements. | [VERSION], --force, --python-version TEXT (full Python version override) |

Anything after a bare `--` on `odoodev start` is passed straight to `odoo-bin`.

## Recipes

### Start a dev server (hot-reload)
```bash
odoodev docker up 19        # PostgreSQL + Mailpit
odoodev start 19 --dev      # native odoo-bin with auto-reload
```
Omit the version when run from inside `~/gitbase/v19/...`.

### Install / update a module on a database
```bash
odoodev start 19 -u my_module -d v19_exam      # update
odoodev start 19 -i my_module -d v19_exam      # install
odoodev start 19 -- -d v19_exam -u my_module   # equivalent, passthrough form
```

### Run a module's tests
```bash
odoodev start 19 --test -- -d test_db -i my_module
```

### Start with a specific config file (v0.46.1)
```bash
odoodev start 18 -c ~/gitbase/v18/myconfs/odoo_custom.conf
# Without -c: glob odoo_*.conf in myconfs/, latest by date wins.
# Playbook equivalent: args: { config: ~/gitbase/v18/myconfs/odoo_custom.conf }
```

### Back up, then restore with PII anonymized (safe default)
```bash
odoodev db backup 18 -n v18_exam -t zip               # ZIP incl. filestore
odoodev db backup 18 -n v18_exam -t tar.zst           # tar.zst (zstd, large DBs); -l 19 for max compression
odoodev db restore 18 -n v18_restored -z backup.zip   # plain restore — DB left untouched
odoodev db restore 18 -n v18_restored -z backup.zip --dry-run -y   # preflight only: nothing restored (since v0.61.0)
odoodev db restore 18 -n v18_restored -z backup.zip --sanitize   # FULL template reset: anonymize + DELETE movement + customer/master data
odoodev db restore 18 -n v18_restored -z backup.zip --sanitize --no-purge-master-data   # anonymize-only (pre-v0.48.0 --sanitize behavior)
odoodev db restore 18 -n v18_restored -z backup.zip --sanitize --uninstall-modules mod1,mod2 -y   # drop conflicting modules first, no prompts
odoodev db purge-master-data 18 -n v18_restored --dry-run        # preview the full reset on an existing DB
odoodev db uninstall 18 -n v18_restored -m mod1,mod2 -y          # uninstall modules on an existing DB
odoodev db users 18 -n v18_restored                              # TUI: reset passwords / disable 2FA
odoodev db drop 18 -m                                            # checkbox multi-select of databases to drop
odoodev db drop 18 --all --filter test_                          # bulk-drop all test_* databases (y/N confirmation)
```
Restore post-processing is **OFF by default** (v0.43.0) — the restored database is left
completely untouched unless flags are passed: `--deactivate-cron`, `--neutralize`,
`--anonymize` (Faker only), `--wipe` (since v0.62.0 a REAL delete: the chatter tables —
mail_message, mail_tracking_value, mail_notification, mail_followers, mail_activity, rel
tables — plus the ir_attachment rows AND their filestore files; keeps `res_field IS NOT NULL`
image/binary storage and `ir.ui.view`/`ir.ui.menu` asset bundles),
`--purge-master-data`, or `--sanitize` for all of them at once (explicit
`--no-*` flags win). **Since v0.48.0 `--sanitize` includes `--purge-master-data`** — a full
"template DB from production" reset that DELETES movement data, CRM/HR/helpdesk/mail content,
the customer/vendor/contact partners and their attachments (keeps products, pricelists,
users+their partner, companies+their partner, config). It runs one superuser
`session_replication_role=replica` transaction, asks a `y/N` confirmation (with the deletable
partner count shown; skipped with `-y`). Transient Odoo wizard tables (`ir_model.transient`,
e.g. `account_payment_register`) that reference a to-be-deleted partner are cleared
automatically; it only aborts cleanly (rollback) if a protected table or a **non-transient**
unhandled RESTRICT/NO-ACTION FK would be hit. Escape with `--no-purge-master-data`. Standalone: `db purge-master-data`.
`--anonymize-users` is a separate opt-in (works standalone, NOT included in `--sanitize`);
its default dev login password is `ownerp` (override with `--user-password`).
`--purge-transactions` (v0.44.0) is a separate movement-only opt-in, NOT included in `--sanitize`:
it deletes stock/sales/purchase/accounting/MRP/POS movement data for a clean stress-test DB
while keeping products, pricelists, partners, users and config. Since v0.44.0, `--anonymize`
also auto-recomputes stored computed fields (e.g. `complete_name`) via `odoo-bin shell` so
kanban/list overviews show the anonymized values (disable with `--no-recompute`).

```bash
odoodev db restore 18 -n v18_test -z prod.zip --purge-transactions --anonymize   # anonymized, movement-free stress-test DB
```

### Update repos + regenerate the Odoo config
```bash
odoodev pull 18                  # git pull all repos
odoodev repos 18 --config-only   # regenerate dated odoo_YYMMDD.conf only
```

### Unattended automation (playbooks, for agents)
```bash
odoodev run -s docker.up -s pull -V 18 -o json       # inline steps, no file — easiest for agents
odoodev run ./path/to/playbook.yaml --output json    # explicit file path → NDJSON, one object/step
odoodev run ./path/to/playbook.yaml --dry-run        # show the plan without executing
odoodev run --list                                   # list discoverable playbooks (see note)
```
**Playbook resolution:** a bare name is looked up ONLY in `./playbooks/` or
`<native_dir>/scripts/playbooks/`. Bundled examples live at
`odoodev/data/examples/playbooks/` (`daily-update`, `full-refresh`, `restore-db`, `start-dev`,
`server-mirror`) and
are **not** name-resolvable — run them via an explicit path or copy them into a discovered dir.
A playbook step's `command` uses dotted names mirroring the CLI groups (`docker.up`, `db.backup`,
`repos`); step `args` use the long option names (e.g. `config-only: true`). Pass variables with
`--var KEY=VALUE`.

### Server-mode playbooks (live→test mirror on customer servers, v0.50.0)
Top-level sections: `targets:` (named container pairs: `db_container`, `odoo_container`, `db_name`,
optional `owner`/`data_dir` — empty `data_dir` is resolved via `docker inspect` mounts), `env_file:`
(secrets loaded into `{{ env.X }}`, file wins over process env, skipped in `--dry-run`), `rpc:`
(connection for `rpc.execute`; missing fields fall back to `ODOO_URL`/`ODOO_PORT`/`ODOO_USER`/
`ODOO_PASSWORD`/`ODOO_DATABASE` from the env_file). Steps reference targets via `target: <name>`.

Steps: `container.stop`/`container.start` (idempotent; `component: odoo|db`), `server.backup`
(`backup_dir`, container2backup-compatible `.tar.zst`), `server.rebuild` (full container rebuild via
the deployed `update_docker_odoo.py`: release fetch + `docker build` + recreate; args `script_path`
default `~/update_docker_odoo.py`, `config` default `~/docker2update.yaml`, `timeout` default 7200s;
exit code is the contract), `server.restore` (`backup_source:` `{mode: from_backup_step}` — the exact
file a previous `server.backup` step of the same run created (v0.57.0) —
or `{mode: file, path: …}` or `{mode: newest_in_dir, dir, pattern, select_by: mtime|filename_timestamp}`;
`template: template0`; sanitize flags `deactivate_cron`/`neutralize`/`anonymize`/`wipe`/
`purge_transactions`/`purge_master_data` or `sanitize: true`), `sql.execute` (`statements:` list or
`file:`, Jinja-templated; works against a `target` or the dev DB), `server.neutralize`,
`server.update-all` (`restart: true` default), `rpc.execute` (`model`, `method`, `args`/`kwargs`, or
`domain` + `values` → search-then-write; needs extra `odoodev-equitania[rpc]`).

**Ordering guardrails:** `server.restore` refuses to run while the target Odoo container is up
(stop it first); `server.neutralize`/`server.update-all` exec into the RUNNING container — place
them after `container.start`. Run customer SQL (enterprise code, website domain) before the start.
`server.rebuild` starts the container itself at the end — place it BEFORE `container.stop` +
`server.restore`; it runs a host-wide `docker system prune -f` and has no lock, so never run two
rebuilds on the same host in parallel.
Bundled example: `server-mirror.yaml`. Requires root on the server (chown, data-dir access).

### Generate a playbook (assistant / GUI)
```bash
odoodev playbook create                                   # interactive interview (dev or server)
odoodev playbook create --answers a.json --non-interactive # GUI/agent mode, no prompts
odoodev playbook schema --json                            # field schema for form rendering
odoodev playbook validate playbooks/mirror.yaml --json    # non-executing validation
```
The wizard opens with a DE/EN language question when no language is explicitly configured
(`--lang`/`ODOODEV_LANG`/config; default from shell locale, optionally persisted) and walks
through numbered steps (server: 6, dev: 4). The server branch is **source-first** (v0.55.0):
it asks the mirror SOURCE first (fresh backup from a container pair — the restore then
automatically consumes the file that backup creates via `backup_source.mode: from_backup_step`,
no pattern questions (v0.57.0) — / existing backup file / newest by pattern; prompt "Source
name"), then the DESTINATION target (prompt "Destination name"; self-mirror guard: restoring
back onto the source pair needs explicit confirmation), then the infrastructure options
(rebuild → stop → SQL presets incl. enterprise code + website-domain swap → start →
update-all → rpc) — `server.restore` is always included, and what happens to the restored
database is ONE question (sanitize flags; picking `neutralize` also adds the
`server.neutralize` step). Server-side paths stay literal (`~/...` is expanded on the server, never on
the machine running the wizard). Secrets never land in the YAML: the assistant writes them into a
0600 env_file referenced via `{{ env.X }}` (nothing entered → no file written). Answers-file
format and schema JSON (`schema_version: 3`; `1`/`2` still accepted): see `usage/playbook.md`.
Answers files may contain inline secrets — treat them like the env_file (0600, never commit,
delete after use). In non-interactive mode an existing output/env file is refused without
`--force`.

### Use Apple Container instead of Docker (macOS)
```bash
odoodev config set container_runtime apple   # persist as default → no flag needed afterwards
odoodev start 18                             # uses Apple Container; prints the container name
container ls                                 # see it (NOT `container machine list`)
odoodev docker status 18 --runtime apple     # names expected container + lists all
```
Per-call override: `odoodev start 18 --runtime apple` (offers to save when it differs from the
default). Requires macOS 26 / Apple silicon. Full guide: `usage/apple-container.md`.

### Stand up a fresh version environment
```bash
odoodev init 18        # dirs + .env + docker-compose.yml + .venv + repos + docker
```

## Guardrails & gotchas
- **Destructive (prompt for confirmation; bypass with `--yes/-y`):** `db drop`, `db copy`, `db rename`
  (overwrite the destination), `db purge` (use `--dry-run` to preview target tables first),
  `venv remove`. `db copy/rename` can force-close sessions with `--terminate-connections`.
- **`odoodev stop --force`** kills the Odoo process; `--keep-docker` leaves PostgreSQL/Mailpit running.
- **`odoodev start` prerequisites** (checked before launch): `.env`, `.venv/`, `odoo-bin`, a dated
  `odoo_*.conf`, PostgreSQL ready at the protocol level (`pg_isready` or a socket probe — not just an
  open TCP port; offers to start the configured runtime — Docker or Apple Container — and to save the
  choice as the new default, then polls readiness up to 60s), and an unchanged
  `requirements.txt` SHA256 (offers an update if it changed). `odoodev docker up` waits for the same
  readiness before reporting success.
- **`start --clean-sessions`** wipes existing sessions; **`--allow-default-credentials`** disables a
  safety check — use only on disposable databases.
- **`db restore` data handling:** a disk-space pre-check (`--no-check-space` to skip) warns + asks
  before extracting if space is tight. The filestore is **moved** into `~/odoo-share/` (instant rename
  on the same filesystem) — `--keep-temp` copies instead so the extracted temp survives. The original
  backup is never auto-deleted; you are asked at the end (`--delete-backup` / `--keep-backup` for scripts).
- **`repos` URL validation (v0.61.1):** every `git_url` from `repos.yaml` is checked before it reaches
  `git`. Accepted: `ssh://`, `https://`, `http://`, `git://` and the SCP shorthand `user@host:path`.
  Rejected: anything starting with `-` (option injection) or containing `::` (git's `ext::`/`fd::`
  remote-helper transports, which execute a shell command). A rejected entry fails that repo with an
  error instead of being cloned — if a clone suddenly fails, check the URL's shape first.
- **Version resolution:** auto-detected from CWD; outside a `vXX` directory the `[VERSION]` argument
  is mandatory or the command errors.
- **psql/pg_dump not required on the host:** all `db` commands fall back to `docker exec` into the
  container publishing the target DB port when host client tools are missing (one-time `[INFO]` line;
  also avoids client/server version mismatches). Force a mode with `ODOODEV_PG_EXEC=host|container`.
  If neither tools nor a container are available the command exits with a clean two-option error.
  Docker-only — on Apple Container install libpq.
- **Non-interactive use:** `init`, `env setup`, `setup` accept `--non-interactive`; destructive db/venv
  commands accept `-y`. Prefer these in automation to avoid blocking on prompts.

## Machine-readable outputs
- `odoodev capability-card` → this card as raw Markdown (self-description; version always live).
- `odoodev run --steps` → list of valid playbook step commands.
- `odoodev db list --json` → array of databases.
- `odoodev config versions --json` → full version registry (ports, paths, git). Since 0.58.0 each
  version also carries `effective_ports` (registry defaults overridden by the version's `.env`
  `DB_PORT`/`ODOO_PORT`/`GEVENT_PORT`/`MAILPIT_PORT`) — on multi-user hosts every user has an own
  port prefix, so consumers must match containers and build URLs against `effective_ports`, not
  `ports`.
- `odoodev config paths --json` → per-version config-file inventory (native/conf/myconfs dirs; path
  + exists flag for .env, compose, requirements, repos.yaml, postgresql.conf, template/generated
  odoo.conf). Primary path-discovery surface for GUIs/agents — do not re-derive paths.
- `odoodev venv check --json` → venv/requirements freshness status.
- `odoodev playbook schema --json` → assistant field schema (GUI form-rendering contract).
- `odoodev playbook create --answers f.json --non-interactive` → generate a playbook without
  prompts (submission endpoint; `--force` to overwrite existing files).
- `odoodev playbook validate FILE --json` → `{"valid": true|false, ...}` (exit code mirrors
  validity; parse stdout regardless).
- `odoodev db neutralize --stdout` → emits the neutralize SQL instead of applying it.
- `odoodev run … --output json` → **NDJSON** stream, one JSON object per executed step (status,
  output, error). Primary integration surface for agents.

## Deeper docs
For background and edge cases see `usage/`: `start.md`, `db.md`, `data-protection.md`, `repos.md`,
`migrate.md`, `run.md`, `playbook.md`, `docker.md`, `apple-container.md`, `venv.md`, `config.md`,
`setup.md`, `doctor.md`, `shell.md`, and the full `odoo-development-workflow.md`.
