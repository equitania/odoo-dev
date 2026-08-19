"""Tests for odoo_config and the .env parser used by repos config generation."""

from __future__ import annotations

import configparser
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


def _addons_paths(conf_path: str) -> list[str]:
    """Return addons_path exactly as Odoo parses it: configparser, then split on ','."""
    parser = configparser.ConfigParser()
    parser.read(conf_path, encoding="utf-8")
    raw = parser["options"]["addons_path"]
    return [part.strip() for part in raw.split(",") if part.strip()]


def _generate(template: Path, out_dir: Path) -> str:
    """Generate a config whose addons_path holds exactly two known paths."""
    out = create_odoo_config(
        template_path=str(template),
        config_dir=str(out_dir),
        all_paths={"base": ["/srv/odoo/addons"], "eq": ["/srv/eq-addons"]},
        repo_metadata={"eq": {"section": "Equitania", "use": True}},
    )
    assert out is not None
    return out


class TestAddonsPathReplacement:
    """The addons_path value must be replaced whole, never appended to.

    An INI value covers the key line plus every indented continuation line.
    When only part of it was replaced, the old paths survived and the new block
    was prepended, so Odoo saw the paths twice — and where an inline value met
    the block, two paths ended up glued across a newline. Odoo splits
    addons_path on ',' alone, so such an entry becomes one unusable path and
    every lookup through it fails silently.
    """

    def test_empty_value_is_filled(self, template: Path, out_dir: Path) -> None:
        paths = _addons_paths(_generate(template, out_dir))
        assert paths == ["/srv/odoo/addons", "/srv/eq-addons"]

    def test_inline_value_is_replaced_not_kept(self, tmp_path: Path, out_dir: Path) -> None:
        tpl = tmp_path / "inline.conf"
        tpl.write_text(
            "[options]\naddons_path = /stale/one,/stale/two\nadmin_passwd = keep\ndb_port = 18432\n",
            encoding="utf-8",
        )
        out = _generate(tpl, out_dir)
        paths = _addons_paths(out)
        assert paths == ["/srv/odoo/addons", "/srv/eq-addons"]
        assert "/stale/" not in Path(out).read_text(encoding="utf-8")

    def test_existing_block_is_replaced_not_prepended(self, tmp_path: Path, out_dir: Path) -> None:
        tpl = tmp_path / "block.conf"
        tpl.write_text(
            "[options]\n"
            "addons_path =\n"
            "    # Generated on 2020-01-01 00:00:00\n"
            "    /stale/one,\n"
            "    # Customer\n"
            "    /stale/two,\n"
            "admin_passwd = keep\n"
            "db_port = 18432\n",
            encoding="utf-8",
        )
        out = _generate(tpl, out_dir)
        assert _addons_paths(out) == ["/srv/odoo/addons", "/srv/eq-addons"]
        assert "/stale/" not in Path(out).read_text(encoding="utf-8")

    def test_inline_value_plus_block_leaves_no_glued_path(self, tmp_path: Path, out_dir: Path) -> None:
        """The v16 breakage: an inline value directly followed by a generated block."""
        tpl = tmp_path / "mixed.conf"
        tpl.write_text(
            "[options]\n"
            "addons_path = /stale/one,/stale/two\n"
            "    # Generated on 2020-01-01 00:00:00\n"
            "    /stale/one,\n"
            "    /stale/two,\n"
            "admin_passwd = keep\n"
            "db_port = 18432\n",
            encoding="utf-8",
        )
        paths = _addons_paths(_generate(tpl, out_dir))
        assert paths == ["/srv/odoo/addons", "/srv/eq-addons"]
        assert not [p for p in paths if "\n" in p], "two paths glued across a newline"

    def test_following_keys_survive(self, tmp_path: Path, out_dir: Path) -> None:
        """The old pattern consumed everything up to the next '[' — keys must not vanish."""
        tpl = tmp_path / "keys.conf"
        tpl.write_text(
            "[options]\naddons_path =\n    /stale/one,\nadmin_passwd = keep\ndb_port = 18432\nhttp_port = 18069\n",
            encoding="utf-8",
        )
        out = _generate(tpl, out_dir)
        assert _read_field(out, "admin_passwd") == "keep"
        assert _read_field(out, "http_port") == "18069"

    def test_generation_is_idempotent(self, template: Path, out_dir: Path) -> None:
        """Feeding a generated config back in must not accumulate paths."""
        first = _generate(template, out_dir)
        second = _generate(Path(first), out_dir)
        assert _addons_paths(second) == _addons_paths(first)
