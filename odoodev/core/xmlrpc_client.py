"""XML-RPC client for Odoo module operations.

Uses Python stdlib xmlrpc.client to communicate with a running Odoo
instance for hot module upgrades without server restart.
"""

from __future__ import annotations

import socket
import xmlrpc.client

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


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
        use_https: Use https:// scheme instead of http://. Credentials are
            transmitted in the XML-RPC body, so HTTPS is required for any
            non-local host to avoid plaintext password leakage.
        allow_insecure_remote: Explicit opt-in to speak plaintext HTTP to a
            non-local host. Use only in trusted LANs — otherwise prefer
            ``use_https=True``.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8069,
        database: str = "",
        username: str = "admin",
        password: str = "admin",  # noqa: S107 — dev tool default, not a real secret
        timeout: int = 10,
        use_https: bool = False,
        allow_insecure_remote: bool = False,
    ) -> None:
        self._host = host
        self._port = port
        self._database = database
        self._username = username
        self._password = password
        self._timeout = timeout
        self._uid: int | None = None

        is_local = host in _LOCAL_HOSTS
        if not is_local and not use_https and not allow_insecure_remote:
            msg = (
                f"Refusing plaintext XML-RPC to remote host {host!r} — "
                f"credentials would travel unencrypted. "
                f"Pass use_https=True for TLS or allow_insecure_remote=True "
                f"to override (trusted LAN only)."
            )
            raise ValueError(msg)

        scheme = "https" if use_https else "http"
        self._base_url = f"{scheme}://{host}:{port}"

        # Warn when user explicitly chose plaintext for a remote host
        if not is_local and not use_https:
            import logging

            logging.getLogger(__name__).warning(
                "XML-RPC connection to %s uses plaintext HTTP — credentials are not encrypted", host
            )

    @classmethod
    def from_stored_credentials(cls, *, port: int, database: str, host: str = "localhost") -> OdooXmlRpcClient:
        """Build a client using the ``odoo_login`` section of the global config.

        Falls back to the admin/admin dev default when nothing is stored.
        Single seam for every TUI XML-RPC call site (update-list, cleanup,
        hot module update) so the same account works everywhere.
        """
        from odoodev.core.global_config import get_odoo_login_credentials

        username, password = get_odoo_login_credentials()
        return cls(host=host, port=port, database=database, username=username, password=password)

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

            # Odoo returns the numeric uid on success, False on bad credentials.
            if not isinstance(uid, int) or not uid:
                msg = f"Authentication failed for {self._username}@{self._database}"
                raise ValueError(msg)

            self._uid = uid
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

    def list_modules(self, installed_only: bool = False, exclude_enterprise: bool = False) -> list[dict[str, object]]:
        """List modules for the Releasemanager CSV export.

        Builds the server-side domain from the flags, then filters out test
        and hardware modules client-side (reliable substring handling instead
        of SQL ``LIKE`` underscore escaping). Themes are kept.

        Non-installable modules are excluded via ``state != 'uninstallable'``
        (not the ``installable`` field, which was removed from
        ``ir.module.module`` in Odoo 19); ``state`` is core across v16-v19.

        Args:
            installed_only: Restrict to ``state = installed`` modules.
            exclude_enterprise: Drop Odoo Enterprise modules (``license = OEEL-1``).

        Returns:
            List of dicts with 'id', 'name', 'installed_version', 'display_name'.
        """
        from odoodev.core.module_export import EXPORT_FIELDS, is_exportable_module

        domain: list[list[object]]
        if installed_only:
            domain = [["state", "=", "installed"]]
        else:
            domain = [["state", "!=", "uninstallable"]]
        if exclude_enterprise:
            domain.append(["license", "!=", "OEEL-1"])

        result = self._execute_kw(
            "ir.module.module",
            "search_read",
            [domain],
            {"fields": list(EXPORT_FIELDS), "order": "name asc"},
        )
        if not isinstance(result, list):
            return []
        return [r for r in result if is_exportable_module(str(r.get("name", "")))]

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

    def update_module_list(self) -> int:
        """Refresh the module list (equivalent to 'Update Apps List' in the UI).

        Re-scans the addons path so ``ir.module.module`` reflects the modules
        actually present on the current system's disk.

        Returns:
            Number of newly added module records (0 if the server returned no
            usable count).

        Raises:
            ConnectionError: If the server is not reachable.
        """
        result = self._execute_kw(
            "ir.module.module",
            "update_list",
            [],
        )
        # Odoo returns ``[updated, added]``; surface the added count for the UI.
        if isinstance(result, (list, tuple)) and len(result) >= 2:
            try:
                return int(result[1])
            except (TypeError, ValueError):
                return 0
        return 0

    def cleanup_uninstalled_modules(self) -> int:
        """Delete all ir.module.module records that are not installed.

        Removes stale catalog entries (``state != 'installed'``) that pollute
        the module list after restoring a database whose source config listed
        modules without installing them. Combine with :meth:`update_module_list`
        to rebuild the catalog from the current system.

        Returns:
            Number of deleted module records.

        Raises:
            ConnectionError: If the server is not reachable.
        """
        ids = self._execute_kw(
            "ir.module.module",
            "search",
            [[["state", "!=", "installed"]]],
        )
        if not isinstance(ids, list) or not ids:
            return 0

        self._execute_kw(
            "ir.module.module",
            "unlink",
            [ids],
        )
        return len(ids)
