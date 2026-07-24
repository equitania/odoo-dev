# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Setup

```bash
uv venv && source .venv/bin/activate.fish   # or venv+ alias
uv pip install -e ".[dev]"
```

## Common Commands

```bash
# Run CLI
odoodev --help

# Tests
pytest                              # all tests
pytest tests/test_version_registry.py  # single module
pytest tests/test_cli_config.py::test_config_versions  # single test

# Linting & formatting
ruff check . && ruff format --check .   # check only
ruff check --fix . && ruff format .     # auto-fix

# Type checking
mypy odoodev

# Build
uv build
```

## Architecture

**odoodev** is a Click-based CLI tool for managing native Odoo development environments (v16-v19). Odoo runs natively on the host, PostgreSQL and Mailpit run in Docker.

### Core data flow

`versions.yaml` → `VersionRegistry` (frozen dataclasses) → Commands → Jinja2 templates → generated files (.env, docker-compose.yml, odoo.conf)

### Key modules

- **`cli.py`** — Click entry point. Auto-detects Odoo version from CWD path (`~/gitbase/vXX/...`). All commands accept an optional `[VERSION]` argument.
- **`core/version_registry.py`** — Loads `data/versions.yaml` into frozen `VersionConfig` dataclasses with nested `PortConfig`, `PathConfig`, `GitConfig`. Supports user overrides via `~/.config/odoodev/versions-override.yaml`.
- **`core/environment.py`** — Detects OS, architecture, shell (fish/zsh/bash), Docker platform, user.
- **`core/git_ops.py`** — Git clone/update with SSH key support. Module-global `_ssh_key_path`. Handles OCA repos (subdirectory extraction for addons_path). Since v0.59.0 `clone_repo` and `switch_branch_and_update` return `(result, error)` tuples — callers must surface errors; `get_module_paths` returns `[]` for missing dirs (no phantom addons_path entries).
- **`core/xmlrpc_client.py`** — Odoo XML-RPC client (moved from `tui/` in v0.59.0, shared by TUI + `export modules`). Credentials via `from_stored_credentials()` factory (reads the `odoo_login` global-config section, default admin/admin); hot module upgrade, `list_modules`, `update_module_list`, `cleanup_uninstalled_modules`.
- **`core/module_export.py`** — Pure Releasemanager-CSV helpers (moved from `tui/` in v0.59.0): `EXPORT_SCOPES`, `is_exportable_module`, `write_modules_csv`, `build_export_path`.
- **`core/database.py`** — PostgreSQL ops via `psql`/`createdb`/`dropdb` CLI. All pg client calls transparently fall back to `docker exec` into the container publishing the target DB port when host CLI tools are absent (`resolve_pg_exec_mode`, per-port cached, `ODOODEV_PG_EXEC=host|container` override; no password needed — Unix-socket trust auth; port-based lookup makes migration-mode's shared-port redirection just work). Dumps are piped via stdin (never `psql -f`). Backup creation (`backup_database_sql`, `create_backup_zip`, `create_backup_tar_zst` — the last pipes a Python `tarfile` stream into the `zstd` CLI, symmetric to the `.tar.zst` restore). Backup extraction (ZIP, 7z, tar, tar.zst, gz, SQL). Post-restore (ALL OFF by default since v0.43.0 — opt-in per flag or `--sanitize` for all four; explicit `--no-*` wins): (1) `deactivate_cronjobs()` psql baseline (crons/mail/fetchmail, `--deactivate-cron`), (2) native `run_neutralize()` → `odoo-bin neutralize` (`--neutralize`; runs each module's `data/neutralize.sql`: payment/IAP/webhooks/banner/cloud modules; graceful-skip if venv/odoo-bin/conf missing), (3) `anonymize_database()` (`--anonymize`) — Faker-generated, per-id-seeded values as bundled `UPDATE ... FROM (VALUES ...)` over `res_partner`/`crm_lead`/`res_partner_bank`/HR; emails/logins forced to RFC 2606 reserved targets, (4) `wipe_database()` (`--wipe`) — content deletion split out of anonymize: mail_message/ir_attachment wipes + linkage-table DELETEs, (5) `anonymize_users()` (`--anonymize-users`, standalone, not in `--sanitize`). Also (v0.44.0, standalone commands AND separate opt-in `db restore` flags, neither in `--sanitize`): `purge_transactional_data()` (`--purge-transactions`, `odoodev db purge`) — deletes all stock/sales/purchase/accounting/MRP/POS movement data while keeping products/pricelists/partners/users/config; computes the ON-DELETE-CASCADE closure of the movement root tables via `pg_constraint` introspection and DELETEs it under `session_replication_role = replica` (not a naive `TRUNCATE CASCADE`, which would also sweep `res_company` via its `account_opening_move_id` FK), then nulls `ON DELETE SET NULL` back-references; a safety pre-check aborts with no deletion if the closure would reach a protected master table; requires a superuser DB role. `run_recompute()` (`--recompute`/`--no-recompute`, auto after `--anonymize`, `odoodev db recompute`) — recomputes stored computed fields (e.g. `res_partner.complete_name`) via `odoo-bin shell` since raw-SQL anonymization bypasses the ORM and leaves them stale; graceful-skip if the dev env (venv/odoo-bin/conf) isn't ready. Standalone `odoodev db neutralize`. Since v0.45.0: `run_uninstall_modules()` (`--uninstall-modules mod1,mod2` on `db restore`, standalone `odoodev db uninstall -n DB -m mods`, playbook arg `uninstall-modules`) — uninstalls modules that conflict with the sanitize steps via `odoo-bin shell` (`button_immediate_uninstall`) BEFORE any sanitize step runs; interactive prompt when the flag is omitted, a sanitize step is enabled and no `-y/--yes` (new restore flag); not-found/not-installed names are warnings (`odoodev-uninstall:` stdout markers); on failure interactive mode offers to abort the pipeline (default abort). User management for the `db users` TUI: `list_users()` (`UserInfo` dataclass, `totp_secret IS NOT NULL` as 2FA status, schema-guarded), `set_user_password()` (pbkdf2_sha512 via `_pbkdf2_sha512_hash`), `disable_user_2fa()` (`totp_secret` NULL + `auth_totp_device` DELETE, table-guarded). Default credentials: `ownerp`/`CHANGE_AT_FIRST`.
- **`core/odoo_config.py`** — Generates `odoo_YYMMDD.conf` with addons_path grouped by section (Odoo, OCA, Enterprise, Syscoon, 3rd-party, Equitania, Customer, Other).
- **`core/venv_manager.py`** — UV-based venv creation. SHA256 hashing of requirements for freshness detection.
- **`core/docker_compose.py`** — Renders and manages docker-compose.yml via Jinja2 template.
- **`core/shell_integration.py`** — Installs `odoodev-activate` shell function for Fish, Bash, Zsh.
- **`core/playbook_schema.py`** — Single source of truth for the playbook assistant (v0.54.0): `SCHEMA_VERSION`, frozen `WizardField`/`WizardSection` dataclasses, `SECTIONS`, `SQL_PRESETS` (enterprise code, eq_cloud cleanup, website-domain swap), `DEV_STEP_GROUPS`/`DEV_STEP_ORDER`, `STEP_ARG_SPECS` (descriptive per-step arg specs incl. `server.rebuild`), `wizard_schema()` (JSON-serializable; resolves `choices_source` like `available_versions` inline). Pure data — no questionary/click imports.
- **`core/playbook_builder.py`** — Pure generator core (v0.54.0): answers dict → `build_playbook_dict()` → `render_playbook_yaml()`; `validate_generated()` round-trips through `playbook._validate_playbook` before any write; `answers_from_file()`/`validate_answers()` collect ALL structural problems into one `AnswersValidationError`; `write_env_file()` (0600 via `os.open`, merge-aware via `dotenv_values`), `find_env_references()`/`find_var_references()` (Jinja ref scanning), `slugify()`/`default_output_path()` (`./playbooks/<slug>.yaml`, matches `run.py` discovery). One shared input contract for the interactive wizard AND the GUI's `--answers` mode.
- **`output.py`** — Rich console helpers (success/error/warning/info/header) + questionary wrappers (`confirm`, `select`, `text_input`, `path_input`, `password_input`, `checkbox_with_separators`).

### Commands (`commands/`)

| Command | Purpose |
|---------|---------|
| `init` | Full environment setup (dirs, .env, compose, venv, repos, docker) |
| `start` | Start Odoo server (modes: normal, --dev, --shell, --test, --prepare). Since v0.59.0: instance-info table first → ONE confirmation → side-effecting preflight (`_run_preflight`); `--yes/-y` visible, skips only the prompt |
| `repos` | Clone/update repos from repos.yaml, generate odoo.conf. Since v0.59.0: SSH access check is diagnostic-only (never blocks a clone), per-repo failures surfaced, `RepoOpSummary` table, exit 1 on failures |
| `export` | `export modules` — Releasemanager CSV via XML-RPC from a running Odoo (shared core with TUI `x` export; `--json` contract for the GUI; credentials: flags > `ODOODEV_ODOO_USER/PASSWORD` env > `odoo_login` config) |
| `db` | list, restore, drop, uninstall, users, purge, recompute, cleanup databases. Since v0.60.0: when PostgreSQL is unreachable, the error path runs `diagnose_runtime()` (`core/container_backend.py`) — runtime-aware hints (`container system start` for a stopped Apple Container API server, `open -a Docker` for a stopped Docker daemon, install/switch hints for a missing CLI) instead of a blanket Docker reference. Also since v0.60.0: `db cleanup [VERSION]` — filestore ↔ DB consistency check (orphaned filestores with sizes / DBs without filestore); report-only by default, `--delete-orphans` (y/N confirm, `-y`), `--json` contract (never deletes); migration-aware via `get_filestore_path` |
| `playbook` | Playbook assistant (v0.54.0, source-first v0.55.0, guided UX v0.56.0, v0.57.0: fresh-backup source hands its file to the restore via backup_source.mode from_backup_step (runner injects _runtime like _rpc_config; no pattern questions) and the restored-DB treatment is ONE sanitize question whose neutralize choice derives the server.neutralize step: opens with a DE/EN language question when none is explicitly set (--lang/ODOODEV_LANG/config; shell-locale default, optional persist via save_global_config), numbered step headers (server 6 / dev 4), role-specific "Source name"/"Destination name" prompts, plain-language labeled choices for on_error/select_by/sanitize flags — values unchanged): `create` (interactive wizard: server branch asks SOURCE first (fresh backup from container pair with auto-derived restore pattern | existing file | newest by pattern), then DESTINATION (self-mirror guard), then optional steps incl. `server.rebuild` — restore always included; server-side paths never locally expanded; dev branch = grouped step checkbox; or `--answers file.json --non-interactive` for GUI/agents, `--force` overwrite guard), `schema --json` (GUI form contract, schema_version 3; v1/v2 answers still accepted), `validate [--json]`. Secrets go into a 0600 env_file, never into the YAML (empty -> no file) |
| `run` | YAML playbook execution (`--list`, `--steps`, `--var`, `--dry-run`, `--output json` NDJSON; server-mode steps incl. `server.rebuild` — shell-out to `update_docker_odoo.py`, v0.54.0) |
| `env` | setup, check, show, dir for .env management |
| `venv` | setup, check, activate, path for UV venv |
| `docker` | up, down, status, logs for the configured container runtime (Docker or Apple Container). Since v0.60.0 `service_up` is self-healing: verifies the runtime CLI + daemon first, auto-starts a stopped `container-apiserver` (Apple), clear error + start command for a stopped Docker daemon; `status` reports a non-ready runtime with its remedy (no auto-start) |
| `config` | versions (table of all versions), show (platform info) |
| `shell-setup` | Install shell wrapper function |

### Required files (user-provided)

| File | Path | Purpose |
|------|------|---------|
| `repos.yaml` | `vXX-dev/scripts/repos.yaml` | Repository definitions for git clone |
| `requirements.txt` | `vXX-dev/devXX_native/requirements.txt` | Python dependencies for Odoo |
| `odooXX_template.conf` | `vXX-dev/conf/odooXX_template.conf` | Template for Odoo config generation |

### Data flow

```
odoodev init → dirs + .env + docker-compose.yml + .venv + repos
                                                          ↓
                                                repos.yaml → git clone
                                                          ↓
                                             odoo_YYMMDD.conf generated
                                                          ↓
odoodev start → load .env → check prereqs → start odoo-bin
               (DB_PORT,    (.venv, odoo-bin,  (with odoo_YYMMDD.conf)
                PGUSER...)   odoo_*.conf, DB)
```

### Start prerequisites

What `odoodev start` checks before launching Odoo:
1. `.env` file exists in native_dir
2. `.venv/` directory exists
3. `odoo-bin` exists in server_dir
4. `odoo_*.conf` exists in myconfs_dir (uses latest by date suffix)
5. PostgreSQL port is reachable (offers to start Docker if not)
6. `requirements.txt` SHA256 hash unchanged (offers update if changed; the hash is stored after a successful update since v0.59.0)

Since v0.59.0 the instance-info table (ports, database, config preview, dirs) is shown BEFORE the single confirmation prompt; checks 2-6 (`_run_preflight`) only run after the user confirms (or immediately with `--yes`/`--no-confirm`). Declining start + shell fallback leaves the system untouched.

### Path convention

```
~/gitbase/vXX/
├── vXX-server/              # Odoo server code
├── vXX-dev/
│   ├── devXX_native/       # Native dev env (venv, .env, docker-compose.yml)
│   │   └── requirements.txt # User-provided Python dependencies
│   ├── conf/               # Config templates (user-provided)
│   └── scripts/            # repos.yaml (user-provided)
└── myconfs/                # Generated odoo_YYMMDD.conf files
```

### Templates (`templates/`)

Jinja2 templates for: `.env`, `docker-compose.yml`, `odoo.conf`, and shell activation scripts. Template context comes from `VersionConfig` and environment detection.

## Code Conventions

- Python 3.10+, line length 120
- Ruff rules: E, W, F, I, B, UP
- Double quotes (`"`)
- isort with `known-first-party = ["odoodev"]`
- Frozen dataclasses for configuration objects
- Absolute imports only (no relative imports)
- Lazy imports in `init_cmd.py` to avoid circular dependencies
- Rich library for all terminal output (never plain print)

## Testing

Tests use pytest with Click's `CliRunner`. Fixtures in `conftest.py` provide `tmp_dir` and a parsed `versions_yaml` dict. Tests cover version registry, environment detection, CLI commands, and template rendering via monkeypatching.
