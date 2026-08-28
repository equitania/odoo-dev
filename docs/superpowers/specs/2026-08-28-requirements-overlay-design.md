# Requirements Base/Overlay Model — Design

- **Date:** 28.08.2026
- **Status:** Approved, not yet implemented
- **Target version:** odoodev 0.63.0
- **Scope:** `odoodev/core/requirements_merge.py` (new), `odoodev/commands/requirements.py` (new),
  `odoodev/core/example_templates.py`, `odoodev/commands/start.py`, `odoodev/commands/init_cmd.py`,
  `odoodev/data/examples/v16..v19/`

## 1. Problem

Every version owns exactly one `requirements.txt` at
`vXX-dev/devXX_native/requirements.txt`. odoodev knows a single bit about it:
`venv_manager.check_requirements_changed()` compares the SHA256 of the whole file against
`.venv/.requirements.sha256`. The answer is "changed / unchanged" — never *which* package.

There is no separation between a shared baseline and machine-local additions. Two consequences:

1. **Rollout overwrites local work.** `odoodev init` calls `copy_example_templates()`, which
   detects "Bundled template differs from existing" via `filecmp` and offers
   *"Replace requirements.txt with bundled version?"* — an all-or-nothing `shutil.copy2` over the
   local file. Everything the developer or a customer site added is gone.
2. **The baseline drifts silently.** The bundled v16 baseline pins `Werkzeug==2.3.8`; the real
   `~/gitbase/v16/v16-dev/dev16_native/requirements.txt` pins `Werkzeug==3.0.6`, and its own
   footnote block claims "Werkzeug at 3.1.3 on purpose". Three states, no reconciliation. The
   installed venv has 3.0.6 — the file is right, its comment is not.

The `requirements.txt` also lives inside the `vXX-dev` git repository
(`git@gitlab.ownerp.io:v16-odoo/v16-dev.git`), so a centrally changed baseline additionally
arrives as a merge conflict on every machine that customised it.

## 2. Decisions

| Question | Decision |
|---|---|
| Where does the baseline live? | In the odoodev wheel, `odoodev/data/examples/vXX/` (as today). Distribution via `uvpublish` → `uv tool upgrade odoodev-equitania`. |
| How is local deviation recorded? | A separate `requirements.local.txt`; odoodev generates the effective `requirements.txt` from baseline + overlay. |
| How do we migrate? | Re-curate the four bundles from the real files first, then reconcile per machine interactively via `adopt`. |
| How automatic is an update? | Generation is automatic; installation stays behind the existing confirmation prompt. |

Rejected alternatives, for the record: marker comments (`# odoodev:keep`) in a single file — a
forgotten marker reproduces exactly the silent overwrite we are removing; a report-only tool —
leaves the actual rollout across four versions as manual work; a separate requirements git repo —
adds a clone step and SSH access on every machine.

## 3. File model

| File | Location | Owner | Git |
|---|---|---|---|
| `requirements.base.txt` | wheel: `odoodev/data/examples/vXX/` | odoodev release | odoo-dev repo |
| `requirements.local.txt` | `vXX-dev/devXX_native/` | developer / customer site | `vXX-dev` repo, never written by odoodev after creation |
| `requirements.txt` | `vXX-dev/devXX_native/` | **generated** | `vXX-dev` repo, not hand-edited |

The generated file keeps today's path and name. `install_requirements()`,
`store_requirements_hash()` and `venv setup` stay untouched — they still see one
`requirements.txt`.

The bundled file is renamed from `requirements.txt` to `requirements.base.txt` inside
`odoodev/data/examples/vXX/` to make the role explicit and to keep it out of the
`_get_template_mapping()` copy path (see §6.2).

## 4. Merge semantics

### 4.1 Key

The merge key is **`(PEP 503 normalised name, marker text)`**, never the name alone.

Normalisation: `re.sub(r"[-_.]+", "-", name).lower()` — so `Werkzeug` = `werkzeug`,
`psycopg2-binary` = `psycopg2_binary`. The marker text is normalised for whitespace and quote
style only, then compared as a string.

This is mandatory, not defensive: v17 declares six packages twice, each pair distinguished only
by a `python_version` marker.

```
Babel==2.10.3 ; python_version < '3.13'
Babel==2.17.0 ; python_version >= '3.13'
zeep==4.2.1   ; python_version < '3.13'
zeep==4.3.1   ; python_version >= '3.13'
```

The full list of doubled packages in v17: `Babel`, `zeep`, `gevent`, `greenlet`, `freezegun`,
`psycopg2-binary`. A name-only key would drop one line of each pair.

### 4.2 No resolution, no new dependency

The merge maps and emits; it never resolves. `uv` does the resolving, as it does today.
That reduces the parser to roughly 30 lines (name, extras, specifier, marker, trailing comment)
and needs no `packaging` dependency. Writing a real requirements *evaluator* by hand would be a
mistake; writing a *mapper* is not.

The parser must not assume `==`. Unpinned and range-pinned lines are normal and common:
v18 has 28 of them (`pytz`, `PyYAML>=6.0.1,<7.0.0`, `eq-chatbot-core[rag,security,docs]>=3.0.0`,
`fsspec>=2024.5.0`).

### 4.3 Structure-preserving output

The baseline defines order and comment blocks. An overlay entry replaces its baseline line
**in place**, carrying a `[local]` provenance marker. Overlay entries without a baseline
counterpart are appended in a dedicated block at the end of the file.

This matters because the comments are the actual knowledge: v16 carries about 40 comment lines,
v18 and v19 about 60 each — CVE justifications and "KEEP: why" notes. Re-sorting the file would
detach block comments from their lines and make the git diff of a baseline update unreadable.

### 4.4 Generated format

```
# GENERATED by odoodev 0.63.0 — do not edit.
# base: v16 bundle sha256:a3f1…  local: requirements.local.txt sha256:7b2c…
# Edit requirements.local.txt instead, then: odoodev requirements sync 16

Babel==2.16.0
cryptography==46.0.7          # CVE-2026-39892 (buffer overflow)
Werkzeug==3.0.6               # [local] MUST stay < 3.1: odoo/http.py:260 reads
                              # [local] werkzeug.__version__, removed in 3.1

# ── local additions ──────────────────────────────────────────
msal==1.31.0                  # [local] v16-microsoft365
```

The `base:` hash in the header is the single source of truth for "is this file stale?" — see §6.1.

### 4.5 Warnings

Two situations are silent by construction and must be reported on every `sync` and `diff`,
without blocking:

- **An overlay pin holds back a baseline bump.** This is how a security update quietly fails to
  arrive: `Werkzeug   overlay holds 3.0.6 back (base: 3.1.3)`.
- **An overlay entry drops the baseline's extras**, e.g. `eq-chatbot-core[rag,security,docs]`
  → `eq-chatbot-core`. A functional loss that otherwise only surfaces at runtime.

An overlay entry replaces the baseline line completely, extras included; the overlay owns its
line. The warning exists because that is easy to do by accident.

## 5. Commands

New Click group `requirements` in `odoodev/cli.py`.

| Command | Behaviour |
|---|---|
| `odoodev requirements diff [VERSION] [--json]` | Three-way report: baseline / overlay / installed (`uv pip freeze` from the version's venv). Read-only. `--json` follows the existing single-line contract used by `venv check --json`. |
| `odoodev requirements sync [VERSION] [--all] [--check]` | Regenerates `requirements.txt`. `--all` covers every configured version (`available_versions()`) in one run. `--check` writes nothing and exits 1 if the file is stale (CI / scripted use). |
| `odoodev requirements adopt [VERSION]` | One-time migration: diffs the existing `requirements.txt` against the baseline and builds `requirements.local.txt` interactively, entry by entry. |

`--all` is the core of the requirement "I cannot adjust everything by hand": one invocation,
every configured version.

## 6. Integration

### 6.1 `start`

In `_run_preflight`, immediately **before** the existing hash check
(`commands/start.py:753`):

The header of the generated file carries the SHA256 of the bundle it was built from. If that
differs from the bundle of the running odoodev version, regenerate and print the change table.
The existing mechanism then takes over unchanged: new file hash → *"requirements.txt has changed
since last install — Update packages now?"*.

```
$ odoodev start 16

  Base requirements updated (odoodev 0.62.2 → 0.63.0)
    cryptography  46.0.0 → 46.0.7   CVE-2026-39892
    idna          3.11   → 3.15     CVE-2026-45409
    Werkzeug      overlay holds 3.0.6 back (base: 3.1.3)
  requirements.txt regenerated.

  requirements.txt has changed since last install
  Update packages now? [y/N]
```

No new confirmation prompt is introduced. Generation is silent-but-reported; installation keeps
its existing gate, so a running customer environment is never rebuilt unasked.

### 6.2 `init`

`requirements.txt` must be **removed** from `_get_template_mapping()` in
`core/example_templates.py`. Otherwise `init` keeps asking *"Replace requirements.txt with
bundled version?"* and `replace_example_template()`'s `shutil.copy2` flattens the generated file —
the exact overwrite this design removes. `repos.yaml`, `postgresql.conf` and the Odoo conf
template keep their current behaviour.

On a first `init` of a fresh environment, odoodev instead creates an empty
`requirements.local.txt` with an explanatory header and runs `sync` once.

### 6.3 Not integrated

`pull` and `repos` call `copy_example_templates()` only on the error path (when `repos.yaml` is
missing), not as a regular step. They are not sync hook points and stay unchanged.

## 7. Safety

**`sync` refuses to run when the existing `requirements.txt` has no `GENERATED` header and no
overlay file exists**, and points to `adopt`.

Without this guard, a `sync` on an existing machine would replace the hand-maintained file with
the bare baseline and lose everything that was never in the bundle — for v16 roughly 20 packages
in one step. `uv pip install -r` does not uninstall, so the venv would survive; the *declaration*
would not, and the next clean setup would be broken.

A missing `requirements.local.txt` next to a file that *does* carry the `GENERATED` header is
not an error: the overlay is simply empty and the generated file equals the baseline. The guard
only triggers when both signals are absent.

`adopt` writes the previous file to `requirements.txt.pre-adopt` before it writes anything.
That is the rollback path.

## 8. Migration

**Phase 1 — once, in the odoo-dev repo.** Re-curate the four bundles from the real files,
comments included. What holds for all Equitania installations becomes baseline — including the
deliberate v16 extras (`msal`, `nextcloud-api-wrapper`, `deepl`, `dicttoxml`, `xmltodict`,
`xmlschema`, `pandas`, `openai`, `odoorpc-toolbox`, `ebaysdk`, `pydot`) that the file's own
comment block documents as intentionally kept. After this, the baseline is current and a fresh
`adopt` finds almost no deviation on a normal machine.

**Phase 2 — per machine.** `odoodev requirements adopt 16`, and so on. Walks the remaining
deviations, one decision per entry (baseline or overlay), done. The machine is then in automatic
mode.

The Werkzeug case lands correctly: `Werkzeug==3.0.6` with its justification goes into the v16
overlay, and every future sync reports *"overlay holds 3.0.6 back (base: 3.1.3)"* instead of
silently bumping it or silently forgetting it.

## 9. Structure and tests

`odoodev/core/requirements_merge.py` — pure functions, no side effects: parse, map, emit,
compare. `odoodev/commands/requirements.py` handles I/O and prompts. This mirrors the split
between `playbook_schema.py` / `playbook_builder.py` and `playbook_cmd.py`, which works well and
makes the merge testable without a filesystem.

Tests in `tests/test_requirements_merge.py`:

- Fixtures taken from the four real files. The six v17 doubles are the regression test that
  fails immediately on a name-only key.
- Golden-file tests for the generated output, including comment placement and the
  `local additions` block.
- Unpinned and range-pinned lines survive a round trip (`pytz`, `PyYAML>=6.0.1,<7.0.0`).
- Extras-dropping and held-back-bump warnings fire on the right inputs.
- `sync` refuses on a non-generated `requirements.txt` without an overlay.
- CLI level in `tests/test_requirements_cmd.py` via `CliRunner`: `diff --json` contract,
  `sync --check` exit codes, `sync --all` across the configured versions.

## 10. Non-goals

No dependency resolution, no version suggestions, no vulnerability scanning. The tool maps and
emits; resolving stays with `uv`. Reporting which pins are outdated is a separate concern and
belongs to `doctor`, not here.

## 11. Risks

| Risk | Mitigation |
|---|---|
| `sync` flattens a hand-maintained file | Header guard (§7) plus `requirements.txt.pre-adopt` backup |
| Re-curated baseline drops a package someone depends on | Phase 1 is a curation pass over the real files, not a reset to the old bundles; `adopt` shows every remaining deviation before writing |
| Overlay pin masks a security bump | Reported on every `sync` and `diff` (§4.5) |
| Generated file churns the `vXX-dev` git diff | Structure-preserving emit (§4.3) keeps diffs limited to changed lines |
| Parser mishandles an exotic requirement form | The four real files contain no `-r`/`-c`/`-e`/URL/git requirements; if one appears later, it is passed through verbatim as an unkeyed line |
