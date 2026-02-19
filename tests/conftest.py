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


@pytest.fixture
def versions_yaml(tmp_dir):
    """Create a minimal versions.yaml for testing."""
    data = {
        "versions": {
            "18": {
                "python": "3.12",
                "postgres": "16.11-alpine",
                "ports": {"db": 15432, "odoo": 18069, "gevent": 18072, "mailpit": 18025, "smtp": 1025},
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
