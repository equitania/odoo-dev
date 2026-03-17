"""Modal screens for the odoodev TUI."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Static

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
