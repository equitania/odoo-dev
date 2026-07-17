"""Tests for the repos command — clone/update dispatch and failure surfacing.

Regression suite for the "new repos.yaml entry is never cloned" bug class:
- the batch SSH access check must never block a clone attempt,
- clone/update failures must land in RepoOpSummary (previously swallowed),
- --config-only must not perform any git operations.
"""

from __future__ import annotations

from unittest.mock import patch

from odoodev.commands.repos import RepoOpSummary, _print_repo_summary, _process_repos


def _config(**overrides) -> dict:
    config = {
        "addons": [
            {
                "key": "eq_addons",
                "path": "v18-addons",
                "git_url": "git@gitlab.example:v18/v18-addons.git",
                "section": "Equitania",
                "use": True,
            },
        ],
    }
    config.update(overrides)
    return config


class TestProcessReposCloning:
    @patch("odoodev.commands.repos.switch_branch_and_update")
    def test_new_repo_is_cloned_even_when_access_check_failed(self, mock_switch, tmp_path):
        """The access check is diagnostic — a failed probe must not skip the clone."""
        repo_dir = str(tmp_path / "v18-addons")

        def fake_switch(full_path, git_url, branch, base_path, is_oca):
            import os

            os.makedirs(full_path)
            return [full_path], ""

        mock_switch.side_effect = fake_switch
        # Non-empty accessible_paths NOT containing our repo → old code skipped it.
        all_paths, _meta, summary = _process_repos(_config(), str(tmp_path), "develop", {"other-repo"})
        mock_switch.assert_called_once()
        assert summary.cloned == ["eq_addons"]
        assert summary.failed == []
        assert all_paths["eq_addons"] == [repo_dir]

    @patch("odoodev.commands.repos.switch_branch_and_update")
    def test_clone_failure_lands_in_summary(self, mock_switch, tmp_path):
        mock_switch.return_value = ([], "clone git@gitlab.example:v18/v18-addons.git: auth denied")
        all_paths, _meta, summary = _process_repos(_config(), str(tmp_path), "develop", set())
        assert summary.cloned == []
        assert len(summary.failed) == 1
        key, error = summary.failed[0]
        assert key == "eq_addons"
        assert "auth denied" in error
        assert all_paths["eq_addons"] == []  # no phantom addons_path entry

    @patch("odoodev.commands.repos.switch_branch_and_update")
    def test_existing_repo_counts_as_updated(self, mock_switch, tmp_path):
        repo_dir = tmp_path / "v18-addons"
        repo_dir.mkdir()
        mock_switch.return_value = ([str(repo_dir)], "")
        _paths, _meta, summary = _process_repos(_config(), str(tmp_path), "develop", set())
        assert summary.updated == ["eq_addons"]
        assert summary.cloned == []

    @patch("odoodev.commands.repos.switch_branch_and_update")
    def test_use_false_repo_is_skipped_not_attempted(self, mock_switch, tmp_path):
        config = _config()
        config["addons"][0]["use"] = False
        _paths, meta, summary = _process_repos(config, str(tmp_path), "develop", set())
        mock_switch.assert_not_called()
        assert summary.skipped == ["eq_addons"]
        assert meta["eq_addons"]["use"] is False

    @patch("odoodev.commands.repos.switch_branch_and_update")
    def test_skip_git_never_touches_git(self, mock_switch, tmp_path):
        _paths, _meta, summary = _process_repos(_config(), str(tmp_path), "develop", set(), skip_git=True)
        mock_switch.assert_not_called()
        assert summary.cloned == []
        assert summary.failed == []

    @patch("odoodev.commands.repos.switch_branch_and_update")
    def test_suffix_applied_to_cloned_paths(self, mock_switch, tmp_path):
        config = _config()
        config["addons"][0]["suffix"] = "/modules"
        repo_dir = str(tmp_path / "v18-addons")

        def fake_switch(full_path, git_url, branch, base_path, is_oca):
            import os

            os.makedirs(full_path)
            return [full_path], ""

        mock_switch.side_effect = fake_switch
        all_paths, _meta, _summary = _process_repos(config, str(tmp_path), "develop", set())
        assert all_paths["eq_addons"] == [f"{repo_dir}/modules"]


class TestConfigOnlyMode:
    def test_config_only_performs_no_git_operations(self, tmp_path, monkeypatch):
        """--config-only is documented as 'no git operations' — enforce it."""
        from click.testing import CliRunner

        from odoodev.cli import cli

        repos_yaml = tmp_path / "repos.yaml"
        repos_yaml.write_text(
            "branch: develop\n"
            "addons:\n"
            "  - key: eq_addons\n"
            "    path: v18-addons\n"
            "    git_url: git@gitlab.example:v18/v18-addons.git\n"
            "    use: true\n"
        )

        for name in ("switch_branch_and_update", "update_repo", "clone_repo_with_progress"):
            monkeypatch.setattr(
                f"odoodev.commands.repos.{name}",
                lambda *a, _name=name, **k: (_ for _ in ()).throw(AssertionError(f"{_name} called in --config-only")),
            )
        monkeypatch.setattr("odoodev.commands.repos._generate_config", lambda *a, **k: None)

        result = CliRunner().invoke(
            cli,
            ["repos", "18", "-c", str(repos_yaml), "--config-only", "--no-enterprise-prompt"],
        )
        assert result.exit_code == 0, result.output


class TestRepoSummaryOutput:
    def test_summary_table_renders_all_buckets(self, capsys):
        summary = RepoOpSummary(
            cloned=["new_repo"],
            updated=["old_repo"],
            skipped=["disabled_repo"],
            failed=[("broken_repo", "clone: auth denied")],
        )
        _print_repo_summary(summary)
        captured = capsys.readouterr()
        out = captured.out
        assert "new_repo" in out
        assert "old_repo" in out
        assert "disabled_repo" in out
        assert "broken_repo" in out
        # Error details go to stderr via print_error
        assert "auth denied" in captured.err
