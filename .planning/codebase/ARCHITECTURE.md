<!-- refreshed: 2026-05-13 -->
# Architecture

**Analysis Date:** 2026-05-13

## System Overview

```text
┌─────────────────────────────────────────────────────────────┐
│                        CLI Entry Point                       │
│   `odoodev/cli.py`  — Click group, lang/health init         │
└──────┬──────────────────────────────────────────────────────┘
       │ imports (post-group, avoids circular)
       ▼
┌─────────────────────────────────────────────────────────────┐
│                    Commands Layer                            │
│   `odoodev/commands/*.py`  — Click subcommands              │
│   init  start  stop  repos  db  env  venv  docker           │
│   config  migrate  pull  run  setup  shell_setup            │
└──────┬──────────────────────────────────────────────────────┘
       │ calls
       ▼
┌──────────────────────────────┬──────────────────────────────┐
│         Core Layer           │       TUI Layer               │
│  `odoodev/core/*.py`         │  `odoodev/tui/*.py`           │
│  version_registry            │  OdooTuiApp (Textual)         │
│  global_config               │  OdooProcess (subprocess)     │
│  environment                 │  LogViewer / FilterBar        │
│  prerequisites               │  xmlrpc_client                │
│  venv_manager                └──────────────────────────────┘
│  git_ops                             │
│  database                            │ spawned by start --dev
│  docker_compose                      │
│  odoo_config                         │
│  shell_integration                   │
│  playbook / automation               │
│  migration_config                    │
└──────┬───────────────────────────────┘
       │ reads / renders
       ▼
┌─────────────────────────────────────────────────────────────┐
│              Data + Templates Layer                          │
│  `odoodev/data/versions.yaml`     — bundled version specs   │
│  `~/.config/odoodev/config.yaml`  — user global config      │
│  `~/.config/odoodev/versions-override.yaml` — path overrides│
│  `odoodev/templates/*.j2`         — Jinja2 templates        │
└─────────────────────────────────────────────────────────────┘
       │ generates (at runtime)
       ▼
┌─────────────────────────────────────────────────────────────┐
│              Generated Files (user filesystem)               │
│  vXX-dev/devXX_native/.env                                  │
│  vXX-dev/devXX_native/docker-compose.yml                    │
│  myconfs/odoo_YYMMDD.conf                                   │
│  shell: odoodev-activate.{fish,zsh,bash}                    │
└─────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `cli.py` | Click group root; language init; interpreter health check; command registration | `odoodev/cli.py` |
| `version_registry` | Load/parse `versions.yaml` into frozen dataclasses; user overrides; CWD auto-detection | `odoodev/core/version_registry.py` |
| `global_config` | Load/save `~/.config/odoodev/config.yaml`; module-level cache `_cached_config` | `odoodev/core/global_config.py` |
| `environment` | Detect OS, arch, shell, user; `command_exists` / `find_executable` | `odoodev/core/environment.py` |
| `prerequisites` | Check UV, Docker, wkhtmltopdf, system libs; `check_port`; `check_interpreter_health` | `odoodev/core/prerequisites.py` |
| `venv_manager` | UV-based venv create/install; SHA256 hash of requirements for freshness | `odoodev/core/venv_manager.py` |
| `git_ops` | Clone/update repos with SSH key; module-global `_ssh_key_path`; temp SSH config | `odoodev/core/git_ops.py` |
| `database` | PostgreSQL ops via CLI tools; backup extraction (ZIP/7z/tar/gz/SQL); post-restore deactivation | `odoodev/core/database.py` |
| `docker_compose` | Render and manage `docker-compose.yml` via Jinja2 | `odoodev/core/docker_compose.py` |
| `odoo_config` | Generate `odoo_YYMMDD.conf` with addons_path grouped by section | `odoodev/core/odoo_config.py` |
| `shell_integration` | Install `odoodev-activate` shell function for fish/zsh/bash | `odoodev/core/shell_integration.py` |
| `playbook` | YAML-driven step automation engine; `VALID_COMMANDS` frozenset | `odoodev/core/playbook.py` |
| `automation` | Higher-level automation routines | `odoodev/core/automation.py` |
| `migration_config` | Active migration group detection; overrides target version DB port/postgres | `odoodev/core/migration_config.py` |
| `process_manager` | Subprocess lifecycle management | `odoodev/core/process_manager.py` |
| `TUI: OdooTuiApp` | Textual app; keyboard bindings; log level filtering; restart/update/language actions | `odoodev/tui/app.py` |
| `TUI: OdooProcess` | Wraps `odoo-bin` subprocess; streams stdout to TUI | `odoodev/tui/odoo_process.py` |
| `TUI: log_parser` | Parse Odoo log lines into structured level/message | `odoodev/tui/log_parser.py` |
| `TUI: xmlrpc_client` | XML-RPC calls for module update and language loading | `odoodev/tui/xmlrpc_client.py` |
| `i18n` | DE/EN message catalog; `detect_language` (CLI flag → env var → config) | `odoodev/i18n.py` |
| `output` | Rich console helpers: `print_success/error/warning/info/header/table/confirm` | `odoodev/output.py` |

## Core Data Flow

### Primary: Config Load Pipeline

```
versions.yaml (bundled)
  └─► load_versions()
        ├─ parse into VersionConfig (frozen dataclasses: PortConfig, PathConfig, GitConfig)
        ├─ apply user overrides (~/.config/odoodev/versions-override.yaml)
        ├─ _apply_global_base_dir()  ← reads GlobalConfig.base_dir
        └─ _apply_migration_overrides()  ← reads active MigrationGroup
              └─► dict[str, VersionConfig]  (passed to all commands)
```

### `odoodev init` Flow

```
resolve_version() → load_versions() → get_version()
  → create dirs
  → render .env (Jinja2 env.template.j2)
  → render docker-compose.yml (docker-compose.yml.j2)
  → create_venv() [venv_manager]
  → clone repos [git_ops]
  → generate odoo_YYMMDD.conf [odoo_config]
  → docker compose up [docker_compose]
```

### `odoodev start` Preflight Checklist

Before launching `odoo-bin`, `start.py` checks in order:
1. `.env` exists in `native_dir`
2. `.venv/` directory exists
3. `odoo-bin` exists in `server_dir`
4. `odoo_*.conf` exists in `myconfs_dir` (latest by date suffix)
5. PostgreSQL port reachable (`check_port`) — offers `docker up` if not
6. `requirements.txt` SHA256 unchanged (`check_requirements_changed`) — offers update if changed
7. Python version in venv matches `VersionConfig.python`

After preflight, dispatches to normal / `--dev` (TUI) / `--shell` / `--test` / `--prepare` mode.

## Key Architectural Patterns

### Frozen Dataclasses for Configuration
All version config objects are `@dataclass(frozen=True)`. Mutation is impossible after load; commands receive immutable snapshots.

### Lazy Command Imports in `cli.py`
Command modules are imported after the `@click.group()` body (marked `# noqa: E402`) to break potential circular import chains (e.g., `init_cmd.py` comment documents this explicitly).

### Module-Global State
- `git_ops._ssh_key_path: str | None` — set once via `set_ssh_key()`, read by all git operations in the session.
- `global_config._cached_config: GlobalConfig | None` — module-level cache, avoids repeated disk reads.

### Version Auto-Detection
`detect_version_from_cwd()` in `version_registry.py`:
- Reads `GlobalConfig.base_dir` (default `~/gitbase`)
- Checks if `os.getcwd()` starts with that path
- Extracts `vXX` segment → strips `v` → returns digit string

### Language Detection Chain
`i18n.detect_language(cli_flag)`:
1. `--lang` CLI flag
2. `ODOODEV_LANG` environment variable
3. `GlobalConfig.cli.language` (from `~/.config/odoodev/config.yaml`)
4. Default: `"en"`

### SHA256 Requirements Freshness
`venv_manager.check_requirements_changed()` hashes `requirements.txt` and compares to stored hash. Prompts user to reinstall on mismatch before starting Odoo.

### Migration Config Override
When `migration_config.get_active_group()` returns a group, `load_versions()` rewrites the target version's `PortConfig.db` and `postgres` image — transparent to all commands.

### TUI Runtime (Textual)
`start --dev` mode launches `OdooTuiApp` (Textual). `OdooProcess` wraps `odoo-bin` as a subprocess, streaming log lines to `LogViewer`. `FilterBar` provides per-level toggle filtering. `xmlrpc_client` drives module update and language load via XML-RPC without leaving the TUI.

## Dependency Direction

```
commands/ → core/ → (no upward imports)
tui/      → core/ → (no upward imports)
cli.py    → core/version_registry, core/prerequisites, core/global_config, i18n
commands/ → cli.resolve_version (only)
core/version_registry → core/global_config, core/migration_config (lazy, inside functions)
```

No circular imports. `core/` modules are leaves.

## Error Handling

- Preflight failures in `start.py`: print error via `output.py`, `sys.exit(1)` or offer interactive recovery.
- `check_interpreter_health()` runs at every CLI invocation; exits early on broken UV tool env.
- `_apply_migration_overrides()` wraps all logic in `try/except` — never breaks normal operation.
- Git ops: subprocess return codes checked; SSH failures logged via `logging`.

---

*Architecture analysis: 2026-05-13*
