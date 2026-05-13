# Codebase Structure

**Analysis Date:** 2026-05-13

## Directory Layout

```
odoo-dev/
├── odoodev/                    # Main package
│   ├── __init__.py             # Package version (__version__)
│   ├── __main__.py             # python -m odoodev entry point
│   ├── cli.py                  # Click root group + command registration
│   ├── i18n.py                 # DE/EN message catalog + language detection
│   ├── output.py               # Rich console helpers (success/error/info/table)
│   ├── commands/               # Click subcommands (one file per command)
│   ├── core/                   # Pure business logic (no Click)
│   ├── data/                   # Bundled YAML data + example configs
│   ├── templates/              # Jinja2 templates for generated files
│   └── tui/                    # Textual TUI for --dev runtime mode
├── tests/                      # pytest test suite
├── usage/                      # Markdown docs per command (bilingual)
├── temp/                       # Scratch repos.yaml files (not committed to logic)
├── dist/                       # Built wheel/sdist (gitignored content)
├── pyproject.toml              # Single source of truth: deps, ruff, mypy, pytest
├── uv.lock                     # UV lockfile
├── README.md
└── RELEASE_NOTES.md
```

## Directory Purposes

### `odoodev/commands/`
One file per CLI subcommand. Each defines a `@click.command()` or `@click.group()` and imports from `core/`. Commands call `resolve_version()` from `cli.py` then `get_version()` from `version_registry`.

| File | Command | Purpose |
|------|---------|---------|
| `init_cmd.py` | `init` | Full env setup: dirs, .env, compose, venv, repos, docker |
| `start.py` | `start` | Launch Odoo (normal/--dev/--shell/--test/--prepare) |
| `stop.py` | `stop` | Stop Odoo process |
| `repos.py` | `repos` | Clone/update git repos, generate odoo.conf |
| `db.py` | `db` | list/restore/drop databases |
| `env.py` | `env` | .env management (setup/check/show/dir) |
| `venv.py` | `venv` | UV venv management (setup/check/activate/path) |
| `docker.py` | `docker` | Docker Compose control (up/down/status/logs) |
| `config.py` | `config` | Show versions table and platform info |
| `migrate.py` | `migrate` | Odoo module migration orchestration |
| `pull.py` | `pull` | Pull latest repo changes |
| `run.py` | `run` | Run arbitrary odoo-bin command |
| `setup_cmd.py` | `setup` | Interactive first-run configuration |
| `shell_setup.py` | `shell-setup` | Install shell wrapper function |

### `odoodev/core/`
Pure logic modules with no Click dependency. Imported by commands.

| File | Purpose |
|------|---------|
| `version_registry.py` | Load `versions.yaml` → frozen `VersionConfig` dataclasses; CWD auto-detect |
| `global_config.py` | Load/save `~/.config/odoodev/config.yaml`; module-level cache |
| `environment.py` | Detect OS, arch, shell, user; `command_exists` / `find_executable` |
| `prerequisites.py` | Check UV, Docker, wkhtmltopdf, system libs, port reachability |
| `venv_manager.py` | UV venv create/install; SHA256 requirements hash |
| `git_ops.py` | Git clone/update; SSH key management (`_ssh_key_path` global) |
| `database.py` | PostgreSQL CLI ops; backup extraction; post-restore deactivation |
| `docker_compose.py` | Render and invoke docker-compose.yml via Jinja2 |
| `odoo_config.py` | Generate `odoo_YYMMDD.conf` with grouped addons_path |
| `shell_integration.py` | Write shell activation scripts (fish/zsh/bash) |
| `playbook.py` | YAML-driven automation step engine |
| `automation.py` | Higher-level automation routines |
| `migration_config.py` | Active migration group; overrides DB port/postgres in version registry |
| `process_manager.py` | Subprocess lifecycle management |
| `example_templates.py` | Helper to emit bundled example config files |

### `odoodev/data/`

```
odoodev/data/
├── versions.yaml               # Bundled version specs for v16-v19
└── examples/
    ├── v16/
    │   ├── repos.yaml          # Example repos definition
    │   ├── requirements.txt    # Example Python deps
    │   ├── odoo16_template.conf
    │   └── postgresql.conf
    ├── v17/  (same structure)
    ├── v18/  (same structure)
    ├── v19/  (same structure)
    └── playbooks/
        ├── daily-update.yaml
        ├── full-refresh.yaml
        ├── restore-db.yaml
        └── start-dev.yaml
```

### `odoodev/templates/`

```
odoodev/templates/
├── __init__.py
├── docker-compose.yml.j2       # Jinja2: PostgreSQL + Mailpit compose
├── env.template.j2             # Jinja2: .env file
└── shell/
    ├── odoodev-activate.bash
    ├── odoodev-activate.fish
    └── odoodev-activate.zsh
```

Templates receive `VersionConfig` fields and environment detection results as context.

### `odoodev/tui/`

```
odoodev/tui/
├── __init__.py
├── app.py                      # OdooTuiApp (Textual App subclass)
├── app.tcss                    # Textual CSS stylesheet
├── log_parser.py               # Parse Odoo log lines → level/message
├── odoo_process.py             # Subprocess wrapper; streams stdout to TUI
├── screens.py                  # Textual Screen definitions (dialogs)
├── xmlrpc_client.py            # XML-RPC: module update, language load
└── widgets/
    ├── __init__.py
    ├── filter_bar.py           # Per-level log filter toggle bar
    ├── log_viewer.py           # Scrollable log display widget
    └── status_bar.py           # Status bar widget
```

Activated by `odoodev start --dev`. Not imported during normal CLI operations.

### `tests/`

```
tests/
├── __init__.py
├── conftest.py                 # Fixtures: tmp_dir, versions_yaml (minimal YAML)
├── test_version_registry.py
├── test_cli_config.py
├── test_environment.py
├── test_git_ops.py
├── test_database.py
├── test_db_backup.py
├── test_venv_manager.py
├── test_venv_patch_version.py
├── test_prerequisites.py
├── test_start.py
├── test_start_language.py
├── test_start_odoo_options.py
├── test_stop.py
├── test_run_command.py
├── test_pull.py
├── test_addon_selector.py
├── test_automation.py
├── test_playbook.py
├── test_migration_config.py
├── test_migrate_command.py
├── test_setup_command.py
├── test_shell_integration.py
├── test_templates.py
├── test_example_templates.py
├── test_global_config.py
├── test_i18n.py
├── test_log_parser.py
├── test_odoo_process.py
├── test_process_manager.py
├── test_process_manager_group.py
├── test_restore_temp_dir.py
├── test_tui_app.py
├── test_interpreter_health.py
├── test_v19_log_handlers.py
├── test_xmlrpc_client.py
└── test_interpreter_health.py
```

## Key File Locations

**Entry Points:**
- `odoodev/cli.py`: Click root group, language + health init, command registration
- `odoodev/__main__.py`: Enables `python -m odoodev`

**Configuration (pyproject.toml sections):**
- `[project]`: package metadata, dependencies
- `[project.scripts]`: `odoodev = "odoodev.cli:cli"`
- `[tool.ruff]`: linting rules (E, W, F, I, B, UP), line-length 120
- `[tool.mypy]`: type checking config
- `[tool.pytest.ini_options]`: test discovery settings

**Bundled Data:**
- `odoodev/data/versions.yaml`: canonical version specs (v16–v19)

**User Config Files (runtime, outside repo):**
- `~/.config/odoodev/config.yaml`: global config (base_dir, DB creds, language)
- `~/.config/odoodev/versions-override.yaml`: per-version path/port overrides

## Required User-Provided Files

These files are **not** in the repo; users create them from examples in `odoodev/data/examples/vXX/`:

| File | Path | Purpose |
|------|------|---------|
| `repos.yaml` | `vXX-dev/scripts/repos.yaml` | Repository definitions for `odoodev repos` |
| `requirements.txt` | `vXX-dev/devXX_native/requirements.txt` | Python deps for Odoo venv |
| `odooXX_template.conf` | `vXX-dev/conf/odooXX_template.conf` | Template for `odoo_YYMMDD.conf` generation |

## Naming Conventions

**Files:**
- Commands: verb noun pattern (`init_cmd.py`, `setup_cmd.py`) or plain noun (`start.py`, `repos.py`)
- Tests: `test_<module_name>.py` mirroring source module names
- Templates: target filename + `.j2` suffix (`docker-compose.yml.j2`)

**Generated files:**
- Odoo config: `odoo_YYMMDD.conf` (date suffix allows keeping multiple versions)
- Shell activation: `odoodev-activate.{fish,zsh,bash}`

## Where to Add New Code

**New CLI subcommand:**
- Implementation: `odoodev/commands/<name>.py`
- Register in: `odoodev/cli.py` (import + `cli.add_command(...)`)
- Tests: `tests/test_<name>.py`

**New core logic (no Click):**
- Implementation: `odoodev/core/<name>.py`
- Tests: `tests/test_<name>.py`

**New Jinja2 template:**
- Template: `odoodev/templates/<filename>.j2`
- Renderer: add to `odoodev/core/docker_compose.py` or new core module

**New version example:**
- Config files: `odoodev/data/examples/vXX/`
- Version spec: `odoodev/data/versions.yaml`

**New TUI widget:**
- Widget: `odoodev/tui/widgets/<name>.py`
- Register in: `odoodev/tui/app.py` compose method

---

*Structure analysis: 2026-05-13*
