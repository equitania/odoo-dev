"""Tests for odoo_config and the .env parser used by repos config generation."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from odoodev.commands.repos import _parse_env_file
from odoodev.core.odoo_config import create_odoo_config


def _write_template(path: Path) -> None:
    """Write a minimal odoo conf template with the four substitutable fields."""
    path.write_text(
        "[options]\n"
        "addons_path =\n"
        "admin_passwd = CHANGE_AT_FIRST\n"
        "db_host = localhost\n"
        "db_port = 18432\n"
        "db_user = ownerp\n"
        "db_password = CHANGE_AT_FIRST\n"
        "http_port = 18069\n"
        "gevent_port = 18072\n",
        encoding="utf-8",
    )


def _read_field(conf_path: str, field: str) -> str | None:
    """Return the value of a `field = value` line from a generated conf file."""
    text = Path(conf_path).read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(field)}\s*=\s*(\S+)\s*$", text, re.MULTILINE)
    return match.group(1) if match else None


@pytest.fixture
def template(tmp_path: Path) -> Path:
    p = tmp_path / "odoo18_template.conf"
    _write_template(p)
    return p


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    d = tmp_path / "myconfs"
    d.mkdir()
    return d


def test_http_port_substituted(template: Path, out_dir: Path) -> None:
    out = create_odoo_config(
        template_path=str(template),
        config_dir=str(out_dir),
        all_paths={},
        repo_metadata={},
        http_port=99069,
    )
    assert out is not None
    assert _read_field(out, "http_port") == "99069"


def test_gevent_port_substituted(template: Path, out_dir: Path) -> None:
    out = create_odoo_config(
        template_path=str(template),
        config_dir=str(out_dir),
        all_paths={},
        repo_metadata={},
        gevent_port=99072,
    )
    assert out is not None
    assert _read_field(out, "gevent_port") == "99072"


def test_db_port_substituted(template: Path, out_dir: Path) -> None:
    out = create_odoo_config(
        template_path=str(template),
        config_dir=str(out_dir),
        all_paths={},
        repo_metadata={},
        native_db_port=99432,
    )
    assert out is not None
    assert _read_field(out, "db_port") == "99432"


def test_none_http_port_leaves_template_value(template: Path, out_dir: Path) -> None:
    out = create_odoo_config(
        template_path=str(template),
        config_dir=str(out_dir),
        all_paths={},
        repo_metadata={},
        http_port=None,
    )
    assert out is not None
    assert _read_field(out, "http_port") == "18069"


def test_none_gevent_port_leaves_template_value(template: Path, out_dir: Path) -> None:
    out = create_odoo_config(
        template_path=str(template),
        config_dir=str(out_dir),
        all_paths={},
        repo_metadata={},
        gevent_port=None,
    )
    assert out is not None
    assert _read_field(out, "gevent_port") == "18072"


def test_parse_env_file_strips_quotes(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        'DB_PORT="16432"\nODOO_PORT=\'17069\'\nGEVENT_PORT=18072\nPGPASSWORD="my\'pass"\nEMPTY=""\n',
        encoding="utf-8",
    )
    result = _parse_env_file(str(env))
    assert result["DB_PORT"] == "16432"
    assert result["ODOO_PORT"] == "17069"
    assert result["GEVENT_PORT"] == "18072"
    assert result["PGPASSWORD"] == "my'pass"
    assert result["EMPTY"] == ""
