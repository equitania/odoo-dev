"""Process discovery and management for odoodev."""

from __future__ import annotations

import os
import signal
import subprocess
import time


def find_odoo_process(port: int) -> list[int]:
    """Find PIDs of processes listening on the given port via lsof.

    Works on macOS and Linux.

    Args:
        port: TCP port number to search for.

    Returns:
        List of PIDs listening on the port (may be empty).
    """
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        pids = []
        for line in result.stdout.strip().splitlines():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
        return pids
    except FileNotFoundError:
        # lsof not available
        return []
    except Exception:
        return []


def _process_exists(pid: int) -> bool:
    """Check if a process with the given PID exists."""
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we lack permission to signal it
        return True


def stop_process(pid: int, timeout: int = 5, force: bool = False) -> bool:
    """Stop a process gracefully: SIGTERM → wait → SIGKILL.

    Args:
        pid: Process ID to stop.
        timeout: Seconds to wait after SIGTERM before sending SIGKILL.
        force: If True, send SIGKILL immediately without SIGTERM.

    Returns:
        True if the process was stopped, False if it did not exist or could not be stopped.
    """
    if not _process_exists(pid):
        return False

    try:
        if force:
            os.kill(pid, signal.SIGKILL)
        else:
            os.kill(pid, signal.SIGTERM)
            # Wait for graceful shutdown
            deadline = time.time() + timeout
            while time.time() < deadline:
                if not _process_exists(pid):
                    return True
                time.sleep(0.2)
            # Process still alive — force kill
            if _process_exists(pid):
                os.kill(pid, signal.SIGKILL)
                time.sleep(0.5)

        return not _process_exists(pid)

    except ProcessLookupError:
        return True  # Already gone
    except PermissionError:
        return False


def is_odoo_running(port: int) -> bool:
    """Check if an Odoo process is running on the given port.

    Args:
        port: TCP port to check.

    Returns:
        True if a process is listening on the port.
    """
    return bool(find_odoo_process(port))
