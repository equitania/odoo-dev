"""Tests for git operations (clone, update, divergent branch handling)."""

from __future__ import annotations

import os
import subprocess
from unittest.mock import MagicMock, patch

from odoodev.core.git_ops import clone_repo, get_module_paths, switch_branch_and_update, update_repo


class TestUpdateRepoFastForward:
    """Tests for update_repo() with --ff-only pull strategy."""

    @patch("odoodev.core.git_ops.subprocess.run")
    def test_pull_uses_ff_only_flag(self, mock_run):
        """update_repo must invoke 'git pull --ff-only', not bare 'git pull'."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        success, error = update_repo("/fake/repo", "develop")
        assert success is True
        assert error == ""
        pull_calls = [c for c in mock_run.call_args_list if c.args[0][:2] == ["git", "pull"]]
        assert len(pull_calls) == 1
        assert "--ff-only" in pull_calls[0].args[0]

    @patch("odoodev.core.git_ops.subprocess.run")
    def test_divergent_branch_returns_actionable_hint(self, mock_run):
        """A non-fast-forward failure must yield a clear, actionable error message."""

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            if cmd[:2] == ["git", "pull"]:
                raise subprocess.CalledProcessError(
                    returncode=128,
                    cmd=cmd,
                    stderr="fatal: Not possible to fast-forward, aborting.\n",
                )
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        success, error = update_repo("/fake/repo", "develop")
        assert success is False
        assert "diverged" in error
        assert "--rebase" in error
        assert "--no-rebase" in error
        assert "/fake/repo" in error

    @patch("odoodev.core.git_ops.subprocess.run")
    def test_legacy_non_fast_forward_message_also_handled(self, mock_run):
        """Older git versions may emit 'non-fast-forward' phrasing — handle both."""

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            if cmd[:2] == ["git", "pull"]:
                raise subprocess.CalledProcessError(
                    returncode=1,
                    cmd=cmd,
                    stderr="error: non-fast-forward update rejected\n",
                )
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        success, error = update_repo("/fake/repo", "develop")
        assert success is False
        assert "diverged" in error

    @patch("odoodev.core.git_ops.subprocess.run")
    def test_unrelated_pull_failure_passes_through(self, mock_run):
        """Non-divergence pull errors (e.g. network) must NOT mention rebase."""

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                return MagicMock(returncode=0, stdout="", stderr="")
            if cmd[:2] == ["git", "pull"]:
                raise subprocess.CalledProcessError(
                    returncode=1,
                    cmd=cmd,
                    stderr="fatal: unable to access 'git@example.com': Connection refused\n",
                )
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        success, error = update_repo("/fake/repo", "develop")
        assert success is False
        assert "diverged" not in error
        assert "Connection refused" in error

    @patch("odoodev.core.git_ops.subprocess.run")
    def test_checkout_failure_short_circuits(self, mock_run):
        """If checkout fails, pull must not be attempted."""

        def side_effect(cmd, **kwargs):
            if cmd[:2] == ["git", "checkout"]:
                raise subprocess.CalledProcessError(
                    returncode=1,
                    cmd=cmd,
                    stderr="error: pathspec 'develop' did not match\n",
                )
            return MagicMock(returncode=0, stdout="", stderr="")

        mock_run.side_effect = side_effect
        success, error = update_repo("/fake/repo", "develop")
        assert success is False
        assert "checkout develop" in error
        pull_calls = [c for c in mock_run.call_args_list if c.args[0][:2] == ["git", "pull"]]
        assert pull_calls == []


class TestCloneRepo:
    """clone_repo must create missing parents and surface errors as (bool, str)."""

    @patch("odoodev.core.git_ops.subprocess.run")
    def test_creates_missing_parent_directory(self, mock_run, tmp_path):
        """A new repo in a not-yet-existing subdirectory must not crash on cwd."""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        target = tmp_path / "new-parent" / "my-repo"
        success, error = clone_repo("git@example.com:x/y.git", str(target), "develop")
        assert success is True
        assert error == ""
        assert (tmp_path / "new-parent").is_dir()

    @patch("odoodev.core.git_ops.subprocess.run")
    def test_clone_failure_returns_error_message(self, mock_run, tmp_path):
        mock_run.side_effect = subprocess.CalledProcessError(
            returncode=128,
            cmd=["git", "clone"],
            stderr="fatal: Could not read from remote repository.\n",
        )
        success, error = clone_repo("git@example.com:x/y.git", str(tmp_path / "repo"), "develop")
        assert success is False
        assert "Could not read from remote repository" in error
        assert "git@example.com:x/y.git" in error


class TestGetModulePaths:
    """A failed clone must not produce phantom addons_path entries."""

    def test_non_oca_existing_dir(self, tmp_path):
        assert get_module_paths(str(tmp_path)) == [str(tmp_path)]

    def test_non_oca_missing_dir_returns_empty(self, tmp_path):
        missing = str(tmp_path / "never-cloned")
        assert get_module_paths(missing) == []

    def test_oca_missing_dir_returns_empty(self, tmp_path):
        missing = str(tmp_path / "never-cloned")
        assert get_module_paths(missing, is_oca=True) == []

    def test_oca_lists_subdirs(self, tmp_path):
        (tmp_path / "mod_b").mkdir()
        (tmp_path / "mod_a").mkdir()
        (tmp_path / ".git").mkdir()
        paths = get_module_paths(str(tmp_path), is_oca=True)
        assert paths == [str(tmp_path / "mod_a"), str(tmp_path / "mod_b")]


class TestSwitchBranchAndUpdate:
    """switch_branch_and_update must propagate clone/update errors."""

    @patch("odoodev.core.git_ops.clone_repo")
    def test_clone_error_is_returned(self, mock_clone, tmp_path):
        mock_clone.return_value = (False, "clone failed: auth error")
        repo_dir = str(tmp_path / "not-there")
        paths, error = switch_branch_and_update(repo_dir, "git@x:y.git", "develop", str(tmp_path))
        assert error == "clone failed: auth error"
        assert paths == []  # nothing on disk → no phantom path

    @patch("odoodev.core.git_ops.update_repo")
    def test_update_error_is_returned(self, mock_update, tmp_path):
        mock_update.return_value = (False, "pull: network down")
        paths, error = switch_branch_and_update(str(tmp_path), "git@x:y.git", "develop", str(tmp_path))
        assert error == "pull: network down"
        assert paths == [str(tmp_path)]  # existing dir keeps its path

    @patch("odoodev.core.git_ops.clone_repo")
    def test_successful_clone_returns_paths_and_no_error(self, mock_clone, tmp_path):
        repo_dir = str(tmp_path / "fresh")

        def fake_clone(git_url, target_dir, branch):
            os.makedirs(target_dir)
            return True, ""

        mock_clone.side_effect = fake_clone
        paths, error = switch_branch_and_update(repo_dir, "git@x:y.git", "develop", str(tmp_path))
        assert error == ""
        assert paths == [repo_dir]
