"""Tests for git operations (clone, update, divergent branch handling)."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch

from odoodev.core.git_ops import update_repo


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
