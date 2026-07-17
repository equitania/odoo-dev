"""Textual TUI application for Odoo server runtime management."""

from __future__ import annotations

import platform
import shutil
import subprocess

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Static

from odoodev import __version__
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
        Binding("b", "backup_db", "Backup DB", show=False),
        Binding("d", "switch_db", "Switch DB", show=False),
        Binding("a", "update_apps_list", "Update Apps List", show=False),
        Binding("k", "cleanup_modules", "Cleanup Modules", show=False),
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
        Binding("y", "toggle_mark_mode", "Mark / copy", show=False),
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
        db_port: int = 0,
    ) -> None:
        super().__init__()
        self._odoo = OdooProcess(cmd=cmd, env=env, cwd=cwd)
        self._version_info = version_info
        self._odoo_port = odoo_port
        self._db_name = db_name
        self._db_port = db_port
        self._search_active = False

    def compose(self) -> ComposeResult:
        """Build the TUI layout."""
        yield StatusBar(id="status-bar")
        yield FilterBar(id="filter-bar")
        yield LogViewer(id="log-viewer")
        yield Footer()
        # Version label on its own thin row just above the footer (right-aligned)
        yield Static(self._mark_hint(), id="app-version")

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
        """Esc: leave mark mode if active, otherwise clear the search term."""
        log_viewer = self.query_one("#log-viewer", LogViewer)
        if log_viewer.mark_mode:
            self._set_mark_mode(False)
            return
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

    def action_toggle_mark_mode(self) -> None:
        """Toggle the log selection (copy) mode — 'y' both enters and yanks.

        First press enters mark mode: auto-scroll freezes so the content holds
        still, the log gets an accent border, the status bar shows a MARK badge,
        and mouse selection is enabled. Drag over the log to mark a region (it
        is highlighted). Press 'y' again to copy the marked text and leave the
        mode; press Esc to leave without copying. This deliberate mode replaces
        the old auto-copy-on-release, which grabbed everything visible.
        """
        log_viewer = self.query_one("#log-viewer", LogViewer)
        if not log_viewer.mark_mode:
            self._set_mark_mode(True)
            self.notify(
                "Mark mode — drag over the log to select, 'y' copies, Esc cancels",
                severity="information",
                timeout=3,
            )
            return
        # Second press: read the selection BEFORE leaving (leaving clears it),
        # copy it if present, then drop back to normal auto-scrolling mode.
        text = self.screen.get_selected_text()
        self._set_mark_mode(False)
        if not text:
            self.notify("Mark mode off — nothing was marked", severity="warning", timeout=2)
            return
        if self._copy_to_clipboard(text):
            line_count = text.count("\n") + 1
            # A partial-line selection isn't "1 line" — say so accurately.
            msg = "Marked text copied to clipboard" if line_count == 1 else f"Copied {line_count} lines to clipboard"
            self.notify(msg, severity="information", timeout=2)
        else:
            self.notify("No clipboard tool found (need pbcopy, xclip, or xsel)", severity="error")

    @staticmethod
    def _mark_hint() -> str:
        """Footer hint shown in normal mode — reminds that 'y' enters mark mode."""
        return f"[dim]y = mark mode[/]   ·   odoodev v{__version__}"

    def _set_mark_mode(self, active: bool) -> None:
        """Central mark-mode switch — keeps widget state, badge and footer hint in sync.

        Beyond the log's own freeze/border (LogViewer.watch_mark_mode) this makes
        the mode unmistakable at the places the user actually looks: the status-bar
        ``● MARK`` badge, the FilterBar auto-scroll indicator (via _update_filter_bar),
        and the always-visible hint line above the footer.
        """
        self.query_one("#log-viewer", LogViewer).mark_mode = active
        self.query_one("#status-bar", StatusBar).mark_mode = active
        hint = self.query_one("#app-version", Static)
        if active:
            hint.update("[black on yellow] ◉ MARK [/]  drag to select · y copies · Esc cancels · auto-scroll paused")
        else:
            hint.update(self._mark_hint())
        self._update_filter_bar()

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

    def _handle_export_modules(self, result) -> None:
        """Launch the export worker after the dialog choice.

        ``result`` is an :class:`ExportModulesChoice` from the dialog or
        ``None`` on cancel. The XML-RPC round-trips (cleanup, apps-list update,
        module listing) block, so they run off the UI thread with a progress
        overlay — previously the export ran synchronously and froze the TUI.
        """
        if result is None:
            return  # cancelled

        self.run_worker(lambda: self._do_export_modules(result), thread=True, exclusive=False)

    def _do_export_modules(self, choice) -> None:
        """Query modules via XML-RPC and write the CSV (runs in a worker thread).

        If requested, non-installed modules are removed and the apps list
        refreshed (cleanup first, then update — so the catalog reflects the
        current system) before the modules are listed.
        """
        import datetime

        from odoodev.core.module_export import EXPORT_SCOPES, build_export_path, write_modules_csv
        from odoodev.core.xmlrpc_client import OdooXmlRpcClient
        from odoodev.i18n import t
        from odoodev.tui.screens import ExportProgressScreen

        progress = ExportProgressScreen()
        self.call_from_thread(self.push_screen, progress)

        installed_only, exclude_enterprise = EXPORT_SCOPES.get(choice.scope, (False, False))
        try:
            # Credentials come from the dialog (per-export override), never
            # logged — they only flow into the client and the optional save.
            client = OdooXmlRpcClient(
                port=self._odoo_port,
                database=choice.db_name,
                username=choice.username,
                password=choice.password,
            )
            self.call_from_thread(progress.set_status, t("tui.export_connecting"))
            if choice.do_cleanup:
                self.call_from_thread(progress.set_status, t("tui.export_progress_cleanup"))
                removed = client.cleanup_uninstalled_modules()
                self.call_from_thread(self.notify, t("tui.modules_cleaned", count=removed), severity="information")
            if choice.do_update:
                self.call_from_thread(progress.set_status, t("tui.export_progress_update"))
                added = client.update_module_list()
                self.call_from_thread(self.notify, t("tui.modules_updated", count=added), severity="information")
            self.call_from_thread(progress.set_status, t("tui.export_progress_listing"))
            records = client.list_modules(installed_only=installed_only, exclude_enterprise=exclude_enterprise)
        except Exception as e:  # surface any RPC/auth failure to the user
            self.call_from_thread(self.notify, t("tui.export_error", error=str(e)), severity="error")
            return
        finally:
            # Never leave the progress overlay stuck — also on error paths.
            self.call_from_thread(progress.dismiss)

        if choice.remember_credentials:
            from odoodev.core.global_config import save_odoo_login_credentials

            save_odoo_login_credentials(choice.username, choice.password)

        if not records:
            self.call_from_thread(self.notify, t("tui.export_empty"), severity="warning")
            return

        path = build_export_path(choice.db_name, choice.scope, datetime.datetime.now())
        try:
            write_modules_csv(records, path)
        except OSError as e:
            self.call_from_thread(self.notify, t("tui.export_error", error=str(e)), severity="error")
            return

        self.call_from_thread(
            self.notify, t("tui.export_saved", count=len(records), path=str(path)), severity="information"
        )

    # --- Database backup / switch + module maintenance ---

    def action_backup_db(self) -> None:
        """Open the database backup dialog (writes to ~/Downloads/)."""
        from odoodev.tui.screens import BackupScreen

        self.push_screen(BackupScreen(self._db_name), self._handle_backup_db)

    def _handle_backup_db(self, result: tuple[str, str] | None) -> None:
        """Run the backup in a worker thread after the dialog choice.

        ``result`` is ``(backup_type, db_name)`` or ``None`` on cancel. The dump
        (pg_dump + ZIP) blocks, so it runs off the UI thread; notifications are
        marshalled back via ``call_from_thread``.
        """
        if result is None:
            return  # cancelled

        backup_type, db_name = result
        self.run_worker(
            lambda: self._do_backup(backup_type, db_name),
            thread=True,
            exclusive=False,
        )

    def _do_backup(self, backup_type: str, db_name: str) -> None:
        """Create the backup file in ~/Downloads/ (runs in a worker thread)."""
        import tempfile
        from datetime import datetime
        from pathlib import Path

        from odoodev.core.database import backup_database_sql, create_backup_zip, format_size, get_filestore_path
        from odoodev.i18n import t

        self.call_from_thread(self.notify, t("tui.backup_running", db=db_name))

        downloads = Path.home() / "Downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        date_suffix = datetime.now().strftime("%y%m%d")
        ext = "sql" if backup_type == "sql" else "zip"
        output_file = downloads / f"{db_name}_{date_suffix}.{ext}"

        try:
            if backup_type == "sql":
                ok = backup_database_sql(db_name, str(output_file), port=self._db_port)
            else:
                tmp_dir = tempfile.mkdtemp(prefix="odoodev_backup_")
                try:
                    sql_path = str(Path(tmp_dir) / "dump.sql")
                    if not backup_database_sql(db_name, sql_path, port=self._db_port):
                        ok = False
                    else:
                        fs_path = get_filestore_path(self._version_info, db_name)
                        fs_dir = fs_path if Path(fs_path).is_dir() else None
                        ok = create_backup_zip(sql_path, str(output_file), fs_dir)
                finally:
                    import shutil as _shutil

                    _shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception as e:
            self.call_from_thread(self.notify, t("tui.backup_error", error=str(e)), severity="error")
            return

        if not ok or not output_file.exists():
            self.call_from_thread(self.notify, t("tui.backup_empty"), severity="error")
            return

        size = format_size(output_file.stat().st_size)
        self.call_from_thread(
            self.notify,
            t("tui.backup_saved", path=str(output_file), size=size),
            severity="information",
        )

    def action_switch_db(self) -> None:
        """Open the database picker; the server restarts with the choice."""
        from odoodev.tui.screens import DbSwitchScreen

        self.push_screen(DbSwitchScreen(self._db_port, self._db_name), self._handle_switch_db)

    def _handle_switch_db(self, new_db: str | None) -> None:
        """Restart the server bound to the newly selected database."""
        if not new_db or new_db == self._db_name:
            return

        from odoodev.i18n import t

        self._db_name = new_db
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.db_name = new_db
        status_bar.server_state = "starting"
        log_viewer = self.query_one("#log-viewer", LogViewer)
        log_viewer.write_line(f"\n--- Switching to database '{new_db}' ---\n")
        self._odoo.restart(extra_args=["-d", new_db])
        self.notify(t("tui.switch_db_switching", db=new_db), severity="information")

    def action_update_apps_list(self) -> None:
        """Refresh the Odoo apps list (update_list) in a worker thread."""
        self.run_worker(self._do_update_apps_list, thread=True, exclusive=False)

    def _do_update_apps_list(self) -> None:
        """Call ir.module.module.update_list via XML-RPC (worker thread)."""
        from odoodev.core.xmlrpc_client import OdooXmlRpcClient
        from odoodev.i18n import t

        self.call_from_thread(self.notify, t("tui.modules_updating"))
        try:
            client = OdooXmlRpcClient.from_stored_credentials(port=self._odoo_port, database=self._db_name)
            added = client.update_module_list()
        except Exception as e:
            self.call_from_thread(self.notify, t("tui.modules_update_error", error=str(e)), severity="error")
            return
        self.call_from_thread(self.notify, t("tui.modules_updated", count=added), severity="information")

    def action_cleanup_modules(self) -> None:
        """Remove non-installed modules from the catalog in a worker thread."""
        self.run_worker(self._do_cleanup_modules, thread=True, exclusive=False)

    def _do_cleanup_modules(self) -> None:
        """Delete ir.module.module rows where state != installed (worker thread)."""
        from odoodev.core.xmlrpc_client import OdooXmlRpcClient
        from odoodev.i18n import t

        self.call_from_thread(self.notify, t("tui.modules_cleaning"))
        try:
            client = OdooXmlRpcClient.from_stored_credentials(port=self._odoo_port, database=self._db_name)
            removed = client.cleanup_uninstalled_modules()
        except Exception as e:
            self.call_from_thread(self.notify, t("tui.modules_clean_error", error=str(e)), severity="error")
            return
        self.call_from_thread(self.notify, t("tui.modules_cleaned", count=removed), severity="information")

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
