"""Scrollable log viewer widget with level filtering and search."""

from __future__ import annotations

from collections import deque

from rich.text import Text
from textual.reactive import reactive
from textual.selection import Selection
from textual.widget import Widget
from textual.widgets import RichLog

from odoodev.tui.log_parser import OdooLogEntry, parse_line

# Color mapping for log levels
LEVEL_STYLES: dict[str, str] = {
    "CRITICAL": "bold red reverse",
    "ERROR": "bold red",
    "WARNING": "yellow",
    "INFO": "",
    "DEBUG": "dim",
    "RAW": "dim italic",
}

# All filterable levels (non-RAW). RAW lines inherit the previous entry's level.
FILTERABLE_LEVELS: frozenset[str] = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

# Default fallback when a RAW line appears before any structured log entry
DEFAULT_RAW_LEVEL = "INFO"

MAX_BUFFER_SIZE = 10_000


class SelectableRichLog(RichLog):
    """RichLog subclass with working mouse text selection.

    The base RichLog inherits get_selection() from Widget, which calls
    self._render(). For ScrollView this returns a debug Panel, so selection
    always returns None. This subclass overrides get_selection() to extract
    plain text directly from the internal Strip line buffer.
    """

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        """Extract selected text from the Strip-based line buffer.

        Args:
            selection: Selection coordinates from the screen's mouse tracking.

        Returns:
            Tuple of (extracted_text, line_ending) or None if no text available.
        """
        if not self.lines:
            return None
        plain_lines = []
        for strip in self.lines:
            plain_lines.append("".join(seg.text for seg in strip if seg.text))
        full_text = "\n".join(plain_lines)
        extracted = selection.extract(full_text)
        if not extracted:
            return None
        return extracted, "\n"


class LogViewer(Widget):
    """Log viewer with multi-toggle level filtering, search highlighting, and auto-scroll.

    Wraps a RichLog widget with an internal buffer of (entry, effective_level)
    tuples. Each level can be independently enabled or disabled. RAW lines
    (tracebacks, stdout) inherit the level of the preceding structured log
    entry, so a traceback after an ERROR is shown together with that ERROR.
    """

    DEFAULT_CSS = """
    LogViewer {
        height: 1fr;
    }
    """

    active_levels: reactive[frozenset[str]] = reactive(FILTERABLE_LEVELS)
    search_term: reactive[str] = reactive("")
    auto_scroll: reactive[bool] = reactive(True)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # Buffer stores parsed entries with their effective filter level.
        # For non-RAW entries, effective_level == entry.level.
        # For RAW entries, effective_level inherits the previous structured level.
        self._buffer: deque[tuple[OdooLogEntry, str]] = deque(maxlen=MAX_BUFFER_SIZE)
        self._last_real_level: str = DEFAULT_RAW_LEVEL
        self._rich_log: SelectableRichLog | None = None

    def compose(self):
        """Create the selectable RichLog widget."""
        yield SelectableRichLog(highlight=False, markup=False, wrap=True, id="log-output")

    def on_mount(self) -> None:
        """Get reference to the RichLog after mounting."""
        self._rich_log = self.query_one("#log-output", SelectableRichLog)

    def write_line(self, line: str) -> None:
        """Parse and display a raw log line.

        Tracks the last structured log level so RAW continuation lines
        (tracebacks, stack traces, plain stdout) are filtered alongside
        their triggering log entry.

        Args:
            line: Raw log line from Odoo stdout/stderr.
        """
        entry = parse_line(line)
        if entry.level == "RAW":
            effective_level = self._last_real_level
        else:
            effective_level = entry.level
            self._last_real_level = entry.level

        self._buffer.append((entry, effective_level))

        if self._should_show(entry, effective_level):
            self._render_entry(entry)

    def _should_show(self, entry: OdooLogEntry, effective_level: str) -> bool:
        """Check if an entry passes the current filter."""
        if effective_level not in self.active_levels:
            return False
        if self.search_term and self.search_term.lower() not in entry.raw.lower():
            return False
        return True

    def _render_entry(self, entry: OdooLogEntry) -> None:
        """Render a single entry to the RichLog."""
        if self._rich_log is None:
            return

        style = LEVEL_STYLES.get(entry.level, "")
        text = Text(entry.raw)
        if style:
            text.stylize(style)

        # Highlight search term if active
        if self.search_term:
            text.highlight_words([self.search_term], style="bold reverse green")

        self._rich_log.write(text, scroll_end=self.auto_scroll)

    def _rebuild_display(self) -> None:
        """Clear and redisplay all buffered entries matching current filter."""
        if self._rich_log is None:
            return
        self._rich_log.clear()
        for entry, effective_level in self._buffer:
            if self._should_show(entry, effective_level):
                self._render_entry(entry)

    def watch_active_levels(self) -> None:
        """React to filter set changes."""
        self._rebuild_display()

    def watch_search_term(self) -> None:
        """React to search term changes."""
        self._rebuild_display()

    def toggle_level(self, level: str) -> None:
        """Toggle a single level on/off.

        Args:
            level: Level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        """
        if level not in FILTERABLE_LEVELS:
            return
        if level in self.active_levels:
            self.active_levels = self.active_levels - {level}
        else:
            self.active_levels = self.active_levels | {level}

    def is_level_active(self, level: str) -> bool:
        """Check if a level is currently shown."""
        return level in self.active_levels

    def show_all_levels(self) -> None:
        """Activate all levels (default state)."""
        self.active_levels = FILTERABLE_LEVELS

    def show_issues_only(self) -> None:
        """Show only WARNING, ERROR, and CRITICAL levels."""
        self.active_levels = frozenset({"WARNING", "ERROR", "CRITICAL"})

    def clear_log(self) -> None:
        """Clear the display (buffer is preserved)."""
        if self._rich_log is not None:
            self._rich_log.clear()

    def clear_all(self) -> None:
        """Clear both display and buffer."""
        self._buffer.clear()
        self._last_real_level = DEFAULT_RAW_LEVEL
        if self._rich_log is not None:
            self._rich_log.clear()

    @property
    def entry_count(self) -> int:
        """Total number of entries in the buffer."""
        return len(self._buffer)

    @property
    def visible_count(self) -> int:
        """Number of entries passing the current filter."""
        return sum(1 for entry, eff in self._buffer if self._should_show(entry, eff))

    def get_visible_text(self) -> str:
        """Return all currently visible log lines as plain text."""
        return "\n".join(entry.raw for entry, eff in self._buffer if self._should_show(entry, eff))

    def _collect_with_tracebacks(self, trigger_levels: set[str]) -> str:
        """Collect log lines at trigger levels including their traceback continuation.

        RAW lines (tracebacks, stack traces) following a triggered log entry
        are included until the next structured log line appears.

        Args:
            trigger_levels: Set of log levels that start a collection block.

        Returns:
            Collected lines as plain text.
        """
        lines: list[str] = []
        collecting = False
        for entry, _eff in self._buffer:
            if entry.level in trigger_levels:
                collecting = True
                lines.append(entry.raw)
            elif entry.level == "RAW" and collecting:
                lines.append(entry.raw)
            else:
                collecting = False
        return "\n".join(lines)

    def get_errors_text(self) -> str:
        """Return ERROR/CRITICAL log lines with their tracebacks."""
        return self._collect_with_tracebacks({"ERROR", "CRITICAL"})

    def get_warnings_and_errors_text(self) -> str:
        """Return WARNING/ERROR/CRITICAL log lines with their tracebacks."""
        return self._collect_with_tracebacks({"WARNING", "ERROR", "CRITICAL"})
