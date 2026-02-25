"""Git operations for repository management."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)

_ssh_key_path: str | None = None


def set_ssh_key(key_path: str) -> None:
    """Set SSH key for git operations.

    Args:
        key_path: Path to SSH private key file.
    """
    global _ssh_key_path
    expanded = os.path.expanduser(key_path)
    if os.path.exists(expanded):
        _ssh_key_path = expanded
        logger.info("Using SSH key: %s", expanded)
    else:
        logger.warning("SSH key not found: %s", expanded)


def get_git_env() -> dict[str, str]:
    """Get environment variables for git operations with SSH key and timeout."""
    env = os.environ.copy()
    ssh_opts = "-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new"
    if _ssh_key_path:
        env["GIT_SSH_COMMAND"] = f"ssh -i {_ssh_key_path} -o IdentitiesOnly=yes {ssh_opts}"
    else:
        env["GIT_SSH_COMMAND"] = f"ssh {ssh_opts}"
    return env


def run_git_command(command: str, cwd: str | None = None) -> tuple[bool, str]:
    """Execute a git command.

    Args:
        command: Shell command to execute
        cwd: Working directory

    Returns:
        Tuple of (success, output_or_error).
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            check=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=get_git_env(),
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr if e.stderr else str(e)
        logger.error("Error executing '%s': %s", command, error_msg)
        return False, error_msg


def check_repo_access(git_url: str, timeout: int = 30) -> bool:
    """Check if a git repository is accessible via SSH.

    Args:
        git_url: Git repository URL
        timeout: Timeout in seconds

    Returns:
        True if repository is accessible.
    """
    try:
        subprocess.run(
            f"git ls-remote {git_url} HEAD",
            shell=True,
            check=True,
            capture_output=True,
            timeout=timeout,
            env=get_git_env(),
        )
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def verify_all_repo_access(repos: list[dict]) -> tuple[list[dict], list[dict]]:
    """Verify access to all repositories.

    Args:
        repos: List of repo dicts with at least 'git_url' and 'key' keys.

    Returns:
        Tuple of (accessible_repos, inaccessible_repos).
    """
    accessible = []
    inaccessible = []

    for repo in repos:
        git_url = repo.get("git_url", "")
        key = repo.get("key", repo.get("path", "unknown"))
        if check_repo_access(git_url):
            logger.info("  ✓ %s", key)
            accessible.append(repo)
        else:
            logger.info("  ✗ %s — NO ACCESS", key)
            inaccessible.append(repo)

    logger.info("%d accessible, %d inaccessible", len(accessible), len(inaccessible))
    return accessible, inaccessible


def clone_repo_with_progress(git_url: str, target_dir: str, branch: str) -> bool:
    """Clone a git repository with visible progress output.

    Unlike clone_repo(), this does NOT capture output so that git's
    progress indicators are visible to the user. Use for large repos
    (e.g., Odoo server).

    Args:
        git_url: Repository URL
        target_dir: Target directory
        branch: Branch to checkout

    Returns:
        True if successful.
    """
    parent_dir = os.path.dirname(target_dir)
    repo_name = os.path.basename(target_dir)
    os.makedirs(parent_dir, exist_ok=True)
    try:
        subprocess.run(
            f"git clone --progress -b {branch} {git_url} {repo_name}",
            shell=True,
            check=True,
            cwd=parent_dir,
            env=get_git_env(),
        )
        return True
    except subprocess.CalledProcessError as e:
        logger.error("Clone failed: %s", e)
        return False


def clone_repo(git_url: str, target_dir: str, branch: str) -> bool:
    """Clone a git repository.

    Args:
        git_url: Repository URL
        target_dir: Target directory
        branch: Branch to checkout

    Returns:
        True if successful.
    """
    parent_dir = os.path.dirname(target_dir)
    repo_name = os.path.basename(target_dir)
    success, _ = run_git_command(f"git clone -b {branch} {git_url} {repo_name}", cwd=parent_dir)
    return success


def clone_repo_fresh(git_url: str, target_dir: str, branch: str) -> bool:
    """Clone a repo from scratch, removing existing directory first.

    Args:
        git_url: Repository URL
        target_dir: Target directory (will be removed if exists)
        branch: Branch to checkout

    Returns:
        True if successful.
    """
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir)
    return clone_repo_with_progress(git_url, target_dir, branch)


def update_repo(repo_dir: str, branch: str) -> bool:
    """Update an existing repository (checkout + pull).

    Args:
        repo_dir: Path to local repository
        branch: Branch to checkout

    Returns:
        True if successful.
    """
    success, _ = run_git_command(f"git checkout {branch}", cwd=repo_dir)
    if not success:
        return False
    success, _ = run_git_command("git pull", cwd=repo_dir)
    if not success:
        return False

    # Clean Python cache
    run_git_command("find . -name '*.pyc' -type f -delete", cwd=repo_dir)
    run_git_command("find . -type d -empty -delete", cwd=repo_dir)

    return True


def get_module_paths(repo_dir: str, is_oca: bool = False) -> list[str]:
    """Get module paths from a repository.

    For OCA repos, returns sorted list of subdirectories.
    For regular repos, returns the repo directory itself.

    Args:
        repo_dir: Path to repository
        is_oca: Whether this is an OCA repository (with sub-modules)

    Returns:
        List of module paths.
    """
    if is_oca:
        subdirs = []
        if os.path.isdir(repo_dir):
            for entry in sorted(os.listdir(repo_dir)):
                entry_path = os.path.join(repo_dir, entry)
                if os.path.isdir(entry_path) and not entry.startswith("."):
                    subdirs.append(entry_path)
        return subdirs
    return [repo_dir]


def switch_branch_and_update(
    repo_dir: str, git_url: str, branch: str, base_dir: str, is_oca: bool = False
) -> list[str]:
    """Switch branch and update a repo, or clone if not exists.

    Args:
        repo_dir: Full path to local repository
        git_url: Remote repository URL
        branch: Branch to checkout
        base_dir: Parent directory for cloning
        is_oca: Whether this is an OCA repository

    Returns:
        List of module paths.
    """
    if os.path.isdir(repo_dir):
        update_repo(repo_dir, branch)
    else:
        clone_repo(git_url, repo_dir, branch)

    return get_module_paths(repo_dir, is_oca)
