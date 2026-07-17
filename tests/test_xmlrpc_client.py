"""Tests for odoodev.core.xmlrpc_client."""

from unittest.mock import MagicMock, patch

import pytest

from odoodev.core.xmlrpc_client import OdooXmlRpcClient


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

    def test_from_stored_credentials(self, monkeypatch):
        """The factory pulls the odoo_login section of the global config."""
        monkeypatch.setattr(
            "odoodev.core.global_config.get_odoo_login_credentials",
            lambda: ("stored_user", "stored_pw"),
        )
        client = OdooXmlRpcClient.from_stored_credentials(port=18069, database="v18_exam")
        assert client._username == "stored_user"
        assert client._password == "stored_pw"
        assert client._port == 18069
        assert client._database == "v18_exam"
        assert client._host == "localhost"


class TestRemoteHostSafety:
    """Test plaintext HTTP safeguards for non-local hosts."""

    def test_no_warning_for_localhost(self, caplog):
        """No warning emitted for localhost connections."""
        import logging

        with caplog.at_level(logging.WARNING, logger="odoodev.core.xmlrpc_client"):
            OdooXmlRpcClient(host="localhost", port=8069, database="test")
        assert "plaintext HTTP" not in caplog.text

    def test_no_warning_for_127(self, caplog):
        """No warning emitted for 127.0.0.1."""
        import logging

        with caplog.at_level(logging.WARNING, logger="odoodev.core.xmlrpc_client"):
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

        with caplog.at_level(logging.WARNING, logger="odoodev.core.xmlrpc_client"):
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

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_authenticate_success(self, mock_proxy_cls, client):
        mock_proxy = MagicMock()
        mock_proxy.authenticate.return_value = 2
        mock_proxy_cls.return_value = mock_proxy

        uid = client.authenticate()
        assert uid == 2
        assert client._uid == 2

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_authenticate_failure(self, mock_proxy_cls, client):
        mock_proxy = MagicMock()
        mock_proxy.authenticate.return_value = False
        mock_proxy_cls.return_value = mock_proxy

        with pytest.raises(ValueError, match="Authentication failed"):
            client.authenticate()

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_authenticate_connection_error(self, mock_proxy_cls, client):
        mock_proxy = MagicMock()
        mock_proxy.authenticate.side_effect = ConnectionRefusedError("Connection refused")
        mock_proxy_cls.return_value = mock_proxy

        with pytest.raises(ConnectionError, match="Cannot connect"):
            client.authenticate()


class TestListInstalledModules:
    """Test module listing."""

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
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

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
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


class TestListModules:
    """Test the Releasemanager CSV export listing."""

    @staticmethod
    def _wire(mock_proxy_cls, records):
        mock_common = MagicMock()
        mock_common.authenticate.return_value = 2
        mock_object = MagicMock()
        mock_object.execute_kw.return_value = records

        def proxy_factory(url):
            if "common" in url:
                return mock_common
            return mock_object

        mock_proxy_cls.side_effect = proxy_factory
        return mock_object

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_all_modules_domain(self, mock_proxy_cls, client):
        """Default flags -> exclude only non-installable modules (state-based)."""
        mock_object = self._wire(mock_proxy_cls, [{"id": 1, "name": "base"}])
        client.list_modules()
        mock_object.execute_kw.assert_called_once_with(
            "v18_exam",
            2,
            "admin",
            "ir.module.module",
            "search_read",
            [[["state", "!=", "uninstallable"]]],
            {"fields": ["id", "name", "installed_version", "display_name"], "order": "name asc"},
        )

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_installed_only_domain(self, mock_proxy_cls, client):
        mock_object = self._wire(mock_proxy_cls, [])
        client.list_modules(installed_only=True)
        args = mock_object.execute_kw.call_args.args
        assert args[5] == [[["state", "=", "installed"]]]

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_exclude_enterprise_domain(self, mock_proxy_cls, client):
        mock_object = self._wire(mock_proxy_cls, [])
        client.list_modules(exclude_enterprise=True)
        args = mock_object.execute_kw.call_args.args
        assert args[5] == [[["state", "!=", "uninstallable"], ["license", "!=", "OEEL-1"]]]

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_domain_never_uses_removed_installable_field(self, mock_proxy_cls, client):
        """Regression: 'installable' was removed from ir.module.module in v19."""
        mock_object = self._wire(mock_proxy_cls, [])
        for kwargs in ({}, {"installed_only": True}, {"exclude_enterprise": True}):
            mock_object.execute_kw.reset_mock()
            client.list_modules(**kwargs)
            domain = mock_object.execute_kw.call_args.args[5]
            fields = [cond[0] for cond in domain[0]]
            assert "installable" not in fields

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_test_and_hw_filtered_theme_kept(self, mock_proxy_cls, client):
        """test_/hw_ modules are dropped client-side; theme_ survives."""
        self._wire(
            mock_proxy_cls,
            [
                {"id": 1, "name": "base"},
                {"id": 2, "name": "test_lint"},
                {"id": 3, "name": "hw_escpos"},
                {"id": 4, "name": "theme_clean"},
            ],
        )
        names = [r["name"] for r in client.list_modules()]
        assert names == ["base", "theme_clean"]

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_non_list_result_returns_empty(self, mock_proxy_cls, client):
        self._wire(mock_proxy_cls, False)
        assert client.list_modules() == []


class TestFindModules:
    """Test module ID lookup."""

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
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

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
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

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
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


class TestUpdateModuleList:
    """Test the 'Update Apps List' (update_list) wrapper."""

    @staticmethod
    def _wire(mock_proxy_cls, result):
        mock_common = MagicMock()
        mock_common.authenticate.return_value = 2
        mock_object = MagicMock()
        mock_object.execute_kw.return_value = result
        mock_proxy_cls.side_effect = lambda url: mock_common if "common" in url else mock_object
        return mock_object

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_calls_update_list_with_no_args(self, mock_proxy_cls, client):
        mock_object = self._wire(mock_proxy_cls, [3, 5])
        added = client.update_module_list()
        assert added == 5
        mock_object.execute_kw.assert_called_once_with(
            "v18_exam",
            2,
            "admin",
            "ir.module.module",
            "update_list",
            [],
            {},
        )

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_non_tuple_result_returns_zero(self, mock_proxy_cls, client):
        self._wire(mock_proxy_cls, None)
        assert client.update_module_list() == 0


class TestCleanupUninstalledModules:
    """Test removal of non-installed module catalog entries."""

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_searches_non_installed_then_unlinks(self, mock_proxy_cls, client):
        mock_common = MagicMock()
        mock_common.authenticate.return_value = 2
        mock_object = MagicMock()
        # First call: search -> ids, second call: unlink -> True
        mock_object.execute_kw.side_effect = [[7, 8, 9], True]
        mock_proxy_cls.side_effect = lambda url: mock_common if "common" in url else mock_object

        removed = client.cleanup_uninstalled_modules()
        assert removed == 3

        search_args = mock_object.execute_kw.call_args_list[0].args
        assert search_args[4] == "search"
        assert search_args[5] == [[["state", "!=", "installed"]]]
        unlink_args = mock_object.execute_kw.call_args_list[1].args
        assert unlink_args[4] == "unlink"
        assert unlink_args[5] == [[7, 8, 9]]

    @patch("odoodev.core.xmlrpc_client.xmlrpc.client.ServerProxy")
    def test_no_matches_skips_unlink(self, mock_proxy_cls, client):
        mock_common = MagicMock()
        mock_common.authenticate.return_value = 2
        mock_object = MagicMock()
        mock_object.execute_kw.return_value = []
        mock_proxy_cls.side_effect = lambda url: mock_common if "common" in url else mock_object

        removed = client.cleanup_uninstalled_modules()
        assert removed == 0
        # Only the search call happened — no unlink.
        assert mock_object.execute_kw.call_count == 1
