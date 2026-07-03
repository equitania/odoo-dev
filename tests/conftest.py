"""Shared test fixtures for odoodev tests."""

import tempfile
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def tmp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture(autouse=True)
def _isolate_migration_config(monkeypatch, tmp_path):
    """Keep every test independent of the developer machine's real migration.yaml.

    Since DB-port resolution consults the active migration group (resolve_db_port),
    an active migration in ~/.config/odoodev/ would silently change ports in
    unrelated tests. Points the config path at an empty tmp location and clears
    the module cache around each test. Migration tests re-patch the path locally.
    """
    from odoodev.core.migration_config import clear_migration_cache

    clear_migration_cache()
    monkeypatch.setattr(
        "odoodev.core.migration_config.get_migration_config_path",
        lambda: tmp_path / "migration.yaml",
    )
    yield
    clear_migration_cache()


@pytest.fixture(autouse=True)
def _force_host_pg_tools(monkeypatch):
    """Default every test to host-mode psql/pg_dump resolution.

    Fakes presence of "psql"/"pg_dump" only (all other tool names delegate to
    the real shutil.which) so unrelated zstd/7z presence tests stay unaffected.
    Keeps the pre-fallback command shapes deterministic regardless of whether
    the machine running the tests has PostgreSQL client tools installed.
    Tests exercising the container exec fallback override this locally.
    """
    import shutil as _shutil

    real_which = _shutil.which

    def _fake_which(name, *args, **kwargs):
        if name in ("psql", "pg_dump"):
            return f"/usr/bin/{name}"
        return real_which(name, *args, **kwargs)

    monkeypatch.setattr("odoodev.core.database.shutil.which", _fake_which)
    monkeypatch.delenv("ODOODEV_PG_EXEC", raising=False)

    from odoodev.core.database import clear_pg_exec_cache

    clear_pg_exec_cache()
    yield
    clear_pg_exec_cache()


@pytest.fixture
def versions_yaml(tmp_dir):
    """Create a minimal versions.yaml for testing."""
    data = {
        "versions": {
            "18": {
                "python": "3.13",
                "postgres": "16.11-alpine",
                "ports": {"db": 18432, "odoo": 18069, "gevent": 18072, "mailpit": 18025, "smtp": 1025},
                "paths": {
                    "base": f"{tmp_dir}/gitbase/v18",
                    "server_subdir": "v18-server",
                    "dev_subdir": "v18-dev",
                    "native_subdir": "dev18_native",
                    "conf_subdir": "conf",
                },
                "git": {
                    "server_url": "git@example.com:v18/v18-server.git",
                    "branch": "develop",
                },
            },
            "19": {
                "python": "3.13",
                "postgres": "17.4-alpine",
                "ports": {"db": 19432, "odoo": 19069, "gevent": 19072, "mailpit": 19025, "smtp": 1925},
                "paths": {
                    "base": f"{tmp_dir}/gitbase/v19",
                    "server_subdir": "v19-server",
                    "dev_subdir": "v19-dev",
                    "native_subdir": "dev19_native",
                    "conf_subdir": "conf",
                },
                "git": {
                    "server_url": "git@example.com:v19/v19-server.git",
                    "branch": "develop",
                },
            },
        }
    }
    path = Path(tmp_dir) / "versions.yaml"
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path
