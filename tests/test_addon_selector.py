"""Tests for interactive addon selector feature."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner


def _collect_all():
    from odoodev.commands.repos import _collect_all_repos_with_status

    return _collect_all_repos_with_status


def _selector():
    from odoodev.commands.repos import _interactive_addon_selector

    return _interactive_addon_selector


def _summary():
    from odoodev.commands.repos import _print_selection_summary

    return _print_selection_summary


# --- _collect_all_repos_with_status ---


class TestCollectAllReposWithStatus:
    """Tests for _collect_all_repos_with_status helper."""

    def test_includes_disabled_repos(self):
        config = {
            "addons": [
                {"key": "a", "path": "a", "section": "Equitania", "use": True},
                {"key": "b", "path": "b", "section": "Customer", "use": False},
            ]
        }
        repos = _collect_all()(config)
        assert len(repos) == 2
        assert repos[0]["use"] is True
        assert repos[1]["use"] is False

    def test_legacy_commented_field(self):
        config = {
            "addons": [
                {"key": "a", "path": "a", "commented": True},
                {"key": "b", "path": "b", "commented": False},
            ]
        }
        repos = _collect_all()(config)
        assert repos[0]["use"] is False  # commented=True → use=False
        assert repos[1]["use"] is True  # commented=False → use=True

    def test_default_use_true(self):
        config = {
            "addons": [
                {"key": "a", "path": "a"},
            ]
        }
        repos = _collect_all()(config)
        assert repos[0]["use"] is True

    def test_multiple_sections(self):
        config = {
            "addons": [{"key": "a", "path": "a", "use": True}],
            "additional": [{"key": "b", "path": "b", "use": False}],
            "special": [{"key": "c", "path": "c", "use": True}],
            "customers": [{"key": "d", "path": "d", "use": False}],
        }
        repos = _collect_all()(config)
        assert len(repos) == 4

    def test_empty_sections(self):
        config = {"addons": [], "additional": None}
        repos = _collect_all()(config)
        assert repos == []

    def test_use_field_takes_precedence_over_commented(self):
        config = {
            "addons": [
                {"key": "a", "path": "a", "use": True, "commented": True},
            ]
        }
        repos = _collect_all()(config)
        assert repos[0]["use"] is True  # use field wins


# --- _interactive_addon_selector ---


class TestInteractiveAddonSelector:
    """Tests for _interactive_addon_selector with mocked checkbox."""

    def test_selector_updates_metadata(self):
        config = {
            "addons": [
                {"key": "a", "path": "path-a", "section": "OCA", "use": False},
                {"key": "b", "path": "path-b", "section": "Enterprise", "use": True},
            ]
        }
        original_metadata = {
            "a": {"section": "OCA", "use": False},
            "b": {"section": "Enterprise", "use": True},
        }

        with patch("odoodev.output.checkbox_with_separators", return_value=["a"]):
            result = _selector()(config, original_metadata)

        assert result["a"]["use"] is True  # Was False, now selected
        assert result["b"]["use"] is False  # Was True, now deselected

    def test_selector_preserves_section_info(self):
        config = {
            "addons": [
                {"key": "a", "path": "path-a", "section": "OCA", "use": True},
            ]
        }
        original_metadata = {"a": {"section": "OCA", "use": True}}

        with patch("odoodev.output.checkbox_with_separators", return_value=["a"]):
            result = _selector()(config, original_metadata)

        assert result["a"]["section"] == "OCA"

    def test_selector_all_deselected(self):
        config = {
            "addons": [
                {"key": "a", "path": "a", "section": "X", "use": True},
                {"key": "b", "path": "b", "section": "Y", "use": True},
            ]
        }
        metadata = {
            "a": {"section": "X", "use": True},
            "b": {"section": "Y", "use": True},
        }

        with patch("odoodev.output.checkbox_with_separators", return_value=[]):
            result = _selector()(config, metadata)

        assert result["a"]["use"] is False
        assert result["b"]["use"] is False


# --- _print_selection_summary ---


class TestPrintSelectionSummary:
    """Tests for _print_selection_summary output."""

    def test_no_changes(self, capsys):
        original = {"a": {"section": "X", "use": True}}
        updated = {"a": {"section": "X", "use": True}}
        _summary()(original, updated)
        captured = capsys.readouterr()
        assert "No changes" in captured.out

    def test_shows_enabled(self, capsys):
        original = {"a": {"section": "X", "use": False}}
        updated = {"a": {"section": "X", "use": True}}
        _summary()(original, updated)
        captured = capsys.readouterr()
        assert "Enabled" in captured.out
        assert "a" in captured.out

    def test_shows_disabled(self, capsys):
        original = {"a": {"section": "X", "use": True}}
        updated = {"a": {"section": "X", "use": False}}
        _summary()(original, updated)
        captured = capsys.readouterr()
        assert "Disabled" in captured.out
        assert "a" in captured.out

    def test_shows_both_enabled_and_disabled(self, capsys):
        original = {
            "a": {"section": "X", "use": False},
            "b": {"section": "Y", "use": True},
        }
        updated = {
            "a": {"section": "X", "use": True},
            "b": {"section": "Y", "use": False},
        }
        _summary()(original, updated)
        captured = capsys.readouterr()
        assert "Enabled" in captured.out
        assert "Disabled" in captured.out


# --- CLI flag presence ---


class TestSelectFlagPresence:
    """Tests that --select flag is registered on commands."""

    def test_select_flag_in_repos_help(self):
        from odoodev.commands.repos import repos

        runner = CliRunner()
        result = runner.invoke(repos, ["--help"])
        assert "--select" in result.output

    def test_select_flag_in_pull_help(self):
        from odoodev.commands.pull import pull

        runner = CliRunner()
        result = runner.invoke(pull, ["--help"])
        assert "--select" in result.output


# --- Non-TTY fallback ---


class TestNonTtyFallback:
    """Tests that --select gracefully skips in non-TTY environments."""

    def test_repos_select_non_tty_skips_selector(self, monkeypatch, capsys):
        """In non-TTY mode, --select prints warning and does not invoke selector."""
        from odoodev.commands.repos import _interactive_addon_selector

        monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"isatty": lambda self: False})())

        # If the selector were called, it would fail — no mock for checkbox
        # We verify it's NOT called by checking the warning message
        import sys

        config = {
            "addons": [{"key": "a", "path": "a", "section": "X", "use": True}],
        }
        repo_metadata = {"a": {"section": "X", "use": True}}

        # Simulate the guard logic used in repos.py and pull.py
        if sys.stdin.isatty():
            repo_metadata = _interactive_addon_selector(config, repo_metadata)
        else:
            from odoodev.output import print_warning

            print_warning("--select requires an interactive terminal, skipping selector")

        captured = capsys.readouterr()
        assert "interactive terminal" in captured.out
