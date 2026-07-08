"""Modal screens for the user-management TUI (odoodev db users)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from odoodev.i18n import t


class SetPasswordScreen(ModalScreen["str | None"]):
    """Modal dialog to set a new password for one user.

    The input is pre-filled with the team-wide dev password and deliberately
    visible (not masked): this is a local dev tool and the value must be
    legible and quickly editable. Returns the password via ``dismiss`` or
    ``None`` on cancel.
    """

    DEFAULT_CSS = """
    SetPasswordScreen {
        align: center middle;
    }
    #password-dialog {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #password-dialog Label {
        margin-bottom: 1;
    }
    #password-input {
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

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, login: str, default_password: str) -> None:
        super().__init__()
        self._login = login
        self._default_password = default_password

    def compose(self) -> ComposeResult:
        with Vertical(id="password-dialog"):
            yield Label(t("users_tui.set_password_title", login=self._login))
            yield Static(f"[dim]{t('users_tui.set_password_hint')}[/]")
            yield Input(value=self._default_password, id="password-input")
            with Vertical(classes="button-row"):
                yield Button(t("users_tui.set_password_btn"), variant="primary", id="btn-set")
                yield Button(t("users_tui.set_password_cancel"), variant="error", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#password-input", Input).focus()

    def _submit(self) -> None:
        pw_input = self.query_one("#password-input", Input)
        password = pw_input.value
        if not password:
            pw_input.placeholder = t("users_tui.set_password_required")
            return
        self.dismiss(password)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
        elif event.button.id == "btn-set":
            self._submit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)


class ConfirmDisable2faScreen(ModalScreen[bool]):
    """Yes/no confirmation before clearing a user's TOTP secret + devices.

    Returns True via ``dismiss`` when confirmed, False otherwise.
    """

    DEFAULT_CSS = """
    ConfirmDisable2faScreen {
        align: center middle;
    }
    #disable2fa-dialog {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #disable2fa-dialog Label {
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

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, login: str) -> None:
        super().__init__()
        self._login = login

    def compose(self) -> ComposeResult:
        with Vertical(id="disable2fa-dialog"):
            yield Label(t("users_tui.disable_2fa_title", login=self._login))
            yield Static(f"[dim]{t('users_tui.disable_2fa_hint')}[/]")
            with Vertical(classes="button-row"):
                yield Button(t("users_tui.disable_2fa_btn"), variant="error", id="btn-disable")
                yield Button(t("users_tui.disable_2fa_cancel"), variant="default", id="btn-cancel")

    def on_mount(self) -> None:
        self.query_one("#btn-disable", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-disable")

    def action_cancel(self) -> None:
        self.dismiss(False)
