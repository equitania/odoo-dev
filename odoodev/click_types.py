"""Custom Click parameter types for odoodev."""

from __future__ import annotations

import os
from typing import Any

import click


class ExpandedPath(click.Path):
    """A ``click.Path`` that expands a leading ``~`` to the user's home directory.

    Click's built-in ``Path`` does not expand ``~`` — the shell normally does it for
    unquoted arguments, but quoted or interactively entered values keep the literal
    tilde and then fail existence checks. This type handles both cases.
    """

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> Any:
        if isinstance(value, str):
            value = os.path.expanduser(value)
        return super().convert(value, param, ctx)
