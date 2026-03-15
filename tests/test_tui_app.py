"""Tests for odoodev.tui app, widgets, and screens."""

import sys

import pytest
from textual.widgets import Static

from odoodev.tui.app import FILTER_LEVELS, OdooTuiApp
from odoodev.tui.widgets.log_viewer import LEVEL_STYLES, LogViewer
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
            assert app.query_one("#filter-bar", Static) is not None
            assert app.query_one("#log-viewer", LogViewer) is not None

    async def test_app_receives_log_output(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            # Wait for process to produce output
            await pilot.pause(1.0)
            log_viewer = app.query_one("#log-viewer", LogViewer)
            assert log_viewer.entry_count > 0

    async def test_cycle_filter(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            log_viewer = app.query_one("#log-viewer", LogViewer)
            assert log_viewer.min_level == "DEBUG"

            await pilot.press("f")
            assert log_viewer.min_level == "INFO"

            await pilot.press("f")
            assert log_viewer.min_level == "WARNING"

    async def test_toggle_auto_scroll(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            log_viewer = app.query_one("#log-viewer", LogViewer)
            assert log_viewer.auto_scroll is True

            await pilot.press("space")
            assert log_viewer.auto_scroll is False

            await pilot.press("space")
            assert log_viewer.auto_scroll is True

    async def test_clear_log(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.5)
            await pilot.press("ctrl+l")
            # Buffer preserved, display cleared
            log_viewer = app.query_one("#log-viewer", LogViewer)
            assert log_viewer.entry_count > 0  # Buffer still has entries

    async def test_quit_stops_process(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.3)
            assert app._odoo.is_running is True
            await pilot.press("q")
        # After exit, process should be stopped
        assert app._odoo.is_running is False

    async def test_status_bar_updates(self, mock_cmd, tmp_path):
        app = make_app(mock_cmd, tmp_path)
        async with app.run_test(size=(120, 30)) as pilot:
            await pilot.pause(0.5)
            status_bar = app.query_one("#status-bar", StatusBar)
            assert status_bar.version == "18"
            assert status_bar.port == 18069
            assert status_bar.db_name == "v18_exam"
