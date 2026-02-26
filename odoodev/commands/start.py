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
from odoodev.core.venv_manager import check_requirements_changed, get_venv_python
from odoodev.core.version_registry import get_version, load_versions
from odoodev.output import confirm, print_error, print_header, print_info, print_table, print_warning


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
    """Set up environment variables for Odoo execution."""
    env = os.environ.copy()
    # Export .env values
    for key, value in env_vars.items():
        env[key] = value

    # Set PostgreSQL connection vars
    env["PGHOST"] = "localhost"
    env["PGPORT"] = env_vars.get("DB_PORT", "18432")
    env["PGUSER"] = env_vars.get("PGUSER", "ownerp")
    env["PGPASSWORD"] = env_vars.get("PGPASSWORD", "CHANGE_AT_FIRST")
    env["HOST"] = "0.0.0.0"

    return env


def _start_odoo(
    odoo_dir: str,
    config_path: str,
    mode: str,
    extra_args: tuple[str, ...],
    env: dict[str, str],
    venv_dir: str,
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

        tmpdir = tempfile.mkdtemp()
        os.chmod(tmpdir, 0o700)
        zshrc = os.path.join(tmpdir, ".zshrc")
        with open(zshrc, "w") as f:
            f.write("[[ -f ~/.zshrc ]] && source ~/.zshrc\n")
            f.write(f'source "{venv_dir}/bin/activate"\n')
            f.write(f'cd "{odoo_dir}"\n')
            f.write(f'export ODOO_CONF="{config_path}"\n')
        env["ZDOTDIR"] = tmpdir
        cmd = ["zsh"]
    else:
        import tempfile

        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".bashrc", delete=False)
        tmp.write("[[ -f ~/.bashrc ]] && source ~/.bashrc\n")
        tmp.write(f'source "{venv_dir}/bin/activate"\n')
        tmp.write(f'cd "{odoo_dir}"\n')
        tmp.write(f'export ODOO_CONF="{config_path}"\n')
        tmp.close()
        os.chmod(tmp.name, 0o600)
        cmd = ["bash", "--rcfile", tmp.name]

    print_info(f"Opening {shell} shell with venv activated...")
    print_info(f"ODOO_CONF={config_path}")
    os.execvpe(cmd[0], cmd, env)


@click.command()
@click.argument("version", required=False)
@click.option("--dev", "mode", flag_value="dev", help="Start in development mode (--dev=all)")
@click.option("--shell", "mode", flag_value="shell", help="Start Odoo interactive shell")
@click.option("--test", "mode", flag_value="test", help="Run tests (--test-enable --stop-after-init)")
@click.option("--prepare", is_flag=True, help="Open interactive shell with venv (don't start Odoo)")
@click.option("--no-confirm", is_flag=True, help="Skip confirmation prompt")
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def start(
    ctx: click.Context,
    version: str | None,
    mode: str | None,
    prepare: bool,
    no_confirm: bool,
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

    # Load .env
    env_file = os.path.join(native_dir, ".env")
    if not os.path.exists(env_file):
        print_error(f"No .env file found at {env_file}")
        print_info(f"Run: odoodev env setup {version}")
        raise SystemExit(1)

    env_vars = _load_env_file(env_file)
    env = _set_environment(env_vars)

    # Check prerequisites
    if not os.path.isdir(venv_dir):
        print_error(f"Virtual environment not found at {venv_dir}")
        print_info(f"Run: odoodev venv setup {version}")
        raise SystemExit(1)

    if not os.path.exists(os.path.join(odoo_dir, "odoo-bin")):
        print_error(f"Odoo not found at {odoo_dir}/odoo-bin")
        print_info(f"Run: odoodev repos {version}")
        raise SystemExit(1)

    # Find config
    config_path = _find_odoo_config(myconfs_dir)
    if not config_path:
        print_error(f"No Odoo config found in {myconfs_dir}")
        print_info(f"Run: odoodev repos {version} --config-only")
        raise SystemExit(1)

    # Check PostgreSQL
    db_port = int(env_vars.get("DB_PORT", str(version_cfg.ports.db)))
    if not check_port("localhost", db_port):
        print_warning(f"PostgreSQL not accessible on localhost:{db_port}")
        if confirm("Start Docker services now?"):
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

    # Show config info
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

    if no_confirm:
        _start_odoo(odoo_dir, config_path, mode, extra_args, env, venv_dir)
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
            _start_odoo(odoo_dir, config_path, mode, extra_args, env, venv_dir)
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
