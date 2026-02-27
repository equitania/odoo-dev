# Release Notes

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
