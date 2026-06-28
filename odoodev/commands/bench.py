"""odoodev bench - Compare PostgreSQL performance: Docker vs Apple Container.

Phase-1 benchmark gate for adopting Apple's ``container`` as a Docker alternative.
Provisions an *isolated* PostgreSQL container (dedicated name/volume/port — your
dev databases are never touched) under each available runtime and measures:

* cold start  — time from ``run`` to the server accepting queries
* TPS         — transaction throughput via ``pgbench`` (psql fallback if absent)
* bulk I/O    — timed bulk INSERT + index build (storage-layer indicator)
* idle usage  — best-effort memory/CPU snapshot

Both runtimes use the raw ``run`` path with identical flags, so the comparison
isolates the runtime/storage layer. The result is a side-by-side table plus a
suggested default — no configuration is changed (that is Phase 2).
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time

import click
from rich.table import Table

from odoodev.cli import resolve_version
from odoodev.core.container_backend import (
    RUNTIME_APPLE,
    RUNTIME_DOCKER,
    ContainerBackend,
    PostgresSpec,
    get_backend,
)
from odoodev.core.environment import detect_os, find_executable
from odoodev.core.global_config import load_global_config
from odoodev.core.prerequisites import check_apple_container, check_docker
from odoodev.core.version_registry import get_version
from odoodev.output import console, print_error, print_header, print_info, print_success, print_warning

DEFAULT_BENCH_PORT = 55432
DEFAULT_DURATION = 15  # pgbench run seconds
DEFAULT_SCALE = 10  # pgbench scale factor (~150 MB)
READY_TIMEOUT = 90  # seconds to wait for postgres to accept queries
FALLBACK_TX = 2000  # transactions for the psql TPS fallback
BENCH_DB = "odoodev_bench"
BENCH_HOST = "localhost"

# Metric direction: True = higher is better, False = lower is better.
_METRIC_HIGHER_BETTER = {"cold_start_s": False, "tps": True, "io_s": False}


def _pg_extra_paths() -> list[str]:
    """macOS Homebrew locations for PostgreSQL client tools (mirrors check_pg_tools)."""
    if detect_os() == "macos":
        return [
            "/opt/homebrew/opt/libpq/bin",
            "/usr/local/opt/libpq/bin",
            "/opt/homebrew/opt/postgresql@16/bin",
        ]
    return []


def _find_pg_binary(name: str) -> str | None:
    """Locate a PostgreSQL client binary (psql, pgbench) on PATH or Homebrew dirs."""
    return find_executable(name, _pg_extra_paths())


def _bench_env(password: str) -> dict[str, str]:
    """Client environment with an explicit PGPASSWORD for the bench container.

    Deliberately does NOT consult ``.pgpass`` — a stray entry could shadow the
    isolated bench credentials and break authentication.
    """
    env = os.environ.copy()
    env["PGPASSWORD"] = password
    return env


def _parse_pgbench_tps(stdout: str) -> float | None:
    """Extract the TPS figure from pgbench output.

    pgbench prints one or two ``tps = <n> (...)`` lines; the first is returned.
    """
    match = re.search(r"tps\s*=\s*([\d.]+)", stdout)
    return float(match.group(1)) if match else None


def _wait_until_ready(psql: str, port: int, user: str, password: str) -> float | None:
    """Poll ``SELECT 1`` until the server answers. Returns elapsed seconds or None.

    Timing starts when this is called (the caller records t0 right before
    ``run_postgres``), so the returned value is the full cold-start duration.
    """
    env = _bench_env(password)
    cmd = [psql, "-U", user, "-h", BENCH_HOST, "-p", str(port), "-d", BENCH_DB, "-tAc", "SELECT 1"]
    deadline = time.perf_counter() + READY_TIMEOUT
    start = time.perf_counter()
    while time.perf_counter() < deadline:
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.returncode == 0 and result.stdout.strip() == "1":
            return time.perf_counter() - start
        time.sleep(0.25)
    return None


def _measure_tps(
    pgbench: str | None, psql: str, port: int, user: str, password: str, duration: int, scale: int
) -> tuple[float | None, str]:
    """Measure transaction throughput. Returns (tps, method-label)."""
    env = _bench_env(password)
    base = ["-U", user, "-h", BENCH_HOST, "-p", str(port)]

    if pgbench:
        init = subprocess.run(
            [pgbench, "-i", "-q", "-s", str(scale), *base, BENCH_DB], capture_output=True, text=True, env=env
        )
        if init.returncode == 0:
            run = subprocess.run(
                [pgbench, "-T", str(duration), *base, BENCH_DB], capture_output=True, text=True, env=env
            )
            tps = _parse_pgbench_tps(run.stdout)
            if tps is not None:
                return tps, "pgbench"
        print_warning("pgbench run failed — falling back to psql timing")

    # Fallback: N single-row UPDATEs (one implicit tx each → N WAL flushes).
    setup = (
        "DROP TABLE IF EXISTS bench_tps; "
        "CREATE TABLE bench_tps(id int primary key, n int); "
        "INSERT INTO bench_tps VALUES (1, 0);"
    )
    subprocess.run(
        [psql, "-U", user, "-h", BENCH_HOST, "-p", str(port), "-d", BENCH_DB, "-q", "-c", setup],
        capture_output=True,
        text=True,
        env=env,
    )
    script = "\n".join("UPDATE bench_tps SET n = n + 1 WHERE id = 1;" for _ in range(FALLBACK_TX))
    with tempfile.NamedTemporaryFile("w", suffix=".sql", delete=False) as fh:
        fh.write(script)
        sql_path = fh.name
    try:
        t0 = time.perf_counter()
        result = subprocess.run(
            [psql, "-U", user, "-h", BENCH_HOST, "-p", str(port), "-d", BENCH_DB, "-q", "-f", sql_path],
            capture_output=True,
            text=True,
            env=env,
        )
        elapsed = time.perf_counter() - t0
    finally:
        os.unlink(sql_path)
    if result.returncode == 0 and elapsed > 0:
        return FALLBACK_TX / elapsed, "psql fallback"
    return None, "n/a"


def _measure_bulk_io(psql: str, port: int, user: str, password: str) -> float | None:
    """Time a bulk INSERT + index build as a storage-layer indicator (seconds)."""
    env = _bench_env(password)
    sql = (
        "DROP TABLE IF EXISTS bench_io; "
        "CREATE TABLE bench_io(id serial primary key, payload text); "
        "INSERT INTO bench_io(payload) SELECT md5(g::text) FROM generate_series(1, 300000) g; "
        "CREATE INDEX bench_io_payload_idx ON bench_io(payload);"
    )
    cmd = [psql, "-U", user, "-h", BENCH_HOST, "-p", str(port), "-d", BENCH_DB, "-q", "-c", sql]
    t0 = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    elapsed = time.perf_counter() - t0
    return elapsed if result.returncode == 0 else None


def _cleanup(backend: ContainerBackend, container: str, volume: str) -> None:
    """Stop+remove the bench container and its volume (best-effort)."""
    backend.stop_postgres(container, remove=True)
    backend.remove_volume(volume)


def _benchmark_runtime(
    backend: ContainerBackend,
    image: str,
    port: int,
    user: str,
    password: str,
    psql: str,
    pgbench: str | None,
    duration: int,
    scale: int,
    keep: bool,
) -> dict:
    """Run the full benchmark for one runtime. Returns a metrics dict."""
    container = f"odoodev-bench-pg-{backend.cli}"
    volume = f"odoodev-bench-vol-{backend.cli}"
    spec = PostgresSpec(
        image=image,
        container_name=container,
        volume_name=volume,
        host_port=port,
        user=user,
        password=password,
        db_name=BENCH_DB,
    )

    # Clean slate from any previous aborted run.
    _cleanup(backend, container, volume)
    # Pre-pull so cold-start measures boot, not image download.
    print_info(f"[{backend.name}] pulling {image} (if needed)...")
    backend.pull_image(image)

    print_info(f"[{backend.name}] starting PostgreSQL and measuring cold start...")
    t0 = time.perf_counter()
    run = backend.run_postgres(spec)
    if run.returncode != 0:
        print_error(f"[{backend.name}] failed to start container: {run.stderr.strip()}")
        _cleanup(backend, container, volume)
        return {"error": "start failed"}

    cold_start = _wait_until_ready(psql, port, user, password)
    if cold_start is None:
        print_error(f"[{backend.name}] PostgreSQL did not become ready within {READY_TIMEOUT}s")
        if not keep:
            _cleanup(backend, container, volume)
        return {"error": "not ready"}
    # Account for the pre-ready container-start latency by re-anchoring on t0.
    cold_start = time.perf_counter() - t0
    print_success(f"[{backend.name}] ready in {cold_start:.2f}s")

    stats = backend.stats(container)

    print_info(f"[{backend.name}] measuring transaction throughput...")
    tps, tps_method = _measure_tps(pgbench, psql, port, user, password, duration, scale)

    print_info(f"[{backend.name}] measuring bulk I/O...")
    io_s = _measure_bulk_io(psql, port, user, password)

    if keep:
        print_warning(f"[{backend.name}] --keep: leaving container '{container}' running on port {port}")
    else:
        _cleanup(backend, container, volume)

    return {
        "cold_start_s": cold_start,
        "tps": tps,
        "tps_method": tps_method,
        "io_s": io_s,
        "stats": stats,
    }


def _fmt(value, suffix: str = "") -> str:
    """Format a metric value for the table ('-' when missing)."""
    if value is None:
        return "[dim]-[/dim]"
    if isinstance(value, float):
        return f"{value:,.2f}{suffix}"
    return f"{value}{suffix}"


def _winner(results: dict[str, dict], metric: str) -> str | None:
    """Return the runtime key that wins a metric, or None if not comparable."""
    higher = _METRIC_HIGHER_BETTER[metric]
    candidates = {rt: m[metric] for rt, m in results.items() if m.get(metric) is not None}
    if len(candidates) < 2:
        return None
    if higher:
        return max(candidates, key=lambda rt: candidates[rt])
    return min(candidates, key=lambda rt: candidates[rt])


def _recommend(results: dict[str, dict]) -> str | None:
    """Suggest a default runtime, prioritising TPS, then cold start."""
    comparable = {rt: m for rt, m in results.items() if "error" not in m}
    if len(comparable) < 2:
        return None
    for metric in ("tps", "cold_start_s"):
        win = _winner(comparable, metric)
        if win:
            return win
    return None


_LABELS = {RUNTIME_DOCKER: "Docker", RUNTIME_APPLE: "Apple Container"}


def _render(results: dict[str, dict]) -> None:
    """Render the comparison table and recommendation."""
    table = Table(title="PostgreSQL Runtime Benchmark", border_style="blue")
    table.add_column("Metric", style="bold")
    for rt in results:
        table.add_column(_LABELS[rt], justify="right")

    rows = [
        ("Cold start (lower=better)", "cold_start_s", "s"),
        ("TPS (higher=better)", "tps", ""),
        ("Bulk I/O (lower=better)", "io_s", "s"),
    ]
    for label, metric, suffix in rows:
        win = _winner(results, metric)
        cells = []
        for rt, m in results.items():
            text = _fmt(m.get(metric), suffix)
            if rt == win:
                text = f"[bold green]{text}[/bold green]"
            cells.append(text)
        table.add_row(label, *cells)

    # Auxiliary, non-scored rows.
    table.add_row("TPS method", *[f"[dim]{m.get('tps_method', '-')}[/dim]" for m in results.values()])
    table.add_row("Idle usage", *[_fmt(m.get("stats")) for m in results.values()])

    console.print(table)

    win = _recommend(results)
    if win:
        print_success(f"Suggested default runtime: {_LABELS[win]}")
        print_info(f"Phase 2 will enable: odoodev config set container_runtime {win}")
    else:
        print_info("Not enough comparable data for a recommendation.")


@click.command("bench")
@click.argument("version", required=False)
@click.option(
    "--runtime",
    type=click.Choice([RUNTIME_DOCKER, RUNTIME_APPLE, "both"]),
    default="both",
    help="Which runtime(s) to benchmark (default: both).",
)
@click.option("--duration", type=int, default=DEFAULT_DURATION, help="pgbench run duration in seconds.")
@click.option("--scale", type=int, default=DEFAULT_SCALE, help="pgbench scale factor.")
@click.option("--port", type=int, default=DEFAULT_BENCH_PORT, help="Host port for the isolated bench container.")
@click.option("--keep", is_flag=True, help="Leave the last bench container running (skip cleanup).")
@click.pass_context
def bench(
    ctx: click.Context,
    version: str | None,
    runtime: str,
    duration: int,
    scale: int,
    port: int,
    keep: bool,
) -> None:
    """Benchmark PostgreSQL under Docker vs Apple Container.

    Uses an isolated container/volume/port — your dev databases are untouched.
    """
    version = resolve_version(ctx, version)
    version_cfg = get_version(version)
    image = f"postgres:{version_cfg.postgres}"

    global_cfg = load_global_config()
    user = global_cfg.database.user
    password = global_cfg.database.password

    print_header(
        "odoodev bench",
        f"PostgreSQL {version_cfg.postgres} • isolated port {port} • db '{BENCH_DB}'",
    )

    psql = _find_pg_binary("psql")
    if not psql:
        print_error("psql not found — required to run the benchmark")
        print_info("Install PostgreSQL client tools (see: odoodev doctor)")
        raise SystemExit(1)
    pgbench = _find_pg_binary("pgbench")
    if not pgbench:
        print_warning("pgbench not found — using psql throughput fallback (less standard)")

    # Decide which runtimes to test and verify availability.
    wanted = [RUNTIME_DOCKER, RUNTIME_APPLE] if runtime == "both" else [runtime]
    availability = {RUNTIME_DOCKER: check_docker, RUNTIME_APPLE: check_apple_container}
    active = [rt for rt in wanted if availability[rt]()]

    skipped = [rt for rt in wanted if rt not in active]
    for rt in skipped:
        print_warning(f"Skipping {_LABELS[rt]} — runtime not available")

    if not active:
        print_error("No requested runtime is available — nothing to benchmark")
        raise SystemExit(1)

    results: dict[str, dict] = {}
    for rt in active:
        backend = get_backend(rt)
        results[rt] = _benchmark_runtime(backend, image, port, user, password, psql, pgbench, duration, scale, keep)

    _render(results)
