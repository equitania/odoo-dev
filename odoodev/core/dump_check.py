"""Streaming safety check for plain SQL dumps that are piped into psql.

psql executes backslash meta-commands read from stdin (``\\! cmd``, ``\\o |cmd``,
``\\copy ... program``, ``\\i``, ``\\setenv`` ...). A dump from an untrusted backup
archive must therefore not contain any, apart from the few pg_dump emits itself.

psql only recognises a meta-command in its "initial" lexer state: never inside a
quoted string, a quoted identifier, a dollar-quoted body, a comment or COPY data.
The scanner below mirrors exactly those states, byte-wise (non-UTF-8 safe) and
line by line, so multi-GB dumps never have to fit in memory.

Where the scanner and psql could disagree, the scanner errs towards rejecting:
the COPY block is only entered for a strict, single-line ``COPY ... FROM stdin;``
at a statement boundary, and ``standard_conforming_strings`` may not be touched.
Every other statement that begins with ``COPY`` is rejected outright: psql would
switch to COPY data for it (e.g. a COPY spread over two lines) while the scanner
kept reading the data as SQL, and a lone quote in that data would then hide a
later meta-command from the scanner.

Beyond psql itself, a few SQL constructs run code on the *database server* and
never appear in a pg_dump of an Odoo database; they are refused as well:
``COPY ... FROM/TO PROGRAM`` (also inside function bodies), top-level ``DO``
blocks, ``ALTER SYSTEM`` and functions in an untrusted language (C, internal,
plpython, plperlu, pltclu, plsh). This is a filter for the known shortcuts, not
a sandbox: SQL restored by a superuser is code, and dynamic SQL built inside a
function body cannot be recognised by scanning. A backup of unknown origin
belongs on a throw-away machine first.
"""

from __future__ import annotations

import re

# Meta-commands pg_dump itself writes into a plain single-database dump. ``\connect``
# is deliberately absent: only ``pg_dump -C`` / ``pg_dumpall`` write it, and it would
# steer the rest of the restore into another database than the one being restored.
ALLOWED_META_COMMANDS = frozenset({"restrict", "unrestrict"})

_UNTRUSTED_LANGUAGES = rb"(?:C|INTERNAL|PLPYTHON[0-9A-Z_]*|PLPERLU|PLTCLU|PLSH)"
# Checked against the upper-cased code text of a statement (strings and comments removed).
_SERVER_SIDE = ((re.compile(rb"\bLANGUAGE\s+" + _UNTRUSTED_LANGUAGES + rb"(?![0-9A-Z_$])"), "LANGUAGE"),)
# COPY ... FROM/TO PROGRAM is always followed by the command as a string literal, so the
# keyword pair only counts right before an opening quote - a table named "program" does not.
_PROGRAM_PENDING = re.compile(rb"\b(?:FROM|TO)\s+PROGRAM\s*(?:E|U&)?$")
_HEAD_FORBIDDEN = (
    (re.compile(rb"^\s*DO(?![0-9A-Z_$])"), "DO"),
    (re.compile(rb"^\s*ALTER\s+SYSTEM(?![0-9A-Z_$])"), "ALTER SYSTEM"),
)
_LANGUAGE_PENDING = re.compile(rb"\bLANGUAGE\s*$")
_QUOTED_UNTRUSTED = re.compile(rb"\s*" + _UNTRUSTED_LANGUAGES + rb"\s*$")
_BODY_PROGRAM = re.compile(rb"\b(?:FROM|TO)\s+PROGRAM\s*(?:E?'|\$)", re.IGNORECASE)
_TAIL_KEEP = 96

_CODE_SPECIAL = re.compile(rb"[\\'\"$/\-;]")
_SQ_SPECIAL = re.compile(rb"'")
_ESQ_SPECIAL = re.compile(rb"[\\']")
_DQ_SPECIAL = re.compile(rb'"')
_BLOCK_SPECIAL = re.compile(rb"/\*|\*/")
_DOLLAR_TAG = re.compile(rb"\$(?:[A-Za-z_\x80-\xff][A-Za-z0-9_\x80-\xff]*)?\$")
_META_WORD = re.compile(rb"\\([A-Za-z0-9_]*)")
_IDENT_BYTES = frozenset(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_$") | frozenset(
    range(0x80, 0x100)
)
_COPY_START = re.compile(
    rb'^\s*COPY\s+(?:"[^"]*"|[A-Za-z0-9_$.\x80-\xff])+(?:\s*\([^;\\]*\))?\s+FROM\s+STDIN\s*(?:WITH\s*)?(?:\([^;\\]*\))?\s*;\s*$',
    re.IGNORECASE,
)
_SCS_OK = re.compile(rb"^\s*SET\s+standard_conforming_strings\s*(=|TO)\s*'?on'?\s*;\s*$", re.IGNORECASE)

_CODE, _SQ, _ESQ, _DQ, _DOLLAR, _BLOCK = range(6)


# SQL findings are reported in upper case, psql commands by their (lower-case) word.
_SQL_FINDINGS = {
    "COPY": "a COPY statement in a form pg_dump does not write",
    "COPY PROGRAM": "COPY ... PROGRAM, which runs a program on the database server",
    "DO": "a DO block, which runs code on the database server",
    "ALTER SYSTEM": "ALTER SYSTEM, which changes the server configuration",
    "LANGUAGE": "a function in an untrusted language (C, internal, plpython, plperlu, pltclu, plsh)",
    "SET": "a change of standard_conforming_strings, which would hide commands from this check",
}


def describe_finding(word: str) -> str:
    """Say in plain words what :func:`find_psql_meta_command` found."""
    return _SQL_FINDINGS.get(word) or f"the psql command '\\{word}'"


def _printable(word: bytes) -> str:
    """A short, safe rendering of a command word for messages."""
    return word[:24].decode("ascii", errors="replace")


def _starts_with_copy(chunk: bytes) -> bool:
    """True when the first word of ``chunk`` is the keyword COPY."""
    text = chunk.lstrip()
    return text[:4].upper() == b"COPY" and (len(text) == 4 or text[4] not in _IDENT_BYTES)


def find_psql_meta_command(sql_file: str) -> tuple[int, str] | None:
    """Return ``(line_number, command_word)`` of the first forbidden psql meta-command, else None."""
    state = _CODE
    dollar_tag = b""
    block_depth = 0
    at_start = True  # at a statement boundary (start of file or right after ';')
    in_copy = False
    head = b""  # upper-cased code text at the start of the current statement
    tail = b""  # upper-cased rolling code text, to match keywords across lines and comments
    body_carry = b""  # end of the previous line inside a dollar-quoted body

    with open(sql_file, "rb") as handle:
        for number, line in enumerate(handle, start=1):
            if in_copy:
                if line.rstrip() == b"\\.":
                    in_copy = False
                    at_start = True
                    head = tail = b""
                continue

            copy_candidate = state == _CODE and at_start and _COPY_START.match(line) is not None
            if b"standard_conforming_strings" in line and not _SCS_OK.match(line):
                return number, "SET"

            pos = 0
            end = len(line)
            while pos < end:
                if state == _CODE:
                    match = _CODE_SPECIAL.search(line, pos)
                    chunk = line[pos:] if match is None else line[pos : match.start()]
                    if chunk.strip():
                        if at_start and not copy_candidate and _starts_with_copy(chunk):
                            return number, "COPY"  # a COPY statement in any but pg_dump's one-line form
                        if at_start:
                            head = b""
                        at_start = False
                    if chunk:
                        upper = chunk.upper()
                        if len(head) < 48:
                            head += upper
                            for pattern, label in _HEAD_FORBIDDEN:
                                if pattern.match(head):
                                    return number, label
                        tail = (tail + upper)[-_TAIL_KEEP:]
                        for pattern, label in _SERVER_SIDE:
                            if pattern.search(tail):
                                return number, label
                    if match is None:
                        break
                    idx = match.start()
                    if line[idx] in b"'$" and _PROGRAM_PENDING.search(tail):
                        return number, "COPY PROGRAM"
                    if line[idx] in b"'\"" and _LANGUAGE_PENDING.search(tail):
                        # LANGUAGE 'c' / LANGUAGE "c": the name is quoted
                        close = line.find(line[idx : idx + 1], idx + 1)
                        if close > 0 and _QUOTED_UNTRUSTED.fullmatch(line[idx + 1 : close].upper()):
                            return number, "LANGUAGE"
                    if line[idx] not in b"\\;":
                        tail += b" "  # a string, comment or operator separates two words
                    char = line[idx]
                    if char == 0x3B:  # ;
                        at_start = True
                        head = tail = b""
                        pos = idx + 1
                    elif char == 0x2D:  # -
                        if line[idx + 1 : idx + 2] == b"-":
                            break  # line comment: rest of line is inert
                        at_start = False
                        pos = idx + 1
                    elif char == 0x2F:  # /
                        if line[idx + 1 : idx + 2] == b"*":
                            state, block_depth, pos = _BLOCK, 1, idx + 2
                        else:
                            at_start = False
                            pos = idx + 1
                    elif char == 0x27:  # '
                        at_start = False
                        extended = (
                            idx >= 1 and line[idx - 1] in b"Ee" and (idx < 2 or line[idx - 2] not in _IDENT_BYTES)
                        )
                        state = _ESQ if extended else _SQ
                        pos = idx + 1
                    elif char == 0x22:  # "
                        at_start = False
                        state, pos = _DQ, idx + 1
                    elif char == 0x24:  # $
                        tag = _DOLLAR_TAG.match(line, idx)
                        if tag and (idx == 0 or line[idx - 1] not in _IDENT_BYTES):
                            at_start = False
                            state, dollar_tag, pos = _DOLLAR, tag.group(), tag.end()
                        else:
                            at_start = False
                            pos = idx + 1
                    else:  # backslash: psql meta-command
                        word = _META_WORD.match(line, idx).group(1)  # type: ignore[union-attr]
                        rest = line[idx + 1 + len(word) :]
                        name = word.decode("ascii")
                        arg_ok = rest[:1] in (b"", b" ", b"\t", b"\r", b"\n")
                        if name not in ALLOWED_META_COMMANDS or not arg_ok or b"\\" in rest or b"`" in rest:
                            return number, _printable(word) or _printable(line[idx + 1 : idx + 2])
                        at_start = True
                        head = tail = b""
                        break
                elif state == _SQ:
                    match = _SQ_SPECIAL.search(line, pos)
                    if match is None:
                        break
                    state, pos = _CODE, match.end()
                elif state == _ESQ:
                    match = _ESQ_SPECIAL.search(line, pos)
                    if match is None:
                        break
                    if line[match.start()] == 0x5C:  # backslash escapes the next byte
                        pos = match.start() + 2
                    else:
                        state, pos = _CODE, match.end()
                elif state == _DQ:
                    match = _DQ_SPECIAL.search(line, pos)
                    if match is None:
                        break
                    state, pos = _CODE, match.end()
                elif state == _DOLLAR:
                    found = line.find(dollar_tag, pos)
                    body = body_carry + (line[pos:] if found < 0 else line[pos:found])
                    if _BODY_PROGRAM.search(body):
                        return number, "COPY PROGRAM"
                    if found < 0:
                        body_carry = body[-24:]
                        break
                    body_carry = b""
                    state, pos = _CODE, found + len(dollar_tag)
                else:  # _BLOCK
                    match = _BLOCK_SPECIAL.search(line, pos)
                    if match is None:
                        break
                    if match.group() == b"/*":
                        block_depth += 1
                    else:
                        block_depth -= 1
                        if block_depth == 0:
                            state = _CODE
                    pos = match.end()

            if copy_candidate and state == _CODE and at_start:
                in_copy = True
    return None
