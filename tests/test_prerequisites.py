"""Tests for prerequisite checks (Node.js, Node packages, system libraries)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from odoodev.core.prerequisites import (
    LINUX_LIBS,
    MACOS_LIBS,
    check_node,
    check_node_packages,
    check_system_libs,
    run_all_checks,
)

# ---------------------------------------------------------------------------
# check_node
# ---------------------------------------------------------------------------


class TestCheckNode:
    """Tests for check_node()."""

    @patch("odoodev.core.prerequisites.command_exists", return_value=True)
    @patch("odoodev.core.prerequisites.find_executable", return_value="/usr/local/bin/node")
    @patch("odoodev.core.prerequisites.detect_os", return_value="macos")
    @patch("subprocess.run")
    def test_node_found_valid_version(self, mock_run, _os, _find, _cmd):
        mock_run.return_value = MagicMock(returncode=0, stdout="v20.11.1\n")
        result = check_node()
        assert result == "/usr/local/bin/node"

    @patch("odoodev.core.prerequisites.command_exists", return_value=True)
    @patch("odoodev.core.prerequisites.find_executable", return_value="/usr/bin/node")
    @patch("odoodev.core.prerequisites.detect_os", return_value="linux")
    @patch("subprocess.run")
    def test_node_found_old_version_warns(self, mock_run, _os, _find, _cmd):
        mock_run.return_value = MagicMock(returncode=0, stdout="v18.19.0\n")
        result = check_node()
        assert result == "/usr/bin/node"

    @patch("odoodev.core.prerequisites.find_executable", return_value=None)
    @patch("odoodev.core.prerequisites.detect_os", return_value="macos")
    def test_node_not_found_macos(self, _os, _find):
        result = check_node()
        assert result is None

    @patch("odoodev.core.prerequisites.find_executable", return_value=None)
    @patch("odoodev.core.prerequisites.detect_os", return_value="linux")
    def test_node_not_found_linux(self, _os, _find):
        result = check_node()
        assert result is None

    @patch("odoodev.core.prerequisites.command_exists")
    @patch("odoodev.core.prerequisites.find_executable", return_value="/usr/local/bin/node")
    @patch("odoodev.core.prerequisites.detect_os", return_value="macos")
    @patch("subprocess.run")
    def test_npm_missing_warns(self, mock_run, _os, _find, mock_cmd):
        mock_run.return_value = MagicMock(returncode=0, stdout="v20.0.0\n")
        mock_cmd.return_value = False  # npm not found
        result = check_node()
        assert result == "/usr/local/bin/node"

    @patch("odoodev.core.prerequisites.command_exists", return_value=True)
    @patch("odoodev.core.prerequisites.find_executable", return_value="/usr/bin/node")
    @patch("odoodev.core.prerequisites.detect_os", return_value="linux")
    @patch("subprocess.run")
    def test_node_unparseable_version(self, mock_run, _os, _find, _cmd):
        mock_run.return_value = MagicMock(returncode=0, stdout="unknown\n")
        result = check_node()
        assert result == "/usr/bin/node"


# ---------------------------------------------------------------------------
# check_node_packages
# ---------------------------------------------------------------------------


class TestCheckNodePackages:
    """Tests for check_node_packages()."""

    @patch("odoodev.core.prerequisites.command_exists")
    @patch("subprocess.run")
    def test_all_packages_present(self, mock_run, mock_cmd):
        mock_cmd.side_effect = lambda c: c in ("npm", "rtlcss", "lessc")
        mock_run.return_value = MagicMock(returncode=0, stdout="/usr/lib\n├── less-plugin-clean-css@1.5.1\n")
        result = check_node_packages()
        assert result == []

    @patch("odoodev.core.prerequisites.command_exists")
    @patch("subprocess.run")
    def test_rtlcss_and_lessc_missing(self, mock_run, mock_cmd):
        mock_cmd.side_effect = lambda c: c == "npm"
        mock_run.return_value = MagicMock(returncode=0, stdout="/usr/lib\n(empty)\n")
        result = check_node_packages()
        assert "rtlcss" in result
        assert "less" in result
        assert "less-plugin-clean-css" in result

    @patch("odoodev.core.prerequisites.command_exists", return_value=False)
    def test_npm_not_available(self, _cmd):
        result = check_node_packages()
        assert len(result) == 3
        assert "rtlcss" in result
        assert "less" in result
        assert "less-plugin-clean-css" in result

    @patch("odoodev.core.prerequisites.command_exists")
    @patch("subprocess.run")
    def test_only_plugin_missing(self, mock_run, mock_cmd):
        mock_cmd.side_effect = lambda c: c in ("npm", "rtlcss", "lessc")
        mock_run.return_value = MagicMock(returncode=0, stdout="/usr/lib\n(empty)\n")
        result = check_node_packages()
        assert result == ["less-plugin-clean-css"]


# ---------------------------------------------------------------------------
# check_system_libs
# ---------------------------------------------------------------------------


class TestCheckSystemLibs:
    """Tests for check_system_libs()."""

    @patch("odoodev.core.prerequisites.detect_os", return_value="macos")
    @patch("odoodev.core.prerequisites.command_exists", return_value=True)
    @patch("subprocess.run")
    def test_macos_all_present(self, mock_run, _cmd, _os):
        mock_run.return_value = MagicMock(returncode=0, stdout="/opt/homebrew/opt/pkg\n")
        result = check_system_libs()
        assert result == []

    @patch("odoodev.core.prerequisites.detect_os", return_value="macos")
    @patch("odoodev.core.prerequisites.command_exists", return_value=True)
    @patch("subprocess.run")
    def test_macos_some_missing(self, mock_run, _cmd, _os):
        def side_effect(args, **kwargs):
            formula = args[2]  # brew --prefix <formula>
            if formula in ("openldap", "libxml2"):
                return MagicMock(returncode=1, stdout="", stderr="Error")
            return MagicMock(returncode=0, stdout="/opt/homebrew/opt/pkg\n")

        mock_run.side_effect = side_effect
        result = check_system_libs()
        assert len(result) == 2
        assert MACOS_LIBS["openldap"] in result
        assert MACOS_LIBS["libxml2"] in result

    @patch("odoodev.core.prerequisites.detect_os", return_value="macos")
    @patch("odoodev.core.prerequisites.command_exists", return_value=False)
    def test_macos_no_brew(self, _cmd, _os):
        result = check_system_libs()
        assert result == []

    @patch("odoodev.core.prerequisites.detect_os", return_value="linux")
    @patch("odoodev.core.prerequisites.command_exists", return_value=True)
    @patch("subprocess.run")
    def test_linux_all_present(self, mock_run, _cmd, _os):
        mock_run.return_value = MagicMock(returncode=0, stdout="ii  libldap2-dev  2.5.16\n")
        result = check_system_libs()
        assert result == []

    @patch("odoodev.core.prerequisites.detect_os", return_value="linux")
    @patch("odoodev.core.prerequisites.command_exists", return_value=True)
    @patch("subprocess.run")
    def test_linux_some_missing(self, mock_run, _cmd, _os):
        def side_effect(args, **kwargs):
            pkg = args[2]  # dpkg -l <pkg>
            if pkg == "libsasl2-dev":
                return MagicMock(returncode=1, stdout="")
            return MagicMock(returncode=0, stdout=f"ii  {pkg}  1.0\n")

        mock_run.side_effect = side_effect
        result = check_system_libs()
        assert len(result) == 1
        assert LINUX_LIBS["libsasl2-dev"] in result

    @patch("odoodev.core.prerequisites.detect_os", return_value="linux")
    @patch("odoodev.core.prerequisites.command_exists", return_value=False)
    def test_linux_no_dpkg(self, _cmd, _os):
        result = check_system_libs()
        assert result == []


# ---------------------------------------------------------------------------
# run_all_checks includes new keys
# ---------------------------------------------------------------------------


class TestRunAllChecks:
    """Test that run_all_checks returns new keys."""

    @patch("odoodev.core.prerequisites.check_system_libs", return_value=[])
    @patch("odoodev.core.prerequisites.check_node_packages", return_value=[])
    @patch("odoodev.core.prerequisites.check_node", return_value="/usr/bin/node")
    @patch("odoodev.core.prerequisites.check_postgres_port", return_value=True)
    @patch("odoodev.core.prerequisites.check_pg_tools", return_value="/usr/bin/pg_dump")
    @patch("odoodev.core.prerequisites.check_wkhtmltopdf", return_value="/usr/bin/wkhtmltopdf")
    @patch("odoodev.core.prerequisites.check_docker_compose", return_value=True)
    @patch("odoodev.core.prerequisites.check_docker", return_value=True)
    @patch("odoodev.core.prerequisites.check_uv", return_value=True)
    def test_results_contain_new_keys(self, *_mocks):
        results = run_all_checks(db_port=5432)
        assert "node" in results
        assert "node_packages" in results
        assert "system_libs" in results
        assert results["node"] is True
        assert results["node_packages"] is True
        assert results["system_libs"] is True
