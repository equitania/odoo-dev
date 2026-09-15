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
    try:
        result = subprocess.run(  # noqa: S603 — fixed argv, repo_dir comes from repos.yaml
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return "?"
    sha = result.stdout.strip()
    return sha or "?"


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
    tree. The Odoo process never inherits the terminal's stdin.
    """
    cmd = build_update_command(db_name, modules, invocation, version)
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    started = time.monotonic()
    warnings = errors = 0
    last_error: str | None = None
    timed_out = False
    forward_raw = False

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
    except OSError as exc:
        return UpdateResult(db_name, False, 1, time.monotonic() - started, log_path, last_error=str(exc))

    duration = time.monotonic() - started
    exit_code = proc.returncode if proc.returncode is not None else 1
    if timed_out:
        last_error = f"timed out after {format_duration(timeout)}"
        exit_code = exit_code or 124
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


def _kill_group(proc: subprocess.Popen) -> None:
    """SIGTERM the whole process group, SIGKILL after a grace period."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
