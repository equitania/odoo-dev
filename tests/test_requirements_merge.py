"""Tests for the pure requirements merge core."""

from odoodev.core.requirements_merge import Requirement, canonical_name, parse_requirements


def test_canonical_name_normalises_case_and_separators():
    assert canonical_name("Werkzeug") == "werkzeug"
    assert canonical_name("psycopg2_binary") == "psycopg2-binary"
    assert canonical_name("psycopg2-binary") == "psycopg2-binary"
    assert canonical_name("zope.interface") == "zope-interface"


def test_parse_simple_pin():
    lines = parse_requirements("Werkzeug==3.0.6\n")
    assert len(lines) == 1
    req = lines[0].requirement
    assert req == Requirement(name="Werkzeug", key="werkzeug", extras=(), specifier="==3.0.6", marker="", comment="")


def test_parse_keeps_trailing_comment_and_marker():
    lines = parse_requirements("gevent==24.11.1 ; sys_platform != 'win32'  # (Trixie)\n")
    req = lines[0].requirement
    assert req.specifier == "==24.11.1"
    assert req.marker == "sys_platform != 'win32'"
    assert req.comment == "(Trixie)"


def test_parse_normalises_marker_quotes_and_whitespace():
    a = parse_requirements('Babel==2.17.0 ; python_version >= "3.13"\n')[0].requirement
    b = parse_requirements("Babel==2.17.0 ;python_version    >=    '3.13'\n")[0].requirement
    assert a.marker == b.marker == "python_version >= '3.13'"


def test_parse_handles_unpinned_and_range_pins():
    lines = parse_requirements("pytz\nPyYAML>=6.0.1,<7.0.0\n")
    assert lines[0].requirement.specifier == ""
    assert lines[1].requirement.specifier == ">=6.0.1,<7.0.0"


def test_parse_extracts_extras_sorted():
    req = parse_requirements("eq-chatbot-core[rag,security,docs]>=3.0.0\n")[0].requirement
    assert req.extras == ("docs", "rag", "security")
    assert req.specifier == ">=3.0.0"


def test_comment_and_blank_lines_carry_no_requirement():
    lines = parse_requirements("# a note\n\nBabel==2.16.0\n")
    assert lines[0].requirement is None
    assert lines[1].requirement is None
    assert lines[2].requirement is not None
    assert lines[0].raw == "# a note"


def test_passthrough_forms_are_not_keyed():
    lines = parse_requirements("-r other.txt\ngit+https://example.invalid/x.git#egg=x\n")
    assert all(line.requirement is None for line in lines)


def test_merge_key_pairs_name_and_marker():
    reqs = [
        line.requirement
        for line in parse_requirements(
            "Babel==2.10.3 ; python_version < '3.13'\nBabel==2.17.0 ; python_version >= '3.13'\n"
        )
    ]
    assert reqs[0].merge_key != reqs[1].merge_key
    assert reqs[0].merge_key == ("babel", "python_version < '3.13'")


def test_to_line_round_trips():
    text = "eq-chatbot-core[docs,rag]>=3.0.0 ; python_version >= '3.13'"
    req = parse_requirements(text + "\n")[0].requirement
    assert req.to_line() == "eq-chatbot-core[docs,rag]>=3.0.0 ; python_version >= '3.13'"
