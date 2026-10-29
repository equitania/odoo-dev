"""Module-list CSV export for the odoodev TUI.

Produces the import-compatible Odoo CSV used by the Equitania Releasemanager
("Import Module CSV"): columns ``.id``, ``name``, ``installed_version``,
``display_name``. odoodev only manages v16-v20, so the "new" export format
(with the ``.id`` column, required since Odoo 13) always applies — no
version branching needed.

These are pure helpers — no Textual or Odoo runtime dependencies — so they
are easy to unit-test in isolation.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

# Import-compatible header, exactly matching the Odoo "RM" export template.
EXPORT_HEADER: tuple[str, ...] = (".id", "name", "installed_version", "display_name")

# Fields fetched from ir.module.module (Odoo returns the db id under "id").
EXPORT_FIELDS: tuple[str, ...] = ("id", "name", "installed_version", "display_name")

# Export scopes offered in the TUI dialog -> (installed_only, exclude_enterprise).
EXPORT_SCOPES: dict[str, tuple[bool, bool]] = {
    "all": (False, False),
    "all_no_enterprise": (False, True),
    "installed": (True, False),
}


def is_exportable_module(name: str) -> bool:
    """Return True if the module belongs in the export.

    Excludes test modules (``test_*``) and hardware modules (containing
    ``hw_``). Themes (``theme_*``) are always kept — they match no exclusion
    rule, so no special-casing is required.
    """
    if name.startswith("test_"):
        return False
    if "hw_" in name:
        return False
    return True


def _csv_cell(value: object) -> str:
    """Render an Odoo field value as a CSV cell (False/None -> empty string)."""
    if value is False or value is None:
        return ""
    return str(value)


def write_modules_csv(records: list[dict[str, object]], path: Path) -> None:
    """Write module records to ``path`` as import-compatible CSV.

    Each record is a dict with the keys from ``EXPORT_FIELDS`` (as returned by
    ``ir.module.module.search_read``). The ``id`` field is written under the
    ``.id`` column header expected by the Releasemanager import. Missing or
    ``False`` values (e.g. ``installed_version`` for uninstalled modules)
    become empty cells. The parent directory is created if needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(EXPORT_HEADER)
        for record in records:
            writer.writerow(
                [
                    _csv_cell(record.get("id")),
                    _csv_cell(record.get("name")),
                    _csv_cell(record.get("installed_version")),
                    _csv_cell(record.get("display_name")),
                ]
            )


SHELL_EXPORT_MARKER = "odoodev-export-result: "


def build_shell_export_script(
    installed_only: bool, exclude_enterprise: bool, do_cleanup: bool, do_update: bool, with_records: bool = True
) -> str:
    """Build the ``odoo-bin shell`` script behind the login-free module export.

    The shell's ``env`` runs as the superuser, so this works on databases
    without a usable admin login (demo databases). It mirrors the XML-RPC path:
    cleanup first, then update, then the same domain as
    ``OdooXmlRpcClient.list_modules``. ``odoo-bin shell`` rolls back on exit,
    so the maintenance steps ``env.cr.commit()`` explicitly. The result is one
    ``SHELL_EXPORT_MARKER`` line with a JSON object, because Odoo may log to
    stdout as well. ``with_records=False`` runs only the maintenance steps
    (the TUI's ``a``/``k`` fallback) and reports an empty module list.
    """
    if installed_only:
        domain: list[tuple[str, str, str]] = [("state", "=", "installed")]
    else:
        domain = [("state", "!=", "uninstallable")]
    if exclude_enterprise:
        domain.append(("license", "!=", "OEEL-1"))
    return (
        "import json as _json\n"
        "_M = env['ir.module.module']\n"
        "_cleaned = None\n"
        "_updated = None\n"
        f"if {do_cleanup!r}:\n"
        "    _stale = _M.search([('state', '!=', 'installed')])\n"
        "    _cleaned = len(_stale)\n"
        "    _stale.unlink()\n"
        "    env.cr.commit()\n"
        f"if {do_update!r}:\n"
        "    _res = _M.update_list()\n"
        "    _updated = int(_res[1]) if isinstance(_res, (list, tuple)) and len(_res) >= 2 else 0\n"
        "    env.cr.commit()\n"
        "_records = []\n"
        f"if {with_records!r}:\n"
        f"    _records = _M.search_read({domain!r}, {list(EXPORT_FIELDS)!r}, order='name asc')\n"
        f"print({SHELL_EXPORT_MARKER!r} + _json.dumps("
        "{'records': _records, 'cleaned': _cleaned, 'updated': _updated}, default=str))\n"
    )


def parse_shell_export_output(stdout: str) -> dict[str, object]:
    """Extract the result object from the shell script's stdout.

    Returns a dict with ``records`` (filtered via :func:`is_exportable_module`,
    like the XML-RPC path), ``cleaned`` and ``updated``.

    Raises:
        ValueError: When the marker line is missing or not valid JSON.
    """
    import json

    for line in reversed(stdout.splitlines()):
        if line.startswith(SHELL_EXPORT_MARKER):
            data = json.loads(line[len(SHELL_EXPORT_MARKER) :])
            records = [r for r in data.get("records") or [] if is_exportable_module(str(r.get("name", "")))]
            return {"records": records, "cleaned": data.get("cleaned"), "updated": data.get("updated")}
    raise ValueError("odoo-bin shell returned no module list")


def build_export_path(db_name: str, scope: str, when: datetime, base_dir: Path | None = None) -> Path:
    """Build the target CSV path in the user's Downloads folder.

    Filename: ``modules_{db}_{scope}_{YYYYmmdd_HHMMSS}.csv``. ``base_dir``
    overrides the default ``~/Downloads`` (used by tests). This function has
    no side effects — directory creation happens in ``write_modules_csv``.
    """
    target_dir = base_dir if base_dir is not None else Path.home() / "Downloads"
    safe_db = (db_name or "nodb").replace("/", "-")
    timestamp = when.strftime("%Y%m%d_%H%M%S")
    return target_dir / f"modules_{safe_db}_{scope}_{timestamp}.csv"
