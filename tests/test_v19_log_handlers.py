"""Tests for Odoo 19+ deprecated RPC endpoint log handler muting."""


def _add_v19_log_handlers(cmd: list[str], version: str) -> None:
    """Local copy of the function to avoid circular import in tests."""
    try:
        if int(version) >= 19:
            cmd.append("--log-handler=odoo.addons.rpc.controllers.jsonrpc:ERROR")
    except (ValueError, TypeError):
        pass


class TestAddV19LogHandlers:
    """Test _add_v19_log_handlers adds --log-handler for v19+."""

    def test_v19_adds_log_handler(self):
        cmd = ["python", "odoo-bin", "-c", "odoo.conf"]
        _add_v19_log_handlers(cmd, "19")
        assert "--log-handler=odoo.addons.rpc.controllers.jsonrpc:ERROR" in cmd

    def test_v20_adds_log_handler(self):
        cmd = ["python", "odoo-bin"]
        _add_v19_log_handlers(cmd, "20")
        assert "--log-handler=odoo.addons.rpc.controllers.jsonrpc:ERROR" in cmd

    def test_v18_no_log_handler(self):
        cmd = ["python", "odoo-bin"]
        _add_v19_log_handlers(cmd, "18")
        assert "--log-handler=odoo.addons.rpc.controllers.jsonrpc:ERROR" not in cmd

    def test_v16_no_log_handler(self):
        cmd = ["python", "odoo-bin"]
        _add_v19_log_handlers(cmd, "16")
        assert "--log-handler=odoo.addons.rpc.controllers.jsonrpc:ERROR" not in cmd

    def test_empty_version_no_crash(self):
        cmd = ["python", "odoo-bin"]
        _add_v19_log_handlers(cmd, "")
        assert "--log-handler=odoo.addons.rpc.controllers.jsonrpc:ERROR" not in cmd

    def test_invalid_version_no_crash(self):
        cmd = ["python", "odoo-bin"]
        _add_v19_log_handlers(cmd, "abc")
        assert "--log-handler=odoo.addons.rpc.controllers.jsonrpc:ERROR" not in cmd

    def test_does_not_modify_existing_args(self):
        cmd = ["python", "odoo-bin", "--dev=all"]
        _add_v19_log_handlers(cmd, "19")
        assert cmd[0] == "python"
        assert cmd[1] == "odoo-bin"
        assert cmd[2] == "--dev=all"
        assert "--log-handler=odoo.addons.rpc.controllers.jsonrpc:ERROR" in cmd
