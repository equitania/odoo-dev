"""Wizard field schema for the playbook assistant — single source of truth.

Drives BOTH the interactive ``odoodev playbook create`` wizard and the
machine-readable ``odoodev playbook schema --json`` output that the GUI
(odoodev-gui) renders its own form from. Pure data: no questionary/click
imports, so ``schema --json`` never pulls in interactive dependencies.

Field types are deliberately GUI-widget-flavored, not a JSON-Schema dialect:
``text | password | select | checkbox | confirm | path | int | json |
list[str] | list[sql] | map[str] | map[secret_text]``.

``depends_on``/``depends_value`` is a flat single-condition model (no boolean
trees) — sufficient for every conditional in the wizard, documented as a
known limitation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# v2 (0.55.0): source-first server flow — new server_source section (source.mode),
# restore always part of the recipe, server-side paths as plain text fields.
# v3 (0.57.0): fresh_backup hands the created file to the restore via
# ``backup_source.mode: from_backup_step`` (no pattern fields); the neutralize
# decision moved into the restore's sanitize question (recipe.neutralize is
# still accepted in answers files, the wizard derives it).
# The ANSWERS format is backward compatible across v1-v3 (targets + recipe).
SCHEMA_VERSION = 3

PLAYBOOK_TYPES = ("dev", "server")

# Mirror source modes (server_source section / wizard source question).
SOURCE_FRESH_BACKUP = "fresh_backup"
SOURCE_EXISTING_FILE = "existing_file"
SOURCE_NEWEST_IN_DIR = "newest_in_dir"

# Sanitize flags offered for restore steps (server.restore / db.restore args).
SANITIZE_FLAGS = ("deactivate_cron", "neutralize", "anonymize", "wipe", "purge_transactions")
SANITIZE_FLAGS_DEFAULT = ("deactivate_cron", "neutralize")

# Dev-mode step commands grouped for the checkbox UI (canonical execution order).
DEV_STEP_GROUPS: dict[str, tuple[str, ...]] = {
    "Docker": ("docker.up", "docker.down", "docker.status"),
    "Code & Repos": ("pull", "repos"),
    "Database": ("db.list", "db.backup", "db.restore", "db.drop", "db.purge"),
    "Environment": ("env.check", "venv.check", "venv.setup"),
    "Server": ("start", "stop"),
}
DEV_STEPS_DEFAULT = ("pull", "repos", "start")

# Canonical execution order for dev steps assembled by the builder.
DEV_STEP_ORDER = (
    "docker.up",
    "docker.status",
    "pull",
    "repos",
    "env.check",
    "venv.check",
    "venv.setup",
    "db.list",
    "db.backup",
    "db.restore",
    "db.drop",
    "db.purge",
    "start",
    "stop",
    "docker.down",
)

# SQL statement presets offered by the sql.execute statement builder.
# ``env_keys`` are flagged for the secrets step when the preset is chosen.
SQL_PRESETS: dict[str, dict[str, Any]] = {
    "enterprise_code": {
        "label_key": "playbook.server.sql.preset_enterprise",
        "statements": [
            "UPDATE ir_config_parameter SET value = '{{ env.PARTNER_ENTERPRISE_CODE }}' "
            "WHERE key = 'database.enterprise_code';",
        ],
        "env_keys": ("PARTNER_ENTERPRISE_CODE",),
    },
    "clear_eq_cloud": {
        "label_key": "playbook.server.sql.preset_eq_cloud",
        "statements": [
            "UPDATE ir_config_parameter SET value = '' WHERE key IN ("
            "'eq_cloud_base.eq_cloud_password','eq_cloud_base.eq_cloud_url',"
            "'eq_cloud_base.eq_cloud_username','eq_cloud_base.eq_is_cloud_connector_enabled');",
            "UPDATE res_users SET eq_client_id = NULL, eq_tenant_id = NULL, "
            "eq_client_secret = NULL, eq_access_allowed = FALSE;",
        ],
        "env_keys": (),
    },
    "website_domain": {
        "label_key": "playbook.server.sql.preset_website",
        # {domain} is filled from the wizard/GUI prompt before the statement lands in answers.
        "statements": ["UPDATE website SET domain = '{domain}';"],
        "env_keys": (),
        "prompt_key": "domain",
        "prompt_default": "https://{{ vars.customer }}-test.ownerp.app",
    },
}

# Env vars the rpc: connection block falls back to (odoo-rollout compatible,
# mirrors playbook._RPC_ENV_FALLBACKS) — offered in the secrets step.
RPC_ENV_KEYS = ("ODOO_URL", "ODOO_USER", "ODOO_PASSWORD", "ODOO_DATABASE", "ODOO_PORT", "ODOO_PROTOCOL")

# Secret keys are masked in the wizard when their name matches one of these markers.
SECRET_NAME_MARKERS = ("PASSWORD", "SECRET", "TOKEN", "KEY", "CODE")


@dataclass(frozen=True)
class WizardField:
    """One answerable field of the playbook assistant."""

    key: str
    type: str
    label_key: str
    required: bool = False
    default: Any = None
    choices: tuple[str, ...] | None = None
    choices_source: str = ""  # named dynamic source, resolved at schema-dump time
    depends_on: str = ""
    depends_value: Any = None
    secret: bool = False

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "key": self.key,
            "type": self.type,
            "label_key": self.label_key,
            "required": self.required,
            "default": list(self.default) if isinstance(self.default, tuple) else self.default,
        }
        if self.choices is not None:
            data["choices"] = list(self.choices)
        if self.choices_source:
            data["choices_source"] = self.choices_source
        if self.depends_on:
            data["depends_on"] = self.depends_on
            data["depends_value"] = self.depends_value
        if self.secret:
            data["secret"] = True
        return data


@dataclass(frozen=True)
class WizardSection:
    """A group of fields; ``repeatable`` sections collect a list/map of items."""

    key: str
    applies_to: tuple[str, ...]
    fields: tuple[WizardField, ...] = ()
    repeatable: bool = False
    min_items: int = 0
    item_fields: tuple[WizardField, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "key": self.key,
            "applies_to": list(self.applies_to),
            "fields": [f.to_dict() for f in self.fields],
        }
        if self.repeatable:
            data["repeatable"] = True
            data["min_items"] = self.min_items
            data["item_fields"] = [f.to_dict() for f in self.item_fields]
        return data


def _f(key: str, type_: str, label_key: str, **kwargs: Any) -> WizardField:
    return WizardField(key=key, type=type_, label_key=label_key, **kwargs)


SECTIONS: tuple[WizardSection, ...] = (
    WizardSection(
        key="playbook_type",
        applies_to=PLAYBOOK_TYPES,
        fields=(
            _f(
                "playbook_type",
                "select",
                "playbook.type.question",
                required=True,
                choices=PLAYBOOK_TYPES,
                default="server",
            ),
        ),
    ),
    WizardSection(
        key="common",
        applies_to=PLAYBOOK_TYPES,
        fields=(
            _f("name", "text", "playbook.common.name", required=True),
            _f("description", "text", "playbook.common.description"),
            _f("version", "select", "playbook.common.version", required=True, choices_source="available_versions"),
            _f("on_error", "select", "playbook.common.on_error", choices=("stop", "continue"), default="stop"),
        ),
    ),
    WizardSection(
        key="server_targets",
        applies_to=("server",),
        repeatable=True,
        min_items=1,
        item_fields=(
            _f("name", "text", "playbook.server.target.name", required=True),
            _f("db_container", "text", "playbook.server.target.db_container", required=True),
            _f("db_name", "text", "playbook.server.target.db_name", required=True),
            _f("odoo_container", "text", "playbook.server.target.odoo_container", default=""),
            _f("owner", "text", "playbook.server.target.owner", default="ownerp"),
            _f("data_dir", "text", "playbook.server.target.data_dir", default=""),
        ),
    ),
    # The mirror SOURCE (asked before the destination). ``source.mode`` is a
    # wizard-guidance field: ``fresh_backup`` implies a source target block +
    # ``recipe.backup.enabled: true`` + ``backup_source.mode: from_backup_step``
    # (the restore consumes the exact file that backup step creates — no
    # pattern questions); the two file-based modes fill
    # ``recipe.restore.backup_source`` instead.
    # All paths below live on the SERVER — render them as plain text inputs,
    # never expand/validate them on the machine running the wizard/GUI.
    WizardSection(
        key="server_source",
        applies_to=("server",),
        fields=(
            _f(
                "source.mode",
                "select",
                "playbook.server.source.question",
                required=True,
                choices=(SOURCE_FRESH_BACKUP, SOURCE_EXISTING_FILE, SOURCE_NEWEST_IN_DIR),
                default=SOURCE_FRESH_BACKUP,
            ),
            _f(
                "recipe.backup.backup_dir",
                "text",
                "playbook.server.recipe.backup_dir",
                required=True,
                default="/opt/backups/docker",
                depends_on="source.mode",
                depends_value=SOURCE_FRESH_BACKUP,
            ),
            _f(
                "recipe.backup.compression_level",
                "int",
                "playbook.server.recipe.compression_level",
                default=5,
                depends_on="source.mode",
                depends_value=SOURCE_FRESH_BACKUP,
            ),
            _f(
                "recipe.backup.only_sql",
                "confirm",
                "playbook.server.recipe.only_sql",
                default=False,
                depends_on="source.mode",
                depends_value=SOURCE_FRESH_BACKUP,
            ),
            _f(
                "recipe.restore.backup_source.path",
                "text",
                "playbook.server.restore.source_path",
                depends_on="source.mode",
                depends_value=SOURCE_EXISTING_FILE,
            ),
            _f(
                "recipe.restore.backup_source.dir",
                "text",
                "playbook.server.restore.source_dir",
                depends_on="source.mode",
                depends_value=SOURCE_NEWEST_IN_DIR,
            ),
            _f(
                "recipe.restore.backup_source.pattern",
                "text",
                "playbook.server.restore.source_pattern",
                depends_on="source.mode",
                depends_value=SOURCE_NEWEST_IN_DIR,
            ),
            _f(
                "recipe.restore.backup_source.select_by",
                "select",
                "playbook.server.restore.select_by",
                choices=("mtime", "filename_timestamp"),
                default="mtime",
                depends_on="source.mode",
                depends_value=SOURCE_NEWEST_IN_DIR,
            ),
        ),
    ),
    # Optional recipe items — server.restore itself is ALWAYS part of the mirror.
    WizardSection(
        key="server_recipe",
        applies_to=("server",),
        fields=(
            _f("recipe.rebuild.enabled", "confirm", "playbook.server.recipe.rebuild", default=False),
            _f(
                "recipe.rebuild.target",
                "select",
                "playbook.server.recipe.rebuild_target",
                choices_source="targets",
                depends_on="recipe.rebuild.enabled",
                depends_value=True,
            ),
            _f(
                "recipe.rebuild.script_path",
                "text",
                "playbook.server.recipe.rebuild_script",
                default="~/update_docker_odoo.py",
                depends_on="recipe.rebuild.enabled",
                depends_value=True,
            ),
            _f(
                "recipe.rebuild.config",
                "text",
                "playbook.server.recipe.rebuild_config",
                default="~/docker2update.yaml",
                depends_on="recipe.rebuild.enabled",
                depends_value=True,
            ),
            _f(
                "recipe.rebuild.timeout",
                "int",
                "playbook.server.recipe.rebuild_timeout",
                default=7200,
                depends_on="recipe.rebuild.enabled",
                depends_value=True,
            ),
            _f("recipe.stop_before_restore", "confirm", "playbook.server.recipe.stop_before", default=True),
            _f(
                "recipe.restore.template",
                "text",
                "playbook.server.restore.template",
                default="template0",
            ),
            _f(
                "recipe.restore.drop",
                "confirm",
                "playbook.server.restore.drop",
                default=True,
            ),
            _f(
                "recipe.restore.sanitize_flags",
                "checkbox",
                "playbook.server.restore.sanitize",
                choices=SANITIZE_FLAGS,
                default=SANITIZE_FLAGS_DEFAULT,
            ),
            _f(
                "recipe.restore.purge_master_data",
                "confirm",
                "playbook.server.restore.purge_master_data",
                default=False,
            ),
            _f("recipe.sql_after_restore.enabled", "confirm", "playbook.server.recipe.sql", default=False),
            _f(
                "recipe.sql_after_restore.statements",
                "list[sql]",
                "playbook.server.sql.statements",
                depends_on="recipe.sql_after_restore.enabled",
                depends_value=True,
            ),
            _f(
                "recipe.sql_after_restore.on_error",
                "select",
                "playbook.server.sql.on_error",
                choices=("stop", "continue"),
                default="continue",
                depends_on="recipe.sql_after_restore.enabled",
                depends_value=True,
            ),
            _f("recipe.start_after_restore", "confirm", "playbook.server.recipe.start_after", default=True),
            _f("recipe.update_all.enabled", "confirm", "playbook.server.recipe.update_all", default=True),
            _f(
                "recipe.update_all.restart",
                "confirm",
                "playbook.server.recipe.update_all_restart",
                default=True,
                depends_on="recipe.update_all.enabled",
                depends_value=True,
            ),
            _f(
                "recipe.update_all.on_error",
                "select",
                "playbook.server.recipe.update_all_on_error",
                choices=("stop", "continue"),
                default="continue",
                depends_on="recipe.update_all.enabled",
                depends_value=True,
            ),
            _f("recipe.rpc_call.enabled", "confirm", "playbook.server.recipe.rpc_call", default=False),
            _f(
                "recipe.rpc_call.model",
                "text",
                "playbook.server.rpc.model",
                required=True,
                depends_on="recipe.rpc_call.enabled",
                depends_value=True,
            ),
            _f(
                "recipe.rpc_call.mode",
                "select",
                "playbook.server.rpc.mode",
                choices=("method", "domain_values", "domain_method"),
                default="method",
                depends_on="recipe.rpc_call.enabled",
                depends_value=True,
            ),
            _f(
                "recipe.rpc_call.method",
                "text",
                "playbook.server.rpc.method",
                depends_on="recipe.rpc_call.enabled",
                depends_value=True,
            ),
            _f(
                "recipe.rpc_call.args",
                "json",
                "playbook.server.rpc.args",
                depends_on="recipe.rpc_call.mode",
                depends_value="method",
            ),
            _f(
                "recipe.rpc_call.kwargs",
                "json",
                "playbook.server.rpc.kwargs",
                depends_on="recipe.rpc_call.mode",
                depends_value="method",
            ),
            _f(
                "recipe.rpc_call.domain",
                "json",
                "playbook.server.rpc.domain",
                depends_on="recipe.rpc_call.enabled",
                depends_value=True,
            ),
            _f(
                "recipe.rpc_call.values",
                "json",
                "playbook.server.rpc.values",
                depends_on="recipe.rpc_call.mode",
                depends_value="domain_values",
            ),
        ),
    ),
    WizardSection(
        key="server_extra_steps",
        applies_to=("server",),
        repeatable=True,
        min_items=0,
        item_fields=(
            _f(
                "command",
                "select",
                "playbook.server.extra_step.command",
                required=True,
                choices_source="server_commands",
            ),
            _f("name", "text", "playbook.server.extra_step.name"),
            _f("args", "map[str]", "playbook.server.extra_step.args"),
            _f(
                "on_error",
                "select",
                "playbook.server.extra_step.on_error",
                choices=("", "stop", "continue"),
                default="",
            ),
        ),
    ),
    WizardSection(
        key="server_rpc",
        applies_to=("server",),
        fields=(
            _f("rpc.enabled", "confirm", "playbook.server.rpc.configure", default=False),
            _f(
                "rpc.host",
                "text",
                "playbook.server.rpc.host",
                default="{{ env.ODOO_URL }}",
                depends_on="rpc.enabled",
                depends_value=True,
            ),
            _f("rpc.db", "text", "playbook.server.rpc.db", depends_on="rpc.enabled", depends_value=True),
        ),
    ),
    WizardSection(
        key="vars",
        applies_to=PLAYBOOK_TYPES,
        fields=(_f("vars", "map[str]", "playbook.common.vars"),),
    ),
    WizardSection(
        key="dev_steps",
        applies_to=("dev",),
        fields=(
            _f(
                "dev_steps",
                "checkbox",
                "playbook.dev.steps.question",
                choices=tuple(cmd for group in DEV_STEP_GROUPS.values() for cmd in group),
                default=DEV_STEPS_DEFAULT,
            ),
        ),
    ),
    WizardSection(
        key="secrets",
        applies_to=PLAYBOOK_TYPES,
        fields=(
            _f("env_file.generate", "confirm", "playbook.secrets.generate", default=True),
            _f("env_file.path", "path", "playbook.secrets.path", depends_on="env_file.generate", depends_value=True),
            _f(
                "env_file.secrets",
                "map[secret_text]",
                "playbook.secrets.values",
                secret=True,
                depends_on="env_file.generate",
                depends_value=True,
            ),
        ),
    ),
    WizardSection(
        key="output",
        applies_to=PLAYBOOK_TYPES,
        fields=(_f("output_path", "path", "playbook.output.path"),),
    ),
)


# ---------------------------------------------------------------------------
# Step argument specs (descriptive only — the runner enforces nothing here).
# Used by the dev-branch per-step prompts and exposed via `schema --json`.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepArg:
    name: str
    type: str
    required: bool = False
    default: Any = None
    choices: tuple[str, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"name": self.name, "type": self.type, "required": self.required}
        if self.default is not None:
            data["default"] = list(self.default) if isinstance(self.default, tuple) else self.default
        if self.choices is not None:
            data["choices"] = list(self.choices)
        return data


@dataclass(frozen=True)
class StepSpec:
    command: str
    mode: str  # "dev" | "server"
    args: tuple[StepArg, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {"command": self.command, "mode": self.mode, "args": [a.to_dict() for a in self.args]}


def _a(name: str, type_: str, **kwargs: Any) -> StepArg:
    return StepArg(name=name, type=type_, **kwargs)


STEP_ARG_SPECS: dict[str, StepSpec] = {
    spec.command: spec
    for spec in (
        # --- dev-mode steps ---
        StepSpec("docker.up", "dev"),
        StepSpec("docker.down", "dev"),
        StepSpec("docker.status", "dev"),
        StepSpec("pull", "dev", (_a("config", "path"), _a("verbose", "confirm", default=False))),
        StepSpec(
            "repos",
            "dev",
            (
                _a("config", "path"),
                _a("config-only", "confirm", default=False),
                _a("server-only", "confirm", default=False),
                _a("skip-access-check", "confirm", default=False),
                _a("verbose", "confirm", default=False),
            ),
        ),
        StepSpec(
            "start",
            "dev",
            (
                _a("mode", "select", default="normal", choices=("normal", "dev", "test")),
                _a("config", "path"),
                _a("extra_args", "list[str]"),
            ),
        ),
        StepSpec(
            "stop",
            "dev",
            (
                _a("keep-docker", "confirm", default=False),
                _a("force", "confirm", default=False),
            ),
        ),
        StepSpec("db.list", "dev"),
        StepSpec(
            "db.backup",
            "dev",
            (
                _a("name", "text", required=True),
                _a("type", "select", default="sql", choices=("sql", "zip")),
                _a("output", "path", default="."),
            ),
        ),
        StepSpec(
            "db.restore",
            "dev",
            (
                _a("name", "text", required=True),
                _a("backup-file", "path", required=True),
                _a("drop", "confirm", default=True),
                _a("sanitize", "confirm", default=False),
                _a("deactivate-cron", "confirm"),
                _a("neutralize", "confirm"),
                _a("anonymize", "confirm"),
                _a("wipe", "confirm"),
                _a("purge-transactions", "confirm", default=False),
                _a("recompute", "confirm"),
                _a("uninstall-modules", "text"),
                _a("anonymize-users", "confirm", default=False),
                _a("reset-passwords", "confirm", default=False),
                _a("reset-2fa", "confirm", default=False),
                _a("user-password", "text"),
            ),
        ),
        StepSpec("db.drop", "dev", (_a("name", "text", required=True),)),
        StepSpec("db.purge", "dev", (_a("name", "text", required=True),)),
        StepSpec("env.check", "dev"),
        StepSpec("venv.check", "dev"),
        StepSpec("venv.setup", "dev"),
        # --- server-mode steps ---
        StepSpec(
            "container.stop",
            "server",
            (
                _a("target", "text"),
                _a("container", "text"),
                _a("component", "select", default="odoo", choices=("odoo", "db")),
                _a("timeout", "int", default=30),
            ),
        ),
        StepSpec(
            "container.start",
            "server",
            (
                _a("target", "text"),
                _a("container", "text"),
                _a("component", "select", default="odoo", choices=("odoo", "db")),
            ),
        ),
        StepSpec(
            "server.backup",
            "server",
            (
                _a("target", "text"),
                _a("backup_dir", "text", required=True),
                _a("compression_level", "int", default=5),
                _a("only_sql", "confirm", default=False),
            ),
        ),
        StepSpec(
            "server.rebuild",
            "server",
            (
                _a("target", "text"),
                _a("container", "text"),
                _a("script_path", "text", default="~/update_docker_odoo.py"),
                _a("config", "text", default="~/docker2update.yaml"),
                _a("timeout", "int", default=7200),
                _a("extra_args", "list[str]"),
            ),
        ),
        StepSpec(
            "server.restore",
            "server",
            (
                _a("target", "text"),
                _a("backup_source", "json", required=True),
                _a("template", "text", default="template0"),
                _a("drop", "confirm", default=True),
                _a("check_space", "confirm", default=True),
                _a("allow_missing_filestore", "confirm", default=False),
                _a("sanitize", "confirm", default=False),
                _a("deactivate_cron", "confirm"),
                _a("neutralize", "confirm"),
                _a("anonymize", "confirm"),
                _a("wipe", "confirm"),
                _a("purge_transactions", "confirm", default=False),
                _a("purge_master_data", "confirm", default=False),
            ),
        ),
        StepSpec(
            "server.neutralize",
            "server",
            (
                _a("target", "text"),
                _a("odoo_bin_path", "text"),
                _a("config_path", "text"),
            ),
        ),
        StepSpec(
            "server.update-all",
            "server",
            (
                _a("target", "text"),
                _a("restart", "confirm", default=True),
                _a("extra_args", "list[str]"),
                _a("odoo_bin_path", "text"),
                _a("config_path", "text"),
            ),
        ),
        StepSpec(
            "sql.execute",
            "server",
            (
                _a("target", "text"),
                _a("db_name", "text"),
                _a("statements", "list[sql]"),
                _a("file", "text"),
            ),
        ),
        StepSpec(
            "rpc.execute",
            "server",
            (
                _a("model", "text", required=True),
                _a("method", "text"),
                _a("args", "json"),
                _a("kwargs", "json"),
                _a("domain", "json"),
                _a("values", "json"),
            ),
        ),
    )
}


def _resolve_choices_source(source: str) -> list[str]:
    """Resolve a named dynamic choices source into a concrete list."""
    if source == "available_versions":
        from odoodev.core.version_registry import available_versions

        return available_versions()
    if source == "server_commands":
        from odoodev.core.playbook import SERVER_COMMANDS

        return sorted(SERVER_COMMANDS)
    if source == "targets":
        return []  # only resolvable at answer time (depends on the user's target list)
    return []


def wizard_schema(playbook_type: str | None = None) -> dict[str, Any]:
    """The full assistant schema as a JSON-serializable dict.

    Named ``choices_source`` entries are resolved to concrete lists where
    statically possible so the GUI needs no second endpoint; ``targets``
    stays a source reference (it depends on the user's own target answers).
    """
    sections = []
    for section in SECTIONS:
        if playbook_type and playbook_type not in section.applies_to:
            continue
        data = section.to_dict()
        for field_data in list(data.get("fields", [])) + list(data.get("item_fields", [])):
            source = field_data.get("choices_source", "")
            if source and source != "targets":
                field_data["choices"] = _resolve_choices_source(source)
        sections.append(data)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "odoodev playbook schema",
        "playbook_types": list(PLAYBOOK_TYPES),
        "sections": sections,
        "dev_step_groups": {group: list(cmds) for group, cmds in DEV_STEP_GROUPS.items()},
        "sql_presets": {
            name: {k: (list(v) if isinstance(v, tuple) else v) for k, v in preset.items()}
            for name, preset in SQL_PRESETS.items()
        },
        "rpc_env_keys": list(RPC_ENV_KEYS),
        "step_args": {command: spec.to_dict() for command, spec in STEP_ARG_SPECS.items()},
    }
