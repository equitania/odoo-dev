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

# Filter levels users can toggle (excludes RAW — RAW inherits the previous entry's level)
FILTER_LEVELS = [level for level in LOG_LEVELS if level != "RAW"]


class OdooTuiApp(App):
    """Terminal UI for running and monitoring an Odoo server.

    Provides scrollable log output with independent per-level filtering,
    reliable process termination, and keyboard shortcuts for common operations.
    """

    CSS_PATH = "app.tcss"

    # Footer stays minimal (q / m / ?) so it fits narrow terminals; everything
    # else is reachable via the quick menu (m) and still works as a direct key.
    BINDINGS = [
        Binding("q", "quit_app", "Quit", priority=True),
        Binding("ctrl+q", "quit_app", "Quit", priority=True, show=False),
        Binding("m", "show_menu", "Menu"),
        Binding("question_mark", "show_help", "Help"),
        # Direct keys — hidden from the footer, all reachable via the menu
        Binding("r", "restart", "Restart", show=False),
        Binding("u", "update", "Update Module", show=False),
        Binding("l", "load_language", "Load Language", show=False),
        # Per-level toggles (multi-toggle filter)
        Binding("0", "filter_all", "All Levels", show=False),
        Binding("1", "show_only_debug", "DEBUG", show=False),
        Binding("2", "show_only_info", "INFO", show=False),
        Binding("3", "show_only_warning", "WARN", show=False),
        Binding("4", "show_only_error", "ERROR", show=False),
        Binding("5", "show_only_critical", "CRIT", show=False),
        Binding("f", "filter_issues", "Issues only", show=False),
        Binding("slash", "search", "Search", show=False),
        Binding("ctrl+l", "clear_log", "Clear Log", show=False),
        Binding("c", "copy_visible", "Copy", show=False),
        Binding("e", "copy_errors", "Copy Errors", show=False),
        Binding("w", "copy_warnings", "Copy Warn+Err", show=False),
        Binding("s", "save_log", "Save Log", show=False),
        Binding("x", "export_modules", "Export CSV", show=False),
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
        status_bar = self.query_one("#status-bar", StatusBar)
        for line in lines:
            entry = log_viewer.write_line(line)
            # Track the database Odoo actually serves (ground truth from logs).
            # Odoo logs "?" before DB routing — ignore those and RAW lines.
            if entry.level != "RAW" and entry.database not in ("", "?") and entry.database != self._db_name:
                self._db_name = entry.database
                status_bar.db_name = entry.database

        # Detect first output → running
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
        """Synchronize filter bar display with log viewer state."""
        filter_bar = self.query_one("#filter-bar", FilterBar)
        log_viewer = self.query_one("#log-viewer", LogViewer)
        filter_bar.set_active_levels(log_viewer.active_levels)
        filter_bar.set_scroll(log_viewer.auto_scroll)
        filter_bar.set_search(log_viewer.search_term)

    def on_filter_tab_selected(self, event: FilterTab.Selected) -> None:
        """Handle click on a filter level tab — toggle that level."""
        log_viewer = self.query_one("#log-viewer", LogViewer)
        log_viewer.toggle_level(event.level)
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

    def _show_only_level(self, level: str) -> None:
        """Activate exactly one log level (radio-style filter).

        Press ``0`` to restore all levels.
        """
        log_viewer = self.query_one("#log-viewer", LogViewer)
        log_viewer.show_only_level(level)
        self._update_filter_bar()

    def action_show_only_debug(self) -> None:
        """Show only DEBUG entries."""
        self._show_only_level("DEBUG")

    def action_show_only_info(self) -> None:
        """Show only INFO entries."""
        self._show_only_level("INFO")

    def action_show_only_warning(self) -> None:
        """Show only WARNING entries."""
        self._show_only_level("WARNING")

    def action_show_only_error(self) -> None:
        """Show only ERROR entries."""
        self._show_only_level("ERROR")

    def action_show_only_critical(self) -> None:
        """Show only CRITICAL entries."""
        self._show_only_level("CRITICAL")

    def action_filter_all(self) -> None:
        """Activate all log levels (default state)."""
        log_viewer = self.query_one("#log-viewer", LogViewer)
        log_viewer.show_all_levels()
        self._update_filter_bar()

    def action_filter_issues(self) -> None:
        """Show only WARNING, ERROR, and CRITICAL."""
        log_viewer = self.query_one("#log-viewer", LogViewer)
        log_viewer.show_issues_only()
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

    def action_save_log(self) -> None:
        """Save the currently visible (filtered) log lines to ~/odoodev-logs/."""
        import datetime
        from pathlib import Path

        log_viewer = self.query_one("#log-viewer", LogViewer)
        text = log_viewer.get_visible_text()
        if not text:
            self.notify("Log buffer is empty", severity="warning")
            return

        log_dir = Path.home() / "odoodev-logs"
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_version = (self._version_info or "unknown").replace("/", "-").replace(" ", "_")
        safe_db = (self._db_name or "nodb").replace("/", "-")
        path = log_dir / f"odoo_{safe_version}_{safe_db}_{timestamp}.log"

        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8")
            self.notify(f"Log saved: {path}", severity="information")
        except OSError as e:
            self.notify(f"Save failed: {e}", severity="error")

    def action_show_menu(self) -> None:
        """Open the quick action menu (folds up from the bottom)."""
        from odoodev.tui.screens import QuickMenuScreen

        self.push_screen(QuickMenuScreen(), self._handle_menu)

    def _handle_menu(self, action: str | None) -> None:
        """Run the action chosen in the quick menu (option id == action name).

        ``run_action`` is a coroutine; schedule it via ``call_next`` so it is
        awaited after this sync dismiss-callback returns.
        """
        if action:
            self.call_next(self.run_action, action)

    def action_export_modules(self) -> None:
        """Open the module CSV export dialog (Releasemanager format)."""
        from odoodev.tui.screens import ExportModulesScreen

        self.push_screen(ExportModulesScreen(self._db_name), self._handle_export_modules)

    def _handle_export_modules(self, result: tuple[str, str] | None) -> None:
        """Query modules via XML-RPC and write the CSV after the dialog choice.

        ``result`` is ``(scope, db_name)`` from the dialog, or ``None`` on cancel.
        The database name is whatever the user confirmed/edited in the dialog.
        """
        if result is None:
            return  # cancelled

        scope, db_name = result

        import datetime

        from odoodev.i18n import t
        from odoodev.tui.module_export import EXPORT_SCOPES, build_export_path, write_modules_csv
        from odoodev.tui.xmlrpc_client import OdooXmlRpcClient

        installed_only, exclude_enterprise = EXPORT_SCOPES.get(scope, (False, False))
        try:
            client = OdooXmlRpcClient(port=self._odoo_port, database=db_name)
            records = client.list_modules(installed_only=installed_only, exclude_enterprise=exclude_enterprise)
        except Exception as e:  # surface any RPC/auth failure to the user
            self.notify(t("tui.export_error", error=str(e)), severity="error")
            return

        if not records:
            self.notify(t("tui.export_empty"), severity="warning")
            return

        path = build_export_path(db_name, scope, datetime.datetime.now())
        try:
            write_modules_csv(records, path)
        except OSError as e:
            self.notify(t("tui.export_error", error=str(e)), severity="error")
            return

        self.notify(t("tui.export_saved", count=len(records), path=str(path)), severity="information")

    def action_show_help(self) -> None:
        """Show the keybinding help overlay."""
        from odoodev.tui.screens import HelpScreen

        self.push_screen(HelpScreen())

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
