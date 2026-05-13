# Technology Stack

**Analysis Date:** 2026-05-13

## Languages

**Primary:**
- Python 3.12 / 3.13 — full tool; `requires-python = ">=3.12"` (`pyproject.toml:16`)

**Secondary:**
- Jinja2 templates — `.env`, `docker-compose.yml`, `odoo.conf` generation (`odoodev/templates/`)
- YAML — version registry and repos config (`odoodev/data/versions.yaml`)

## Runtime

**Environment:**
- CPython 3.12+ (host OS — macOS or Linux)
- Python 3.12 used for Odoo v16/v17 venvs
- Python 3.13 used for Odoo v18/v19 venvs (set in `data/versions.yaml`)

**Package Manager:**
- UV — used both for odoodev itself and for managing per-Odoo-version venvs (`odoodev/core/venv_manager.py:21`)
- Lockfile: `uv.lock` present

## Frameworks & Libraries

**Core:**
- `click>=8.1.7` — CLI framework, entry point `odoodev.cli:cli` (`pyproject.toml:36`)
- `rich>=13.7.0` — terminal output (success/error/warning/info/header via `odoodev/output.py`)
- `Jinja2>=3.1.6` — template rendering for `.env`, `docker-compose.yml`, `odoo.conf` (`odoodev/templates/`)
- `PyYAML>=6.0` — parse `versions.yaml`, `repos.yaml`, user override configs
- `python-dotenv>=1.0.0` — load `.env` files into environment before starting Odoo
- `questionary>=2.0.0` — interactive prompts (confirm, select, text) in setup/init flows (`odoodev/output.py:8`)
- `textual>=1.0.0` — TUI (terminal UI) application for interactive server management (`odoodev/tui/`)

**i18n:**
- Custom lightweight DE/EN localization module (`odoodev/i18n.py`) — no external dependency; dot-namespaced flat message dict, language resolved via `--lang` flag → `ODOODEV_LANG` env → config file → system locale

**Build:**
- `hatchling` — build backend (`pyproject.toml:2`)
- `uv build` — build invocation

## Dev Dependencies (`pyproject.toml:39-50`)

| Package | Version | Purpose |
|---------|---------|---------|
| `ruff` | >=0.8.0 | Linting (E,W,F,I,B,UP,S rules) + formatting (double quotes, 120 chars) |
| `pytest` | >=8.0 | Test runner |
| `pytest-cov` | >=5.0 | Coverage (fail-under=55, `pyproject.toml:84`) |
| `pytest-mock` | >=3.12.0 | Mocking in tests |
| `pytest-asyncio` | >=1.0.0 | Async test support |
| `mypy` | >=1.8.0 | Static type checking |
| `types-PyYAML` | >=6.0.0 | Type stubs for PyYAML |
| `types-click` | >=7.1.0 | Type stubs for Click |
| `textual-dev` | >=1.0.0 | Textual TUI dev tools |
| `build` | >=1.0.0 | Package build |

## Key Configuration

**Linting (`pyproject.toml:55-73`):**
- Ruff rules: `E, W, F, I, B, UP, S`
- S603/S607 globally ignored (subprocess with hardcoded commands)
- Per-file suppressions for `start.py` (S104/S606), `database.py` (S105/S202), `env.py` (S701)

**Type checking:**
- `mypy odoodev` — strict type annotations required (`pyproject.toml:40`)

## Runtime Requirements (external, not PyPI)

**Host tools required:**
- `uv` — venv creation and package installation for Odoo Python environments
- `git` — repo clone/update via SSH (`odoodev/core/git_ops.py`)
- `docker` + `docker compose` — PostgreSQL and Mailpit containers (`odoodev/core/docker_compose.py`)
- `psql`, `createdb`, `dropdb` — PostgreSQL CLI tools (`odoodev/core/database.py:95`)
- `odoo-bin` — the Odoo executable (user-provided, cloned via repos)
- `7z` (optional) — for 7zip backup extraction (`odoodev/core/database.py`)

**Platform:**
- macOS (darwin) and Linux (POSIX) supported (`pyproject.toml:21-23`)
- Shell: Fish (primary), Bash, Zsh — shell detection in `odoodev/core/environment.py`

## Supported Odoo Versions

| Odoo | Python | PostgreSQL (Docker) | DB Port | Odoo Port |
|------|--------|--------------------:|--------:|----------:|
| v16 | 3.12 | 16.11-alpine | 16432 | 16069 |
| v17 | 3.12 | 16.11-alpine | 17432 | 17069 |
| v18 | 3.13 | 16.11-alpine | 18432 | 18069 |
| v19 | 3.13 | 17.4-alpine | 19432 | 19069 |

Source: `odoodev/data/versions.yaml`

---

*Stack analysis: 2026-05-13*
