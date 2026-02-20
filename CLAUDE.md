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
- **`core/git_ops.py`** — Git clone/update with SSH key support. Module-global `_ssh_key_path`. Handles OCA repos (subdirectory extraction for addons_path).
- **`core/database.py`** — PostgreSQL ops via `psql`/`createdb`/`dropdb` CLI. Backup extraction (ZIP, 7z, tar, gz, SQL). Post-restore: deactivates cron jobs and cloud integrations. Default credentials: `ownerp`/`CHANGE_AT_FIRST`.
- **`core/odoo_config.py`** — Generates `odoo_YYMMDD.conf` with addons_path grouped by section (Odoo, OCA, Enterprise, Syscoon, 3rd-party, Equitania, Customer, Other).
- **`core/venv_manager.py`** — UV-based venv creation. SHA256 hashing of requirements for freshness detection.
- **`core/docker_compose.py`** — Renders and manages docker-compose.yml via Jinja2 template.
- **`core/shell_integration.py`** — Installs `odoodev-activate` shell function for Fish, Bash, Zsh.
- **`output.py`** — Rich console helpers (success/error/warning/info/header).

### Commands (`commands/`)

| Command | Purpose |
|---------|---------|
| `init` | Full environment setup (dirs, .env, compose, venv, repos, docker) |
| `start` | Start Odoo server (modes: normal, --dev, --shell, --test, --prepare) |
| `repos` | Clone/update repos from repos.yaml, generate odoo.conf |
| `db` | list, restore, drop databases |
| `env` | setup, check, show, dir for .env management |
| `venv` | setup, check, activate, path for UV venv |
| `docker` | up, down, status, logs for Docker services |
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
6. `requirements.txt` SHA256 hash unchanged (offers update if changed)

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
