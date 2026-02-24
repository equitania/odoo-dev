# Release Notes

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
