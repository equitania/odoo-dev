"""Clickable filter bar widget with level toggles and auto-scroll toggle."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class FilterTab(Static):
    """Clickable log level toggle tab.

    Each tab toggles a single log level on or off independently of the others.
    """

    ALLOW_SELECT = False

    class Selected(Message):
        """Posted when a filter tab is clicked.

        The receiver should toggle the level — not switch to a single
        active level.
        """

        def __init__(self, level: str) -> None:
            super().__init__()
            self.level = level

    def __init__(self, level: str, **kwargs) -> None:
        super().__init__(f" {level} ", **kwargs)
        self.level = level
        self.add_class(f"level-{level.lower()}")

    def on_click(self) -> None:
        """Post selection message on click."""
        self.post_message(self.Selected(self.level))


class ScrollToggle(Static):
    """Clickable auto-scroll toggle indicator."""

    ALLOW_SELECT = False

    class Toggled(Message):
        """Posted when the scroll toggle is clicked."""

    def on_click(self) -> None:
        """Post toggle message on click."""
        self.post_message(self.Toggled())


class FilterBar(Widget):
    """Clickable filter bar with independent level toggles, auto-scroll toggle, and search indicator.

    Each level (DEBUG, INFO, WARNING, ERROR, CRITICAL) can be enabled or
    disabled independently. Active tabs are highlighted in green, inactive
    tabs are dimmed.
    """

    DEFAULT_CSS = """
    FilterBar {
        height: 1;
        dock: top;
        padding: 0 1;
        background: $surface;
        layout: horizontal;
    }

    FilterBar Horizontal {
        height: 1;
        width: 1fr;
    }

    FilterTab {
        width: auto;
        height: 1;
        min-width: 5;
    }

    FilterTab:hover {
        background: $block-hover-background;
    }

    FilterTab.active {
        text-style: bold reverse;
        color: $success;
    }

    FilterTab.inactive {
        text-style: none;
        color: $text-muted;
    }

    .separator {
        width: auto;
        height: 1;
        color: $text-muted;
    }

    .label {
        width: auto;
        height: 1;
        color: $text-muted;
    }

    ScrollToggle {
        width: auto;
        height: 1;
        min-width: 11;
    }

    ScrollToggle:hover {
        background: $block-hover-background;
    }

    ScrollToggle.scroll-on {
        color: $success;
    }

    ScrollToggle.scroll-off {
        color: $text-muted;
    }

    .search-indicator {
        width: auto;
        height: 1;
        color: $text;
    }
    """

    LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    DEFAULT_ACTIVE: frozenset[str] = frozenset(LEVELS)

    active_levels: reactive[frozenset[str]] = reactive(DEFAULT_ACTIVE)
    auto_scroll: reactive[bool] = reactive(True)
    search_term: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        """Build the filter bar with clickable toggle tabs."""
        with Horizontal():
            yield Static("Levels:", classes="label")
            for level in self.LEVELS:
                yield FilterTab(level, id=f"tab-{level.lower()}")
            yield Static(" | ", classes="separator")
            yield ScrollToggle("auto-scroll", id="scroll-toggle")
            yield Static("", id="search-indicator", classes="search-indicator")

    def on_mount(self) -> None:
        """Apply initial styles."""
        self._update_tab_styles()
        self._update_scroll_style()

    def watch_active_levels(self) -> None:
        """Update tab styles when active set changes."""
        self._update_tab_styles()

    def watch_auto_scroll(self) -> None:
        """Update scroll toggle style."""
        self._update_scroll_style()

    def watch_search_term(self) -> None:
        """Update search indicator."""
        self._update_search_indicator()

    def set_active_levels(self, levels: frozenset[str]) -> None:
        """Set the full set of active filter levels."""
        self.active_levels = levels

    def set_scroll(self, enabled: bool) -> None:
        """Set the auto-scroll state."""
        self.auto_scroll = enabled

    def set_search(self, term: str) -> None:
        """Set the search term display."""
        self.search_term = term

    def _update_tab_styles(self) -> None:
        """Apply active/inactive styles to filter tabs."""
        for level in self.LEVELS:
            tabs = self.query(f"#tab-{level.lower()}")
            if not tabs:
                continue
            tab = tabs.first(FilterTab)
            if level in self.active_levels:
                tab.update(f"[bold reverse green] {level} [/]")
                tab.remove_class("inactive")
                tab.add_class("active")
            else:
                tab.update(f"[dim] {level} [/]")
                tab.remove_class("active")
                tab.add_class("inactive")

    def _update_scroll_style(self) -> None:
        """Update the scroll toggle display."""
        try:
            toggle = self.query_one("#scroll-toggle", ScrollToggle)
        except Exception:
            return
        if self.auto_scroll:
            toggle.update("[green]auto-scroll[/]")
            toggle.remove_class("scroll-off")
            toggle.add_class("scroll-on")
        else:
            toggle.update("[dim]manual[/]")
            toggle.remove_class("scroll-on")
            toggle.add_class("scroll-off")

    def _update_search_indicator(self) -> None:
        """Update the search term indicator."""
        try:
            indicator = self.query_one("#search-indicator", Static)
        except Exception:
            return
        if self.search_term:
            indicator.update(f" | search: [bold]{self.search_term}[/]")
        else:
            indicator.update("")
