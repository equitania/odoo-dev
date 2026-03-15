"""Parser for Odoo server log lines.

Odoo log format:
    2025-03-15 10:23:45,123 4567 INFO v18_exam odoo.modules.loading: Loading module eq_sale
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Compiled regex for Odoo log lines
# Groups: timestamp, pid, level, database, logger, message
_LOG_PATTERN = re.compile(
    r"^(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d+)"  # timestamp
    r"\s+(\d+)"  # pid
    r"\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)"  # level
    r"\s+(\S+)"  # database
    r"\s+(\S+?):"  # logger (non-greedy, up to colon)
    r"\s*(.*)",  # message (rest of line)
)

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL", "RAW")

# Numeric ordering for level filtering
LEVEL_ORDER: dict[str, int] = {level: i for i, level in enumerate(LOG_LEVELS)}


@dataclass(frozen=True)
class OdooLogEntry:
    """Parsed representation of a single Odoo log line."""

    timestamp: str
    pid: str
    level: str
    database: str
    logger: str
    message: str
    raw: str


def parse_line(line: str) -> OdooLogEntry:
    """Parse a single Odoo log line into an OdooLogEntry.

    Lines that don't match the expected format (tracebacks, blank lines,
    startup messages) are returned with level='RAW'.

    Args:
        line: Raw log line from Odoo stdout/stderr.

    Returns:
        Parsed OdooLogEntry with extracted fields or RAW fallback.
    """
    stripped = line.rstrip("\n\r")
    match = _LOG_PATTERN.match(stripped)
    if match:
        return OdooLogEntry(
            timestamp=match.group(1),
            pid=match.group(2),
            level=match.group(3),
            database=match.group(4),
            logger=match.group(5),
            message=match.group(6),
            raw=stripped,
        )
    return OdooLogEntry(
        timestamp="",
        pid="",
        level="RAW",
        database="",
        logger="",
        message=stripped,
        raw=stripped,
    )


def level_ge(entry_level: str, min_level: str) -> bool:
    """Check if entry_level is >= min_level in severity.

    RAW entries always pass the filter (they may contain tracebacks).

    Args:
        entry_level: Level of the log entry.
        min_level: Minimum level to display.

    Returns:
        True if the entry should be shown.
    """
    if entry_level == "RAW":
        return True
    return LEVEL_ORDER.get(entry_level, 0) >= LEVEL_ORDER.get(min_level, 0)
