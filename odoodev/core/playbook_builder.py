"""Pure generator core for the playbook assistant: answers dict -> playbook YAML.

One input contract for both frontends: the interactive wizard
(``commands/playbook_cmd.py``) and the GUI's ``--answers file.json`` mode both
produce the same nested answers dict (see ``usage/playbook.md``) and feed it
through :func:`build_playbook_dict`. No questionary/click imports here.

Every generated playbook is round-trip validated through
:func:`odoodev.core.playbook._validate_playbook` before it is written, so
whatever the assistant emits is provably loadable by ``odoodev run``.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml

from odoodev.core.playbook import SERVER_COMMANDS, VALID_COMMANDS, PlaybookValidationError, _validate_playbook
from odoodev.core.playbook_schema import (
    DEV_STEP_ORDER,
    PLAYBOOK_TYPES,
    SANITIZE_FLAGS,
    SCHEMA_VERSION,
)

# Answers files from v1 (0.54.0) remain valid — the answers format is unchanged;
# schema v2 only restructured the wizard/GUI question flow (source-first).
SUPPORTED_SCHEMA_VERSIONS = (1, SCHEMA_VERSION)

_ENV_REF_RE = re.compile(r"\{\{\s*env\.(\w+)\s*\}\}")
_VAR_REF_RE = re.compile(r"\{\{\s*vars\.(\w+)\s*\}\}")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SLUG_STRIP_RE = re.compile(r"[^a-z0-9_-]+")


class AnswersValidationError(Exception):
    """Raised when an answers dict is structurally invalid; carries ALL problems."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("invalid answers: " + "; ".join(problems))


# ---------------------------------------------------------------------------
# Answers loading & validation
# ---------------------------------------------------------------------------


def answers_from_file(path: str) -> dict[str, Any]:
    """Load and validate an answers JSON file (``playbook create --answers``)."""
    expanded = os.path.expanduser(path)
    with open(expanded, encoding="utf-8") as fh:
        try:
            answers = json.load(fh)
        except json.JSONDecodeError as exc:
            raise AnswersValidationError([f"not valid JSON: {exc}"]) from exc
    if not isinstance(answers, dict):
        raise AnswersValidationError(["top level must be a JSON object"])
    problems = validate_answers(answers)
    if problems:
        raise AnswersValidationError(problems)
    return answers


def validate_answers(answers: dict[str, Any]) -> list[str]:
    """Structural validation of an answers dict. Returns ALL problems (no first-fail)."""
    problems: list[str] = []

    schema_version = answers.get("schema_version")
    if schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        problems.append(f"schema_version must be one of {list(SUPPORTED_SCHEMA_VERSIONS)}, got {schema_version!r}")

    playbook_type = answers.get("playbook_type")
    if playbook_type not in PLAYBOOK_TYPES:
        problems.append(f"playbook_type must be one of {list(PLAYBOOK_TYPES)}, got {playbook_type!r}")

    if not str(answers.get("name", "") or "").strip():
        problems.append("name is required")
    if not str(answers.get("version", "") or "").strip():
        problems.append("version is required")
    on_error = answers.get("on_error", "stop")
    if on_error not in ("stop", "continue"):
        problems.append(f"on_error must be 'stop' or 'continue', got {on_error!r}")

    if playbook_type == "server":
        problems.extend(_validate_server_answers(answers))
    elif playbook_type == "dev":
        problems.extend(_validate_dev_answers(answers))

    env_file = answers.get("env_file") or {}
    if not isinstance(env_file, dict):
        problems.append("env_file must be an object")
    elif env_file.get("generate") and not str(env_file.get("path", "") or "").strip():
        problems.append("env_file.generate is true but env_file.path is missing")
    elif isinstance(env_file.get("secrets"), dict):
        for key in env_file["secrets"]:
            if not _ENV_KEY_RE.match(str(key)):
                problems.append(f"env_file.secrets: invalid variable name {key!r}")

    return problems


def _validate_server_answers(answers: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    targets = answers.get("targets") or {}
    if not isinstance(targets, dict) or not targets:
        problems.append("server playbooks need at least one entry in 'targets'")
        targets = {}
    for name, target in targets.items():
        if not isinstance(target, dict):
            problems.append(f"targets.{name} must be an object")
            continue
        for required in ("db_container", "db_name"):
            if not str(target.get(required, "") or "").strip():
                problems.append(f"targets.{name}: missing required field '{required}'")

    recipe = answers.get("recipe") or {}
    if not isinstance(recipe, dict):
        problems.append("recipe must be an object")
        recipe = {}

    def check_target_ref(section: str) -> None:
        block = recipe.get(section) or {}
        if isinstance(block, dict) and block.get("enabled"):
            ref = str(block.get("target", "") or "")
            if ref and ref not in targets:
                problems.append(f"recipe.{section}.target '{ref}' is not a defined target")

    for section in ("backup", "rebuild", "restore"):
        check_target_ref(section)
    destination = str(recipe.get("destination", "") or "")
    if destination and destination not in targets:
        problems.append(f"recipe.destination '{destination}' is not a defined target")

    backup = recipe.get("backup") or {}
    if isinstance(backup, dict) and backup.get("enabled") and not str(backup.get("backup_dir", "") or "").strip():
        problems.append("recipe.backup.enabled is true but recipe.backup.backup_dir is missing")

    # Self-mirror guard: backing up a target and restoring straight back into the
    # SAME target is the v0.54.0 wizard failure mode (source question missing) —
    # the restore would overwrite the system that was just backed up.
    restore_block = recipe.get("restore") or {}
    if isinstance(backup, dict) and isinstance(restore_block, dict) and backup.get("enabled"):
        if restore_block.get("enabled"):
            dest = str(recipe.get("destination", "") or "") or str(restore_block.get("target", "") or "")
            if dest and str(backup.get("target", "") or "") == dest:
                problems.append(
                    f"backup source and restore destination are the same target ('{dest}') — "
                    "the mirror would overwrite the system it just backed up"
                )

    restore = recipe.get("restore") or {}
    if isinstance(restore, dict) and restore.get("enabled"):
        source = restore.get("backup_source") or {}
        mode = str(source.get("mode", "") or "") if isinstance(source, dict) else ""
        if isinstance(source, dict) and mode == "file" and not str(source.get("path", "") or "").strip():
            problems.append("recipe.restore.backup_source.mode 'file' requires 'path'")
        elif isinstance(source, dict) and mode == "newest_in_dir":
            if not str(source.get("dir", "") or "").strip() or not str(source.get("pattern", "") or "").strip():
                problems.append("recipe.restore.backup_source.mode 'newest_in_dir' requires 'dir' and 'pattern'")
        elif not isinstance(source, str | dict) or not source:
            problems.append("recipe.restore.enabled is true but recipe.restore.backup_source is missing")
        flags = restore.get("sanitize_flags") or []
        for flag in flags:
            if flag not in SANITIZE_FLAGS:
                problems.append(f"recipe.restore.sanitize_flags: unknown flag {flag!r}")

    rpc_call = recipe.get("rpc_call") or {}
    if isinstance(rpc_call, dict) and rpc_call.get("enabled"):
        if not str(rpc_call.get("model", "") or "").strip():
            problems.append("recipe.rpc_call.enabled is true but recipe.rpc_call.model is missing")
        mode = str(rpc_call.get("mode", "method") or "method")
        if mode == "method" and not str(rpc_call.get("method", "") or "").strip():
            problems.append("recipe.rpc_call.mode 'method' requires 'method'")
        if mode in ("domain_values", "domain_method") and not rpc_call.get("domain"):
            problems.append(f"recipe.rpc_call.mode '{mode}' requires 'domain'")
        if mode == "domain_values" and not rpc_call.get("values"):
            problems.append("recipe.rpc_call.mode 'domain_values' requires 'values'")
        if mode == "domain_method" and not str(rpc_call.get("method", "") or "").strip():
            problems.append("recipe.rpc_call.mode 'domain_method' requires 'method'")

    for index, step in enumerate(answers.get("extra_steps") or [], start=1):
        if not isinstance(step, dict):
            problems.append(f"extra_steps[{index}] must be an object")
            continue
        command = str(step.get("command", "") or "")
        if command not in VALID_COMMANDS:
            problems.append(f"extra_steps[{index}]: unknown command {command!r}")

    return problems


def _validate_dev_answers(answers: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    dev_steps = answers.get("dev_steps") or []
    if not isinstance(dev_steps, list) or not dev_steps:
        problems.append("dev playbooks need at least one entry in 'dev_steps'")
        return problems
    for index, step in enumerate(dev_steps, start=1):
        command = step.get("command") if isinstance(step, dict) else step
        command = str(command or "")
        if command not in VALID_COMMANDS:
            problems.append(f"dev_steps[{index}]: unknown command {command!r}")
        elif command in SERVER_COMMANDS and command != "sql.execute":
            problems.append(f"dev_steps[{index}]: '{command}' is a server-mode step (use a server playbook)")
    return problems


# ---------------------------------------------------------------------------
# Playbook assembly
# ---------------------------------------------------------------------------


def build_playbook_dict(answers: dict[str, Any]) -> dict[str, Any]:
    """Assemble the ordered playbook dict from a validated answers dict."""
    playbook: dict[str, Any] = {
        "version": str(answers.get("version", "")),
        "description": str(answers.get("description", "") or answers.get("name", "")),
        "on_error": str(answers.get("on_error", "stop") or "stop"),
    }

    env_file = answers.get("env_file") or {}
    if isinstance(env_file, dict) and str(env_file.get("path", "") or "").strip():
        playbook["env_file"] = str(env_file["path"])

    if answers.get("playbook_type") == "server":
        targets = answers.get("targets") or {}
        playbook["targets"] = {name: _clean_target(target) for name, target in targets.items()}
        rpc = answers.get("rpc") or {}
        if isinstance(rpc, dict) and rpc.get("enabled"):
            rpc_block = {k: v for k, v in rpc.items() if k != "enabled" and str(v or "").strip()}
            if rpc_block:
                playbook["rpc"] = rpc_block

    variables = answers.get("vars") or {}
    if isinstance(variables, dict) and variables:
        playbook["vars"] = {str(k): str(v) for k, v in variables.items()}

    if answers.get("playbook_type") == "server":
        playbook["steps"] = _build_server_steps(answers)
    else:
        playbook["steps"] = _build_dev_steps(answers)

    return playbook


def _clean_target(target: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {
        "db_container": str(target.get("db_container", "")),
        "db_name": str(target.get("db_name", "")),
    }
    for optional in ("odoo_container", "data_dir"):
        value = str(target.get(optional, "") or "")
        if value:
            cleaned[optional] = value
    owner = str(target.get("owner", "") or "")
    if owner and owner != "ownerp":
        cleaned["owner"] = owner
    return cleaned


def _mirror_destination(answers: dict[str, Any]) -> str:
    """The target the mirror writes into (stop/restore/start/neutralize/update)."""
    recipe = answers.get("recipe") or {}
    explicit = str(recipe.get("destination", "") or "")
    if explicit:
        return explicit
    for section in ("restore", "rebuild"):
        block = recipe.get(section) or {}
        if isinstance(block, dict) and str(block.get("target", "") or ""):
            return str(block["target"])
    targets = list((answers.get("targets") or {}).keys())
    backup_target = str((recipe.get("backup") or {}).get("target", "") or "")
    for name in targets:
        if name != backup_target:
            return name
    return targets[0] if targets else ""


def _build_server_steps(answers: dict[str, Any]) -> list[dict[str, Any]]:
    recipe = answers.get("recipe") or {}
    dest = _mirror_destination(answers)
    steps: list[dict[str, Any]] = []

    backup = recipe.get("backup") or {}
    if backup.get("enabled"):
        source = str(backup.get("target", "") or "")
        args: dict[str, Any] = {
            "target": source,
            "backup_dir": str(backup.get("backup_dir", "")),
            "compression_level": int(backup.get("compression_level", 5)),
        }
        if backup.get("only_sql"):
            args["only_sql"] = True
        steps.append({"name": f"Create fresh backup ({source})", "command": "server.backup", "args": args})

    rebuild = recipe.get("rebuild") or {}
    if rebuild.get("enabled"):
        args = {"target": str(rebuild.get("target", "") or dest)}
        for key, default in (("script_path", "~/update_docker_odoo.py"), ("config", "~/docker2update.yaml")):
            value = str(rebuild.get(key, "") or "")
            if value and value != default:
                args[key] = value
        timeout = int(rebuild.get("timeout", 7200))
        if timeout != 7200:
            args["timeout"] = timeout
        steps.append({"name": f"Rebuild Odoo container ({args['target']})", "command": "server.rebuild", "args": args})

    if recipe.get("stop_before_restore"):
        steps.append(
            {
                "name": f"Stop Odoo container ({dest})",
                "command": "container.stop",
                "args": {"target": dest, "component": "odoo"},
            }
        )

    restore = recipe.get("restore") or {}
    if restore.get("enabled"):
        source_cfg = restore.get("backup_source") or {}
        if isinstance(source_cfg, dict):
            mode = str(source_cfg.get("mode", "") or "")
            if mode == "file":
                backup_source: Any = {"mode": "file", "path": str(source_cfg.get("path", ""))}
            else:
                backup_source = {
                    "mode": "newest_in_dir",
                    "dir": str(source_cfg.get("dir", "")),
                    "pattern": str(source_cfg.get("pattern", "")),
                    "select_by": str(source_cfg.get("select_by", "mtime") or "mtime"),
                }
        else:
            backup_source = str(source_cfg)
        flags = set(restore.get("sanitize_flags") or [])
        args = {
            "target": str(restore.get("target", "") or dest),
            "backup_source": backup_source,
            "drop": bool(restore.get("drop", True)),
            "template": str(restore.get("template", "template0") or "template0"),
            "deactivate_cron": "deactivate_cron" in flags,
            "neutralize": "neutralize" in flags,
            "anonymize": "anonymize" in flags,
            "wipe": "wipe" in flags,
        }
        if "purge_transactions" in flags:
            args["purge_transactions"] = True
        if restore.get("purge_master_data"):
            args["purge_master_data"] = True
        steps.append({"name": f"Restore backup into {args['target']}", "command": "server.restore", "args": args})

    sql = recipe.get("sql_after_restore") or {}
    if sql.get("enabled") and sql.get("statements"):
        step: dict[str, Any] = {
            "name": "Customer-specific SQL (before the server starts)",
            "command": "sql.execute",
            "args": {"target": dest, "statements": [str(s) for s in sql["statements"]]},
        }
        on_error = str(sql.get("on_error", "continue") or "continue")
        if on_error != "stop":
            step["on_error"] = on_error
        steps.append(step)

    if recipe.get("start_after_restore"):
        steps.append(
            {
                "name": f"Start Odoo container ({dest})",
                "command": "container.start",
                "args": {"target": dest, "component": "odoo"},
            }
        )

    if (recipe.get("neutralize") or {}).get("enabled"):
        steps.append(
            {
                "name": "Neutralize (odoo-bin neutralize in the container)",
                "command": "server.neutralize",
                "args": {"target": dest},
            }
        )

    update_all = recipe.get("update_all") or {}
    if update_all.get("enabled"):
        step = {
            "name": "Update all modules",
            "command": "server.update-all",
            "args": {"target": dest, "restart": bool(update_all.get("restart", True))},
        }
        on_error = str(update_all.get("on_error", "continue") or "continue")
        if on_error != "stop":
            step["on_error"] = on_error
        steps.append(step)

    rpc_call = recipe.get("rpc_call") or {}
    if rpc_call.get("enabled"):
        mode = str(rpc_call.get("mode", "method") or "method")
        args = {"model": str(rpc_call.get("model", ""))}
        if mode == "method":
            args["method"] = str(rpc_call.get("method", ""))
            if rpc_call.get("args"):
                args["args"] = rpc_call["args"]
            if rpc_call.get("kwargs"):
                args["kwargs"] = rpc_call["kwargs"]
        elif mode == "domain_values":
            args["domain"] = rpc_call.get("domain") or []
            args["values"] = rpc_call.get("values") or {}
        else:  # domain_method
            args["domain"] = rpc_call.get("domain") or []
            args["method"] = str(rpc_call.get("method", ""))
        steps.append({"name": "Post-restore RPC configuration", "command": "rpc.execute", "args": args})

    for extra in answers.get("extra_steps") or []:
        step = {"command": str(extra.get("command", ""))}
        if str(extra.get("name", "") or ""):
            step = {"name": str(extra["name"]), **step}
        if extra.get("args"):
            step["args"] = extra["args"]
        if str(extra.get("on_error", "") or ""):
            step["on_error"] = str(extra["on_error"])
        steps.append(step)

    return steps


def _build_dev_steps(answers: dict[str, Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for step in answers.get("dev_steps") or []:
        if isinstance(step, str):
            normalized.append({"command": step})
        else:
            normalized.append(dict(step))

    def order_key(step: dict[str, Any]) -> int:
        command = str(step.get("command", ""))
        return DEV_STEP_ORDER.index(command) if command in DEV_STEP_ORDER else len(DEV_STEP_ORDER)

    steps: list[dict[str, Any]] = []
    for step in sorted(normalized, key=order_key):
        built: dict[str, Any] = {
            "name": str(step.get("name", "") or step.get("command", "")),
            "command": str(step.get("command", "")),
        }
        if step.get("args"):
            built["args"] = step["args"]
        if str(step.get("on_error", "") or ""):
            built["on_error"] = str(step["on_error"])
        steps.append(built)
    return steps


# ---------------------------------------------------------------------------
# Rendering, validation, output paths
# ---------------------------------------------------------------------------


def render_playbook_yaml(playbook_dict: dict[str, Any], header_comment: str = "") -> str:
    """Dump the playbook dict as YAML (insertion order preserved) with a header line."""
    header = header_comment or "# Generated by: odoodev playbook create"
    body = yaml.dump(playbook_dict, default_flow_style=False, allow_unicode=True, sort_keys=False, width=120)
    return f"{header}\n{body}"


def validate_generated(playbook_dict: dict[str, Any]) -> None:
    """Round-trip the generated dict through the runner's own validation.

    Raises PlaybookValidationError if the assistant produced something
    ``odoodev run`` would reject — the safety net behind every write.
    """
    try:
        _validate_playbook(playbook_dict)
    except PlaybookValidationError as exc:
        raise PlaybookValidationError(f"generated playbook failed validation: {exc}") from exc


def _find_references(value: Any, pattern: re.Pattern[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        found.update(pattern.findall(value))
    elif isinstance(value, dict):
        for item in value.values():
            found.update(_find_references(item, pattern))
    elif isinstance(value, list | tuple):
        for item in value:
            found.update(_find_references(item, pattern))
    return found


def find_env_references(value: Any) -> set[str]:
    """All ``{{ env.X }}`` variable names referenced anywhere in a nested structure."""
    return _find_references(value, _ENV_REF_RE)


def find_var_references(value: Any) -> set[str]:
    """All ``{{ vars.x }}`` variable names referenced anywhere in a nested structure."""
    return _find_references(value, _VAR_REF_RE)


def slugify(name: str) -> str:
    """Filesystem-safe playbook slug: lowercase, spaces to '-', [a-z0-9_-] only."""
    slug = _SLUG_STRIP_RE.sub("-", name.strip().lower().replace(" ", "-")).strip("-")
    return re.sub(r"-{2,}", "-", slug) or "playbook"


def default_output_path(name: str) -> str:
    """Default output location matching ``odoodev run``'s project discovery dir."""
    return os.path.join(".", "playbooks", f"{slugify(name)}.yaml")


# ---------------------------------------------------------------------------
# Secrets env_file
# ---------------------------------------------------------------------------


def build_env_file_content(secrets: dict[str, str]) -> str:
    """Render ``KEY=value`` lines (dotenv format); rejects invalid names/newlines."""
    lines = ["# Generated by: odoodev playbook create — keep permissions at 600, never commit"]
    for key, value in secrets.items():
        if not _ENV_KEY_RE.match(str(key)):
            raise ValueError(f"invalid env variable name: {key!r}")
        text = str(value)
        if "\n" in text or "\r" in text:
            raise ValueError(f"env value for {key} must not contain newlines")
        if any(ch in text for ch in (" ", "#", '"', "'")):
            escaped = text.replace("\\", "\\\\").replace('"', '\\"')
            text = f'"{escaped}"'
        lines.append(f"{key}={text}")
    return "\n".join(lines) + "\n"


def write_env_file(path: str, secrets: dict[str, str], merge_existing: bool = False) -> Path:
    """Write the secrets file with 0600 permissions.

    ``merge_existing``: keys already in the file survive unless re-entered now
    (new values win). Without it an existing file is overwritten — callers must
    confirm that with the user first (wizard) or require ``--force`` (answers mode).
    """
    expanded = Path(os.path.expanduser(path))
    expanded.parent.mkdir(parents=True, exist_ok=True)

    merged = {str(k): str(v) for k, v in secrets.items()}
    if merge_existing and expanded.exists():
        from dotenv import dotenv_values

        existing = {str(k): str(v or "") for k, v in dotenv_values(expanded).items()}
        merged = {**existing, **merged}

    content = build_env_file_content(merged)
    fd = os.open(expanded, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    os.chmod(expanded, 0o600)
    return expanded
