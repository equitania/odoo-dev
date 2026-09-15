"""Module updates across many databases (``odoodev db update``).

Two concerns live here, both free of any interactive prompt so the CLI, the
``pull --update`` hand-off and the ``db.update`` playbook step share them:

1. **Update state** — after every clean ``-u all`` the HEAD commit of each
   repository in ``repos.yaml`` is recorded per database in
   ``<native_dir>/.odoodev-update-state.yaml``. Comparing that record with the
   current repository heads tells whether a database is *stale*, i.e. still
   needs an update after a pull. A database without a record is always stale.
2. **Runner** — ``run_module_update`` executes
   ``odoo-bin -c <conf> -d <db> -u <modules> --stop-after-init`` in the native
   environment, streams every output line into a log file and forwards only
   WARNING/ERROR/CRITICAL entries (plus the traceback lines that follow an
   error) to a callback. INFO/DEBUG never leave the log file.
"""

from __future__ import annotations

import copy
import hashlib
import os
import queue
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import yaml

from odoodev.tui.log_parser import parse_line

STATE_FILENAME = ".odoodev-update-state.yaml"
DEFAULT_TIMEOUT = 3600
_ISSUE_LEVELS = frozenset({"WARNING", "ERROR", "CRITICAL"})
_ERROR_LEVELS = frozenset({"ERROR", "CRITICAL"})

IssueCallback = Callable[[str, str], None]


# ---------------------------------------------------------------------------
# Update state
# ---------------------------------------------------------------------------


def update_state_path(version_cfg: Any) -> str:
    """Path of the per-environment update state file."""
    return os.path.join(version_cfg.paths.native_dir, STATE_FILENAME)


def load_update_state(path: str) -> dict[str, Any]:
    """Load the state file; a missing or malformed file is an empty state."""
    if not os.path.exists(path):
        return {"databases": {}}
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError):
        return {"databases": {}}
    if not isinstance(data, dict) or not isinstance(data.get("databases"), dict):
        return {"databases": {}}
    return data


def save_update_state(path: str, state: dict[str, Any]) -> None:
    """Persist the state file (creates the directory if needed)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(state, f, sort_keys=True, allow_unicode=True)


def record_update(
    state: dict[str, Any],
    db_name: str,
    heads: dict[str, str],
    modules: str = "all",
    when: str | None = None,
) -> None:
    """Record a clean update of ``db_name`` against the given repository heads."""
    state.setdefault("databases", {})[db_name] = {
        "updated_at": when or datetime.now().replace(microsecond=0).isoformat(),
        "modules": modules,
        "repos": dict(heads),
    }


def forget_database(state: dict[str, Any], db_name: str) -> None:
    """Drop the record of a database (e.g. after ``db drop``)."""
    state.get("databases", {}).pop(db_name, None)


def move_database_state(state: dict[str, Any], src: str, dst: str, keep_src: bool) -> None:
    """Carry a database's record to a new name (``db rename``, or ``db copy`` with ``keep_src``).

    The destination always ends up with exactly the source's record: a source
    that was never updated clears whatever stale entry the destination name had.
    """
    databases = state.setdefault("databases", {})
    entry = databases.get(src) if keep_src else databases.pop(src, None)
    if entry is None:
        databases.pop(dst, None)
    else:
        databases[dst] = copy.deepcopy(entry)


def stale_reason(state: dict[str, Any], db_name: str, heads: dict[str, str]) -> str | None:
    """Explain why a database needs an update, or ``None`` when it is current.

    A repository that vanished from ``repos.yaml`` since the last update does
    not make the database stale; a new or changed one does.
    """
    entry = state.get("databases", {}).get(db_name)
    if not entry or not isinstance(entry.get("repos"), dict):
        return "never updated"
    recorded: dict[str, str] = entry["repos"]
    changed = sorted(key for key, sha in heads.items() if recorded.get(key) != sha)
    if not changed:
        return None
    noun = "repo" if len(changed) == 1 else "repos"
    return f"{len(changed)} {noun} changed: {', '.join(changed)}"


def collect_repo_heads(repos_config: dict[str, Any], base_path: str, version_cfg: Any) -> dict[str, str]:
    """HEAD commit of the server repo and every active repo that exists on disk.

    Keys are ``"server"`` and the repo ``key`` (falling back to its path). A
    directory that is not a git repository yields ``"?"`` — it can never equal
    a recorded hash, so such an environment always counts as stale rather than
    silently passing as current.
    """
    from odoodev.commands.repos import _collect_all_repos

    heads: dict[str, str] = {}
    server_path = os.path.join(base_path, repos_config.get("server", {}).get("path", version_cfg.paths.server_subdir))
    if os.path.isdir(server_path):
        heads["server"] = _git_head(server_path)
    for repo in _collect_all_repos(repos_config):
        repo_path = repo.get("path", "")
        if not repo_path:
            continue
        full_path = os.path.join(base_path, repo_path)
        if os.path.isdir(full_path):
            heads[repo.get("key", repo_path)] = _git_head(full_path)
    return heads


def _git_head(repo_dir: str) -> str:
    """HEAD commit, suffixed with a digest of the uncommitted changes when the tree is dirty.

    A working tree with local edits is not the commit it sits on. The digest covers
    ``git status`` (new, deleted and untracked files) and ``git diff HEAD`` (a further
    edit to an already modified file), so every such change makes the database stale
    again. Edits *inside* an untracked file are not seen — adding the file is.
    """
    raw = _git_output(repo_dir, "rev-parse", "HEAD")
    sha = raw.decode("utf-8", "replace").strip() if raw else ""
    if not sha:
        return "?"
    status = _git_output(repo_dir, "status", "--porcelain", "-z", "--untracked-files=all")
    if status is None:
        return "?"
    if not status:
        return sha
    diff = _git_output(repo_dir, "diff", "HEAD", "--binary", "--no-ext-diff") or b""
    digest = hashlib.sha256(status + b"\0" + diff).hexdigest()[:12]
    return f"{sha}+dirty-{digest}"


def _git_output(repo_dir: str, *args: str) -> bytes | None:
    """stdout of a git call in ``repo_dir``; ``None`` when git fails or is missing."""
    try:
        result = subprocess.run(  # noqa: S603 — fixed git subcommands, repo_dir comes from repos.yaml
            ["git", "--no-optional-locks", *args],  # noqa: S607
            cwd=repo_dir,
            capture_output=True,
            check=True,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UpdateResult:
    """Outcome of one ``odoo-bin -u`` run on one database."""

    db_name: str
    ok: bool
    exit_code: int
    duration_s: float
    log_path: str
    warnings: int = 0
    errors: int = 0
    last_error: str | None = None
    timed_out: bool = False

    @property
    def clean(self) -> bool:
        """Exit 0 and nothing logged at ERROR/CRITICAL — the only state worth recording."""
        return self.ok and self.errors == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "database": self.db_name,
            "ok": self.ok,
            "exit_code": self.exit_code,
            "duration_s": round(self.duration_s, 1),
            "warnings": self.warnings,
            "errors": self.errors,
            "last_error": self.last_error,
            "timed_out": self.timed_out,
            "log": self.log_path,
        }


def build_update_command(db_name: str, modules: str, invocation: dict[str, Any], version: str) -> list[str]:
    """Argv for a one-shot ``odoo-bin -u`` run (mirrors ``start``'s v19 log mutes)."""
    from odoodev.commands.start import _add_v19_log_handlers

    cmd = [
        invocation["venv_python"],
        invocation["odoo_bin"],
        "-c",
        invocation["config_path"],
        "-d",
        db_name,
        "-u",
        modules,
        "--stop-after-init",
    ]
    _add_v19_log_handlers(cmd, version)
    return cmd


def format_duration(seconds: float) -> str:
    """``13s`` below a minute, ``1m 15s`` above."""
    total = round(seconds)
    if total < 60:
        return f"{total}s"
    minutes, rest = divmod(total, 60)
    return f"{minutes}m {rest}s"


def run_module_update(
    db_name: str,
    modules: str,
    invocation: dict[str, Any],
    log_path: str,
    version: str,
    on_issue: IssueCallback | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> UpdateResult:
    """Run ``odoo-bin -u <modules> --stop-after-init`` on one database.

    Every output line lands in ``log_path``. ``on_issue(level, text)`` receives
    WARNING/ERROR/CRITICAL entries as ``"<logger>: <message>"`` and, with level
    ``"RAW"``, the unstructured lines (tracebacks) that directly follow such an
    entry. Odoo runs in its own process group so a timeout can kill the whole
    tree — and so can an interruption: Ctrl+C never reaches that group from the
    terminal, so a ``KeyboardInterrupt`` (or any other exception) kills it before
    it propagates instead of leaving ``-u`` running on the database in the
    background. The Odoo process never inherits the terminal's stdin.
    """
    cmd = build_update_command(db_name, modules, invocation, version)
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    started = time.monotonic()
    warnings = errors = 0
    last_error: str | None = None
    timed_out = False
    forward_raw = False

    # Installed before odoo-bin starts: a SIGTERM between Popen and the handler
    # would otherwise end odoodev and orphan Odoo in its own session.
    restore_signals = _signals_as_interrupt()
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            log.write("# " + " ".join(cmd) + "\n")
            try:
                proc = subprocess.Popen(  # noqa: S603 — argv built from the resolved dev environment
                    cmd,
                    cwd=invocation.get("cwd"),
                    env=invocation.get("env"),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    start_new_session=True,
                )
            except OSError as exc:
                log.write(f"# failed to start: {exc}\n")
                return UpdateResult(db_name, False, 127, time.monotonic() - started, log_path, last_error=str(exc))

            deadline = started + timeout
            try:
                for line in _iter_lines(proc, deadline):
                    if line is None:
                        timed_out = True
                        _kill_group(proc)
                        break
                    log.write(line)
                    entry = parse_line(line)
                    if entry.level in _ISSUE_LEVELS:
                        text = f"{entry.logger}: {entry.message}"
                        if entry.level == "WARNING":
                            warnings += 1
                        else:
                            errors += 1
                            last_error = text
                        forward_raw = True
                        if on_issue:
                            on_issue(entry.level, text)
                    elif entry.level == "RAW":
                        if forward_raw and entry.message.strip() and on_issue:
                            on_issue("RAW", entry.message)
                    else:
                        forward_raw = False
                proc.wait()
            except BaseException:
                # A second SIGTERM (Stop, then closing the GUI) must not raise out of
                # the grace-period wait and skip the SIGKILL; `finally` restores.
                _ignore_termination_signals()
                _kill_group(proc)
                log.write("# interrupted — odoo-bin process group terminated\n")
                raise
    except OSError as exc:
        return UpdateResult(db_name, False, 1, time.monotonic() - started, log_path, last_error=str(exc))
    finally:
        restore_signals()

    duration = time.monotonic() - started
    exit_code = proc.returncode if proc.returncode is not None else 1
    if timed_out:
        last_error = f"timed out after {format_duration(timeout)}"
        exit_code = 124  # what SIGTERM left behind (-15) is an artefact of the kill, not Odoo's answer
    elif exit_code != 0 and last_error is None:
        last_error = f"exit code {exit_code} — see log"
    return UpdateResult(
        db_name=db_name,
        ok=(exit_code == 0 and not timed_out),
        exit_code=exit_code,
        duration_s=duration,
        log_path=log_path,
        warnings=warnings,
        errors=errors,
        last_error=last_error,
        timed_out=timed_out,
    )


def _iter_lines(proc: subprocess.Popen, deadline: float) -> Iterator[str | None]:
    """Yield output lines until EOF; yield ``None`` once when the deadline passes.

    A blocking ``readline`` cannot honour a timeout, so a daemon thread feeds a
    queue and the consumer waits on it with the remaining time.
    """
    q: queue.Queue[str | None] = queue.Queue()

    stdout = proc.stdout

    def _pump() -> None:
        if stdout is not None:
            for raw in stdout:
                q.put(raw)
        q.put(None)

    threading.Thread(target=_pump, daemon=True).start()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            yield None
            return
        try:
            item = q.get(timeout=remaining)
        except queue.Empty:
            yield None
            return
        if item is None:
            return
        yield item


def _signals_as_interrupt() -> Callable[[], None]:
    """Turn SIGTERM/SIGHUP into ``KeyboardInterrupt`` while an update runs; returns the undo.

    Python's default SIGTERM/SIGHUP action ends the interpreter without unwinding,
    so the cleanup that kills Odoo's process group would never run: a GUI ending
    odoodev, or a closed terminal, left ``-u all`` working on the database. As an
    exception they take the same path as Ctrl+C. SIGKILL cannot be caught — a
    caller that must stop an update sends SIGTERM first. Handlers can only be set
    from the main thread; elsewhere this is a no-op.
    """
    if threading.current_thread() is not threading.main_thread():
        return lambda: None

    def _raise(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt(f"signal {signum}")

    previous: dict[int, Any] = {}
    for name in ("SIGTERM", "SIGHUP"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            previous[signum] = signal.signal(signum, _raise)
        except (OSError, ValueError):
            continue

    def _restore() -> None:
        for signum, handler in previous.items():
            signal.signal(signum, handler)

    return _restore


def _ignore_termination_signals() -> None:
    """Ignore SIGTERM/SIGHUP while an interrupted update cleans up (main thread only).

    The caller restores the handlers ``_signals_as_interrupt`` saved.
    """
    if threading.current_thread() is not threading.main_thread():
        return
    for name in ("SIGTERM", "SIGHUP"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            signal.signal(signum, signal.SIG_IGN)
        except (OSError, ValueError):
            continue


def _kill_group(proc: subprocess.Popen) -> None:
    """SIGTERM the whole process group, SIGKILL after a grace period.

    Without process groups (``os.killpg`` is missing on Windows) the direct
    child is terminated the same way instead.
    """
    killpg = getattr(os, "killpg", None)
    if killpg is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return
    try:
        killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.wait()
