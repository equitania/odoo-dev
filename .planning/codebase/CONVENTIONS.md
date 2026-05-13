# Coding Conventions

**Analysis Date:** 2026-05-13

## Language & Runtime

- Python 3.12+ (pyproject.toml: `requires-python = ">=3.12"`, `target-version = "py312"`)
- All files begin with `from __future__ import annotations` for forward-reference support

## Formatting & Linting

**Tool:** Ruff

**Key settings** (`pyproject.toml`):
- Line length: 120
- Quote style: double (`"`)
- Ruff lint rules: `E, W, F, I, B, UP, S`
- Ignored globally: `S603` (subprocess list args), `S607` (partial executable path)
- Per-file ignores for `tests/**`: `S101, S105, S106, S108, S701, B011, E741`

**Type checking:** mypy (`mypy odoodev`)

**isort:**
- `known-first-party = ["odoodev"]`
- Standard library → third-party → `odoodev` internal

## Import Organization

**Order:**
1. `from __future__ import annotations` (always first if present)
2. Standard library
3. Third-party (click, rich, yaml, jinja2, questionary)
4. `odoodev` internal (absolute only — no relative imports)

**Lazy imports:** `odoodev/commands/init_cmd.py` uses lazy imports inside functions to avoid circular dependencies. Apply same pattern if a new command imports from other commands.

## Naming Patterns

**Files:** `snake_case.py` throughout (`version_registry.py`, `git_ops.py`, `docker_compose.py`)

**Classes:** `PascalCase` — `VersionConfig`, `PortConfig`, `PathConfig`, `GitConfig`

**Functions/methods:** `snake_case` — `load_versions()`, `detect_version_from_cwd()`, `get_version()`

**Constants:** `UPPER_SNAKE_CASE` — `SUPPORTED`, `DEFAULT_LANGUAGE`, `MESSAGES`

**Private helpers:** leading underscore — `_ownerp_style()`, `_patch_checkbox_indicators()`, `_get_template_env()`

**Test classes:** `PascalCase` grouped by subject — `TestLoadVersions`, `TestEnvTemplate`

**Test functions:** `test_<subject>_<scenario>` — `test_node_found_valid_version`, `test_version_18_config`

## Configuration Objects

All config dataclasses are **frozen** (`@dataclass(frozen=True)`):
- `PortConfig` — port numbers per Odoo version
- `PathConfig` — directory paths with computed `@property` accessors
- `GitConfig` — server URL + branch
- `VersionConfig` — top-level container nesting the above

Never use plain dicts for version/port/path config. Add new config fields to the appropriate frozen dataclass.

## Output (Terminal)

**Library:** Rich + questionary. **Never use `print()`.**

All output goes through `odoodev/output.py`:

```python
from odoodev.output import print_success, print_error, print_warning, print_info, print_header

print_success("message")      # [OK] in green
print_error("message")        # [ERROR] in red → stderr
print_warning("message")      # [WARN] in yellow
print_info("message")         # [INFO] in blue
print_header("title", "sub")  # Panel with blue border
```

Interactive prompts also go through `output.py`: `confirm()`, `select()`, `text_input()`, `path_input()`, `checkbox()`, `checkbox_with_separators()`.

## Error Handling

- Preflight failures: `print_error(...)` then `raise SystemExit(1)`
- Never use `click.echo()` for errors — use `print_error()` instead
- Interactive prompt cancellation (Ctrl-C / None result): `raise SystemExit(0)`
- Subprocess errors: re-raise with `raise` after logging, or `sys.exit(result.returncode)`
- No bare `except:` — always catch specific exception types

## Internationalization

User-facing CLI strings support DE/EN via `odoodev/i18n.py`:

```python
from odoodev.i18n import t
msg = t("start.env_missing", path="/foo/.env")
```

- Keys use dot-namespace: `"start.env_missing"`, `"db.restore_confirm"`
- Both `en` and `de` entries required for every new key in `MESSAGES` dict
- Language precedence: `--lang` flag → `ODOODEV_LANG` env var → `~/.config/odoodev/config.yaml` → system locale → `en`
- Only critical user-guidance messages are translated; internal/debug strings stay English

## Docstrings & Comments

- Module-level docstring on every file (one sentence, describes purpose)
- Class docstrings: one sentence describing what the class represents
- Method/function docstrings: one sentence, imperative mood ("Return base path with ~ expanded.")
- Inline comments in English only
- No docstrings on `__init__` unless non-trivial

## Version Management

**Rule:** bump version in **both** files on every functional change:
1. `odoodev/__init__.py` → `__version__ = "X.Y.Z"`
2. `pyproject.toml` → `version = "X.Y.Z"`

**Git commit prefixes:** `[ADD]` new features · `[CHG]` modifications · `[FIX]` bug fixes

## Module Design

- Exports: no `__all__` used; import explicitly from submodules
- No barrel `__init__.py` re-exports (import from `odoodev.core.version_registry`, not `odoodev`)
- Commands live in `odoodev/commands/`, each command in its own file
- Core logic lives in `odoodev/core/`, one file per concern

---

*Convention analysis: 2026-05-13*
