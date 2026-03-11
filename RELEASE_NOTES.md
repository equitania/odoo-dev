# Release Notes

## Version 0.4.15 (11.03.2026)

### Changed
- **Dynamic sections for addons_path**: Removed hardcoded `SECTION_ORDER` list from `odoo_config.py` — sections in the generated `odoo.conf` now follow the insertion order from `repos.yaml`. Any section name (e.g. "DACH", "Design", "Chatbot", "fast-report") is supported; previously only 8 fixed names were recognized and all others were silently dropped.

## Version 0.4.14 (11.03.2026)

### Added
- **Interpreter health check**: Detects broken UV tool environments where Python versions have been removed by `uv python` updates
  - `check_interpreter_health()`: Validates the running Python interpreter's symlink chain at CLI startup; exits with clear fix instruction (`uv tool upgrade --all`) if broken
  - `check_venv_interpreter()`: Validates Odoo venv Python symlink chains before `odoodev start`; suggests `odoodev venv setup <version> --force` if broken
  - `_resolve_symlink_chain()`: Utility to follow and report multi-level symlink chains with broken-link detection
- **Shell wrapper pre-flight checks**: `odoodev-activate` (Fish/Bash/Zsh) now verifies the odoodev interpreter is functional before calling it — catches the case where `odoodev` itself cannot start at all
- 14 new tests for interpreter health checks (symlink chain resolution, broken venvs, UV tool directory detection)

## Version 0.4.13 (11.03.2026)

### Added
- System dependency checks for `odoodev init`: Node.js, npm, Node packages (rtlcss, less, less-plugin-clean-css), and system libraries (libldap, libxml2, libxslt, libjpeg, cairo, fontconfig)
- Platform-specific install instructions: Homebrew (macOS) and apt-get (Linux/Debian)
- `check_node()`: Detects Node.js with version warning (< 20) and npm availability check
- `check_node_packages()`: Verifies rtlcss/lessc binaries and less-plugin-clean-css via npm
- `check_system_libs()`: Checks C-extension build dependencies via `brew --prefix` (macOS) or `dpkg -l` (Linux)
- 17 new tests for all prerequisite checks

### Changed
- All new checks are WARNING-level (non-blocking) — pre-built wheels don't need system libs

## Version 0.4.12 (09.03.2026)

### Added
- `odoodev pull`: Automatic Odoo config regeneration (`odoo_YYMMDD.conf`) after pulling repositories, so the `addons_path` stays up-to-date when new modules arrive via pull
- `odoodev pull --no-config`: Opt-out flag to skip config regeneration when only a quick pull is needed

## Version 0.4.11 (06.03.2026)

### Fixed
- **Security hardening**: Eliminated all `shell=True` subprocess calls in `database.py` and `git_ops.py` to prevent command injection via user-supplied database names, git URLs, and branch names
- `database.py`: All PostgreSQL commands (`psql`, `createdb`, `dropdb`, `pg_dump`) now use safe argument lists instead of shell string interpolation
- `git_ops.py`: `run_git_command()` signature changed from `str` to `list[str]`; all git operations (`clone`, `checkout`, `pull`, `ls-remote`) and `find` commands use argument lists
- `backup_database_sql()` and `extract_backup()` gz: Shell output redirects replaced with Python file handles
- Removed obsolete `S602` ruff ignores from `pyproject.toml`

## Version 0.4.10 (05.03.2026)

### Fixed
- `odoodev venv check`: Patch version upgrade now correctly passes the full Python version (e.g. `3.13.12`) to `venv setup`, so UV creates the venv with the exact detected version instead of the latest for the major.minor
- `odoodev venv setup`: Uses `--clear` flag when recreating an existing venv, preventing UV's interactive "replace?" prompt
- `odoodev core/venv_manager.py`: `create_venv()` now appends `--clear` when target directory exists

## Version 0.4.9 (05.03.2026)

### Fixed
- Fish shell: `odoodev-activate` used reserved `$version` variable (Fish built-in = Fish version e.g. `4.5.0`), causing all commands to receive wrong version. Renamed to `$_odoo_ver`.

## Version 0.4.8 (05.03.2026)

### Added
- Fish shell completions for all `odoodev` commands, subcommands, and flags via Click's built-in completion
- Dynamic version completions for `odoodev-activate` (Tab shows available versions like 16, 17, 18, 19)
- Fish abbreviations: `oda` -> `odoodev-activate`, `odev` -> `odoodev`
- Bash/Zsh completions for `odoodev` (via `eval`) and `odoodev-activate`
- Bash/Zsh aliases: `oda` -> `odoodev-activate`, `odev` -> `odoodev`
- `odoodev config versions --plain` flag for script-friendly output (one version per line)
- Python patch version advisory: `odoodev start` and `odoodev venv check` warn when a newer Python patch version is available on the system
- `get_full_python_version()` and `get_system_python_version()` in `venv_manager.py`
- Zsh now has its own completion block (using `compdef`) instead of sharing Bash's function
- 27 new tests for shell integration (completions, abbreviations, installation, `--plain` flag)

### Changed
- `odoodev shell-setup` now installs completions, abbreviations/aliases alongside the `odoodev-activate` function
- Shell setup output shows what was installed (completions, abbreviations/aliases)
- `tests/**` excluded from ruff S101 rule (assert is standard in pytest)
- README.md refactored: compact main README with links to `usage/` documentation files
- Separate bilingual docs (DE/EN) in `usage/` for: setup, start, db, repos, venv, docker, run, shell, config

## Version 0.4.7 (05.03.2026)

### Changed
- All commands now interactive when flags are omitted — "prompt if not provided" pattern
- `odoodev db drop` without `-n`: interactive database selection via `_select_database()`
- `odoodev db restore` without `-n`/`-z`: interactive file path and database name prompts with smart name suggestion from filename
- `odoodev run` without args: interactive mode selection (YAML playbook or inline step checkbox)
- `odoodev start` prerequisite checks: missing `.env`, `.venv`, `odoo-bin`, `odoo_*.conf` now offer to create/clone via `confirm()` + `ctx.invoke()` instead of showing error
- `odoodev env check`/`env show`: missing `.env` offers creation via `confirm()` + `ctx.invoke(env_setup)`
- `odoodev venv check`/`venv activate`: missing `.venv` offers creation via `confirm()` + `ctx.invoke(venv_setup)`
- `odoodev repos`/`pull`: missing `repos.yaml` copies example template and shows guidance instead of bare error
- New output helpers: `text_input()`, `path_input()`, `checkbox()` in `output.py`
- All commands remain fully scriptable — explicit flags skip interactive prompts

## Version 0.4.6 (05.03.2026)

### Changed
- Questionary as unified prompt system across all commands

## Version 0.4.5 (05.03.2026)

### Changed
- `odoodev db drop` now also removes the filestore directory (`~/odoo-share/vXX/filestore/{db_name}/`) when dropping a database
- Confirmation prompt includes filestore notice when a filestore exists
- `odoodev db restore` now shows a hint to run `odoodev start -- -d {name} -u all` after restore

## Version 0.4.4 (04.03.2026)

### Changed
- `odoodev pull` now shows detailed error messages when repository updates fail (e.g. branch not found, merge conflicts)
- `update_repo()` returns `tuple[bool, str]` instead of `bool` to propagate git error messages
- `--verbose` flag now produces debug logs per repository (updating, success/failure)
- Summary table displays error details below the table for each failed repository

## Version 0.4.0 (27.02.2026)

### Added
- `odoodev run` command — YAML-driven playbook automation for AI agents and scripted workflows
- Two execution modes: YAML playbook files (`odoodev run playbook.yaml`) and inline steps (`odoodev run --step docker.up --step pull -V 18`)
- 15 non-interactive command handlers: `docker.up`, `docker.down`, `docker.status`, `pull`, `repos`, `start`, `stop`, `db.list`, `db.backup`, `db.restore`, `db.drop`, `env.check`, `venv.check`, `venv.setup`
- `--dry-run` flag for previewing playbook steps without execution
- `--output json` for NDJSON machine-readable output (one JSON event per line)
- Per-step `on_error` override (stop/continue) with playbook-level default
- Non-blocking `start` handler — launches Odoo as background subprocess
- `--yes` flag for `odoodev db drop` to skip confirmation prompt
- 4 bundled example playbooks in `odoodev/data/examples/playbooks/`: daily-update, start-dev, full-refresh, restore-db
- `odoodev/core/playbook.py` — frozen dataclasses (`StepConfig`, `PlaybookConfig`, `StepResult`, `PlaybookResult`), YAML loader with validation, `PlaybookRunner`
- `odoodev/core/automation.py` — handler registry (`COMMAND_HANDLERS`) with non-interactive wrappers around core functions
- 69 new tests covering playbook engine, automation handlers, and CLI integration

### Fixed
- `odoodev start --no-confirm` now also skips the Docker start confirmation prompt

## Version 0.3.4 (27.02.2026)

### Fixed
- Odoo config templates (v16-v19): replaced deprecated `longpolling_port` with `gevent_port`
- Odoo config templates (v16-v19): corrected `limit_request` from `8192` to `65536` (official default)
- v16 template: replaced deprecated `osv_memory_age_limit` with `transient_age_limit = 1.0`
- v19 template: replaced `without_demo` with `with_demo` (new v19 parameter)
- Removed invalid parameters from all templates: `demo = {}`, `translate_modules`

### Changed
- Removed unused Jinja2 master template `odoo_template.conf.j2` (not version-specific, never used by repos command)
- Credentials in all example templates now use project standard (`ownerp`/`CHANGE_AT_FIRST`)

### Security
- Default password replaced with `CHANGE_AT_FIRST` across all source files, templates, and documentation
- Git history cleaned via `git filter-repo` to remove hardcoded credentials from all historical commits

## Version 0.3.3 (26.02.2026)

### Added
- `odoodev pull [VERSION]` command — quick `git pull` across all existing repositories without cloning, SSH access checks, or config regeneration
- `odoodev db backup [VERSION]` subcommand — create database backups as SQL dump (`pg_dump`) or ZIP with filestore (Odoo standard format)
- Interactive database and backup type selection when options are omitted
- Core functions `backup_database_sql()` and `create_backup_zip()` in `database.py`
- Rich summary table for pull results (Updated/Skipped/Failed)
- Tests for pull command (6 tests) and db backup (7 tests)

## Version 0.3.2 (26.02.2026)

### Added
- `odoodev stop [VERSION]` command — stops running Odoo process (via port-based process discovery) and Docker services
- `odoodev/core/process_manager.py` — reusable core module for process discovery via `lsof` and graceful termination (SIGTERM → SIGKILL)
- `--keep-docker` flag for `stop` — keeps PostgreSQL/Mailpit running while stopping Odoo
- `--force` flag for `stop` — immediate SIGKILL without graceful shutdown
- `odoodev init` now checks for `wkhtmltopdf` at startup — shows install hint if missing (non-blocking warning)
- Start modes overview table in README (DE + EN) documenting all `--dev`, `--shell`, `--test`, `--prepare` flags

### Changed
- Start prompt improved: "Start Odoo v18 server?" instead of unclear "in normal mode"; descriptive labels for dev/shell/test modes
- When declining start prompt, alternative modes (`--dev`, `--shell`, `--test`, `--prepare`) are now shown with descriptions

### Fixed
- Mailpit URL in start banner is now only displayed when the Mailpit service is actually reachable (port check via `check_port()`)
- `wkhtmltopdf` install hint now recommends the 'patched qt' binary from wkhtmltopdf.org instead of `brew install wkhtmltopdf` — Homebrew's version lacks patched Qt and may not render Odoo PDF reports correctly
- README installation instructions corrected accordingly (both DE and EN sections)

## Version 0.2.0 (24.02.2026)

### Added
- Interactive setup wizard (`odoodev setup`) with questionary-based prompts for base directory, active versions, and database credentials
- Global configuration infrastructure (`global_config.py`) with `GlobalConfig` and `DatabaseConfig` frozen dataclasses, YAML persistence, and module-level caching
- First-run detection hint when no configuration exists
- `--non-interactive` flag for automated setup with defaults
- `--reset` flag to restore default configuration
- Global Configuration section in `config show` output
- Dynamic base directory support — version paths automatically rebase when global config has custom `base_dir`

### Changed
- Database credentials in `.env` template are now parametrized via global config instead of hardcoded
- `database.py` reads credentials from global config at runtime with fallback to module constants
- `version_registry.py` uses global config `base_dir` for version auto-detection and path resolution
- README.md restructured with setup wizard documentation at prominent position
- Version bump to 0.2.0

### Fixed
- Version path rebasing respects explicit user overrides from `versions-override.yaml`

## Version 0.1.0

- Initial release with CLI commands: init, start, repos, db, env, venv, docker, config, shell-setup
- Version registry with frozen dataclasses and user override support
- Jinja2 template system for .env, docker-compose.yml, and odoo.conf generation
- UV-based virtual environment management with requirements hash tracking
- Rich console output helpers
