"""Tests for odoodev.tui.odoo_process."""

import sys
import time

import pytest

from odoodev.tui.odoo_process import OdooProcess


@pytest.fixture
def echo_process(tmp_path):
    """Create an OdooProcess that echoes lines to stdout."""
    script = tmp_path / "echo_server.py"
    script.write_text(
        "import sys, time\n"
        "for i in range(10):\n"
        "    print(f'2025-03-15 10:00:0{i},000 999 INFO test_db odoo.test: Line {i}', flush=True)\n"
        "    time.sleep(0.05)\n"
        "# Keep running like a server\n"
        "try:\n"
        "    time.sleep(60)\n"
        "except (KeyboardInterrupt, SystemExit):\n"
        "    pass\n"
    )
    return OdooProcess(
        cmd=[sys.executable, str(script)],
        env={},
        cwd=str(tmp_path),
    )


@pytest.fixture
def quick_exit_process(tmp_path):
    """Create an OdooProcess that exits immediately after printing."""
    script = tmp_path / "quick_exit.py"
    script.write_text("print('2025-03-15 10:00:00,000 999 INFO db odoo.test: Done', flush=True)\n")
    return OdooProcess(
        cmd=[sys.executable, str(script)],
        env={},
        cwd=str(tmp_path),
    )


@pytest.fixture
def stubborn_process(tmp_path):
    """Create a process that ignores SIGTERM (for SIGKILL escalation test)."""
    script = tmp_path / "stubborn.py"
    script.write_text(
        "import signal, time\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        "print('2025-03-15 10:00:00,000 999 INFO db odoo.test: Stubborn', flush=True)\n"
        "while True:\n"
        "    time.sleep(0.1)\n"
    )
    return OdooProcess(
        cmd=[sys.executable, str(script)],
        env={},
        cwd=str(tmp_path),
    )


class TestOdooProcessLifecycle:
    """Test start/stop lifecycle."""

    def test_start_and_running(self, echo_process):
        echo_process.start()
        assert echo_process.is_running is True
        assert echo_process.pid is not None
        echo_process.stop()

    def test_stop_returns_true(self, echo_process):
        echo_process.start()
        assert echo_process.stop() is True
        assert echo_process.is_running is False

    def test_stop_when_not_started(self, echo_process):
        assert echo_process.stop() is True

    def test_double_start_noop(self, echo_process):
        echo_process.start()
        pid1 = echo_process.pid
        echo_process.start()  # Should not start a second process
        assert echo_process.pid == pid1
        echo_process.stop()

    def test_pid_none_after_stop(self, echo_process):
        echo_process.start()
        echo_process.stop()
        assert echo_process.pid is None

    def test_return_code_none_while_running(self, echo_process):
        echo_process.start()
        assert echo_process.return_code is None
        echo_process.stop()


class TestOdooProcessOutput:
    """Test output reading from subprocess."""

    def test_read_lines(self, echo_process):
        echo_process.start()
        time.sleep(0.8)  # Wait for echo script to produce output
        lines = echo_process.read_lines()
        assert len(lines) > 0
        assert any("Line 0" in line for line in lines)
        echo_process.stop()

    def test_read_lines_empty_initially(self, echo_process):
        echo_process.start()
        # Immediately read — may or may not have output yet
        lines = echo_process.read_lines()
        assert isinstance(lines, list)
        echo_process.stop()

    def test_quick_exit_output(self, quick_exit_process):
        quick_exit_process.start()
        time.sleep(0.3)  # Wait for process to finish
        lines = quick_exit_process.read_lines()
        assert any("Done" in line for line in lines)


class TestOdooProcessUptime:
    """Test uptime tracking."""

    def test_uptime_while_running(self, echo_process):
        echo_process.start()
        time.sleep(0.2)
        assert echo_process.uptime > 0.1
        echo_process.stop()

    def test_uptime_zero_when_stopped(self, echo_process):
        assert echo_process.uptime == 0.0


class TestOdooProcessRestart:
    """Test restart functionality."""

    def test_restart_changes_pid(self, echo_process):
        echo_process.start()
        pid1 = echo_process.pid
        echo_process.restart()
        pid2 = echo_process.pid
        assert pid2 is not None
        assert pid2 != pid1
        echo_process.stop()

    def test_restart_with_extra_args(self, tmp_path):
        script = tmp_path / "args_echo.py"
        script.write_text(
            "import sys, time\n"
            "print(' '.join(sys.argv[1:]), flush=True)\n"
            "try:\n"
            "    time.sleep(60)\n"
            "except (KeyboardInterrupt, SystemExit):\n"
            "    pass\n"
        )
        proc = OdooProcess(
            cmd=[sys.executable, str(script), "--base-arg"],
            env={},
            cwd=str(tmp_path),
        )
        proc.start()
        proc.restart(extra_args=["-u", "eq_sale"])
        time.sleep(0.3)
        lines = proc.read_lines()
        assert any("-u" in line and "eq_sale" in line for line in lines)
        proc.stop()


class TestOdooProcessSigkillEscalation:
    """Test that stubborn processes are killed via SIGKILL."""

    def test_stubborn_process_killed(self, stubborn_process):
        stubborn_process.start()
        assert stubborn_process.is_running is True
        # Short timeout to trigger SIGKILL escalation quickly
        result = stubborn_process.stop(timeout=1)
        assert result is True
        assert stubborn_process.is_running is False
