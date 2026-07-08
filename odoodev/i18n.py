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
    """
    chain: list[str | None] = [
        cli_flag,
        os.environ.get("ODOODEV_LANG"),
        _config_language(),
        _locale_language(),
    ]
    for candidate in chain:
        normalized = normalize_language(candidate)
        if normalized:
            return normalized
    return DEFAULT_LANGUAGE


def _config_language() -> str | None:
    """Read cli.language from the global config without raising on errors."""
    try:
        from odoodev.core.global_config import load_global_config

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
