"""Container runtime abstraction: Docker vs Apple Container.

odoodev needs a single Linux container (PostgreSQL) for local development.
Historically this was provisioned via ``docker compose``. Apple's ``container``
(https://github.com/apple/container, v1.0.0+, macOS 26) is a native alternative
that runs each container as its own lightweight VM via Virtualization.framework.

Both runtimes expose a near-identical ``run`` CLI (``--publish``, ``--volume``,
``--env``, ``--detach``, named volumes), so a thin abstraction lets us provision
an equivalent PostgreSQL container on either and compare them (see
``odoodev bench``). Phase 2 will wire the chosen runtime into ``start``/``init``.

This module deliberately uses the raw ``run`` path (not ``docker compose``) so
that a Docker-vs-Apple benchmark measures the runtime/storage layer itself,
without compose orchestration overhead skewing the numbers.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

from odoodev.core.environment import command_exists, detect_os, detect_user, is_macos
from odoodev.core.version_registry import VersionConfigProtocol

# Runtime identifiers used across config, CLI flags and the factory.
RUNTIME_DOCKER = "docker"
RUNTIME_APPLE = "apple"
VALID_RUNTIMES = (RUNTIME_DOCKER, RUNTIME_APPLE)

# Mount the data volume here, but point PGDATA at a SUBDIRECTORY of it.
# Apple Container backs each named volume with its own EXT4 block device, whose
# root contains a 'lost+found' entry — so a volume mounted directly as the data
# dir is "not empty" and the postgres image's initdb refuses to run. Using a
# subdirectory (the postgres image's documented workaround for block-device
# volumes) sidesteps this and is harmless on Docker, keeping both runtimes
# identical for a fair benchmark.
_DATA_MOUNT = "/var/lib/postgresql/data"
_PGDATA = f"{_DATA_MOUNT}/pgdata"


def _probe(argv: list[str], timeout: float = 15) -> bool:
    """Run a short health-probe command; False on failure, absence or timeout."""
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


@dataclass(frozen=True)
class RuntimeDiagnosis:
    """Structured result of a container-runtime health probe.

    Produced by :func:`diagnose_runtime` — pure inspection, no side effects.
    ``problem`` describes what is wrong (None when the runtime is usable),
    ``hints`` are actionable next steps in recommended order.
    """

    runtime: str
    backend_name: str
    cli_installed: bool
    daemon_running: bool
    problem: str | None
    hints: tuple[str, ...]

    @property
    def ready(self) -> bool:
        return self.cli_installed and self.daemon_running


@dataclass(frozen=True)
class PostgresSpec:
    """Everything needed to provision a single PostgreSQL container.

    Backend-agnostic: the same spec produces an equivalent container under
    Docker (``docker run``) or Apple Container (``container run``).
    """

    image: str  # e.g. "postgres:16.11-alpine"
    container_name: str
    volume_name: str  # named volume mounted at /var/lib/postgresql/data
    host_port: int  # published to localhost:<host_port> -> 5432
    user: str
    password: str
    db_name: str = "postgres"
    shm_size: str = "1g"
    # Host postgresql.conf to bind-mount (dev service mirrors the compose tuning).
    # None → run with the image's stock config (used by the isolated benchmark).
    conf_path: str | None = None


def _postgres_run_args(spec: PostgresSpec) -> list[str]:
    """Build the runtime-agnostic ``run`` arguments for a PostgreSQL container.

    The flags (-d/-p/-v/-e/--shm-size) are accepted identically by ``docker run``
    and ``container run``, so a single builder serves both backends. Returned as
    a list (no shell) — the backend prepends its CLI name.
    """
    conf_target = "/etc/postgresql/postgresql.conf"
    args = [
        "run",
        "-d",
        "--name",
        spec.container_name,
        "-p",
        f"{spec.host_port}:5432",
        "-v",
        f"{spec.volume_name}:{_DATA_MOUNT}",
        "--shm-size",
        spec.shm_size,
        "-e",
        f"POSTGRES_USER={spec.user}",
        "-e",
        f"POSTGRES_PASSWORD={spec.password}",
        "-e",
        f"POSTGRES_DB={spec.db_name}",
        # PGDATA must be a subdirectory of the mount — see _PGDATA comment above.
        "-e",
        f"PGDATA={_PGDATA}",
    ]
    if spec.conf_path:
        args += ["-v", f"{spec.conf_path}:{conf_target}"]
    args.append(spec.image)
    if spec.conf_path:
        # Mirror the compose 'command:' so postgres uses the mounted config.
        args += ["postgres", "-c", f"config_file={conf_target}"]
    return args


class ContainerBackend:
    """Common interface for a container runtime (Docker or Apple Container).

    Subclasses only differ in the CLI binary name and a few subcommand quirks
    (volume removal). All provisioning goes through the shared ``_postgres_run_args``
    builder so the two backends stay symmetric and the benchmark is fair.
    """

    name: str = ""  # human label, e.g. "Docker"
    cli: str = ""  # binary, e.g. "docker" / "container"

    def is_available(self) -> bool:
        """Return True if the runtime CLI exists and its daemon is reachable."""
        raise NotImplementedError

    def cli_installed(self) -> bool:
        """Return True if the runtime CLI binary is on PATH."""
        return command_exists(self.cli)

    def daemon_running(self) -> bool:
        """Return True if the runtime's daemon / API server answers."""
        raise NotImplementedError

    def ensure_runtime_ready(self) -> bool:
        """Verify the runtime can serve container commands; print concrete guidance if not.

        Backends may self-heal where that is safe (Apple Container: start the
        launchd API server). Returns False when the runtime stays unusable —
        callers should treat that as a failed service operation.
        """
        raise NotImplementedError

    def pull_image(self, image: str) -> None:
        """Pre-pull an image so a later run measures boot, not download. Best-effort."""
        raise NotImplementedError

    def run_postgres(self, spec: PostgresSpec) -> subprocess.CompletedProcess:
        """Start a detached PostgreSQL container from ``spec``."""
        return self._run(_postgres_run_args(spec), capture=True)

    def stop_postgres(self, container_name: str, remove: bool = True) -> None:
        """Stop (and by default remove) a container. Best-effort; errors ignored."""
        raise NotImplementedError

    def remove_volume(self, volume_name: str) -> None:
        """Remove a named volume. Best-effort; errors ignored."""
        raise NotImplementedError

    def stats(self, container_name: str) -> str | None:
        """Return a one-line resource-usage snapshot, or None if unsupported."""
        raise NotImplementedError

    # --- dev service lifecycle (the local PostgreSQL container) ---------------
    # version_cfg + env (loaded from the version's .env) fully describe the dev
    # service; each backend derives what it needs (compose dir vs run spec).

    def service_up(self, version_cfg: VersionConfigProtocol, env: dict[str, str]) -> int:
        """Start the dev PostgreSQL service. Returns a process-style return code."""
        raise NotImplementedError

    def service_down(self, version_cfg: VersionConfigProtocol, env: dict[str, str]) -> int:
        """Stop the dev PostgreSQL service (persistent data is kept)."""
        raise NotImplementedError

    def service_status(self, version_cfg: VersionConfigProtocol, env: dict[str, str]) -> int:
        """Show the dev service status."""
        raise NotImplementedError

    def service_logs(self, version_cfg: VersionConfigProtocol, env: dict[str, str], follow: bool, tail: int) -> int:
        """Show the dev service logs."""
        raise NotImplementedError

    def find_container_by_port(self, port: int) -> str | None:
        """Return the name of a running container publishing host ``port``, or None.

        Used by the psql/pg_dump exec fallback in ``odoodev.core.database`` to
        locate the PostgreSQL container when the host has no client tools.
        """
        raise NotImplementedError

    def _run(self, args: list[str], capture: bool = False) -> subprocess.CompletedProcess:
        """Invoke ``<cli> <args...>``."""
        return subprocess.run(
            [self.cli, *args],
            capture_output=capture,
            text=True,
        )


class DockerBackend(ContainerBackend):
    """Docker runtime (``docker run`` / ``docker volume`` / ``docker stats``)."""

    name = "Docker"
    cli = "docker"

    def is_available(self) -> bool:
        return self.cli_installed() and self.daemon_running()

    def daemon_running(self) -> bool:
        return _probe([self.cli, "info"])

    def ensure_runtime_ready(self) -> bool:
        from odoodev.output import print_error, print_info

        if not self.cli_installed():
            print_error("Docker CLI not found")
            print_info("Install Docker Desktop (macOS) / Docker Engine (Linux)")
            if apple_runtime_supported():
                print_info("Or switch runtime: odoodev config set container_runtime apple")
            return False
        if not self.daemon_running():
            print_error("Docker is installed but the daemon is not running")
            if is_macos():
                print_info("Start Docker Desktop: open -a Docker")
            else:
                print_info("Start the daemon: sudo systemctl start docker")
            return False
        return True

    def pull_image(self, image: str) -> None:
        self._run(["pull", image], capture=True)

    def stop_postgres(self, container_name: str, remove: bool = True) -> None:
        # 'rm -f' stops and removes a running container in one step.
        if remove:
            self._run(["rm", "-f", container_name], capture=True)
        else:
            self._run(["stop", container_name], capture=True)

    def remove_volume(self, volume_name: str) -> None:
        self._run(["volume", "rm", volume_name], capture=True)

    def stats(self, container_name: str) -> str | None:
        result = self._run(
            ["stats", "--no-stream", "--format", "{{.MemUsage}} / CPU {{.CPUPerc}}", container_name],
            capture=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return None

    def find_container_by_port(self, port: int) -> str | None:
        result = self._run(["ps", "--format", "{{.Names}}\t{{.Ports}}"], capture=True)
        if result.returncode != 0:
            return None
        needle = f":{port}->"
        for line in result.stdout.splitlines():
            name, _, ports = line.partition("\t")
            if needle in ports:
                return name.strip()
        return None

    # Docker keeps using docker-compose for the dev service — unchanged behaviour.
    def service_up(self, version_cfg: VersionConfigProtocol, env: dict[str, str]) -> int:
        if not self.ensure_runtime_ready():
            return 1
        from odoodev.core.docker_compose import compose_up

        return compose_up(version_cfg.paths.native_dir)

    def service_down(self, version_cfg: VersionConfigProtocol, env: dict[str, str]) -> int:
        from odoodev.core.docker_compose import compose_down

        return compose_down(version_cfg.paths.native_dir)

    def service_status(self, version_cfg: VersionConfigProtocol, env: dict[str, str]) -> int:
        from odoodev.core.docker_compose import compose_ps

        return compose_ps(version_cfg.paths.native_dir)

    def service_logs(self, version_cfg: VersionConfigProtocol, env: dict[str, str], follow: bool, tail: int) -> int:
        from odoodev.core.docker_compose import compose_logs

        return compose_logs(version_cfg.paths.native_dir, follow=follow, tail=tail)


class AppleContainerBackend(ContainerBackend):
    """Apple Container runtime (``container run`` / ``container volume`` ...).

    Apple Container is only meaningful on Apple silicon + macOS 26. ``is_available``
    probes both the CLI presence and a live ``container system status``.
    """

    name = "Apple Container"
    cli = "container"

    def is_available(self) -> bool:
        if not self.cli_installed():
            return False
        if self.daemon_running():
            return True
        # Fall back to a liveness probe that also starts the API server implicitly.
        return _probe([self.cli, "ls"])

    def daemon_running(self) -> bool:
        # 'system status' reflects whether container-apiserver is running.
        return _probe([self.cli, "system", "status"])

    def start_daemon(self) -> bool:
        """Start the container-apiserver launchd agent (``container system start``)."""
        self._run(["system", "start"], capture=True)
        return self.daemon_running()

    def ensure_runtime_ready(self) -> bool:
        from odoodev.output import print_error, print_info, print_success

        if not self.cli_installed():
            print_error("Apple Container CLI ('container') not found")
            print_info("Install: brew install container (requires macOS 26 on Apple silicon)")
            print_info("Or switch runtime: odoodev config set container_runtime docker")
            return False
        if not self.daemon_running():
            print_info("Apple Container API server is not running — starting it (container system start)...")
            if not self.start_daemon():
                print_error("Could not start the Apple Container API server")
                print_info("Start it manually: container system start")
                return False
            print_success("Apple Container API server started")
        return True

    def pull_image(self, image: str) -> None:
        self._run(["image", "pull", image], capture=True)

    def stop_postgres(self, container_name: str, remove: bool = True) -> None:
        self._run(["stop", container_name], capture=True)
        if remove:
            # Apple Container uses 'delete' (alias 'rm') to remove a stopped container.
            result = self._run(["delete", container_name], capture=True)
            if result.returncode != 0:
                self._run(["rm", container_name], capture=True)

    def remove_volume(self, volume_name: str) -> None:
        result = self._run(["volume", "delete", volume_name], capture=True)
        if result.returncode != 0:
            self._run(["volume", "rm", volume_name], capture=True)

    def stats(self, container_name: str) -> str | None:
        # 'container stats' is not guaranteed across releases — best-effort only.
        result = self._run(["stats", "--no-stream", container_name], capture=True)
        if result.returncode == 0 and result.stdout.strip():
            return _parse_apple_stats(result.stdout)
        return None

    def find_container_by_port(self, port: int) -> str | None:
        # Apple Container's port-listing format is not parsed yet — the exec
        # fallback for psql/pg_dump is Docker-only for now. On an Apple
        # Container host, install the client tools instead (brew install libpq).
        return None

    # Apple Container has no compose — provision the dev postgres as a single
    # `container run`, mirroring the compose service (name/volume/port/conf), with
    # the persistent named volume kept across down/up (compose-like semantics).
    def service_up(self, version_cfg: VersionConfigProtocol, env: dict[str, str]) -> int:
        if not self.ensure_runtime_ready():
            return 1
        spec = build_dev_spec(version_cfg, env)
        # A stopped container with the same name would block 'run'; remove it
        # first (the named volume — i.e. the data — persists independently).
        self.stop_postgres(spec.container_name, remove=True)
        result = self.run_postgres(spec)
        return result.returncode

    def service_down(self, version_cfg: VersionConfigProtocol, env: dict[str, str]) -> int:
        spec = build_dev_spec(version_cfg, env)
        # Stop + remove the container but KEEP the named volume (dev data).
        self.stop_postgres(spec.container_name, remove=True)
        return 0

    def service_status(self, version_cfg: VersionConfigProtocol, env: dict[str, str]) -> int:
        return self._run(["ls", "-a"]).returncode

    def service_logs(self, version_cfg: VersionConfigProtocol, env: dict[str, str], follow: bool, tail: int) -> int:
        spec = build_dev_spec(version_cfg, env)
        args = ["logs"]
        if follow:
            args.append("--follow")
        args.append(spec.container_name)
        return self._run(args).returncode


def _parse_apple_stats(raw: str) -> str | None:
    """Compact ``container stats`` output into a one-line 'mem / CPU x%' string.

    Apple's ``container stats`` prints a multi-column table (Container ID, Cpu %,
    Memory Usage, ...) which is unreadable in a comparison cell. Extract just the
    memory-usage pair and CPU percentage via regex; return None if neither parses.
    """
    mem = re.search(r"\d+(?:\.\d+)?\s*[KMG]i?B\s*/\s*\d+(?:\.\d+)?\s*[KMG]i?B", raw)
    cpu = re.search(r"\d+(?:\.\d+)?%", raw)
    if not mem and not cpu:
        return None
    parts = []
    if mem:
        parts.append(mem.group(0))
    if cpu:
        parts.append(f"CPU {cpu.group(0)}")
    return " / ".join(parts)


def apple_runtime_supported() -> bool:
    """Whether Apple Container is a viable runtime choice on this OS (macOS only)."""
    return is_macos()


def diagnose_runtime(version: str | None = None, runtime: str | None = None) -> RuntimeDiagnosis:
    """Probe the configured container runtime and derive actionable hints.

    Pure inspection — never starts anything and never raises for an unusable
    runtime, so error paths (e.g. "PostgreSQL not accessible") can surface a
    runtime-specific diagnosis instead of a blanket Docker reference. Every
    not-ready state still ends with the ``odoodev docker up`` hint because that
    command dispatches to the configured runtime.
    """
    rt = resolve_runtime(runtime)
    up_cmd = f"odoodev docker up {version}" if version else "odoodev docker up <version>"

    if rt == RUNTIME_APPLE and not apple_runtime_supported():
        return RuntimeDiagnosis(
            runtime=rt,
            backend_name="Apple Container",
            cli_installed=False,
            daemon_running=False,
            problem=f"Apple Container is configured but only supported on macOS (detected: {detect_os()})",
            hints=(
                "Switch runtime: odoodev config set container_runtime docker",
                f"Then start PostgreSQL: {up_cmd}",
            ),
        )

    backend = get_backend(rt)
    cli = backend.cli_installed()
    daemon = backend.daemon_running() if cli else False

    problem: str | None = None
    hints: tuple[str, ...]
    if rt == RUNTIME_APPLE:
        if not cli:
            problem = "Apple Container CLI ('container') not found"
            hints = (
                "Install: brew install container (requires macOS 26 on Apple silicon)",
                "Or switch runtime: odoodev config set container_runtime docker",
                f"Then start PostgreSQL: {up_cmd}",
            )
        elif not daemon:
            problem = "Apple Container API server (container-apiserver) is not running"
            hints = (
                "Start it: container system start",
                f"Then start PostgreSQL: {up_cmd}",
            )
        else:
            hints = (
                f"Start PostgreSQL (Apple Container): {up_cmd}",
                "Inspect containers: container ls -a",
            )
    else:
        if not cli:
            problem = "Docker CLI not found"
            install_hints = ["Install Docker Desktop (macOS) / Docker Engine (Linux)"]
            if apple_runtime_supported():
                install_hints.append("Or switch runtime: odoodev config set container_runtime apple")
            hints = (*install_hints, f"Then start PostgreSQL: {up_cmd}")
        elif not daemon:
            problem = "Docker is installed but the daemon is not running"
            if is_macos():
                daemon_hint = "Start Docker Desktop: open -a Docker"
            else:
                daemon_hint = "Start it: sudo systemctl start docker"
            hints = (daemon_hint, f"Then start PostgreSQL: {up_cmd}")
        else:
            hints = (f"Start PostgreSQL (Docker): {up_cmd}",)

    return RuntimeDiagnosis(
        runtime=rt,
        backend_name=backend.name,
        cli_installed=cli,
        daemon_running=daemon,
        problem=problem,
        hints=hints,
    )


def get_backend(runtime: str) -> ContainerBackend:
    """Return the backend for a runtime identifier.

    Args:
        runtime: One of ``"docker"`` / ``"apple"``.

    Raises:
        SystemExit: If the Apple runtime is requested on a non-macOS host.
        ValueError: If the runtime is unknown.
    """
    if runtime == RUNTIME_DOCKER:
        return DockerBackend()
    if runtime == RUNTIME_APPLE:
        if not apple_runtime_supported():
            from odoodev.output import print_error, print_info

            print_error(f"Apple Container is only supported on macOS (detected: {detect_os()}).")
            print_info("Use --runtime docker, or: odoodev config set container_runtime docker")
            raise SystemExit(1)
        return AppleContainerBackend()
    raise ValueError(f"Unknown container runtime '{runtime}'. Valid: {', '.join(VALID_RUNTIMES)}")


def resolve_runtime(override: str | None = None) -> str:
    """Resolve the active runtime: explicit override > global config default.

    Raises:
        ValueError: If an explicit override is not a valid runtime.
    """
    if override:
        if override not in VALID_RUNTIMES:
            raise ValueError(f"Unknown container runtime '{override}'. Valid: {', '.join(VALID_RUNTIMES)}")
        return override
    from odoodev.core.global_config import load_global_config

    return load_global_config().container_runtime


def get_active_backend(override: str | None = None) -> ContainerBackend:
    """Return the backend for the active runtime (override or configured default)."""
    return get_backend(resolve_runtime(override))


def read_env_file(native_dir: str) -> dict[str, str]:
    """Parse a version's ``.env`` into a dict (KEY=VALUE), expanding ``$USER``.

    Returns an empty dict if the file is absent. Used to derive the dev service
    spec for non-compose runtimes (Docker Compose reads ``.env`` itself).
    """
    env_file = os.path.join(native_dir, ".env")
    values: dict[str, str] = {}
    if not os.path.isfile(env_file):
        return values
    user = os.environ.get("USER", "odoo")
    with open(env_file, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            value = value.replace("${USER}", user).replace("$USER", user)
            values[key.strip()] = value
    return values


def build_dev_spec(version_cfg: VersionConfigProtocol, env: dict[str, str]) -> PostgresSpec:
    """Build the dev PostgreSQL spec, mirroring the docker-compose service.

    Values come from the version's ``.env`` (when present) with config/registry
    fallbacks, so a non-compose runtime provisions an equivalent container:
    same name, named volume, published port, credentials and postgresql.conf.
    """
    from odoodev.core.global_config import load_global_config

    cfg = load_global_config()
    version = version_cfg.version
    user = env.get("DEV_USER") or detect_user()
    pg_version = env.get("POSTGRES_VERSION") or version_cfg.postgres
    host_port = int(env.get("DB_PORT") or version_cfg.ports.db)
    native_dir = version_cfg.paths.native_dir

    conf = os.path.join(native_dir, "postgresql.conf")
    conf_path = conf if os.path.isfile(conf) else None

    return PostgresSpec(
        image=f"postgres:{pg_version}",
        container_name=f"{user}-dev-db-{version}-native",
        volume_name=f"{user}-vol-dev-db-{version}-native",
        host_port=host_port,
        user=env.get("PGUSER") or cfg.database.user,
        password=env.get("PGPASSWORD") or cfg.database.password,
        db_name="postgres",
        conf_path=conf_path,
    )
