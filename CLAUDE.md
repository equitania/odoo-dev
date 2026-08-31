# CLAUDE.md

This file provides guidance to coding agents working with code in this repository — Claude Code
(claude.ai/code) and, via the `AGENTS.md` symlink pointing here, Codex and any other agent that
reads `AGENTS.md`.

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

### Architecture reference

Module-by-module detail, the command table, the data-flow diagram and the `start`
preflight list live in **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — read it when
changing a core module or adding a command. For *using* the CLI, `usage/AGENT.md` is
the better source: it tracks the actual `--help` output.

### Traps worth knowing before you touch the code

These are the things that are wrong-by-default if you do not know them:

- **`requirements.txt` is generated** from the shipped baseline plus
  `requirements.local.txt`. Never hand-edit it, never commit a `requirements.txt` as
  the source of truth — edit the overlay and run `odoodev requirements sync`.
  Overlay and baseline match on `(PEP 503 name, environment marker)`, with a
  name-level fallback only when one side is unmarked.
- **`git_ops.clone_repo` / `switch_branch_and_update` return `(result, error)` tuples.**
  A caller that ignores the second element swallows a failed clone silently.
- **Every psql/pg_dump call may run through `docker exec`** into the container
  publishing the target port (`resolve_pg_exec_mode`), because host pg clients are
  often absent or version-mismatched. Pipe dumps via stdin — never `psql -f` — and
  pass `stdin=subprocess.DEVNULL` to anything non-interactive, or the container's
  `-i` flips the terminal into raw mode.
- **Post-restore processing is OFF by default.** `db restore` leaves the database
  untouched unless a flag or `--sanitize` opts in; explicit `--no-*` always wins.
- **Playbook secrets belong in the 0600 `env_file`,** never in the YAML.

### Required files (user-provided)

| File | Path | Purpose |
|------|------|---------|
| `repos.yaml` | `vXX-dev/scripts/repos.yaml` | Repository definitions for git clone |
| `requirements.local.txt` | `vXX-dev/devXX_native/requirements.local.txt` | Machine-local requirements overlay (v0.63.0); `requirements.txt` itself is now generated from this plus the shipped baseline — see `core/requirements_sync.py` |
| `odooXX_template.conf` | `vXX-dev/conf/odooXX_template.conf` | Template for Odoo config generation |

### Path convention

```
~/gitbase/vXX/
├── vXX-server/              # Odoo server code
├── vXX-dev/
│   ├── devXX_native/       # Native dev env (venv, .env, docker-compose.yml)
│   │   ├── requirements.local.txt # User-provided overlay (v0.63.0)
│   │   └── requirements.txt       # Generated: baseline + overlay
│   ├── conf/               # Config templates (user-provided)
│   └── scripts/            # repos.yaml (user-provided)
└── myconfs/                # Generated odoo_YYMMDD.conf files
```

### Templates (`templates/`)

Jinja2 templates for: `.env`, `docker-compose.yml`, `odoo.conf`, and shell activation scripts. Template context comes from `VersionConfig` and environment detection.

## Code Conventions

- Python 3.12+ (`requires-python = ">=3.12"`), line length 120, target `py312`
- Ruff rules: E, W, F, I, B, UP, **S** (bandit security checks — `subprocess` calls need a justification comment or an explicit `# noqa: S`)
- Double quotes (`"`)
- isort with `known-first-party = ["odoodev"]`
- Frozen dataclasses for configuration objects
- Absolute imports only (no relative imports)
- Lazy imports in `init_cmd.py` to avoid circular dependencies
- Rich library for all terminal output (never plain print)

## Testing

Tests use pytest with Click's `CliRunner`. Fixtures in `conftest.py` provide `tmp_dir` and a parsed `versions_yaml` dict. Tests cover version registry, environment detection, CLI commands, and template rendering via monkeypatching.
