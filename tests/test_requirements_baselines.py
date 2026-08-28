"""Structural guards for the shipped requirements baselines."""

import pytest

from odoodev.core.example_templates import get_base_requirements_path
from odoodev.core.requirements_merge import parse_requirements

VERSIONS = ("16", "17", "18", "19")


@pytest.mark.parametrize("version", VERSIONS)
def test_baseline_parses_without_unkeyed_requirement_lines(version):
    """Every non-comment line must parse, or the merge would silently pass it through."""
    text = get_base_requirements_path(version).read_text(encoding="utf-8")
    for line in parse_requirements(text):
        stripped = line.raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert line.requirement is not None, f"v{version}: unparsed line {line.raw!r}"


@pytest.mark.parametrize("version", VERSIONS)
def test_baseline_has_no_duplicate_merge_keys(version):
    """Two entries with the same (name, marker) would make the merge ambiguous."""
    text = get_base_requirements_path(version).read_text(encoding="utf-8")
    keys = [line.requirement.merge_key for line in parse_requirements(text) if line.requirement]
    assert len(keys) == len(set(keys)), f"v{version}: duplicate merge keys"


def test_v17_keeps_both_marker_variants():
    """The six doubled v17 packages must survive curation."""
    text = get_base_requirements_path("17").read_text(encoding="utf-8")
    names = [line.requirement.key for line in parse_requirements(text) if line.requirement]
    for package in ("babel", "zeep", "gevent", "greenlet", "freezegun", "psycopg2-binary"):
        assert names.count(package) == 2, f"v17: expected two marker variants of {package}"


def test_v16_pins_werkzeug_below_3_1():
    """Odoo 16 does not import with Werkzeug 3.1.x (odoo/http.py:260)."""
    text = get_base_requirements_path("16").read_text(encoding="utf-8")
    werkzeug = [
        line.requirement for line in parse_requirements(text) if line.requirement and line.requirement.key == "werkzeug"
    ]
    assert len(werkzeug) == 1
    assert werkzeug[0].specifier == "==3.0.6"


@pytest.mark.parametrize("version", VERSIONS)
def test_baseline_carries_no_generated_header(version):
    """A baseline is a source file, never a generated one."""
    from odoodev.core.requirements_merge import is_generated

    assert not is_generated(get_base_requirements_path(version).read_text(encoding="utf-8"))
