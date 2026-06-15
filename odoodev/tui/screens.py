"""Modal screens for the odoodev TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, OptionList, RadioButton, RadioSet, Static
from textual.widgets.option_list import Option

from odoodev.i18n import t
from odoodev.tui.odoo_process import OdooProcess


class ModuleUpdateScreen(ModalScreen[str | None]):
    """Modal dialog for updating Odoo modules.

    Supports two update strategies:
    - Restart with -u flag (reliable, full restart)
    - XML-RPC hot update (fast, no restart needed)
    """

    DEFAULT_CSS = """
    ModuleUpdateScreen {
        align: center middle;
    }
    #update-dialog {
        width: 70;
        height: auto;
        max-height: 20;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #update-dialog Label {
        margin-bottom: 1;
    }
    #module-input {
        width: 100%;
        margin-bottom: 1;
    }
    .button-row {
        height: 3;
        align: center middle;
        layout: horizontal;
    }
    .button-row Button {
        margin: 0 1;
    }
    """

    def __init__(self, process: OdooProcess, odoo_port: int = 0, db_name: str = "") -> None:
        super().__init__()
        self._process = process
        self._odoo_port = odoo_port
        self._db_name = db_name

    def compose(self) -> ComposeResult:
        """Build the update dialog."""
        with Vertical(id="update-dialog"):
            yield Label("Update Odoo Module(s)")
            yield Static("[dim]Enter module name(s), comma-separated[/]")
            yield Input(placeholder="e.g. eq_sale,eq_stock", id="module-input")
            with Vertical(classes="button-row"):
                yield Button("Restart with -u", variant="primary", id="btn-restart")
                yield Button("Hot Update (XML-RPC)", variant="default", id="btn-xmlrpc")
                yield Button("Cancel", variant="error", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "btn-cancel":
            self.dismiss(None)
            return

        module_input = self.query_one("#module-input", Input)
        modules = module_input.value.strip()
        if not modules:
            module_input.placeholder = "Please enter at least one module name!"
            return

        if event.button.id == "btn-restart":
            self._restart_with_update(modules)
        elif event.button.id == "btn-xmlrpc":
            self._xmlrpc_update(modules)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input — default to restart."""
        modules = event.value.strip()
        if modules:
            self._restart_with_update(modules)

    def _restart_with_update(self, modules: str) -> None:
        """Restart Odoo with -u flag for the given modules."""
        module_list = [m.strip() for m in modules.split(",") if m.strip()]
        self._process.restart(extra_args=["-u", ",".join(module_list)])
        self.dismiss(f"restart:{','.join(module_list)}")

    def _xmlrpc_update(self, modules: str) -> None:
        """Trigger module update via XML-RPC."""
        module_list = [m.strip() for m in modules.split(",") if m.strip()]
        try:
            from odoodev.tui.xmlrpc_client import OdooXmlRpcClient

            client = OdooXmlRpcClient(port=self._odoo_port, database=self._db_name)
            updated = client.upgrade_modules(module_list)
            if updated:
                self.dismiss(f"xmlrpc:{','.join(module_list)}")
            else:
                # Fallback to restart
                self._restart_with_update(modules)
        except Exception:
            # XML-RPC failed — fallback to restart
            import logging

            logging.getLogger(__name__).debug("XML-RPC update failed, falling back to restart", exc_info=True)
            self._restart_with_update(modules)


class LanguageLoadScreen(ModalScreen[str | None]):
    """Modal dialog for loading/reloading Odoo translations.

    Restarts Odoo with --load-language and optionally --i18n-overwrite flags.
    """

    DEFAULT_CSS = """
    LanguageLoadScreen {
        align: center middle;
    }
    #lang-dialog {
        width: 70;
        height: auto;
        max-height: 22;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #lang-dialog Label {
        margin-bottom: 1;
    }
    #lang-input {
        width: 100%;
        margin-bottom: 1;
    }
    #lang-overwrite {
        margin-bottom: 1;
    }
    .button-row {
        height: 3;
        align: center middle;
        layout: horizontal;
    }
    .button-row Button {
        margin: 0 1;
    }
    """

    def __init__(self, process: OdooProcess) -> None:
        super().__init__()
        self._process = process

    def compose(self) -> ComposeResult:
        """Build the language load dialog."""
        with Vertical(id="lang-dialog"):
            yield Label("Load Language / Reload Translations")
            yield Static("[dim]Enter language code (e.g. de_DE, fr_FR) or 'all'[/]")
            yield Input(placeholder="e.g. de_DE, fr_FR, all", id="lang-input")
            yield Checkbox("Overwrite existing translations (--i18n-overwrite)", id="lang-overwrite")
            with Vertical(classes="button-row"):
                yield Button("Load Language (Restart)", variant="primary", id="btn-load")
                yield Button("Cancel", variant="error", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "btn-cancel":
            self.dismiss(None)
            return
        if event.button.id == "btn-load":
            self._do_load()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input — trigger load."""
        if event.value.strip():
            self._do_load()

    def _do_load(self) -> None:
        """Restart Odoo with language loading flags."""
        lang_input = self.query_one("#lang-input", Input)
        lang = lang_input.value.strip()
        if not lang:
            lang_input.placeholder = "Please enter a language code!"
            return

        overwrite = self.query_one("#lang-overwrite", Checkbox).value
        args: list[str] = [f"--load-language={lang}"]
        if overwrite:
            args.append("--i18n-overwrite")
            # Odoo requires -u (update) when --i18n-overwrite is used
            args.extend(["-u", "all"])

        self._process.restart(extra_args=args)
        overwrite_label = " (overwrite)" if overwrite else ""
        self.dismiss(f"lang:{lang}{overwrite_label}")


class ExportModulesScreen(ModalScreen["tuple[str, str] | None"]):
    """Modal dialog to choose scope and database for the Releasemanager CSV.

    Returns ``(scope, db_name)`` via ``dismiss`` — ``scope`` is one of the
    ``EXPORT_SCOPES`` keys ('all', 'all_no_enterprise', 'installed') and
    ``db_name`` is the (editable) target database — or ``None`` on cancel.
    """

    DEFAULT_CSS = """
    ExportModulesScreen {
        align: center middle;
    }
    #export-dialog {
        width: 72;
        height: auto;
        max-height: 24;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #export-dialog Label {
        margin-bottom: 1;
    }
    #export-db {
        width: 100%;
        margin-bottom: 1;
    }
    #export-options {
        width: 100%;
        margin-bottom: 1;
    }
    .button-row {
        height: 3;
        align: center middle;
        layout: horizontal;
    }
    .button-row Button {
        margin: 0 1;
    }
    """

    _SCOPE_BY_ID = {
        "opt-all": "all",
        "opt-all-no-ent": "all_no_enterprise",
        "opt-installed": "installed",
    }

    def __init__(self, db_name: str = "") -> None:
        super().__init__()
        self._db_name = db_name

    def compose(self) -> ComposeResult:
        """Build the export dialog."""
        with Vertical(id="export-dialog"):
            yield Label(t("tui.export_title"))
            yield Static(f"[dim]{t('tui.export_db_label')}[/]")
            yield Input(value=self._db_name, placeholder="v18_exam", id="export-db")
            yield RadioSet(
                RadioButton(t("tui.export_opt_all"), id="opt-all", value=True),
                RadioButton(t("tui.export_opt_all_no_ent"), id="opt-all-no-ent"),
                RadioButton(t("tui.export_opt_installed"), id="opt-installed"),
                id="export-options",
            )
            with Vertical(classes="button-row"):
                yield Button(t("tui.export_btn"), variant="primary", id="btn-export")
                yield Button(t("tui.export_cancel"), variant="error", id="btn-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button clicks."""
        if event.button.id == "btn-cancel":
            self.dismiss(None)
            return
        if event.button.id == "btn-export":
            self._do_export()

    def _do_export(self) -> None:
        """Validate the database field and dismiss with (scope, db_name)."""
        db_input = self.query_one("#export-db", Input)
        db_name = db_input.value.strip()
        if not db_name:
            db_input.placeholder = t("tui.export_db_required")
            return
        radio_set = self.query_one("#export-options", RadioSet)
        pressed = radio_set.pressed_button
        button_id = pressed.id if pressed is not None else "opt-all"
        scope = self._SCOPE_BY_ID.get(button_id or "opt-all", "all")
        self.dismiss((scope, db_name))


class QuickMenuScreen(ModalScreen["str | None"]):
    """Bottom-anchored action menu that folds upward.

    Consolidates view filters, log actions, export and server controls into a
    single keyboard-navigable list (arrows + Enter), so the footer can stay
    minimal on narrow terminals. Returns the chosen action name via ``dismiss``
    (the option id equals the app's ``action_*`` name), or ``None`` on cancel.
    """

    DEFAULT_CSS = """
    QuickMenuScreen {
        align: center bottom;
        background: $background 40%;
    }
    #quick-menu {
        width: 56;
        height: auto;
        max-height: 26;
        border: tall $primary;
        background: $surface;
        margin-bottom: 1;
        padding: 0 1;
    }
    #quick-menu Label {
        margin: 0 1;
    }
    #quick-menu-list {
        height: auto;
        max-height: 24;
    }
    """

    BINDINGS = [
        ("escape", "dismiss_menu", "Close"),
        ("m", "dismiss_menu", "Close"),
    ]

    def compose(self) -> ComposeResult:
        """Build the grouped quick-action menu."""
        with Vertical(id="quick-menu"):
            yield Label(t("tui.menu_title"))
            yield OptionList(
                Option(f"[b cyan]{t('tui.menu_view')}[/]", disabled=True),
                Option(t("tui.menu_all_levels"), id="filter_all"),
                Option(t("tui.menu_issues"), id="filter_issues"),
                Option(t("tui.menu_only_warning"), id="show_only_warning"),
                Option(t("tui.menu_only_error"), id="show_only_error"),
                Option(t("tui.menu_only_critical"), id="show_only_critical"),
                Option(t("tui.menu_only_info"), id="show_only_info"),
                Option(t("tui.menu_only_debug"), id="show_only_debug"),
                None,
                Option(f"[b cyan]{t('tui.menu_log')}[/]", disabled=True),
                Option(t("tui.menu_search"), id="search"),
                Option(t("tui.menu_clear"), id="clear_log"),
                Option(t("tui.menu_save"), id="save_log"),
                Option(t("tui.menu_copy_visible"), id="copy_visible"),
                Option(t("tui.menu_copy_errors"), id="copy_errors"),
                Option(t("tui.menu_copy_warnings"), id="copy_warnings"),
                None,
                Option(f"[b cyan]{t('tui.menu_export')}[/]", disabled=True),
                Option(t("tui.menu_export_csv"), id="export_modules"),
                None,
                Option(f"[b cyan]{t('tui.menu_server')}[/]", disabled=True),
                Option(t("tui.menu_restart"), id="restart"),
                Option(t("tui.menu_update"), id="update"),
                Option(t("tui.menu_load_language"), id="load_language"),
                id="quick-menu-list",
                compact=True,
            )

    def on_mount(self) -> None:
        """Focus the option list so arrow keys work immediately."""
        self.query_one("#quick-menu-list", OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Dismiss with the selected action name."""
        self.dismiss(event.option.id)

    def action_dismiss_menu(self) -> None:
        """Close the menu without selecting anything."""
        self.dismiss(None)


HELP_SECTIONS: tuple[tuple[str, tuple[tuple[str, str], ...]], ...] = (
    (
        "Server Control",
        (
            ("r", "Restart Odoo server"),
            ("u", "Update module (-u restart or XML-RPC hot update)"),
            ("l", "Load language / reload translations"),
            ("q / Ctrl+Q", "Quit (stops the server)"),
        ),
    ),
    (
        "Log Filtering",
        (
            ("0", "Show all levels"),
            ("1-5", "Toggle DEBUG / INFO / WARNING / ERROR / CRITICAL"),
            ("f", "Issues only (WARN + ERROR + CRIT)"),
            ("/", "Search log output (Escape clears)"),
            ("Space", "Toggle auto-scroll"),
            ("Ctrl+L", "Clear log display"),
        ),
    ),
    (
        "Clipboard & Export",
        (
            ("c", "Copy visible (filtered) lines to clipboard"),
            ("e", "Copy ERROR/CRITICAL lines to clipboard"),
            ("w", "Copy WARN + ERROR + CRIT lines to clipboard"),
            ("s", "Save visible log to ~/odoodev-logs/"),
            ("x", "Export module list as CSV to ~/Downloads/"),
        ),
    ),
    (
        "Menu & Help",
        (
            ("m", "Open the quick action menu (folds up from the bottom)"),
            ("?", "Show this overlay (Escape or q closes)"),
        ),
    ),
)


class HelpScreen(ModalScreen[None]):
    """Full keybinding reference overlay."""

    BINDINGS = [
        ("escape", "dismiss_help", "Close"),
        ("q", "dismiss_help", "Close"),
        ("question_mark", "dismiss_help", "Close"),
    ]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-dialog {
        width: 76;
        height: auto;
        max-height: 38;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
        overflow-y: auto;
    }
    #help-dialog .help-section {
        margin-top: 1;
    }
    """

    def compose(self) -> ComposeResult:
        """Build the help overlay from HELP_SECTIONS."""
        with Vertical(id="help-dialog"):
            yield Label("[bold]odoodev TUI — Keybindings[/bold]")
            for section, entries in HELP_SECTIONS:
                yield Static(f"[bold cyan]{section}[/bold cyan]", classes="help-section")
                for key, description in entries:
                    yield Static(f"  [bold]{key:<10}[/bold] {description}")
            yield Static("")
            yield Button("Close", variant="primary", id="btn-help-close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-help-close":
            self.dismiss(None)

    def action_dismiss_help(self) -> None:
        self.dismiss(None)
