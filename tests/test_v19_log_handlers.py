"""Tests for Odoo 19+ deprecated RPC endpoint log handler muting."""

from __future__ import annotations

# Import cli first to resolve the circular import chain (cli → start → cli)
import odoodev.cli  # noqa: F401
from odoodev.commands.start import _add_v19_log_handlers

XMLRPC_HANDLER = "--log-handler=odoo.addons.rpc.controllers.xmlrpc:ERROR"
JSONRPC_HANDLER = "--log-handler=odoo.addons.rpc.controllers.jsonrpc:ERROR"


class TestAddV19LogHandlers:
    """Test _add_v19_log_handlers adds --log-handler for v19+."""

    def test_v19_mutes_both_controllers(self):
        cmd = ["python", "odoo-bin", "-c", "odoo.conf"]
        _add_v19_log_handlers(cmd, "19")
        # The xmlrpc handler is the one that silences the TUI module-export warning.
        assert XMLRPC_HANDLER in cmd
        assert JSONRPC_HANDLER in cmd

    def test_v20_mutes_both_controllers(self):
        cmd = ["python", "odoo-bin"]
        _add_v19_log_handlers(cmd, "20")
        assert XMLRPC_HANDLER in cmd
        assert JSONRPC_HANDLER in cmd

    def test_v18_no_log_handler(self):
        cmd = ["python", "odoo-bin"]
        _add_v19_log_handlers(cmd, "18")
        assert XMLRPC_HANDLER not in cmd
        assert JSONRPC_HANDLER not in cmd

    def test_v16_no_log_handler(self):
        cmd = ["python", "odoo-bin"]
        _add_v19_log_handlers(cmd, "16")
        assert XMLRPC_HANDLER not in cmd

    def test_empty_version_no_crash(self):
        cmd = ["python", "odoo-bin"]
        _add_v19_log_handlers(cmd, "")
        assert XMLRPC_HANDLER not in cmd

    def test_invalid_version_no_crash(self):
        cmd = ["python", "odoo-bin"]
        _add_v19_log_handlers(cmd, "abc")
        assert XMLRPC_HANDLER not in cmd

    def test_does_not_modify_existing_args(self):
        cmd = ["python", "odoo-bin", "--dev=all"]
        _add_v19_log_handlers(cmd, "19")
        assert cmd[0] == "python"
        assert cmd[1] == "odoo-bin"
        assert cmd[2] == "--dev=all"
        assert XMLRPC_HANDLER in cmd
