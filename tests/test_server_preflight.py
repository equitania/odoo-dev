"""Tests for the checks a server playbook is held against before its first step."""

from __future__ import annotations

import os

import pytest

from odoodev.core import server_preflight as pf
from odoodev.core.playbook import PlaybookRunner, _validate_playbook

RELEASE_MARCH = "version_info = (19, 0, 0, FINAL, 0, '-26.03.10')\n"
RELEASE_SEPT = "version_info = (19, 0, 0, FINAL, 0, '-26.09.29')\n"


@pytest.fixture
def host(monkeypatch, tmp_path):
    """A controllable stand-in for everything the preflight reads off the host."""
    state = {"release": {}, "databases": {}, "running": set()}

    monkeypatch.setattr(
        "odoodev.core.docker_exec.read_container_file",
        lambda name, path, cli="docker": state["release"].get(name),
    )
    monkeypatch.setattr(
        "odoodev.core.docker_exec.docker_container_running",
        lambda name, cli="docker": name in state["running"],
    )
    monkeypatch.setattr(
        "odoodev.core.database.database_exists",
        lambda db, host, port, user: db in state["databases"].get("live-db", set()),
    )
    state["tmp"] = tmp_path
    return state


def _config(tmp_path, **entry) -> str:
    values = {"container_name": "live-odoo", "database_name": "acme_prod", "odoo_version": "19", "active": True}
    values.update(entry)
    lines = ["defaults:", "  log_retention_days: 90", "containers:"]
    first = True
    for key, value in values.items():
        rendered = str(value).lower() if isinstance(value, bool) else f'"{value}"'
        lines.append(f"  {'- ' if first else '  '}{key}: {rendered}")
        first = False
    path = tmp_path / "docker2update.yaml"
    path.write_text("\n".join(lines) + "\n")
    return str(path)


TARGET = {"db_container": "live-db", "odoo_container": "live-odoo", "db_name": "acme_prod", "owner": "ownerp"}


def _restore(**extra) -> tuple[str, dict]:
    return "server.restore", {**TARGET, "backup_source": {"mode": "file", "path": "/nowhere.tar.zst"}, **extra}


def _rebuild(config: str, **extra) -> tuple[str, dict]:
    return "server.rebuild", {**TARGET, "config": config, **extra}


def _messages(findings, level=None) -> list[str]:
    return [f.message for f in findings if level is None or f.level == level]


class TestParseRelease:
    def test_ownerp_kernel_with_build_date(self):
        release = pf.parse_release("# header\n" + RELEASE_MARCH)
        assert release.major == "19"
        assert release.build == "26.03.10"
        assert release.build_key == (26, 3, 10)

    def test_upstream_kernel_without_build_date(self):
        release = pf.parse_release("version_info = (19, 0, 0, FINAL, 0, '')\n")
        assert release.major == "19"
        assert release.build == ""
        assert release.build_key is None

    def test_garbage_is_none(self):
        assert pf.parse_release("nothing here") is None
        assert pf.parse_release("") is None

    def test_build_comparison(self):
        assert pf.build_is_older("26.03.10", "26.09.29") is True
        assert pf.build_is_older("26.09.29", "26.09.29") is False
        assert pf.build_is_older("27.01.02", "26.09.29") is False
        # no statement without two readable dates
        assert pf.build_is_older("", "26.09.29") is None
        assert pf.build_is_older("26.03.10", "unknown") is None


class TestManifest:
    def test_round_trip_next_to_the_archive(self, tmp_path):
        backup = tmp_path / "acme_prod_live-odoo_dockerbackup_2026-09-30_10-00-00.tar.zst"
        backup.write_text("archive")
        path = pf.write_backup_manifest(str(backup), {"db_name": "acme_prod", "odoo_build": "26.09.29"})
        assert path == str(backup) + ".manifest"
        assert os.stat(path).st_mode & 0o777 == 0o600
        assert pf.read_backup_manifest(str(backup)) == {"db_name": "acme_prod", "odoo_build": "26.09.29"}

    def test_manifest_named_after_the_stem_is_found(self, tmp_path):
        # written by other backup tooling: <name>.manifest next to <name>.tar.zst
        backup = tmp_path / "acme_prod_20260929-092511.tar.zst"
        backup.write_text("archive")
        (tmp_path / "acme_prod_20260929-092511.manifest").write_text("db_name=acme_prod\nhost=a server\n")
        assert pf.read_backup_manifest(str(backup)) == {"db_name": "acme_prod", "host": "a server"}

    def test_no_manifest_is_empty(self, tmp_path):
        assert pf.read_backup_manifest(str(tmp_path / "x.tar.zst")) == {}


class TestFindUpdateEntry:
    def test_entry_found_in_nested_list(self, tmp_path):
        readable, entry = pf.find_update_entry(_config(tmp_path), "live-odoo")
        assert readable is True
        assert entry["database_name"] == "acme_prod"

    def test_container_not_defined(self, tmp_path):
        assert pf.find_update_entry(_config(tmp_path), "test-odoo") == (True, None)

    def test_missing_file_makes_no_statement(self, tmp_path):
        assert pf.find_update_entry(str(tmp_path / "nope.yaml"), "live-odoo") == (False, None)

    def test_unparseable_file_makes_no_statement(self, tmp_path):
        path = tmp_path / "broken.yaml"
        path.write_text("containers: [unclosed\n")
        assert pf.find_update_entry(str(path), "live-odoo") == (False, None)


class TestRebuildChecks:
    def test_matching_configuration_is_clean(self, host, tmp_path):
        steps = [_restore(), _rebuild(_config(tmp_path))]
        assert pf.preflight_server_steps("19", steps) == []

    def test_wrong_odoo_version_is_an_error(self, host, tmp_path):
        # Found on a customer server: a v19 release configured as odoo_version "18".
        steps = [_restore(), _rebuild(_config(tmp_path, odoo_version="18"))]
        errors = _messages(pf.preflight_server_steps("19", steps), pf.ERROR)
        assert len(errors) == 1
        assert "odoo_version '18'" in errors[0]

    def test_other_database_in_the_update_config_is_an_error(self, host, tmp_path):
        steps = [_restore(), _rebuild(_config(tmp_path, database_name="v19_live"))]
        errors = _messages(pf.preflight_server_steps("19", steps), pf.ERROR)
        assert len(errors) == 1
        assert "'v19_live'" in errors[0] and "'acme_prod'" in errors[0]

    def test_container_missing_from_the_update_config_is_an_error(self, host, tmp_path):
        steps = [_restore(), _rebuild(_config(tmp_path, container_name="other-odoo"))]
        errors = _messages(pf.preflight_server_steps("19", steps), pf.ERROR)
        assert any("not defined" in m for m in errors)

    def test_inactive_entry_is_a_warning(self, host, tmp_path):
        steps = [_restore(), _rebuild(_config(tmp_path, active=False))]
        findings = pf.preflight_server_steps("19", steps)
        assert _messages(findings, pf.ERROR) == []
        assert any("active: false" in m for m in _messages(findings, pf.WARNING))

    def test_without_the_config_file_nothing_is_claimed(self, host, tmp_path):
        steps = [_restore(), _rebuild(str(tmp_path / "missing.yaml"))]
        assert pf.preflight_server_steps("19", steps) == []


class TestRestoreChecks:
    def test_restore_without_any_update_is_a_warning(self, host):
        findings = pf.preflight_server_steps("19", [_restore()])
        assert any("never updated" in m for m in _messages(findings, pf.WARNING))

    def test_rebuild_before_the_restore_is_a_warning(self, host, tmp_path):
        steps = [_rebuild(_config(tmp_path)), _restore()]
        warnings = _messages(pf.preflight_server_steps("19", steps), pf.WARNING)
        assert any("before the restore" in m for m in warnings)

    def test_update_all_after_the_restore_counts_as_an_update(self, host):
        steps = [_restore(), ("server.update-all", dict(TARGET))]
        assert pf.preflight_server_steps("19", steps) == []

    def test_existing_database_without_backup_is_a_warning(self, host, tmp_path):
        host["running"].add("live-db")
        host["databases"]["live-db"] = {"acme_prod"}
        steps = [_restore(), _rebuild(_config(tmp_path))]
        warnings = _messages(pf.preflight_server_steps("19", steps), pf.WARNING)
        assert any("without a backup" in m for m in warnings)

    def test_existing_database_with_safety_backup_is_clean(self, host, tmp_path):
        host["running"].add("live-db")
        host["databases"]["live-db"] = {"acme_prod"}
        steps = [
            ("server.backup", {**TARGET, "backup_dir": "/opt/backups/docker", "safety": True}),
            _restore(),
            _rebuild(_config(tmp_path)),
        ]
        assert pf.preflight_server_steps("19", steps) == []

    def test_existing_database_and_drop_false_is_an_error(self, host, tmp_path):
        host["running"].add("live-db")
        host["databases"]["live-db"] = {"acme_prod"}
        steps = [_restore(drop=False), _rebuild(_config(tmp_path))]
        errors = _messages(pf.preflight_server_steps("19", steps), pf.ERROR)
        assert any("drop: false" in m for m in errors)

    def test_stopped_db_container_makes_no_statement_about_the_database(self, host, tmp_path):
        host["databases"]["live-db"] = {"acme_prod"}  # exists, but the container cannot be asked
        steps = [_restore(), _rebuild(_config(tmp_path))]
        assert pf.preflight_server_steps("19", steps) == []


class TestKernelChecks:
    def _backup(self, tmp_path, build="26.09.29") -> str:
        backup = tmp_path / "acme_prod_live-odoo_dockerbackup_2026-09-30_10-00-00.tar.zst"
        backup.write_text("archive")
        pf.write_backup_manifest(str(backup), {"db_name": "acme_prod", "odoo_build": build})
        return str(backup)

    def test_older_kernel_without_a_rebuild_is_an_error(self, host, tmp_path):
        # The case this check exists for: modules of September on a kernel of March.
        host["release"]["live-odoo"] = RELEASE_MARCH
        steps = [
            _restore(backup_source={"mode": "file", "path": self._backup(tmp_path)}),
            ("server.update-all", dict(TARGET)),
        ]
        errors = _messages(pf.preflight_server_steps("19", steps), pf.ERROR)
        assert len(errors) == 1
        assert "26.03.10" in errors[0] and "26.09.29" in errors[0]

    def test_older_kernel_with_a_rebuild_to_come_is_a_warning(self, host, tmp_path):
        host["release"]["live-odoo"] = RELEASE_MARCH
        steps = [
            _restore(backup_source={"mode": "file", "path": self._backup(tmp_path)}),
            _rebuild(_config(tmp_path)),
        ]
        findings = pf.preflight_server_steps("19", steps)
        assert _messages(findings, pf.ERROR) == []
        assert any("has to deliver a newer one" in m for m in _messages(findings, pf.WARNING))

    def test_current_kernel_is_clean(self, host, tmp_path):
        host["release"]["live-odoo"] = RELEASE_SEPT
        steps = [
            _restore(backup_source={"mode": "file", "path": self._backup(tmp_path)}),
            _rebuild(_config(tmp_path)),
        ]
        assert pf.preflight_server_steps("19", steps) == []

    def test_newest_in_dir_source_is_resolved(self, host, tmp_path):
        host["release"]["live-odoo"] = RELEASE_MARCH
        self._backup(tmp_path)
        source = {"mode": "newest_in_dir", "dir": str(tmp_path), "pattern": "*_dockerbackup_*.tar.zst"}
        steps = [_restore(backup_source=source), _rebuild(_config(tmp_path))]
        assert any("26.03.10" in m for m in _messages(pf.preflight_server_steps("19", steps)))

    def test_backup_without_manifest_makes_no_statement(self, host, tmp_path):
        host["release"]["live-odoo"] = RELEASE_MARCH
        backup = tmp_path / "plain.tar.zst"
        backup.write_text("archive")
        steps = [_restore(backup_source={"mode": "file", "path": str(backup)}), _rebuild(_config(tmp_path))]
        assert pf.preflight_server_steps("19", steps) == []

    def test_image_of_another_major_version_is_an_error(self, host):
        host["release"]["live-odoo"] = "version_info = (18, 0, 0, FINAL, 0, '-26.09.29')\n"
        steps = [_restore(), ("server.update-all", dict(TARGET))]
        errors = _messages(pf.preflight_server_steps("19", steps), pf.ERROR)
        assert any("is Odoo 18" in m for m in errors)

    def test_image_of_another_major_version_is_a_warning_when_it_is_rebuilt(self, host, tmp_path):
        host["release"]["live-odoo"] = "version_info = (18, 0, 0, FINAL, 0, '-26.09.29')\n"
        steps = [_restore(), _rebuild(_config(tmp_path))]
        findings = pf.preflight_server_steps("19", steps)
        assert _messages(findings, pf.ERROR) == []
        assert any("is Odoo 18" in m for m in _messages(findings, pf.WARNING))


class TestRunnerIntegration:
    PLAYBOOK = {
        "version": "19",
        "on_error": "stop",
        "targets": {"live": {"db_container": "live-db", "odoo_container": "live-odoo", "db_name": "acme_prod"}},
        "steps": [
            {"command": "container.stop", "args": {"target": "live", "component": "odoo"}},
            {
                "command": "server.restore",
                "args": {"target": "live", "backup_source": {"mode": "file", "path": "/nowhere.tar.zst"}},
            },
            {"command": "server.rebuild", "args": {"target": "live", "config": "__CONFIG__"}},
        ],
    }

    def _playbook(self, config: str):
        import copy

        data = copy.deepcopy(self.PLAYBOOK)
        data["steps"][2]["args"]["config"] = config
        return _validate_playbook(data)

    def test_error_stops_a_real_run_before_the_first_step(self, host, tmp_path, monkeypatch):
        called = []
        runner = PlaybookRunner()
        for command in ("container.stop", "server.restore", "server.rebuild"):
            monkeypatch.setitem(runner._handlers, command, lambda cfg, args, c=command: called.append(c))
        result = runner.execute(self._playbook(_config(tmp_path, odoo_version="18")))
        assert called == []
        assert result.status == "error"
        assert result.steps[0].command == "preflight"
        assert result.steps[0].status == "error"
        assert "odoo_version" in result.steps[0].message
        assert [s.status for s in result.steps[1:]] == ["skipped"] * 3

    def test_dry_run_reports_the_error_and_still_lists_the_steps(self, host, tmp_path):
        result = PlaybookRunner().execute(self._playbook(_config(tmp_path, odoo_version="18")), dry_run=True)
        assert result.status == "error"
        assert result.steps[0].command == "preflight"
        assert all("[dry-run]" in s.message for s in result.steps[1:])

    def test_clean_playbook_has_no_preflight_result(self, host, tmp_path):
        result = PlaybookRunner().execute(self._playbook(_config(tmp_path)), dry_run=True)
        assert [s.command for s in result.steps] == ["container.stop", "server.restore", "server.rebuild"]
        assert result.status == "ok"

    def test_warning_is_reported_and_does_not_stop(self, host, tmp_path):
        result = PlaybookRunner().execute(self._playbook(_config(tmp_path, active=False)), dry_run=True)
        assert result.steps[0].command == "preflight"
        assert result.steps[0].status == "ok"
        assert result.steps[0].details == {"errors": 0, "warnings": 1}
        assert result.status == "ok"

    def test_preflight_can_be_switched_off(self, host, tmp_path):
        result = PlaybookRunner().execute(
            self._playbook(_config(tmp_path, odoo_version="18")), dry_run=True, preflight=False
        )
        assert "preflight" not in [s.command for s in result.steps]

    def test_dev_playbooks_are_not_preflighted(self, host):
        playbook = _validate_playbook({"version": "18", "steps": [{"command": "docker.status"}]})
        result = PlaybookRunner().execute(playbook, dry_run=True)
        assert [s.command for s in result.steps] == ["docker.status"]
