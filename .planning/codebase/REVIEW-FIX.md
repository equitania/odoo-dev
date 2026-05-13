---
phase: codebase
fixed_at: 2026-05-13T10:50:00+02:00
review_path: .planning/codebase/REVIEW.md
iteration: 1
findings_in_scope: 11
fixed: 8
skipped: 3
status: partial
---

# Code Review Fix Report

**Fixed at:** 2026-05-13
**Source review:** `.planning/codebase/REVIEW.md`
**Iteration:** 1

**Summary:**
- Findings in scope: 11 (3 Critical + 8 Warning)
- Fixed: 8
- Skipped: 3

## Fixed Issues

### CR-01: `os.chdir()` before `subprocess.run()` mutates global CWD

**Files modified:** `odoodev/commands/start.py`
**Commit:** 4247d8e
**Applied fix:** Removed `os.chdir(odoo_dir)` call; added `cwd=odoo_dir` to `subprocess.run()`.

---

### CR-02: SSH config `~/.ssh/odoodev_config` never cleaned up

**Files modified:** `odoodev/core/git_ops.py`
**Commit:** d9775ab
**Applied fix:** Replaced `os.open` on a fixed path with `tempfile.mkstemp(prefix="odoodev_ssh_", ...)` + `atexit.register` to delete on process exit. Added `atexit` and `tempfile` imports.

---

### CR-03: Temp directories leaked when `os.execvpe()` replaces process

**Files modified:** `odoodev/commands/start.py`
**Commit:** 7928abb
**Applied fix:**
- zsh path: replaced `tempfile.mkdtemp()` with a fixed `~/.cache/odoodev/` directory (overwritten each time, never accumulates).
- bash path: kept `mkdtemp` but unlinks the file and rmdir the tmpdir immediately before `execvpe` — POSIX allows this because bash already holds an open fd to the file via `--rcfile`.

---

### WR-01: `run_git_command()` used for `find` — errors silently ignored

**Files modified:** `odoodev/core/git_ops.py`
**Commit:** 105fd3e
**Applied fix:** Replaced both `run_git_command(["find", ...])` calls with `subprocess.run([...], capture_output=True)` (check=False by default). Errors are non-fatal and no longer misleadingly routed through the git command handler.

---

### WR-03: `_write_pgpass` fd leak when `os.fdopen` fails

**Files modified:** `odoodev/commands/start.py`
**Commit:** 656c4a6
**Applied fix:** Added `fd = -1` sentinel after `os.fdopen` consumes the descriptor; exception handler closes `fd` only when it is still open (i.e., `fd != -1`).

---

### WR-04: Post-restore deactivation failures silently ignored

**Files modified:** `odoodev/commands/db.py`
**Commit:** 9b6de00
**Applied fix:** Both `deactivate_cronjobs()` and `deactivate_cloud()` return values are now checked; a `print_warning()` is emitted on failure (non-fatal, tables may simply not exist on fresh databases).

---

### WR-07: `docker compose up` return code not checked

**Files modified:** `odoodev/commands/start.py`
**Commit:** b98948b
**Applied fix:** Captured `subprocess.run` result; added `returncode != 0` check with an immediate `print_error` + `SystemExit(1)` before sleeping and re-checking the port.

---

### WR-08: `.env` parser does not strip surrounding quotes

**Files modified:** `odoodev/commands/start.py`
**Commit:** 99ce4ad
**Applied fix:** Added quote-stripping for single and double quotes. Also expanded `$USER` (bare, without braces) in addition to the existing `${USER}` expansion.

---

## Skipped Issues

### WR-02: `_insecure_default_warned` global not reset between test invocations

**File:** `odoodev/core/database.py:20-38`
**Reason:** Intentional design — warn-once per process prevents log spam. Resetting per-command requires a context/state object threaded through many call sites. Risk is negligible in production (CLI invoked once per shell session). Skipping.

---

### WR-05: `extract_backup` bare `except Exception` hides error type

**File:** `odoodev/core/database.py:296-299`
**Reason:** The existing `except ValueError: raise` guard correctly preserves path-traversal errors. The outer handler covers multiple archive formats (zip, tar, gz, sql) with different exception types. Narrowing without a comprehensive test suite risks silent regressions. Skipping.

---

### WR-06: Module-global `_ssh_key_path` not thread-safe

**File:** `odoodev/core/git_ops.py:12`
**Reason:** odoodev is a single-threaded CLI. No async/thread concurrency exists in current production paths. Encapsulating into a dataclass is a refactor, not a bug fix — deferred. Skipping.

---

_Fixed: 2026-05-13_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
