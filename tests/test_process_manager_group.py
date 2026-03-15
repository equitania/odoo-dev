"""Tests for stop_process_group in process_manager."""

from odoodev.core.process_manager import stop_process_group


class TestStopProcessGroup:
    """Test process group termination."""

    def test_stop_nonexistent_group(self):
        # PID 99999 is unlikely to exist
        result = stop_process_group(99999)
        assert result is True  # ProcessLookupError → already gone

    def test_stop_returns_bool(self):
        result = stop_process_group(99999, timeout=1)
        assert isinstance(result, bool)

    def test_force_nonexistent(self):
        result = stop_process_group(99999, force=True)
        assert result is True
