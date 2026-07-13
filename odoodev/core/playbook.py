"""Playbook engine for YAML-driven automation of odoodev commands."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# --- Valid commands for playbook steps ---

VALID_COMMANDS = frozenset(
    {
        "docker.up",
        "docker.down",
        "docker.status",
        "pull",
        "repos",
        "start",
        "stop",
        "db.list",
        "db.backup",
        "db.restore",
        "db.drop",
        "db.purge",
        "env.check",
        "venv.check",
        "venv.setup",
        # Server-mode steps (customer servers: Docker containers only, no dev layout)
        "container.stop",
        "container.start",
        "server.backup",
        "server.restore",
        "server.neutralize",
        "server.update-all",
        "sql.execute",
        "rpc.execute",
    }
)

# Subset of VALID_COMMANDS that only makes sense on customer servers (requires a
# ``targets:`` block); used for capability listing, never for validation.
SERVER_COMMANDS = frozenset(
    {
        "container.stop",
        "container.start",
        "server.backup",
        "server.restore",
        "server.neutralize",
        "server.update-all",
        "sql.execute",
        "rpc.execute",
    }
)

# Convention (odoo-rollout compatible): connection fields for rpc.execute that are
# not set in the playbook's ``rpc:`` section fall back to these environment
# variables (process env merged with the playbook's ``env_file``).
_RPC_ENV_FALLBACKS = {
    "host": "ODOO_URL",
    "port": "ODOO_PORT",
    "user": "ODOO_USER",
    "password": "ODOO_PASSWORD",
    "db": "ODOO_DATABASE",
    "protocol": "ODOO_PROTOCOL",
}


# --- Dataclasses ---


@dataclass(frozen=True)
class StepConfig:
    """Configuration for a single playbook step."""

    name: str
    command: str
    args: dict[str, Any] = field(default_factory=dict)
    on_error: str = ""  # "" = inherit from playbook, "stop", "continue"


@dataclass(frozen=True)
class TargetConfig:
    """A named server target: one Odoo/PostgreSQL container pair on a customer server."""

    db_container: str
    db_name: str
    odoo_container: str = ""
    owner: str = "ownerp"
    data_dir: str = ""  # host path of the Odoo data mount; empty = resolve via docker inspect


@dataclass(frozen=True)
class PlaybookConfig:
    """Configuration for a complete playbook."""

    version: str
    on_error: str  # "stop" | "continue"
    steps: tuple[StepConfig, ...]
    vars: dict[str, str] = field(default_factory=dict)
    description: str = ""
    targets: dict[str, TargetConfig] = field(default_factory=dict)
    env_file: str = ""
    rpc: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StepResult:
    """Result of executing a single playbook step."""

    name: str
    command: str
    status: str  # "ok" | "error" | "skipped"
    message: str
    exit_code: int
    duration_ms: int
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlaybookResult:
    """Result of executing a complete playbook."""

    playbook: str
    version: str
    status: str  # "ok" | "error"
    steps: tuple[StepResult, ...]
    total_duration_ms: int


# --- Validation ---


class PlaybookValidationError(Exception):
    """Raised when playbook YAML is invalid."""


def _validate_step(step_data: dict[str, Any], index: int) -> StepConfig:
    """Validate and parse a single step from YAML data.

    Args:
        step_data: Raw step dictionary from YAML.
        index: Step index for error messages.

    Returns:
        Validated StepConfig.

    Raises:
        PlaybookValidationError: If step data is invalid.
    """
    if not isinstance(step_data, dict):
        raise PlaybookValidationError(f"Step {index + 1}: must be a mapping, got {type(step_data).__name__}")

    name = step_data.get("name", f"Step {index + 1}")
    command = step_data.get("command")

    if not command:
        raise PlaybookValidationError(f"Step '{name}': missing required field 'command'")

    if command not in VALID_COMMANDS:
        raise PlaybookValidationError(
            f"Step '{name}': unknown command '{command}'. Valid commands: {', '.join(sorted(VALID_COMMANDS))}"
        )

    args = step_data.get("args", {})
    if not isinstance(args, dict):
        raise PlaybookValidationError(f"Step '{name}': 'args' must be a mapping, got {type(args).__name__}")

    on_error = step_data.get("on_error", "")
    if on_error and on_error not in ("stop", "continue"):
        raise PlaybookValidationError(f"Step '{name}': on_error must be 'stop' or 'continue', got '{on_error}'")

    return StepConfig(name=name, command=command, args=args, on_error=on_error)


def _validate_playbook(data: dict[str, Any]) -> PlaybookConfig:
    """Validate and parse playbook YAML data.

    Args:
        data: Raw YAML dictionary.

    Returns:
        Validated PlaybookConfig.

    Raises:
        PlaybookValidationError: If playbook data is invalid.
    """
    if not isinstance(data, dict):
        raise PlaybookValidationError(f"Playbook must be a mapping, got {type(data).__name__}")

    version = str(data.get("version", ""))
    if not version:
        raise PlaybookValidationError("Playbook: missing required field 'version'")

    on_error = data.get("on_error", "stop")
    if on_error not in ("stop", "continue"):
        raise PlaybookValidationError(f"Playbook: on_error must be 'stop' or 'continue', got '{on_error}'")

    steps_data = data.get("steps", [])
    if not isinstance(steps_data, list):
        raise PlaybookValidationError(f"Playbook: 'steps' must be a list, got {type(steps_data).__name__}")

    if not steps_data:
        raise PlaybookValidationError("Playbook: 'steps' must contain at least one step")

    steps = tuple(_validate_step(s, i) for i, s in enumerate(steps_data))

    vars_data = data.get("vars", {})
    if not isinstance(vars_data, dict):
        raise PlaybookValidationError(f"Playbook: 'vars' must be a mapping, got {type(vars_data).__name__}")
    playbook_vars = {str(k): str(v) for k, v in vars_data.items()}

    description = str(data.get("description", ""))

    targets = _validate_targets(data.get("targets", {}))

    env_file = str(data.get("env_file", "") or "")

    rpc_data = data.get("rpc", {})
    if not isinstance(rpc_data, dict):
        raise PlaybookValidationError(f"Playbook: 'rpc' must be a mapping, got {type(rpc_data).__name__}")

    return PlaybookConfig(
        version=version,
        on_error=on_error,
        steps=steps,
        vars=playbook_vars,
        description=description,
        targets=targets,
        env_file=env_file,
        rpc=rpc_data,
    )


def _validate_targets(targets_data: Any) -> dict[str, TargetConfig]:
    """Validate and parse the optional top-level ``targets:`` section."""
    if not targets_data:
        return {}
    if not isinstance(targets_data, dict):
        raise PlaybookValidationError(f"Playbook: 'targets' must be a mapping, got {type(targets_data).__name__}")

    targets: dict[str, TargetConfig] = {}
    for name, raw in targets_data.items():
        if not isinstance(raw, dict):
            raise PlaybookValidationError(f"Target '{name}': must be a mapping, got {type(raw).__name__}")
        db_container = str(raw.get("db_container", "") or "")
        db_name = str(raw.get("db_name", "") or "")
        if not db_container:
            raise PlaybookValidationError(f"Target '{name}': missing required field 'db_container'")
        if not db_name:
            raise PlaybookValidationError(f"Target '{name}': missing required field 'db_name'")
        targets[str(name)] = TargetConfig(
            db_container=db_container,
            db_name=db_name,
            odoo_container=str(raw.get("odoo_container", "") or ""),
            owner=str(raw.get("owner", "") or "ownerp"),
            data_dir=str(raw.get("data_dir", "") or ""),
        )
    return targets


# --- Loading ---


def load_playbook(path: str) -> PlaybookConfig:
    """Load and validate a playbook from a YAML file.

    Args:
        path: Path to the playbook YAML file.

    Returns:
        Validated PlaybookConfig.

    Raises:
        FileNotFoundError: If the file does not exist.
        PlaybookValidationError: If the playbook is invalid.
    """
    playbook_path = Path(path)
    if not playbook_path.exists():
        raise FileNotFoundError(f"Playbook not found: {path}")

    with open(playbook_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        raise PlaybookValidationError(f"Playbook file is empty: {path}")

    return _validate_playbook(data)


def build_playbook_from_steps(steps: list[str], version: str, on_error: str = "stop") -> PlaybookConfig:
    """Build a PlaybookConfig from inline step commands.

    Used for ``--step`` CLI mode: ``odoodev run --step docker.up --step pull 18``

    Args:
        steps: List of command strings (e.g. ["docker.up", "pull"]).
        version: Odoo version string.
        on_error: Default error handling ("stop" or "continue").

    Returns:
        PlaybookConfig with one StepConfig per command.

    Raises:
        PlaybookValidationError: If any command is invalid.
    """
    if not steps:
        raise PlaybookValidationError("No steps provided")

    if not version:
        raise PlaybookValidationError("Version is required")

    step_configs = []
    for cmd in steps:
        if cmd not in VALID_COMMANDS:
            raise PlaybookValidationError(
                f"Unknown command '{cmd}'. Valid commands: {', '.join(sorted(VALID_COMMANDS))}"
            )
        step_configs.append(StepConfig(name=cmd, command=cmd))

    return PlaybookConfig(version=version, on_error=on_error, steps=tuple(step_configs))


# --- Variable templating ---


def build_template_context(
    playbook_vars: dict[str, str],
    cli_vars: dict[str, str] | None = None,
    env_file_vars: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the Jinja2 context for step-arg rendering.

    Available in templates: ``{{ vars.x }}`` (playbook ``vars:`` block, CLI
    ``--var`` overrides win), ``{{ env.X }}`` (process environment, overlaid
    with the playbook's ``env_file`` values — the file wins) and ``{{ date }}``
    (today, ISO 8601).
    """
    import os
    from datetime import date

    merged = {**playbook_vars, **(cli_vars or {})}
    env = {**os.environ, **(env_file_vars or {})}
    return {"vars": merged, "env": env, "date": date.today().isoformat()}


def load_env_file(path: str) -> dict[str, str]:
    """Load a ``.env`` file for the playbook Jinja context (secrets stay out of YAML).

    Raises:
        PlaybookValidationError: If the file does not exist (a declared secrets
        file that is silently missing would produce empty credentials downstream).
    """
    import os

    expanded = os.path.expanduser(path)
    if not os.path.isfile(expanded):
        raise PlaybookValidationError(f"env_file not found: {path}")

    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(expanded).items() if v is not None}


def _render_value(value: Any, jenv: Any, context: dict[str, Any], key: str) -> Any:
    """Recursively render Jinja2 templates in strings inside nested dicts/lists."""
    from jinja2 import TemplateError

    if isinstance(value, str):
        try:
            return jenv.from_string(value).render(context)
        except TemplateError as exc:
            raise PlaybookValidationError(f"Template error in arg '{key}': {exc}") from exc
    if isinstance(value, dict):
        return {k: _render_value(v, jenv, context, f"{key}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [_render_value(v, jenv, context, f"{key}[{i}]") for i, v in enumerate(value)]
    return value


def render_step_args(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Render Jinja2 templates in step-arg values (sandboxed), recursively.

    Strings are rendered wherever they appear — including inside nested mappings
    (``backup_source:``) and lists (``statements:``). Other value types (bools,
    ints) pass through unchanged. Raises PlaybookValidationError on template
    syntax errors.
    """
    from jinja2.sandbox import SandboxedEnvironment

    jenv = SandboxedEnvironment()
    return {key: _render_value(value, jenv, context, key) for key, value in args.items()}


def _inject_target_context(step_args: dict[str, Any], targets: dict[str, TargetConfig]) -> dict[str, Any]:
    """Resolve a step's ``target`` reference into flat args before dispatch.

    No-op when the step has no ``target`` key. Explicit step args always win
    over target-derived values.

    Raises:
        PlaybookValidationError: If the referenced target is not defined.
    """
    target_name = step_args.get("target")
    if not isinstance(target_name, str) or not target_name:
        return step_args

    target = targets.get(target_name)
    if target is None:
        known = ", ".join(sorted(targets)) or "none defined"
        raise PlaybookValidationError(f"Unknown target '{target_name}'. Defined targets: {known}")

    derived = {
        "db_container": target.db_container,
        "db_name": target.db_name,
        "odoo_container": target.odoo_container,
        "owner": target.owner,
        "data_dir": target.data_dir,
    }
    return {**derived, **step_args}


def _resolve_rpc_config(rpc: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    """Render the playbook ``rpc:`` section and fill gaps from environment conventions.

    Fields absent from the section fall back to the odoo-rollout style variables
    (``ODOO_URL``/``ODOO_PORT``/``ODOO_USER``/``ODOO_PASSWORD``/``ODOO_DATABASE``/
    ``ODOO_PROTOCOL``) in the merged environment (process env + ``env_file``).
    """
    from jinja2.sandbox import SandboxedEnvironment

    jenv = SandboxedEnvironment()
    rendered = {key: _render_value(value, jenv, context, f"rpc.{key}") for key, value in rpc.items()}

    env = context.get("env", {})
    for field_name, env_var in _RPC_ENV_FALLBACKS.items():
        if not rendered.get(field_name) and env.get(env_var):
            rendered[field_name] = env[env_var]
    return rendered


# --- Runner ---


class PlaybookRunner:
    """Execute playbook steps sequentially using automation handlers."""

    def __init__(self) -> None:
        # Lazy import to avoid circular dependencies
        from odoodev.core.automation import COMMAND_HANDLERS
        from odoodev.core.server_automation import SERVER_COMMAND_HANDLERS

        self._handlers = {**COMMAND_HANDLERS, **SERVER_COMMAND_HANDLERS}

    def execute(
        self,
        playbook: PlaybookConfig,
        version_override: str | None = None,
        dry_run: bool = False,
        playbook_name: str = "<inline>",
        cli_vars: dict[str, str] | None = None,
        on_step: Callable[[StepResult], None] | None = None,
    ) -> PlaybookResult:
        """Execute all steps in a playbook.

        Args:
            playbook: The playbook configuration to execute.
            version_override: Override the playbook's version.
            dry_run: If True, show steps without executing.
            playbook_name: Name for result reporting.
            cli_vars: ``--var`` overrides for the playbook ``vars:`` block.
            on_step: Called with each StepResult as soon as the step finishes,
                enabling live progress output while the playbook is running.

        Returns:
            PlaybookResult with all step results.
        """
        from odoodev.core.version_registry import get_version

        version = version_override or playbook.version
        version_cfg = get_version(version)
        # Dry-run stays previewable on machines without the server's secrets file;
        # unresolved {{ env.X }} references simply render empty there.
        env_file_vars = load_env_file(playbook.env_file) if playbook.env_file and not dry_run else {}
        context = build_template_context(playbook.vars, cli_vars, env_file_vars)
        rpc_config = _resolve_rpc_config(playbook.rpc, context)

        results: list[StepResult] = []
        start_time = time.monotonic()
        aborted = False

        def record(result: StepResult) -> None:
            results.append(result)
            if on_step is not None:
                on_step(result)

        for step in playbook.steps:
            if aborted:
                record(
                    StepResult(
                        name=step.name,
                        command=step.command,
                        status="skipped",
                        message="Skipped due to previous error",
                        exit_code=-1,
                        duration_ms=0,
                    )
                )
                continue

            try:
                step_args = render_step_args(step.args, context)
                step_args = _inject_target_context(step_args, playbook.targets)
                if step.command == "rpc.execute" and "_rpc_config" not in step_args:
                    step_args["_rpc_config"] = rpc_config
            except PlaybookValidationError as exc:
                record(
                    StepResult(
                        name=step.name,
                        command=step.command,
                        status="error",
                        message=str(exc),
                        exit_code=1,
                        duration_ms=0,
                    )
                )
                if (step.on_error or playbook.on_error) == "stop":
                    aborted = True
                continue

            if dry_run:
                args_str = f" ({step_args})" if step_args else ""
                record(
                    StepResult(
                        name=step.name,
                        command=step.command,
                        status="ok",
                        message=f"[dry-run] Would execute: {step.command}{args_str}",
                        exit_code=0,
                        duration_ms=0,
                    )
                )
                continue

            handler = self._handlers.get(step.command)
            if not handler:
                result = StepResult(
                    name=step.name,
                    command=step.command,
                    status="error",
                    message=f"No handler for command '{step.command}'",
                    exit_code=1,
                    duration_ms=0,
                )
            else:
                step_start = time.monotonic()
                try:
                    result = handler(version_cfg, step_args)
                except Exception as exc:
                    duration_ms = int((time.monotonic() - step_start) * 1000)
                    result = StepResult(
                        name=step.name,
                        command=step.command,
                        status="error",
                        message=str(exc),
                        exit_code=1,
                        duration_ms=duration_ms,
                    )

            record(result)

            # Check on_error policy
            if result.status == "error":
                effective_on_error = step.on_error or playbook.on_error
                if effective_on_error == "stop":
                    aborted = True

        total_ms = int((time.monotonic() - start_time) * 1000)
        has_errors = any(r.status == "error" for r in results)

        return PlaybookResult(
            playbook=playbook_name,
            version=version,
            status="error" if has_errors else "ok",
            steps=tuple(results),
            total_duration_ms=total_ms,
        )
