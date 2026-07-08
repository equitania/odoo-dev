"""Textual TUI for Odoo user management (password reset + 2FA disable).

Launched via ``odoodev db users``. Separate from the server-runtime TUI
(:mod:`odoodev.tui.app`): this app talks straight to PostgreSQL through the
core database helpers, no Odoo process involved.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Input, Static

from odoodev.core.database import (
    DEFAULT_DEV_PASSWORD,
    UserInfo,
    disable_user_2fa,
    list_users,
    set_user_password,
)
from odoodev.i18n import t
from odoodev.tui.screens import DbSwitchScreen
from odoodev.tui.users_screens import ConfirmDisable2faScreen, SetPasswordScreen


class UsersTuiApp(App):
    """Pick a database, browse its users, reset passwords and disable 2FA."""

    CSS_PATH = "users_app.tcss"

    BINDINGS = [
        Binding("q", "quit_app", "Quit", priority=True),
        Binding("ctrl+q", "quit_app", "Quit", priority=True, show=False),
        Binding("p", "set_password", "Set password"),
        Binding("t", "disable_2fa", "Disable 2FA"),
        Binding("d", "switch_db", "Switch DB"),
        Binding("slash", "search", "Search"),
        Binding("a", "toggle_portal", "Portal users", show=False),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("escape", "clear_search", "Clear search", show=False),
    ]

    def __init__(
        self,
        db_name: str = "",
        host: str = "localhost",
        port: int = 18432,
        user: str = "ownerp",
    ) -> None:
        super().__init__()
        self._db_name = db_name
        self._host = host
        self._port = port
        self._user = user
        self._users: list[UserInfo] = []
        self._filter_query = ""
        self._include_portal = False

    # ------------------------------------------------------------------ UI --

    def compose(self) -> ComposeResult:
        yield Static("", id="users-title")
        yield Input(placeholder=t("users_tui.search_placeholder"), id="users-search")
        table: DataTable = DataTable(id="users-table", cursor_type="row", zebra_stripes=True)
        yield table
        yield Static("", id="users-status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#users-table", DataTable)
        table.add_columns(
            t("users_tui.col_login"),
            t("users_tui.col_name"),
            t("users_tui.col_2fa"),
            t("users_tui.col_active"),
        )
        self.query_one("#users-search", Input).display = False
        if self._db_name:
            self._reload_users()
        else:
            self._open_db_picker(initial=True)
        table.focus()

    def _update_title(self) -> None:
        title = t("users_tui.title", db=self._db_name or "—")
        self.query_one("#users-title", Static).update(f"[b]{title}[/]")

    def _visible_users(self) -> list[UserInfo]:
        if not self._filter_query:
            return self._users
        query = self._filter_query.lower()
        return [u for u in self._users if query in u.login.lower() or query in u.name.lower()]

    def _reload_users(self) -> None:
        """Fetch users from the database and rebuild the table."""
        self._users = list_users(
            self._db_name,
            host=self._host,
            port=self._port,
            user=self._user,
            include_portal=self._include_portal,
        )
        self._refresh_table()
        self._update_title()

    def _refresh_table(self) -> None:
        """Re-render table rows from the current user list + filter."""
        table = self.query_one("#users-table", DataTable)
        table.clear()
        for u in self._visible_users():
            totp = "[green]✔[/]" if u.totp_enabled else "[dim]—[/]"
            active = "[green]✔[/]" if u.active else "[red]✘[/]"
            login = u.login if u.active else f"[dim]{u.login}[/]"
            table.add_row(login, u.name, totp, active, key=str(u.id))
        self._update_status()

    def _update_status(self) -> None:
        parts = [t("users_tui.status_count", shown=len(self._visible_users()), total=len(self._users))]
        if self._filter_query:
            parts.append(t("users_tui.status_filter", query=self._filter_query))
        if self._include_portal:
            parts.append(t("users_tui.status_portal"))
        if not self._users and self._db_name:
            parts.append(t("users_tui.no_users", db=self._db_name))
        self.query_one("#users-status", Static).update("[dim]" + "  ·  ".join(parts) + "[/]")

    def _selected_user(self) -> UserInfo | None:
        """The user behind the highlighted table row (row key = user id)."""
        table = self.query_one("#users-table", DataTable)
        if table.row_count == 0 or table.cursor_row is None:
            return None
        try:
            row_key = list(table.rows.keys())[table.cursor_row]
        except IndexError:
            return None
        key_value = row_key.value if hasattr(row_key, "value") else row_key
        for u in self._users:
            if str(u.id) == str(key_value):
                return u
        return None

    # ------------------------------------------------------------- actions --

    def action_quit_app(self) -> None:
        self.exit()

    def action_set_password(self) -> None:
        user = self._selected_user()
        if user is None:
            self.notify(t("users_tui.no_selection"), severity="warning")
            return

        def _on_password(password: str | None) -> None:
            if password is None:
                return
            ok, msg = set_user_password(
                self._db_name, user.id, password, host=self._host, port=self._port, user=self._user
            )
            if ok:
                self.notify(t("users_tui.password_set", login=user.login))
            else:
                self.notify(t("users_tui.password_error", error=msg.strip()), severity="error")

        self.push_screen(SetPasswordScreen(user.login, DEFAULT_DEV_PASSWORD), _on_password)

    def action_disable_2fa(self) -> None:
        user = self._selected_user()
        if user is None:
            self.notify(t("users_tui.no_selection"), severity="warning")
            return
        if not user.totp_enabled:
            self.notify(t("users_tui.already_disabled", login=user.login))
            return

        def _on_confirm(confirmed: bool | None) -> None:
            if not confirmed:
                return
            ok, msg = disable_user_2fa(self._db_name, user.id, host=self._host, port=self._port, user=self._user)
            if ok:
                self.notify(t("users_tui.disabled_2fa", login=user.login))
                self._reload_users()
            else:
                self.notify(t("users_tui.disable_2fa_error", error=msg.strip()), severity="error")

        self.push_screen(ConfirmDisable2faScreen(user.login), _on_confirm)

    def action_switch_db(self) -> None:
        self._open_db_picker(initial=False)

    def _open_db_picker(self, initial: bool) -> None:
        def _on_db_picked(db_name: str | None) -> None:
            if db_name:
                self._db_name = db_name
                self._filter_query = ""
                self.query_one("#users-search", Input).value = ""
                self._reload_users()
            elif initial and not self._db_name:
                # Cancelled the initial picker without ever choosing a DB.
                self.exit()

        self.push_screen(DbSwitchScreen(db_port=self._port, current_db=self._db_name), _on_db_picked)

    def action_search(self) -> None:
        search = self.query_one("#users-search", Input)
        search.display = True
        search.focus()

    def action_clear_search(self) -> None:
        search = self.query_one("#users-search", Input)
        if search.display:
            search.value = ""
            search.display = False
            self._filter_query = ""
            self._refresh_table()
            self.query_one("#users-table", DataTable).focus()

    def action_toggle_portal(self) -> None:
        self._include_portal = not self._include_portal
        self._reload_users()

    def action_refresh(self) -> None:
        self._reload_users()

    # -------------------------------------------------------------- events --

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "users-search":
            self._filter_query = event.value.strip()
            self._refresh_table()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "users-search":
            self.query_one("#users-table", DataTable).focus()
