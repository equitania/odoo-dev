"""Pure requirements parsing and merging — no filesystem, no console output.

The merge maps baseline entries against overlay entries and emits a file.
It deliberately does NOT resolve dependencies: uv does that, as it always has.
That is why this module needs no `packaging` dependency.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_NAME_RE = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?:\[(?P<extras>[^\]]*)\])?")


def canonical_name(name: str) -> str:
    """Normalise a distribution name per PEP 503."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _normalise_marker(marker: str) -> str:
    """Collapse whitespace and unify quote style so markers compare as strings."""
    return re.sub(r"\s+", " ", marker.strip().replace('"', "'"))


@dataclass(frozen=True)
class Requirement:
    """A single parsed requirement line."""

    name: str
    key: str
    extras: tuple[str, ...]
    specifier: str
    marker: str
    comment: str

    @property
    def merge_key(self) -> tuple[str, str]:
        """Identity for merging: name AND marker.

        v17 pins six packages twice, distinguished only by a python_version
        marker. Keying on the name alone would drop one line of each pair.
        """
        return (self.key, self.marker)

    def to_line(self) -> str:
        """Render back to a requirements.txt line (without trailing comment)."""
        extras = f"[{','.join(self.extras)}]" if self.extras else ""
        marker = f" ; {self.marker}" if self.marker else ""
        return f"{self.name}{extras}{self.specifier}{marker}"


@dataclass(frozen=True)
class Line:
    """One source line: either a requirement or verbatim passthrough."""

    raw: str
    requirement: Requirement | None


def _parse_line(raw: str) -> Line:
    stripped = raw.strip()
    if not stripped or stripped.startswith("#"):
        return Line(raw=raw, requirement=None)

    body, _, comment = stripped.partition("#")
    body = body.strip()
    comment = comment.strip()

    # Options, editables and URL requirements are carried through verbatim.
    if body.startswith("-") or "://" in body:
        return Line(raw=raw, requirement=None)

    spec_part, sep, marker_part = body.partition(";")
    marker = _normalise_marker(marker_part) if sep else ""

    spec_part = spec_part.strip()
    match = _NAME_RE.match(spec_part)
    if not match:
        return Line(raw=raw, requirement=None)

    name = match.group("name")
    extras_raw = match.group("extras") or ""
    extras = tuple(sorted(e.strip() for e in extras_raw.split(",") if e.strip()))
    specifier = spec_part[match.end() :].strip()

    return Line(
        raw=raw,
        requirement=Requirement(
            name=name,
            key=canonical_name(name),
            extras=extras,
            specifier=specifier,
            marker=marker,
            comment=comment,
        ),
    )


def parse_requirements(text: str) -> list[Line]:
    """Parse a requirements file into lines, preserving order and comments."""
    return [_parse_line(raw) for raw in text.splitlines()]
