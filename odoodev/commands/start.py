"""odoodev start - Start Odoo server in various modes."""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys

import click

from odoodev import i18n
from odoodev.cli import resolve_version
from odoodev.core.environment import detect_shell
from odoodev.core.prerequisites import check_port
from odoodev.core.venv_manager import (
    check_requirements_changed,
    check_venv_python_matches,
    get_venv_python,
    get_venv_python_version,
    install_requirements,
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


def _clean_sessions(config_path: str, version: str, force: bool, no_confirm: bool) -> None:
    """Check for existing Odoo sessions and optionally clean them.

    When *force* is True (``--clean-sessions`` flag), sessions are removed
    without prompting.  Otherwise an interactive confirmation is shown —
    unless *no_confirm* is True, in which case nothing happens.
    """
    data_dir = _get_config_value(config_path, "data_dir")
    if not data_dir:
        return

    data_dir = os.path.expanduser(data_dir)
    sessions_dir = os.path.join(data_dir, "sessions")

    if not os.path.isdir(sessions_dir):
        return

    session_files = [f for f in os.listdir(sessions_dir) if os.path.isfile(os.path.join(sessions_dir, f))]
    if not session_files:
        return

    count = len(session_files)
    should_clean = force
    if not should_clean and not no_confirm:
        should_clean = confirm(
            f"v{version}: {count} Session(s) gefunden in {sessions_dir}. Bereinigen?",
            default=False,
        )

    if should_clean:
        shutil.rmtree(sessions_dir)
        os.makedirs(sessions_dir, exist_ok=True)
        print_success(f"v{version}: {count} Session(s) bereinigt")


def _load_env_file(env_file: str) -> dict[str, str]:
    """Load .env file and return as dict."""
    env_vars: dict[str, str] = {}
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
                # Strip surrounding quotes (single or double) — e.g. PASSWORD="my pass"
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                # Expand ${USER} and $USER
                value = value.replace("${USER}", os.environ.get("USER", "odoo"))
                value = value.replace("$USER", os.environ.get("USER", "odoo"))
                env_vars[key] = value
    return env_vars


def _set_environment(env_vars: dict[str, str], bind_host: str = "127.0.0.1") -> dict[str, str]:
    """Set up environment variables for Odoo execution.

    Uses .pgpass file for PostgreSQL authentication instead of
    exposing PGPASSWORD in the process environment.

    Args:
        env_vars: Parsed .env values.
        bind_host: Interface Odoo should bind to. Defaults to ``127.0.0.1``
            (loopback only) to avoid exposing the dev server on all
            interfaces. Use ``0.0.0.0`` to accept connections from VMs
            or shared networks.
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

    # Warn once when the placeholder default is still in use
    from odoodev.core.database import _warn_once_on_placeholder

    _warn_once_on_placeholder(pg_password)

    env["PGHOST"] = pg_host
    env["PGPORT"] = pg_port
    env["PGUSER"] = pg_user
    env["HOST"] = bind_host

    # Write credentials to .pgpass instead of PGPASSWORD env var
    _write_pgpass(pg_host, pg_port, pg_user, pg_password)
    # Remove PGPASSWORD from env if present (prefer .pgpass)
    env.pop("PGPASSWORD", None)

    return env


def resolve_odoo_invocation(version_cfg, env_vars: dict[str, str]) -> dict | None:
    """Resolve the building blocks for a one-shot odoo-bin invocation.

    Returns a kwargs dict for callers that run odoo-bin (e.g. ``run_neutralize``),
    or ``None`` when prerequisites are missing (venv, odoo-bin, generated config).

    Returns:
        ``{venv_python, odoo_bin, config_path, env, cwd}`` or ``None``.
    """
    venv_dir = os.path.join(version_cfg.paths.native_dir, ".venv")
    venv_python = get_venv_python(venv_dir)
    odoo_bin = os.path.join(version_cfg.paths.server_dir, "odoo-bin")
    config_path = _find_odoo_config(version_cfg.paths.myconfs_dir)
    if not (os.path.exists(venv_python) and os.path.exists(odoo_bin) and config_path):
        return None
    return {
        "venv_python": venv_python,
        "odoo_bin": odoo_bin,
        "config_path": config_path,
        "env": _set_environment(env_vars),
        "cwd": version_cfg.paths.server_dir,
    }


def _pgpass_escape(value: str) -> str:
    """Escape a .pgpass field per pgpass(5): backslash first, then colon."""
    return value.replace("\\", "\\\\").replace(":", "\\:")


def _write_pgpass(host: str, port: str, user: str, password: str) -> None:
    """Write PostgreSQL credentials to ~/.pgpass file.

    This avoids exposing passwords via process environment variables.
    Uses atomic write (write to temp file, then rename) to prevent
    data loss if the process crashes mid-write.

    Colons and backslashes are escaped per the pgpass format; only
    newlines (illegal in the format) cause the write to be skipped.
    """
    if "\n" in password or "\r" in password:
        from odoodev.output import print_warning

        print_warning("Password contains a newline — skipping .pgpass write")
        return

    pgpass_path = os.path.join(os.path.expanduser("~"), ".pgpass")
    entry = f"{_pgpass_escape(host)}:{_pgpass_escape(port)}:*:{_pgpass_escape(user)}:{_pgpass_escape(password)}"

    # Read existing entries, update or append
    existing_lines: list[str] = []
    if os.path.exists(pgpass_path):
        with open(pgpass_path, encoding="utf-8") as f:
            existing_lines = [line.rstrip("\n") for line in f if line.strip()]

    # Build match prefix to find existing entry for this host:port:*:user
    prefix = f"{_pgpass_escape(host)}:{_pgpass_escape(port)}:*:{_pgpass_escape(user)}:"
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
        fd = -1  # fdopen consumed the fd; mark as closed
        os.chmod(tmp_path, 0o600)
        os.rename(tmp_path, pgpass_path)
    except Exception:
        # Close fd if os.fdopen never consumed it
        if fd != -1:
            try:
                os.close(fd)
            except OSError:
                pass
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _add_v19_log_handlers(cmd: list[str], version: str) -> None:
    """Mute deprecated XML-RPC/JSON-RPC warnings for Odoo 19+.

    Odoo 19 deprecated /xmlrpc, /xmlrpc/2 and /jsonrpc endpoints
    (scheduled for removal in Odoo 22). The deprecation warning is emitted
    by both the ``xmlrpc`` and ``jsonrpc`` controllers, so both loggers are
    raised to ERROR. The TUI module export uses /xmlrpc/2, hence the
    ``xmlrpc`` handler is what actually silences it.
    """
    try:
        if int(version) >= 19:
            cmd.append("--log-handler=odoo.addons.rpc.controllers.xmlrpc:ERROR")
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
    version_cfg: object = None,
    load_language: str | None = None,
    i18n_overwrite: bool = False,
) -> None:
    """Start Odoo server with the given configuration."""
    python = get_venv_python(venv_dir)
    odoo_bin = os.path.join(odoo_dir, "odoo-bin")

    cmd = [python, odoo_bin, "-c", config_path]

    # Always show the URL panel so users get visual confirmation of the port
    # they should open in the browser — also in --dev/--shell/--test.
    default_odoo_port = str(version_cfg.ports.odoo) if version_cfg is not None else ""  # type: ignore[attr-defined]
    default_mailpit_port = str(version_cfg.ports.mailpit) if version_cfg is not None else ""  # type: ignore[attr-defined]
    odoo_port = env.get("ODOO_PORT") or default_odoo_port
    mailpit_port = env.get("MAILPIT_PORT") or default_mailpit_port
    mode_suffix = {"dev": " (--dev)", "shell": " (--shell)", "test": " (--test)"}.get(mode, "")
    if odoo_port:
        if mailpit_port and check_port("localhost", int(mailpit_port)):
            subtitle = i18n.t("start.url_panel_with_mailpit", port=odoo_port, mailpit=mailpit_port)
        else:
            subtitle = i18n.t("start.url_panel_subtitle", port=odoo_port)
        print_header(
            f"Odoo v{env.get('ODOO_VERSION', version or '?')} — Native Development{mode_suffix}",
            subtitle,
        )

    if mode == "dev":
        print_info("Starting Odoo in development mode (--dev=all)...")
        cmd.append("--dev=all")
    elif mode == "shell":
        print_info("Starting Odoo shell...")
        cmd.insert(2, "shell")
    elif mode == "test":
        print_info("Running Odoo tests...")
        cmd.extend(["--test-enable", "--stop-after-init"])

    # Mute deprecated RPC endpoint warnings for v19+
    _add_v19_log_handlers(cmd, version)

    # Add i18n/language loading flags
    if load_language:
        cmd.append(f"--load-language={load_language}")
    if i18n_overwrite:
        cmd.append("--i18n-overwrite")
        # Odoo requires -u (update) when --i18n-overwrite is used
        if "-u" not in extra_args:
            cmd.extend(["-u", "all"])

    # Add extra arguments
    cmd.extend(extra_args)

    # The interactive Odoo shell (REPL) must stay in the terminal's foreground
    # process group to read stdin — running it in its own session would trigger
    # SIGTTIN. So shell mode keeps the simple inherit-and-run path.
    if mode == "shell":
        try:
            result = subprocess.run(cmd, env=env, cwd=odoo_dir)
            sys.exit(result.returncode)
        except KeyboardInterrupt:
            print_info("Odoo server stopped.")
        return

    # For long-running server modes (normal/dev/test) launch odoo-bin in its own
    # session. Ctrl+C in the terminal then reaches only odoodev, which forwards a
    # SIGTERM→SIGKILL to the whole Odoo process group — otherwise odoo-bin's
    # forked workers survive and keep holding the port. Mirrors the TUI pattern
    # in odoodev/tui/odoo_process.py.
    from odoodev.core.process_manager import stop_process_group

    proc = subprocess.Popen(cmd, env=env, cwd=odoo_dir, start_new_session=True)
    try:
        proc.wait()
        sys.exit(proc.returncode)
    except KeyboardInterrupt:
        print_info("Stopping Odoo server...")
        try:
            pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            pgid = None
        if pgid is not None:
            stop_process_group(pgid, timeout=10)
        print_info("Odoo server stopped.")
        sys.exit(0)


def _start_interactive_shell(odoo_dir: str, venv_dir: str, config_path: str, env: dict[str, str]) -> None:
    """Open an interactive shell with venv activated."""
    shell = detect_shell()
    env["ODOO_CONF"] = config_path

    if shell == "fish":
        activate = f"source '{venv_dir}/bin/activate.fish'"
        cmd = ["fish", "-C", f"{activate}; cd '{odoo_dir}'"]
    elif shell == "zsh":
        # Use a fixed cache directory instead of mkdtemp so execvpe never
        # leaves orphaned temp directories behind.
        cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "odoodev")
        os.makedirs(cache_dir, mode=0o700, exist_ok=True)
        zshrc = os.path.join(cache_dir, ".zshrc")
        # Overwrite atomically with correct permissions
        fd = os.open(zshrc, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("[[ -f ~/.zshrc ]] && source ~/.zshrc\n")
            f.write(f'source "{venv_dir}/bin/activate"\n')
            f.write(f'cd "{odoo_dir}"\n')
            f.write(f'export ODOO_CONF="{config_path}"\n')
        env["ZDOTDIR"] = cache_dir
        cmd = ["zsh"]
    else:
        import tempfile

        # Create temp file with correct permissions atomically.
        # Unlink the file before execvpe: on POSIX the shell already receives
        # the path via --rcfile and holds an open fd, so the file stays
        # accessible but is removed from the directory immediately — no leak.
        tmpdir = tempfile.mkdtemp(prefix="odoodev_")
        bashrc_path = os.path.join(tmpdir, "odoodev.bashrc")
        fd = os.open(bashrc_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("[[ -f ~/.bashrc ]] && source ~/.bashrc\n")
            f.write(f'source "{venv_dir}/bin/activate"\n')
            f.write(f'cd "{odoo_dir}"\n')
            f.write(f'export ODOO_CONF="{config_path}"\n')
        cmd = ["bash", "--rcfile", bashrc_path]
        # Unlink before exec so the file disappears from the filesystem even
        # though execvpe replaces this process (no Python finally/atexit runs).
        try:
            os.unlink(bashrc_path)
            os.rmdir(tmpdir)
        except OSError:
            pass

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
        print_warning(i18n.t("start.env_missing", path=env_file))
        print_info(i18n.t("start.env_missing_hint", version=version))
        if confirm(f"Create .env for v{version} now?"):
            from odoodev.commands.env import env_setup

            ctx.invoke(env_setup, version=version, non_interactive=False)
            if not os.path.exists(env_file):
                print_error("Failed to create .env file")
                raise SystemExit(1)
        else:
            raise SystemExit(1)

    return _load_env_file(env_file)


def _check_placeholder_password(
    env_vars: dict[str, str],
    version: str,
    native_dir: str,
    allow_default: bool,
) -> None:
    """Block on the unchanged ``CHANGE_AT_FIRST`` placeholder password.

    Renders a Rich panel with the affected ``.env`` path and an action hint,
    then — in interactive sessions — prompts a blocking confirmation. CI and
    scripted runs can pass ``allow_default=True`` (via
    ``--allow-default-credentials``) to bypass the prompt.

    Raises:
        SystemExit: If the user declines the placeholder, or if running
            non-interactively without ``allow_default``.
    """
    from odoodev.core.database import DEFAULT_DB_PASSWORD

    pg_password = env_vars.get("PGPASSWORD", "")
    if pg_password and pg_password != DEFAULT_DB_PASSWORD:
        return  # configured properly, nothing to do

    env_path = os.path.join(native_dir, ".env")

    print_warning(i18n.t("start.placeholder_password_title"))
    print_info(i18n.t("start.placeholder_password_body", path=env_path))
    print_info(i18n.t("start.placeholder_password_action", version=version, path=env_path))

    if allow_default:
        return

    if not sys.stdin.isatty():
        print_error(i18n.t("start.placeholder_password_aborted"))
        raise SystemExit(1)

    if not confirm(i18n.t("start.placeholder_password_continue"), default=False):
        print_error(i18n.t("start.placeholder_password_aborted"))
        raise SystemExit(1)


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


def _persist_runtime_if_confirmed(chosen: str, configured: str) -> None:
    """Offer to save the chosen runtime as the new default when it differs.

    Only called in interactive mode. Writes ``container_runtime`` to the global
    config so the user is not forced to pass ``--runtime`` on every invocation.
    """
    if chosen == configured:
        return
    if not confirm(f"Save '{chosen}' as default runtime?", default=False):
        return
    import dataclasses

    from odoodev.core.global_config import load_global_config, save_global_config

    save_global_config(dataclasses.replace(load_global_config(), container_runtime=chosen))
    print_success(f"Saved container_runtime = {chosen}")


def _select_runtime(runtime_override: str | None, no_confirm: bool) -> str | None:
    """Decide which container runtime to start PostgreSQL with.

    ``--runtime`` wins outright. Otherwise, when interactive, offer the choice
    (default = configured runtime) plus a 'skip' option; non-interactive uses the
    configured default. When interactive and the effective runtime differs from
    the stored default, offer to persist it. Returns the runtime id, or None to
    skip starting services.
    """
    from odoodev.core.container_backend import resolve_runtime

    configured = resolve_runtime(None)

    if runtime_override:
        chosen = resolve_runtime(runtime_override)
        if not no_confirm:
            _persist_runtime_if_confirmed(chosen, configured)
        return chosen

    if no_confirm:
        return configured

    import questionary

    from odoodev.output import select as _select

    choice = _select(
        "PostgreSQL is not running. Start it with which runtime?",
        choices=[
            questionary.Choice("Docker", value="docker"),
            questionary.Choice("Apple Container", value="apple"),
            questionary.Choice("Skip (continue without starting)", value="skip"),
        ],
        default=configured,
    )
    if choice == "skip":
        return None
    _persist_runtime_if_confirmed(choice, configured)
    return choice


def _check_services(
    env_vars: dict[str, str],
    version_cfg: object,
    version: str,
    native_dir: str,
    venv_dir: str,
    no_confirm: bool,
    runtime: str | None = None,
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

        # Migration redirect: start the source version's container (shared DB).
        effective_cfg = version_cfg
        try:
            from odoodev.core.migration_config import get_active_group

            group = get_active_group()
            if group and group.to_version == version:
                effective_cfg = get_version(group.from_version)
                print_info(f"[MIGRATION] Starting v{group.from_version}'s PostgreSQL container")
        except Exception:  # noqa: S110
            pass

        runtime_name = _select_runtime(runtime, no_confirm)
        if runtime_name is None:
            print_warning("Continuing without PostgreSQL — Odoo may fail to start")
        else:
            from odoodev.core.container_backend import get_backend, read_env_file

            backend = get_backend(runtime_name)
            svc_env = read_env_file(effective_cfg.paths.native_dir)  # type: ignore[attr-defined]
            print_info(f"Starting PostgreSQL via {backend.name}...")
            if backend.service_up(effective_cfg, svc_env) != 0:
                print_error(f"Failed to start PostgreSQL via {backend.name}")
                raise SystemExit(1)
            import time

            time.sleep(5)
            if not check_port("localhost", db_port):
                print_error(f"PostgreSQL still not accessible on port {db_port}")
                raise SystemExit(1)
            # Apple Container has no compose/Desktop UI — surface the container
            # name so the user can confirm it is running (`container ls`, NOT
            # `container machine list`, which only lists VM infrastructure).
            if runtime_name == "apple":
                from odoodev.core.container_backend import build_dev_spec

                name = build_dev_spec(effective_cfg, svc_env).container_name
                print_success(f"Apple Container '{name}' is running — inspect with: container ls")

    # Check requirements freshness
    requirements = os.path.join(native_dir, "requirements.txt")
    if os.path.exists(requirements) and check_requirements_changed(venv_dir, requirements):
        print_warning("requirements.txt has changed since last install")
        if not no_confirm and confirm("Update packages now?"):
            install_requirements(venv_dir, requirements, capture=False)

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


def _extract_db_from_args(extra_args: tuple[str, ...]) -> str | None:
    """Recover the database name from raw Odoo extra args.

    Covers the ``odoodev start ... -- -d db`` form, where ``-d`` is passed
    through to odoo-bin without going through the ``--database`` option.
    Handles ``-d db`` / ``--database db`` and ``-d=db`` / ``--database=db``.
    """
    args = list(extra_args)
    for i, arg in enumerate(args):
        if arg in ("-d", "--database") and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith("-d="):
            return arg[len("-d=") :]
        if arg.startswith("--database="):
            return arg[len("--database=") :]
    return None


def _resolve_tui_db_name(database: str | None, extra_args: tuple[str, ...], config_path: str, version: str) -> str:
    """Resolve which database the TUI should display and target.

    Priority: explicit ``--database`` > ``-d``/``--database`` inside the raw
    extra args (the ``-- -d db`` form) > ``db_name`` from the Odoo config >
    conventional ``v{version}_exam`` fallback. Fixes the bug where the user's
    chosen database was ignored in favor of the conf value / fallback.
    """
    return (
        database or _extract_db_from_args(extra_args) or _get_config_value(config_path, "db_name") or f"v{version}_exam"
    )


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
    database: str | None = None,
    load_language: str | None = None,
    i18n_overwrite: bool = False,
) -> None:
    """Launch the TUI mode."""
    python = get_venv_python(venv_dir)
    odoo_bin = os.path.join(odoo_dir, "odoo-bin")
    tui_cmd = [python, odoo_bin, "-c", config_path]
    if mode == "dev":
        tui_cmd.append("--dev=all")
    _add_v19_log_handlers(tui_cmd, version)
    if load_language:
        tui_cmd.append(f"--load-language={load_language}")
    if i18n_overwrite:
        tui_cmd.append("--i18n-overwrite")
        if "-u" not in extra_args:
            tui_cmd.extend(["-u", "all"])
    tui_cmd.extend(extra_args)

    ports = version_cfg.ports  # type: ignore[attr-defined]
    odoo_port = int(env_vars.get("ODOO_PORT", str(ports.odoo)))
    db_port = int(env_vars.get("DB_PORT", str(ports.db)))
    tui_db_name = _resolve_tui_db_name(database, extra_args, config_path, version)

    from odoodev.tui.app import OdooTuiApp

    app = OdooTuiApp(
        cmd=tui_cmd,
        env=env,
        cwd=odoo_dir,
        version_info=version,
        odoo_port=odoo_port,
        db_name=tui_db_name,
        db_port=db_port,
    )
    app.run()
    # Safety net: ensure Odoo is stopped regardless of how TUI exited
    # (crash, unhandled exception, signal). OdooProcess.stop() is idempotent.
    app._odoo.stop()


def _build_odoo_extra_args(
    database: str | None,
    update: str | None,
    init: str | None,
    extra_args: tuple[str, ...],
) -> tuple[str, ...]:
    """Merge explicit Odoo options (-d, -u, -i) into extra_args tuple."""
    merged = list(extra_args)
    if database:
        merged.extend(["-d", database])
    if update:
        merged.extend(["-u", update])
    if init:
        merged.extend(["-i", init])
    return tuple(merged)


@click.command()
@click.argument("version", required=False)
@click.option("--dev", "mode", flag_value="dev", help="Start in development mode (--dev=all)")
@click.option("--shell", "mode", flag_value="shell", help="Start Odoo interactive shell")
@click.option("--test", "mode", flag_value="test", help="Run tests (--test-enable --stop-after-init)")
@click.option("--prepare", is_flag=True, help="Open interactive shell with venv (don't start Odoo)")
@click.option("--no-confirm", is_flag=True, help="Skip confirmation prompt")
@click.option("--yes", "-y", "yes_flag", is_flag=True, hidden=True, help="Alias for --no-confirm")
@click.option("--tui", is_flag=True, help="Start with Terminal UI (log viewer, filtering, module update)")
@click.option("--load-language", default=None, help="Load language (e.g. 'de_DE', 'fr_FR', 'all')")
@click.option("--i18n-overwrite", is_flag=True, help="Overwrite existing translations when loading language")
@click.option("--clean-sessions", is_flag=True, help="Clear Odoo sessions before starting")
@click.option("-d", "--database", default=None, help="Odoo database name")
@click.option("-u", "--update", default=None, help="Modules to update (comma-separated or 'all')")
@click.option("-i", "--init", default=None, help="Modules to install (comma-separated)")
@click.option(
    "--host",
    "bind_host",
    default="127.0.0.1",
    show_default=True,
    help="Interface Odoo binds to. Use 0.0.0.0 to expose on all interfaces (VMs, shared networks).",
)
@click.option(
    "--allow-default-credentials",
    is_flag=True,
    help="Allow the placeholder password 'CHANGE_AT_FIRST' (development/CI only).",
)
@click.option(
    "--runtime",
    "runtime",
    type=click.Choice(["docker", "apple"]),
    default=None,
    help="Container runtime for PostgreSQL when it must be started (overrides config). docker | apple",
)
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def start(
    ctx: click.Context,
    version: str | None,
    mode: str | None,
    prepare: bool,
    no_confirm: bool,
    yes_flag: bool,
    tui: bool,
    load_language: str | None,
    i18n_overwrite: bool,
    clean_sessions: bool,
    database: str | None,
    update: str | None,
    init: str | None,
    bind_host: str,
    allow_default_credentials: bool,
    runtime: str | None,
    extra_args: tuple[str, ...],
) -> None:
    """Start Odoo server for the given version.

    \b
    Common Odoo options can be passed directly:
        odoodev start 18 --dev -d v18_exam -u eq_sale
        odoodev start 18 -d v18_exam -i eq_sale,eq_stock

    \b
    Start with the Terminal UI (log viewer, filtering, module update):
        odoodev start 18 --tui
        odoodev start 18 --dev --tui -d v18_exam

    \b
    For other Odoo arguments, use '--' separator:
        odoodev start 18 -d v18_exam -- --workers=4 --log-level=debug

    \b
    Load translations:
        odoodev start 18 --load-language=de_DE --i18n-overwrite -d v18_exam

    \b
    Clean sessions before starting:
        odoodev start 18 --clean-sessions
    """
    no_confirm = no_confirm or yes_flag

    version = resolve_version(ctx, version)
    versions = load_versions()
    version_cfg = get_version(version, versions)

    # Merge explicit Odoo options into extra_args
    extra_args = _build_odoo_extra_args(database, update, init, extra_args)

    native_dir = version_cfg.paths.native_dir
    odoo_dir = version_cfg.paths.server_dir
    myconfs_dir = version_cfg.paths.myconfs_dir
    venv_dir = os.path.join(native_dir, ".venv")

    # Preflight checks
    env_vars = _check_env_file(ctx, version, native_dir)
    _check_placeholder_password(env_vars, version, native_dir, allow_default_credentials)
    env = _set_environment(env_vars, bind_host=bind_host)
    _check_venv(ctx, version, version_cfg, venv_dir)
    _check_odoo_source(ctx, version, odoo_dir)
    config_path = _check_odoo_config(ctx, version, myconfs_dir)
    _clean_sessions(config_path, version, clean_sessions, no_confirm)
    _check_services(env_vars, version_cfg, version, native_dir, venv_dir, no_confirm, runtime=runtime)

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
        _launch_tui(
            version,
            mode,
            env,
            env_vars,
            version_cfg,
            odoo_dir,
            venv_dir,
            config_path,
            extra_args,
            database=database,
            load_language=load_language,
            i18n_overwrite=i18n_overwrite,
        )
        return

    if no_confirm:
        _start_odoo(
            odoo_dir,
            config_path,
            mode,
            extra_args,
            env,
            venv_dir,
            version=version,
            version_cfg=version_cfg,
            load_language=load_language,
            i18n_overwrite=i18n_overwrite,
        )
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
            _start_odoo(
                odoo_dir,
                config_path,
                mode,
                extra_args,
                env,
                venv_dir,
                version=version,
                version_cfg=version_cfg,
                load_language=load_language,
                i18n_overwrite=i18n_overwrite,
            )
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
