"""Scrollable log viewer widget with level filtering and search."""

from __future__ import annotations

from collections import deque

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import RichLog

from odoodev.tui.log_parser import OdooLogEntry, level_ge, parse_line

# Color mapping for log levels
LEVEL_STYLES: dict[str, str] = {
    "CRITICAL": "bold red reverse",
    "ERROR": "bold red",
    "WARNING": "yellow",
    "INFO": "",
    "DEBUG": "dim",
    "RAW": "dim italic",
}

MAX_BUFFER_SIZE = 10_000


class LogViewer(Widget):
    """Log viewer with level filtering, search highlighting, and auto-scroll.

    Wraps a RichLog widget with an internal buffer of parsed entries.
    Supports filtering by minimum log level and highlighting search terms.
    """

    DEFAULT_CSS = """
    LogViewer {
        height: 1fr;
    }
    """

    min_level: reactive[str] = reactive("DEBUG")
    search_term: reactive[str] = reactive("")
    auto_scroll: reactive[bool] = reactive(True)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._buffer: deque[OdooLogEntry] = deque(maxlen=MAX_BUFFER_SIZE)
        self._rich_log: RichLog | None = None

    def compose(self):
        """Create the RichLog widget."""
        yield RichLog(highlight=False, markup=False, wrap=True, id="log-output")

    def on_mount(self) -> None:
        """Get reference to the RichLog after mounting."""
        self._rich_log = self.query_one("#log-output", RichLog)

    def write_line(self, line: str) -> None:
        """Parse and display a raw log line.

        Args:
            line: Raw log line from Odoo stdout/stderr.
        """
        entry = parse_line(line)
        self._buffer.append(entry)

        if self._should_show(entry):
            self._render_entry(entry)

    def _should_show(self, entry: OdooLogEntry) -> bool:
        """Check if an entry passes the current filter."""
        if not level_ge(entry.level, self.min_level):
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
        for entry in self._buffer:
            if self._should_show(entry):
                self._render_entry(entry)

    def watch_min_level(self) -> None:
        """React to filter level changes."""
        self._rebuild_display()

    def watch_search_term(self) -> None:
        """React to search term changes."""
        self._rebuild_display()

    def clear_log(self) -> None:
        """Clear the display (buffer is preserved)."""
        if self._rich_log is not None:
            self._rich_log.clear()

    def clear_all(self) -> None:
        """Clear both display and buffer."""
        self._buffer.clear()
        if self._rich_log is not None:
            self._rich_log.clear()

    @property
    def entry_count(self) -> int:
        """Total number of entries in the buffer."""
        return len(self._buffer)

    @property
    def visible_count(self) -> int:
        """Number of entries passing the current filter."""
        return sum(1 for e in self._buffer if self._should_show(e))

    def get_visible_text(self) -> str:
        """Return all currently visible log lines as plain text."""
        return "\n".join(e.raw for e in self._buffer if self._should_show(e))

    def get_errors_text(self) -> str:
        """Return only ERROR and CRITICAL log lines as plain text."""
        return "\n".join(e.raw for e in self._buffer if e.level in ("ERROR", "CRITICAL"))

    def get_warnings_and_errors_text(self) -> str:
        """Return WARNING, ERROR, and CRITICAL log lines as plain text."""
        return "\n".join(e.raw for e in self._buffer if e.level in ("WARNING", "ERROR", "CRITICAL"))
