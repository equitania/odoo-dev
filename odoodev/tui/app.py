"""Textual TUI application for Odoo server runtime management."""

from __future__ import annotations

import platform
import shutil
import subprocess

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer

from odoodev.tui.log_parser import LOG_LEVELS
from odoodev.tui.odoo_process import OdooProcess
from odoodev.tui.widgets.filter_bar import FilterBar, FilterTab, ScrollToggle
from odoodev.tui.widgets.log_viewer import LogViewer
from odoodev.tui.widgets.status_bar import StatusBar

# Filter levels users can cycle through (excludes RAW)
FILTER_LEVELS = [level for level in LOG_LEVELS if level != "RAW"]


class OdooTuiApp(App):
    """Terminal UI for running and monitoring an Odoo server.

    Provides scrollable log output with level filtering, reliable
    process termination, and keyboard shortcuts for common operations.
    """

    CSS_PATH = "app.tcss"

    BINDINGS = [
        Binding("q", "quit_app", "Quit", priority=True),
        Binding("ctrl+q", "quit_app", "Quit", priority=True, show=False),
        Binding("r", "restart", "Restart"),
        Binding("u", "update", "Update Module"),
        Binding("l", "load_language", "Load Language"),
        Binding("f", "cycle_filter", "Filter Level"),
        Binding("slash", "search", "Search"),
        Binding("ctrl+l", "clear_log", "Clear Log"),
        Binding("c", "copy_visible", "Copy Visible"),
        Binding("e", "copy_errors", "Copy Errors"),
        Binding("w", "copy_warnings", "Copy Warn+Err"),
        Binding("space", "toggle_scroll", "Auto-scroll", show=False),
        Binding("escape", "clear_search", "Clear Search", show=False),
    ]

    def __init__(
        self,
        cmd: list[str],
        env: dict[str, str],
        cwd: str,
        version_info: str = "",
        odoo_port: int = 0,
        db_name: str = "",
    ) -> None:
        super().__init__()
        self._odoo = OdooProcess(cmd=cmd, env=env, cwd=cwd)
        self._version_info = version_info
        self._odoo_port = odoo_port
        self._db_name = db_name
        self._filter_index = 0  # Index into FILTER_LEVELS
        self._search_active = False

    def compose(self) -> ComposeResult:
        """Build the TUI layout."""
        yield StatusBar(id="status-bar")
        yield FilterBar(id="filter-bar")
        yield LogViewer(id="log-viewer")
        yield Footer()

    def on_mount(self) -> None:
        """Start the Odoo process and begin polling."""
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.version = self._version_info
        status_bar.port = self._odoo_port
        status_bar.db_name = self._db_name
        status_bar.server_state = "starting"

        self._update_filter_bar()

        self._odoo.start()
        self.set_interval(0.05, self._poll_process)
        self.set_interval(1.0, self._update_status)

    def _poll_process(self) -> None:
        """Drain output queue and write lines to log viewer."""
        lines = self._odoo.read_lines()
        if not lines:
            return

        log_viewer = self.query_one("#log-viewer", LogViewer)
        for line in lines:
            log_viewer.write_line(line)

        # Detect first output → running
        status_bar = self.query_one("#status-bar", StatusBar)
        if status_bar.server_state == "starting":
            status_bar.server_state = "running"

    def _update_status(self) -> None:
        """Update status bar with uptime and running state."""
        status_bar = self.query_one("#status-bar", StatusBar)
        if self._odoo.is_running:
            status_bar.uptime_seconds = self._odoo.uptime
            if status_bar.server_state == "stopped":
                status_bar.server_state = "running"
        else:
            if status_bar.server_state != "stopped":
                status_bar.server_state = "stopped"
                rc = self._odoo.return_code
                log_viewer = self.query_one("#log-viewer", LogViewer)
                if rc is not None and rc != 0:
                    log_viewer.write_line(f"\n--- Odoo exited with code {rc} ---\n")
                else:
                    log_viewer.write_line("\n--- Odoo server stopped ---\n")

    def _update_filter_bar(self) -> None:
        """Update the filter bar display."""
        filter_bar = self.query_one("#filter-bar", FilterBar)
        log_viewer = self.query_one("#log-viewer", LogViewer)
        filter_bar.set_level(FILTER_LEVELS[self._filter_index])
        filter_bar.set_scroll(log_viewer.auto_scroll)
        filter_bar.set_search(log_viewer.search_term)

    def on_filter_tab_selected(self, event: FilterTab.Selected) -> None:
        """Handle click on a filter level tab."""
        try:
            self._filter_index = FILTER_LEVELS.index(event.level)
        except ValueError:
            return
        log_viewer = self.query_one("#log-viewer", LogViewer)
        log_viewer.min_level = event.level
        self._update_filter_bar()

    def on_scroll_toggle_toggled(self, event: ScrollToggle.Toggled) -> None:
        """Handle click on the auto-scroll toggle."""
        self.action_toggle_scroll()

    # --- Actions ---

    def action_quit(self) -> None:
        """Override Textual's default quit to ensure Odoo process cleanup.

        Textual's built-in ctrl+q binding calls action_quit() which only
        calls self.exit(). We override it to stop the Odoo process first.
        """
        self._odoo.stop()
        self.exit()

    def action_quit_app(self) -> None:
        """Stop the Odoo process and exit (q key binding)."""
        self.action_quit()

    def action_restart(self) -> None:
        """Restart the Odoo server."""
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.server_state = "starting"
        log_viewer = self.query_one("#log-viewer", LogViewer)
        log_viewer.write_line("\n--- Restarting Odoo server ---\n")
        self._odoo.restart()

    def action_update(self) -> None:
        """Open module update dialog."""
        from odoodev.tui.screens import ModuleUpdateScreen

        self.push_screen(ModuleUpdateScreen(self._odoo, self._odoo_port, self._db_name))

    def action_load_language(self) -> None:
        """Open language load dialog."""
        from odoodev.tui.screens import LanguageLoadScreen

        self.push_screen(LanguageLoadScreen(self._odoo))

    def action_cycle_filter(self) -> None:
        """Cycle through log level filters."""
        self._filter_index = (self._filter_index + 1) % len(FILTER_LEVELS)
        level = FILTER_LEVELS[self._filter_index]
        log_viewer = self.query_one("#log-viewer", LogViewer)
        log_viewer.min_level = level
        self._update_filter_bar()

    def action_search(self) -> None:
        """Prompt for search term via inline input."""
        self._search_active = True

        from textual.screen import ModalScreen
        from textual.widgets import Input

        class SearchDialog(ModalScreen[str]):
            """Simple search input dialog."""

            DEFAULT_CSS = """
            SearchDialog {
                align: center middle;
            }
            SearchDialog Input {
                width: 60;
                margin: 1;
            }
            """

            def compose(self) -> ComposeResult:
                yield Input(placeholder="Search log output...", id="search-input")

            def on_input_submitted(self, event: Input.Submitted) -> None:
                self.dismiss(event.value)

        def handle_search(term: str | None) -> None:
            self._search_active = False
            if term is not None:
                log_viewer = self.query_one("#log-viewer", LogViewer)
                log_viewer.search_term = term
                self._update_filter_bar()

        self.push_screen(SearchDialog(), handle_search)

    def action_clear_search(self) -> None:
        """Clear the current search term."""
        log_viewer = self.query_one("#log-viewer", LogViewer)
        log_viewer.search_term = ""
        self._update_filter_bar()

    def action_clear_log(self) -> None:
        """Clear the log display and buffer."""
        log_viewer = self.query_one("#log-viewer", LogViewer)
        log_viewer.clear_all()

    def action_copy_visible(self) -> None:
        """Copy all currently visible (filtered) log lines to clipboard."""
        log_viewer = self.query_one("#log-viewer", LogViewer)
        text = log_viewer.get_visible_text()
        count = log_viewer.visible_count
        if self._copy_to_clipboard(text):
            self.notify(f"{count} visible lines copied to clipboard", severity="information")
        else:
            self.notify("No clipboard tool found (need pbcopy, xclip, or xsel)", severity="error")

    def action_copy_errors(self) -> None:
        """Copy only ERROR/CRITICAL lines to clipboard."""
        log_viewer = self.query_one("#log-viewer", LogViewer)
        text = log_viewer.get_errors_text()
        if not text:
            self.notify("No errors to copy", severity="warning")
            return
        count = text.count("\n") + 1
        if self._copy_to_clipboard(text):
            self.notify(f"{count} error lines copied to clipboard", severity="information")
        else:
            self.notify("No clipboard tool found (need pbcopy, xclip, or xsel)", severity="error")

    def action_copy_warnings(self) -> None:
        """Copy WARNING, ERROR, and CRITICAL lines to clipboard."""
        log_viewer = self.query_one("#log-viewer", LogViewer)
        text = log_viewer.get_warnings_and_errors_text()
        if not text:
            self.notify("No warnings or errors to copy", severity="warning")
            return
        count = text.count("\n") + 1
        if self._copy_to_clipboard(text):
            self.notify(f"{count} warning/error lines copied to clipboard", severity="information")
        else:
            self.notify("No clipboard tool found (need pbcopy, xclip, or xsel)", severity="error")

    @staticmethod
    def _copy_to_clipboard(text: str) -> bool:
        """Copy text to system clipboard. Returns True on success."""
        if not text:
            return True

        # macOS
        if platform.system() == "Darwin" and shutil.which("pbcopy"):
            subprocess.run(["pbcopy"], input=text, text=True, check=False)
            return True

        # Linux — try xclip, then xsel
        if shutil.which("xclip"):
            subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, check=False)
            return True
        if shutil.which("xsel"):
            subprocess.run(["xsel", "--clipboard", "--input"], input=text, text=True, check=False)
            return True

        return False

    def action_toggle_scroll(self) -> None:
        """Toggle auto-scroll behavior."""
        log_viewer = self.query_one("#log-viewer", LogViewer)
        log_viewer.auto_scroll = not log_viewer.auto_scroll
        self._update_filter_bar()

    def copy_to_clipboard(self, text: str) -> None:
        """Copy text using system clipboard tools with OSC 52 fallback.

        Overrides Textual's default copy_to_clipboard to use pbcopy/xclip/xsel
        which work reliably on macOS Terminal (where OSC 52 may not work).
        This is called automatically by Textual's text selection system.
        """
        if not self._copy_to_clipboard(text):
            super().copy_to_clipboard(text)
