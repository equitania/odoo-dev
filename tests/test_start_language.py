"""Tests for i18n/language loading parameters in odoodev start."""

from __future__ import annotations

import sys

import pytest
from click.testing import CliRunner


class TestLanguageArgs:
    """Test that --load-language and --i18n-overwrite flags are correctly added to the Odoo command."""

    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_start_help_shows_language_options(self, runner):
        """CLI --help shows --load-language and --i18n-overwrite options."""
        from odoodev.cli import cli

        result = runner.invoke(cli, ["start", "--help"])
        assert "--load-language" in result.output
        assert "--i18n-overwrite" in result.output

    def test_load_language_help_text(self, runner):
        """--load-language help describes supported values."""
        from odoodev.cli import cli

        result = runner.invoke(cli, ["start", "--help"])
        assert "de_DE" in result.output or "language" in result.output.lower()


class TestStartOdooCommandBuilding:
    """Test _start_odoo command construction directly (avoiding circular import)."""

    def test_load_language_added(self, monkeypatch):
        """--load-language adds the flag before extra_args."""
        import subprocess

        captured = []

        def mock_run(cmd, **kwargs):
            captured.extend(cmd)

            class R:
                returncode = 0

            return R()

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr("os.chdir", lambda x: None)

        # Import after monkeypatching to avoid circular import at module level
        # Create minimal fake venv
        import tempfile

        from odoodev.commands.start import _start_odoo

        with tempfile.TemporaryDirectory() as td:
            import os

            venv = os.path.join(td, ".venv")
            os.makedirs(os.path.join(venv, "bin"))
            python_path = os.path.join(venv, "bin", "python3")
            os.symlink(sys.executable, python_path)

            odoo_dir = os.path.join(td, "server")
            os.makedirs(odoo_dir)
            with open(os.path.join(odoo_dir, "odoo-bin"), "w") as f:
                f.write("")

            config_path = os.path.join(td, "odoo.conf")
            with open(config_path, "w") as f:
                f.write("[options]\n")

            with pytest.raises(SystemExit):
                _start_odoo(
                    odoo_dir,
                    config_path,
                    "normal",
                    ("-d", "v18_exam"),
                    {},
                    venv,
                    version="18",
                    load_language="de_DE",
                )

        assert any("--load-language=de_DE" in arg for arg in captured)
        # Language flag should be before extra args
        lang_idx = next(i for i, a in enumerate(captured) if "--load-language" in a)
        db_idx = next(i for i, a in enumerate(captured) if a == "-d")
        assert lang_idx < db_idx

    def test_i18n_overwrite_added(self, monkeypatch):
        """--i18n-overwrite adds the flag."""
        import subprocess

        captured = []

        def mock_run(cmd, **kwargs):
            captured.extend(cmd)

            class R:
                returncode = 0

            return R()

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr("os.chdir", lambda x: None)

        import os
        import tempfile

        from odoodev.commands.start import _start_odoo

        with tempfile.TemporaryDirectory() as td:
            venv = os.path.join(td, ".venv")
            os.makedirs(os.path.join(venv, "bin"))
            os.symlink(sys.executable, os.path.join(venv, "bin", "python3"))

            odoo_dir = os.path.join(td, "server")
            os.makedirs(odoo_dir)
            with open(os.path.join(odoo_dir, "odoo-bin"), "w") as f:
                f.write("")

            config_path = os.path.join(td, "odoo.conf")
            with open(config_path, "w") as f:
                f.write("[options]\n")

            with pytest.raises(SystemExit):
                _start_odoo(
                    odoo_dir,
                    config_path,
                    "normal",
                    (),
                    {},
                    venv,
                    version="18",
                    i18n_overwrite=True,
                )

        assert "--i18n-overwrite" in captured
        # Odoo requires -u when --i18n-overwrite is used — auto-added
        assert "-u" in captured
        assert "all" in captured

    def test_both_flags_combined(self, monkeypatch):
        """Both flags work together."""
        import subprocess

        captured = []

        def mock_run(cmd, **kwargs):
            captured.extend(cmd)

            class R:
                returncode = 0

            return R()

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr("os.chdir", lambda x: None)

        import os
        import tempfile

        from odoodev.commands.start import _start_odoo

        with tempfile.TemporaryDirectory() as td:
            venv = os.path.join(td, ".venv")
            os.makedirs(os.path.join(venv, "bin"))
            os.symlink(sys.executable, os.path.join(venv, "bin", "python3"))

            odoo_dir = os.path.join(td, "server")
            os.makedirs(odoo_dir)
            with open(os.path.join(odoo_dir, "odoo-bin"), "w") as f:
                f.write("")

            config_path = os.path.join(td, "odoo.conf")
            with open(config_path, "w") as f:
                f.write("[options]\n")

            with pytest.raises(SystemExit):
                _start_odoo(
                    odoo_dir,
                    config_path,
                    "normal",
                    (),
                    {},
                    venv,
                    version="18",
                    load_language="all",
                    i18n_overwrite=True,
                )

        assert any("--load-language=all" in arg for arg in captured)
        assert "--i18n-overwrite" in captured
        assert "-u" in captured
        assert "all" in captured

    def test_no_flags_by_default(self, monkeypatch):
        """Without language options, no language flags appear."""
        import subprocess

        captured = []

        def mock_run(cmd, **kwargs):
            captured.extend(cmd)

            class R:
                returncode = 0

            return R()

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr("os.chdir", lambda x: None)

        import os
        import tempfile

        from odoodev.commands.start import _start_odoo

        with tempfile.TemporaryDirectory() as td:
            venv = os.path.join(td, ".venv")
            os.makedirs(os.path.join(venv, "bin"))
            os.symlink(sys.executable, os.path.join(venv, "bin", "python3"))

            odoo_dir = os.path.join(td, "server")
            os.makedirs(odoo_dir)
            with open(os.path.join(odoo_dir, "odoo-bin"), "w") as f:
                f.write("")

            config_path = os.path.join(td, "odoo.conf")
            with open(config_path, "w") as f:
                f.write("[options]\n")

            with pytest.raises(SystemExit):
                _start_odoo(
                    odoo_dir,
                    config_path,
                    "normal",
                    (),
                    {},
                    venv,
                    version="18",
                )

        assert not any("--load-language" in arg for arg in captured)
        assert "--i18n-overwrite" not in captured

    def test_i18n_overwrite_skips_auto_update_when_user_provides_u(self, monkeypatch):
        """When user already passes -u in extra_args, don't add -u all."""
        import subprocess

        captured = []

        def mock_run(cmd, **kwargs):
            captured.extend(cmd)

            class R:
                returncode = 0

            return R()

        monkeypatch.setattr(subprocess, "run", mock_run)
        monkeypatch.setattr("os.chdir", lambda x: None)

        import os
        import tempfile

        from odoodev.commands.start import _start_odoo

        with tempfile.TemporaryDirectory() as td:
            venv = os.path.join(td, ".venv")
            os.makedirs(os.path.join(venv, "bin"))
            os.symlink(sys.executable, os.path.join(venv, "bin", "python3"))

            odoo_dir = os.path.join(td, "server")
            os.makedirs(odoo_dir)
            with open(os.path.join(odoo_dir, "odoo-bin"), "w") as f:
                f.write("")

            config_path = os.path.join(td, "odoo.conf")
            with open(config_path, "w") as f:
                f.write("[options]\n")

            with pytest.raises(SystemExit):
                _start_odoo(
                    odoo_dir,
                    config_path,
                    "normal",
                    ("-u", "eq_sale"),
                    {},
                    venv,
                    version="18",
                    i18n_overwrite=True,
                )

        assert "--i18n-overwrite" in captured
        # User provided -u eq_sale, so -u all should NOT be auto-added
        assert "eq_sale" in captured
        assert captured.count("-u") == 1  # Only user's -u, not auto-added
