"""Tests for odoodev.core.server_inventory — what the server's own configuration already says."""

from __future__ import annotations

import os

from odoodev.core import server_inventory as inv

UPDATE_YAML = """\
defaults:
  log_retention_days: 90
containers:
  - active: false
    container_name: "test-odoo"
    database_name: "test_db"
    db_user: "ownerp"
    db_password: "secret"
    db_host: "test-db"
    volume: "--network test-db-net -v /opt/odoo/test:/opt/odoo/data"
    odoo_version: "19"
  - active: true
    container_name: "live-odoo"
    database_name: "acme_prod"
    db_user: "odoo"
    db_password: "secret"
    db_host: "live-db"
    volume: "--network live-db-net -v /opt/fonts:/usr/share/fonts:ro -v /opt/odoo/live:/opt/odoo/data"
    odoo_version: "19"
  - active: true
    container_name: "half-configured"
    database_name: ""
    db_host: "x-db"
"""


def _write(tmp_path, name, content) -> str:
    path = tmp_path / name
    path.write_text(content)
    return str(path)


class TestLoadInstances:
    def test_active_instances_come_first(self, tmp_path):
        instances = inv.load_instances(_write(tmp_path, "docker2update.yaml", UPDATE_YAML))
        assert [i.container for i in instances] == ["live-odoo", "test-odoo"]
        assert [i.active for i in instances] == [True, False]

    def test_everything_a_target_needs_is_read(self, tmp_path):
        live = inv.load_instances(_write(tmp_path, "docker2update.yaml", UPDATE_YAML))[0]
        assert live.as_target() == {
            "db_container": "live-db",
            "db_name": "acme_prod",
            "odoo_container": "live-odoo",
            "owner": "odoo",
            "data_dir": "/opt/odoo/live",
        }
        assert live.odoo_version == "19"
        assert live.target_name == "live"

    def test_entry_without_database_is_not_offered(self, tmp_path):
        instances = inv.load_instances(_write(tmp_path, "docker2update.yaml", UPDATE_YAML))
        assert "half-configured" not in [i.container for i in instances]

    def test_password_is_never_carried(self, tmp_path):
        live = inv.load_instances(_write(tmp_path, "docker2update.yaml", UPDATE_YAML))[0]
        assert "secret" not in repr(live)

    def test_missing_file_is_empty(self, tmp_path):
        assert inv.load_instances(str(tmp_path / "nope.yaml")) == []

    def test_unparseable_file_is_empty(self, tmp_path):
        assert inv.load_instances(_write(tmp_path, "broken.yaml", "containers: [unclosed\n")) == []

    def test_target_name_without_odoo_suffix(self):
        assert inv.Instance("erp", "db", "pg").target_name == "erp"
        assert inv.Instance("-odoo", "db", "pg").target_name == "-odoo"


class TestDataDirFromVolume:
    def test_only_the_data_mount_counts(self):
        volume = "--network n -v /opt/fonts:/usr/share/fonts -v /opt/odoo/live:/opt/odoo/data:rw"
        assert inv.data_dir_from_volume(volume) == "/opt/odoo/live"

    def test_long_option_form(self):
        assert inv.data_dir_from_volume("--volume=/srv/odoo:/opt/odoo/data") == "/srv/odoo"

    def test_named_volume_is_left_to_docker_inspect(self):
        assert inv.data_dir_from_volume("-v vol-odoo-live:/opt/odoo/data") == ""

    def test_no_data_mount(self):
        assert inv.data_dir_from_volume("--network live-db-net") == ""
        assert inv.data_dir_from_volume("") == ""


class TestBackupDirectory:
    def test_database_archives_live_in_the_docker_subfolder(self, tmp_path):
        path = _write(tmp_path, "container2backup.yaml", "defaults:\n  backup_path: /srv/backups\n")
        assert inv.backup_directory(path) == "/srv/backups/docker"
        assert inv.default_backup_dir(path) == "/srv/backups/docker"

    def test_unconfigured_falls_back_to_the_convention(self, tmp_path):
        assert inv.backup_directory(str(tmp_path / "nope.yaml")) == ""
        assert inv.default_backup_dir(str(tmp_path / "nope.yaml")) == "/opt/backups/docker"

    def test_file_without_backup_path(self, tmp_path):
        assert inv.backup_directory(_write(tmp_path, "c.yaml", "defaults:\n  retention_days: 14\n")) == ""
        assert inv.backup_directory(_write(tmp_path, "d.yaml", "- just\n- a list\n")) == ""


class TestListBackups:
    def test_newest_first_archives_only(self, tmp_path):
        for index, name in enumerate(("old.tar.zst", "mid.zip", "new.tar.zst", "notes.txt", "x.manifest")):
            path = tmp_path / name
            path.write_text("x" * (index + 1))
            os.utime(path, (1_000_000 + index, 1_000_000 + index))
        (tmp_path / "folder.tar.zst").mkdir()
        found = inv.list_backups(str(tmp_path))
        assert [os.path.basename(b.path) for b in found] == ["new.tar.zst", "mid.zip", "old.tar.zst"]
        assert found[0].size == 3

    def test_limit(self, tmp_path):
        for index in range(5):
            path = tmp_path / f"b{index}.tar.zst"
            path.write_text("x")
            os.utime(path, (1_000_000 + index, 1_000_000 + index))
        assert [os.path.basename(b.path) for b in inv.list_backups(str(tmp_path), limit=2)] == [
            "b4.tar.zst",
            "b3.tar.zst",
        ]

    def test_missing_directory_is_empty(self, tmp_path):
        assert inv.list_backups(str(tmp_path / "nope")) == []


def test_format_size():
    assert inv.format_size(512) == "512 B"
    assert inv.format_size(2048) == "2.0 KB"
    assert inv.format_size(9028428100) == "8.4 GB"
    assert inv.format_size(5 * 1024**4) == "5120.0 GB"
