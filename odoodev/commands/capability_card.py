"""Self-serve capability card command."""

from __future__ import annotations

import re
from pathlib import Path

import click

from odoodev import __version__

_VERSION_LINE_RE = re.compile(r"(\*\*Version:\*\*\s*)\d+\.\d+\.\d+")


def _find_card() -> Path | None:
    """Locate the capability card: bundled package data first, repo checkout as fallback."""
    package_dir = Path(__file__).parent.parent
    candidates = [
        package_dir / "data" / "AGENT.md",  # bundled in the wheel (force-include)
        package_dir.parent / "usage" / "AGENT.md",  # editable install / repo checkout
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


@click.command("capability-card")
def capability_card() -> None:
    """Print the agent capability card (usage/AGENT.md) for LLM/agent consumption."""
    card_path = _find_card()
    if card_path is None:
        # Raw click.echo instead of Rich: the consumer is a machine and the
        # card must arrive as unmodified Markdown on stdout.
        click.echo("Error: capability card not found (neither bundled nor in the repo checkout).", err=True)
        raise SystemExit(1)

    content = card_path.read_text(encoding="utf-8")
    content = _VERSION_LINE_RE.sub(rf"\g<1>{__version__}", content, count=1)
    click.echo(content)
