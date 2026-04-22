"""Tests for odoodev.tui.xmlrpc_client."""

from unittest.mock import MagicMock, patch

import pytest

from odoodev.tui.xmlrpc_client import OdooXmlRpcClient


@pytest.fixture
def client():
    """Create a test XML-RPC client."""
    return OdooXmlRpcClient(
        host="localhost",
        port=18069,
        database="v18_exam",
        username="admin",
        password="admin",
    )


class TestOdooXmlRpcClientInit:
    """Test client initialization."""

    def test_default_values(self):
        client = OdooXmlRpcClient()
        assert client._host == "localhost"
        assert client._port == 8069
        assert client._username == "admin"

    def test_custom_values(self, client):
        assert client._port == 18069
        assert client._database == "v18_exam"
        assert client._base_url == "http://localhost:18069"


class TestRemoteHostSafety:
    """Test plaintext HTTP safeguards for non-local hosts."""

    def test_no_warning_for_localhost(self, caplog):
        """No warning emitted for localhost connections."""
        import logging

        with caplog.at_level(logging.WARNING, logger="odoodev.tui.xmlrpc_client"):
            OdooXmlRpcClient(host="localhost", port=8069, database="test")
        assert "plaintext HTTP" not in caplog.text

    def test_no_warning_for_127(self, caplog):
        """No warning emitted for 127.0.0.1."""
        import logging

        with caplog.at_level(logging.WARNING, logger="odoodev.tui.xmlrpc_client"):
            OdooXmlRpcClient(host="127.0.0.1", port=8069, database="test")
        assert "plaintext HTTP" not in caplog.text

    def test_remote_plaintext_blocked_by_default(self):
        """Remote hosts are blocked without explicit TLS or insecure opt-in."""
        with pytest.raises(ValueError, match="Refusing plaintext XML-RPC"):
            OdooXmlRpcClient(host="remote-server.example.com", port=8069, database="test")

    def test_remote_https_allowed(self):
        """use_https=True allows connections to remote hosts."""
        client = OdooXmlRpcClient(host="odoo.example.com", port=443, database="test", use_https=True)
        assert client._base_url == "https://odoo.example.com:443"

    def test_remote_insecure_opt_in_warns(self, caplog):
        """allow_insecure_remote=True connects over plaintext but logs a warning."""
        import logging

        with caplog.at_level(logging.WARNING, logger="odoodev.tui.xmlrpc_client"):
            client = OdooXmlRpcClient(
                host="remote-server.example.com",
                port=8069,
                database="test",
                allow_insecure_remote=True,
            )
        assert client._base_url == "http://remote-server.example.com:8069"
        assert "plaintext HTTP" in caplog.text
        assert "remote-server.example.com" in caplog.text


class TestAuthenticate:
    """Test authentication."""

    @patch("odoodev.tui.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_authenticate_success(self, mock_proxy_cls, client):
        mock_proxy = MagicMock()
        mock_proxy.authenticate.return_value = 2
        mock_proxy_cls.return_value = mock_proxy

        uid = client.authenticate()
        assert uid == 2
        assert client._uid == 2

    @patch("odoodev.tui.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_authenticate_failure(self, mock_proxy_cls, client):
        mock_proxy = MagicMock()
        mock_proxy.authenticate.return_value = False
        mock_proxy_cls.return_value = mock_proxy

        with pytest.raises(ValueError, match="Authentication failed"):
            client.authenticate()

    @patch("odoodev.tui.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_authenticate_connection_error(self, mock_proxy_cls, client):
        mock_proxy = MagicMock()
        mock_proxy.authenticate.side_effect = ConnectionRefusedError("Connection refused")
        mock_proxy_cls.return_value = mock_proxy

        with pytest.raises(ConnectionError, match="Cannot connect"):
            client.authenticate()


class TestListInstalledModules:
    """Test module listing."""

    @patch("odoodev.tui.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_list_modules(self, mock_proxy_cls, client):
        mock_common = MagicMock()
        mock_common.authenticate.return_value = 2
        mock_object = MagicMock()
        mock_object.execute_kw.return_value = [
            {"id": 1, "name": "base", "shortdesc": "Base"},
            {"id": 2, "name": "sale", "shortdesc": "Sales"},
        ]

        def proxy_factory(url):
            if "common" in url:
                return mock_common
            return mock_object

        mock_proxy_cls.side_effect = proxy_factory

        modules = client.list_installed_modules()
        assert len(modules) == 2
        assert modules[0]["name"] == "base"

    @patch("odoodev.tui.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_list_modules_empty(self, mock_proxy_cls, client):
        mock_common = MagicMock()
        mock_common.authenticate.return_value = 2
        mock_object = MagicMock()
        mock_object.execute_kw.return_value = []

        def proxy_factory(url):
            if "common" in url:
                return mock_common
            return mock_object

        mock_proxy_cls.side_effect = proxy_factory

        modules = client.list_installed_modules()
        assert modules == []


class TestFindModules:
    """Test module ID lookup."""

    @patch("odoodev.tui.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_find_existing_modules(self, mock_proxy_cls, client):
        mock_common = MagicMock()
        mock_common.authenticate.return_value = 2
        mock_object = MagicMock()
        mock_object.execute_kw.return_value = [42, 43]

        def proxy_factory(url):
            if "common" in url:
                return mock_common
            return mock_object

        mock_proxy_cls.side_effect = proxy_factory

        ids = client.find_modules(["eq_sale", "eq_stock"])
        assert ids == [42, 43]


class TestUpgradeModules:
    """Test module upgrade."""

    @patch("odoodev.tui.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_upgrade_success(self, mock_proxy_cls, client):
        mock_common = MagicMock()
        mock_common.authenticate.return_value = 2
        mock_object = MagicMock()
        # First call: find_modules (search), second call: button_immediate_upgrade
        mock_object.execute_kw.side_effect = [[42], True]

        def proxy_factory(url):
            if "common" in url:
                return mock_common
            return mock_object

        mock_proxy_cls.side_effect = proxy_factory

        result = client.upgrade_modules(["eq_sale"])
        assert result is True

    @patch("odoodev.tui.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_upgrade_no_modules_found(self, mock_proxy_cls, client):
        mock_common = MagicMock()
        mock_common.authenticate.return_value = 2
        mock_object = MagicMock()
        mock_object.execute_kw.return_value = []

        def proxy_factory(url):
            if "common" in url:
                return mock_common
            return mock_object

        mock_proxy_cls.side_effect = proxy_factory

        with pytest.raises(ValueError, match="No installed modules found"):
            client.upgrade_modules(["nonexistent_module"])
