---
phase: codebase
reviewed: 2026-05-13T10:35:00+02:00
depth: standard
files_reviewed: 9
files_reviewed_list:
  - odoodev/core/database.py
  - odoodev/core/git_ops.py
  - odoodev/core/venv_manager.py
  - odoodev/core/prerequisites.py
  - odoodev/core/docker_compose.py
  - odoodev/core/process_manager.py
  - odoodev/commands/start.py
  - odoodev/commands/db.py
  - odoodev/cli.py
findings:
  critical: 3
  warning: 8
  info: 3
  total: 14
status: issues_found
---

# Code Review — odoodev

**Reviewed:** 2026-05-13
**Depth:** standard
**Files Reviewed:** 9 (3 215 lines)
**Status:** issues_found

## Summary

codebase-wide review of the odoodev Click CLI tool. Focus on subprocess
safety, credential handling, file operations, and correctness.

No `shell=True` found anywhere — good. No relative imports found — good.
`print()` calls are only inside Rich console wrappers or subprocess `-c`
strings — acceptable. The main risks are: (1) a persistent SSH config file
leaking key paths across concurrent processes, (2) bare `except Exception`
swallowing actionable errors in the restore and start flows, (3) `os.chdir()`
permanently mutating process-global working directory before exec, and
(4) temp directories leaked on `os.execvpe()` in the shell-mode path.

- **Critical:** 3
- **Warning:** 8
- **Info:** 3

---

## Critical Findings

### CR-01: `os.chdir()` before `subprocess.run()` mutates global CWD permanently

**File:** `odoodev/commands/start.py:285`
**Category:** correctness / reliability
**Issue:** `_start_odoo()` calls `os.chdir(odoo_dir)` before
`subprocess.run(cmd, env=env)`. `os.chdir` mutates the process-global working
directory for the remainder of the Python process lifetime. If `subprocess.run`
raises or `sys.exit` is not reached (e.g., in test runs where `sys.exit` is
caught by the test runner), any subsequent code — including cleanup paths —
runs with a stale CWD. More critically, `os.chdir` + `subprocess.run` is
unnecessary: `subprocess.run` accepts a `cwd=` argument that is scoped to the
child process only.
**Fix:**
```python
# Replace:
os.chdir(odoo_dir)
result = subprocess.run(cmd, env=env)

# With:
result = subprocess.run(cmd, env=env, cwd=odoo_dir)
```

---

### CR-02: SSH config file `~/.ssh/odoodev_config` persists across processes and is never cleaned up

**File:** `odoodev/core/git_ops.py:63`
**Category:** security / information leak
**Issue:** `_get_ssh_config_path()` writes `~/.ssh/odoodev_config` and the
comment explicitly says "persists for the session." The file contains the
absolute path to the private SSH key. It is never removed — not on success,
not on error, not on process exit. Any process running as the same user can
read this file without any authentication. In multi-user or shared-home
environments (CI containers, VSCode Server) this leaks the SSH key path.
Additionally, `get_git_env()` is called on every `run_git_command()` invocation,
so `_get_ssh_config_path()` overwrites the same file on every git call — a
TOCTOU window between stat and open exists because `os.O_CREAT | os.O_TRUNC`
is used, not a temp-then-rename pattern.
**Fix:** Use `tempfile.NamedTemporaryFile(delete=False, dir=..., mode=0o600)`
and register an `atexit` handler (or a context manager at call-site) to delete
the file. For single-operation usage, pass the path to the caller and clean up
after the subprocess returns.
```python
import atexit, tempfile

def _get_ssh_config_path() -> str | None:
    if not _ssh_key_path:
        return None
    try:
        config_dir = os.path.join(os.path.expanduser("~"), ".ssh")
        os.makedirs(config_dir, mode=0o700, exist_ok=True)
        fd, config_path = tempfile.mkstemp(prefix="odoodev_ssh_", dir=config_dir)
        os.chmod(config_path, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(f"IdentityFile {_ssh_key_path}\n")
            f.write("IdentitiesOnly yes\n")
        atexit.register(lambda p=config_path: os.unlink(p) if os.path.exists(p) else None)
        return config_path
    except OSError:
        logger.warning("Could not create SSH config file, using direct key reference")
        return None
```

---

### CR-03: Temp directories leaked when `os.execvpe()` replaces the process in shell mode

**File:** `odoodev/commands/start.py:304-327`
**Category:** resource leak / correctness
**Issue:** `_start_interactive_shell()` creates `tmpdir` via `tempfile.mkdtemp()`
for both zsh (`.zshrc`) and bash (`.bashrc`) modes, then calls
`os.execvpe(cmd[0], cmd, env)`. `execvpe` **replaces** the current process
image; no Python `finally`, `atexit`, or context manager will ever run.
The temp directory and its credential-containing shell config file
(`source venv/bin/activate`, `export ODOO_CONF=...`) are left on disk
permanently until the user manually removes them.
**Fix:** On Linux/macOS, after writing the file, `os.unlink()` the file
immediately before `execvpe` — the shell has already opened it via the env var
or `--rcfile`. For zsh the `ZDOTDIR` approach requires the directory to exist
at exec time, so use a well-known fixed path (e.g., `~/.cache/odoodev/zshrc`)
that is overwritten on each use, instead of an ever-growing `mkdtemp`.
```python
# bash path: unlink after exec — shell already received path via --rcfile arg
# At startup the shell opens the file; it can be unlinked before exec on POSIX.
os.unlink(bashrc_path)   # file stays accessible via shell's already-open fd
os.execvpe(cmd[0], cmd, env)
```
For zsh, use a fixed path:
```python
cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "odoodev")
os.makedirs(cache_dir, mode=0o700, exist_ok=True)
zshrc = os.path.join(cache_dir, "zshrc")
# write zshrc ... then:
env["ZDOTDIR"] = cache_dir
os.execvpe("zsh", ["zsh"], env)
```

---

## Warning Findings

### WR-01: `run_git_command()` used to invoke `find` — errors silently ignored

**File:** `odoodev/core/git_ops.py:240-241`
**Issue:** Two `find` invocations (delete `.pyc` files and empty dirs) are
passed through `run_git_command()`. This function prefixes `git` — wait, it
does NOT: it takes a full command list. But the function name and all
documentation imply "git command." More importantly, both return values are
discarded. On systems where `find` is not in `PATH` or the path does not exist,
`subprocess.CalledProcessError` is caught and silently logged at ERROR level
only — the caller never knows. The `.pyc` cleanup failing is non-fatal but
masking the error is misleading. Use `subprocess.run` directly with
`check=False` and log at DEBUG.
```python
subprocess.run(
    ["find", ".", "-name", "*.pyc", "-type", "f", "-delete"],
    cwd=repo_dir, capture_output=True
)
```

---

### WR-02: `_warn_once_on_placeholder` global flag not reset between tests / subcommand invocations

**File:** `odoodev/core/database.py:20-38`
**Issue:** `_insecure_default_warned` is a module-level boolean. Once set to
`True` in a process, the warning is never shown again — even if a different
subcommand runs later in the same process with the placeholder password. In
tests using `CliRunner.invoke()` multiple times in one process the warning
will fire only once. More practically, if a user runs two odoodev subcommands
in the same shell via shell integration, the second invocation suppresses the
warning. The flag should be reset per-command invocation or the warning should
be tied to a session/context object rather than a module global.

---

### WR-03: `_write_pgpass` bare `except Exception` re-raises without logging

**File:** `odoodev/commands/start.py:201-207`
**Issue:** The bare `except Exception` block unlinks the temp file and
re-raises. If `os.fdopen(fd, "w")` raises (e.g., disk full), `fd` is already
consumed by `fdopen` and `os.unlink(tmp_path)` will succeed. But if
`os.fdopen` itself fails before the `with` block is entered, `fd` is leaked
(never closed). The safe pattern is to wrap `fd` immediately:
```python
try:
    with os.fdopen(fd, "w") as f:
        f.write(...)
    os.chmod(tmp_path, 0o600)
    os.rename(tmp_path, pgpass_path)
except Exception:
    try:
        os.close(fd)   # close if fdopen never consumed it
    except OSError:
        pass
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    raise
```
Note: `os.fdopen` consuming `fd` means a double-close is an OSError, so
catching it is necessary.

---

### WR-04: `deactivate_cloud` silently succeeds when `fetchmail_server` table does not exist

**File:** `odoodev/core/database.py:495-511`
**Issue:** `deactivate_cronjobs` runs `UPDATE fetchmail_server SET active = false WHERE active = true` and `deactivate_cloud` runs `UPDATE ir_config_parameter ... WHERE key LIKE '%nextcloud%'`. On a fresh or partially-installed database these tables may not exist and psql will return an error. `_run_psql` returns `(False, stderr)` but `deactivate_cronjobs`/`deactivate_cloud` aggregate the booleans and return a single `bool`. The callers in `db.py:292-296` discard the return value entirely — no warning is printed if post-restore deactivation fails. At minimum the caller should warn on failure; better, `_run_psql` failures for non-existent tables should be distinguished from genuine errors.
**Fix:** In `db.py` restore path:
```python
if deactivate_cron:
    if not deactivate_cronjobs(name, **params):
        print_warning("Cron deactivation failed — some tables may be missing (non-fatal)")
```

---

### WR-05: `extract_backup` uses `except Exception` that hides path-traversal re-raise logic

**File:** `odoodev/core/database.py:296-299`
**Issue:** The `except ValueError: raise` guard at line 296 correctly re-raises
path-traversal errors. But the outer `except Exception as e` at line 298 catches
**all** other exceptions including OSError from extraction failures. If a
`zipfile.BadZipFile` or `tarfile.ReadError` is raised (corrupted backup), it
is caught, logged, and `False` is returned — the caller cannot distinguish
"bad format" from "path traversal blocked" vs "disk full." Consider catching
specific exceptions rather than bare `Exception`, or at minimum logging the
exception type.

---

### WR-06: Module-global `_ssh_key_path` mutable state — not thread-safe

**File:** `odoodev/core/git_ops.py:12`
**Issue:** `_ssh_key_path` is a module-global written by `set_ssh_key()` and
read by `get_git_env()`. If two threads ever call `set_ssh_key()` concurrently
(e.g., future async refactoring, test parallelism) there is a race. Currently
odoodev is single-threaded in production, but the TUI uses Textual which runs
an asyncio event loop and may spawn threads. The state should be encapsulated
in a dataclass or passed explicitly.

---

### WR-07: `_check_services` calls `subprocess.run(["docker", "compose", "up", "-d"])` without checking return code

**File:** `odoodev/commands/start.py:545`
**Issue:** After the user confirms "Start Docker services now?", the result of
`subprocess.run(["docker", "compose", "up", "-d"], cwd=compose_cwd)` is not
checked. The code then sleeps 5 seconds and re-checks the port. If docker
fails (wrong cwd, daemon not running, compose file missing), the port check
will fail and a `SystemExit(1)` is raised — but the error message says
"PostgreSQL still not accessible" with no indication that `docker compose up`
itself failed. Check `result.returncode != 0` and print the error immediately.

---

### WR-08: `_load_env_file` does not handle quoted values — `${USER}` is only partially expanded

**File:** `odoodev/commands/start.py:90-107`
**Issue:** The `.env` parser strips quotes literally (`value = value.strip()`)
and expands only `${USER}`. If a user writes `PGPASSWORD="my password"` (with
quotes), the password stored in the dict will be `"my password"` (with literal
quotes) and the wrong value will be written to `.pgpass`. Additionally, only
`${USER}` is expanded — `${HOME}`, `$HOME`, and other common `.env` patterns
are silently left unexpanded. Either use `python-dotenv` (already a common
dep), or document that the `.env` format does not support quoting/shell
expansion.

---

## Info Findings

### IN-01: `version_cfg` typed as `object` throughout `start.py` — suppresses type checking

**File:** `odoodev/commands/start.py:244,434,524,612`
**Issue:** Multiple functions accept `version_cfg: object` and then access
attributes via `version_cfg.ports`, `version_cfg.python`, etc., all annotated
with `# type: ignore[attr-defined]`. This means mypy cannot catch attribute
typos or version mismatches on `VersionConfig`. The correct type is
`VersionConfig` from `odoodev.core.version_registry`. The `object` annotation
was presumably used to avoid a circular import, but the import can be guarded
with `TYPE_CHECKING`.
```python
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from odoodev.core.version_registry import VersionConfig
```

---

### IN-02: `detect_version_from_cwd()` only validates `isdigit()` — accepts e.g. `v0`, `v9999`

**File:** `odoodev/core/version_registry.py:306`
**Issue:** Version auto-detection accepts any directory matching `v` + `isdigit()`.
A directory named `v0` or `v9999` would produce a version string that
`get_version()` will then fail to find in the registry, raising a
`click.UsageError` at a confusing point. Consider validating against
`available_versions()` at detection time and returning `None` if not found.

---

### IN-03: `_start_interactive_shell` fish path constructs shell command via f-string with unescaped paths

**File:** `odoodev/commands/start.py:299-300`
**Issue:** The fish shell command is built as:
```python
cmd = ["fish", "-C", f"{activate}; cd '{odoo_dir}'"]
```
`odoo_dir` is a filesystem path derived from `VersionConfig`, not user input,
so injection is unlikely in practice. However, if `odoo_dir` contains a single
quote (valid in POSIX paths), the `cd '...'` argument breaks. Use
`shlex.quote(odoo_dir)` for robustness.

---

## Quick Wins

1. **`start.py:285`** — Replace `os.chdir(odoo_dir)` + `subprocess.run(cmd)` with `subprocess.run(cmd, cwd=odoo_dir)`. One-line fix, eliminates CR-01.
2. **`db.py:292-296`** — Check return values of `deactivate_cronjobs()` / `deactivate_cloud()` and print a warning on failure. Three lines.
3. **`start.py:545`** — Check `result.returncode` after `docker compose up -d`. Two lines.
4. **`git_ops.py:240-241`** — Replace `run_git_command(["find", ...])` with plain `subprocess.run`. Two lines, removes semantic confusion.
5. **`start.py:300`** — Wrap `odoo_dir` with `shlex.quote()`. One-character fix.

---

## Overall Health

The codebase is well-structured with clear separation of concerns, no `shell=True` subprocess calls, no hardcoded secrets in the meaningful sense (placeholder credentials are warned on), and path-traversal validation in ZIP/tar extraction. The three critical findings are all correctness/resource-leak issues rather than severe security vulnerabilities given the developer-tool threat model. The most impactful fix is CR-01 (`os.chdir` → `cwd=` parameter), which affects every `odoodev start` invocation. The SSH config leak (CR-02) matters most in shared CI environments. Eight warning-level findings exist, all fixable in under an hour combined.

---

_Reviewed: 2026-05-13_
_Reviewer: Claude (adversarial code review)_
_Depth: standard_
