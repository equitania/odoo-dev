"""Tests for shell integration: completions, abbreviations, and shell functions."""

from __future__ import annotations

import os

from click.testing import CliRunner

from odoodev.commands.config import config
from odoodev.core.shell_integration import (
    BASH_FUNCTION,
    FISH_FUNCTION,
    ZSH_FUNCTION,
    get_shell_config_path,
    get_shell_function,
    install_shell_function,
)


class TestFishCompletions:
    """Test Fish shell completion content."""

    def test_fish_contains_click_completion_function(self):
        assert "_odoodev_completion" in FISH_FUNCTION

    def test_fish_contains_complete_command(self):
        assert "complete --no-files --command odoodev" in FISH_FUNCTION

    def test_fish_contains_activate_completion(self):
        assert "--command odoodev-activate" in FISH_FUNCTION

    def test_fish_contains_versions_plain_call(self):
        assert "odoodev config versions --plain" in FISH_FUNCTION

    def test_fish_contains_abbreviations(self):
        assert "abbr -a --global oda" in FISH_FUNCTION
        assert "abbr -a --global odev" in FISH_FUNCTION

    def test_fish_contains_odoodev_activate_function(self):
        assert "function odoodev-activate" in FISH_FUNCTION

    def test_fish_completion_uses_fish_complete_env(self):
        assert "_ODOODEV_COMPLETE=fish_complete" in FISH_FUNCTION


class TestBashCompletions:
    """Test Bash shell completion content."""

    def test_bash_contains_click_completion(self):
        assert "_ODOODEV_COMPLETE=bash_source" in BASH_FUNCTION

    def test_bash_contains_activate_completion(self):
        assert "_odoodev_activate_completions" in BASH_FUNCTION
        assert "complete -F _odoodev_activate_completions odoodev-activate" in BASH_FUNCTION

    def test_bash_contains_versions_plain_call(self):
        assert "odoodev config versions --plain" in BASH_FUNCTION

    def test_bash_contains_aliases(self):
        assert "alias oda='odoodev-activate'" in BASH_FUNCTION
        assert "alias odev='odoodev'" in BASH_FUNCTION

    def test_bash_contains_odoodev_activate_function(self):
        assert "odoodev-activate()" in BASH_FUNCTION


class TestZshCompletions:
    """Test Zsh shell completion content."""

    def test_zsh_contains_click_completion(self):
        assert "_ODOODEV_COMPLETE=zsh_source" in ZSH_FUNCTION

    def test_zsh_contains_activate_completion(self):
        assert "_odoodev_activate_completions" in ZSH_FUNCTION
        assert "compdef _odoodev_activate_completions odoodev-activate" in ZSH_FUNCTION

    def test_zsh_contains_versions_plain_call(self):
        assert "odoodev config versions --plain" in ZSH_FUNCTION

    def test_zsh_contains_aliases(self):
        assert "alias oda='odoodev-activate'" in ZSH_FUNCTION
        assert "alias odev='odoodev'" in ZSH_FUNCTION

    def test_zsh_is_different_from_bash(self):
        assert ZSH_FUNCTION != BASH_FUNCTION


class TestGetShellFunction:
    """Test shell function selection."""

    def test_fish_returns_fish_function(self):
        assert get_shell_function("fish") == FISH_FUNCTION

    def test_bash_returns_bash_function(self):
        assert get_shell_function("bash") == BASH_FUNCTION

    def test_zsh_returns_zsh_function(self):
        assert get_shell_function("zsh") == ZSH_FUNCTION


class TestGetShellConfigPath:
    """Test shell config path detection."""

    def test_fish_path(self):
        path = get_shell_config_path("fish")
        assert path.endswith("conf.d/odoodev.fish")

    def test_bash_path(self):
        path = get_shell_config_path("bash")
        assert path.endswith(".bashrc")

    def test_zsh_path(self):
        path = get_shell_config_path("zsh")
        assert path.endswith(".zshrc")


class TestInstallShellFunction:
    """Test shell function installation."""

    def test_fish_creates_file(self, tmp_dir, monkeypatch):
        fish_conf_d = os.path.join(tmp_dir, ".config", "fish", "conf.d")
        expected_path = os.path.join(fish_conf_d, "odoodev.fish")
        monkeypatch.setattr("odoodev.core.shell_integration.get_shell_config_path", lambda shell=None: expected_path)
        result = install_shell_function("fish")
        assert result == expected_path
        assert os.path.exists(expected_path)
        with open(expected_path, encoding="utf-8") as f:
            content = f.read()
        assert "_odoodev_completion" in content
        assert "abbr -a --global oda" in content
        assert "function odoodev-activate" in content

    def test_bash_appends_to_bashrc(self, tmp_dir, monkeypatch):
        bashrc = os.path.join(tmp_dir, ".bashrc")
        with open(bashrc, "w") as f:
            f.write("# existing content\n")
        monkeypatch.setattr("odoodev.core.shell_integration.get_shell_config_path", lambda shell=None: bashrc)
        install_shell_function("bash")
        with open(bashrc, encoding="utf-8") as f:
            content = f.read()
        assert "# existing content" in content
        assert "_ODOODEV_COMPLETE=bash_source" in content
        assert "alias oda='odoodev-activate'" in content


class TestConfigVersionsPlain:
    """Test config versions --plain output."""

    def test_plain_output(self, monkeypatch):
        monkeypatch.setattr(
            "odoodev.commands.config.available_versions",
            lambda: ["16", "17", "18", "19"],
        )
        runner = CliRunner()
        result = runner.invoke(config, ["versions", "--plain"])
        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        assert lines == ["16", "17", "18", "19"]

    def test_plain_output_no_table(self, monkeypatch):
        monkeypatch.setattr(
            "odoodev.commands.config.available_versions",
            lambda: ["18"],
        )
        runner = CliRunner()
        result = runner.invoke(config, ["versions", "--plain"])
        assert result.exit_code == 0
        assert result.output.strip() == "18"
        # Should NOT contain table formatting
        assert "Version" not in result.output
