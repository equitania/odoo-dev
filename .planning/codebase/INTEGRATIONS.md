# External Integrations

**Analysis Date:** 2026-05-13

## Docker / Docker Compose

**Services managed:**
- **PostgreSQL** — primary service; Docker image `postgres:{version}-alpine` per Odoo version (e.g., `16.11-alpine` for v16-v18, `17.4-alpine` for v19)
- **Mailpit** — SMTP test server; defined but commented out in template by default (`odoodev/templates/docker-compose.yml.j2:41-52`)

**How managed:**
- Template rendered from `odoodev/templates/docker-compose.yml.j2` via Jinja2 → `docker-compose.yml` in `vXX-dev/devXX_native/`
- CLI wrapper in `odoodev/core/docker_compose.py`
- Commands: `odoodev docker up|down|status|logs`
- `odoodev start` auto-starts Docker compose if PostgreSQL port unreachable (`odoodev/commands/start.py:545`)
- `odoodev stop` calls `docker compose down`

**Port convention:** Each Odoo version gets dedicated ports (DB: `{version}432`, Odoo: `{version}069`, Mailpit: `{version}025`) to allow parallel instances.

**Volume naming:** `vol-dev-db-{version}-native` — version-isolated persistent volumes.

## Git / Repository Management

**Implementation:** `odoodev/core/git_ops.py`

**Operations:**
- Clone repos from `repos.yaml` (user-provided at `vXX-dev/scripts/repos.yaml`)
- Update existing clones via `git pull`
- Subdirectory extraction for OCA repos (clones to temp, moves target subdir)

**SSH authentication:**
- Module-global `_ssh_key_path` (`git_ops.py:12`)
- Sets `GIT_SSH_COMMAND` env var with `ssh -i {key} -o IdentitiesOnly=yes` or SSH config file
- SSH config written to `~/.ssh/odoodev_ssh_{hash}.conf` for per-key isolation
- All repo URLs use `git@gitlab.ownerp.io` (internal GitLab, never GitHub)

**`versions.yaml` defaults:**
- `server_url`: `git@gitlab.ownerp.io:vXX/vXX-server.git`
- `branch`: `develop`

## PostgreSQL Integration

**Implementation:** `odoodev/core/database.py`

**All operations via CLI tools** (no ORM or psycopg2):
- `psql` — query execution, DB listing, SQL file restore (`database.py:95`)
- `createdb` — new database creation (`database.py:189`)
- `dropdb` — database removal (`database.py:171`)

**Authentication:**
- Checks for `~/.pgpass` first; falls back to `PGPASSWORD` env var (`database.py:76`)
- Default credentials: user `ownerp`, password `CHANGE_AT_FIRST` (dev placeholder)
- Connection params from `.env` file: `DB_HOST`, `DB_PORT`, `DB_USER`, `PGPASSWORD`

**Backup restore supports:**
- `.zip` (Odoo manager format) — extracts filestore + SQL dump
- `.7z` — 7zip archives (requires `7z` on PATH)
- `.tar.gz` / `.gz` — compressed archives
- `.sql` — raw SQL files
- Post-restore: deactivates cron jobs and cloud integrations via `_run_psql` queries (`database.py:489,508`)

## Odoo Runtime (odoo-bin)

**Implementation:** `odoodev/commands/start.py`

**Invocation strategy:**
- Normal/dev/test modes: `os.execvpe(cmd[0], cmd, env)` — replaces process (`start.py:331`)
- Shell mode: `subprocess.run(cmd, env=env)` — child process (`start.py:287`)
- Command: `python odoo-bin -c {conf} [args]` with venv Python

**Start prerequisites checked** (`start.py:468`):
1. `.env` file present in `native_dir`
2. `.venv/` directory present
3. `odoo-bin` binary present in `server_dir`
4. `odoo_*.conf` present in `myconfs_dir` (latest by date suffix `YYMMDD`)
5. PostgreSQL port reachable (TCP check)
6. `requirements.txt` SHA256 unchanged

**Modes:** `normal`, `--dev` (hot-reload), `--shell`, `--test`, `--prepare`

**Config generation:** `odoodev/core/odoo_config.py` writes `odoo_YYMMDD.conf` with `addons_path` grouped by section (Odoo core, OCA, Enterprise, Syscoon, 3rd-party, Equitania, Customer, Other).

## Shell Integration

**Implementation:** `odoodev/core/shell_integration.py`, `odoodev/templates/shell/`

**Supported shells:**
- Fish — `odoodev-activate.fish` (primary, detection via `detect_shell()`)
- Bash — `odoodev-activate.bash`
- Zsh — `odoodev-activate.zsh`

**What's installed:**
- `odoodev-activate` shell function written to shell config file (`~/.config/fish/config.fish`, `~/.bashrc`, `~/.zshrc`)
- Function: activates per-version venv, changes to server dir, sets env vars
- Click shell completion registered per shell

**Command:** `odoodev shell-setup` triggers installation.

## Jinja2 Template Rendering

**Templates location:** `odoodev/templates/`

| Template | Output | Renderer |
|----------|--------|---------|
| `env.template.j2` | `devXX_native/.env` | `odoodev/commands/env.py` |
| `docker-compose.yml.j2` | `devXX_native/docker-compose.yml` | `odoodev/core/docker_compose.py` |
| `shell/odoodev-activate.{fish,bash,zsh}` | Shell config | `odoodev/core/shell_integration.py` |

**Template context:** `VersionConfig` dataclass fields + `EnvironmentInfo` (OS, arch, user, Docker platform).

**odoo.conf:** Generated directly (not Jinja2) by `odoodev/core/odoo_config.py` with addons_path logic.

## File System Layout Convention

**Path root:** `~/gitbase/vXX/` (configurable via `~/.config/odoodev/config.yaml`)

```
~/gitbase/vXX/
├── vXX-server/              # Odoo server code (odoo-bin lives here)
├── vXX-dev/
│   ├── devXX_native/        # .env, docker-compose.yml, .venv/
│   │   └── requirements.txt # User-provided Python deps for Odoo
│   ├── conf/                # odooXX_template.conf (user-provided)
│   └── scripts/
│       └── repos.yaml       # User-provided repo definitions
└── myconfs/                 # Generated odoo_YYMMDD.conf files
```

**Auto-detection:** CLI reads CWD path to extract version number (regex `~/gitbase/v(\d+)/`), so `[VERSION]` arg is optional when inside a version directory.

## User Configuration

**Global config:** `~/.config/odoodev/config.yaml` — stores global defaults (base dir, credentials, language)
**Version overrides:** `~/.config/odoodev/versions-override.yaml` — override any `versions.yaml` field per version
**Implementation:** `odoodev/core/global_config.py`, `odoodev/core/version_registry.py:132`

## i18n / Localization

**Scope:** DE/EN only; user-facing CLI messages (preflight errors, setup prompts, init steps)
**Resolution order:** `--lang` flag → `ODOODEV_LANG` env → `~/.config/odoodev/config.yaml` `cli.language` → system locale → `en`
**Implementation:** `odoodev/i18n.py` — flat `MESSAGES` dict, `t("key", **kwargs)` function, no external dependency

---

*Integration audit: 2026-05-13*
