"""Tests for odoodev.tui app, widgets, and screens."""

import sys

import pytest

from odoodev.tui.app import FILTER_LEVELS, OdooTuiApp
from odoodev.tui.widgets.filter_bar import FilterBar, FilterTab, ScrollToggle
from odoodev.tui.widgets.log_viewer import LEVEL_STYLES, LogViewer, SelectableRichLog
from odoodev.tui.widgets.status_bar import StatusBar


@pytest.fixture
def mock_cmd(tmp_path):
    """Create a mock Odoo process command."""
    script = tmp_path / "mock_odoo.py"
    script.write_text(
        "import time, sys\n"
        "lines = [\n"
        '    "2025-03-15 10:00:00,000 999 INFO test_db odoo.modules.loading: Loading module base",\n'
        '    "2025-03-15 10:00:01,000 999 WARNING test_db odoo.models: Deprecated field",\n'
        '    "2025-03-15 10:00:02,000 999 ERROR test_db odoo.http: Request failed",\n'
        '    "2025-03-15 10:00:03,000 999 DEBUG test_db odoo.sql_db: query took 0.003s",\n'
        "]\n"
        "for line in lines:\n"
        "    print(line, flush=True)\n"
        "    time.sleep(0.05)\n"
        "try:\n"
        "    time.sleep(60)\n"
        "except (KeyboardInterrupt, SystemExit):\n"
        "    pass\n"
    )
    return [sys.executable, str(script)]


def make_app(mock_cmd, tmp_path):
    """Create a test TUI app instance."""
    return OdooTuiApp(
        cmd=mock_cmd,
        env={},
        cwd=str(tmp_path),
        version_info="18",
        odoo_port=18069,
        db_name="v18_exam",
        db_port=18432,
    )


class TestLogViewer:
    """Test LogViewer widget functionality."""

    def test_level_styles_complete(self):
        assert "ERROR" in LEVEL_STYLES
        assert "WARNING" in LEVEL_STYLES
        assert "INFO" in LEVEL_STYLES
        assert "DEBUG" in LEVEL_STYLES
        assert "CRITICAL" in LEVEL_STYLES
        assert "RAW" in LEVEL_STYLES

    def test_error_style_is_red(self):
        assert "red" in LEVEL_STYLES["ERROR"]

    def test_warning_style_is_yellow(self):
        assert "yellow" in LEVEL_STYLES["WARNING"]


class TestStatusBar:
    """Test StatusBar widget functionality."""

    def test_format_uptime(self):
        bar = StatusBar()
        bar.uptime_seconds = 3661.0  # 1h 1m 1s
        assert bar._format_uptime() == "01:01:01"

    def test_format_uptime_zero(self):
        bar = StatusBar()
        bar.uptime_seconds = 0.0
        assert bar._format_uptime() == "00:00:00"

    def test_format_uptime_large(self):
        bar = StatusBar()
        bar.uptime_seconds = 86400.0  # 24 hours
        assert bar._format_uptime() == "24:00:00"

    def test_render_status_stopped(self):
        bar = StatusBar()
        bar.server_state = "stopped"
        bar.version = "18"
        bar.port = 18069
        status = bar._render_status()
        assert "Stopped" in status
        assert "v18" in status

    def test_render_status_running(self):
        bar = StatusBar()
        bar.server_state = "running"
        bar.version = "18"
        bar.port = 18069
        bar.uptime_seconds = 60.0
        status = bar._render_status()
        assert "Running" in status
        assert "00:01:00" in status

    def test_render_status_with_db(self):
        bar = StatusBar()
        bar.server_state = "running"
        bar.db_name = "v18_exam"
        status = bar._render_status()
        assert "v18_exam" in status


class TestFilterLevels:
    """Test filter level cycling."""

    def test_filter_levels_no_raw(self):
        assert "RAW" not in FILTER_LEVELS

    def test_filter_levels_order(self):
        assert FILTER_LEVELS == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class TestOdooTuiAppIntegration:
    """Integration tests using Textual's async test runner."""

    async def test_app_starts_and_has_widgets(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as _pilot:
            # Verify core widgets exist
            assert app.query_one("#status-bar", StatusBar) is not None
            assert app.query_one("#filter-bar", FilterBar) is not None
            assert app.query_one("#log-viewer", LogViewer) is not None

    async def test_app_receives_log_output(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            # Wait for process to produce output
            await pilot.pause(1.0)
            log_viewer = app.query_one("#log-viewer", LogViewer)
            assert log_viewer.entry_count > 0

    async def test_level_keys_exclusive_filter(self, mock_cmd, tmp_path):
        """Hotkeys 1-5 activate exactly one level (radio-style)."""
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            log_viewer = app.query_one("#log-viewer", LogViewer)
            # All levels active by default
            assert log_viewer.active_levels == frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

            # "5" → only CRITICAL
            await pilot.press("5")
            assert log_viewer.active_levels == frozenset({"CRITICAL"})

            # "3" → only WARNING (replaces, not adds)
            await pilot.press("3")
            assert log_viewer.active_levels == frozenset({"WARNING"})

            # "5" again → still only CRITICAL (idempotent)
            await pilot.press("5")
            assert log_viewer.active_levels == frozenset({"CRITICAL"})

            # "1" → only DEBUG
            await pilot.press("1")
            assert log_viewer.active_levels == frozenset({"DEBUG"})

    async def test_filter_all_hotkey(self, mock_cmd, tmp_path):
        """'0' restores all levels active."""
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            log_viewer = app.query_one("#log-viewer", LogViewer)
            await pilot.press("5")  # narrow to CRITICAL only
            assert log_viewer.active_levels == frozenset({"CRITICAL"})

            await pilot.press("0")
            assert log_viewer.active_levels == frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

    async def test_filter_issues_hotkey(self, mock_cmd, tmp_path):
        """'f' shows only WARNING, ERROR, CRITICAL."""
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            log_viewer = app.query_one("#log-viewer", LogViewer)
            await pilot.press("f")
            assert log_viewer.active_levels == frozenset({"WARNING", "ERROR", "CRITICAL"})

    async def test_toggle_auto_scroll(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            log_viewer = app.query_one("#log-viewer", LogViewer)
            assert log_viewer.auto_scroll is True

            await pilot.press("space")
            assert log_viewer.auto_scroll is False

            await pilot.press("space")
            assert log_viewer.auto_scroll is True

    async def test_clear_log_clears_buffer(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.5)
            log_viewer = app.query_one("#log-viewer", LogViewer)
            assert log_viewer.entry_count > 0  # Has entries before clear
            await pilot.press("ctrl+l")
            assert log_viewer.entry_count == 0  # Buffer cleared

    async def test_clear_log_empties_clipboard_copy(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(1.0)
            log_viewer = app.query_one("#log-viewer", LogViewer)
            assert log_viewer.get_errors_text() != ""  # Has errors before clear
            await pilot.press("ctrl+l")
            assert log_viewer.get_errors_text() == ""  # Empty after clear
            assert log_viewer.get_visible_text() == ""

    async def test_clear_log_prevents_filter_restore(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.5)
            log_viewer = app.query_one("#log-viewer", LogViewer)
            assert log_viewer.entry_count > 0
            await pilot.press("ctrl+l")
            assert log_viewer.entry_count == 0
            # Changing filter should NOT bring back cleared entries
            await pilot.press("f")  # Issues only
            assert log_viewer.entry_count == 0
            await pilot.press("0")  # All levels
            assert log_viewer.entry_count == 0

    async def test_quit_stops_process(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            assert app._odoo.is_running is True
            await pilot.press("q")
        # After exit, process should be stopped
        assert app._odoo.is_running is False

    async def test_ctrl_q_stops_process(self, mock_cmd, tmp_path):
        """Ctrl+Q must also stop the Odoo process (not just 'q')."""
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            assert app._odoo.is_running is True
            await pilot.press("ctrl+q")
        # After exit, process should be stopped
        assert app._odoo.is_running is False

    async def test_action_quit_override_stops_process(self, mock_cmd, tmp_path):
        """Textual's action_quit override must stop the Odoo process."""
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            assert app._odoo.is_running is True
            # Call action_quit directly (simulates any Textual quit path)
            app.action_quit()
        assert app._odoo.is_running is False

    async def test_status_bar_updates(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.5)
            status_bar = app.query_one("#status-bar", StatusBar)
            assert status_bar.version == "18"
            assert status_bar.port == 18069
            # db_name is detected live from the Odoo log lines (mock emits "test_db"),
            # overriding the start-time value — this proves log-based DB detection.
            assert status_bar.db_name == "test_db"

    async def test_get_visible_text(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(1.0)
            log_viewer = app.query_one("#log-viewer", LogViewer)
            text = log_viewer.get_visible_text()
            assert "Loading module base" in text

    async def test_get_errors_text(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(1.0)
            log_viewer = app.query_one("#log-viewer", LogViewer)
            errors = log_viewer.get_errors_text()
            assert "Request failed" in errors
            assert "Loading module base" not in errors

    async def test_get_warnings_and_errors_text(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(1.0)
            log_viewer = app.query_one("#log-viewer", LogViewer)
            text = log_viewer.get_warnings_and_errors_text()
            assert "Deprecated field" in text
            assert "Request failed" in text
            assert "Loading module base" not in text


class TestTracebackCollection:
    """Test that error/warning copy includes traceback continuation lines."""

    def test_errors_include_traceback(self):
        viewer = LogViewer()
        lines = [
            "2025-03-15 10:00:00,000 999 INFO db odoo.modules: Starting",
            "2025-03-15 10:00:01,000 999 ERROR db odoo.http: Exception during request handling.",
            "Traceback (most recent call last):",
            '  File "/server/odoo/http.py", line 2825, in __call__',
            "    response = request._serve_db()",
            "TypeError: cannot unpack non-iterable NoneType object",
            "2025-03-15 10:00:02,000 999 INFO db odoo.modules: Loaded",
        ]
        for line in lines:
            viewer.write_line(line)

        errors = viewer.get_errors_text()
        assert "Exception during request handling" in errors
        assert "Traceback (most recent call last):" in errors
        assert "TypeError: cannot unpack" in errors
        assert "Starting" not in errors
        assert "Loaded" not in errors

    def test_warnings_include_traceback(self):
        viewer = LogViewer()
        lines = [
            "2025-03-15 10:00:00,000 999 WARNING db odoo.models: Deprecated field usage",
            "  some continuation detail",
            "2025-03-15 10:00:01,000 999 INFO db odoo.modules: Done",
        ]
        for line in lines:
            viewer.write_line(line)

        text = viewer.get_warnings_and_errors_text()
        assert "Deprecated field usage" in text
        assert "some continuation detail" in text
        assert "Done" not in text

    def test_no_traceback_between_separate_errors(self):
        viewer = LogViewer()
        lines = [
            "2025-03-15 10:00:00,000 999 ERROR db odoo.http: First error",
            "2025-03-15 10:00:01,000 999 INFO db odoo.modules: Info between",
            "2025-03-15 10:00:02,000 999 ERROR db odoo.http: Second error",
            "Traceback for second error",
        ]
        for line in lines:
            viewer.write_line(line)

        errors = viewer.get_errors_text()
        assert "First error" in errors
        assert "Info between" not in errors
        assert "Second error" in errors
        assert "Traceback for second error" in errors

    def test_raw_lines_inherit_previous_level(self):
        """RAW continuation lines after an ERROR are filtered with the ERROR."""
        viewer = LogViewer()
        lines = [
            "2025-03-15 10:00:00,000 999 INFO db odoo.modules: Starting",
            "2025-03-15 10:00:01,000 999 ERROR db odoo.http: Boom",
            "Traceback line 1",
            "Traceback line 2",
            "2025-03-15 10:00:02,000 999 INFO db odoo.modules: Done",
        ]
        for line in lines:
            viewer.write_line(line)

        # Filter to ERROR only — Traceback lines should still appear (inherited level)
        viewer.active_levels = frozenset({"ERROR"})
        visible = viewer.get_visible_text()
        assert "Boom" in visible
        assert "Traceback line 1" in visible
        assert "Traceback line 2" in visible
        assert "Starting" not in visible
        assert "Done" not in visible


class TestLanguageLoadScreen:
    """Test LanguageLoadScreen integration."""

    async def test_language_load_keybinding(self, mock_cmd, tmp_path):
        """'l' key opens LanguageLoadScreen."""
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("l")
            await pilot.pause(0.1)
            from odoodev.tui.screens import LanguageLoadScreen

            assert any(isinstance(s, LanguageLoadScreen) for s in app.screen_stack)

    async def test_language_load_screen_has_widgets(self, mock_cmd, tmp_path):
        """LanguageLoadScreen has input, checkbox, and buttons."""
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("l")
            await pilot.pause(0.1)
            from textual.widgets import Button, Checkbox, Input

            screen = app.screen_stack[-1]
            assert screen.query_one("#lang-input", Input) is not None
            assert screen.query_one("#lang-overwrite", Checkbox) is not None
            assert screen.query_one("#btn-load", Button) is not None
            assert screen.query_one("#btn-cancel", Button) is not None

    async def test_language_load_cancel(self, mock_cmd, tmp_path):
        """Cancel button dismisses the dialog."""
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("l")
            await pilot.pause(0.1)
            from odoodev.tui.screens import LanguageLoadScreen

            assert any(isinstance(s, LanguageLoadScreen) for s in app.screen_stack)
            # Click cancel
            cancel_btn = app.screen_stack[-1].query_one("#btn-cancel")
            cancel_btn.press()
            await pilot.pause(0.1)
            assert not any(isinstance(s, LanguageLoadScreen) for s in app.screen_stack)


class TestFilterBarClick:
    """Test clickable filter bar interactions."""

    async def test_filter_tab_click_toggles_level(self, mock_cmd, tmp_path):
        """Clicking a filter tab toggles that level on/off."""
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            log_viewer = app.query_one("#log-viewer", LogViewer)
            # All levels active by default
            assert "WARNING" in log_viewer.active_levels

            # Click the WARNING tab — toggles it off
            warning_tab = app.query_one("#tab-warning", FilterTab)
            await pilot.click(warning_tab)
            assert "WARNING" not in log_viewer.active_levels
            # Other levels untouched
            assert "ERROR" in log_viewer.active_levels

            # Click again — toggles WARNING back on
            await pilot.click(warning_tab)
            assert "WARNING" in log_viewer.active_levels

    async def test_filter_tab_click_updates_filter_bar(self, mock_cmd, tmp_path):
        """Clicking a filter tab updates the filter bar display."""
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            filter_bar = app.query_one("#filter-bar", FilterBar)
            # All levels active by default
            assert "ERROR" in filter_bar.active_levels

            error_tab = app.query_one("#tab-error", FilterTab)
            await pilot.click(error_tab)
            assert "ERROR" not in filter_bar.active_levels

    async def test_scroll_toggle_click(self, mock_cmd, tmp_path):
        """Clicking the scroll toggle changes auto-scroll state."""
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            log_viewer = app.query_one("#log-viewer", LogViewer)
            assert log_viewer.auto_scroll is True

            toggle = app.query_one("#scroll-toggle", ScrollToggle)
            await pilot.click(toggle)
            assert log_viewer.auto_scroll is False

            await pilot.click(toggle)
            assert log_viewer.auto_scroll is True

    async def test_filter_tabs_all_present(self, mock_cmd, tmp_path):
        """All five filter level tabs are rendered."""
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as _pilot:
            for level in ("debug", "info", "warning", "error", "critical"):
                tab = app.query_one(f"#tab-{level}", FilterTab)
                assert tab is not None


class TestSelectableRichLog:
    """Test SelectableRichLog text selection."""

    def test_get_selection_extracts_text(self):
        """get_selection extracts plain text from Strip buffer."""
        from rich.segment import Segment
        from textual.geometry import Offset
        from textual.selection import Selection
        from textual.strip import Strip

        log = SelectableRichLog()
        # Manually populate the lines buffer with Strip objects
        log.lines = [
            Strip([Segment("Line one content")]),
            Strip([Segment("Line two content")]),
            Strip([Segment("Line three content")]),
        ]

        # Selection uses Offset(x=column, y=line)
        # From line 0, col 0 to line 1, col 16
        selection = Selection(start=Offset(0, 0), end=Offset(16, 1))
        result = log.get_selection(selection)
        assert result is not None
        text, ending = result
        assert "Line one content" in text
        assert "Line two content" in text
        assert ending == "\n"

    def test_get_selection_empty_lines(self):
        """get_selection returns None for empty buffer."""
        from textual.geometry import Offset
        from textual.selection import Selection

        log = SelectableRichLog()
        log.lines = []
        selection = Selection(start=Offset(0, 0), end=Offset(10, 0))
        result = log.get_selection(selection)
        assert result is None

    def test_get_selection_single_line_partial(self):
        """get_selection can extract part of a single line."""
        from rich.segment import Segment
        from textual.geometry import Offset
        from textual.selection import Selection
        from textual.strip import Strip

        log = SelectableRichLog()
        log.lines = [
            Strip([Segment("Hello World")]),
        ]
        # Select "World" — Offset(x=column, y=line)
        selection = Selection(start=Offset(6, 0), end=Offset(11, 0))
        result = log.get_selection(selection)
        assert result is not None
        text, _ = result
        assert text == "World"


class TestClipboard:
    """Test clipboard copy functionality."""

    def test_copy_to_clipboard_returns_bool(self):
        result = OdooTuiApp._copy_to_clipboard("test")
        assert isinstance(result, bool)

    def test_copy_empty_string(self):
        assert OdooTuiApp._copy_to_clipboard("") is True


class TestSaveLog:
    """Test the 's' log export action."""

    async def test_save_log_writes_file(self, mock_cmd, tmp_path, monkeypatch):
        import pathlib

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.6)
            app.action_save_log()
            await pilot.pause(0.1)
        log_dir = home / "odoodev-logs"
        # db_name is detected from the mock log lines ("test_db") by the time we save.
        files = list(log_dir.glob("odoo_18_test_db_*.log"))
        assert len(files) == 1
        content = files[0].read_text()
        assert "Loading module base" in content

    async def test_save_log_empty_buffer_warns(self, mock_cmd, tmp_path, monkeypatch):
        import pathlib

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.6)
            app.action_clear_log()
            app.action_save_log()
            await pilot.pause(0.1)
        assert not (home / "odoodev-logs").exists()


class TestHelpScreen:
    """Test the '?' help overlay."""

    async def test_question_mark_opens_help(self, mock_cmd, tmp_path):
        from odoodev.tui.screens import HelpScreen

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("question_mark")
            await pilot.pause(0.1)
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause(0.1)
            assert not isinstance(app.screen, HelpScreen)

    def test_help_sections_cover_all_app_bindings(self):
        from odoodev.tui.app import OdooTuiApp
        from odoodev.tui.screens import HELP_SECTIONS

        documented = " ".join(f"{key} {desc}" for _, entries in HELP_SECTIONS for key, desc in entries).lower()
        for binding in OdooTuiApp.BINDINGS:
            key = binding.key if hasattr(binding, "key") else binding[0]
            normalized = {
                "question_mark": "?",
                "slash": "/",
                "1": "1-5",
                "2": "1-5",
                "3": "1-5",
                "4": "1-5",
                "5": "1-5",
            }.get(key, key)
            assert normalized.lower() in documented, f"Binding '{key}' missing from HELP_SECTIONS"


class TestExportModulesScreen:
    """Test the 'x' module CSV export dialog and action."""

    async def test_export_keybinding_opens_screen(self, mock_cmd, tmp_path):
        from odoodev.tui.screens import ExportModulesScreen

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("x")
            await pilot.pause(0.1)
            assert any(isinstance(s, ExportModulesScreen) for s in app.screen_stack)

    async def test_export_screen_has_widgets(self, mock_cmd, tmp_path):
        from textual.widgets import Button, RadioButton, RadioSet

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("x")
            await pilot.pause(0.1)
            screen = app.screen_stack[-1]
            assert screen.query_one("#export-options", RadioSet) is not None
            assert screen.query_one("#opt-all", RadioButton) is not None
            assert screen.query_one("#opt-all-no-ent", RadioButton) is not None
            assert screen.query_one("#opt-installed", RadioButton) is not None
            assert screen.query_one("#btn-export", Button) is not None
            assert screen.query_one("#btn-cancel", Button) is not None

    async def test_export_cancel_dismisses(self, mock_cmd, tmp_path):
        from odoodev.tui.screens import ExportModulesScreen

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("x")
            await pilot.pause(0.1)
            assert any(isinstance(s, ExportModulesScreen) for s in app.screen_stack)
            app.screen_stack[-1].query_one("#btn-cancel").press()
            await pilot.pause(0.1)
            assert not any(isinstance(s, ExportModulesScreen) for s in app.screen_stack)

    async def test_export_writes_csv(self, mock_cmd, tmp_path, monkeypatch):
        import pathlib
        from unittest.mock import MagicMock, patch

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))

        fake_modules = [
            {"id": 1, "name": "base", "installed_version": "18.0", "display_name": "Base"},
            {"id": 2, "name": "sale", "installed_version": "18.0", "display_name": "Sales"},
        ]
        with patch("odoodev.tui.xmlrpc_client.xmlrpc.client.ServerProxy") as mock_proxy_cls:
            mock_common = MagicMock()
            mock_common.authenticate.return_value = 2
            mock_object = MagicMock()
            mock_object.execute_kw.return_value = fake_modules
            mock_proxy_cls.side_effect = lambda url: mock_common if "common" in url else mock_object

            app = make_app(mock_cmd, tmp_path)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause(0.3)
                app._handle_export_modules(("installed", "v18_exam", False, False))
                await pilot.pause(0.1)

        files = list((home / "Downloads").glob("modules_v18_exam_installed_*.csv"))
        assert len(files) == 1
        content = files[0].read_text(encoding="utf-8")
        assert content.splitlines()[0] == ".id,name,installed_version,display_name"
        assert "base" in content
        assert "sale" in content

    async def test_export_empty_warns_no_file(self, mock_cmd, tmp_path, monkeypatch):
        import pathlib
        from unittest.mock import MagicMock, patch

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))

        with patch("odoodev.tui.xmlrpc_client.xmlrpc.client.ServerProxy") as mock_proxy_cls:
            mock_common = MagicMock()
            mock_common.authenticate.return_value = 2
            mock_object = MagicMock()
            mock_object.execute_kw.return_value = []
            mock_proxy_cls.side_effect = lambda url: mock_common if "common" in url else mock_object

            app = make_app(mock_cmd, tmp_path)
            async with app.run_test(size=(120, 30)) as pilot:
                await pilot.pause(0.3)
                app._handle_export_modules(("all", "v18_exam", False, False))
                await pilot.pause(0.1)

        assert not (home / "Downloads").exists()

    async def test_export_cancel_scope_none_is_noop(self, mock_cmd, tmp_path, monkeypatch):
        import pathlib

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            app._handle_export_modules(None)
            await pilot.pause(0.1)

        assert not (home / "Downloads").exists()

    async def test_export_db_field_prefilled_with_detected_db(self, mock_cmd, tmp_path):
        """The export dialog pre-fills the DB field with the live-detected database."""
        from textual.widgets import Input

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.6)  # let log-based DB detection run -> "test_db"
            await pilot.press("x")
            await pilot.pause(0.1)
            db_input = app.screen_stack[-1].query_one("#export-db", Input)
            assert db_input.value == "test_db"

    async def test_export_empty_db_keeps_dialog_open(self, mock_cmd, tmp_path):
        """Clearing the DB field and pressing Export must not dismiss the dialog."""
        from textual.widgets import Input

        from odoodev.tui.screens import ExportModulesScreen

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.6)
            await pilot.press("x")
            await pilot.pause(0.1)
            screen = app.screen_stack[-1]
            screen.query_one("#export-db", Input).value = ""
            screen.query_one("#btn-export").press()
            await pilot.pause(0.1)
            assert any(isinstance(s, ExportModulesScreen) for s in app.screen_stack)


class TestQuickMenu:
    """Test the 'm' quick action menu (folds up from the bottom)."""

    async def test_menu_keybinding_opens_screen(self, mock_cmd, tmp_path):
        from odoodev.tui.screens import QuickMenuScreen

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("m")
            await pilot.pause(0.1)
            assert any(isinstance(s, QuickMenuScreen) for s in app.screen_stack)

    async def test_menu_contains_action_options(self, mock_cmd, tmp_path):
        from textual.widgets import OptionList

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("m")
            await pilot.pause(0.1)
            option_list = app.screen_stack[-1].query_one("#quick-menu-list", OptionList)
            ids = set()
            for i in range(option_list.option_count):
                opt = option_list.get_option_at_index(i)
                if opt.id:
                    ids.add(opt.id)
            # Every action must be present — guards against silently dropping
            # (or clipping) a menu entry such as load_language.
            expected = {
                "filter_all",
                "filter_issues",
                "show_only_warning",
                "show_only_error",
                "show_only_critical",
                "show_only_info",
                "show_only_debug",
                "search",
                "clear_log",
                "save_log",
                "copy_visible",
                "copy_errors",
                "copy_warnings",
                "export_modules",
                "update_apps_list",
                "cleanup_modules",
                "restart",
                "update",
                "load_language",
                "backup_db",
                "switch_db",
            }
            assert expected <= ids

    async def test_menu_escape_closes(self, mock_cmd, tmp_path):
        from odoodev.tui.screens import QuickMenuScreen

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("m")
            await pilot.pause(0.1)
            await pilot.press("escape")
            await pilot.pause(0.1)
            assert not any(isinstance(s, QuickMenuScreen) for s in app.screen_stack)

    async def test_handle_menu_dispatches_action(self, mock_cmd, tmp_path):
        """_handle_menu runs the named action (export opens its dialog)."""
        from odoodev.tui.screens import ExportModulesScreen

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause(0.3)
            app._handle_menu("export_modules")
            await pilot.pause(0.1)
            assert any(isinstance(s, ExportModulesScreen) for s in app.screen_stack)

    async def test_handle_menu_none_is_noop(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(80, 30)) as pilot:
            await pilot.pause(0.3)
            app._handle_menu(None)  # must not raise
            await pilot.pause(0.1)

    async def test_menu_options_show_shortcut_keys(self, mock_cmd, tmp_path):
        """Each menu action shows its direct shortcut key (cheat-sheet)."""
        from textual.widgets import OptionList

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(80, 40)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("m")
            await pilot.pause(0.1)
            option_list = app.screen_stack[-1].query_one("#quick-menu-list", OptionList)
            prompts = {}
            for i in range(option_list.option_count):
                opt = option_list.get_option_at_index(i)
                if opt.id:
                    prompts[opt.id] = str(opt.prompt)
            assert "x" in prompts["export_modules"]
            assert "s" in prompts["save_log"]
            assert "0" in prompts["filter_all"]
            assert "Ctrl+L" in prompts["clear_log"]
            assert "r" in prompts["restart"]


class TestVersionDisplay:
    """Test the odoodev version label shown bottom-right."""

    async def test_version_label_shows_current_version(self, mock_cmd, tmp_path):
        from textual.widgets import Static

        from odoodev import __version__

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.2)
            label = app.query_one("#app-version", Static)
            assert __version__ in str(label.render())

    async def test_version_label_does_not_cover_footer(self, mock_cmd, tmp_path):
        """Regression: the version row must not overlap the footer's keys."""
        from textual.widgets import Footer, Static

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.2)
            footer = app.query_one(Footer)
            version = app.query_one("#app-version", Static)
            # Both visible with real height, on different rows (no overlap).
            assert footer.region.height >= 1
            assert version.region.height >= 1
            assert footer.region.y != version.region.y


class TestBackupScreen:
    """Test the 'b' database backup dialog and worker-based backup."""

    async def test_backup_keybinding_opens_screen(self, mock_cmd, tmp_path):
        from odoodev.tui.screens import BackupScreen

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("b")
            await pilot.pause(0.1)
            assert any(isinstance(s, BackupScreen) for s in app.screen_stack)

    async def test_backup_cancel_is_noop(self, mock_cmd, tmp_path, monkeypatch):
        import pathlib

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            app._handle_backup_db(None)
            await pilot.pause(0.1)
        assert not (home / "Downloads").exists()

    async def test_backup_sql_writes_to_downloads(self, mock_cmd, tmp_path, monkeypatch):
        import pathlib

        import odoodev.core.database as db_core

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setattr(pathlib.Path, "home", classmethod(lambda cls: home))

        def fake_sql(name, output_path, **params):
            with open(output_path, "w", encoding="utf-8") as fh:
                fh.write("SQL")
            return True

        monkeypatch.setattr(db_core, "backup_database_sql", fake_sql)

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            app._handle_backup_db(("sql", "v18_exam"))
            await app.workers.wait_for_complete()
            await pilot.pause(0.1)

        files = list((home / "Downloads").glob("v18_exam_*.sql"))
        assert len(files) == 1


class TestDbSwitchScreen:
    """Test the 'd' database switch dialog and restart wiring."""

    async def test_switch_keybinding_opens_screen(self, mock_cmd, tmp_path, monkeypatch):
        import odoodev.core.database as db_core

        monkeypatch.setattr(db_core, "list_databases", lambda **kw: ["v18_exam", "other"])

        from odoodev.tui.screens import DbSwitchScreen

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            await pilot.press("d")
            await pilot.pause(0.1)
            assert any(isinstance(s, DbSwitchScreen) for s in app.screen_stack)

    async def test_switch_restarts_with_new_db(self, mock_cmd, tmp_path):
        from unittest.mock import MagicMock

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            restart_mock = MagicMock()
            app._odoo.restart = restart_mock  # type: ignore[method-assign]
            app._handle_switch_db("newdb")
            await pilot.pause(0.1)
            restart_mock.assert_called_once_with(extra_args=["-d", "newdb"])
            assert app._db_name == "newdb"

    async def test_switch_same_or_none_is_noop(self, mock_cmd, tmp_path):
        from unittest.mock import MagicMock

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            restart_mock = MagicMock()
            app._odoo.restart = restart_mock  # type: ignore[method-assign]
            app._handle_switch_db(None)
            app._handle_switch_db(app._db_name)
            await pilot.pause(0.1)
            restart_mock.assert_not_called()


class TestModuleMaintenanceActions:
    """Test the 'a' (update apps list) and 'k' (cleanup) worker actions."""

    async def test_update_apps_list_calls_client(self, mock_cmd, tmp_path, monkeypatch):
        from unittest.mock import MagicMock

        import odoodev.tui.xmlrpc_client as xmlrpc_mod

        instance = MagicMock()
        instance.update_module_list.return_value = 4
        monkeypatch.setattr(xmlrpc_mod, "OdooXmlRpcClient", MagicMock(return_value=instance))

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            app.action_update_apps_list()
            await app.workers.wait_for_complete()
            await pilot.pause(0.1)
        instance.update_module_list.assert_called_once()

    async def test_cleanup_modules_calls_client(self, mock_cmd, tmp_path, monkeypatch):
        from unittest.mock import MagicMock

        import odoodev.tui.xmlrpc_client as xmlrpc_mod

        instance = MagicMock()
        instance.cleanup_uninstalled_modules.return_value = 7
        monkeypatch.setattr(xmlrpc_mod, "OdooXmlRpcClient", MagicMock(return_value=instance))

        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            app.action_cleanup_modules()
            await app.workers.wait_for_complete()
            await pilot.pause(0.1)
        instance.cleanup_uninstalled_modules.assert_called_once()
