"""Playbook engine for YAML-driven automation of odoodev commands."""

from __future__ import annotations

import time
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
        "env.check",
        "venv.check",
        "venv.setup",
    }
)


# --- Dataclasses ---


@dataclass(frozen=True)
class StepConfig:
    """Configuration for a single playbook step."""

    name: str
    command: str
    args: dict[str, Any] = field(default_factory=dict)
    on_error: str = ""  # "" = inherit from playbook, "stop", "continue"


@dataclass(frozen=True)
class PlaybookConfig:
    """Configuration for a complete playbook."""

    version: str
    on_error: str  # "stop" | "continue"
    steps: tuple[StepConfig, ...]


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

    return PlaybookConfig(version=version, on_error=on_error, steps=steps)


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


# --- Runner ---


class PlaybookRunner:
    """Execute playbook steps sequentially using automation handlers."""

    def __init__(self) -> None:
        # Lazy import to avoid circular dependencies
        from odoodev.core.automation import COMMAND_HANDLERS

        self._handlers = COMMAND_HANDLERS

    def execute(
        self,
        playbook: PlaybookConfig,
        version_override: str | None = None,
        dry_run: bool = False,
        playbook_name: str = "<inline>",
    ) -> PlaybookResult:
        """Execute all steps in a playbook.

        Args:
            playbook: The playbook configuration to execute.
            version_override: Override the playbook's version.
            dry_run: If True, show steps without executing.
            playbook_name: Name for result reporting.

        Returns:
            PlaybookResult with all step results.
        """
        from odoodev.core.version_registry import get_version

        version = version_override or playbook.version
        version_cfg = get_version(version)

        results: list[StepResult] = []
        start_time = time.monotonic()
        aborted = False

        for step in playbook.steps:
            if aborted:
                results.append(
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

            if dry_run:
                args_str = f" ({step.args})" if step.args else ""
                results.append(
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
                    result = handler(version_cfg, step.args)
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

            results.append(result)

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
