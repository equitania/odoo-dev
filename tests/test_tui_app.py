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

    async def test_toggle_individual_levels_via_keyboard(self, mock_cmd, tmp_path):
        """Hotkeys 1-5 toggle individual levels independently."""
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            log_viewer = app.query_one("#log-viewer", LogViewer)
            # All levels active by default
            assert "DEBUG" in log_viewer.active_levels
            assert "INFO" in log_viewer.active_levels
            assert "WARNING" in log_viewer.active_levels
            assert "ERROR" in log_viewer.active_levels
            assert "CRITICAL" in log_viewer.active_levels

            # "1" toggles DEBUG off
            await pilot.press("1")
            assert "DEBUG" not in log_viewer.active_levels
            assert "INFO" in log_viewer.active_levels  # others untouched

            # "1" again toggles DEBUG back on
            await pilot.press("1")
            assert "DEBUG" in log_viewer.active_levels

            # "2" toggles INFO off
            await pilot.press("2")
            assert "INFO" not in log_viewer.active_levels

    async def test_filter_all_hotkey(self, mock_cmd, tmp_path):
        """'0' restores all levels active."""
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            log_viewer = app.query_one("#log-viewer", LogViewer)
            await pilot.press("1")  # disable DEBUG
            await pilot.press("2")  # disable INFO
            assert "DEBUG" not in log_viewer.active_levels
            assert "INFO" not in log_viewer.active_levels

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
            assert status_bar.db_name == "v18_exam"

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
