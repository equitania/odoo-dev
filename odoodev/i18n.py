"""Lightweight DE/EN localization for odoodev user-facing CLI strings.

Phase-1 scope: critical user-guidance messages (preflight errors, placeholder
warnings, setup wizard prompts, init step headers, db-restore confirmations).
Remaining strings stay English until promoted in later phases.

Selection precedence (highest first):
    1. ``--lang`` CLI flag
    2. ``ODOODEV_LANG`` environment variable
    3. ``cli.language`` field in ``~/.config/odoodev/config.yaml``
    4. System locale (``de_*`` -> ``de``, anything else -> ``en``)
    5. Default ``en``

Usage::

    from odoodev.i18n import t, set_language
    set_language("de")
    print(t("start.env_missing", path="/foo/.env"))
"""

from __future__ import annotations

import locale
import logging
import os

logger = logging.getLogger(__name__)

SUPPORTED = ("en", "de")
DEFAULT_LANGUAGE = "en"

_active_language: str = DEFAULT_LANGUAGE
# True when the last detect_language() resolved via an explicit source
# (--lang flag, ODOODEV_LANG, config file) rather than locale/default.
_explicit_language: bool = False

# Flat dot-namespaced keys, en is the canonical source. de mirrors en.
MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        # --- start.py preflight ---
        "start.env_missing": "No .env file found at {path}.",
        "start.env_missing_hint": (
            "Run 'odoodev init {version}' to create it, or 'odoodev setup' to configure global defaults."
        ),
        "start.placeholder_password_title": "Insecure default credentials",
        "start.placeholder_password_body": (
            "The .env at {path} still contains the placeholder password 'CHANGE_AT_FIRST'.\n"
            "This is a development default and must be changed before any real use."
        ),
        "start.placeholder_password_action": (
            "Run 'odoodev setup' to configure a real password, then re-run 'odoodev init {version}'\n"
            "to regenerate the .env. Or edit {path} directly and replace PGPASSWORD."
        ),
        "start.placeholder_password_continue": "Continue with placeholder password (development only)?",
        "start.placeholder_password_aborted": "Aborted. Configure a real password and try again.",
        "start.url_panel_subtitle": "Web: http://localhost:{port}",
        "start.url_panel_with_mailpit": "Web: http://localhost:{port}  |  Mailpit: http://localhost:{mailpit}",
        # --- setup wizard ---
        "setup.welcome": "odoodev setup wizard",
        "setup.lang_question": "Preferred language for CLI messages?",
        "setup.base_dir_question": "Base directory for Odoo development:",
        "setup.db_user_question": "PostgreSQL username:",
        "setup.db_password_question": "PostgreSQL password:",
        "setup.versions_question": "Active Odoo versions:",
        "setup.runtime_question": "Container runtime for PostgreSQL:",
        "setup.saved": "Configuration saved to {path}",
        # --- init steps ---
        "init.header": "Initializing Odoo v{version} development environment",
        "init.step_dirs": "Creating directory structure",
        "init.step_env": "Generating .env file",
        "init.step_compose": "Generating docker-compose.yml",
        "init.step_venv": "Creating Python virtual environment",
        "init.step_repos": "Cloning repositories",
        "init.step_docker": "Starting Docker services",
        "init.done": "Odoo v{version} initialized successfully.",
        "init.next_steps_title": "Next steps",
        "init.next_steps_body": (
            "1. Edit {env_path} and set PGPASSWORD to a real value.\n"
            "2. Run 'odoodev start {version}' to launch the server."
        ),
        # --- db restore ---
        "db.restore_dropping": "Dropping existing database '{name}'...",
        "db.restore_creating": "Creating database '{name}'...",
        "db.restore_extracting": "Extracting backup ({fmt})...",
        "db.restore_importing": "Importing SQL...",
        "db.restore_postprocess": "Deactivating cron jobs and cloud integrations...",
        "db.restore_done": "Database '{name}' restored successfully.",
        "db.restore_confirm": "Database '{name}' exists. Drop and recreate?",
        # --- tui module export ---
        "tui.export_title": "Export modules to CSV (Releasemanager format)",
        "tui.export_db_label": "Target database (editable):",
        "tui.export_db_required": "Please enter a database name!",
        "tui.export_opt_all": "All available modules",
        "tui.export_opt_all_no_ent": "All modules without Enterprise",
        "tui.export_opt_installed": "Installed modules only",
        "tui.export_btn": "Export CSV",
        "tui.export_cancel": "Cancel",
        "tui.export_saved": "{count} modules exported: {path}",
        "tui.export_empty": "No modules to export.",
        "tui.export_error": "Module export failed: {error}",
        "tui.export_chk_update": "Update apps list before export",
        "tui.export_chk_cleanup": "Remove non-installed modules before export",
        "tui.export_username_label": "Odoo login (res.users):",
        "tui.export_password_label": "Password:",
        "tui.export_username_required": "Please enter a username!",
        "tui.export_chk_remember": "Save credentials for future exports",
        "tui.export_connecting": "Connecting to Odoo...",
        "tui.export_progress_update": "Updating apps list...",
        "tui.export_progress_cleanup": "Removing non-installed modules...",
        "tui.export_progress_listing": "Fetching module list...",
        # --- tui backup ---
        "tui.backup_title": "Back up database",
        "tui.backup_db_label": "Database to back up (editable):",
        "tui.backup_db_required": "Please enter a database name!",
        "tui.backup_opt_zip": "ZIP (SQL + filestore)",
        "tui.backup_opt_sql": "SQL only",
        "tui.backup_btn": "Create backup",
        "tui.backup_cancel": "Cancel",
        "tui.backup_running": "Creating backup of '{db}'…",
        "tui.backup_saved": "Backup saved: {path} ({size})",
        "tui.backup_empty": "Backup failed (no output produced).",
        "tui.backup_error": "Backup failed: {error}",
        # --- tui database switch ---
        "tui.switch_db_title": "Switch database",
        "tui.switch_db_hint": "Select a database — the server restarts with it.",
        "tui.switch_db_current": "(current)",
        "tui.switch_db_empty": "No databases found.",
        "tui.switch_db_cancel": "Cancel",
        "tui.switch_db_switching": "Switching to '{db}' — restarting server…",
        # --- tui module maintenance ---
        "tui.modules_updating": "Updating apps list…",
        "tui.modules_updated": "Apps list updated ({count} new module(s)).",
        "tui.modules_update_error": "Apps list update failed: {error}",
        "tui.modules_cleaning": "Removing non-installed modules…",
        "tui.modules_cleaned": "Removed {count} non-installed module(s).",
        "tui.modules_clean_error": "Module cleanup failed: {error}",
        # --- tui quick menu ---
        "tui.menu_title": "Quick menu — ↑/↓ + Enter, Esc closes",
        "tui.menu_view": "View",
        "tui.menu_all_levels": "All levels",
        "tui.menu_issues": "Issues only (WARN + ERROR + CRIT)",
        "tui.menu_only_debug": "Only DEBUG",
        "tui.menu_only_info": "Only INFO",
        "tui.menu_only_warning": "Only WARNING",
        "tui.menu_only_error": "Only ERROR",
        "tui.menu_only_critical": "Only CRITICAL",
        "tui.menu_log": "Log",
        "tui.menu_search": "Search…",
        "tui.menu_clear": "Clear log",
        "tui.menu_save": "Save visible log",
        "tui.menu_copy_visible": "Copy visible lines",
        "tui.menu_copy_errors": "Copy errors",
        "tui.menu_copy_warnings": "Copy warnings + errors",
        "tui.menu_export": "Export",
        "tui.menu_export_csv": "Export modules as CSV →",
        "tui.menu_modules": "Modules",
        "tui.menu_update_apps": "Update apps list",
        "tui.menu_cleanup_modules": "Remove non-installed modules",
        "tui.menu_server": "Server",
        "tui.menu_restart": "Restart server",
        "tui.menu_update": "Update module…",
        "tui.menu_load_language": "Load language…",
        "tui.menu_backup": "Back up database…",
        "tui.menu_switch_db": "Switch database…",
        # --- db users TUI ---
        "users_tui.title": "odoodev db users — {db}",
        "users_tui.col_login": "Login",
        "users_tui.col_name": "Name",
        "users_tui.col_2fa": "2FA",
        "users_tui.col_active": "Active",
        "users_tui.status_count": "{shown}/{total} users",
        "users_tui.status_filter": "filter: {query}",
        "users_tui.status_portal": "incl. portal",
        "users_tui.no_users": "No users found in '{db}'.",
        "users_tui.search_placeholder": "Filter by login or name…",
        "users_tui.set_password_title": "Set password for '{login}'",
        "users_tui.set_password_hint": "Stored as pbkdf2_sha512 hash — visible here (dev tool).",
        "users_tui.set_password_btn": "Set password",
        "users_tui.set_password_cancel": "Cancel",
        "users_tui.set_password_required": "Please enter a password!",
        "users_tui.password_set": "Password set for '{login}'.",
        "users_tui.password_error": "Password reset failed: {error}",
        "users_tui.disable_2fa_title": "Disable 2FA for '{login}'?",
        "users_tui.disable_2fa_hint": "Clears the TOTP secret and removes trusted devices.",
        "users_tui.disable_2fa_btn": "Disable 2FA",
        "users_tui.disable_2fa_cancel": "Cancel",
        "users_tui.disabled_2fa": "2FA disabled for '{login}'.",
        "users_tui.disable_2fa_error": "2FA disable failed: {error}",
        "users_tui.already_disabled": "2FA is not enabled for '{login}'.",
        "users_tui.pick_db_first": "Select a database first.",
        "users_tui.no_selection": "No user selected.",
        "users_tui.key_password": "Set password",
        "users_tui.key_2fa": "Disable 2FA",
        "users_tui.key_switch_db": "Switch DB",
        "users_tui.key_search": "Search",
        "users_tui.key_quit": "Quit",
        # --- playbook assistant ---
        "playbook.wizard.header": "odoodev playbook assistant",
        "playbook.wizard.subtitle": "Answer the questions — a runnable playbook YAML comes out.",
        "playbook.lang.question": "Sprache / Language?",
        "playbook.lang.persist": "Save as default language for odoodev?",
        "playbook.lang.saved": "Language saved to {path}.",
        "playbook.step.prefix": "Step {step}/{total} — {title}",
        "playbook.step.basics": "Basics",
        "playbook.step.source": "Source",
        "playbook.step.source_sub": "Where does the data come from?",
        "playbook.step.dest": "Destination",
        "playbook.step.dest_sub": "Where should the data go?",
        "playbook.step.flow": "Mirror options",
        "playbook.step.flow_sub": "What should happen along the way?",
        "playbook.step.steps": "Steps",
        "playbook.step.secrets": "Variables & credentials",
        "playbook.step.summary": "Summary",
        "playbook.server.intro": (
            "A mirror copies one Odoo system onto another: SOURCE -> DESTINATION.\n"
            "The assistant asks three things: 1) Where does the data come from?\n"
            "2) Where should it go? 3) What should happen along the way?"
        ),
        "playbook.type.question": "Which kind of playbook do you want to create?",
        "playbook.type.dev": "Dev-mode (local Odoo development environment)",
        "playbook.type.server": "Server-mode (customer server with Docker containers)",
        "playbook.common.name": "Playbook name:",
        "playbook.common.name_invalid": "Name must not be empty.",
        "playbook.common.description": "Description:",
        "playbook.common.version": "Odoo version:",
        "playbook.common.on_error": "What should happen when a step fails?",
        "playbook.choice.on_error_stop": "Stop the playbook (stop)",
        "playbook.choice.on_error_continue": "Continue with the next step (continue)",
        "playbook.choice.on_error_inherit": "Use the playbook default (inherit)",
        "playbook.choice.select_mtime": "Newest file by modification time (mtime)",
        "playbook.choice.select_filename_ts": "Newest by timestamp in the filename (filename_timestamp)",
        "playbook.common.vars": "Custom variables ({{ vars.x }})",
        "playbook.common.vars_add": "Add a custom variable?",
        "playbook.common.var_key": "Variable name (empty = done):",
        "playbook.common.var_value": "Value for '{name}':",
        "playbook.server.target.name": "Target name:",
        "playbook.server.target.db_container": "PostgreSQL container name:",
        "playbook.server.target.db_name": "Database name:",
        "playbook.server.target.odoo_container": "Odoo container name (empty = none):",
        "playbook.server.target.owner": "Database owner/user:",
        "playbook.server.target.data_dir": "Host data dir (empty = resolve via docker inspect):",
        "playbook.server.target.add_more": "Add another target?",
        "playbook.server.target.need_one": "At least one target is required.",
        "playbook.server.target.duplicate": "Target '{name}' already exists.",
        "playbook.server.recipe.question": (
            "Which optional steps should the mirror include? (restore is always part of it)"
        ),
        "playbook.server.source.question": "What is the SOURCE of the mirror?",
        "playbook.server.source.fresh": "Create a fresh backup from the running source system",
        "playbook.server.source.file": "Use an existing backup file",
        "playbook.server.source.newest": "Use the newest backup file from a directory",
        "playbook.server.source.name": "Source name (identifier in the playbook):",
        "playbook.server.source.header": "Source — the container pair the backup is taken FROM",
        "playbook.server.source.auto_handoff": (
            "The restore will automatically use the backup file this run creates — nothing to configure."
        ),
        "playbook.server.dest.header": "Destination — the container pair the backup is restored INTO",
        "playbook.server.dest.name": "Destination name (identifier in the playbook):",
        "playbook.server.dest.self_mirror_warning": (
            "Destination uses the SAME database container as the source ('{name}') — "
            "the restore would overwrite the system you just backed up!"
        ),
        "playbook.server.dest.self_mirror_confirm": "Really restore back onto the source system?",
        "playbook.server.recipe.rebuild": "Rebuild the destination Odoo container (server.rebuild)",
        "playbook.server.recipe.stop_before": "Stop destination Odoo before restore (container.stop)",
        "playbook.server.recipe.sql": "Run custom SQL after restore (sql.execute)",
        "playbook.server.recipe.start_after": "Start destination Odoo after restore (container.start)",
        "playbook.server.recipe.update_all": "Update all modules (server.update-all)",
        "playbook.server.recipe.rpc_call": "Post-restore RPC call (rpc.execute)",
        "playbook.server.recipe.backup_dir": "Backup directory on the server:",
        "playbook.server.recipe.compression_level": "zstd compression level (1-22):",
        "playbook.server.recipe.only_sql": "SQL-only backup (skip filestore)?",
        "playbook.server.recipe.rebuild_target": "Rebuild target:",
        "playbook.server.recipe.rebuild_script": "Path to update_docker_odoo.py:",
        "playbook.server.recipe.rebuild_config": "Path to docker2update.yaml:",
        "playbook.server.recipe.rebuild_timeout": "Rebuild timeout in seconds:",
        "playbook.server.recipe.rebuild_hint": (
            "The release access code lives in release.txt inside the build folder; "
            "the container must be an active entry in docker2update.yaml."
        ),
        "playbook.server.recipe.update_all_restart": "Restart the container after the module update?",
        "playbook.server.recipe.update_all_on_error": "If the module update fails:",
        "playbook.server.restore.source_dir": "Backup directory:",
        "playbook.server.restore.source_pattern": "Filename pattern:",
        "playbook.server.restore.select_by": "Select newest by:",
        "playbook.server.restore.source_path": "Backup file path:",
        "playbook.server.restore.template": "CREATE DATABASE template:",
        "playbook.server.restore.drop": "Drop the existing database first?",
        "playbook.server.restore.sanitize": "What should happen to the restored database?",
        "playbook.server.restore.flag.deactivate_cron": "deactivate_cron — disable cron jobs & outgoing mail",
        "playbook.server.restore.flag.neutralize": (
            "neutralize — neutralize Odoo (payments, IAP, webhooks, bank sync off)"
        ),
        "playbook.server.restore.neutralize_needs_start": (
            "neutralize needs the Odoo container running — without 'start after restore' "
            "only the psql part runs; the odoo-bin neutralize step is skipped."
        ),
        "playbook.server.restore.flag.anonymize": "anonymize — replace personal data with fake data",
        "playbook.server.restore.flag.wipe": "wipe — delete chatter & attachments (incl. files)",
        "playbook.server.restore.flag.purge_transactions": (
            "purge_transactions — delete transactional data (orders, postings, stock)"
        ),
        "playbook.server.restore.purge_master_data": "Also purge ALL master data (destructive template reset)?",
        "playbook.server.restore.purge_warning": (
            "purge_master_data deletes partners, CRM/HR content and attachments — only for template databases!"
        ),
        "playbook.server.sql.menu": "Add SQL statement:",
        "playbook.server.sql.preset_enterprise": "Set enterprise code (preset)",
        "playbook.server.sql.preset_eq_cloud": "Clear eq_cloud connector params (preset)",
        "playbook.server.sql.preset_website": "Swap website domain (preset)",
        "playbook.server.sql.custom": "Custom SQL statement",
        "playbook.server.sql.done": "Done adding statements",
        "playbook.server.sql.custom_input": "SQL statement:",
        "playbook.server.sql.website_domain": "New website domain:",
        "playbook.server.sql.statements": "SQL statements",
        "playbook.server.sql.on_error": "If the SQL step fails:",
        "playbook.server.sql.none_added": "No statements added — skipping the SQL step.",
        "playbook.server.rpc.configure": "Configure the RPC connection block (rpc:)?",
        "playbook.server.rpc.host": "Odoo host/URL (use {{ env.ODOO_URL }} for secrets):",
        "playbook.server.rpc.db": "RPC database:",
        "playbook.server.rpc.model": "Odoo model (e.g. ir.config_parameter):",
        "playbook.server.rpc.mode": "RPC call form:",
        "playbook.server.rpc.mode_method": "method + args",
        "playbook.server.rpc.mode_domain_values": "domain + values (search, then write)",
        "playbook.server.rpc.mode_domain_method": "domain + method",
        "playbook.server.rpc.method": "Method name:",
        "playbook.server.rpc.args": 'Positional args as JSON list (e.g. ["key", "value"], empty = none):',
        "playbook.server.rpc.kwargs": "Keyword args as JSON object (empty = none):",
        "playbook.server.rpc.domain": 'Domain as JSON list (e.g. [["is_company", "=", true]]):',
        "playbook.server.rpc.values": "Values as JSON object:",
        "playbook.server.rpc.invalid_json": "Invalid JSON: {error}",
        "playbook.server.rpc.hint": "Credentials come from ODOO_USER/ODOO_PASSWORD in the env_file.",
        "playbook.server.extra_step.add": "Add another custom step?",
        "playbook.server.extra_step.command": "Step command:",
        "playbook.server.extra_step.name": "Step name (optional):",
        "playbook.server.extra_step.args": "Step args",
        "playbook.server.extra_step.arg_key": "Arg name (empty = done):",
        "playbook.server.extra_step.arg_value": "Value for '{name}':",
        "playbook.server.extra_step.on_error": "If this step fails:",
        "playbook.dev.steps.question": "Which steps should the playbook run?",
        "playbook.dev.steps.none": "No steps selected — using defaults ({defaults}).",
        "playbook.dev.args_header": "Arguments for '{command}'",
        "playbook.dev.arg_prompt": "{command} — {arg}:",
        "playbook.secrets.generate": "Generate a secrets .env file for this playbook?",
        "playbook.secrets.path": "Secrets file path:",
        "playbook.secrets.detected": "These environment variables are referenced in your playbook:",
        "playbook.secrets.value_for": "Value for {name} (empty = fill in later):",
        "playbook.secrets.add_more": "Add another secret variable?",
        "playbook.secrets.key_name": "Variable name (empty = done):",
        "playbook.secrets.exists_merge": "{path} already exists — merge new keys into it (existing values kept)?",
        "playbook.secrets.skipped": (
            "No secrets file written — create {path} manually (chmod 600) before running from cron."
        ),
        "playbook.secrets.written": "Secrets written to {path} (permissions 600).",
        "playbook.secrets.none": "No secret values entered — no env file written.",
        "playbook.output.path": "Output file:",
        "playbook.output.overwrite": "{path} already exists — overwrite?",
        "playbook.summary.header": "Playbook summary",
        "playbook.summary.source": "Source",
        "playbook.summary.destination": "Destination",
        "playbook.summary.source_fresh": "{target} (fresh backup)",
        "playbook.summary.source_file": "file: {path}",
        "playbook.summary.source_newest": "newest in {dir}",
        "playbook.summary.type": "Type",
        "playbook.summary.name": "Name",
        "playbook.summary.version": "Version",
        "playbook.summary.steps": "Steps",
        "playbook.summary.targets": "Targets",
        "playbook.summary.env_file": "Secrets file",
        "playbook.summary.output": "Output path",
        "playbook.summary.confirm": "Write this playbook?",
        "playbook.summary.cancelled": "Playbook creation cancelled.",
        "playbook.summary.written": "Playbook written to {path}",
        "playbook.summary.hint_validate": "Validate: odoodev playbook validate {path}",
        "playbook.summary.hint_dryrun": "Dry-run: odoodev run {path} --dry-run",
        "playbook.summary.hint_cron": (
            "Cron example: 0 2 * * * odoodev run {path} >> /var/log/odoodev-mirror.log 2>&1 (absolute paths!)"
        ),
        "playbook.validate.ok": "Playbook is valid: {steps} step(s), version {version}",
        "playbook.validate.failed": "Playbook invalid: {error}",
        "playbook.create.answers_required": "--non-interactive requires --answers FILE",
        "playbook.create.answers_invalid": "Answers file is invalid:",
        "playbook.create.output_exists": "{path} already exists — pass --force to overwrite",
        "playbook.create.env_exists": (
            "env_file already exists at {path} — pass --force to overwrite or set env_file.generate to false"
        ),
    },
    "de": {
        # --- start.py preflight ---
        "start.env_missing": "Keine .env-Datei unter {path} gefunden.",
        "start.env_missing_hint": (
            "Erstelle sie mit 'odoodev init {version}' oder konfiguriere globale Defaults via 'odoodev setup'."
        ),
        "start.placeholder_password_title": "Unsichere Default-Zugangsdaten",
        "start.placeholder_password_body": (
            "Die .env unter {path} enthält noch das Placeholder-Passwort 'CHANGE_AT_FIRST'.\n"
            "Das ist nur ein Entwicklungs-Default und muss vor jeder echten Nutzung geändert werden."
        ),
        "start.placeholder_password_action": (
            "Führe 'odoodev setup' aus, um ein echtes Passwort zu hinterlegen,\n"
            "und danach 'odoodev init {version}' für eine neue .env.\n"
            "Oder bearbeite {path} direkt und ersetze PGPASSWORD."
        ),
        "start.placeholder_password_continue": "Mit Placeholder-Passwort fortfahren (nur Entwicklung)?",
        "start.placeholder_password_aborted": "Abgebrochen. Bitte echtes Passwort konfigurieren und erneut starten.",
        "start.url_panel_subtitle": "Web: http://localhost:{port}",
        "start.url_panel_with_mailpit": "Web: http://localhost:{port}  |  Mailpit: http://localhost:{mailpit}",
        # --- setup wizard ---
        "setup.welcome": "odoodev Setup-Assistent",
        "setup.lang_question": "Bevorzugte Sprache für CLI-Meldungen?",
        "setup.base_dir_question": "Basisverzeichnis für die Odoo-Entwicklung:",
        "setup.db_user_question": "PostgreSQL-Benutzer:",
        "setup.db_password_question": "PostgreSQL-Passwort:",
        "setup.versions_question": "Aktive Odoo-Versionen:",
        "setup.runtime_question": "Container-Runtime für PostgreSQL:",
        "setup.saved": "Konfiguration gespeichert unter {path}",
        # --- init steps ---
        "init.header": "Initialisiere Odoo v{version} Entwicklungsumgebung",
        "init.step_dirs": "Verzeichnisstruktur anlegen",
        "init.step_env": ".env-Datei erzeugen",
        "init.step_compose": "docker-compose.yml erzeugen",
        "init.step_venv": "Python-Virtual-Environment anlegen",
        "init.step_repos": "Repositories klonen",
        "init.step_docker": "Docker-Dienste starten",
        "init.done": "Odoo v{version} erfolgreich initialisiert.",
        "init.next_steps_title": "Nächste Schritte",
        "init.next_steps_body": (
            "1. {env_path} bearbeiten und PGPASSWORD auf einen echten Wert setzen.\n"
            "2. 'odoodev start {version}' ausführen, um den Server zu starten."
        ),
        # --- db restore ---
        "db.restore_dropping": "Bestehende Datenbank '{name}' wird gelöscht…",
        "db.restore_creating": "Datenbank '{name}' wird angelegt…",
        "db.restore_extracting": "Backup wird entpackt ({fmt})…",
        "db.restore_importing": "SQL wird importiert…",
        "db.restore_postprocess": "Cron-Jobs und Cloud-Integrationen werden deaktiviert…",
        "db.restore_done": "Datenbank '{name}' erfolgreich wiederhergestellt.",
        "db.restore_confirm": "Datenbank '{name}' existiert. Löschen und neu anlegen?",
        # --- tui module export ---
        "tui.export_title": "Module als CSV exportieren (Releasemanager-Format)",
        "tui.export_db_label": "Zieldatenbank (editierbar):",
        "tui.export_db_required": "Bitte einen Datenbanknamen eingeben!",
        "tui.export_opt_all": "Alle verfügbaren Module",
        "tui.export_opt_all_no_ent": "Alle Module ohne Enterprise",
        "tui.export_opt_installed": "Nur installierte Module",
        "tui.export_btn": "CSV exportieren",
        "tui.export_cancel": "Abbrechen",
        "tui.export_saved": "{count} Module exportiert: {path}",
        "tui.export_empty": "Keine Module zum Exportieren.",
        "tui.export_error": "Modul-Export fehlgeschlagen: {error}",
        "tui.export_chk_update": "Apps-Liste vor Export aktualisieren",
        "tui.export_chk_cleanup": "Nicht-installierte Module vor Export entfernen",
        "tui.export_username_label": "Odoo-Login (res.users):",
        "tui.export_password_label": "Passwort:",
        "tui.export_username_required": "Bitte einen Benutzernamen eingeben!",
        "tui.export_chk_remember": "Zugangsdaten für künftige Exporte speichern",
        "tui.export_connecting": "Verbinde mit Odoo...",
        "tui.export_progress_update": "Aktualisiere Apps-Liste...",
        "tui.export_progress_cleanup": "Entferne nicht-installierte Module...",
        "tui.export_progress_listing": "Lade Modulliste...",
        # --- tui backup ---
        "tui.backup_title": "Datenbank sichern",
        "tui.backup_db_label": "Zu sichernde Datenbank (editierbar):",
        "tui.backup_db_required": "Bitte einen Datenbanknamen eingeben!",
        "tui.backup_opt_zip": "ZIP (SQL + Filestore)",
        "tui.backup_opt_sql": "Nur SQL",
        "tui.backup_btn": "Backup erstellen",
        "tui.backup_cancel": "Abbrechen",
        "tui.backup_running": "Erstelle Backup von '{db}'…",
        "tui.backup_saved": "Backup gespeichert: {path} ({size})",
        "tui.backup_empty": "Backup fehlgeschlagen (keine Ausgabe erzeugt).",
        "tui.backup_error": "Backup fehlgeschlagen: {error}",
        # --- tui database switch ---
        "tui.switch_db_title": "Datenbank wechseln",
        "tui.switch_db_hint": "Datenbank wählen — der Server startet damit neu.",
        "tui.switch_db_current": "(aktuell)",
        "tui.switch_db_empty": "Keine Datenbanken gefunden.",
        "tui.switch_db_cancel": "Abbrechen",
        "tui.switch_db_switching": "Wechsel zu '{db}' — Server startet neu…",
        # --- tui module maintenance ---
        "tui.modules_updating": "Apps-Liste wird aktualisiert…",
        "tui.modules_updated": "Apps-Liste aktualisiert ({count} neue Module).",
        "tui.modules_update_error": "Aktualisierung der Apps-Liste fehlgeschlagen: {error}",
        "tui.modules_cleaning": "Nicht-installierte Module werden entfernt…",
        "tui.modules_cleaned": "{count} nicht-installierte Module entfernt.",
        "tui.modules_clean_error": "Modul-Cleanup fehlgeschlagen: {error}",
        # --- tui quick menu ---
        "tui.menu_title": "Schnellmenü — ↑/↓ + Enter, Esc schließt",
        "tui.menu_view": "Ansicht",
        "tui.menu_all_levels": "Alle Level",
        "tui.menu_issues": "Nur Probleme (WARN + ERROR + CRIT)",
        "tui.menu_only_debug": "Nur DEBUG",
        "tui.menu_only_info": "Nur INFO",
        "tui.menu_only_warning": "Nur WARNING",
        "tui.menu_only_error": "Nur ERROR",
        "tui.menu_only_critical": "Nur CRITICAL",
        "tui.menu_log": "Log",
        "tui.menu_search": "Suchen…",
        "tui.menu_clear": "Log leeren",
        "tui.menu_save": "Sichtbares Log speichern",
        "tui.menu_copy_visible": "Sichtbare Zeilen kopieren",
        "tui.menu_copy_errors": "Fehler kopieren",
        "tui.menu_copy_warnings": "Warnungen + Fehler kopieren",
        "tui.menu_export": "Export",
        "tui.menu_export_csv": "Module als CSV exportieren →",
        "tui.menu_modules": "Module",
        "tui.menu_update_apps": "Apps-Liste aktualisieren",
        "tui.menu_cleanup_modules": "Nicht-installierte Module entfernen",
        "tui.menu_server": "Server",
        "tui.menu_restart": "Server neu starten",
        "tui.menu_update": "Modul aktualisieren…",
        "tui.menu_load_language": "Sprache laden…",
        "tui.menu_backup": "Datenbank sichern…",
        "tui.menu_switch_db": "Datenbank wechseln…",
        # --- db users TUI ---
        "users_tui.title": "odoodev db users — {db}",
        "users_tui.col_login": "Login",
        "users_tui.col_name": "Name",
        "users_tui.col_2fa": "2FA",
        "users_tui.col_active": "Aktiv",
        "users_tui.status_count": "{shown}/{total} Benutzer",
        "users_tui.status_filter": "Filter: {query}",
        "users_tui.status_portal": "inkl. Portal",
        "users_tui.no_users": "Keine Benutzer in '{db}' gefunden.",
        "users_tui.search_placeholder": "Nach Login oder Name filtern…",
        "users_tui.set_password_title": "Passwort für '{login}' setzen",
        "users_tui.set_password_hint": "Wird als pbkdf2_sha512-Hash gespeichert — hier sichtbar (Dev-Tool).",
        "users_tui.set_password_btn": "Passwort setzen",
        "users_tui.set_password_cancel": "Abbrechen",
        "users_tui.set_password_required": "Bitte ein Passwort eingeben!",
        "users_tui.password_set": "Passwort für '{login}' gesetzt.",
        "users_tui.password_error": "Passwort-Reset fehlgeschlagen: {error}",
        "users_tui.disable_2fa_title": "2FA für '{login}' deaktivieren?",
        "users_tui.disable_2fa_hint": "Löscht das TOTP-Secret und entfernt vertrauenswürdige Geräte.",
        "users_tui.disable_2fa_btn": "2FA deaktivieren",
        "users_tui.disable_2fa_cancel": "Abbrechen",
        "users_tui.disabled_2fa": "2FA für '{login}' deaktiviert.",
        "users_tui.disable_2fa_error": "2FA-Deaktivierung fehlgeschlagen: {error}",
        "users_tui.already_disabled": "2FA ist für '{login}' nicht aktiv.",
        "users_tui.pick_db_first": "Bitte zuerst eine Datenbank wählen.",
        "users_tui.no_selection": "Kein Benutzer ausgewählt.",
        "users_tui.key_password": "Passwort setzen",
        "users_tui.key_2fa": "2FA deaktivieren",
        "users_tui.key_switch_db": "DB wechseln",
        "users_tui.key_search": "Suche",
        "users_tui.key_quit": "Beenden",
        # --- playbook assistant ---
        "playbook.wizard.header": "odoodev Playbook-Assistent",
        "playbook.wizard.subtitle": "Fragen beantworten — heraus kommt eine lauffähige Playbook-YAML.",
        "playbook.lang.question": "Sprache / Language?",
        "playbook.lang.persist": "Als Standardsprache für odoodev speichern?",
        "playbook.lang.saved": "Sprache gespeichert in {path}.",
        "playbook.step.prefix": "Schritt {step}/{total} — {title}",
        "playbook.step.basics": "Grundlagen",
        "playbook.step.source": "Quelle",
        "playbook.step.source_sub": "Woher kommen die Daten?",
        "playbook.step.dest": "Ziel",
        "playbook.step.dest_sub": "Wohin sollen die Daten?",
        "playbook.step.flow": "Ablauf-Optionen",
        "playbook.step.flow_sub": "Was soll dabei passieren?",
        "playbook.step.steps": "Schritte",
        "playbook.step.secrets": "Variablen & Zugangsdaten",
        "playbook.step.summary": "Zusammenfassung",
        "playbook.server.intro": (
            "Ein Mirror kopiert ein Odoo-System auf ein anderes: QUELLE -> ZIEL.\n"
            "Der Assistent fragt drei Dinge: 1) Woher kommen die Daten?\n"
            "2) Wohin sollen sie? 3) Was soll dabei passieren?"
        ),
        "playbook.type.question": "Welche Art Playbook möchtest du erstellen?",
        "playbook.type.dev": "Dev-Mode (lokale Odoo-Entwicklungsumgebung)",
        "playbook.type.server": "Server-Mode (Kundenserver mit Docker-Containern)",
        "playbook.common.name": "Playbook-Name:",
        "playbook.common.name_invalid": "Der Name darf nicht leer sein.",
        "playbook.common.description": "Beschreibung:",
        "playbook.common.version": "Odoo-Version:",
        "playbook.common.on_error": "Was soll bei einem Fehler passieren?",
        "playbook.choice.on_error_stop": "Playbook anhalten (stop)",
        "playbook.choice.on_error_continue": "Mit dem nächsten Schritt weitermachen (continue)",
        "playbook.choice.on_error_inherit": "Standard des Playbooks verwenden (inherit)",
        "playbook.choice.select_mtime": "Neueste Datei nach Änderungszeit (mtime)",
        "playbook.choice.select_filename_ts": "Neueste nach Zeitstempel im Dateinamen (filename_timestamp)",
        "playbook.common.vars": "Eigene Variablen ({{ vars.x }})",
        "playbook.common.vars_add": "Eigene Variable hinzufügen?",
        "playbook.common.var_key": "Variablenname (leer = fertig):",
        "playbook.common.var_value": "Wert für '{name}':",
        "playbook.server.target.name": "Target-Name:",
        "playbook.server.target.db_container": "Name des PostgreSQL-Containers:",
        "playbook.server.target.db_name": "Datenbankname:",
        "playbook.server.target.odoo_container": "Name des Odoo-Containers (leer = keiner):",
        "playbook.server.target.owner": "Datenbank-Owner/-Benutzer:",
        "playbook.server.target.data_dir": "Host-Datenverzeichnis (leer = per docker inspect ermitteln):",
        "playbook.server.target.add_more": "Weiteres Target hinzufügen?",
        "playbook.server.target.need_one": "Mindestens ein Target ist erforderlich.",
        "playbook.server.target.duplicate": "Target '{name}' existiert bereits.",
        "playbook.server.recipe.question": (
            "Welche optionalen Schritte soll der Mirror enthalten? (Restore ist immer dabei)"
        ),
        "playbook.server.source.question": "Was ist die QUELLE des Mirrors?",
        "playbook.server.source.fresh": "Frisches Backup vom laufenden Quellsystem erstellen",
        "playbook.server.source.file": "Bestehende Backup-Datei verwenden",
        "playbook.server.source.newest": "Neueste Backup-Datei aus einem Verzeichnis nehmen",
        "playbook.server.source.name": "Quell-Name (Bezeichner im Playbook):",
        "playbook.server.source.header": "Quelle — das Container-Paar, VON dem gesichert wird",
        "playbook.server.source.auto_handoff": (
            "Der Restore verwendet automatisch die in diesem Lauf erzeugte Backup-Datei — nichts zu konfigurieren."
        ),
        "playbook.server.dest.header": "Ziel — das Container-Paar, IN das restored wird",
        "playbook.server.dest.name": "Ziel-Name (Bezeichner im Playbook):",
        "playbook.server.dest.self_mirror_warning": (
            "Das Ziel nutzt denselben Datenbank-Container wie die Quelle ('{name}') — "
            "der Restore würde das gerade gesicherte System überschreiben!"
        ),
        "playbook.server.dest.self_mirror_confirm": "Wirklich auf das Quellsystem zurückspielen?",
        "playbook.server.recipe.rebuild": "Ziel-Odoo-Container neu aufbauen (server.rebuild)",
        "playbook.server.recipe.stop_before": "Ziel-Odoo vor dem Restore stoppen (container.stop)",
        "playbook.server.recipe.sql": "Eigenes SQL nach dem Restore ausführen (sql.execute)",
        "playbook.server.recipe.start_after": "Ziel-Odoo nach dem Restore starten (container.start)",
        "playbook.server.recipe.update_all": "Alle Module aktualisieren (server.update-all)",
        "playbook.server.recipe.rpc_call": "RPC-Aufruf nach dem Restore (rpc.execute)",
        "playbook.server.recipe.backup_dir": "Backup-Verzeichnis auf dem Server:",
        "playbook.server.recipe.compression_level": "zstd-Kompressionslevel (1-22):",
        "playbook.server.recipe.only_sql": "Nur SQL sichern (Filestore überspringen)?",
        "playbook.server.recipe.rebuild_target": "Rebuild-Target:",
        "playbook.server.recipe.rebuild_script": "Pfad zu update_docker_odoo.py:",
        "playbook.server.recipe.rebuild_config": "Pfad zu docker2update.yaml:",
        "playbook.server.recipe.rebuild_timeout": "Rebuild-Timeout in Sekunden:",
        "playbook.server.recipe.rebuild_hint": (
            "Der Release-Access-Code liegt in release.txt im Build-Ordner; "
            "der Container muss als aktiver Eintrag in docker2update.yaml existieren."
        ),
        "playbook.server.recipe.update_all_restart": "Container nach dem Modul-Update neu starten?",
        "playbook.server.recipe.update_all_on_error": "Wenn das Modul-Update fehlschlägt:",
        "playbook.server.restore.source_dir": "Backup-Verzeichnis:",
        "playbook.server.restore.source_pattern": "Dateinamen-Muster:",
        "playbook.server.restore.select_by": "Neueste Datei bestimmen nach:",
        "playbook.server.restore.source_path": "Pfad zur Backup-Datei:",
        "playbook.server.restore.template": "CREATE-DATABASE-Template:",
        "playbook.server.restore.drop": "Bestehende Datenbank vorher löschen?",
        "playbook.server.restore.sanitize": "Was soll mit der wiederhergestellten Datenbank passieren?",
        "playbook.server.restore.flag.deactivate_cron": "deactivate_cron — Cronjobs & Mailversand deaktivieren",
        "playbook.server.restore.flag.neutralize": (
            "neutralize — Odoo neutralisieren (Zahlungen, IAP, Webhooks, Bank-Sync aus)"
        ),
        "playbook.server.restore.neutralize_needs_start": (
            "neutralize braucht den laufenden Odoo-Container — ohne 'nach dem Restore starten' "
            "läuft nur der psql-Teil; der odoo-bin-neutralize-Schritt entfällt."
        ),
        "playbook.server.restore.flag.anonymize": "anonymize — Personendaten durch Fake-Daten ersetzen",
        "playbook.server.restore.flag.wipe": "wipe — Chatter & Anhänge löschen (inkl. Dateien)",
        "playbook.server.restore.flag.purge_transactions": (
            "purge_transactions — Bewegungsdaten löschen (Aufträge, Buchungen, Lager)"
        ),
        "playbook.server.restore.purge_master_data": (
            "Zusätzlich ALLE Stammdaten löschen (destruktiver Template-Reset)?"
        ),
        "playbook.server.restore.purge_warning": (
            "purge_master_data löscht Partner, CRM/HR-Inhalte und Anhänge — nur für Template-Datenbanken!"
        ),
        "playbook.server.sql.menu": "SQL-Statement hinzufügen:",
        "playbook.server.sql.preset_enterprise": "Enterprise-Code setzen (Preset)",
        "playbook.server.sql.preset_eq_cloud": "eq_cloud-Connector-Parameter leeren (Preset)",
        "playbook.server.sql.preset_website": "Website-Domain tauschen (Preset)",
        "playbook.server.sql.custom": "Eigenes SQL-Statement",
        "playbook.server.sql.done": "Fertig mit Statements",
        "playbook.server.sql.custom_input": "SQL-Statement:",
        "playbook.server.sql.website_domain": "Neue Website-Domain:",
        "playbook.server.sql.statements": "SQL-Statements",
        "playbook.server.sql.on_error": "Wenn der SQL-Schritt fehlschlägt:",
        "playbook.server.sql.none_added": "Keine Statements hinzugefügt — SQL-Schritt wird übersprungen.",
        "playbook.server.rpc.configure": "RPC-Verbindungsblock (rpc:) konfigurieren?",
        "playbook.server.rpc.host": "Odoo-Host/-URL ({{ env.ODOO_URL }} für Secrets verwenden):",
        "playbook.server.rpc.db": "RPC-Datenbank:",
        "playbook.server.rpc.model": "Odoo-Modell (z. B. ir.config_parameter):",
        "playbook.server.rpc.mode": "Form des RPC-Aufrufs:",
        "playbook.server.rpc.mode_method": "method + args",
        "playbook.server.rpc.mode_domain_values": "domain + values (suchen, dann schreiben)",
        "playbook.server.rpc.mode_domain_method": "domain + method",
        "playbook.server.rpc.method": "Methodenname:",
        "playbook.server.rpc.args": 'Positionale Args als JSON-Liste (z. B. ["key", "value"], leer = keine):',
        "playbook.server.rpc.kwargs": "Keyword-Args als JSON-Objekt (leer = keine):",
        "playbook.server.rpc.domain": 'Domain als JSON-Liste (z. B. [["is_company", "=", true]]):',
        "playbook.server.rpc.values": "Werte als JSON-Objekt:",
        "playbook.server.rpc.invalid_json": "Ungültiges JSON: {error}",
        "playbook.server.rpc.hint": "Zugangsdaten kommen aus ODOO_USER/ODOO_PASSWORD in der env_file.",
        "playbook.server.extra_step.add": "Weiteren eigenen Schritt hinzufügen?",
        "playbook.server.extra_step.command": "Step-Command:",
        "playbook.server.extra_step.name": "Step-Name (optional):",
        "playbook.server.extra_step.args": "Step-Argumente",
        "playbook.server.extra_step.arg_key": "Argumentname (leer = fertig):",
        "playbook.server.extra_step.arg_value": "Wert für '{name}':",
        "playbook.server.extra_step.on_error": "Wenn dieser Schritt fehlschlägt:",
        "playbook.dev.steps.question": "Welche Schritte soll das Playbook ausführen?",
        "playbook.dev.steps.none": "Keine Schritte gewählt — Standard wird verwendet ({defaults}).",
        "playbook.dev.args_header": "Argumente für '{command}'",
        "playbook.dev.arg_prompt": "{command} — {arg}:",
        "playbook.secrets.generate": "Secrets-Datei (.env) für dieses Playbook erzeugen?",
        "playbook.secrets.path": "Pfad der Secrets-Datei:",
        "playbook.secrets.detected": "Diese Umgebungsvariablen werden im Playbook referenziert:",
        "playbook.secrets.value_for": "Wert für {name} (leer = später eintragen):",
        "playbook.secrets.add_more": "Weitere Secret-Variable hinzufügen?",
        "playbook.secrets.key_name": "Variablenname (leer = fertig):",
        "playbook.secrets.exists_merge": "{path} existiert bereits — neue Keys hineinmergen (Bestand bleibt)?",
        "playbook.secrets.skipped": (
            "Keine Secrets-Datei geschrieben — {path} manuell anlegen (chmod 600), bevor das Playbook per Cron läuft."
        ),
        "playbook.secrets.written": "Secrets geschrieben nach {path} (Rechte 600).",
        "playbook.secrets.none": "Keine Secret-Werte eingegeben — es wird keine env-Datei geschrieben.",
        "playbook.output.path": "Ausgabedatei:",
        "playbook.output.overwrite": "{path} existiert bereits — überschreiben?",
        "playbook.summary.header": "Playbook-Zusammenfassung",
        "playbook.summary.source": "Quelle",
        "playbook.summary.destination": "Ziel",
        "playbook.summary.source_fresh": "{target} (frisches Backup)",
        "playbook.summary.source_file": "Datei: {path}",
        "playbook.summary.source_newest": "neueste in {dir}",
        "playbook.summary.type": "Typ",
        "playbook.summary.name": "Name",
        "playbook.summary.version": "Version",
        "playbook.summary.steps": "Schritte",
        "playbook.summary.targets": "Targets",
        "playbook.summary.env_file": "Secrets-Datei",
        "playbook.summary.output": "Ausgabepfad",
        "playbook.summary.confirm": "Playbook schreiben?",
        "playbook.summary.cancelled": "Playbook-Erstellung abgebrochen.",
        "playbook.summary.written": "Playbook geschrieben nach {path}",
        "playbook.summary.hint_validate": "Prüfen: odoodev playbook validate {path}",
        "playbook.summary.hint_dryrun": "Probelauf: odoodev run {path} --dry-run",
        "playbook.summary.hint_cron": (
            "Cron-Beispiel: 0 2 * * * odoodev run {path} >> /var/log/odoodev-mirror.log 2>&1 (absolute Pfade!)"
        ),
        "playbook.validate.ok": "Playbook ist gültig: {steps} Schritt(e), Version {version}",
        "playbook.validate.failed": "Playbook ungültig: {error}",
        "playbook.create.answers_required": "--non-interactive erfordert --answers DATEI",
        "playbook.create.answers_invalid": "Die Answers-Datei ist ungültig:",
        "playbook.create.output_exists": "{path} existiert bereits — --force zum Überschreiben angeben",
        "playbook.create.env_exists": (
            "env_file existiert bereits unter {path} — --force zum Überschreiben angeben "
            "oder env_file.generate auf false setzen"
        ),
    },
}


def normalize_language(lang: str | None) -> str | None:
    """Map raw language tags to supported codes, or return None if unsupported."""
    if not lang:
        return None
    code = lang.strip().lower().split("_", 1)[0].split("-", 1)[0]
    return code if code in SUPPORTED else None


def set_language(lang: str) -> None:
    """Activate the given language. Falls back to default if unsupported."""
    global _active_language
    normalized = normalize_language(lang)
    if normalized is None:
        logger.debug("i18n: unsupported language %r, keeping %r", lang, _active_language)
        return
    _active_language = normalized


def get_language() -> str:
    """Return the currently active language code."""
    return _active_language


def detect_language(cli_flag: str | None = None) -> str:
    """Resolve the active language using the documented precedence chain.

    Order: cli_flag > ODOODEV_LANG env > config file > system locale > default.
    Also records whether the result came from an explicit source (flag, env,
    config) so interactive wizards can offer a language choice otherwise.
    """
    global _explicit_language
    explicit_sources: tuple[str | None, ...] = (
        cli_flag,
        os.environ.get("ODOODEV_LANG"),
        _config_language(),
    )
    for candidate in explicit_sources:
        normalized = normalize_language(candidate)
        if normalized:
            _explicit_language = True
            return normalized
    _explicit_language = False
    return normalize_language(_locale_language()) or DEFAULT_LANGUAGE


def language_was_explicit() -> bool:
    """True when the last detect_language() hit --lang, ODOODEV_LANG or the config file."""
    return _explicit_language


def _config_language() -> str | None:
    """Read cli.language from the global config without raising on errors.

    Returns None when no config file exists — the dataclass default would
    otherwise mask locale detection with a hardcoded "en".
    """
    try:
        from odoodev.core.global_config import config_exists, load_global_config

        if not config_exists():
            return None
        return load_global_config().cli.language
    except (ImportError, AttributeError, OSError):
        return None


def _locale_language() -> str | None:
    """Best-effort system locale detection (de_*, en_*, ...)."""
    try:
        loc, _enc = locale.getlocale()
    except (ValueError, TypeError):
        return None
    return loc


def t(key: str, **kwargs: object) -> str:
    """Translate ``key`` to the active language with optional formatting.

    Falls back through: active language -> English -> the key itself.
    Missing format arguments are left as-is rather than raising — translators
    can iterate without breaking the CLI.
    """
    template = MESSAGES.get(_active_language, {}).get(key)
    if template is None:
        template = MESSAGES["en"].get(key)
    if template is None:
        logger.debug("i18n: missing key %r", key)
        return key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError):
        logger.debug("i18n: format failed for %r with %r", key, kwargs)
        return template
