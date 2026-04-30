"""odoodev setup - Interactive configuration wizard."""

from __future__ import annotations

import click

from odoodev import i18n
from odoodev.core.global_config import (
    DEFAULT_ACTIVE_VERSIONS,
    DEFAULT_BASE_DIR,
    DEFAULT_DB_PASSWORD,
    DEFAULT_DB_USER,
    CliConfig,
    DatabaseConfig,
    GlobalConfig,
    clear_config_cache,
    config_exists,
    get_config_path,
    load_global_config,
    save_global_config,
)
from odoodev.output import (
    _ownerp_style,
    _patch_checkbox_indicators,
    confirm,
    print_header,
    print_info,
    print_success,
    print_table,
    print_warning,
)


def _run_interactive_wizard() -> GlobalConfig:
    """Run the interactive setup wizard.

    Returns:
        GlobalConfig with user-selected values.
    """
    import os

    import questionary

    os.environ.setdefault("PROMPT_TOOLKIT_NO_CPR", "1")

    style = _ownerp_style()

    print_header(i18n.t("setup.welcome"), "Interactive configuration wizard")

    # Show current config if it exists
    if config_exists():
        current = load_global_config()
        print_info(f"Current config: base_dir={current.base_dir}, db_user={current.database.user}")
        print_info("Values in brackets are current settings.\n")

    # Step 0: Preferred CLI language (applies to subsequent prompts immediately)
    default_lang = load_global_config().cli.language if config_exists() else i18n.get_language()
    lang_choices = [
        questionary.Choice("English", value="en", checked=default_lang == "en"),
        questionary.Choice("Deutsch", value="de", checked=default_lang == "de"),
    ]
    lang = questionary.select(
        i18n.t("setup.lang_question"),
        choices=lang_choices,
        default=default_lang,
        style=style,
    ).ask()
    if lang is None:
        raise SystemExit(0)
    i18n.set_language(lang)

    # Step 1: Base Directory
    default_base = load_global_config().base_dir if config_exists() else DEFAULT_BASE_DIR
    base_dir = questionary.text(
        i18n.t("setup.base_dir_question"),
        default=default_base,
        style=style,
    ).ask()

    if base_dir is None:
        raise SystemExit(0)

    # Step 2: Active Versions
    default_versions = load_global_config().active_versions if config_exists() else list(DEFAULT_ACTIVE_VERSIONS)
    all_versions = ["16", "17", "18", "19"]
    version_choices = [questionary.Choice(f"v{v}", value=v, checked=v in default_versions) for v in all_versions]
    with _patch_checkbox_indicators():
        active_versions = questionary.checkbox(
            i18n.t("setup.versions_question"),
            choices=version_choices,
            style=style,
        ).ask()

    if active_versions is None:
        raise SystemExit(0)

    if not active_versions:
        print_warning("No versions selected, using defaults.")
        active_versions = list(DEFAULT_ACTIVE_VERSIONS)

    # Step 3: Database Credentials
    default_user = load_global_config().database.user if config_exists() else DEFAULT_DB_USER
    default_pass = load_global_config().database.password if config_exists() else DEFAULT_DB_PASSWORD

    db_user = questionary.text(
        i18n.t("setup.db_user_question"),
        default=default_user,
        style=style,
    ).ask()

    if db_user is None:
        raise SystemExit(0)

    db_password = questionary.text(
        i18n.t("setup.db_password_question"),
        default=default_pass,
        style=style,
    ).ask()

    if db_password is None:
        raise SystemExit(0)

    config = GlobalConfig(
        base_dir=base_dir,
        database=DatabaseConfig(user=db_user, password=db_password),
        cli=CliConfig(language=lang),
        active_versions=sorted(active_versions),
    )

    # Step 4: Summary & Confirm
    print_table(
        "Configuration Summary",
        {
            "Base Directory": config.base_dir,
            "Active Versions": ", ".join(f"v{v}" for v in config.active_versions),
            "DB User": config.database.user,
            "DB Password": "***",
            "Config File": str(get_config_path()),
        },
    )

    if not confirm("Save this configuration?", default=True):
        print_info("Setup cancelled.")
        raise SystemExit(0)

    return config


@click.command("setup")
@click.option("--non-interactive", is_flag=True, help="Save defaults without prompting")
@click.option("--reset", is_flag=True, help="Reset configuration to defaults")
def setup(non_interactive: bool, reset: bool) -> None:
    """Interactive setup wizard for odoodev configuration.

    Creates ~/.config/odoodev/config.yaml with your preferences
    for base directory, active versions, and database credentials.
    """
    if reset:
        clear_config_cache()
        config = GlobalConfig()
        path = save_global_config(config)
        print_success(f"Configuration reset to defaults: {path}")
        return

    if non_interactive:
        clear_config_cache()
        if config_exists():
            print_info("Configuration already exists. Use --reset to restore defaults.")
            return
        config = GlobalConfig()
        path = save_global_config(config)
        print_success(f"Default configuration saved: {path}")
        return

    # Interactive wizard
    clear_config_cache()
    config = _run_interactive_wizard()
    clear_config_cache()
    path = save_global_config(config)
    print_success(i18n.t("setup.saved", path=str(path)))
