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
"""

from __future__ import annotations

import re

# Meta-commands pg_dump itself writes into plain dumps.
ALLOWED_META_COMMANDS = frozenset({"connect", "restrict", "unrestrict"})

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

    with open(sql_file, "rb") as handle:
        for number, line in enumerate(handle, start=1):
            if in_copy:
                if line.rstrip() == b"\\.":
                    in_copy = False
                    at_start = True
                continue

            copy_candidate = state == _CODE and at_start and _COPY_START.match(line) is not None
            if b"standard_conforming_strings" in line and not _SCS_OK.match(line):
                return number, "standard_conforming_strings"

            pos = 0
            end = len(line)
            while pos < end:
                if state == _CODE:
                    match = _CODE_SPECIAL.search(line, pos)
                    chunk = line[pos:] if match is None else line[pos : match.start()]
                    if chunk.strip():
                        if at_start and not copy_candidate and _starts_with_copy(chunk):
                            return number, "copy"  # a COPY statement in any but pg_dump's one-line form
                        at_start = False
                    if match is None:
                        break
                    idx = match.start()
                    char = line[idx]
                    if char == 0x3B:  # ;
                        at_start = True
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
                    if found < 0:
                        break
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
