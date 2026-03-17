"""odoodev start - Start Odoo server in various modes."""

from __future__ import annotations

import glob
import os
import subprocess
import sys

import click

from odoodev.cli import resolve_version
from odoodev.core.environment import detect_shell
from odoodev.core.prerequisites import check_port
from odoodev.core.venv_manager import (
    check_requirements_changed,
    check_venv_python_matches,
    get_venv_python,
    get_venv_python_version,
)
from odoodev.core.version_registry import get_version, load_versions
from odoodev.output import confirm, print_error, print_header, print_info, print_success, print_table, print_warning


def _find_odoo_config(myconfs_dir: str) -> str | None:
    """Find the latest Odoo config file in myconfs directory.

    Looks for files matching odoo_*.conf, sorted lexicographically (latest date last).
    """
    pattern = os.path.join(myconfs_dir, "odoo_*.conf")
    configs = sorted(glob.glob(pattern))
    if configs:
        return configs[-1]
    return None


def _get_config_value(config_path: str, key: str) -> str | None:
    """Extract a value from an Odoo config file."""
    try:
        with open(config_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith(key) and "=" in line:
                    _, _, value = line.partition("=")
                    value = value.strip()
                    value = value.replace("$HOME", os.path.expanduser("~"))
                    return value if value and value != "False" else None
    except OSError:
        pass
    return None


def _load_env_file(env_file: str) -> dict[str, str]:
    """Load .env file and return as dict."""
    env_vars = {}
    if not os.path.exists(env_file):
        return env_vars
    with open(env_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Expand ${USER}
                value = value.replace("${USER}", os.environ.get("USER", "odoo"))
                env_vars[key] = value
    return env_vars


def _set_environment(env_vars: dict[str, str]) -> dict[str, str]:
    """Set up environment variables for Odoo execution.

    Uses .pgpass file for PostgreSQL authentication instead of
    exposing PGPASSWORD in the process environment.
    """
    env = os.environ.copy()
    # Export .env values
    for key, value in env_vars.items():
        env[key] = value

    # Set PostgreSQL connection vars
    pg_host = "localhost"
    pg_port = env_vars.get("DB_PORT", "18432")
    pg_user = env_vars.get("PGUSER", "ownerp")
    pg_password = env_vars.get("PGPASSWORD", "CHANGE_AT_FIRST")

    env["PGHOST"] = pg_host
    env["PGPORT"] = pg_port
    env["PGUSER"] = pg_user
    env["HOST"] = "0.0.0.0"

    # Write credentials to .pgpass instead of PGPASSWORD env var
    _write_pgpass(pg_host, pg_port, pg_user, pg_password)
    # Remove PGPASSWORD from env if present (prefer .pgpass)
    env.pop("PGPASSWORD", None)

    return env


def _write_pgpass(host: str, port: str, user: str, password: str) -> None:
    """Write PostgreSQL credentials to ~/.pgpass file.

    This avoids exposing passwords via process environment variables.
    Uses atomic write (write to temp file, then rename) to prevent
    data loss if the process crashes mid-write.

    Validates that password contains no characters that would corrupt
    the pgpass format (colons, newlines).
    """
    # Validate password against pgpass format-breaking characters
    if ":" in password or "\n" in password or "\r" in password:
        from odoodev.output import print_warning

        print_warning("Password contains invalid pgpass characters (: or newline) — skipping .pgpass write")
        return

    pgpass_path = os.path.join(os.path.expanduser("~"), ".pgpass")
    entry = f"{host}:{port}:*:{user}:{password}"

    # Read existing entries, update or append
    existing_lines: list[str] = []
    if os.path.exists(pgpass_path):
        with open(pgpass_path, encoding="utf-8") as f:
            existing_lines = [line.rstrip("\n") for line in f if line.strip()]

    # Build match prefix to find existing entry for this host:port:*:user
    prefix = f"{host}:{port}:*:{user}:"
    updated = False
    new_lines = []
    for line in existing_lines:
        if line.startswith(prefix):
            new_lines.append(entry)
            updated = True
        else:
            new_lines.append(line)
    if not updated:
        new_lines.append(entry)

    # Atomic write: write to temp file, then rename over target
    import tempfile

    pgpass_dir = os.path.dirname(pgpass_path)
    fd, tmp_path = tempfile.mkstemp(prefix=".pgpass_", dir=pgpass_dir)
    try:
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(new_lines) + "\n")
        os.chmod(tmp_path, 0o600)
        os.rename(tmp_path, pgpass_path)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _add_v19_log_handlers(cmd: list[str], version: str) -> None:
    """Mute deprecated XML-RPC/JSON-RPC warnings for Odoo 19+.

    Odoo 19 deprecated /xmlrpc, /xmlrpc/2 and /jsonrpc endpoints
    (scheduled for removal in Odoo 20). This silences the warnings
    until clients are migrated to the new /json/2/ API.
    """
    try:
        if int(version) >= 19:
            cmd.append("--log-handler=odoo.addons.rpc.controllers.jsonrpc:ERROR")
    except (ValueError, TypeError):
        pass


def _start_odoo(
    odoo_dir: str,
    config_path: str,
    mode: str,
    extra_args: tuple[str, ...],
    env: dict[str, str],
    venv_dir: str,
    version: str = "",
) -> None:
    """Start Odoo server with the given configuration."""
    python = get_venv_python(venv_dir)
    odoo_bin = os.path.join(odoo_dir, "odoo-bin")

    cmd = [python, odoo_bin, "-c", config_path]

    if mode == "dev":
        print_info("Starting Odoo in development mode (--dev=all)...")
        cmd.append("--dev=all")
    elif mode == "shell":
        print_info("Starting Odoo shell...")
        cmd.insert(2, "shell")
    elif mode == "test":
        print_info("Running Odoo tests...")
        cmd.extend(["--test-enable", "--stop-after-init"])
    else:
        # Normal mode
        odoo_port = env.get("ODOO_PORT", "18069")
        subtitle = f"Web: http://localhost:{odoo_port}"
        mailpit_port = env.get("MAILPIT_PORT", "18025")
        if check_port("localhost", int(mailpit_port)):
            subtitle += f"  |  Mailpit: http://localhost:{mailpit_port}"
        print_header(
            f"Odoo v{env.get('ODOO_VERSION', '?')} — Native Development",
            subtitle,
        )

    # Mute deprecated RPC endpoint warnings for v19+
    _add_v19_log_handlers(cmd, version)

    # Add extra arguments
    cmd.extend(extra_args)

    # Execute Odoo
    os.chdir(odoo_dir)
    try:
        result = subprocess.run(cmd, env=env)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print_info("Odoo server stopped.")


def _start_interactive_shell(odoo_dir: str, venv_dir: str, config_path: str, env: dict[str, str]) -> None:
    """Open an interactive shell with venv activated."""
    shell = detect_shell()
    env["ODOO_CONF"] = config_path

    if shell == "fish":
        activate = f"source '{venv_dir}/bin/activate.fish'"
        cmd = ["fish", "-C", f"{activate}; cd '{odoo_dir}'"]
    elif shell == "zsh":
        import tempfile

        tmpdir = tempfile.mkdtemp(prefix="odoodev_")
        zshrc = os.path.join(tmpdir, ".zshrc")
        # Create file with correct permissions from the start (no race condition)
        fd = os.open(zshrc, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("[[ -f ~/.zshrc ]] && source ~/.zshrc\n")
            f.write(f'source "{venv_dir}/bin/activate"\n')
            f.write(f'cd "{odoo_dir}"\n')
            f.write(f'export ODOO_CONF="{config_path}"\n')
        env["ZDOTDIR"] = tmpdir
        cmd = ["zsh"]
    else:
        import tempfile

        # Create temp file with correct permissions atomically
        tmpdir = tempfile.mkdtemp(prefix="odoodev_")
        bashrc_path = os.path.join(tmpdir, "odoodev.bashrc")
        fd = os.open(bashrc_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("[[ -f ~/.bashrc ]] && source ~/.bashrc\n")
            f.write(f'source "{venv_dir}/bin/activate"\n')
            f.write(f'cd "{odoo_dir}"\n')
            f.write(f'export ODOO_CONF="{config_path}"\n')
        cmd = ["bash", "--rcfile", bashrc_path]

    print_info(f"Opening {shell} shell with venv activated...")
    print_info(f"ODOO_CONF={config_path}")
    os.execvpe(cmd[0], cmd, env)


def _check_env_file(ctx: click.Context, version: str, native_dir: str) -> dict[str, str]:
    """Ensure .env file exists and return loaded env vars.

    Offers to create .env interactively if missing.

    Raises:
        SystemExit: If .env cannot be created or loaded.
    """
    env_file = os.path.join(native_dir, ".env")
    if not os.path.exists(env_file):
        print_warning(f"No .env file found at {env_file}")
        if confirm(f"Create .env for v{version} now?"):
            from odoodev.commands.env import env_setup

            ctx.invoke(env_setup, version=version, non_interactive=False)
            if not os.path.exists(env_file):
                print_error("Failed to create .env file")
                raise SystemExit(1)
        else:
            raise SystemExit(1)

    return _load_env_file(env_file)


def _check_venv(
    ctx: click.Context,
    version: str,
    version_cfg: object,
    venv_dir: str,
) -> None:
    """Validate virtual environment: exists, interpreter intact, Python version matches.

    Offers to create venv if missing. Checks setuptools for v16/v17.

    Raises:
        SystemExit: If venv is broken and cannot be fixed.
    """
    if not os.path.isdir(venv_dir):
        print_warning(f"Virtual environment not found at {venv_dir}")
        if confirm(f"Create venv for v{version} now?"):
            from odoodev.commands.venv import venv_setup

            ctx.invoke(venv_setup, version=version, force=False)
            if not os.path.isdir(venv_dir):
                print_error("Failed to create virtual environment")
                raise SystemExit(1)
        else:
            raise SystemExit(1)

    # Check venv interpreter symlink chain is intact
    from odoodev.core.prerequisites import check_venv_interpreter

    if not check_venv_interpreter(venv_dir):
        print_error("Venv Python interpreter is broken (underlying Python removed)")
        print_info(f"Fix: odoodev venv setup {version} --force")
        raise SystemExit(1)

    # Check venv Python version matches configuration
    python_version = version_cfg.python  # type: ignore[attr-defined]
    if not check_venv_python_matches(venv_dir, python_version):
        actual = get_venv_python_version(venv_dir) or "unknown"
        print_error(f"Venv Python version mismatch: found {actual}, expected {python_version}")
        print_info(f"Run: odoodev venv setup {version} --force")
        raise SystemExit(1)

    # Advisory: check for newer Python patch version
    from odoodev.core.venv_manager import get_full_python_version, get_system_python_version

    venv_full = get_full_python_version(venv_dir)
    system_full = get_system_python_version(python_version)
    if venv_full and system_full and venv_full != system_full:
        print_warning(f"Newer Python available: venv has {venv_full}, system has {system_full}")
        print_info(f"Run: odoodev venv setup {version} --force")

    # Odoo 16/17 require pkg_resources (from setuptools)
    try:
        ver_int = int(version)
    except (ValueError, TypeError):
        ver_int = 0
    if ver_int in (16, 17):
        from odoodev.core.venv_manager import ensure_setuptools

        print_info("Checking setuptools (required for Odoo v16/v17)...")
        if ensure_setuptools(venv_dir):
            print_info("setuptools available")
        else:
            print_error("Failed to install setuptools (required for Odoo v16/v17)")
            print_info(f"Manual fix: VIRTUAL_ENV={venv_dir} uv pip install setuptools")
            raise SystemExit(1)


def _check_odoo_source(ctx: click.Context, version: str, odoo_dir: str) -> None:
    """Ensure odoo-bin exists, offer to clone if missing.

    Raises:
        SystemExit: If odoo-bin cannot be found.
    """
    if not os.path.exists(os.path.join(odoo_dir, "odoo-bin")):
        print_warning(f"Odoo not found at {odoo_dir}/odoo-bin")
        if confirm(f"Clone repositories for v{version} now?"):
            from odoodev.commands.repos import repos as repos_cmd

            ctx.invoke(repos_cmd, version=version, init_mode=True)
            if not os.path.exists(os.path.join(odoo_dir, "odoo-bin")):
                print_error("odoo-bin still not found after repos clone")
                raise SystemExit(1)
        else:
            raise SystemExit(1)


def _check_odoo_config(ctx: click.Context, version: str, myconfs_dir: str) -> str:
    """Ensure an Odoo config file exists, offer to generate if missing.

    Returns:
        Path to the Odoo config file.

    Raises:
        SystemExit: If config cannot be found or generated.
    """
    config_path = _find_odoo_config(myconfs_dir)
    if not config_path:
        print_warning(f"No Odoo config found in {myconfs_dir}")
        if confirm("Generate Odoo config now?"):
            from odoodev.commands.repos import repos as repos_cmd

            ctx.invoke(repos_cmd, version=version, config_only=True)
            config_path = _find_odoo_config(myconfs_dir)
            if not config_path:
                print_error("Config generation failed")
                raise SystemExit(1)
        else:
            raise SystemExit(1)
    return config_path


def _check_services(
    env_vars: dict[str, str],
    version_cfg: object,
    version: str,
    native_dir: str,
    venv_dir: str,
    no_confirm: bool,
) -> None:
    """Check PostgreSQL, requirements freshness, and port conflicts.

    Raises:
        SystemExit: If a blocking issue cannot be resolved.
    """
    ports = version_cfg.ports  # type: ignore[attr-defined]

    # Check PostgreSQL
    db_port = int(env_vars.get("DB_PORT", str(ports.db)))
    if not check_port("localhost", db_port):
        print_warning(f"PostgreSQL not accessible on localhost:{db_port}")
        if no_confirm or confirm("Start Docker services now?"):
            subprocess.run(["docker", "compose", "up", "-d"], cwd=native_dir)
            import time

            time.sleep(5)
            if not check_port("localhost", db_port):
                print_error(f"PostgreSQL still not accessible on port {db_port}")
                raise SystemExit(1)
        else:
            print_warning("Continuing without PostgreSQL — Odoo may fail to start")

    # Check requirements freshness
    requirements = os.path.join(native_dir, "requirements.txt")
    if os.path.exists(requirements) and check_requirements_changed(venv_dir, requirements):
        print_warning("requirements.txt has changed since last install")
        if not no_confirm and confirm("Update packages now?"):
            subprocess.run(
                ["uv", "pip", "install", "-r", requirements],
                env={**os.environ, "VIRTUAL_ENV": venv_dir},
            )

    # Check if Odoo port is already in use
    odoo_port = int(env_vars.get("ODOO_PORT", str(ports.odoo)))
    if check_port("localhost", odoo_port):
        from odoodev.core.process_manager import find_odoo_process, stop_process

        pids = find_odoo_process(odoo_port)
        if pids:
            print_warning(f"Port {odoo_port} already in use by PID(s): {', '.join(str(p) for p in pids)}")
            if not no_confirm and confirm("Kill blocking process(es) and continue?"):
                for pid in pids:
                    stop_process(pid, timeout=5)
                print_success("Blocking process(es) terminated")
            else:
                raise SystemExit(1)
        else:
            print_warning(f"Port {odoo_port} is in use but process could not be identified")
            raise SystemExit(1)


def _launch_tui(
    version: str,
    mode: str,
    env: dict[str, str],
    env_vars: dict[str, str],
    version_cfg: object,
    odoo_dir: str,
    venv_dir: str,
    config_path: str,
    extra_args: tuple[str, ...],
) -> None:
    """Launch the TUI mode."""
    python = get_venv_python(venv_dir)
    odoo_bin = os.path.join(odoo_dir, "odoo-bin")
    tui_cmd = [python, odoo_bin, "-c", config_path]
    if mode == "dev":
        tui_cmd.append("--dev=all")
    _add_v19_log_handlers(tui_cmd, version)
    tui_cmd.extend(extra_args)

    ports = version_cfg.ports  # type: ignore[attr-defined]
    odoo_port = int(env_vars.get("ODOO_PORT", str(ports.odoo)))
    tui_db_name = _get_config_value(config_path, "db_name") or f"v{version}_exam"

    from odoodev.tui.app import OdooTuiApp

    app = OdooTuiApp(
        cmd=tui_cmd,
        env=env,
        cwd=odoo_dir,
        version_info=version,
        odoo_port=odoo_port,
        db_name=tui_db_name,
    )
    app.run()
    # Safety net: ensure Odoo is stopped regardless of how TUI exited
    # (crash, unhandled exception, signal). OdooProcess.stop() is idempotent.
    app._odoo.stop()


@click.command()
@click.argument("version", required=False)
@click.option("--dev", "mode", flag_value="dev", help="Start in development mode (--dev=all)")
@click.option("--shell", "mode", flag_value="shell", help="Start Odoo interactive shell")
@click.option("--test", "mode", flag_value="test", help="Run tests (--test-enable --stop-after-init)")
@click.option("--prepare", is_flag=True, help="Open interactive shell with venv (don't start Odoo)")
@click.option("--no-confirm", is_flag=True, help="Skip confirmation prompt")
@click.option("--tui", is_flag=True, help="Start with Terminal UI (log viewer, filtering, module update)")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def start(
    ctx: click.Context,
    version: str | None,
    mode: str | None,
    prepare: bool,
    no_confirm: bool,
    tui: bool,
    extra_args: tuple[str, ...],
) -> None:
    """Start Odoo server for the given version.

    Pass additional arguments to Odoo after '--':

        odoodev start 18 --dev -- -d v18_exam -u eq_sale
    """
    version = resolve_version(ctx, version)
    versions = load_versions()
    version_cfg = get_version(version, versions)

    native_dir = version_cfg.paths.native_dir
    odoo_dir = version_cfg.paths.server_dir
    myconfs_dir = version_cfg.paths.myconfs_dir
    venv_dir = os.path.join(native_dir, ".venv")

    # Preflight checks
    env_vars = _check_env_file(ctx, version, native_dir)
    env = _set_environment(env_vars)
    _check_venv(ctx, version, version_cfg, venv_dir)
    _check_odoo_source(ctx, version, odoo_dir)
    config_path = _check_odoo_config(ctx, version, myconfs_dir)
    _check_services(env_vars, version_cfg, version, native_dir, venv_dir, no_confirm)

    # Show config info
    db_port = int(env_vars.get("DB_PORT", str(version_cfg.ports.db)))
    if not no_confirm and not prepare:
        print_table(
            "Configuration",
            {
                "Version": f"v{version}",
                "Config": config_path,
                "DB Host": _get_config_value(config_path, "db_host") or "localhost",
                "DB Port": str(db_port),
                "Odoo Port": env_vars.get("ODOO_PORT", str(version_cfg.ports.odoo)),
            },
        )

    # Route based on mode
    if mode is None:
        mode = "normal"

    if prepare:
        _start_interactive_shell(odoo_dir, venv_dir, config_path, env)
        return

    # TUI mode — available for normal and dev modes only
    if tui:
        if mode not in ("normal", "dev"):
            print_error("--tui is only available for normal and dev modes")
            raise SystemExit(1)
        _launch_tui(version, mode, env, env_vars, version_cfg, odoo_dir, venv_dir, config_path, extra_args)
        return

    if no_confirm:
        _start_odoo(odoo_dir, config_path, mode, extra_args, env, venv_dir, version=version)
    else:
        if mode == "normal":
            prompt = f"Start Odoo v{version} server?"
        else:
            mode_descriptions = {
                "dev": "development mode (hot-reload)",
                "shell": "interactive shell",
                "test": "test mode (--test-enable)",
            }
            mode_label = mode_descriptions.get(mode, f"{mode} mode")
            prompt = f"Start Odoo v{version} in {mode_label}?"

        if confirm(prompt):
            _start_odoo(odoo_dir, config_path, mode, extra_args, env, venv_dir, version=version)
        else:
            print_info("Alternative start modes:")
            print_info("  odoodev start --dev      Development mode (hot-reload)")
            print_info("  odoodev start --shell    Odoo interactive shell")
            print_info("  odoodev start --test     Run tests (--test-enable)")
            print_info("  odoodev start --prepare  Open shell with venv activated")
            if confirm("Open interactive shell with venv instead?"):
                _start_interactive_shell(odoo_dir, venv_dir, config_path, env)
            else:
                print_info("Aborted.")
