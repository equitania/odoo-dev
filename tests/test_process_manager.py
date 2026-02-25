"""Tests for odoodev.core.process_manager."""

from __future__ import annotations

from odoodev.core.process_manager import find_odoo_process, is_odoo_running, stop_process


class TestFindOdooProcess:
    def test_find_no_process_on_unused_port(self):
        # Port 1 is never used in normal operation (requires root)
        pids = find_odoo_process(1)
        assert isinstance(pids, list)
        assert pids == []

    def test_find_returns_list(self):
        result = find_odoo_process(65000)
        assert isinstance(result, list)
        for pid in result:
            assert isinstance(pid, int)


class TestIsOdooRunning:
    def test_not_running_on_unused_port(self):
        assert is_odoo_running(1) is False

    def test_not_running_on_high_port(self):
        assert is_odoo_running(65001) is False


class TestStopProcess:
    def test_stop_nonexistent_pid_returns_false(self):
        # PID 999999 almost certainly does not exist
        result = stop_process(999999)
        assert result is False

    def test_stop_nonexistent_pid_does_not_raise(self):
        # Must not raise any exception
        try:
            stop_process(999998)
        except Exception as exc:
            assert False, f"stop_process raised unexpectedly: {exc}"
