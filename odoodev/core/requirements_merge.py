"""Pure requirements parsing and merging — no filesystem, no console output.

The merge maps baseline entries against overlay entries and emits a file.
It deliberately does NOT resolve dependencies: uv does that, as it always has.
That is why this module needs no `packaging` dependency.
"""

from __future__ import annotations

import hashlib
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


LOCAL_MARK = "[local]"
ADDITIONS_HEADER = "# ── local additions ──────────────────────────────────────────"


@dataclass(frozen=True)
class MergeResult:
    """Outcome of merging a baseline with an overlay."""

    body: tuple[str, ...]
    replaced: tuple[tuple[Requirement, Requirement], ...]
    added: tuple[Requirement, ...]
    warnings: tuple[str, ...]


def _pin_value(specifier: str) -> str | None:
    """Return the pinned version for an '==' specifier, else None."""
    return specifier[2:].strip() if specifier.startswith("==") else None


def _version_tuple(value: str) -> tuple[int, ...] | None:
    """Best-effort numeric version tuple; None when not purely numeric."""
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError:
        return None


def _render_local(req: Requirement) -> str:
    """Render an overlay requirement with its provenance marker."""
    line = req.to_line()
    padding = " " * max(1, 30 - len(line))
    comment = f" {req.comment}" if req.comment else ""
    return f"{line}{padding}# {LOCAL_MARK}{comment}"


def _compare_warning(base: Requirement, local: Requirement) -> str | None:
    """Warn when an overlay pin holds a baseline bump back."""
    base_pin, local_pin = _pin_value(base.specifier), _pin_value(local.specifier)
    if not base_pin or not local_pin or base_pin == local_pin:
        return None
    base_tuple, local_tuple = _version_tuple(base_pin), _version_tuple(local_pin)
    if base_tuple is None or local_tuple is None:
        return f"{base.name}: overlay pin {local_pin} differs from base {base_pin}"
    if local_tuple < base_tuple:
        return f"{base.name}: overlay holds {local_pin} back (base: {base_pin})"
    return None


def _extras_warning(base: Requirement, local: Requirement) -> str | None:
    """Warn when an overlay entry silently drops the baseline's extras."""
    dropped = set(base.extras) - set(local.extras)
    if not dropped:
        return None
    return f"{base.name}: overlay drops baseline extras {sorted(dropped)}"


def merge_requirements(base_text: str, local_text: str) -> MergeResult:
    """Merge an overlay into a baseline, preserving baseline structure.

    Overlay entries replace their baseline counterpart in place; entries with
    no counterpart are appended in a dedicated block. Keeping the baseline's
    order and comment blocks is what makes the git diff of a baseline update
    readable — the comments are the actual knowledge in these files.
    """
    base_lines = parse_requirements(base_text)
    local_lines = parse_requirements(local_text)

    overlay: dict[tuple[str, str], Requirement] = {}
    for line in local_lines:
        if line.requirement is not None:
            overlay[line.requirement.merge_key] = line.requirement

    body: list[str] = []
    replaced: list[tuple[Requirement, Requirement]] = []
    warnings: list[str] = []
    consumed: set[tuple[str, str]] = set()

    for line in base_lines:
        base_req = line.requirement
        if base_req is None or base_req.merge_key not in overlay:
            body.append(line.raw)
            continue
        local_req = overlay[base_req.merge_key]
        consumed.add(base_req.merge_key)
        replaced.append((base_req, local_req))
        body.append(_render_local(local_req))
        for warning in (_compare_warning(base_req, local_req), _extras_warning(base_req, local_req)):
            if warning:
                warnings.append(warning)

    added = tuple(req for key, req in overlay.items() if key not in consumed)
    if added:
        if body and body[-1].strip():
            body.append("")
        body.append(ADDITIONS_HEADER)
        body.extend(_render_local(req) for req in added)

    return MergeResult(
        body=tuple(body),
        replaced=tuple(replaced),
        added=added,
        warnings=tuple(warnings),
    )


GENERATED_PREFIX = "# GENERATED by odoodev "
_BASE_HASH_RE = re.compile(r"^# base: v\S+ bundle sha256:(?P<hash>[0-9a-f]{64})", re.MULTILINE)


def sha256_text(text: str) -> str:
    """SHA256 of a text payload, UTF-8 encoded."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def is_generated(text: str) -> bool:
    """True when the text carries odoodev's generated-file header."""
    return text.lstrip().startswith(GENERATED_PREFIX)


def extract_base_hash(text: str) -> str | None:
    """Return the baseline hash recorded in a generated file's header."""
    match = _BASE_HASH_RE.search(text)
    return match.group("hash") if match else None


def render_requirements(
    *,
    version: str,
    odoodev_version: str,
    base_text: str,
    local_text: str,
) -> tuple[str, MergeResult]:
    """Merge baseline and overlay and render the effective requirements file.

    The header records both input hashes. The baseline hash is what `start`
    compares against the shipped bundle to decide whether to regenerate.
    """
    result = merge_requirements(base_text, local_text)
    header = [
        f"{GENERATED_PREFIX}{odoodev_version} — do not edit.",
        f"# base: v{version} bundle sha256:{sha256_text(base_text)}"
        f"  local: requirements.local.txt sha256:{sha256_text(local_text)}",
        f"# Edit requirements.local.txt instead, then: odoodev requirements sync {version}",
        "",
    ]
    body = "\n".join([*header, *result.body]).rstrip("\n") + "\n"
    return body, result
