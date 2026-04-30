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
