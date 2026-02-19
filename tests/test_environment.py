"""Tests for environment detection module."""


from odoodev.core.environment import (
    command_exists,
    detect_arch,
    detect_docker_platform,
    detect_os,
    detect_shell,
    detect_user,
    find_executable,
    is_linux,
    is_macos,
)


class TestDetectOS:
    def test_returns_valid_os(self):
        result = detect_os()
        assert result in ("macos", "linux")

    def test_macos_or_linux(self):
        # Exactly one must be true
        assert is_macos() != is_linux()


class TestDetectArch:
    def test_returns_valid_arch(self):
        result = detect_arch()
        assert result in ("arm64", "amd64")


class TestDetectDockerPlatform:
    def test_returns_valid_platform(self):
        result = detect_docker_platform()
        assert result.startswith("linux/")
        assert result in ("linux/arm64", "linux/amd64")


class TestDetectShell:
    def test_returns_valid_shell(self):
        result = detect_shell()
        assert result in ("fish", "zsh", "bash")

    def test_detects_fish(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/opt/homebrew/bin/fish")
        assert detect_shell() == "fish"

    def test_detects_zsh(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/bin/zsh")
        assert detect_shell() == "zsh"

    def test_detects_bash(self, monkeypatch):
        monkeypatch.setenv("SHELL", "/bin/bash")
        assert detect_shell() == "bash"


class TestDetectUser:
    def test_returns_string(self):
        result = detect_user()
        assert isinstance(result, str)
        assert len(result) > 0


class TestCommandExists:
    def test_python_exists(self):
        assert command_exists("python3") is True

    def test_nonexistent_command(self):
        assert command_exists("nonexistent_command_xyz_123") is False


class TestFindExecutable:
    def test_find_in_path(self):
        result = find_executable("python3")
        assert result is not None

    def test_find_nonexistent(self):
        result = find_executable("nonexistent_xyz_123")
        assert result is None
