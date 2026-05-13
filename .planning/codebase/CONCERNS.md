# Codebase Concerns

**Analysis Date:** 2026-05-13

---

## HIGH — Security / Correctness

### Default PostgreSQL password in source

**Issue:** `DEFAULT_DB_PASSWORD = "CHANGE_AT_FIRST"` is a module-level constant that flows into `PGPASSWORD` env var when `.pgpass` is absent and no global config is configured.
**Files:** `odoodev/core/database.py:17`, `odoodev/core/database.py:72-74`
**Impact:** New users who skip `odoodev setup` have the placeholder password silently used for all DB operations. The one-shot warning (`_insecure_default_warned`, line 20) fires at most once per process; if the first call is from a background context the warning is never visible. `odoodev start` has a separate blocking check (`_check_placeholder_password`), but `odoodev db restore` does not go through that path.
**Fix approach:** Make `_get_pg_env` raise `ClickException` rather than fall through silently when the placeholder is detected and no `.pgpass` exists.

### Port 18432 hardcoded in `database.py` function signatures

**Issue:** Every public function in `odoodev/core/database.py` defaults `port=18432` directly in the signature (lines 58, 86, 116, 135, 162, 184, 203, 415, 478, 498). Callers that do not explicitly pass a port use this literal regardless of what the version registry or `.env` file says.
**Files:** `odoodev/core/database.py` (10 occurrences), `odoodev/core/odoo_config.py:75`, `odoodev/commands/start.py:130`
**Impact:** Silent misconfiguration if a version's `DB_PORT` differs from 18432. The port is read from `.env` at the `start` command level but not threaded through to bare `database.py` calls made from other commands (e.g., `db list`).
**Fix approach:** Remove the literal default; require callers to supply the port, or read it from global config inside `_get_pg_env`.

---

## HIGH — Reliability

### `run_git_command` used for non-git `find` commands

**Issue:** `update_repo` calls `run_git_command(["find", ".", ...])` (lines 240–241) to clean `.pyc` files. This injects `GIT_SSH_COMMAND` into the environment of a `find` invocation and ignores its return value. On Windows or containers without `find` in PATH the call silently fails.
**Files:** `odoodev/core/git_ops.py:240-241`
**Impact:** Python cache cleanup is unreliable; errors are swallowed.
**Fix approach:** Use `pathlib.Path.rglob("**/*.pyc")` + `unlink()` in pure Python instead.

### Module-global mutable state — testability and thread-safety

**Issue:** Five module-level mutable globals exist:
- `_ssh_key_path` (`core/git_ops.py:12`) — mutated by `set_ssh_key()`
- `_insecure_default_warned` (`core/database.py:20`) — one-shot flag, never reset between tests
- `_cached_config` (`core/global_config.py:22`, `core/migration_config.py:19`) — persists across test cases unless explicitly cleared
- `_active_language` (`i18n.py:32`) — changed by `set_language()`

**Impact:** Tests that call functions touching these globals are order-dependent. The `_cached_config` globals are the highest-risk: a test that loads a config file will contaminate subsequent tests unless `importlib.reload()` or explicit reset is used. Coverage report at 58.5% means many paths through these globals are not exercised under controlled conditions.
**Fix approach:** Expose `_reset_*` helpers for tests; consider a `Config` context object passed explicitly instead of module globals.

### `start.py` accumulates `type: ignore` suppressions

**Issue:** Five `# type: ignore[attr-defined]` comments in `odoodev/commands/start.py` (lines 244, 245, 434, 524, 612) suppress mypy errors on `version_cfg` attribute access. This indicates the type of `version_cfg` is `VersionConfig | None` at the call site but the code proceeds without a None guard.
**Files:** `odoodev/commands/start.py:244-245, 434, 524, 612`
**Impact:** If `version_cfg` is `None` at those lines, an `AttributeError` is raised at runtime rather than a clean user-facing error.
**Fix approach:** Add explicit `assert version_cfg is not None` or refactor to raise `ClickException` before reaching those lines; then remove the `type: ignore` annotations.

---

## MEDIUM — Fragility / Tech Debt

### CWD-based version auto-detection is brittle

**Issue:** `detect_version_from_cwd()` (`core/version_registry.py:287`) parses the process working directory against `~/gitbase/vXX/...`. If the user runs odoodev from outside that tree, from a symlinked path, or with a custom `base_dir`, detection returns `None` and every command requires an explicit version argument.
**Files:** `odoodev/core/version_registry.py:287-308`, `odoodev/cli.py:38`, `odoodev/core/global_config.py:15`
**Impact:** Silent failure mode — no version detected, no helpful error until a subcommand runs. The error message references `~/gitbase/vXX/...` literally (`cli.py:46`), confusing users with a non-default `base_dir`.
**Fix approach:** When detection fails, show the configured `base_dir` in the error, not the hardcoded default string.

### Version list duplicated outside `versions.yaml`

**Issue:** `["16", "17", "18", "19"]` appears in both `odoodev/core/global_config.py:18` (`DEFAULT_ACTIVE_VERSIONS`) and `odoodev/commands/setup_cmd.py:85` (`all_versions`). Adding v20 support requires updating both locations plus `versions.yaml`.
**Files:** `odoodev/core/global_config.py:18`, `odoodev/commands/setup_cmd.py:85`
**Fix approach:** `setup_cmd.py` should derive its list from `available_versions()` (already exists in `version_registry.py:311`).

### Lazy imports in `init_cmd.py` to break circular deps

**Issue:** `init_cmd.py:41-44` defers imports of `check_node`, `check_wkhtmltopdf` etc. inside the command function body with a comment explaining this avoids circular imports. The circular dependency itself is not resolved.
**Files:** `odoodev/commands/init_cmd.py:41-44`
**Impact:** Code smell that hides a structural issue; any future import of `init_cmd` at module level would re-trigger the circular import problem.
**Fix approach:** Move prerequisite checks to a separate `checks.py` module with no upward imports.

### Backup restore deactivates cron/cloud by default without undo path

**Issue:** `db restore` runs `deactivate_cronjobs` and `deactivate_cloud` with `default=True` (lines 197-203). These `UPDATE` statements (`ir_cron SET active = false`, `ir_mail_server SET active = false`, `ir_config_parameter SET value = ''`) are irreversible within the restore flow — no backup of the pre-restore state is taken.
**Files:** `odoodev/commands/db.py:197-203`, `odoodev/core/database.py:482-510`
**Impact:** Developer restoring a production backup to test a feature silently destroys scheduling config. The `--no-deactivate-cron` flag is available but not prominently documented in the help text.
**Fix approach:** Log the rows affected before modification so the user can restore them; consider printing a post-restore summary of changes made.

### User-provided files create silent onboarding failures

**Issue:** Three files must exist before most commands are useful: `repos.yaml`, `requirements.txt`, `odooXX_template.conf`. Their absence is checked at command runtime, not at `odoodev init` time, so failures surface only when the dependent subcommand runs.
**Files:** `odoodev/core/example_templates.py:39-42`, `odoodev/commands/pull.py:66-69`, `odoodev/commands/init_cmd.py:155`
**Impact:** New user runs `odoodev init 18`, gets success, then `odoodev start 18` fails with a missing-config error.
**Fix approach:** `init` should emit a visible checklist of required user files that are still missing at the end of its run.

---

## MEDIUM — Recent Instability Indicators

### Repeated prerequisite probe fixes (v0.4.45 → v0.4.54)

**Pattern:** Four releases in the v0.4.45–v0.4.54 range touched `prerequisites.py`: Node.js hints (v0.4.45/v0.4.46), system library checks for Debian (v0.4.45), multi-name package probing for Debian 13 renames (v0.4.54).
**Files:** `odoodev/core/prerequisites.py`
**Implication:** The OS/distro detection and package-name mapping logic is the most frequently broken area. Test coverage for this module exists (`tests/test_prerequisites.py`, 249 lines) but distro-specific branches require mocking, leaving real-world regressions possible.

### TUI filter and log parser fixes (v0.4.53)

**Pattern:** `multi-toggle level filter + RAW-inheritance + transparent footer` were all fixed together, suggesting the TUI layer accumulated several interacting bugs.
**Files:** `odoodev/tui/widgets/filter_bar.py`, `odoodev/tui/log_parser.py`, `odoodev/tui/widgets/status_bar.py`
**Risk:** The TUI has broad `except Exception` catches (filter_bar.py:200, 215; status_bar.py:85) that hide errors. `test_tui_app.py` is the largest test file (545 lines) but TUI tests are inherently harder to cover.

---

## LOW — Minor Issues

### Uncommitted example `repos.yaml` files

**State:** `odoodev/data/examples/v{16,17,18,19}/repos.yaml` are modified but not committed (current git status). These are the scaffolding files created for new users via `odoodev pull`. If the working tree stays dirty, future `git stash` or branch operations may inadvertently discard them.
**Action:** Commit or document why they are intentionally held back.

### `gunzip` external binary with no fallback

**Issue:** `.gz` backup extraction calls `["gunzip", "-c", backup_file]` (`database.py:281`) with no `shutil.which("gunzip")` check. On Windows or minimal Docker images `gunzip` is absent.
**Files:** `odoodev/core/database.py:276-287`
**Fix approach:** Use `gzip.open()` from stdlib as a fallback.

### Coverage threshold at 55% (low bar)

**Config:** `pyproject.toml` sets `--cov-fail-under=55`. At 58.53% reported, the project is barely above the threshold.
**Risk:** Large untested areas include `core/automation.py` (683 lines), `commands/start.py` (824 lines), and `tui/` widgets. Regressions in these areas would not be caught by CI.
**Fix approach:** Incrementally raise the threshold and add targeted tests for the `start` preflight checks and `automation.py` step orchestration.

---

*Concerns audit: 2026-05-13*
