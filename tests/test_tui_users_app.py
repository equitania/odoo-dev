"""Tests for the user-management TUI (odoodev db users)."""

from __future__ import annotations

import pytest

from odoodev.core.database import UserInfo
from odoodev.tui.users_app import UsersTuiApp
from odoodev.tui.users_screens import ConfirmDisable2faScreen, SetPasswordScreen

USERS = [
    UserInfo(id=1, login="admin", name="Administrator", active=True, totp_enabled=True, share=False),
    UserInfo(id=5, login="jweber", name="Jörg Weber", active=False, totp_enabled=True, share=False),
    UserInfo(id=7, login="mmueller", name="Max Müller", active=True, totp_enabled=False, share=False),
]


@pytest.fixture
def data_layer(monkeypatch):
    """Patch the data layer at the users_app import site; record calls."""
    calls: dict[str, list] = {"list": [], "password": [], "disable": []}

    def fake_list_users(db_name, host=None, port=None, user=None, include_portal=False):
        calls["list"].append((db_name, include_portal))
        return list(USERS)

    monkeypatch.setattr("odoodev.tui.users_app.list_users", fake_list_users)
    monkeypatch.setattr(
        "odoodev.tui.users_app.set_user_password",
        lambda db, uid, pw, **k: (calls["password"].append((db, uid, pw)), (True, ""))[1],
    )
    monkeypatch.setattr(
        "odoodev.tui.users_app.disable_user_2fa",
        lambda db, uid, **k: (calls["disable"].append((db, uid)), (True, "cleared"))[1],
    )
    return calls


def make_app(db_name="v18_exam"):
    return UsersTuiApp(db_name=db_name, host="localhost", port=18432, user="ownerp")


class TestUsersTable:
    async def test_mount_populates_table(self, data_layer):
        app = make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.1)
            table = app.query_one("#users-table")
            assert table.row_count == 3
            assert calls_first_db(data_layer) == ("v18_exam", False)

    async def test_search_filters_rows(self, data_layer):
        app = make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.1)
            await pilot.press("slash")
            await pilot.press("m", "u", "e")  # matches "mmueller" (login) + "Max Müller" via login
            await pilot.pause(0.05)
            table = app.query_one("#users-table")
            assert table.row_count == 1

    async def test_escape_clears_search(self, data_layer):
        app = make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.1)
            await pilot.press("slash")
            await pilot.press("x", "y", "z")
            await pilot.pause(0.05)
            assert app.query_one("#users-table").row_count == 0
            await pilot.press("escape")
            await pilot.pause(0.05)
            assert app.query_one("#users-table").row_count == 3

    async def test_toggle_portal_requeries(self, data_layer):
        app = make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.1)
            await pilot.press("a")
            await pilot.pause(0.05)
            assert data_layer["list"][-1] == ("v18_exam", True)

    async def test_quit(self, data_layer):
        app = make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.1)
            await pilot.press("q")
            await pilot.pause(0.05)
        assert app.return_value is None  # exited cleanly


class TestPasswordReset:
    async def test_p_opens_modal_and_sets_password(self, data_layer):
        app = make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.1)
            await pilot.press("p")
            await pilot.pause(0.05)
            assert isinstance(app.screen, SetPasswordScreen)
            # Input is pre-filled with the dev password — Enter accepts it
            await pilot.press("enter")
            await pilot.pause(0.05)
            assert data_layer["password"] == [("v18_exam", 1, "ownerp")]

    async def test_cancel_does_not_set_password(self, data_layer):
        app = make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.1)
            await pilot.press("p")
            await pilot.pause(0.05)
            await pilot.press("escape")
            await pilot.pause(0.05)
            assert data_layer["password"] == []


class TestDisable2fa:
    async def test_t_confirm_disables(self, data_layer):
        app = make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.1)
            await pilot.press("t")  # cursor on first row (admin, 2FA on)
            await pilot.pause(0.05)
            assert isinstance(app.screen, ConfirmDisable2faScreen)
            await pilot.press("enter")  # focused confirm button
            await pilot.pause(0.1)
            assert data_layer["disable"] == [("v18_exam", 1)]

    async def test_t_on_user_without_2fa_is_noop(self, data_layer):
        app = make_app()
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.1)
            await pilot.press("down", "down")  # cursor → mmueller (no 2FA)
            await pilot.pause(0.05)
            await pilot.press("t")
            await pilot.pause(0.05)
            assert not isinstance(app.screen, ConfirmDisable2faScreen)
            assert data_layer["disable"] == []


class TestInitialDbPicker:
    async def test_no_db_opens_picker_and_cancel_exits(self, data_layer, monkeypatch):
        monkeypatch.setattr("odoodev.core.database.list_databases", lambda **k: ["v18_a", "v18_b"])
        app = make_app(db_name="")
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.1)
            from odoodev.tui.screens import DbSwitchScreen

            assert isinstance(app.screen, DbSwitchScreen)
            await pilot.press("escape")
            await pilot.pause(0.1)
        # cancelled without a DB → app exits, never queried users
        assert data_layer["list"] == []

    async def test_no_db_pick_loads_users(self, data_layer, monkeypatch):
        monkeypatch.setattr("odoodev.core.database.list_databases", lambda **k: ["v18_a"])
        app = make_app(db_name="")
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause(0.1)
            await pilot.press("enter")  # select the only database
            await pilot.pause(0.1)
            assert data_layer["list"] == [("v18_a", False)]


def calls_first_db(calls: dict[str, list]) -> tuple:
    return calls["list"][0]
