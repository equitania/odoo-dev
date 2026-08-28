# Requirements Base/Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single hand-maintained `requirements.txt` per Odoo version with a wheel-shipped baseline plus a machine-local overlay, from which odoodev generates the effective file — so a baseline rollout across v16–v19 never overwrites local pins.

**Architecture:** Two new core modules. `core/requirements_merge.py` is pure: it parses requirement lines, maps baseline against overlay on the key `(PEP 503 name, marker)`, and renders a structure-preserving output file with a provenance header. `core/requirements_sync.py` owns the filesystem: paths, the overwrite guard, sync, and the three-way comparison against the installed venv. `commands/requirements.py` is I/O and prompts only. This mirrors the existing `playbook_schema.py` / `playbook_builder.py` vs. `playbook_cmd.py` split.

**Tech Stack:** Python 3.12+, Click, Rich, questionary, pytest + Click's `CliRunner`, `uv` for the actual dependency resolution. No new runtime dependency — in particular **not** `packaging`.

**Spec:** `docs/superpowers/specs/2026-08-28-requirements-overlay-design.md`

## Global Constraints

- Python 3.10+ syntax target, line length 120, ruff rules `E, W, F, I, B, UP, S`.
- Double quotes. Absolute imports only (`from odoodev.core.x import y`), never relative.
- Frozen dataclasses for all configuration and result objects.
- All terminal output goes through `odoodev/output.py` helpers (`print_success`, `print_error`, `print_warning`, `print_info`, `print_table`, `confirm`, `select`). Never a bare `print()`.
- **No new runtime dependency.** The merge maps and emits; it never resolves. Version comparison is best-effort and must degrade to a neutral message rather than raise.
- Merge key is `(canonical_name, marker)` — never the name alone. v17 declares six packages twice, distinguished only by a `python_version` marker.
- The parser must not assume `==`. v18 has 28 unpinned or range-pinned lines.
- Every task ends with a passing `pytest` run for its own tests plus `ruff check .` and `ruff format --check .`.
- Commit prefixes: `[ADD]` new features, `[CHG]` modifications, `[FIX]` bug fixes.

## File Structure

| File | Responsibility |
|---|---|
| `odoodev/core/requirements_merge.py` (new) | Pure: `Requirement`, `Line`, `parse_requirements`, `canonical_name`, `merge_requirements`, `render_requirements`, `sha256_text`, `extract_base_hash`, `is_generated`. No filesystem, no console. |
| `odoodev/core/requirements_sync.py` (new) | Filesystem: bundle/overlay/generated paths, the overwrite guard, `sync_version`, `ensure_generated_requirements`, `three_way_report`, `installed_packages`. |
| `odoodev/commands/requirements.py` (new) | Click group `requirements` with `sync`, `diff`, `adopt`. Prompts and Rich output only. |
| `odoodev/core/example_templates.py` (modify) | Drop `requirements.txt` from `_get_template_mapping()`; add `get_base_requirements_path()`. |
| `odoodev/commands/start.py` (modify, ~line 753) | Call `ensure_generated_requirements()` before the existing hash check. |
| `odoodev/commands/init_cmd.py` (modify, ~line 66) | Seed an empty overlay and run one sync on a fresh environment. |
| `odoodev/cli.py` (modify) | Register the `requirements` group. |
| `odoodev/data/examples/vXX/requirements.base.txt` (rename + curate) | The baseline, re-curated from the real files. |
| `tests/test_requirements_merge.py` (new) | Pure merge/parse/render tests incl. the v17 doubles regression. |
| `tests/test_requirements_sync.py` (new) | Filesystem layer: guard, sync, ensure, three-way. |
| `tests/test_requirements_cmd.py` (new) | `CliRunner` level: `diff --json`, `sync --check` exit codes, `sync --all`, `adopt`. |

---

### Task 1: Requirement parser

**Files:**
- Create: `odoodev/core/requirements_merge.py`
- Test: `tests/test_requirements_merge.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `canonical_name(name: str) -> str`; frozen dataclass `Requirement(name: str, key: str, extras: tuple[str, ...], specifier: str, marker: str, comment: str)` with property `merge_key -> tuple[str, str]` and method `to_line() -> str`; frozen dataclass `Line(raw: str, requirement: Requirement | None)`; `parse_requirements(text: str) -> list[Line]`.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the pure requirements merge core."""

from odoodev.core.requirements_merge import Requirement, canonical_name, parse_requirements


def test_canonical_name_normalises_case_and_separators():
    assert canonical_name("Werkzeug") == "werkzeug"
    assert canonical_name("psycopg2_binary") == "psycopg2-binary"
    assert canonical_name("psycopg2-binary") == "psycopg2-binary"
    assert canonical_name("zope.interface") == "zope-interface"


def test_parse_simple_pin():
    lines = parse_requirements("Werkzeug==3.0.6\n")
    assert len(lines) == 1
    req = lines[0].requirement
    assert req == Requirement(
        name="Werkzeug", key="werkzeug", extras=(), specifier="==3.0.6", marker="", comment=""
    )


def test_parse_keeps_trailing_comment_and_marker():
    lines = parse_requirements("gevent==24.11.1 ; sys_platform != 'win32'  # (Trixie)\n")
    req = lines[0].requirement
    assert req.specifier == "==24.11.1"
    assert req.marker == "sys_platform != 'win32'"
    assert req.comment == "(Trixie)"


def test_parse_normalises_marker_quotes_and_whitespace():
    a = parse_requirements('Babel==2.17.0 ; python_version >= "3.13"\n')[0].requirement
    b = parse_requirements("Babel==2.17.0 ;python_version    >=    '3.13'\n")[0].requirement
    assert a.marker == b.marker == "python_version >= '3.13'"


def test_parse_handles_unpinned_and_range_pins():
    lines = parse_requirements("pytz\nPyYAML>=6.0.1,<7.0.0\n")
    assert lines[0].requirement.specifier == ""
    assert lines[1].requirement.specifier == ">=6.0.1,<7.0.0"


def test_parse_extracts_extras_sorted():
    req = parse_requirements("eq-chatbot-core[rag,security,docs]>=3.0.0\n")[0].requirement
    assert req.extras == ("docs", "rag", "security")
    assert req.specifier == ">=3.0.0"


def test_comment_and_blank_lines_carry_no_requirement():
    lines = parse_requirements("# a note\n\nBabel==2.16.0\n")
    assert lines[0].requirement is None
    assert lines[1].requirement is None
    assert lines[2].requirement is not None
    assert lines[0].raw == "# a note"


def test_passthrough_forms_are_not_keyed():
    lines = parse_requirements("-r other.txt\ngit+https://example.invalid/x.git#egg=x\n")
    assert all(line.requirement is None for line in lines)


def test_merge_key_pairs_name_and_marker():
    reqs = [line.requirement for line in parse_requirements(
        "Babel==2.10.3 ; python_version < '3.13'\nBabel==2.17.0 ; python_version >= '3.13'\n"
    )]
    assert reqs[0].merge_key != reqs[1].merge_key
    assert reqs[0].merge_key == ("babel", "python_version < '3.13'")


def test_to_line_round_trips():
    text = "eq-chatbot-core[docs,rag]>=3.0.0 ; python_version >= '3.13'"
    req = parse_requirements(text + "\n")[0].requirement
    assert req.to_line() == "eq-chatbot-core[docs,rag]>=3.0.0 ; python_version >= '3.13'"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_requirements_merge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'odoodev.core.requirements_merge'`

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_requirements_merge.py -v && ruff check odoodev/core/requirements_merge.py && ruff format --check odoodev/core/requirements_merge.py`
Expected: 9 passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add odoodev/core/requirements_merge.py tests/test_requirements_merge.py
git commit -m "[ADD] requirements parser: PEP 503 keys with marker awareness"
```

---

### Task 2: Merge with provenance and warnings

**Files:**
- Modify: `odoodev/core/requirements_merge.py`
- Test: `tests/test_requirements_merge.py`

**Interfaces:**
- Consumes: `parse_requirements`, `Requirement`, `Line` from Task 1.
- Produces: frozen dataclass `MergeResult(body: tuple[str, ...], replaced: tuple[tuple[Requirement, Requirement], ...], added: tuple[Requirement, ...], warnings: tuple[str, ...])`; `merge_requirements(base_text: str, local_text: str) -> MergeResult`. `body` holds the merged file lines WITHOUT the header — Task 3 adds that.

- [ ] **Step 1: Write the failing test**

```python
from odoodev.core.requirements_merge import merge_requirements

BASE = """# baseline
Babel==2.16.0
cryptography==46.0.7          # CVE-2026-39892
Werkzeug==3.1.3
eq-chatbot-core[rag,docs]>=3.0.0
"""


def test_overlay_replaces_in_place_and_keeps_order():
    result = merge_requirements(BASE, "Werkzeug==3.0.6  # MUST stay < 3.1\n")
    body = "\n".join(result.body)
    assert body.index("Babel") < body.index("Werkzeug") < body.index("eq-chatbot-core")
    assert "Werkzeug==3.0.6" in body
    assert "3.1.3" not in body
    assert "[local]" in body


def test_baseline_comments_survive():
    result = merge_requirements(BASE, "")
    body = "\n".join(result.body)
    assert "# baseline" in body
    assert "# CVE-2026-39892" in body


def test_overlay_only_entries_land_in_additions_block():
    result = merge_requirements(BASE, "msal==1.31.0  # v16-microsoft365\n")
    body = "\n".join(result.body)
    assert "local additions" in body
    assert body.index("eq-chatbot-core") < body.index("msal")
    assert [r.name for r in result.added] == ["msal"]


def test_marker_variants_are_replaced_independently():
    base = "Babel==2.10.3 ; python_version < '3.13'\nBabel==2.17.0 ; python_version >= '3.13'\n"
    result = merge_requirements(base, "Babel==2.18.0 ; python_version >= '3.13'\n")
    body = "\n".join(result.body)
    assert "Babel==2.10.3 ; python_version < '3.13'" in body
    assert "Babel==2.18.0 ; python_version >= '3.13'" in body
    assert "2.17.0" not in body
    assert result.added == ()


def test_held_back_bump_is_reported():
    result = merge_requirements(BASE, "Werkzeug==3.0.6\n")
    assert any("Werkzeug" in w and "3.0.6" in w and "3.1.3" in w for w in result.warnings)


def test_forward_pin_is_not_reported_as_held_back():
    result = merge_requirements(BASE, "Werkzeug==3.2.0\n")
    assert not any("holds" in w for w in result.warnings)


def test_unparseable_version_degrades_to_neutral_message():
    result = merge_requirements("foo==1.0.0\n", "foo==2.0.0rc1\n")
    assert any("differs" in w for w in result.warnings)
    assert not any("holds" in w for w in result.warnings)


def test_dropped_extras_are_reported():
    result = merge_requirements(BASE, "eq-chatbot-core>=3.1.0\n")
    assert any("extras" in w and "eq-chatbot-core" in w for w in result.warnings)


def test_replaced_pairs_expose_base_and_local():
    result = merge_requirements(BASE, "Werkzeug==3.0.6\n")
    base_req, local_req = result.replaced[0]
    assert base_req.specifier == "==3.1.3"
    assert local_req.specifier == "==3.0.6"


def test_empty_overlay_reproduces_baseline_body():
    result = merge_requirements(BASE, "")
    assert "\n".join(result.body).rstrip() == BASE.rstrip()
    assert result.replaced == ()
    assert result.added == ()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_requirements_merge.py -v`
Expected: FAIL — `ImportError: cannot import name 'merge_requirements'`

- [ ] **Step 3: Write minimal implementation**

Append to `odoodev/core/requirements_merge.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_requirements_merge.py -v && ruff check . && ruff format --check .`
Expected: 19 passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add odoodev/core/requirements_merge.py tests/test_requirements_merge.py
git commit -m "[ADD] requirements merge: in-place overlay with held-back and extras warnings"
```

---

### Task 3: Render with provenance header

**Files:**
- Modify: `odoodev/core/requirements_merge.py`
- Test: `tests/test_requirements_merge.py`

**Interfaces:**
- Consumes: `merge_requirements`, `MergeResult` from Task 2.
- Produces: `sha256_text(text: str) -> str` (64 hex chars); `render_requirements(*, version: str, odoodev_version: str, base_text: str, local_text: str) -> tuple[str, MergeResult]`; `is_generated(text: str) -> bool`; `extract_base_hash(text: str) -> str | None`.

Note: the spec illustrates the header hash abbreviated (`sha256:a3f1…`). The implementation writes the **full** 64-character digest so `extract_base_hash` is unambiguous.

- [ ] **Step 1: Write the failing test**

```python
from odoodev.core.requirements_merge import (
    extract_base_hash,
    is_generated,
    render_requirements,
    sha256_text,
)


def test_render_emits_header_with_both_hashes():
    base, local = "Babel==2.16.0\n", "msal==1.31.0\n"
    text, _ = render_requirements(version="16", odoodev_version="0.63.0", base_text=base, local_text=local)
    lines = text.splitlines()
    assert lines[0] == "# GENERATED by odoodev 0.63.0 — do not edit."
    assert sha256_text(base) in lines[1]
    assert sha256_text(local) in lines[1]
    assert "odoodev requirements sync 16" in lines[2]


def test_render_output_is_recognised_as_generated():
    text, _ = render_requirements(version="18", odoodev_version="0.63.0", base_text="a==1\n", local_text="")
    assert is_generated(text)


def test_hand_written_file_is_not_recognised_as_generated():
    assert not is_generated("Babel==2.16.0\n# just a file\n")


def test_extract_base_hash_round_trips():
    base = "Babel==2.16.0\n"
    text, _ = render_requirements(version="19", odoodev_version="0.63.0", base_text=base, local_text="")
    assert extract_base_hash(text) == sha256_text(base)


def test_extract_base_hash_returns_none_for_plain_file():
    assert extract_base_hash("Babel==2.16.0\n") is None


def test_render_returns_the_merge_result():
    _, result = render_requirements(
        version="16", odoodev_version="0.63.0", base_text="Werkzeug==3.1.3\n", local_text="Werkzeug==3.0.6\n"
    )
    assert result.warnings
    assert len(result.replaced) == 1


def test_render_ends_with_single_newline():
    text, _ = render_requirements(version="16", odoodev_version="0.63.0", base_text="a==1\n", local_text="")
    assert text.endswith("\n")
    assert not text.endswith("\n\n")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_requirements_merge.py -v`
Expected: FAIL — `ImportError: cannot import name 'render_requirements'`

- [ ] **Step 3: Write minimal implementation**

Add `import hashlib` at the top of `odoodev/core/requirements_merge.py`, then append:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_requirements_merge.py -v && ruff check . && ruff format --check .`
Expected: 26 passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add odoodev/core/requirements_merge.py tests/test_requirements_merge.py
git commit -m "[ADD] requirements render: provenance header with baseline hash"
```

---

### Task 4: Bundle rename and template mapping change

**Files:**
- Rename: `odoodev/data/examples/v16/requirements.txt` → `requirements.base.txt` (likewise v17, v18, v19)
- Modify: `odoodev/core/example_templates.py`
- Test: `tests/test_example_templates.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `get_base_requirements_path(version: str) -> Path` in `odoodev.core.example_templates`.

This is the task that removes the destructive overwrite. Today `init` offers *"Replace requirements.txt with bundled version?"* and `replace_example_template()` runs `shutil.copy2` over the local file. With `requirements.txt` gone from the mapping, that prompt can no longer target it.

- [ ] **Step 1: Write the failing test**

```python
from odoodev.core.example_templates import _get_template_mapping, get_base_requirements_path


def test_requirements_txt_is_no_longer_a_copyable_template(tmp_path):
    """The generated requirements.txt must never be replaced by a bundled copy."""
    from odoodev.core.version_registry import get_version

    cfg = get_version("18")
    mapping = _get_template_mapping("18", cfg)
    assert "requirements.txt" not in mapping
    assert "repos.yaml" in mapping
    assert "postgresql.conf" in mapping


def test_base_requirements_path_points_at_the_bundle():
    path = get_base_requirements_path("16")
    assert path.name == "requirements.base.txt"
    assert path.is_file()
    assert "Werkzeug" in path.read_text(encoding="utf-8")


def test_every_supported_version_ships_a_baseline():
    for version in ("16", "17", "18", "19"):
        assert get_base_requirements_path(version).is_file()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_example_templates.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_base_requirements_path'` and the mapping assertion fails

- [ ] **Step 3: Write minimal implementation**

Rename the four bundles:

```bash
for v in 16 17 18 19; do
  git mv "odoodev/data/examples/v$v/requirements.txt" "odoodev/data/examples/v$v/requirements.base.txt"
done
```

In `odoodev/core/example_templates.py`, delete the `requirements.txt` entry from `_get_template_mapping()`:

```python
    return {
        "repos.yaml": os.path.join(native_dir, "repos.yaml"),
        "postgresql.conf": os.path.join(native_dir, "postgresql.conf"),
        f"odoo{version}_template.conf": os.path.join(conf_dir, f"odoo{version}_template.conf"),
    }
```

And add:

```python
def get_base_requirements_path(version: str) -> Path:
    """Return the bundled baseline requirements for a version.

    Deliberately NOT part of _get_template_mapping(): the baseline is never
    copied into the project. odoodev generates requirements.txt from it plus
    the machine-local overlay instead.
    """
    return get_example_dir(version) / "requirements.base.txt"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_example_templates.py -v && ruff check . && ruff format --check .`
Expected: all passed. If a pre-existing test asserted `requirements.txt` in the mapping, update that test — the removal is the intended change.

- [ ] **Step 5: Commit**

```bash
git add odoodev/core/example_templates.py odoodev/data/examples tests/test_example_templates.py
git commit -m "[CHG] bundles: rename to requirements.base.txt, drop from copy mapping"
```

---

### Task 5: Filesystem layer — paths, guard, sync

**Files:**
- Create: `odoodev/core/requirements_sync.py`
- Test: `tests/test_requirements_sync.py`

**Interfaces:**
- Consumes: `render_requirements`, `sha256_text`, `extract_base_hash`, `is_generated`, `MergeResult` (Tasks 1–3); `get_base_requirements_path` (Task 4).
- Produces:
  - `overlay_path(version_cfg) -> str` → `<native_dir>/requirements.local.txt`
  - `generated_path(version_cfg) -> str` → `<native_dir>/requirements.txt`
  - `sync_allowed(version_cfg) -> tuple[bool, str]` → `(allowed, reason)`
  - frozen dataclass `SyncOutcome(version: str, written: bool, stale: bool, path: str, result: MergeResult | None, blocked_reason: str)` — `stale` is True when the rendered text differs from what is on disk, set in both normal and `check_only` mode so `--check` needs no second render
  - `sync_version(version: str, version_cfg, *, check_only: bool = False) -> SyncOutcome`
  - `ensure_generated_requirements(version: str, version_cfg) -> SyncOutcome | None`
  - `OVERLAY_TEMPLATE: str`
  - `seed_overlay(version_cfg) -> bool`

The guard is the safety mechanism from spec §7: without it, a `sync` on an existing machine replaces the hand-maintained file with the bare baseline. For v16 that is roughly 20 packages lost in one step.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for the requirements filesystem layer."""

import os

import pytest

from odoodev.core.requirements_sync import (
    SyncOutcome,
    ensure_generated_requirements,
    generated_path,
    overlay_path,
    seed_overlay,
    sync_allowed,
    sync_version,
)


class FakePaths:
    def __init__(self, native_dir):
        self.native_dir = native_dir


class FakeConfig:
    def __init__(self, native_dir):
        self.paths = FakePaths(native_dir)


@pytest.fixture
def cfg(tmp_path):
    return FakeConfig(str(tmp_path))


@pytest.fixture
def bundle(monkeypatch, tmp_path):
    """Point the baseline lookup at a controllable file."""
    base_file = tmp_path / "requirements.base.txt"
    base_file.write_text("Babel==2.16.0\nWerkzeug==3.1.3\n", encoding="utf-8")
    monkeypatch.setattr(
        "odoodev.core.requirements_sync.get_base_requirements_path",
        lambda version: base_file,
    )
    return base_file


def test_paths_sit_next_to_each_other(cfg):
    assert overlay_path(cfg).endswith("requirements.local.txt")
    assert generated_path(cfg).endswith("requirements.txt")
    assert os.path.dirname(overlay_path(cfg)) == os.path.dirname(generated_path(cfg))


def test_sync_allowed_on_a_fresh_environment(cfg):
    allowed, reason = sync_allowed(cfg)
    assert allowed is True
    assert reason == ""


def test_sync_blocked_on_a_hand_written_file_without_overlay(cfg, tmp_path):
    (tmp_path / "requirements.txt").write_text("Babel==2.16.0\nmsal==1.31.0\n", encoding="utf-8")
    allowed, reason = sync_allowed(cfg)
    assert allowed is False
    assert "adopt" in reason


def test_sync_allowed_once_an_overlay_exists(cfg, tmp_path):
    (tmp_path / "requirements.txt").write_text("Babel==2.16.0\n", encoding="utf-8")
    (tmp_path / "requirements.local.txt").write_text("msal==1.31.0\n", encoding="utf-8")
    allowed, _ = sync_allowed(cfg)
    assert allowed is True


def test_sync_allowed_on_a_previously_generated_file(cfg, tmp_path, bundle):
    sync_version("16", cfg)
    allowed, _ = sync_allowed(cfg)
    assert allowed is True


def test_sync_writes_a_generated_file(cfg, tmp_path, bundle):
    (tmp_path / "requirements.local.txt").write_text("Werkzeug==3.0.6\n", encoding="utf-8")
    outcome = sync_version("16", cfg)
    assert outcome.written is True
    text = (tmp_path / "requirements.txt").read_text(encoding="utf-8")
    assert "GENERATED by odoodev" in text
    assert "Werkzeug==3.0.6" in text
    assert outcome.result.warnings


def test_check_only_never_writes_but_reports_staleness(cfg, tmp_path, bundle):
    outcome = sync_version("16", cfg, check_only=True)
    assert outcome.written is False
    assert outcome.stale is True
    assert not (tmp_path / "requirements.txt").exists()


def test_check_only_reports_current_after_a_sync(cfg, tmp_path, bundle):
    sync_version("16", cfg)
    outcome = sync_version("16", cfg, check_only=True)
    assert outcome.stale is False


def test_sync_blocked_returns_reason_and_writes_nothing(cfg, tmp_path):
    (tmp_path / "requirements.txt").write_text("hand written\n", encoding="utf-8")
    outcome = sync_version("16", cfg)
    assert outcome.written is False
    assert outcome.blocked_reason
    assert (tmp_path / "requirements.txt").read_text(encoding="utf-8") == "hand written\n"


def test_ensure_regenerates_when_the_bundle_moved_on(cfg, tmp_path, bundle):
    sync_version("16", cfg)
    bundle.write_text("Babel==2.17.0\nWerkzeug==3.1.3\n", encoding="utf-8")
    outcome = ensure_generated_requirements("16", cfg)
    assert isinstance(outcome, SyncOutcome)
    assert outcome.written is True
    assert "2.17.0" in (tmp_path / "requirements.txt").read_text(encoding="utf-8")


def test_ensure_is_a_noop_when_the_file_is_current(cfg, tmp_path, bundle):
    sync_version("16", cfg)
    assert ensure_generated_requirements("16", cfg) is None


def test_ensure_is_a_noop_on_a_hand_written_file(cfg, tmp_path, bundle):
    (tmp_path / "requirements.txt").write_text("Babel==2.16.0\n", encoding="utf-8")
    assert ensure_generated_requirements("16", cfg) is None


def test_seed_overlay_creates_an_annotated_empty_file(cfg, tmp_path):
    assert seed_overlay(cfg) is True
    text = (tmp_path / "requirements.local.txt").read_text(encoding="utf-8")
    assert text.startswith("#")
    assert "requirements.local.txt" in text


def test_seed_overlay_never_overwrites(cfg, tmp_path):
    (tmp_path / "requirements.local.txt").write_text("msal==1.31.0\n", encoding="utf-8")
    assert seed_overlay(cfg) is False
    assert (tmp_path / "requirements.local.txt").read_text(encoding="utf-8") == "msal==1.31.0\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_requirements_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'odoodev.core.requirements_sync'`

- [ ] **Step 3: Write minimal implementation**

```python
"""Filesystem layer for the requirements base/overlay model.

Pure merging lives in requirements_merge; this module owns paths, the
overwrite guard and the write itself.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from odoodev import __version__
from odoodev.core.example_templates import get_base_requirements_path
from odoodev.core.requirements_merge import (
    MergeResult,
    extract_base_hash,
    is_generated,
    render_requirements,
    sha256_text,
)

OVERLAY_FILENAME = "requirements.local.txt"
GENERATED_FILENAME = "requirements.txt"

OVERLAY_TEMPLATE = """# Local requirements overlay — this file is yours; odoodev never overwrites it.
#
# Entries here replace the matching baseline entry (matched on package name AND
# environment marker) or are appended when the baseline has no counterpart.
# After editing, run: odoodev requirements sync
#
# Example:
#   Werkzeug==3.0.6   # MUST stay < 3.1: odoo/http.py:260 reads werkzeug.__version__
"""


@dataclass(frozen=True)
class SyncOutcome:
    """Result of a sync attempt for one version.

    `stale` says the rendered text differs from what is on disk. It is set in
    check_only mode too, which is what lets `sync --check` decide without
    rendering a second time.
    """

    version: str
    written: bool
    stale: bool
    path: str
    result: MergeResult | None
    blocked_reason: str


def overlay_path(version_cfg) -> str:
    """Path to the machine-local overlay file."""
    return os.path.join(version_cfg.paths.native_dir, OVERLAY_FILENAME)


def generated_path(version_cfg) -> str:
    """Path to the generated effective requirements file."""
    return os.path.join(version_cfg.paths.native_dir, GENERATED_FILENAME)


def _read(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def sync_allowed(version_cfg) -> tuple[bool, str]:
    """Decide whether sync may write over the existing requirements.txt.

    Refuses when a hand-maintained file is present and no overlay exists —
    otherwise sync would replace it with the bare baseline and lose every
    package that was never in the bundle. An overlay's existence counts as
    consent: the user has been through adopt.
    """
    target = generated_path(version_cfg)
    if not os.path.exists(target):
        return True, ""
    if is_generated(_read(target)):
        return True, ""
    if os.path.exists(overlay_path(version_cfg)):
        return True, ""
    return False, (
        f"{target} was not generated by odoodev and no {OVERLAY_FILENAME} exists. "
        f"Run 'odoodev requirements adopt' first — it preserves your current pins."
    )


def sync_version(version: str, version_cfg, *, check_only: bool = False) -> SyncOutcome:
    """Regenerate requirements.txt for one version."""
    target = generated_path(version_cfg)
    allowed, reason = sync_allowed(version_cfg)
    if not allowed:
        return SyncOutcome(
            version=version, written=False, stale=False, path=target, result=None, blocked_reason=reason
        )

    base_text = get_base_requirements_path(version).read_text(encoding="utf-8")
    local_text = _read(overlay_path(version_cfg))
    text, result = render_requirements(
        version=version,
        odoodev_version=__version__,
        base_text=base_text,
        local_text=local_text,
    )

    stale = text != _read(target)
    if check_only or not stale:
        written = False
    else:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(text)
        written = True

    return SyncOutcome(
        version=version, written=written, stale=stale, path=target, result=result, blocked_reason=""
    )


def ensure_generated_requirements(version: str, version_cfg) -> SyncOutcome | None:
    """Regenerate when the shipped baseline has moved on since the last sync.

    Returns None when nothing needed doing — which includes a hand-maintained
    file, so this never touches an environment that has not adopted yet.
    """
    target = generated_path(version_cfg)
    current = _read(target)
    if not current or not is_generated(current):
        return None

    base_file = get_base_requirements_path(version)
    if not base_file.is_file():
        return None
    if extract_base_hash(current) == sha256_text(base_file.read_text(encoding="utf-8")):
        return None

    outcome = sync_version(version, version_cfg)
    return outcome if outcome.written else None


def seed_overlay(version_cfg) -> bool:
    """Create an annotated empty overlay. Returns False if one already exists."""
    path = overlay_path(version_cfg)
    if os.path.exists(path):
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(OVERLAY_TEMPLATE)
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_requirements_sync.py -v && ruff check . && ruff format --check .`
Expected: 14 passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add odoodev/core/requirements_sync.py tests/test_requirements_sync.py
git commit -m "[ADD] requirements sync layer: paths, overwrite guard, generation"
```

---

### Task 6: CLI group and `requirements sync`

**Files:**
- Create: `odoodev/commands/requirements.py`
- Modify: `odoodev/cli.py`
- Test: `tests/test_requirements_cmd.py`

**Interfaces:**
- Consumes: `sync_version`, `SyncOutcome` (Task 5); `resolve_version` from `odoodev.cli`; `available_versions`, `get_version` from `odoodev.core.version_registry`.
- Produces: Click group `requirements` exporting subcommand `sync`; helper `_print_sync_outcome(outcome: SyncOutcome) -> None`.

- [ ] **Step 1: Write the failing test**

```python
"""CliRunner-level tests for the requirements command group."""

import pytest
from click.testing import CliRunner

from odoodev.cli import cli


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A version config pointing at tmp_path, with a controllable baseline."""
    base_file = tmp_path / "requirements.base.txt"
    base_file.write_text("Babel==2.16.0\nWerkzeug==3.1.3\n", encoding="utf-8")
    monkeypatch.setattr(
        "odoodev.core.requirements_sync.get_base_requirements_path",
        lambda version: base_file,
    )

    class FakePaths:
        native_dir = str(tmp_path)

    class FakeConfig:
        paths = FakePaths()

    monkeypatch.setattr("odoodev.commands.requirements.get_version", lambda version: FakeConfig())
    monkeypatch.setattr("odoodev.commands.requirements.available_versions", lambda: ["16", "18"])
    return tmp_path


def test_sync_writes_the_generated_file(env):
    result = CliRunner().invoke(cli, ["requirements", "sync", "16"])
    assert result.exit_code == 0
    assert "GENERATED by odoodev" in (env / "requirements.txt").read_text(encoding="utf-8")


def test_sync_reports_held_back_pins(env):
    (env / "requirements.local.txt").write_text("Werkzeug==3.0.6\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["requirements", "sync", "16"])
    assert result.exit_code == 0
    assert "holds" in result.output
    assert "3.1.3" in result.output


def test_sync_check_exits_1_when_stale_and_writes_nothing(env):
    result = CliRunner().invoke(cli, ["requirements", "sync", "16", "--check"])
    assert result.exit_code == 1
    assert not (env / "requirements.txt").exists()


def test_sync_check_exits_0_when_current(env):
    CliRunner().invoke(cli, ["requirements", "sync", "16"])
    result = CliRunner().invoke(cli, ["requirements", "sync", "16", "--check"])
    assert result.exit_code == 0


def test_sync_blocked_exits_1_and_keeps_the_file(env):
    (env / "requirements.txt").write_text("hand written\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["requirements", "sync", "16"])
    assert result.exit_code == 1
    assert "adopt" in result.output
    assert (env / "requirements.txt").read_text(encoding="utf-8") == "hand written\n"


def test_sync_all_covers_every_configured_version(env):
    result = CliRunner().invoke(cli, ["requirements", "sync", "--all"])
    assert result.exit_code == 0
    assert "v16" in result.output
    assert "v18" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_requirements_cmd.py -v`
Expected: FAIL — `Error: No such command 'requirements'`

- [ ] **Step 3: Write minimal implementation**

Create `odoodev/commands/requirements.py`:

```python
"""Requirements base/overlay management commands."""

from __future__ import annotations

import click

from odoodev.core.requirements_sync import SyncOutcome, sync_version
from odoodev.core.version_registry import available_versions, get_version
from odoodev.output import print_error, print_info, print_success, print_warning


@click.group()
def requirements() -> None:
    """Manage base requirements and the machine-local overlay."""


def _print_sync_outcome(outcome: SyncOutcome) -> None:
    """Report one version's sync result, including merge warnings."""
    if outcome.blocked_reason:
        print_error(f"v{outcome.version}: {outcome.blocked_reason}")
        return

    if outcome.result is not None:
        for base_req, local_req in outcome.result.replaced:
            print_info(f"v{outcome.version}: overlay pins {local_req.name}{local_req.specifier}")
        for warning in outcome.result.warnings:
            print_warning(f"v{outcome.version}: {warning}")

    if outcome.written:
        print_success(f"v{outcome.version}: {outcome.path} regenerated")
    else:
        print_info(f"v{outcome.version}: already current")


@requirements.command("sync")
@click.argument("version", required=False)
@click.option("--all", "all_versions", is_flag=True, help="Sync every configured version")
@click.option("--check", is_flag=True, help="Write nothing; exit 1 if the file is stale")
@click.pass_context
def requirements_sync(ctx: click.Context, version: str | None, all_versions: bool, check: bool) -> None:
    """Regenerate requirements.txt from the baseline plus the local overlay."""
    from odoodev.cli import resolve_version

    targets = available_versions() if all_versions else [resolve_version(ctx, version)]

    failed = False
    for target in targets:
        outcome = sync_version(target, get_version(target), check_only=check)
        _print_sync_outcome(outcome)
        if outcome.blocked_reason or (check and outcome.stale):
            failed = True

    if failed:
        raise SystemExit(1)
```

Register it in `odoodev/cli.py` next to the existing imports and `add_command` calls:

```python
from odoodev.commands.requirements import requirements  # noqa: E402
...
cli.add_command(requirements)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_requirements_cmd.py -v && ruff check . && ruff format --check .`
Expected: 6 passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add odoodev/commands/requirements.py odoodev/cli.py tests/test_requirements_cmd.py
git commit -m "[ADD] odoodev requirements sync with --all and --check"
```

---

### Task 7: `requirements diff` — three-way report

**Files:**
- Modify: `odoodev/core/requirements_sync.py`
- Modify: `odoodev/commands/requirements.py`
- Test: `tests/test_requirements_sync.py`, `tests/test_requirements_cmd.py`

**Interfaces:**
- Consumes: `parse_requirements`, `canonical_name` (Task 1); `overlay_path`, `generated_path` (Task 5).
- Produces in `requirements_sync`: `installed_packages(venv_dir: str) -> dict[str, str]` (canonical name → version); frozen dataclass `DiffRow(name: str, base: str, local: str, installed: str, status: str)`; `three_way_report(version: str, version_cfg) -> list[DiffRow]`. Status is one of `"local override"`, `"local only"`, `"not installed"`, `"ok"`. (An earlier draft also listed `"base only"`; it describes no distinguishable state — a package present only in the baseline is the normal case and is already told apart by `"ok"` versus `"not installed"`.)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_requirements_sync.py`:

```python
from odoodev.core.requirements_sync import DiffRow, installed_packages, three_way_report


def test_installed_packages_parses_uv_freeze(monkeypatch):
    import subprocess

    def fake_run(cmd, **kwargs):
        assert cmd[:3] == ["uv", "pip", "freeze"]
        return subprocess.CompletedProcess(cmd, 0, stdout="Babel==2.16.0\nWerkzeug==3.0.6\n", stderr="")

    monkeypatch.setattr("odoodev.core.requirements_sync.subprocess.run", fake_run)
    assert installed_packages("/tmp/venv") == {"babel": "2.16.0", "werkzeug": "3.0.6"}


def test_installed_packages_returns_empty_on_failure(monkeypatch):
    import subprocess

    monkeypatch.setattr(
        "odoodev.core.requirements_sync.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom"),
    )
    assert installed_packages("/tmp/venv") == {}


def test_three_way_report_classifies_each_row(cfg, tmp_path, bundle, monkeypatch):
    (tmp_path / "requirements.local.txt").write_text("Werkzeug==3.0.6\nmsal==1.31.0\n", encoding="utf-8")
    monkeypatch.setattr(
        "odoodev.core.requirements_sync.installed_packages",
        lambda venv_dir: {"babel": "2.16.0", "werkzeug": "3.0.6"},
    )
    rows = {row.name: row for row in three_way_report("16", cfg)}

    assert rows["Babel"].status == "ok"
    assert rows["Werkzeug"].status == "local override"
    assert rows["Werkzeug"].base == "==3.1.3"
    assert rows["Werkzeug"].local == "==3.0.6"
    assert rows["Werkzeug"].installed == "3.0.6"
    assert rows["msal"].status == "local only"


def test_three_way_report_flags_declared_but_missing(cfg, tmp_path, bundle, monkeypatch):
    monkeypatch.setattr("odoodev.core.requirements_sync.installed_packages", lambda venv_dir: {})
    rows = {row.name: row for row in three_way_report("16", cfg)}
    assert rows["Babel"].status == "not installed"
    assert isinstance(rows["Babel"], DiffRow)
```

Add to `tests/test_requirements_cmd.py`:

```python
def test_diff_json_contract(env, monkeypatch):
    import json

    (env / "requirements.local.txt").write_text("Werkzeug==3.0.6\n", encoding="utf-8")
    monkeypatch.setattr(
        "odoodev.core.requirements_sync.installed_packages",
        lambda venv_dir: {"werkzeug": "3.0.6"},
    )
    result = CliRunner().invoke(cli, ["requirements", "diff", "16", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output.strip())
    assert payload["version"] == "16"
    names = {row["name"]: row for row in payload["rows"]}
    assert names["Werkzeug"]["status"] == "local override"


def test_diff_never_writes(env):
    CliRunner().invoke(cli, ["requirements", "diff", "16"])
    assert not (env / "requirements.txt").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_requirements_sync.py tests/test_requirements_cmd.py -v`
Expected: FAIL — `ImportError: cannot import name 'three_way_report'`

- [ ] **Step 3: Write minimal implementation**

Add `import subprocess` to `requirements_sync.py` and append:

```python
@dataclass(frozen=True)
class DiffRow:
    """One package as seen by baseline, overlay and the installed venv."""

    name: str
    base: str
    local: str
    installed: str
    status: str


def installed_packages(venv_dir: str) -> dict[str, str]:
    """Canonical name → installed version, via `uv pip freeze`.

    Returns an empty mapping when the venv is absent or uv fails; the report
    then simply shows nothing as installed rather than aborting.
    """
    from odoodev.core.requirements_merge import canonical_name

    env = {**os.environ, "VIRTUAL_ENV": venv_dir}
    result = subprocess.run(["uv", "pip", "freeze"], env=env, capture_output=True, text=True)
    if result.returncode != 0:
        return {}

    packages: dict[str, str] = {}
    for line in result.stdout.splitlines():
        name, sep, version = line.strip().partition("==")
        if sep and name:
            packages[canonical_name(name)] = version.strip()
    return packages


def three_way_report(version: str, version_cfg) -> list[DiffRow]:
    """Compare baseline, overlay and installed packages for one version."""
    from odoodev.core.requirements_merge import parse_requirements

    base_text = get_base_requirements_path(version).read_text(encoding="utf-8")
    local_text = _read(overlay_path(version_cfg))
    installed = installed_packages(os.path.join(version_cfg.paths.native_dir, ".venv"))

    base_reqs = {
        line.requirement.merge_key: line.requirement
        for line in parse_requirements(base_text)
        if line.requirement is not None
    }
    local_reqs = {
        line.requirement.merge_key: line.requirement
        for line in parse_requirements(local_text)
        if line.requirement is not None
    }

    rows: list[DiffRow] = []
    for key in list(base_reqs) + [k for k in local_reqs if k not in base_reqs]:
        base_req = base_reqs.get(key)
        local_req = local_reqs.get(key)
        effective = local_req if local_req is not None else base_req
        if effective is None:  # unreachable: the key came from one of the two maps
            continue
        installed_version = installed.get(effective.key, "")

        if base_req is None:
            status = "local only"
        elif local_req is not None:
            status = "local override"
        elif not installed_version:
            status = "not installed"
        else:
            status = "ok"

        rows.append(
            DiffRow(
                name=effective.name,
                base=base_req.specifier if base_req else "",
                local=local_req.specifier if local_req else "",
                installed=installed_version,
                status=status,
            )
        )
    return rows
```

Add the command to `odoodev/commands/requirements.py`:

```python
@requirements.command("diff")
@click.argument("version", required=False)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output")
@click.pass_context
def requirements_diff(ctx: click.Context, version: str | None, as_json: bool) -> None:
    """Show baseline vs. overlay vs. installed packages. Writes nothing."""
    import json
    import sys

    from rich.console import Console
    from rich.table import Table

    from odoodev.cli import resolve_version
    from odoodev.core.requirements_sync import three_way_report

    target = resolve_version(ctx, version)
    rows = three_way_report(target, get_version(target))

    if as_json:
        payload = {
            "version": target,
            "rows": [
                {
                    "name": row.name,
                    "base": row.base,
                    "local": row.local,
                    "installed": row.installed,
                    "status": row.status,
                }
                for row in rows
            ],
        }
        sys.stdout.write(json.dumps(payload) + "\n")
        return

    table = Table(title=f"Requirements v{target}")
    for column in ("Package", "Base", "Local", "Installed", "Status"):
        table.add_column(column)
    for row in rows:
        if row.status == "ok":
            continue
        table.add_row(row.name, row.base, row.local, row.installed, row.status)
    Console().print(table)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_requirements_sync.py tests/test_requirements_cmd.py -v && ruff check . && ruff format --check .`
Expected: all passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add odoodev/core/requirements_sync.py odoodev/commands/requirements.py tests/
git commit -m "[ADD] odoodev requirements diff: three-way base/local/installed report"
```

---

### Task 8: `requirements adopt` — one-time migration

**Files:**
- Modify: `odoodev/commands/requirements.py`
- Modify: `odoodev/core/requirements_sync.py`
- Test: `tests/test_requirements_sync.py`, `tests/test_requirements_cmd.py`

**Interfaces:**
- Consumes: `parse_requirements`, `Requirement` (Task 1); `overlay_path`, `generated_path`, `sync_version`, `_read` (Task 5); `get_base_requirements_path` (Task 4).
- Produces in `requirements_sync`: frozen dataclass `AdoptCandidate(existing: Requirement, base: Requirement | None)`; `adopt_candidates(version: str, version_cfg) -> list[AdoptCandidate]`; `write_overlay(version_cfg, entries: list[Requirement]) -> str`; `backup_existing(version_cfg) -> str | None` writing `requirements.txt.pre-adopt`.

Refinement of spec §8: the command asks **only about genuine conflicts** — an entry that exists in both files with a different specifier. Entries that exist only in the current file have no meaningful alternative to keeping them, so they move into the overlay automatically and are reported. This keeps `adopt` lossless without turning it into 60 prompts.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_requirements_sync.py`:

```python
from odoodev.core.requirements_sync import adopt_candidates, backup_existing, write_overlay


def test_adopt_candidates_split_conflicts_from_local_only(cfg, tmp_path, bundle):
    (tmp_path / "requirements.txt").write_text(
        "Babel==2.16.0\nWerkzeug==3.0.6\nmsal==1.31.0\n", encoding="utf-8"
    )
    candidates = {c.existing.name: c for c in adopt_candidates("16", cfg)}

    assert "Babel" not in candidates          # identical to baseline, nothing to decide
    assert candidates["Werkzeug"].base is not None   # conflict: baseline has 3.1.3
    assert candidates["msal"].base is None           # local only


def test_adopt_candidates_respect_markers(cfg, tmp_path, monkeypatch):
    base_file = tmp_path / "base.txt"
    base_file.write_text("Babel==2.10.3 ; python_version < '3.13'\n", encoding="utf-8")
    monkeypatch.setattr(
        "odoodev.core.requirements_sync.get_base_requirements_path", lambda version: base_file
    )
    (tmp_path / "requirements.txt").write_text(
        "Babel==2.10.3 ; python_version < '3.13'\nBabel==2.17.0 ; python_version >= '3.13'\n",
        encoding="utf-8",
    )
    candidates = adopt_candidates("16", cfg)
    assert len(candidates) == 1
    assert candidates[0].existing.marker == "python_version >= '3.13'"
    assert candidates[0].base is None


def test_backup_existing_writes_pre_adopt_copy(cfg, tmp_path):
    (tmp_path / "requirements.txt").write_text("Babel==2.16.0\n", encoding="utf-8")
    path = backup_existing(cfg)
    assert path.endswith("requirements.txt.pre-adopt")
    assert (tmp_path / "requirements.txt.pre-adopt").read_text(encoding="utf-8") == "Babel==2.16.0\n"


def test_backup_existing_returns_none_without_a_file(cfg):
    assert backup_existing(cfg) is None


def test_write_overlay_emits_parseable_entries(cfg, tmp_path):
    from odoodev.core.requirements_merge import parse_requirements

    existing = [
        line.requirement
        for line in parse_requirements("msal==1.31.0  # v16-microsoft365\n")
        if line.requirement
    ]
    path = write_overlay(cfg, existing)
    text = open(path, encoding="utf-8").read()
    assert "msal==1.31.0" in text
    assert "v16-microsoft365" in text
    assert text.lstrip().startswith("#")
```

Add to `tests/test_requirements_cmd.py`:

```python
def test_adopt_moves_local_only_entries_and_asks_about_conflicts(env, monkeypatch):
    (env / "requirements.txt").write_text(
        "Babel==2.16.0\nWerkzeug==3.0.6\nmsal==1.31.0\n", encoding="utf-8"
    )
    monkeypatch.setattr("odoodev.commands.requirements.select", lambda message, choices: "keep local")

    result = CliRunner().invoke(cli, ["requirements", "adopt", "16"])
    assert result.exit_code == 0

    overlay = (env / "requirements.local.txt").read_text(encoding="utf-8")
    assert "Werkzeug==3.0.6" in overlay
    assert "msal==1.31.0" in overlay
    assert "Babel" not in overlay
    assert (env / "requirements.txt.pre-adopt").exists()
    assert "GENERATED by odoodev" in (env / "requirements.txt").read_text(encoding="utf-8")


def test_adopt_taking_the_baseline_leaves_it_out_of_the_overlay(env, monkeypatch):
    (env / "requirements.txt").write_text("Werkzeug==3.0.6\n", encoding="utf-8")
    monkeypatch.setattr("odoodev.commands.requirements.select", lambda message, choices: "take baseline")

    CliRunner().invoke(cli, ["requirements", "adopt", "16"])
    overlay = (env / "requirements.local.txt").read_text(encoding="utf-8")
    assert "Werkzeug" not in overlay
    assert "Werkzeug==3.1.3" in (env / "requirements.txt").read_text(encoding="utf-8")


def test_adopt_yes_keeps_every_local_entry_without_prompting(env):
    (env / "requirements.txt").write_text("Werkzeug==3.0.6\nmsal==1.31.0\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["requirements", "adopt", "16", "--yes"])
    assert result.exit_code == 0
    overlay = (env / "requirements.local.txt").read_text(encoding="utf-8")
    assert "Werkzeug==3.0.6" in overlay
    assert "msal==1.31.0" in overlay


def test_adopt_refuses_on_an_already_generated_file(env):
    CliRunner().invoke(cli, ["requirements", "sync", "16"])
    result = CliRunner().invoke(cli, ["requirements", "adopt", "16"])
    assert result.exit_code == 1
    assert "already" in result.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_requirements_sync.py tests/test_requirements_cmd.py -v`
Expected: FAIL — `ImportError: cannot import name 'adopt_candidates'`

- [ ] **Step 3: Write minimal implementation**

Append to `odoodev/core/requirements_sync.py` (add `import shutil` at the top):

```python
PRE_ADOPT_SUFFIX = ".pre-adopt"


@dataclass(frozen=True)
class AdoptCandidate:
    """An entry from the existing file that adopt must decide about.

    `base` is the baseline counterpart when one exists (a genuine conflict),
    None when the entry exists only locally.
    """

    existing: Requirement
    base: Requirement | None


def adopt_candidates(version: str, version_cfg) -> list[AdoptCandidate]:
    """Entries of the current requirements.txt that deviate from the baseline."""
    from odoodev.core.requirements_merge import parse_requirements

    base_text = get_base_requirements_path(version).read_text(encoding="utf-8")
    existing_text = _read(generated_path(version_cfg))

    base_reqs = {
        line.requirement.merge_key: line.requirement
        for line in parse_requirements(base_text)
        if line.requirement is not None
    }

    candidates: list[AdoptCandidate] = []
    for line in parse_requirements(existing_text):
        req = line.requirement
        if req is None:
            continue
        base_req = base_reqs.get(req.merge_key)
        if base_req is not None and base_req.specifier == req.specifier and base_req.extras == req.extras:
            continue
        candidates.append(AdoptCandidate(existing=req, base=base_req))
    return candidates


def backup_existing(version_cfg) -> str | None:
    """Copy requirements.txt aside before adopt rewrites it."""
    source = generated_path(version_cfg)
    if not os.path.exists(source):
        return None
    target = source + PRE_ADOPT_SUFFIX
    shutil.copy2(source, target)
    return target


def write_overlay(version_cfg, entries: list[Requirement]) -> str:
    """Write the overlay file from a list of requirements."""
    path = overlay_path(version_cfg)
    lines = [OVERLAY_TEMPLATE.rstrip("\n"), ""]
    for req in entries:
        comment = f"  # {req.comment}" if req.comment else ""
        lines.append(f"{req.to_line()}{comment}")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip("\n") + "\n")
    return path
```

Add `Requirement` to the existing import from `requirements_merge`.

Add the command to `odoodev/commands/requirements.py` (extend the top-level import to include `select`):

```python
@requirements.command("adopt")
@click.argument("version", required=False)
@click.option("--yes", "-y", is_flag=True, help="Keep every local pin without prompting")
@click.pass_context
def requirements_adopt(ctx: click.Context, version: str | None, yes: bool) -> None:
    """Migrate a hand-maintained requirements.txt into baseline + overlay."""
    import os

    from odoodev.cli import resolve_version
    from odoodev.core.requirements_merge import is_generated
    from odoodev.core.requirements_sync import (
        adopt_candidates,
        backup_existing,
        generated_path,
        sync_version,
        write_overlay,
    )

    target = resolve_version(ctx, version)
    cfg = get_version(target)
    current = generated_path(cfg)

    if not os.path.exists(current):
        print_error(f"No requirements.txt at {current} — nothing to adopt. Run 'odoodev requirements sync'.")
        raise SystemExit(1)

    with open(current, encoding="utf-8") as handle:
        if is_generated(handle.read()):
            print_error(f"v{target}: requirements.txt is already generated — this environment has adopted.")
            raise SystemExit(1)

    keep: list = []
    for candidate in adopt_candidates(target, cfg):
        if candidate.base is None:
            print_info(f"local only, moved to overlay: {candidate.existing.to_line()}")
            keep.append(candidate.existing)
            continue
        if yes:
            keep.append(candidate.existing)
            continue
        choice = select(
            f"{candidate.existing.name}: baseline {candidate.base.specifier} vs. "
            f"local {candidate.existing.specifier}",
            ["keep local", "take baseline"],
        )
        if choice == "keep local":
            keep.append(candidate.existing)

    backup = backup_existing(cfg)
    if backup:
        print_info(f"Previous file kept at {backup}")

    overlay = write_overlay(cfg, keep)
    print_success(f"Overlay written: {overlay} ({len(keep)} entries)")

    outcome = sync_version(target, cfg)
    _print_sync_outcome(outcome)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_requirements_sync.py tests/test_requirements_cmd.py -v && ruff check . && ruff format --check .`
Expected: all passed, ruff clean

- [ ] **Step 5: Commit**

```bash
git add odoodev/core/requirements_sync.py odoodev/commands/requirements.py tests/
git commit -m "[ADD] odoodev requirements adopt: lossless migration to base/overlay"
```

---

### Task 9: Wire the automatic regeneration into `start`

**Files:**
- Modify: `odoodev/commands/start.py` (new helper plus one call in `_run_preflight`, immediately before the existing requirements-freshness block at ~line 753)
- Test: `tests/test_start.py`

**Interfaces:**
- Consumes: `ensure_generated_requirements`, `SyncOutcome` (Task 5).
- Produces: `_report_requirements_sync(version: str, version_cfg) -> bool` in `odoodev.commands.start` — returns True when a regeneration happened.

`_run_preflight` takes 14 parameters and is not worth driving from a test. Extracting a small
helper follows the file's existing convention (it is full of tested `_`-prefixed helpers) and
makes the behaviour directly assertable.

This is the step that makes a baseline update arrive without hand work: regenerate
silently-but-reported, then let the **existing** SHA256 prompt handle installation.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_start.py`:

```python
class TestReportRequirementsSync:
    """start regenerates requirements.txt before it compares hashes."""

    def _outcome(self, warnings=()):
        from odoodev.core.requirements_merge import MergeResult, Requirement
        from odoodev.core.requirements_sync import SyncOutcome

        base = Requirement(
            name="Werkzeug", key="werkzeug", extras=(), specifier="==3.1.3", marker="", comment=""
        )
        local = Requirement(
            name="Werkzeug", key="werkzeug", extras=(), specifier="==3.0.6", marker="", comment=""
        )
        return SyncOutcome(
            version="16",
            written=True,
            stale=True,
            path="/tmp/requirements.txt",
            result=MergeResult(body=(), replaced=((base, local),), added=(), warnings=warnings),
            blocked_reason="",
        )

    def test_reports_regeneration_and_warnings(self, monkeypatch, capsys):
        from odoodev.commands.start import _report_requirements_sync

        outcome = self._outcome(warnings=("Werkzeug: overlay holds 3.0.6 back (base: 3.1.3)",))
        monkeypatch.setattr(
            "odoodev.commands.start.ensure_generated_requirements",
            lambda version, version_cfg: outcome,
        )

        assert _report_requirements_sync("16", object()) is True
        out = capsys.readouterr().out
        assert "regenerated" in out
        assert "holds 3.0.6 back" in out
        assert "overlay pins ==3.0.6" in out

    def test_stays_silent_when_nothing_changed(self, monkeypatch, capsys):
        from odoodev.commands.start import _report_requirements_sync

        monkeypatch.setattr(
            "odoodev.commands.start.ensure_generated_requirements",
            lambda version, version_cfg: None,
        )

        assert _report_requirements_sync("16", object()) is False
        assert capsys.readouterr().out == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_start.py -k ReportRequirementsSync -v`
Expected: FAIL — `ImportError: cannot import name '_report_requirements_sync'`

- [ ] **Step 3: Write minimal implementation**

Add to the imports at the top of `odoodev/commands/start.py`:

```python
from odoodev.core.requirements_sync import ensure_generated_requirements
```

Add the helper next to the other module-level helpers:

```python
def _report_requirements_sync(version: str, version_cfg) -> bool:
    """Regenerate requirements.txt when the shipped baseline moved on.

    Returns True when a regeneration happened. Runs BEFORE the SHA256
    freshness check on purpose: a regeneration changes the file, which is
    exactly what that check is meant to react to.
    """
    outcome = ensure_generated_requirements(version, version_cfg)
    if outcome is None or outcome.result is None:
        return False

    print_info(f"Base requirements updated — {outcome.path} regenerated")
    for _base_req, local_req in outcome.result.replaced:
        print_info(f"  {local_req.name}: overlay pins {local_req.specifier}")
    for warning in outcome.result.warnings:
        print_warning(f"  {warning}")
    return True
```

Call it in `_run_preflight`, immediately before the existing `# Check requirements freshness`
block:

```python
    _report_requirements_sync(version, version_cfg)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_start.py -v && ruff check . && ruff format --check .`
Expected: all passed — including the pre-existing start tests, which must stay green

- [ ] **Step 5: Commit**

```bash
git add odoodev/commands/start.py tests/test_start.py
git commit -m "[CHG] start: regenerate requirements from baseline before the hash check"
```

---

### Task 10: Seed the overlay on a fresh `init`

**Files:**
- Modify: `odoodev/core/requirements_sync.py`
- Modify: `odoodev/commands/init_cmd.py` (after the Step 1.5 template block, ~line 83)
- Test: `tests/test_requirements_sync.py`

**Interfaces:**
- Consumes: `seed_overlay`, `sync_version`, `SyncOutcome` (Task 5).
- Produces: `bootstrap_requirements(version: str, version_cfg) -> tuple[bool, SyncOutcome]` in
  `requirements_sync` — `(overlay_was_created, sync_outcome)`.

`init` is one long procedural function; putting the logic in the core keeps it testable without
driving the whole init machinery, and leaves `init` with a three-line call.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_requirements_sync.py`:

```python
from odoodev.core.requirements_sync import bootstrap_requirements


def test_bootstrap_seeds_overlay_and_generates(cfg, tmp_path, bundle):
    created, outcome = bootstrap_requirements("16", cfg)
    assert created is True
    assert outcome.written is True
    assert (tmp_path / "requirements.local.txt").exists()
    assert "GENERATED by odoodev" in (tmp_path / "requirements.txt").read_text(encoding="utf-8")


def test_bootstrap_keeps_an_existing_overlay(cfg, tmp_path, bundle):
    (tmp_path / "requirements.local.txt").write_text("msal==1.31.0\n", encoding="utf-8")
    created, outcome = bootstrap_requirements("16", cfg)
    assert created is False
    assert (tmp_path / "requirements.local.txt").read_text(encoding="utf-8") == "msal==1.31.0\n"
    assert "msal==1.31.0" in (tmp_path / "requirements.txt").read_text(encoding="utf-8")


def test_bootstrap_is_blocked_by_a_hand_written_file(cfg, tmp_path, bundle):
    (tmp_path / "requirements.txt").write_text("hand written\n", encoding="utf-8")
    created, outcome = bootstrap_requirements("16", cfg)
    assert outcome.blocked_reason
    assert (tmp_path / "requirements.txt").read_text(encoding="utf-8") == "hand written\n"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_requirements_sync.py -k bootstrap -v`
Expected: FAIL — `ImportError: cannot import name 'bootstrap_requirements'`

- [ ] **Step 3: Write minimal implementation**

Append to `odoodev/core/requirements_sync.py`:

```python
def bootstrap_requirements(version: str, version_cfg) -> tuple[bool, SyncOutcome]:
    """Seed an empty overlay if needed and generate the effective file.

    Used by `init` on a fresh environment. Returns whether the overlay was
    created, plus the sync outcome (which carries a blocked_reason when an
    un-adopted hand-maintained file is in the way).
    """
    created = seed_overlay(version_cfg)
    return created, sync_version(version, version_cfg)
```

In `odoodev/commands/init_cmd.py`, directly after the `if outdated:` block of Step 1.5, following
the file's established lazy-import convention (see the `copy_example_templates` import above):

```python
    # Step 1.6: Requirements baseline/overlay
    from odoodev.core.requirements_sync import bootstrap_requirements

    overlay_created, sync_outcome = bootstrap_requirements(version, version_cfg)
    if overlay_created:
        print_info(f"Created empty local overlay: {os.path.join(native_dir, 'requirements.local.txt')}")
    if sync_outcome.blocked_reason:
        print_warning(sync_outcome.blocked_reason)
    elif sync_outcome.written:
        print_success(f"requirements.txt generated: {sync_outcome.path}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_requirements_sync.py tests/test_init_cmd.py -v && ruff check . && ruff format --check .`
Expected: all passed (`tests/test_init_cmd.py` only if it exists in the repository)

- [ ] **Step 5: Commit**

```bash
git add odoodev/core/requirements_sync.py odoodev/commands/init_cmd.py tests/test_requirements_sync.py
git commit -m "[CHG] init: seed requirements overlay and generate the effective file"
```

---

### Task 11: Curate the four baselines (spec §8, phase 1)

**Files:**
- Modify: `odoodev/data/examples/v16/requirements.base.txt`
- Modify: `odoodev/data/examples/v17/requirements.base.txt`
- Modify: `odoodev/data/examples/v18/requirements.base.txt`
- Modify: `odoodev/data/examples/v19/requirements.base.txt`
- Test: `tests/test_requirements_baselines.py` (new)

**Interfaces:**
- Consumes: `parse_requirements`, `canonical_name` (Task 1); `get_base_requirements_path` (Task 4).
- Produces: nothing importable — this is a content task with mechanical guards.

The shipped baselines predate the real files. v16 ships `Werkzeug==2.3.8` while the real environment runs `3.0.6`. Until this task runs, an `adopt` would push roughly 20 packages into the v16 overlay and the baseline would steer nothing.

- [ ] **Step 1: Write the failing test**

```python
"""Structural guards for the shipped requirements baselines."""

import pytest

from odoodev.core.example_templates import get_base_requirements_path
from odoodev.core.requirements_merge import parse_requirements

VERSIONS = ("16", "17", "18", "19")


@pytest.mark.parametrize("version", VERSIONS)
def test_baseline_parses_without_unkeyed_requirement_lines(version):
    """Every non-comment line must parse, or the merge would silently pass it through."""
    text = get_base_requirements_path(version).read_text(encoding="utf-8")
    for line in parse_requirements(text):
        stripped = line.raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        assert line.requirement is not None, f"v{version}: unparsed line {line.raw!r}"


@pytest.mark.parametrize("version", VERSIONS)
def test_baseline_has_no_duplicate_merge_keys(version):
    """Two entries with the same (name, marker) would make the merge ambiguous."""
    text = get_base_requirements_path(version).read_text(encoding="utf-8")
    keys = [line.requirement.merge_key for line in parse_requirements(text) if line.requirement]
    assert len(keys) == len(set(keys)), f"v{version}: duplicate merge keys"


def test_v17_keeps_both_marker_variants():
    """The six doubled v17 packages must survive curation."""
    text = get_base_requirements_path("17").read_text(encoding="utf-8")
    names = [line.requirement.key for line in parse_requirements(text) if line.requirement]
    for package in ("babel", "zeep", "gevent", "greenlet", "freezegun", "psycopg2-binary"):
        assert names.count(package) == 2, f"v17: expected two marker variants of {package}"


def test_v16_pins_werkzeug_below_3_1():
    """Odoo 16 does not import with Werkzeug 3.1.x (odoo/http.py:260)."""
    text = get_base_requirements_path("16").read_text(encoding="utf-8")
    werkzeug = [line.requirement for line in parse_requirements(text) if line.requirement and line.requirement.key == "werkzeug"]
    assert len(werkzeug) == 1
    assert werkzeug[0].specifier == "==3.0.6"


@pytest.mark.parametrize("version", VERSIONS)
def test_baseline_carries_no_generated_header(version):
    """A baseline is a source file, never a generated one."""
    from odoodev.core.requirements_merge import is_generated

    assert not is_generated(get_base_requirements_path(version).read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_requirements_baselines.py -v`
Expected: FAIL — `test_v16_pins_werkzeug_below_3_1` fails with `'==2.3.8' != '==3.0.6'`

- [ ] **Step 3: Curate the baselines**

For each version, take the real file as the source of truth:

```bash
for v in 16 17 18 19; do
  cp "$HOME/gitbase/v$v/v$v-dev/dev${v}_native/requirements.txt" \
     "odoodev/data/examples/v$v/requirements.base.txt"
done
git diff --stat odoodev/data/examples
```

Then review each file by hand — this is curation, not a copy job:

1. **Remove anything machine- or customer-specific.** Local paths, `-e` editable installs, private index URLs. (A scan of the four current files found none, but re-check after copying.)
2. **Fix the v16 contradiction.** The footnote block at the end of the real v16 file claims *"lxml stays at 5.3.1 and Werkzeug at 3.1.3 on purpose"*, while line 44 pins `Werkzeug==3.0.6` and explains why it must stay below 3.1. The pin is correct — the installed venv runs 3.0.6 and Odoo 16 does not import with 3.1.x. Correct the footnote to say 3.0.6.
3. **Keep every comment.** They are the reason the pins exist (CVE references, "KEEP: why"). The merge preserves them; losing them here loses them everywhere.
4. **Keep the deliberate v16 extras** the file's own comment block documents as intentionally retained: `msal`, `nextcloud-api-wrapper`, `deepl`, `dicttoxml`, `xmltodict`, `xmlschema`, `pandas`, `openai`, `odoorpc-toolbox`, `ebaysdk`, `pydot`. These are Equitania-wide, not machine-local, so they belong in the baseline.

- [ ] **Step 4: Verify the curation lands correctly**

Run: `pytest tests/test_requirements_baselines.py -v`
Expected: all passed

Then verify against a real environment without touching it, using a copy:

```bash
mkdir -p /tmp/adopt-check/dev16_native
cp ~/gitbase/v16/v16-dev/dev16_native/requirements.txt /tmp/adopt-check/dev16_native/
python - <<'PY'
from odoodev.core.example_templates import get_base_requirements_path
from odoodev.core.requirements_merge import parse_requirements

base = {l.requirement.merge_key: l.requirement
        for l in parse_requirements(get_base_requirements_path("16").read_text(encoding="utf-8"))
        if l.requirement}
real = {l.requirement.merge_key: l.requirement
        for l in parse_requirements(open("/tmp/adopt-check/dev16_native/requirements.txt", encoding="utf-8").read())
        if l.requirement}

deviations = [k for k, r in real.items() if k not in base or base[k].specifier != r.specifier]
print(f"v16 would put {len(deviations)} entries into the overlay: {[k[0] for k in deviations]}")
PY
```
Expected: 0 entries, or only entries you consciously decided are machine-local.
Repeat for v17, v18, v19.

- [ ] **Step 5: Commit**

```bash
git add odoodev/data/examples tests/test_requirements_baselines.py
git commit -m "[CHG] baselines: curate v16-v19 from the maintained environments"
```

---

### Task 12: Version bump and documentation

**Files:**
- Modify: `odoodev/__init__.py` (`__version__ = "0.63.0"`)
- Modify: `pyproject.toml` (`version = "0.63.0"`)
- Modify: `RELEASE_NOTES.md`
- Modify: `CLAUDE.md`
- Modify: `README.md`
- Modify: `usage/AGENT.md`

**Interfaces:**
- Consumes: everything from Tasks 1–11.
- Produces: nothing importable.

- [ ] **Step 1: Bump the version in both places**

`odoodev/__init__.py`:
```python
__version__ = "0.63.0"
```

`pyproject.toml`:
```toml
version = "0.63.0"
```

- [ ] **Step 2: Write the release notes entry**

Prepend to `RELEASE_NOTES.md`, below the `# Release Notes` heading, following the existing style (What changed, why it mattered, concrete file references):

```markdown
## Version 0.63.0 (DD.MM.YYYY)

### Added
- **Requirements are now a baseline plus a machine-local overlay.** Each version
  keeps a shipped baseline (`odoodev/data/examples/vXX/requirements.base.txt`)
  and a local `requirements.local.txt` that odoodev never overwrites; the
  effective `requirements.txt` is generated from both. Overlay entries replace
  their baseline counterpart in place, matched on `(PEP 503 name, environment
  marker)` — v17 pins six packages twice, distinguished only by a
  `python_version` marker, and a name-only match would have dropped one of each.
- **New command group `odoodev requirements`**: `sync` (regenerate, `--all` for
  every configured version, `--check` for CI), `diff` (baseline vs. overlay vs.
  installed, `--json`), `adopt` (one-time lossless migration of a hand-maintained
  file, keeping a `requirements.txt.pre-adopt` backup).
- **A held-back pin is now reported.** When an overlay pin blocks a baseline
  bump, every sync says so (`Werkzeug: overlay holds 3.0.6 back (base: 3.1.3)`)
  instead of letting a security update disappear silently. The same applies when
  an overlay entry drops the baseline's extras.

### Changed
- `odoodev start` regenerates `requirements.txt` when the shipped baseline moved
  on, immediately before the existing SHA256 freshness check — so a baseline
  update flows into the familiar *"Update packages now?"* prompt without any
  hand-editing of package lines.
- `odoodev init` seeds an empty annotated overlay and generates the effective file.
- `requirements.txt` was removed from `example_templates._get_template_mapping()`.
  Previously `init` offered *"Replace requirements.txt with bundled version?"*,
  and answering yes ran `shutil.copy2` over the local file — an all-or-nothing
  overwrite that discarded every local pin. The bundled files were renamed to
  `requirements.base.txt` to make the role explicit.
- The four shipped baselines were re-curated from the maintained environments.
  The v16 bundle had drifted far enough to pin `Werkzeug==2.3.8` while the real
  environment ran `3.0.6`.

### Safety
- `requirements sync` refuses to run when the existing `requirements.txt` was not
  generated by odoodev and no overlay exists, and points at `adopt`. Without that
  guard a sync would have replaced a hand-maintained file with the bare baseline
  — roughly 20 packages on v16.
```

Use the actual current date in DD.MM.YYYY format.

- [ ] **Step 3: Update `CLAUDE.md`**

In the "Key modules" list, after the `core/venv_manager.py` entry:

```markdown
- **`core/requirements_merge.py`** — Pure requirements merging (v0.63.0): `parse_requirements`,
  `canonical_name` (PEP 503), `merge_requirements`, `render_requirements`. Merge key is
  `(name, environment marker)` — v17 pins six packages twice under different `python_version`
  markers. No resolution and no `packaging` dependency: uv resolves, this only maps and emits.
- **`core/requirements_sync.py`** — Filesystem layer for the baseline/overlay model (v0.63.0):
  paths, the overwrite guard (`sync_allowed` — refuses on a hand-maintained file without an
  overlay), `sync_version`, `ensure_generated_requirements` (called by `start` before the hash
  check), `three_way_report`, `adopt_candidates`.
```

Add a `requirements` row to the Commands table:

```markdown
| `requirements` | sync / diff / adopt — baseline (wheel) + `requirements.local.txt` overlay → generated `requirements.txt` (v0.63.0) |
```

Update the "Required files (user-provided)" table: `requirements.txt` is now generated;
`requirements.local.txt` is the user-provided file.

Update the "Start prerequisites" list: step 7 now runs after an automatic regeneration check.

- [ ] **Step 4: Update `README.md` and `usage/AGENT.md`**

`README.md`: add the `requirements` group to the command overview (bilingual DE/EN, matching the
file's existing structure), and describe the three-file model in one short section.

`usage/AGENT.md`: add the `requirements` commands with their flags and the `diff --json` contract,
matching the density of the neighbouring entries. This file is served by
`odoodev capability-card`, so keep it terse and complete rather than narrative.

- [ ] **Step 5: Verify the whole suite and commit**

Run: `pytest && ruff check . && ruff format --check . && mypy odoodev && uv build`
Expected: all tests pass, ruff clean, mypy clean, build succeeds

```bash
git add odoodev/__init__.py pyproject.toml RELEASE_NOTES.md CLAUDE.md README.md usage/AGENT.md
git commit -m "[CHG] version 0.63.0: requirements baseline/overlay model"
```

- [ ] **Step 6: Update the odoo-dev skill**

The skill lives outside this repository at `~/.claude/skills/odoo-dev/SKILL.md`. Add the two new
core modules to the project-structure tree, the `requirements` group to the CLI command table, and
a short section on the baseline/overlay model next to "Venv Management with Hash Tracking". Note in
the hash section that the SHA256 now tracks a *generated* file, which is what makes a baseline
update surface as the familiar update prompt.

---

## Notes for the executor

- **Task order matters.** Tasks 1–3 build the pure core, 4–5 the filesystem layer, 6–8 the CLI,
  9–10 the integration, 11 the content, 12 the release. Task 11 can be done earlier if you want to
  see real data flowing through, but its test depends on Tasks 1 and 4.
- **Task 11 is judgement work, not mechanical.** Copying the four files is one command; deciding
  what belongs in a baseline shipped to every machine is the actual task. When unsure whether an
  entry is Equitania-wide or machine-local, leave it in the baseline — `adopt` lets each machine
  override it, whereas a missing baseline entry is invisible.
- **Do not touch `pull` or `repos`.** They call `copy_example_templates()` only on the error path
  (when `repos.yaml` is missing), not as a regular step, so they are not sync hook points. Adding a
  sync there would run it on every git pull, which is not what spec §6.3 asks for.
- **Never weaken the guard in `sync_allowed`** to make a test pass. It is the single thing standing
  between a routine sync and a lost requirements file.
