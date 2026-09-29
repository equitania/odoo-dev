"""Tests for opt-in pgvector (PGVECTOR in .env) and the pgvector restore check.

Odoo 19+ Enterprise installs the AI module wherever the database server offers
pgvector, so the dev database keeps it off unless PGVECTOR=true. A backup of a
system that has it must not be restored silently without its AI tables.
Nothing here builds an image or talks to a real server.
"""

from __future__ import annotations

import os
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from odoodev.cli import cli
from odoodev.core import container_backend as cb
from odoodev.core.database import dump_uses_pgvector


def _vcfg(native_dir: str):
    return SimpleNamespace(
        version="19",
        postgres="17.4-alpine",
        ports=SimpleNamespace(db=19432),
        paths=SimpleNamespace(native_dir=native_dir),
    )


@pytest.fixture()
def global_cfg(monkeypatch):
    monkeypatch.setattr(
        "odoodev.core.global_config.load_global_config",
        lambda: SimpleNamespace(database=SimpleNamespace(user="u", password="p")),
    )


class TestSwitch:
    @pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on", " true "])
    def test_on(self, value):
        assert cb.pgvector_enabled({"PGVECTOR": value})

    @pytest.mark.parametrize("env", [{}, {"PGVECTOR": ""}, {"PGVECTOR": "false"}, {"PGVECTOR": "0"}])
    def test_off_by_default(self, env):
        assert not cb.pgvector_enabled(env)

    def test_spec_uses_stock_image_without_pgvector(self, tmp_path, global_cfg):
        spec = cb.build_dev_spec(_vcfg(str(tmp_path)), {})
        assert spec.image == "postgres:17.4-alpine"
        assert spec.pg_version == "17.4-alpine"

    def test_spec_uses_local_build_with_pgvector(self, tmp_path, global_cfg):
        spec = cb.build_dev_spec(_vcfg(str(tmp_path)), {"PGVECTOR": "true", "POSTGRES_VERSION": "16.11-alpine"})
        assert spec.image == "odoodev-postgres-pgvector:16.11-alpine"

    def test_dockerfile_is_shipped_and_keeps_the_base_image(self):
        # Built on postgres:<version> itself - Alpine stays Alpine, so the
        # collations of an existing data volume stay valid.
        with open(os.path.join(cb.PGVECTOR_DOCKERFILE_DIR, "Dockerfile"), encoding="utf-8") as handle:
            dockerfile = handle.read()
        assert "FROM postgres:${PG_VERSION}" in dockerfile
        assert "apk add" in dockerfile and "postgresql-${PG_MAJOR}-pgvector" in dockerfile


class TestEnsureImage:
    def _backend(self, exists):
        backend = cb.AppleContainerBackend()
        backend.image_exists = MagicMock(return_value=exists)
        backend.build_image = MagicMock(return_value=True)
        return backend

    def test_existing_image_is_not_rebuilt(self):
        backend = self._backend(exists=True)
        assert backend.ensure_pgvector_image("17.4-alpine")
        backend.build_image.assert_not_called()

    def test_missing_image_is_built_with_proxy(self, monkeypatch):
        monkeypatch.setenv("https_proxy", "http://proxy.example.com:3128")
        backend = self._backend(exists=False)
        assert backend.ensure_pgvector_image("17.4-alpine")
        image, context, args = backend.build_image.call_args.args
        assert image == "odoodev-postgres-pgvector:17.4-alpine"
        assert context == cb.PGVECTOR_DOCKERFILE_DIR
        assert args["PG_VERSION"] == "17.4-alpine"
        assert args["https_proxy"] == "http://proxy.example.com:3128"

    def test_failed_build_reports_false(self):
        backend = self._backend(exists=False)
        backend.build_image.return_value = False
        assert not backend.ensure_pgvector_image("17.4-alpine")

    def test_build_command_shape(self):
        backend = cb.DockerBackend()
        backend._run = MagicMock(return_value=SimpleNamespace(returncode=0))
        assert backend.build_image("img:1", "/ctx", {"PG_VERSION": "1"})
        backend._run.assert_called_once_with(["build", "-t", "img:1", "--build-arg", "PG_VERSION=1", "/ctx"])


class TestServiceUp:
    def test_apple_builds_before_run_and_stops_on_failure(self, tmp_path, global_cfg):
        backend = cb.AppleContainerBackend()
        backend.ensure_runtime_ready = MagicMock(return_value=True)
        backend.ensure_pgvector_image = MagicMock(return_value=False)
        backend.stop_postgres = MagicMock()
        backend.run_postgres = MagicMock()
        assert backend.service_up(_vcfg(str(tmp_path)), {"PGVECTOR": "true"}) == 1
        # The running container is not touched when the image cannot be built.
        backend.stop_postgres.assert_not_called()
        backend.run_postgres.assert_not_called()

    def test_apple_without_pgvector_builds_nothing(self, tmp_path, global_cfg):
        backend = cb.AppleContainerBackend()
        backend.ensure_runtime_ready = MagicMock(return_value=True)
        backend.ensure_pgvector_image = MagicMock()
        backend.stop_postgres = MagicMock()
        backend.run_postgres = MagicMock(return_value=SimpleNamespace(returncode=0))
        assert backend.service_up(_vcfg(str(tmp_path)), {}) == 0
        backend.ensure_pgvector_image.assert_not_called()

    def test_docker_hands_the_image_to_compose(self, tmp_path, monkeypatch):
        (tmp_path / "docker-compose.yml").write_text("image: ${POSTGRES_IMAGE:-postgres:17.4-alpine}\n")
        calls = {}
        monkeypatch.setattr(
            "odoodev.core.docker_compose.compose_up",
            lambda d, extra_env=None: calls.setdefault("env", extra_env) and 0,
        )
        backend = cb.DockerBackend()
        backend.ensure_runtime_ready = MagicMock(return_value=True)
        backend.ensure_pgvector_image = MagicMock(return_value=True)
        backend.service_up(_vcfg(str(tmp_path)), {"PGVECTOR": "true"})
        assert calls["env"] == {"POSTGRES_IMAGE": "odoodev-postgres-pgvector:17.4-alpine"}

    def test_docker_refuses_an_old_compose_file(self, tmp_path, monkeypatch):
        (tmp_path / "docker-compose.yml").write_text("image: postgres:${POSTGRES_VERSION:-17.4-alpine}\n")
        monkeypatch.setattr("odoodev.core.docker_compose.compose_up", MagicMock(return_value=0))
        backend = cb.DockerBackend()
        backend.ensure_runtime_ready = MagicMock(return_value=True)
        backend.ensure_pgvector_image = MagicMock(return_value=True)
        assert backend.service_up(_vcfg(str(tmp_path)), {"PGVECTOR": "true"}) == 1
        backend.ensure_pgvector_image.assert_not_called()


class TestTemplates:
    def test_compose_template_reads_postgres_image(self):
        path = os.path.join(os.path.dirname(cb.__file__), "..", "templates", "docker-compose.yml.j2")
        with open(path, encoding="utf-8") as handle:
            assert "${POSTGRES_IMAGE:-postgres:${POSTGRES_VERSION:-" in handle.read()

    def test_env_template_defaults_to_off(self):
        path = os.path.join(os.path.dirname(cb.__file__), "..", "templates", "env.template.j2")
        with open(path, encoding="utf-8") as handle:
            assert "\nPGVECTOR=false\n" in handle.read()


class TestDumpDetection:
    def test_detects_the_extension(self, tmp_path):
        dump = tmp_path / "dump.sql"
        dump.write_text("SET x;\nCREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;\n")
        assert dump_uses_pgvector(str(dump))

    def test_ignores_comments_and_other_extensions(self, tmp_path):
        dump = tmp_path / "dump.sql"
        dump.write_text("-- Name: vector; Type: EXTENSION\nCREATE EXTENSION IF NOT EXISTS unaccent;\n")
        assert not dump_uses_pgvector(str(dump))

    def test_missing_file(self, tmp_path):
        assert not dump_uses_pgvector(str(tmp_path / "nope.sql"))


@pytest.fixture()
def restore_env(monkeypatch, tmp_path):
    """db restore with every side effect replaced; records the call order."""
    from odoodev.commands import db as db_cmd

    cfg = types.SimpleNamespace(
        version="19",
        ports=types.SimpleNamespace(db=19432),
        paths=types.SimpleNamespace(native_dir=str(tmp_path), server_dir=str(tmp_path), myconfs_dir=str(tmp_path)),
    )
    dump = tmp_path / "dump.sql"
    dump.write_text("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA public;\n")
    state = {"calls": [], "offered": False}

    def record(name, result=True):
        def _fn(*a, **k):
            state["calls"].append(name)
            return result

        return _fn

    monkeypatch.setattr(db_cmd, "resolve_version", lambda ctx, v: "19")
    monkeypatch.setattr(db_cmd, "get_version", lambda v: cfg)
    monkeypatch.setattr(db_cmd, "_load_env_vars", lambda vc: {})
    monkeypatch.setattr(db_cmd, "_get_db_params", lambda vc, ev: {"host": "localhost", "port": 19432, "user": "u"})
    monkeypatch.setattr(db_cmd, "_ensure_pg_reachable", lambda v, p: None)
    monkeypatch.setattr(db_cmd, "_print_migration_hint", lambda v: None)
    monkeypatch.setattr(db_cmd, "_forget_update_state", lambda vc, names: None)
    monkeypatch.setattr(db_cmd, "get_restore_temp_dir", lambda b: str(tmp_path))
    monkeypatch.setattr(db_cmd, "check_restore_space", lambda b, t, f: (True, "ok", 0))
    monkeypatch.setattr(db_cmd, "get_filestore_path", lambda v, n: str(tmp_path / "fs" / n))
    monkeypatch.setattr(db_cmd, "cleanup_restore_temp", record("cleanup"))
    monkeypatch.setattr(db_cmd, "extract_backup", record("extract"))
    monkeypatch.setattr(db_cmd, "detect_backup_type", lambda p: {"sql_file": str(dump), "filestore": None})
    monkeypatch.setattr(db_cmd, "server_offers_pgvector", lambda **k: state["offered"])
    monkeypatch.setattr(db_cmd, "drop_database", record("drop"))
    monkeypatch.setattr(db_cmd, "create_database", record("create"))
    monkeypatch.setattr(db_cmd, "restore_database", record("restore"))
    monkeypatch.setattr(db_cmd, "RestorePipeline", lambda *a, **k: SimpleNamespace(run=lambda: None))
    backup = tmp_path / "backup.zip"
    backup.write_bytes(b"x")
    state["backup"] = str(backup)
    return state


def _restore(state, *extra, input=None):
    args = ["db", "restore", "19", "-n", "copy19", "-z", state["backup"], "--keep-backup", *extra]
    return CliRunner().invoke(cli, args, input=input)


class TestRestoreCheck:
    def test_drop_comes_after_extraction(self, restore_env):
        restore_env["offered"] = True
        result = _restore(restore_env, "-y")
        assert result.exit_code == 0, result.output
        calls = restore_env["calls"]
        assert calls.index("extract") < calls.index("drop") < calls.index("create")

    def test_yes_does_not_skip_the_check(self, restore_env):
        result = _restore(restore_env, "-y")
        assert result.exit_code == 1, result.output
        assert "drop" not in restore_env["calls"]
        assert "--without-pgvector" in result.output

    def test_without_pgvector_restores_anyway(self, restore_env):
        result = _restore(restore_env, "-y", "--without-pgvector")
        assert result.exit_code == 0, result.output
        assert "restore" in restore_env["calls"]

    def test_interactive_no_leaves_the_database_untouched(self, restore_env, monkeypatch):
        from odoodev.commands import db as db_cmd

        monkeypatch.setattr(db_cmd, "confirm", lambda *a, **k: False)
        result = _restore(restore_env)
        assert result.exit_code == 1, result.output
        assert "drop" not in restore_env["calls"]
        assert "cleanup" in restore_env["calls"]

    def test_server_with_pgvector_passes(self, restore_env):
        restore_env["offered"] = True
        result = _restore(restore_env, "-y")
        assert "offered by the database server" in result.output
