"""Streaming psql meta-command check for dumps (restore safety)."""

from __future__ import annotations

import subprocess

import pytest

from odoodev.core import database as db_mod
from odoodev.core.dump_check import find_psql_meta_command

CLEAN = b"""--
-- PostgreSQL database dump
--
\\restrict abc123
SET statement_timeout = 0;
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
CREATE TABLE public.t (id integer, note text);
COPY public.t (id, note) FROM stdin;
1	\\N
2	\\\\server\\share
3	back\\tslash
\\.
CREATE FUNCTION public.f() RETURNS void LANGUAGE plpgsql AS $_$
BEGIN
\\! not a command inside a dollar quote
END
$_$;
INSERT INTO public.t VALUES (4, 'multi
\\! still a string
line');
INSERT INTO public.t VALUES (5, E'it\\'s fine \\\\');
/* block
\\! comment */
-- \\! line comment
SELECT "weird
\\name";
\\connect odoo
\\unrestrict abc123
"""


def _write(tmp_path, data: bytes):
    path = tmp_path / "dump.sql"
    path.write_bytes(data)
    return str(path)


def test_clean_dump_passes(tmp_path):
    assert find_psql_meta_command(_write(tmp_path, CLEAN)) is None


def test_non_utf8_bytes_pass(tmp_path):
    data = b"COPY public.t (a) FROM stdin;\n\xff\xfe\\N\n\\.\nINSERT INTO t VALUES ('\xe9');\n"
    assert find_psql_meta_command(_write(tmp_path, data)) is None


@pytest.mark.parametrize(
    ("body", "line", "word"),
    [
        (b"SELECT 1;\n\\! touch x\n", 2, "!"),
        (b"  \\! id\n", 1, "!"),
        (b"SELECT 1 \\gexec\n", 1, "gexec"),
        (b"SELECT 1; \\! id\n", 1, "!"),
        (b"\\o |cmd\n", 1, "o"),
        (b"\\copy t from program 'x'\n", 1, "copy"),
        (b"\\i /etc/passwd\n", 1, "i"),
        (b"\\setenv A b\n", 1, "setenv"),
        (b"COPY public.t (a) FROM stdin;\n1\n\\.\n\\! id\n", 4, "!"),
        (b"\\connect db `id`\n", 1, "connect"),
        (b"\\connect db \\! id\n", 1, "connect"),
        (b"\\.\n", 1, "."),
        (b"SET standard_conforming_strings = off;\nSELECT '\\'; \\! id; --';\n", 1, "standard_conforming_strings"),
        # a COPY line that is not at a statement boundary does not open a COPY block
        (b"SELECT 1\nCOPY t FROM stdin;\n\\! id\n\\.\n", 3, "!"),
    ],
)
def test_rejected(tmp_path, body, line, word):
    assert find_psql_meta_command(_write(tmp_path, body)) == (line, word)


def test_meta_after_closed_quote_and_comment_is_rejected(tmp_path):
    body = b"SELECT 'a' /* c */ \\! id\n"
    assert find_psql_meta_command(_write(tmp_path, body)) == (1, "!")


def test_ident_dollar_is_not_a_dollar_quote(tmp_path):
    # psql lexes ``AS$$`` as an identifier, so the backslash below is live
    body = b"SELECT AS$$ \\! id\n"
    assert find_psql_meta_command(_write(tmp_path, body)) == (1, "!")


def test_large_file_streams(tmp_path):
    row = b"1\tsome data\\N\n"
    data = b"COPY public.t (a, b) FROM stdin;\n" + row * 200000 + b"\\.\n"
    assert find_psql_meta_command(_write(tmp_path, data)) is None


def test_restore_refuses_and_never_starts_psql(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("psql must not start")

    monkeypatch.setattr(subprocess, "run", boom)
    ok, errors = db_mod.restore_database_report("db", _write(tmp_path, b"SELECT 1;\n\\! id\n"), port=18432)
    assert ok is False
    assert "line 2" in errors[0]
    assert "\\!" in errors[0]
    assert "--allow-psql-meta" in errors[0]


def test_restore_opt_out_pipes_dump(tmp_path, monkeypatch):
    calls = []

    class Done:
        stderr = ""

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return Done()

    monkeypatch.setattr(db_mod, "resolve_pg_exec_mode", lambda port: db_mod.PgExecMode(db_mod.PG_EXEC_HOST))
    monkeypatch.setattr(subprocess, "run", fake_run)
    path = _write(tmp_path, b"\\! id\n")
    ok, _ = db_mod.restore_database_report("db", path, port=18432, allow_psql_meta=True)
    assert ok is True
    assert "--no-psqlrc" in calls[0]


@pytest.mark.parametrize(
    "copy_stmt",
    [
        b"COPY public.t (id, note) FROM\nstdin;\n",  # spread over two lines
        b"copy public.t FROM /* x */ stdin;\n",  # comment inside
        b"SELECT 1; COPY public.t FROM stdin;\n",  # not at the start of the line
        b"/* lead */ COPY public.t FROM stdin;\n",
    ],
)
def test_copy_in_any_other_form_is_rejected(tmp_path, copy_stmt):
    """psql would read the next lines as COPY data, the scanner as SQL.

    A lone quote in that data then opens a "string" for the scanner only and
    hides the meta-command after the terminator — so such a COPY is refused.
    """
    body = copy_stmt + b"it's data\n\\.\n\\! touch /tmp/pwned\nSELECT 'close';\n"
    result = find_psql_meta_command(_write(tmp_path, body))
    assert result is not None
    assert result[1] == "copy"


def test_copy_inside_function_body_passes(tmp_path):
    body = b"CREATE FUNCTION f() RETURNS void LANGUAGE sql AS $$\nCOPY t\nFROM '/x';\n$$;\n"
    assert find_psql_meta_command(_write(tmp_path, body)) is None
