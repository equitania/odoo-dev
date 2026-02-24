"""Example template management: copy bundled templates for new projects."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from odoodev.core.version_registry import VersionConfig


def get_example_dir(version: str) -> Path:
    """Return path to bundled example templates for a version.

    Args:
        version: Version string (e.g., "18")

    Returns:
        Path to the example directory (e.g., odoodev/data/examples/v18/)
    """
    return Path(__file__).parent.parent / "data" / "examples" / f"v{version}"


def _get_template_mapping(version: str, version_cfg: VersionConfig) -> dict[str, str]:
    """Return mapping of template filenames to their target paths.

    Args:
        version: Version string (e.g., "18")
        version_cfg: VersionConfig for the target version.

    Returns:
        Dict mapping template filename to absolute target path.
    """
    dev_dir = version_cfg.paths.dev_dir
    native_dir = version_cfg.paths.native_dir
    conf_dir = version_cfg.paths.conf_dir

    return {
        "repos.yaml": os.path.join(dev_dir, "scripts", "repos.yaml"),
        "requirements.txt": os.path.join(native_dir, "requirements.txt"),
        f"odoo{version}_template.conf": os.path.join(conf_dir, f"odoo{version}_template.conf"),
    }


def copy_example_templates(version: str, version_cfg: VersionConfig) -> dict[str, str]:
    """Copy missing example templates to the correct locations.

    Only copies if the target file does NOT exist. Creates missing
    subdirectories (scripts/, conf/) as needed.

    Args:
        version: Version string (e.g., "18")
        version_cfg: VersionConfig for the target version.

    Returns:
        Dict of {filename: destination_path} for files that were copied.
        Empty dict if all files already exist or no templates available.
    """
    example_dir = get_example_dir(version)
    if not example_dir.is_dir():
        return {}

    mapping = _get_template_mapping(version, version_cfg)
    copied: dict[str, str] = {}

    for template_name, target_path in mapping.items():
        source = example_dir / template_name
        if not source.is_file():
            continue
        if os.path.exists(target_path):
            continue

        # Create parent directory if missing
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        shutil.copy2(str(source), target_path)
        copied[template_name] = target_path

    return copied
