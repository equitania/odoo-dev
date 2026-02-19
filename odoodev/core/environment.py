"""Platform detection and environment utilities."""

from __future__ import annotations

import os
import platform
import shutil


def detect_os() -> str:
    """Detect operating system.

    Returns:
        'macos' or 'linux'
    """
    system = platform.system()
    if system == "Darwin":
        return "macos"
    return "linux"


def detect_arch() -> str:
    """Detect CPU architecture.

    Returns:
        'arm64' or 'amd64'
    """
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return "amd64"


def detect_docker_platform() -> str:
    """Detect Docker platform string.

    Returns:
        'linux/arm64' or 'linux/amd64'
    """
    arch = detect_arch()
    return f"linux/{arch}"


def detect_shell() -> str:
    """Detect current shell type.

    Returns:
        'fish', 'zsh', or 'bash'
    """
    shell = os.environ.get("SHELL", "/bin/bash")
    basename = os.path.basename(shell)
    if "fish" in basename:
        return "fish"
    if "zsh" in basename:
        return "zsh"
    return "bash"


def detect_user() -> str:
    """Detect current username."""
    return os.environ.get("USER", os.environ.get("USERNAME", "odoo"))


def is_macos() -> bool:
    """Check if running on macOS."""
    return detect_os() == "macos"


def is_linux() -> bool:
    """Check if running on Linux."""
    return detect_os() == "linux"


def command_exists(cmd: str) -> bool:
    """Check if a command exists in PATH."""
    return shutil.which(cmd) is not None


def find_executable(name: str, extra_paths: list[str] | None = None) -> str | None:
    """Find an executable by name, checking extra paths first.

    Args:
        name: Executable name (e.g., 'wkhtmltopdf')
        extra_paths: Additional paths to check before PATH search

    Returns:
        Full path to executable, or None if not found.
    """
    if extra_paths:
        for path in extra_paths:
            full = os.path.join(path, name)
            if os.path.isfile(full) and os.access(full, os.X_OK):
                return full
    return shutil.which(name)
