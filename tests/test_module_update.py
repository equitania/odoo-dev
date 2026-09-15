"""Tests for odoodev.core.module_update — multi-database module updates."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from odoodev.core.module_update import (
    UpdateResult,
    build_update_command,
    collect_repo_heads,
    format_duration,
    load_update_state,
    record_update,
    run_module_update,
    save_update_state,
    stale_reason,
    update_state_path,
)

# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------


class TestUpdateState:
    def test_missing_file_is_empty_state(self, tmp_path):
        state = load_update_state(str(tmp_path / "missing.yaml"))
        assert state == {"databases": {}}

    def test_round_trip(self, tmp_path):
        path = str(tmp_path / "state.yaml")
        state = load_update_state(path)
        record_update(state, "v19_a", {"server": "abc", "v19-addons": "def"}, modules="all", when="2026-09-15T10:00:00")
        save_update_state(path, state)

        loaded = load_update_state(path)
        entry = loaded["databases"]["v19_a"]
        assert entry["repos"] == {"server": "abc", "v19-addons": "def"}
        assert entry["updated_at"] == "2026-09-15T10:00:00"
        assert entry["modules"] == "all"

    def test_corrupt_file_is_treated_as_empty(self, tmp_path):
        path = tmp_path / "state.yaml"
        path.write_text("- not\n- a mapping\n", encoding="utf-8")
        assert load_update_state(str(path)) == {"databases": {}}

    def test_state_path_lives_in_native_dir(self):
        class Paths:
            native_dir = "/tmp/native"

        class Cfg:
            paths = Paths()

        assert update_state_path(Cfg()) == os.path.join("/tmp/native", ".odoodev-update-state.yaml")


class TestStaleReason:
    def test_never_updated(self):
        assert stale_reason({"databases": {}}, "v19_a", {"server": "abc"}) == "never updated"

    def test_up_to_date(self):
        state = {"databases": {"v19_a": {"repos": {"server": "abc", "v19-addons": "def"}}}}
        assert stale_reason(state, "v19_a", {"server": "abc", "v19-addons": "def"}) is None

    def test_changed_repos_are_named(self):
        state = {"databases": {"v19_a": {"repos": {"server": "abc", "v19-addons": "def"}}}}
        reason = stale_reason(state, "v19_a", {"server": "abc", "v19-addons": "xyz"})
        assert reason == "1 repo changed: v19-addons"

    def test_new_repo_counts_as_change(self):
        state = {"databases": {"v19_a": {"repos": {"server": "abc"}}}}
        reason = stale_reason(state, "v19_a", {"server": "abc", "v19-oca": "111"})
        assert reason == "1 repo changed: v19-oca"

    def test_removed_repo_does_not_count(self):
        """A repo that disappeared from repos.yaml cannot make a DB stale."""
        state = {"databases": {"v19_a": {"repos": {"server": "abc", "gone": "000"}}}}
        assert stale_reason(state, "v19_a", {"server": "abc"}) is None

    def test_plural_wording(self):
        state = {"databases": {"v19_a": {"repos": {"a": "1", "b": "2", "c": "3"}}}}
        reason = stale_reason(state, "v19_a", {"a": "9", "b": "9", "c": "3"})
        assert reason == "2 repos changed: a, b"


# ---------------------------------------------------------------------------
# Repo heads
# ---------------------------------------------------------------------------


def _git_repo(path: Path) -> str:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "i"],
        cwd=path,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True
    ).stdout.strip()


class TestCollectRepoHeads:
    def test_server_and_active_repos(self, tmp_path):
        server_sha = _git_repo(tmp_path / "v19-server")
        addons_sha = _git_repo(tmp_path / "v19-addons")
        config = {
            "addons": [
                {"key": "v19-addons", "path": "v19-addons", "use": True},
                {"key": "v19-off", "path": "v19-off", "use": False},
                {"key": "v19-missing", "path": "v19-missing", "use": True},
            ]
        }

        class Paths:
            server_subdir = "v19-server"

        class Cfg:
            paths = Paths()

        heads = collect_repo_heads(config, str(tmp_path), Cfg())
        assert heads == {"server": server_sha, "v19-addons": addons_sha}

    def test_non_git_dir_yields_question_mark(self, tmp_path):
        (tmp_path / "v19-addons").mkdir()
        config = {"addons": [{"key": "v19-addons", "path": "v19-addons", "use": True}]}

        class Paths:
            server_subdir = "v19-server"

        class Cfg:
            paths = Paths()

        assert collect_repo_heads(config, str(tmp_path), Cfg()) == {"v19-addons": "?"}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _fake_odoo_bin(tmp_path: Path, body: str) -> dict:
    """Write a fake odoo-bin (python script) and return an invocation dict."""
    script = tmp_path / "odoo-bin"
    script.write_text("import sys\n" + body, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return {
        "venv_python": sys_executable(),
        "odoo_bin": str(script),
        "config_path": str(tmp_path / "odoo.conf"),
        "env": dict(os.environ),
        "cwd": str(tmp_path),
    }


def sys_executable() -> str:
    import sys

    return sys.executable


_OK_BODY = """
print("2026-09-15 10:00:00,001 1 INFO v19_a odoo.modules.loading: loading 120 modules...")
print("2026-09-15 10:00:00,002 1 WARNING v19_a odoo.addons.base: something dubious")
print("2026-09-15 10:00:00,003 1 INFO v19_a odoo.modules.loading: Modules loaded.")
sys.exit(0)
"""

_FAIL_BODY = """
print("2026-09-15 10:00:00,001 1 INFO v19_a odoo.modules.loading: loading 120 modules...")
print("2026-09-15 10:00:00,002 1 ERROR v19_a odoo.modules.registry: Failed to load registry")
print("Traceback (most recent call last):")
print('  File "x.py", line 1, in <module>')
print("ValueError: boom")
print("2026-09-15 10:00:00,003 1 INFO v19_a odoo.modules.loading: after error info line")
print("2026-09-15 10:00:00,004 1 CRITICAL v19_a odoo.service.server: Failed to initialize database `v19_a`.")
sys.exit(255)
"""

_SLEEP_BODY = """
import time
print("2026-09-15 10:00:00,001 1 INFO v19_a odoo.modules.loading: loading...", flush=True)
time.sleep(30)
"""


class TestBuildUpdateCommand:
    def test_shape(self):
        inv = {"venv_python": "/py", "odoo_bin": "/odoo-bin", "config_path": "/c.conf"}
        cmd = build_update_command("v19_a", "all", inv, version="18")
        assert cmd == ["/py", "/odoo-bin", "-c", "/c.conf", "-d", "v19_a", "-u", "all", "--stop-after-init"]

    def test_v19_mutes_rpc_deprecation(self):
        inv = {"venv_python": "/py", "odoo_bin": "/odoo-bin", "config_path": "/c.conf"}
        cmd = build_update_command("v19_a", "eq_base,eq_sale", inv, version="19")
        assert "-u" in cmd and cmd[cmd.index("-u") + 1] == "eq_base,eq_sale"
        assert any(a.startswith("--log-handler=odoo.addons.rpc.controllers.xmlrpc") for a in cmd)


class TestRunModuleUpdate:
    def test_success_forwards_only_warnings(self, tmp_path):
        inv = _fake_odoo_bin(tmp_path, _OK_BODY)
        issues: list[tuple[str, str]] = []
        log = tmp_path / "run.log"

        result = run_module_update(
            "v19_a", "all", inv, str(log), version="18", on_issue=lambda level, text: issues.append((level, text))
        )

        assert isinstance(result, UpdateResult)
        assert result.ok is True
        assert result.exit_code == 0
        assert result.warnings == 1
        assert result.errors == 0
        assert result.last_error is None
        assert issues == [("WARNING", "odoo.addons.base: something dubious")]
        # INFO lines never reach the callback but are in the log file
        assert "Modules loaded." in log.read_text(encoding="utf-8")
        assert result.log_path == str(log)

    def test_failure_forwards_errors_and_traceback(self, tmp_path):
        inv = _fake_odoo_bin(tmp_path, _FAIL_BODY)
        issues: list[tuple[str, str]] = []

        result = run_module_update(
            "v19_a",
            "all",
            inv,
            str(tmp_path / "run.log"),
            version="18",
            on_issue=lambda level, text: issues.append((level, text)),
        )

        assert result.ok is False
        assert result.exit_code == 255
        assert result.errors == 2
        assert result.warnings == 0
        levels = [lvl for lvl, _ in issues]
        assert levels == ["ERROR", "RAW", "RAW", "RAW", "CRITICAL"]
        assert issues[1][1] == "Traceback (most recent call last):"
        assert "after error info line" not in " ".join(t for _, t in issues)
        assert result.last_error == "odoo.service.server: Failed to initialize database `v19_a`."

    def test_timeout_kills_and_fails(self, tmp_path):
        inv = _fake_odoo_bin(tmp_path, _SLEEP_BODY)
        result = run_module_update("v19_a", "all", inv, str(tmp_path / "run.log"), version="18", timeout=1)
        assert result.ok is False
        assert result.timed_out is True
        assert "timed out" in (result.last_error or "")

    def test_missing_binary_is_a_failure_not_a_crash(self, tmp_path):
        inv = {
            "venv_python": str(tmp_path / "nope"),
            "odoo_bin": str(tmp_path / "odoo-bin"),
            "config_path": str(tmp_path / "c.conf"),
            "env": dict(os.environ),
            "cwd": str(tmp_path),
        }
        result = run_module_update("v19_a", "all", inv, str(tmp_path / "run.log"), version="18")
        assert result.ok is False
        assert result.last_error

    def test_log_dir_is_created(self, tmp_path):
        inv = _fake_odoo_bin(tmp_path, _OK_BODY)
        log = tmp_path / "deep" / "dir" / "run.log"
        run_module_update("v19_a", "all", inv, str(log), version="18")
        assert log.exists()


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0.4, "0s"), (12.6, "13s"), (75, "1m 15s"), (3600, "60m 0s")],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected
