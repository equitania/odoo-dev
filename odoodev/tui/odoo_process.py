"""Subprocess wrapper for Odoo server with process group management.

Uses os.setsid() to isolate the Odoo process tree in its own process group,
enabling reliable termination of the entire tree (main server + workers).
"""

from __future__ import annotations

import os
import queue
import signal
import subprocess
import threading
import time


class OdooProcess:
    """Manages an Odoo server subprocess with process group isolation.

    The Odoo process runs in its own session (via os.setsid), so Ctrl+C
    in the parent TUI does not propagate directly. Instead, the TUI calls
    stop() which sends SIGTERM to the entire process group.

    Stdout and stderr are read by daemon threads into a thread-safe queue,
    allowing the TUI to poll for new lines without blocking.
    """

    def __init__(self, cmd: list[str], env: dict[str, str], cwd: str) -> None:
        self._cmd = list(cmd)
        self._base_cmd = list(cmd)
        self._env = dict(env)
        self._cwd = cwd
        self._process: subprocess.Popen | None = None
        self._output_queue: queue.Queue[str] = queue.Queue(maxsize=50_000)
        self._start_time: float = 0.0
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the Odoo server subprocess in a new process group."""
        if self._process is not None and self._process.poll() is None:
            return  # Already running

        self._output_queue = queue.Queue(maxsize=50_000)
        self._process = subprocess.Popen(
            self._cmd,
            env=self._env,
            cwd=self._cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            preexec_fn=os.setsid,
        )
        self._start_time = time.monotonic()

        # Daemon thread to read stdout line-by-line
        self._stdout_thread = threading.Thread(
            target=self._read_stream,
            args=(self._process.stdout,),
            daemon=True,
            name="odoo-stdout-reader",
        )
        self._stdout_thread.start()

    def _read_stream(self, stream) -> None:  # noqa: ANN001
        """Read lines from a stream and put them into the output queue."""
        try:
            for line in iter(stream.readline, ""):
                try:
                    self._output_queue.put_nowait(line)
                except queue.Full:
                    # Drop oldest line to make room
                    try:
                        self._output_queue.get_nowait()
                    except queue.Empty:
                        pass
                    self._output_queue.put_nowait(line)
            stream.close()
        except (ValueError, OSError):
            # Stream closed — process is shutting down
            pass

    def stop(self, timeout: int = 5) -> bool:
        """Stop the Odoo process group: SIGTERM -> wait -> SIGKILL.

        Args:
            timeout: Seconds to wait after SIGTERM before escalating to SIGKILL.

        Returns:
            True if the process was stopped successfully.
        """
        if self._process is None:
            return True

        proc = self._process
        if proc.poll() is not None:
            self._process = None
            return True

        pgid = os.getpgid(proc.pid)

        # Phase 1: SIGTERM to process group
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            self._process = None
            return True

        # Wait for graceful shutdown
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                self._process = None
                return True
            time.sleep(0.2)

        # Phase 2: SIGKILL to process group
        try:
            os.killpg(pgid, signal.SIGKILL)
            proc.wait(timeout=2)
        except (ProcessLookupError, PermissionError, subprocess.TimeoutExpired):
            pass

        self._process = None
        return True

    def restart(self, extra_args: list[str] | None = None) -> None:
        """Stop the current process and start a new one.

        Args:
            extra_args: Additional arguments to append (e.g. ["-u", "module"]).
        """
        self.stop()
        if extra_args:
            self._cmd = self._base_cmd + extra_args
        else:
            self._cmd = list(self._base_cmd)
        self.start()

    @property
    def is_running(self) -> bool:
        """Check if the Odoo process is currently running."""
        if self._process is None:
            return False
        return self._process.poll() is None

    @property
    def pid(self) -> int | None:
        """Return the PID of the running Odoo process, or None."""
        if self._process is not None and self._process.poll() is None:
            return self._process.pid
        return None

    @property
    def return_code(self) -> int | None:
        """Return the exit code if the process has terminated."""
        if self._process is not None:
            return self._process.poll()
        return None

    @property
    def uptime(self) -> float:
        """Return seconds since the process was started. 0.0 if not running."""
        if not self.is_running:
            return 0.0
        return time.monotonic() - self._start_time

    def read_lines(self) -> list[str]:
        """Drain all available lines from the output queue.

        Returns:
            List of raw log lines (may be empty).
        """
        lines: list[str] = []
        while True:
            try:
                lines.append(self._output_queue.get_nowait())
            except queue.Empty:
                break
        return lines
