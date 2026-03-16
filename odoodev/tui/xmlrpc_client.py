"""XML-RPC client for Odoo module operations.

Uses Python stdlib xmlrpc.client to communicate with a running Odoo
instance for hot module upgrades without server restart.
"""

from __future__ import annotations

import socket
import xmlrpc.client


class OdooXmlRpcClient:
    """XML-RPC client for Odoo module operations.

    Connects to a running Odoo instance to perform module upgrades
    without requiring a server restart.

    Args:
        host: Odoo server hostname.
        port: Odoo server port.
        database: Database name.
        username: Admin username (default: admin).
        password: Admin password (default: admin).
        timeout: Connection timeout in seconds.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8069,
        database: str = "",
        username: str = "admin",
        password: str = "admin",  # noqa: S107 — dev tool default, not a real secret
        timeout: int = 10,
    ) -> None:
        self._host = host
        self._port = port
        self._database = database
        self._username = username
        self._password = password
        self._timeout = timeout
        self._uid: int | None = None

        self._base_url = f"http://{host}:{port}"

        # Warn when transmitting credentials over plaintext to non-local hosts
        if host not in ("localhost", "127.0.0.1", "::1"):
            import logging

            logging.getLogger(__name__).warning(
                "XML-RPC connection to %s uses plaintext HTTP — credentials are not encrypted", host
            )

    def _get_proxy(self, service: str) -> xmlrpc.client.ServerProxy:
        """Create an XML-RPC proxy for the given service."""
        return xmlrpc.client.ServerProxy(
            f"{self._base_url}/xmlrpc/2/{service}",
        )

    def authenticate(self) -> int:
        """Authenticate and return the user ID.

        Returns:
            User ID on success.

        Raises:
            ConnectionError: If the server is not reachable.
            ValueError: If authentication fails.
        """
        try:
            common = self._get_proxy("common")
            # Set socket timeout for this call
            old_timeout = socket.getdefaulttimeout()
            socket.setdefaulttimeout(self._timeout)
            try:
                uid = common.authenticate(self._database, self._username, self._password, {})
            finally:
                socket.setdefaulttimeout(old_timeout)

            if not uid:
                msg = f"Authentication failed for {self._username}@{self._database}"
                raise ValueError(msg)

            self._uid = int(uid)
            return self._uid
        except (ConnectionRefusedError, OSError, TimeoutError) as e:
            msg = f"Cannot connect to Odoo at {self._base_url}: {e}"
            raise ConnectionError(msg) from e

    def _execute_kw(self, model: str, method: str, args: list, kwargs: dict | None = None) -> object:
        """Execute an Odoo RPC method.

        Args:
            model: Odoo model name (e.g. 'ir.module.module').
            method: Method name (e.g. 'search_read').
            args: Positional arguments.
            kwargs: Keyword arguments.

        Returns:
            Method result.
        """
        if self._uid is None:
            self.authenticate()

        models = self._get_proxy("object")
        return models.execute_kw(
            self._database,
            self._uid,
            self._password,
            model,
            method,
            args,
            kwargs or {},
        )

    def list_installed_modules(self) -> list[dict[str, object]]:
        """List all installed modules.

        Returns:
            List of dicts with 'id', 'name', 'shortdesc' keys.
        """
        result = self._execute_kw(
            "ir.module.module",
            "search_read",
            [[["state", "=", "installed"]]],
            {"fields": ["name", "shortdesc"]},
        )
        return result if isinstance(result, list) else []

    def find_modules(self, module_names: list[str]) -> list[int]:
        """Find module IDs by name.

        Args:
            module_names: List of technical module names.

        Returns:
            List of module record IDs.
        """
        result = self._execute_kw(
            "ir.module.module",
            "search",
            [[["name", "in", module_names], ["state", "=", "installed"]]],
        )
        return result if isinstance(result, list) else []

    def upgrade_modules(self, module_names: list[str]) -> bool:
        """Trigger module upgrade via XML-RPC.

        Finds the module IDs and calls button_immediate_upgrade.

        Args:
            module_names: List of technical module names to upgrade.

        Returns:
            True if upgrade was triggered successfully.

        Raises:
            ConnectionError: If the server is not reachable.
            ValueError: If no matching modules are found.
        """
        module_ids = self.find_modules(module_names)
        if not module_ids:
            found_names = ", ".join(module_names)
            msg = f"No installed modules found matching: {found_names}"
            raise ValueError(msg)

        self._execute_kw(
            "ir.module.module",
            "button_immediate_upgrade",
            [module_ids],
        )
        return True
