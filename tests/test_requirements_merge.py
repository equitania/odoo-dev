"""Tests for the pure requirements merge core."""

from odoodev.core.requirements_merge import (
    Requirement,
    canonical_name,
    extract_base_hash,
    is_generated,
    merge_requirements,
    parse_requirements,
    render_requirements,
    sha256_text,
)


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


BASE = """# baseline
Babel==2.16.0
cryptography==46.0.7          # CVE-2026-39892
Werkzeug==3.1.3
eq-chatbot-core[rag,docs]>=3.0.0
"""


def test_overlay_replaces_in_place_and_keeps_order():
    result = merge_requirements(BASE, "Werkzeug==3.0.6  # MUST stay < 3.1\n")
    body = "\n".join(result.body)
    assert body.index("Babel") < body.index("Werkzeug") < body.index("eq-chatbot-core")
    assert "Werkzeug==3.0.6" in body
    assert "3.1.3" not in body
    assert "[local]" in body


def test_baseline_comments_survive():
    result = merge_requirements(BASE, "")
    body = "\n".join(result.body)
    assert "# baseline" in body
    assert "# CVE-2026-39892" in body


def test_overlay_only_entries_land_in_additions_block():
    result = merge_requirements(BASE, "msal==1.31.0  # v16-microsoft365\n")
    body = "\n".join(result.body)
    assert "local additions" in body
    assert body.index("eq-chatbot-core") < body.index("msal")
    assert [r.name for r in result.added] == ["msal"]


def test_overlay_passthrough_lines_survive_verbatim_in_additions_block():
    local = (
        "-e ./local-pkg\ngit+https://example.invalid/x.git#egg=x\npkg @ https://example.invalid/x.whl\nmsal==1.31.0\n"
    )
    result = merge_requirements(BASE, local)
    body = "\n".join(result.body)
    assert "local additions" in body
    assert "-e ./local-pkg" in body
    assert "git+https://example.invalid/x.git#egg=x" in body
    assert "pkg @ https://example.invalid/x.whl" in body
    assert result.added_passthrough == (
        "-e ./local-pkg",
        "git+https://example.invalid/x.git#egg=x",
        "pkg @ https://example.invalid/x.whl",
    )
    assert [r.name for r in result.added] == ["msal"]


def test_overlay_passthrough_line_alone_still_opens_the_additions_block():
    result = merge_requirements(BASE, "-e ./local-pkg\n")
    body = "\n".join(result.body)
    assert "local additions" in body
    assert "-e ./local-pkg" in body
    assert result.added == ()
    assert result.added_passthrough == ("-e ./local-pkg",)


def test_overlay_blank_and_comment_lines_are_not_treated_as_passthrough():
    result = merge_requirements(BASE, "\n# just a note\n")
    assert result.added_passthrough == ()
    assert "local additions" not in "\n".join(result.body)


def test_marker_variants_are_replaced_independently():
    base = "Babel==2.10.3 ; python_version < '3.13'\nBabel==2.17.0 ; python_version >= '3.13'\n"
    result = merge_requirements(base, "Babel==2.18.0 ; python_version >= '3.13'\n")
    body = "\n".join(result.body)
    assert "Babel==2.10.3 ; python_version < '3.13'" in body
    assert "Babel==2.18.0 ; python_version >= '3.13'" in body
    assert "2.17.0" not in body
    assert result.added == ()


def test_held_back_bump_is_reported():
    result = merge_requirements(BASE, "Werkzeug==3.0.6\n")
    assert any("Werkzeug" in w and "3.0.6" in w and "3.1.3" in w for w in result.warnings)


def test_forward_pin_is_not_reported_as_held_back():
    result = merge_requirements(BASE, "Werkzeug==3.2.0\n")
    assert not any("holds" in w for w in result.warnings)


def test_unparseable_version_degrades_to_neutral_message():
    result = merge_requirements("foo==1.0.0\n", "foo==2.0.0rc1\n")
    assert any("differs" in w for w in result.warnings)
    assert not any("holds" in w for w in result.warnings)


def test_dropped_extras_are_reported():
    result = merge_requirements(BASE, "eq-chatbot-core>=3.1.0\n")
    assert any("extras" in w and "eq-chatbot-core" in w for w in result.warnings)


def test_replaced_pairs_expose_base_and_local():
    result = merge_requirements(BASE, "Werkzeug==3.0.6\n")
    base_req, local_req = result.replaced[0]
    assert base_req.specifier == "==3.1.3"
    assert local_req.specifier == "==3.0.6"


def test_empty_overlay_reproduces_baseline_body():
    result = merge_requirements(BASE, "")
    assert "\n".join(result.body).rstrip() == BASE.rstrip()
    assert result.replaced == ()
    assert result.added == ()


def test_render_emits_header_with_both_hashes():
    base, local = "Babel==2.16.0\n", "msal==1.31.0\n"
    text, _ = render_requirements(version="16", odoodev_version="0.63.0", base_text=base, local_text=local)
    lines = text.splitlines()
    assert lines[0] == "# GENERATED by odoodev 0.63.0 — do not edit."
    assert sha256_text(base) in lines[1]
    assert sha256_text(local) in lines[1]
    assert "odoodev requirements sync 16" in lines[2]


def test_render_output_is_recognised_as_generated():
    text, _ = render_requirements(version="18", odoodev_version="0.63.0", base_text="a==1\n", local_text="")
    assert is_generated(text)


def test_hand_written_file_is_not_recognised_as_generated():
    assert not is_generated("Babel==2.16.0\n# just a file\n")


def test_extract_base_hash_round_trips():
    base = "Babel==2.16.0\n"
    text, _ = render_requirements(version="19", odoodev_version="0.63.0", base_text=base, local_text="")
    assert extract_base_hash(text) == sha256_text(base)


def test_extract_base_hash_returns_none_for_plain_file():
    assert extract_base_hash("Babel==2.16.0\n") is None


def test_render_returns_the_merge_result():
    _, result = render_requirements(
        version="16", odoodev_version="0.63.0", base_text="Werkzeug==3.1.3\n", local_text="Werkzeug==3.0.6\n"
    )
    assert result.warnings
    assert len(result.replaced) == 1


def test_render_ends_with_single_newline():
    text, _ = render_requirements(version="16", odoodev_version="0.63.0", base_text="a==1\n", local_text="")
    assert text.endswith("\n")
    assert not text.endswith("\n\n")


def test_a_marked_overlay_entry_replaces_an_unmarked_baseline_pin():
    """A marker mismatch must not turn one package into two conflicting pins.

    The v18 baseline pins python-ldap without a marker while the machine's
    hand-maintained file carried `; sys_platform != 'win32'`. Matching on
    (name, marker) alone treated that as a package the baseline does not know,
    so both lines were emitted and uv refused: "you require python-ldap==3.4.5
    and python-ldap{sys_platform != 'win32'}==3.4.4".
    """
    result = merge_requirements(
        "python-ldap==3.4.5\n",
        "python-ldap==3.4.4 ; sys_platform != 'win32'\n",
    )
    body = "\n".join(result.body)
    assert "3.4.5" not in body
    assert "3.4.4" in body
    assert body.count("python-ldap") == 1


def test_an_exact_marker_match_still_leaves_the_other_baseline_pin_alone():
    """The v17 pairs stay individually addressable — that is why marker is in the key."""
    base = "greenlet==3.1.1 ; python_version >= '3.12'\ngreenlet==2.0.2 ; python_version < '3.12'\n"
    result = merge_requirements(base, "greenlet==3.2.0 ; python_version >= '3.12'\n")
    body = "\n".join(result.body)
    assert "3.2.0" in body
    assert "2.0.2" in body
    assert "3.1.1" not in body


def test_an_unmarked_overlay_entry_collapses_every_baseline_pin_of_that_package():
    """ "I want this version" replaces the whole set, rather than duplicating it."""
    base = "greenlet==3.1.1 ; python_version >= '3.12'\ngreenlet==2.0.2 ; python_version < '3.12'\n"
    result = merge_requirements(base, "greenlet==3.2.0\n")
    body = "\n".join(result.body)
    assert body.count("greenlet") == 1
    assert "3.2.0" in body


def test_two_different_markers_stay_side_by_side():
    """Complementary markers are not a conflict — collapsing them drops a platform.

    The baseline covers `python_version < '3.13'`, the overlay adds the other
    half. Both lines must survive; only an unmarked entry, which applies
    everywhere, genuinely overlaps.
    """
    result = merge_requirements(
        "Babel==2.10.3 ; python_version < '3.13'\n",
        "Babel==2.17.0 ; python_version >= '3.13'\n",
    )
    body = "\n".join(result.body)
    assert "2.10.3" in body
    assert "2.17.0" in body
