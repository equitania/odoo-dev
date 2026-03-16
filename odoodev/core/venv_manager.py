"""Virtual environment management with UV."""

from __future__ import annotations

import hashlib
import os
import subprocess


def create_venv(venv_dir: str, python_version: str, prompt: str) -> bool:
    """Create a UV virtual environment.

    Args:
        venv_dir: Path where venv should be created
        python_version: Python version (e.g., '3.12' or '3.13.12')
        prompt: Shell prompt name for the venv

    Returns:
        True if successful.
    """
    cmd = ["uv", "venv", "--python", python_version, "--prompt", prompt]
    if os.path.exists(venv_dir):
        cmd.append("--clear")
    cmd.append(venv_dir)
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def install_requirements(venv_dir: str, requirements_path: str) -> bool:
    """Install requirements.txt into venv using UV.

    Args:
        venv_dir: Path to virtual environment
        requirements_path: Path to requirements.txt

    Returns:
        True if successful.
    """
    env = {**os.environ, "VIRTUAL_ENV": venv_dir}
    result = subprocess.run(
        ["uv", "pip", "install", "-r", requirements_path],
        env=env,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def hash_requirements(requirements_path: str) -> str:
    """Calculate SHA256 hash of requirements file."""
    sha256 = hashlib.sha256()
    with open(requirements_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def store_requirements_hash(venv_dir: str, requirements_path: str) -> None:
    """Store requirements.txt hash in venv directory."""
    hash_value = hash_requirements(requirements_path)
    hash_file = os.path.join(venv_dir, ".requirements.sha256")
    with open(hash_file, "w") as f:
        f.write(hash_value)


def check_requirements_changed(venv_dir: str, requirements_path: str) -> bool:
    """Check if requirements.txt has changed since last install.

    Returns:
        True if requirements have changed (or hash file missing).
    """
    hash_file = os.path.join(venv_dir, ".requirements.sha256")
    if not os.path.exists(hash_file):
        return True

    with open(hash_file) as f:
        stored_hash = f.read().strip()

    current_hash = hash_requirements(requirements_path)
    return current_hash != stored_hash


def get_venv_python_version(venv_dir: str) -> str | None:
    """Get the Python major.minor version from an existing venv.

    Returns e.g. "3.13" or None if not determinable.
    """
    python_bin = os.path.join(venv_dir, "bin", "python3")
    if not os.path.exists(python_bin):
        return None
    try:
        result = subprocess.run(
            [python_bin, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def check_venv_python_matches(venv_dir: str, expected_version: str) -> bool:
    """Check if venv Python version matches the expected version.

    Returns True if matching, False if mismatch or not determinable.
    """
    actual = get_venv_python_version(venv_dir)
    if actual is None:
        return False
    return actual == expected_version


def get_full_python_version(venv_dir: str) -> str | None:
    """Get the full Python version (major.minor.patch) from a venv."""
    python_bin = os.path.join(venv_dir, "bin", "python3")
    if not os.path.exists(python_bin):
        return None
    try:
        result = subprocess.run(
            [
                python_bin,
                "-c",
                "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        pass
    return None


def get_system_python_version(major_minor: str) -> str | None:
    """Get the newest installed Python version for a major.minor via UV.

    Args:
        major_minor: e.g. "3.13"

    Returns:
        Full version string (e.g. "3.13.12") or None.
    """
    try:
        result = subprocess.run(
            ["uv", "python", "list", "--only-installed"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        # Parse lines like: "cpython-3.13.12-macos-aarch64-none    /path/to/python"
        best: str | None = None
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line.startswith("cpython-"):
                continue
            parts = line.split()
            if not parts:
                continue
            version_part = parts[0].split("-")[1]  # "3.13.12"
            if version_part.startswith(major_minor + "."):
                if best is None or _version_tuple(version_part) > _version_tuple(best):
                    best = version_part
        return best
    except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
        return None


def _version_tuple(version: str) -> tuple[int, ...]:
    """Convert version string to comparable tuple."""
    return tuple(int(x) for x in version.split("."))


def ensure_setuptools(venv_dir: str) -> bool:
    """Ensure setuptools is installed in the venv.

    Odoo 16/17 require pkg_resources (from setuptools) which is no
    longer bundled with Python 3.12+. This installs it if missing.

    Returns:
        True if setuptools is available (already present or installed).
    """
    python = os.path.join(venv_dir, "bin", "python3")
    result = subprocess.run(
        [python, "-c", "import pkg_resources"],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True

    # Install setuptools<82 — version 82+ removed pkg_resources entirely.
    # Use --reinstall because UV may have 82.x cached/registered.
    env = {**os.environ, "VIRTUAL_ENV": venv_dir}
    result = subprocess.run(
        ["uv", "pip", "install", "--reinstall", "setuptools<82"],
        env=env,
    )
    if result.returncode != 0:
        return False

    # Verify installation actually worked
    result = subprocess.run(
        [python, "-c", "import pkg_resources"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def get_venv_python(venv_dir: str) -> str:
    """Get path to Python binary in venv."""
    return os.path.join(venv_dir, "bin", "python3")


def get_activate_command(venv_dir: str, shell: str) -> str:
    """Get the shell-specific activation command.

    Args:
        venv_dir: Path to virtual environment
        shell: Shell type ('fish', 'zsh', 'bash')

    Returns:
        Activation command string.
    """
    if shell == "fish":
        return f"source {venv_dir}/bin/activate.fish"
    return f"source {venv_dir}/bin/activate"
