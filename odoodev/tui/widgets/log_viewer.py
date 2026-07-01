"""Scrollable log viewer widget with level filtering and search."""

from __future__ import annotations

from collections import deque

from rich.segment import Segment
from rich.text import Text
from textual.reactive import reactive
from textual.selection import Selection
from textual.strip import Strip
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
    """RichLog subclass with working, mode-gated mouse text selection.

    Stock RichLog has no mouse selection at all: unlike Textual's ``Log``
    widget (which calls ``Strip.apply_offsets`` in its ``_render_line``),
    ``RichLog.render_line`` never embeds the ``"offset"`` style meta that the
    compositor needs to map a mouse position to a content offset. Without it
    ``screen.selections`` stays empty forever, so no selection is tracked, no
    highlight is drawn, and the terminal emulator's own selection takes over
    (grabbing "all visible lines"). ``render_line`` below fixes that by
    embedding the offsets and drawing the ``screen--selection`` highlight.

    Selection is gated on ``_select_enabled`` (driven by the LogViewer mark
    mode) via the ``allow_select`` property, so the app only claims the mouse
    while the user is deliberately marking.
    """

    _select_enabled: bool = False

    @property
    def allow_select(self) -> bool:
        """Only allow mouse text selection while mark mode is active."""
        return self._select_enabled

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

    def render_line(self, y: int) -> Strip:
        """Embed mouse offsets and draw the selection highlight.

        Two things stock RichLog never does:

        1. ``strip.apply_offsets(scroll_x, scroll_y + y)`` embeds the ``"offset"``
           style meta the compositor needs to turn a mouse position into a content
           offset. Without this call ``screen.selections`` stays empty for this
           widget and NOTHING downstream works (no tracking, no highlight, no
           copy). It runs on every line, selection or not, so a drag can start.
        2. The ``screen--selection`` highlight over the selected span, mirroring
           Textual's own per-line selection rendering. Coordinates are
           content-absolute (``self.lines`` index), matching ``get_selection`` so
           the highlight and the copied text cover exactly the same region.

        ``apply_offsets`` runs last, on the (possibly highlighted) strip, so the
        colour-only selection style can't clobber the offset meta.
        """
        strip = super().render_line(y)
        # render_line(y) shows content row scroll_y + y; get_span expects that row.
        content_y = self.scroll_offset.y + y
        selection = self.text_selection
        if selection is not None:
            span = selection.get_span(content_y)
            if span is not None:
                start, end = span
                if end == -1:  # -1 means "to end of line" (interior lines of a multi-line selection)
                    end = strip.cell_length
                start = max(0, min(start, strip.cell_length))
                end = max(start, min(end, strip.cell_length))
                if start != end:
                    sel_style = self.screen.get_component_rich_style("screen--selection")
                    # crop (not divide) so edge spans — start at 0 or end at
                    # cell_length — need no assumption about the piece count.
                    before = strip.crop(0, start)
                    after = strip.crop(end, strip.cell_length)
                    # Overlay the selection style so it WINS over each segment's own
                    # style. Strip.apply_style / Segment.apply_style combine as
                    # (sel_style + seg.style) — i.e. the segment's existing background
                    # overrides ours, leaving the highlight invisible. Combine the
                    # other way (seg.style + sel_style) so the selection colour wins.
                    middle_src = strip.crop(start, end)
                    middle = Strip(
                        [
                            Segment(seg.text, (seg.style + sel_style) if seg.style else sel_style, seg.control)
                            for seg in middle_src
                        ],
                        middle_src.cell_length,
                    )
                    strip = Strip.join([before, middle, after])
        return strip.apply_offsets(self.scroll_offset.x, content_y)

    def selection_updated(self, selection: Selection | None) -> None:
        """Repaint on selection change — clear RichLog's own line cache too.

        Textual notifies the selected widget via ``selection_updated`` whenever
        ``screen.selections`` changes, but the base ``Widget`` default only calls
        ``self.refresh()``, which clears ``_styles_cache`` and NOT RichLog's own
        ``_line_cache`` (keyed without any selection info). So the stale,
        un-highlighted strips survive: the highlight never appears, and an old
        highlight lingers until some unrelated repaint (scroll/new line/resize)
        happens to clear it — the "old + new" artefact. Textual's own ``Log``
        widget solves the identical problem the same way (see ``_log.py``).
        """
        self._line_cache.clear()
        self.refresh()


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
    mark_mode: reactive[bool] = reactive(False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # Buffer stores parsed entries with their effective filter level.
        # For non-RAW entries, effective_level == entry.level.
        # For RAW entries, effective_level inherits the previous structured level.
        self._buffer: deque[tuple[OdooLogEntry, str]] = deque(maxlen=MAX_BUFFER_SIZE)
        self._last_real_level: str = DEFAULT_RAW_LEVEL
        self._rich_log: SelectableRichLog | None = None
        self._scroll_was_auto: bool | None = None

    def compose(self):
        """Create the selectable RichLog widget."""
        yield SelectableRichLog(highlight=False, markup=False, wrap=True, id="log-output")

    def on_mount(self) -> None:
        """Get reference to the RichLog after mounting."""
        self._rich_log = self.query_one("#log-output", SelectableRichLog)

    def watch_mark_mode(self, active: bool) -> None:
        """Enter/leave the explicit selection (copy) mode.

        Marking only works when the content stands still — otherwise the live,
        auto-scrolling log re-maps the same screen row to a different content
        line mid-drag (the old "grabs all visible lines" bug). So mark mode
        freezes auto-scroll, enables mouse selection on the RichLog, and adds
        the ``mark-mode`` class (accent border). Leaving restores the previous
        auto-scroll state and clears any active selection.
        """
        if self._rich_log is None:
            return
        if active:
            self._scroll_was_auto = self.auto_scroll
            self.auto_scroll = False
            self._rich_log._select_enabled = True
            self._rich_log.add_class("mark-mode")
        else:
            self._rich_log._select_enabled = False
            # Clear the selection first so its highlight-removing repaint runs
            # before the class change; then drop the accent border.
            try:
                self.screen.clear_selection()
            except Exception:  # noqa: S110 — screen may be gone during teardown
                pass
            self._rich_log.remove_class("mark-mode")
            if self._scroll_was_auto is not None:
                self.auto_scroll = self._scroll_was_auto
                self._scroll_was_auto = None

    def write_line(self, line: str) -> OdooLogEntry:
        """Parse and display a raw log line.

        Tracks the last structured log level so RAW continuation lines
        (tracebacks, stack traces, plain stdout) are filtered alongside
        their triggering log entry.

        Args:
            line: Raw log line from Odoo stdout/stderr.

        Returns:
            The parsed ``OdooLogEntry`` (so callers can read e.g. the
            ``database`` field without re-parsing).
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

        return entry

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

    def show_only_level(self, level: str) -> None:
        """Activate exactly one level (radio-style filter).

        Press ``0`` to restore all levels; press a number key to focus on
        a single level. No-op when ``level`` is not a filterable level.
        """
        if level not in FILTERABLE_LEVELS:
            return
        self.active_levels = frozenset({level})

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
