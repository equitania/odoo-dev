"""Playbook assistant: interactive wizard + GUI endpoints.

``odoodev playbook create``            — interview -> answers dict -> YAML
``odoodev playbook create --answers f`` — same builder path, no prompts (GUI)
``odoodev playbook schema --json``      — wizard field schema for GUI forms
``odoodev playbook validate FILE``      — reuses the runner's load_playbook()

Both frontends produce the identical answers dict (see usage/playbook.md), so
the interactive wizard and the GUI submission can never drift apart.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import click

from odoodev import i18n
from odoodev.click_types import ExpandedPath
from odoodev.core.playbook import SERVER_COMMANDS, PlaybookValidationError, load_playbook
from odoodev.core.playbook_builder import (
    AnswersValidationError,
    answers_from_file,
    build_playbook_dict,
    default_output_path,
    find_env_references,
    find_var_references,
    render_playbook_yaml,
    slugify,
    validate_answers,
    validate_generated,
    write_env_file,
)
from odoodev.core.playbook_schema import (
    DEV_STEP_GROUPS,
    DEV_STEP_ORDER,
    DEV_STEPS_DEFAULT,
    RPC_ENV_KEYS,
    SANITIZE_FLAGS,
    SANITIZE_FLAGS_DEFAULT,
    SCHEMA_VERSION,
    SECRET_NAME_MARKERS,
    SQL_PRESETS,
    STEP_ARG_SPECS,
    wizard_schema,
)
from odoodev.output import (
    checkbox_with_separators,
    confirm,
    console,
    password_input,
    path_input,
    print_error,
    print_header,
    print_info,
    print_success,
    print_table,
    print_warning,
    select,
    text_input,
)


@click.group("playbook")
def playbook() -> None:
    """Create and validate YAML playbooks (assistant + GUI endpoints)."""


# =============================================================================
# Wizard prompt helpers
# =============================================================================


def _required_text(message: str, default: str = "") -> str:
    while True:
        value = text_input(message, default=default).strip()
        if value:
            return value
        print_warning(i18n.t("playbook.common.name_invalid"))


def _int_input(message: str, default: int) -> int:
    while True:
        raw = text_input(message, default=str(default)).strip()
        try:
            return int(raw)
        except ValueError:
            print_warning(f"'{raw}' is not a number")


def _json_input(message: str, default: str = "") -> Any:
    """Prompt for a JSON value; empty input returns None."""
    while True:
        raw = text_input(message, default=default).strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            print_warning(i18n.t("playbook.server.rpc.invalid_json", error=str(exc)))


def _secret_or_text(key: str, message: str) -> str:
    if any(marker in key.upper() for marker in SECRET_NAME_MARKERS):
        return password_input(message)
    return text_input(message)


def _on_error_select(label_key: str, default: str, include_inherit: bool = False) -> str:
    import questionary

    choices = []
    if include_inherit:
        choices.append(questionary.Choice(i18n.t("playbook.choice.on_error_inherit"), value="inherit"))
    choices += [
        questionary.Choice(i18n.t("playbook.choice.on_error_stop"), value="stop"),
        questionary.Choice(i18n.t("playbook.choice.on_error_continue"), value="continue"),
    ]
    return select(i18n.t(label_key), choices=choices, default=default)


def _select_by_input(default: str = "mtime") -> str:
    import questionary

    choices = [
        questionary.Choice(i18n.t("playbook.choice.select_mtime"), value="mtime"),
        questionary.Choice(i18n.t("playbook.choice.select_filename_ts"), value="filename_timestamp"),
    ]
    return select(i18n.t("playbook.server.restore.select_by"), choices=choices, default=default)


def _step_header(step: int, total: int, title_key: str, subtitle_key: str = "") -> None:
    title = i18n.t("playbook.step.prefix", step=step, total=total, title=i18n.t(title_key))
    print_header(title, i18n.t(subtitle_key) if subtitle_key else "")


# =============================================================================
# Interview: language + common head
# =============================================================================


def _wizard_language() -> None:
    """Offer a one-time DE/EN choice when no language is explicitly configured.

    Skipped whenever --lang, ODOODEV_LANG or the config file already decided
    (language_was_explicit) — the default comes from the shell locale.
    """
    if i18n.language_was_explicit():
        return
    import questionary

    choices = [
        questionary.Choice("Deutsch", value="de"),
        questionary.Choice("English", value="en"),
    ]
    lang = select(i18n.t("playbook.lang.question"), choices=choices, default=i18n.get_language())
    i18n.set_language(lang)
    if confirm(i18n.t("playbook.lang.persist"), default=True):
        from dataclasses import replace

        from odoodev.core.global_config import CliConfig, load_global_config, save_global_config

        path = save_global_config(replace(load_global_config(), cli=CliConfig(language=lang)))
        print_info(i18n.t("playbook.lang.saved", path=str(path)))


def _wizard_type(answers: dict[str, Any]) -> None:
    import questionary

    type_choices = [
        questionary.Choice(i18n.t("playbook.type.server"), value="server"),
        questionary.Choice(i18n.t("playbook.type.dev"), value="dev"),
    ]
    answers["playbook_type"] = select(i18n.t("playbook.type.question"), choices=type_choices, default="server")


def _wizard_basics(answers: dict[str, Any]) -> None:
    from odoodev.core.version_registry import available_versions, detect_version_from_cwd

    answers["name"] = _required_text(i18n.t("playbook.common.name"))
    answers["description"] = text_input(i18n.t("playbook.common.description"), default=answers["name"])

    versions = available_versions()
    detected = detect_version_from_cwd()
    default_version = detected if detected in versions else (versions[-1] if versions else "")
    answers["version"] = select(i18n.t("playbook.common.version"), choices=versions, default=default_version)
    answers["on_error"] = _on_error_select("playbook.common.on_error", "stop")


# =============================================================================
# Interview: server branch (guided mirror recipe)
# =============================================================================

# Optional recipe items — server.restore itself is ALWAYS part of the mirror
# (its source comes from the dedicated source question, never from this checkbox).
_RECIPE_ITEMS = (
    ("rebuild", "playbook.server.recipe.rebuild", False),
    ("stop_before_restore", "playbook.server.recipe.stop_before", True),
    ("sql_after_restore", "playbook.server.recipe.sql", False),
    ("start_after_restore", "playbook.server.recipe.start_after", True),
    ("neutralize", "playbook.server.recipe.neutralize", True),
    ("update_all", "playbook.server.recipe.update_all", True),
    ("rpc_call", "playbook.server.recipe.rpc_call", False),
)

_SOURCE_FRESH = "fresh_backup"
_SOURCE_FILE = "existing_file"
_SOURCE_NEWEST = "newest_in_dir"


def _wizard_one_target(
    answers: dict[str, Any], name_default: str, name_label_key: str = "playbook.server.target.name"
) -> str:
    """Ask one target block (container pair); returns its unique name.

    name_label_key adapts the first prompt to the block's role — asking for a
    generic "target name" right after the SOURCE question reads like a
    contradiction (found by the Captain in the v0.55.0 field test).
    """
    targets: dict[str, dict[str, str]] = answers.setdefault("targets", {})
    while True:
        name = text_input(i18n.t(name_label_key), default=name_default).strip()
        if not name:
            print_warning(i18n.t("playbook.server.target.need_one"))
            continue
        if name in targets:
            print_warning(i18n.t("playbook.server.target.duplicate", name=name))
            continue
        break
    targets[name] = {
        "db_container": _required_text(i18n.t("playbook.server.target.db_container"), default=f"{name}-db"),
        "db_name": _required_text(i18n.t("playbook.server.target.db_name")),
        "odoo_container": text_input(i18n.t("playbook.server.target.odoo_container"), default=f"{name}-odoo").strip(),
        "owner": text_input(i18n.t("playbook.server.target.owner"), default="ownerp").strip() or "ownerp",
        "data_dir": text_input(i18n.t("playbook.server.target.data_dir")).strip(),
    }
    return name


def _select_target(answers: dict[str, Any], label_key: str, default: str = "") -> str:
    names = list(answers["targets"].keys())
    if len(names) == 1:
        return names[0]
    effective_default = default if default in names else names[0]
    return select(i18n.t(label_key), choices=names, default=effective_default)


def _wizard_source(answers: dict[str, Any]) -> dict[str, Any]:
    """Ask what the mirror restores FROM.

    Three modes: create a fresh backup from a container pair (adds the source
    target + recipe.backup and derives the restore pattern from the backup
    filename convention), an explicit backup file, or the newest file matching
    a pattern. Server-side paths are asked via text_input — never expanded on
    the machine running the wizard (the handlers expand on the server).
    """
    import questionary

    recipe = answers["recipe"]
    mode_choices = [
        questionary.Choice(i18n.t("playbook.server.source.fresh"), value=_SOURCE_FRESH),
        questionary.Choice(i18n.t("playbook.server.source.file"), value=_SOURCE_FILE),
        questionary.Choice(i18n.t("playbook.server.source.newest"), value=_SOURCE_NEWEST),
    ]
    mode = select(i18n.t("playbook.server.source.question"), choices=mode_choices, default=_SOURCE_FRESH)
    source: dict[str, Any] = {"mode": mode}

    if mode == _SOURCE_FRESH:
        print_info(i18n.t("playbook.server.source.header"))
        name = _wizard_one_target(answers, "live", "playbook.server.source.name")
        backup_dir = _required_text(i18n.t("playbook.server.recipe.backup_dir"), default="/opt/backups/docker")
        recipe["backup"] = {
            "enabled": True,
            "target": name,
            "backup_dir": backup_dir,
            "compression_level": _int_input(i18n.t("playbook.server.recipe.compression_level"), 5),
            "only_sql": confirm(i18n.t("playbook.server.recipe.only_sql"), default=False),
        }
        src = answers["targets"][name]
        # Mirror handle_server_backup's output naming: {db}_{data_container}_dockerbackup_{ts}.tar.zst
        data_container = src["odoo_container"] or src["db_container"]
        backup_source: dict[str, Any] = {
            "mode": "newest_in_dir",
            "dir": backup_dir,
            "pattern": f"{src['db_name']}_{data_container}_dockerbackup_*.tar.zst",
            "select_by": "mtime",
        }
        print_info(i18n.t("playbook.server.source.derived_pattern", pattern=backup_source["pattern"], dir=backup_dir))
        if confirm(i18n.t("playbook.server.source.adjust_pattern"), default=False):
            backup_source["dir"] = _required_text(i18n.t("playbook.server.restore.source_dir"), default=backup_dir)
            backup_source["pattern"] = _required_text(
                i18n.t("playbook.server.restore.source_pattern"), default=backup_source["pattern"]
            )
            backup_source["select_by"] = _select_by_input()
        source["target"] = name
        source["backup_source"] = backup_source
    elif mode == _SOURCE_FILE:
        source["backup_source"] = {
            "mode": "file",
            "path": _required_text(i18n.t("playbook.server.restore.source_path")),
        }
    else:
        source["backup_source"] = {
            "mode": "newest_in_dir",
            "dir": _required_text(i18n.t("playbook.server.restore.source_dir"), default="/opt/backups/docker"),
            "pattern": _required_text(
                i18n.t("playbook.server.restore.source_pattern"), default="*_dockerbackup_*.tar.zst"
            ),
            "select_by": _select_by_input(),
        }
    return source


def _wizard_destination(answers: dict[str, Any], source: dict[str, Any]) -> str:
    """Ask the destination target; guard against restoring back onto the source."""
    print_info(i18n.t("playbook.server.dest.header"))
    source_target = answers["targets"].get(str(source.get("target", "")), {})
    while True:
        name = _wizard_one_target(answers, "test", "playbook.server.dest.name")
        db_container = answers["targets"][name]["db_container"]
        if source.get("mode") == _SOURCE_FRESH and db_container == source_target.get("db_container"):
            print_warning(i18n.t("playbook.server.dest.self_mirror_warning", name=db_container))
            if not confirm(i18n.t("playbook.server.dest.self_mirror_confirm"), default=False):
                del answers["targets"][name]
                continue
        return name


def _wizard_server(answers: dict[str, Any], total_steps: int) -> None:
    import questionary

    answers["targets"] = {}
    recipe: dict[str, Any] = {}
    answers["recipe"] = recipe
    answers["extra_steps"] = []
    pending_env: set[str] = set()

    _step_header(2, total_steps, "playbook.step.source", "playbook.step.source_sub")
    source = _wizard_source(answers)
    _step_header(3, total_steps, "playbook.step.dest", "playbook.step.dest_sub")
    dest = _wizard_destination(answers, source)
    recipe["destination"] = dest
    while confirm(i18n.t("playbook.server.target.add_more"), default=False):
        _wizard_one_target(answers, "")

    _step_header(4, total_steps, "playbook.step.flow", "playbook.step.flow_sub")
    choices = [
        questionary.Choice(i18n.t(label_key), value=key, checked=checked) for key, label_key, checked in _RECIPE_ITEMS
    ]
    selected = set(checkbox_with_separators(i18n.t("playbook.server.recipe.question"), choices))

    if "rebuild" in selected:
        print_info(i18n.t("playbook.server.recipe.rebuild_hint"))
        recipe["rebuild"] = {
            "enabled": True,
            "target": _select_target(answers, "playbook.server.recipe.rebuild_target", default=dest),
            "script_path": text_input(
                i18n.t("playbook.server.recipe.rebuild_script"), default="~/update_docker_odoo.py"
            ).strip(),
            "config": text_input(
                i18n.t("playbook.server.recipe.rebuild_config"), default="~/docker2update.yaml"
            ).strip(),
            "timeout": _int_input(i18n.t("playbook.server.recipe.rebuild_timeout"), 7200),
        }

    recipe["stop_before_restore"] = "stop_before_restore" in selected

    # server.restore is the core of the mirror — always included.
    recipe["restore"] = _wizard_restore(dest, source["backup_source"])

    if "sql_after_restore" in selected:
        statements = _wizard_sql_statements(answers, pending_env)
        if statements:
            recipe["sql_after_restore"] = {
                "enabled": True,
                "statements": statements,
                "on_error": _on_error_select("playbook.server.sql.on_error", "continue"),
            }
        else:
            print_info(i18n.t("playbook.server.sql.none_added"))

    recipe["start_after_restore"] = "start_after_restore" in selected
    recipe["neutralize"] = {"enabled": "neutralize" in selected}

    if "update_all" in selected:
        recipe["update_all"] = {
            "enabled": True,
            "restart": confirm(i18n.t("playbook.server.recipe.update_all_restart"), default=True),
            "on_error": _on_error_select("playbook.server.recipe.update_all_on_error", "continue"),
        }

    if "rpc_call" in selected:
        recipe["rpc_call"] = _wizard_rpc_call()

    _wizard_extra_steps(answers)
    _wizard_rpc_connection(answers, dest, pending_env)
    answers["_pending_env_keys"] = pending_env


def _wizard_restore(dest: str, backup_source: dict[str, Any]) -> dict[str, Any]:
    """Restore details for the destination; the source was decided upfront."""
    import questionary

    restore: dict[str, Any] = {"enabled": True, "target": dest, "backup_source": backup_source}
    restore["template"] = text_input(i18n.t("playbook.server.restore.template"), default="template0") or "template0"
    restore["drop"] = confirm(i18n.t("playbook.server.restore.drop"), default=True)

    flag_choices = [
        questionary.Choice(
            i18n.t(f"playbook.server.restore.flag.{flag}"), value=flag, checked=flag in SANITIZE_FLAGS_DEFAULT
        )
        for flag in SANITIZE_FLAGS
    ]
    restore["sanitize_flags"] = checkbox_with_separators(i18n.t("playbook.server.restore.sanitize"), flag_choices)

    print_warning(i18n.t("playbook.server.restore.purge_warning"))
    restore["purge_master_data"] = confirm(i18n.t("playbook.server.restore.purge_master_data"), default=False)
    return restore


def _wizard_sql_statements(answers: dict[str, Any], pending_env: set[str]) -> list[str]:
    import questionary

    statements: list[str] = []
    while True:
        menu = [
            questionary.Choice(i18n.t("playbook.server.sql.preset_enterprise"), value="enterprise_code"),
            questionary.Choice(i18n.t("playbook.server.sql.preset_eq_cloud"), value="clear_eq_cloud"),
            questionary.Choice(i18n.t("playbook.server.sql.preset_website"), value="website_domain"),
            questionary.Choice(i18n.t("playbook.server.sql.custom"), value="custom"),
            questionary.Choice(i18n.t("playbook.server.sql.done"), value="done"),
        ]
        choice = select(i18n.t("playbook.server.sql.menu"), choices=menu, default="done" if statements else None)
        if choice == "done":
            return statements
        if choice == "custom":
            statement = text_input(i18n.t("playbook.server.sql.custom_input")).strip()
            if statement:
                statements.append(statement)
            continue
        preset = SQL_PRESETS[choice]
        if preset.get("prompt_key"):
            value = text_input(
                i18n.t("playbook.server.sql.website_domain"), default=str(preset.get("prompt_default", ""))
            )
            statements.extend(s.format(**{str(preset["prompt_key"]): value}) for s in preset["statements"])
        else:
            statements.extend(preset["statements"])
        pending_env.update(preset.get("env_keys", ()))


def _wizard_rpc_call() -> dict[str, Any]:
    import questionary

    call: dict[str, Any] = {"enabled": True}
    call["model"] = _required_text(i18n.t("playbook.server.rpc.model"), default="ir.config_parameter")
    mode_choices = [
        questionary.Choice(i18n.t("playbook.server.rpc.mode_method"), value="method"),
        questionary.Choice(i18n.t("playbook.server.rpc.mode_domain_values"), value="domain_values"),
        questionary.Choice(i18n.t("playbook.server.rpc.mode_domain_method"), value="domain_method"),
    ]
    mode = select(i18n.t("playbook.server.rpc.mode"), choices=mode_choices, default="method")
    call["mode"] = mode
    if mode == "method":
        call["method"] = _required_text(i18n.t("playbook.server.rpc.method"), default="set_param")
        args = _json_input(i18n.t("playbook.server.rpc.args"))
        if args is not None:
            call["args"] = args
        kwargs = _json_input(i18n.t("playbook.server.rpc.kwargs"))
        if kwargs is not None:
            call["kwargs"] = kwargs
    else:
        domain = None
        while domain is None:
            domain = _json_input(i18n.t("playbook.server.rpc.domain"))
        call["domain"] = domain
        if mode == "domain_values":
            values = None
            while values is None:
                values = _json_input(i18n.t("playbook.server.rpc.values"))
            call["values"] = values
        else:
            call["method"] = _required_text(i18n.t("playbook.server.rpc.method"))
    return call


def _wizard_extra_steps(answers: dict[str, Any]) -> None:
    while confirm(i18n.t("playbook.server.extra_step.add"), default=False):
        step: dict[str, Any] = {
            "command": select(i18n.t("playbook.server.extra_step.command"), choices=sorted(SERVER_COMMANDS)),
        }
        name = text_input(i18n.t("playbook.server.extra_step.name")).strip()
        if name:
            step["name"] = name
        args: dict[str, str] = {}
        while True:
            key = text_input(i18n.t("playbook.server.extra_step.arg_key")).strip()
            if not key:
                break
            args[key] = text_input(i18n.t("playbook.server.extra_step.arg_value", name=key))
        if args:
            step["args"] = args
        on_error = _on_error_select("playbook.server.extra_step.on_error", "inherit", include_inherit=True)
        if on_error != "inherit":
            step["on_error"] = on_error
        answers["extra_steps"].append(step)


def _wizard_rpc_connection(answers: dict[str, Any], dest: str, pending_env: set[str]) -> None:
    has_rpc_step = bool((answers["recipe"].get("rpc_call") or {}).get("enabled"))
    if not confirm(i18n.t("playbook.server.rpc.configure"), default=has_rpc_step):
        return
    print_info(i18n.t("playbook.server.rpc.hint"))
    host = text_input(i18n.t("playbook.server.rpc.host"), default="{{ env.ODOO_URL }}")
    default_db = answers["targets"].get(dest, {}).get("db_name", "")
    db = text_input(i18n.t("playbook.server.rpc.db"), default=default_db)
    answers["rpc"] = {"enabled": True, "host": host, "db": db}
    pending_env.update(k for k in RPC_ENV_KEYS if k in ("ODOO_USER", "ODOO_PASSWORD"))


# =============================================================================
# Interview: dev branch (checkbox-based)
# =============================================================================

# Arg types the dev branch prompts for; list/json args stay expert-only (YAML edit).
_DEV_PROMPT_TYPES = ("text", "path", "select", "confirm", "int")


def _wizard_dev(answers: dict[str, Any]) -> None:
    import questionary

    choices: list[Any] = []
    for group, commands in DEV_STEP_GROUPS.items():
        choices.append(questionary.Separator(f"── {group} ──"))
        choices.extend(
            questionary.Choice(command, value=command, checked=command in DEV_STEPS_DEFAULT) for command in commands
        )
    selected = checkbox_with_separators(i18n.t("playbook.dev.steps.question"), choices)
    if not selected:
        selected = list(DEV_STEPS_DEFAULT)
        print_warning(i18n.t("playbook.dev.steps.none", defaults=", ".join(selected)))

    ordered = sorted(selected, key=lambda c: DEV_STEP_ORDER.index(c) if c in DEV_STEP_ORDER else 99)
    dev_steps: list[dict[str, Any]] = []
    for command in ordered:
        step: dict[str, Any] = {"command": command}
        args = _wizard_dev_step_args(command)
        if args:
            step["args"] = args
        dev_steps.append(step)
    answers["dev_steps"] = dev_steps


def _wizard_dev_step_args(command: str) -> dict[str, Any]:
    spec = STEP_ARG_SPECS.get(command)
    if spec is None or not spec.args:
        return {}
    promptable = [a for a in spec.args if a.type in _DEV_PROMPT_TYPES]
    if not promptable:
        return {}
    print_info(i18n.t("playbook.dev.args_header", command=command))
    args: dict[str, Any] = {}
    for arg in promptable:
        message = i18n.t("playbook.dev.arg_prompt", command=command, arg=arg.name)
        if arg.type == "confirm":
            default_bool = bool(arg.default) if arg.default is not None else False
            value: Any = confirm(message, default=default_bool)
            if value != default_bool or (arg.default is None and value):
                args[arg.name] = value
        elif arg.type == "select":
            value = select(message, choices=list(arg.choices or ()), default=arg.default)
            if arg.required or value != arg.default:
                args[arg.name] = value
        elif arg.type == "int":
            value = _int_input(message, int(arg.default or 0))
            if arg.required or value != arg.default:
                args[arg.name] = value
        else:
            prompt = path_input if arg.type == "path" else text_input
            if arg.required:
                while True:
                    value = prompt(message, default=str(arg.default or "")).strip()
                    if value:
                        break
                    print_warning(i18n.t("playbook.common.name_invalid"))
                args[arg.name] = value
            else:
                value = prompt(message, default=str(arg.default or "")).strip()
                if value and value != str(arg.default or ""):
                    args[arg.name] = value
    return args


# =============================================================================
# Interview: common tail (vars, secrets, output)
# =============================================================================


def _wizard_vars(answers: dict[str, Any]) -> None:
    preview = build_playbook_dict(answers)
    referenced = find_var_references(preview)
    existing = dict(answers.get("vars") or {})
    for key in sorted(referenced - set(existing)):
        existing[key] = text_input(i18n.t("playbook.common.var_value", name=key))
    while confirm(i18n.t("playbook.common.vars_add"), default=False):
        key = text_input(i18n.t("playbook.common.var_key")).strip()
        if not key:
            break
        existing[key] = text_input(i18n.t("playbook.common.var_value", name=key))
    if existing:
        answers["vars"] = existing


def _wizard_secrets(answers: dict[str, Any]) -> None:
    preview = build_playbook_dict(answers)
    pending = set(answers.pop("_pending_env_keys", set()))
    pending |= find_env_references(preview)

    slug = slugify(answers["name"])
    if answers.get("playbook_type") == "server":
        default_path = f"~/.config/odoodev/{slug}.env"
    else:
        default_path = f"./playbooks/{slug}.env"

    if not confirm(i18n.t("playbook.secrets.generate"), default=bool(pending)):
        if pending:
            path = path_input(i18n.t("playbook.secrets.path"), default=default_path)
            answers["env_file"] = {"path": path, "generate": False}
            print_warning(i18n.t("playbook.secrets.skipped", path=path))
        return

    path = path_input(i18n.t("playbook.secrets.path"), default=default_path)
    secrets: dict[str, str] = {}
    if pending:
        print_info(i18n.t("playbook.secrets.detected"))
        for key in sorted(pending):
            print_info(f"  - {key}")
        for key in sorted(pending):
            value = _secret_or_text(key, i18n.t("playbook.secrets.value_for", name=key))
            if value:
                secrets[key] = value
    while confirm(i18n.t("playbook.secrets.add_more"), default=False):
        key = text_input(i18n.t("playbook.secrets.key_name")).strip()
        if not key:
            break
        secrets[key] = _secret_or_text(key, i18n.t("playbook.secrets.value_for", name=key))

    if not secrets:
        # Never write a header-only secrets file. Keep the env_file reference in the
        # YAML only when something actually needs it ({{ env.X }} references exist).
        if pending:
            answers["env_file"] = {"path": path, "generate": False}
            print_warning(i18n.t("playbook.secrets.skipped", path=path))
        else:
            print_info(i18n.t("playbook.secrets.none"))
        return

    merge = False
    write = True
    if os.path.exists(os.path.expanduser(path)):
        merge = confirm(i18n.t("playbook.secrets.exists_merge", path=path), default=True)
        if not merge:
            write = False
            print_warning(i18n.t("playbook.secrets.skipped", path=path))
    answers["env_file"] = {"path": path, "generate": write, "secrets": secrets, "_merge": merge}


def _run_wizard(output_default: str = "") -> dict[str, Any]:
    os.environ.setdefault("PROMPT_TOOLKIT_NO_CPR", "1")
    _wizard_language()
    print_header(i18n.t("playbook.wizard.header"), i18n.t("playbook.wizard.subtitle"))

    answers: dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    _wizard_type(answers)
    if answers["playbook_type"] == "server":
        total = 6
        print_info(i18n.t("playbook.server.intro"))
        _step_header(1, total, "playbook.step.basics")
        _wizard_basics(answers)
        _wizard_server(answers, total)  # steps 2-4: source, destination, flow
    else:
        total = 4
        _step_header(1, total, "playbook.step.basics")
        _wizard_basics(answers)
        _step_header(2, total, "playbook.step.steps")
        _wizard_dev(answers)
    _step_header(total - 1, total, "playbook.step.secrets")
    _wizard_vars(answers)
    _wizard_secrets(answers)

    _step_header(total, total, "playbook.step.summary")
    default_output = output_default or default_output_path(answers["name"])
    answers["output_path"] = path_input(i18n.t("playbook.output.path"), default=default_output)
    return answers


# =============================================================================
# Summary + write (shared between wizard and answers mode)
# =============================================================================


def _describe_source(answers: dict[str, Any]) -> str:
    """Human-readable mirror source for the summary, derived from the recipe."""
    recipe = answers.get("recipe") or {}
    backup = recipe.get("backup") or {}
    if backup.get("enabled"):
        return i18n.t("playbook.summary.source_fresh", target=str(backup.get("target", "")))
    source = (recipe.get("restore") or {}).get("backup_source") or {}
    if isinstance(source, str):
        return i18n.t("playbook.summary.source_file", path=source)
    if source.get("mode") == "file":
        return i18n.t("playbook.summary.source_file", path=str(source.get("path", "")))
    if source.get("mode") == "newest_in_dir":
        return i18n.t("playbook.summary.source_newest", dir=str(source.get("dir", "")))
    return "-"


def _summarize_and_confirm(answers: dict[str, Any], playbook_dict: dict[str, Any]) -> None:
    steps = playbook_dict.get("steps", [])
    summary = {
        i18n.t("playbook.summary.type"): str(answers.get("playbook_type", "")),
        i18n.t("playbook.summary.name"): str(answers.get("name", "")),
        i18n.t("playbook.summary.version"): str(playbook_dict.get("version", "")),
        i18n.t("playbook.summary.steps"): str(len(steps)),
    }
    if answers.get("playbook_type") == "server":
        summary[i18n.t("playbook.summary.source")] = _describe_source(answers)
        summary[i18n.t("playbook.summary.destination")] = str((answers.get("recipe") or {}).get("destination", "-"))
    summary.update(
        {
            i18n.t("playbook.summary.targets"): ", ".join(playbook_dict.get("targets", {})) or "-",
            i18n.t("playbook.summary.env_file"): str(playbook_dict.get("env_file", "") or "-"),
            i18n.t("playbook.summary.output"): str(answers.get("output_path", "")),
        }
    )
    print_table(i18n.t("playbook.summary.header"), summary)
    for index, step in enumerate(steps, start=1):
        console.print(f"  {index}. {step.get('name', step['command'])} [dim]\\[{step['command']}][/dim]")
    if not confirm(i18n.t("playbook.summary.confirm"), default=True):
        print_info(i18n.t("playbook.summary.cancelled"))
        raise SystemExit(0)


def _write_outputs(answers: dict[str, Any], *, force: bool, interactive: bool) -> Path:
    playbook_dict = build_playbook_dict(answers)
    validate_generated(playbook_dict)

    output_path = Path(os.path.expanduser(str(answers.get("output_path") or default_output_path(answers["name"]))))
    if output_path.exists():
        if interactive:
            if not confirm(i18n.t("playbook.output.overwrite", path=str(output_path)), default=False):
                print_info(i18n.t("playbook.summary.cancelled"))
                raise SystemExit(0)
        elif not force:
            print_error(i18n.t("playbook.create.output_exists", path=str(output_path)))
            raise SystemExit(1)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_playbook_yaml(playbook_dict), encoding="utf-8")
    print_success(i18n.t("playbook.summary.written", path=str(output_path)))

    env_cfg = answers.get("env_file") or {}
    if isinstance(env_cfg, dict) and env_cfg.get("generate") and env_cfg.get("path"):
        env_path = os.path.expanduser(str(env_cfg["path"]))
        merge = bool(env_cfg.get("_merge"))
        if os.path.exists(env_path) and not interactive and not force:
            print_error(i18n.t("playbook.create.env_exists", path=env_path))
            raise SystemExit(1)
        written = write_env_file(env_path, env_cfg.get("secrets") or {}, merge_existing=merge)
        print_success(i18n.t("playbook.secrets.written", path=str(written)))

    print_info(i18n.t("playbook.summary.hint_validate", path=str(output_path)))
    print_info(i18n.t("playbook.summary.hint_dryrun", path=str(output_path)))
    if answers.get("playbook_type") == "server":
        print_info(i18n.t("playbook.summary.hint_cron", path=str(output_path.resolve())))
    return output_path


# =============================================================================
# Subcommands
# =============================================================================


@playbook.command("create")
@click.option(
    "--answers",
    "answers_file",
    type=ExpandedPath(exists=True, dir_okay=False),
    help="Answers JSON file (see usage/playbook.md) — skips all prompts.",
)
@click.option("--non-interactive", is_flag=True, help="Fail instead of prompting; requires --answers.")
@click.option(
    "--output",
    "-o",
    "output_path",
    type=ExpandedPath(),
    default=None,
    help="Output path for the playbook YAML (default: ./playbooks/<name>.yaml).",
)
@click.option("--force", is_flag=True, help="Overwrite existing playbook/env files (non-interactive mode).")
def playbook_create(answers_file: str | None, non_interactive: bool, output_path: str | None, force: bool) -> None:
    """Create a playbook — interactively or from an answers JSON file."""
    if non_interactive and not answers_file:
        raise click.UsageError(i18n.t("playbook.create.answers_required"))

    if answers_file:
        try:
            answers = answers_from_file(answers_file)
        except AnswersValidationError as exc:
            print_error(i18n.t("playbook.create.answers_invalid"))
            for problem in exc.problems:
                print_error(f"  - {problem}")
            raise SystemExit(1) from exc
        if output_path:
            answers["output_path"] = output_path
        _write_outputs(answers, force=force, interactive=False)
        return

    answers = _run_wizard(output_default=output_path or "")
    problems = validate_answers(answers)
    if problems:
        # Should not happen — the wizard enforces every constraint interactively.
        print_error(i18n.t("playbook.create.answers_invalid"))
        for problem in problems:
            print_error(f"  - {problem}")
        raise SystemExit(1)
    playbook_dict = build_playbook_dict(answers)
    validate_generated(playbook_dict)
    _summarize_and_confirm(answers, playbook_dict)
    _write_outputs(answers, force=force, interactive=True)


@playbook.command("schema")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable wizard field schema (one JSON line).")
def playbook_schema_cmd(as_json: bool) -> None:
    """Print the assistant's field schema (GUI form rendering contract)."""
    schema = wizard_schema()
    if as_json:
        sys.stdout.write(json.dumps(schema) + "\n")
        return
    print_header(i18n.t("playbook.wizard.header"), f"schema v{schema['schema_version']}")
    for section in schema["sections"]:
        fields = section.get("fields", []) or section.get("item_fields", [])
        applies = ", ".join(section["applies_to"])
        print_info(f"{section['key']}: {len(fields)} field(s) [{applies}]")
    print_info("Use --json for the full machine-readable schema.")


@playbook.command("validate")
@click.argument("playbook_file", type=ExpandedPath(exists=True, dir_okay=False))
@click.option("--json", "as_json", is_flag=True, help="Machine-readable result (one JSON line).")
def playbook_validate(playbook_file: str, as_json: bool) -> None:
    """Validate a playbook file without executing it."""
    try:
        config = load_playbook(playbook_file)
    except (PlaybookValidationError, FileNotFoundError, OSError) as exc:
        if as_json:
            sys.stdout.write(json.dumps({"valid": False, "error": str(exc)}) + "\n")
        else:
            print_error(i18n.t("playbook.validate.failed", error=str(exc)))
        raise SystemExit(1) from exc
    if as_json:
        sys.stdout.write(json.dumps({"valid": True, "steps": len(config.steps), "version": config.version}) + "\n")
        return
    print_success(i18n.t("playbook.validate.ok", steps=len(config.steps), version=config.version))
