"""Virtual environment management with UV."""

from __future__ import annotations

import hashlib
import os
import subprocess


def create_venv(venv_dir: str, python_version: str, prompt: str) -> bool:
    """Create a UV virtual environment.

    Args:
        venv_dir: Path where venv should be created
        python_version: Python version (e.g., '3.12')
        prompt: Shell prompt name for the venv

    Returns:
        True if successful.
    """
    result = subprocess.run(
        ["uv", "venv", "--python", python_version, "--prompt", prompt, venv_dir],
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
