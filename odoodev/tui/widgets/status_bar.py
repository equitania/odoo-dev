"""Server status bar widget showing running state, version, port, and uptime."""

from __future__ import annotations

from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class StatusBar(Widget):
    """Displays Odoo server status in a compact bar.

    Shows: running state, version, port, database, and uptime.
    """

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
    }
    StatusBar .status-running {
        color: green;
    }
    StatusBar .status-stopped {
        color: red;
    }
    StatusBar .status-starting {
        color: yellow;
    }
    """

    server_state: reactive[str] = reactive("stopped")
    uptime_seconds: reactive[float] = reactive(0.0)
    version: reactive[str] = reactive("")
    port: reactive[int] = reactive(0)
    db_name: reactive[str] = reactive("")

    def compose(self):
        """Create the status display."""
        yield Static(id="status-text")

    def _format_uptime(self) -> str:
        """Format uptime as HH:MM:SS."""
        total = int(self.uptime_seconds)
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def _render_status(self) -> str:
        """Build the status bar text."""
        if self.server_state == "running":
            state = "[green]Running[/green]"
        elif self.server_state == "starting":
            state = "[yellow]Starting[/yellow]"
        else:
            state = "[red]Stopped[/red]"

        parts = [state]
        if self.version:
            parts.append(f"v{self.version}")
        if self.port:
            parts.append(f":{self.port}")
        if self.db_name:
            parts.append(f"DB: {self.db_name}")
        if self.server_state == "running":
            parts.append(f"Up {self._format_uptime()}")

        return " | ".join(parts)

    def watch_server_state(self) -> None:
        """Update display on state change."""
        self._update_display()

    def watch_uptime_seconds(self) -> None:
        """Update display on uptime change."""
        self._update_display()

    def _update_display(self) -> None:
        """Re-render the status bar text."""
        try:
            label = self.query_one("#status-text", Static)
            label.update(self._render_status())
        except Exception:  # noqa: S110 — widget may not be mounted yet during startup
            pass
