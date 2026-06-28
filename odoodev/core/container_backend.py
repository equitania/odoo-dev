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

import re
import subprocess
from dataclasses import dataclass

from odoodev.core.environment import command_exists

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


def _postgres_run_args(spec: PostgresSpec) -> list[str]:
    """Build the runtime-agnostic ``run`` arguments for a PostgreSQL container.

    The flags (-d/-p/-v/-e/--shm-size) are accepted identically by ``docker run``
    and ``container run``, so a single builder serves both backends. Returned as
    a list (no shell) — the backend prepends its CLI name.
    """
    return [
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
        spec.image,
    ]


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
        if not command_exists("docker"):
            return False
        result = subprocess.run(["docker", "info"], capture_output=True, text=True)
        return result.returncode == 0

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


class AppleContainerBackend(ContainerBackend):
    """Apple Container runtime (``container run`` / ``container volume`` ...).

    Apple Container is only meaningful on Apple silicon + macOS 26. ``is_available``
    probes both the CLI presence and a live ``container system status``.
    """

    name = "Apple Container"
    cli = "container"

    def is_available(self) -> bool:
        if not command_exists("container"):
            return False
        # 'system status' reflects whether container-apiserver is running.
        result = subprocess.run(["container", "system", "status"], capture_output=True, text=True)
        if result.returncode == 0:
            return True
        # Fall back to a liveness probe that also starts the API server implicitly.
        result = subprocess.run(["container", "ls"], capture_output=True, text=True)
        return result.returncode == 0

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


def get_backend(runtime: str) -> ContainerBackend:
    """Return the backend for a runtime identifier.

    Args:
        runtime: One of ``"docker"`` / ``"apple"``.

    Raises:
        ValueError: If the runtime is unknown.
    """
    if runtime == RUNTIME_DOCKER:
        return DockerBackend()
    if runtime == RUNTIME_APPLE:
        return AppleContainerBackend()
    raise ValueError(f"Unknown container runtime '{runtime}'. Valid: {', '.join(VALID_RUNTIMES)}")
