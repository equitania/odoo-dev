# `db update --output ndjson` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `odoodev db update … --output ndjson` streams one JSON event per line (plan, start, issue, result, summary, interrupted, error) so the desktop GUI can show live per-database progress.

**Architecture:** The events are emitted from the callbacks that already drive the Rich progress bar (`execute_updates`' `on_issue`/`on_result`, plus a new `on_start`) through a small `_EventSink`. In NDJSON mode stdout carries only events; all human-readable output is redirected to stderr through a tee that remembers the last line, so a preflight `SystemExit` can still be reported as an `error` event.

**Tech Stack:** Python 3.12, Click 8.3, Rich, pytest + `click.testing.CliRunner` (separate `result.stdout` / `result.stderr`), uv, ruff, mypy.

**Spec:** `/Users/picard/gitbase/odoodev-gui/docs/superpowers/specs/2026-09-15-db-update-gui-design.md` — section "1. CLI contract — odoodev 0.69.0".

## Global Constraints

- Repository: `/Users/picard/gitbase/PyPi-Projects/odoo-dev`; run everything with `uv run --quiet …`.
- Target version: **0.69.0** (`pyproject.toml`, `odoodev/__init__.py`, `uv.lock`); release-notes date from `date +%d.%m.%Y`, never copied.
- Event names exactly: `plan`, `start`, `issue`, `result`, `summary`, `interrupted`, `error`.
- In NDJSON mode stdout contains **only** event lines, each flushed immediately; every other message goes to stderr.
- NDJSON requires an explicit selection (`-n/--name`, `--all` or `--stale`); `-m` is refused; `--json` together with `--output ndjson` is refused. Implies `--yes`.
- Exit codes: 0 success / nothing to do / dry run, 1 any failure or preflight error, 130 interrupted.
- Code style: line length 120, double quotes, ruff rules E,W,F,I,B,UP,S; commit prefixes `[ADD]`/`[CHG]`/`[FIX]`.
- Docs in English. This repo is mirrored to GitHub: no customer names, hostnames, IPs or e-mail addresses in code, tests, docs or commit messages.
- Do not change the behaviour of the text mode, `--json`, `pull --update` or the `db.update` playbook step.

## File Structure

- Modify `odoodev/commands/db_update.py` — `execute_updates` gains `on_start`; new `_EventSink`, `_LastLineTee`, `_fail`, `_run_ndjson`, `_run_with_events`; `_update_databases` gains `sink`; `update_databases` gains `ndjson`; Click option `--output`.
- Modify `tests/test_db_update.py` — new classes `TestExecuteUpdatesCallbacks`, `TestNdjson`, `TestNdjsonFailures`.
- Modify `usage/AGENT.md`, `RELEASE_NOTES.md`, `README.md`, `pyproject.toml`, `odoodev/__init__.py`, `uv.lock`.

---

### Task 1: `on_start` callback in `execute_updates`

**Files:**
- Modify: `odoodev/commands/db_update.py` (function `execute_updates`)
- Test: `tests/test_db_update.py`

**Interfaces:**
- Consumes: existing `env` fixture and `_FakeRunner` in `tests/test_db_update.py` (the runner echoes the `log_path` it receives into `UpdateResult.log_path`).
- Produces: `execute_updates(..., on_issue=None, on_result=None, on_start: Callable[[str, int, int, str], None] | None = None)` — called as `on_start(database, index, total, log_path)` before each database, `index` 1-based.

- [ ] **Step 1: Write the failing test** — append to `tests/test_db_update.py`:

```python
class TestExecuteUpdatesCallbacks:
    def test_on_start_precedes_each_database_with_its_log_path(self, env, tmp_path):
        cfg, runner = env
        seen: list[tuple[str, int, int, str]] = []
        results = mod.execute_updates(
            "19",
            {"venv_python": "py"},
            ["v19_a", "v19_b"],
            "all",
            {"server": "abc"},
            {"databases": {}},
            str(tmp_path / "state.yaml"),
            on_start=lambda db, index, total, log: seen.append((db, index, total, log)),
        )
        assert [(s[0], s[1], s[2]) for s in seen] == [("v19_a", 1, 2), ("v19_b", 2, 2)]
        assert [s[3] for s in seen] == [r.log_path for r in results]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run --quiet pytest -q -p no:cacheprovider --no-cov tests/test_db_update.py::TestExecuteUpdatesCallbacks`
Expected: FAIL — `TypeError: execute_updates() got an unexpected keyword argument 'on_start'`

- [ ] **Step 3: Implement** — in `execute_updates`, add the parameter after `on_result` and compute the log path once per database:

```python
    on_result: Callable[[UpdateResult], None] | None = None,
    on_start: Callable[[str, int, int, str], None] | None = None,
) -> list[UpdateResult]:
    """Run ``-u <modules>`` on every target in order; record clean ``all`` runs.

    ``on_start(db, index, total, log_path)`` fires before each database (index
    1-based), ``on_issue(db, level, text)`` receives the forwarded
    warnings/errors, ``on_result`` every finished database. The state file is
    saved after each clean run so an aborted batch keeps what it achieved.
    """
    results: list[UpdateResult] = []
    total = len(targets)
    for index, db_name in enumerate(targets, start=1):
        log_path = log_path_for(version, db_name)
        if on_start is not None:
            on_start(db_name, index, total, log_path)
        per_db_issue: IssueCallback | None = None
        if on_issue is not None:
            per_db_issue = functools.partial(on_issue, db_name)
        result = run_module_update(
            db_name,
            modules,
            invocation,
            log_path,
            version=version,
            on_issue=per_db_issue,
            timeout=timeout,
        )
```

(the rest of the loop body — `results.append`, `record_update`, `on_result`, `stop_on_error` — stays unchanged)

- [ ] **Step 4: Run the tests**

Run: `uv run --quiet pytest -q -p no:cacheprovider --no-cov tests/test_db_update.py`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add odoodev/commands/db_update.py tests/test_db_update.py
git commit -m "[ADD] db update: on_start callback in execute_updates"
```

---

### Task 2: NDJSON event stream (plan, start, issue, result, summary)

**Files:**
- Modify: `odoodev/commands/db_update.py`
- Test: `tests/test_db_update.py`

**Interfaces:**
- Consumes: `execute_updates(..., on_start=...)` from Task 1; `UpdateResult.to_dict()` (keys `database, ok, exit_code, duration_s, warnings, errors, last_error, timed_out, log`).
- Produces:
  - `class _EventSink` with `out`, `current: str | None`, `sent: set[str]`, `emit(event: str, **fields) -> None`.
  - `_update_databases(..., json_out, sink: _EventSink | None = None)`.
  - `update_databases(..., ndjson: bool = False)`; `_run_ndjson(version, names, multi, select_all, name_filter, stale, modules, stop_on_error, timeout, dry_run, as_json) -> int`.
  - Click option `--output [text|ndjson]` (default `text`).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_db_update.py`:

```python
def _events(result) -> list[dict]:
    """Every stdout line must be a JSON object — json.loads raises otherwise."""
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


class TestNdjson:
    def test_help_lists_output_option(self):
        result = CliRunner().invoke(cli, ["db", "update", "--help"])
        assert "--output" in result.output and "ndjson" in result.output

    def test_event_order_for_a_mixed_run(self, env):
        cfg, runner = env
        runner.outcomes["v19_a"] = {"warnings": 1, "issues": [("WARNING", "odoo.addons.base: dubious")]}
        runner.outcomes["v19_b"] = {"exit_code": 2, "errors": 1, "last_error": "odoo.registry: dead"}
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "--output", "ndjson"])
        assert result.exit_code == 1, result.output
        events = _events(result)
        assert [e["event"] for e in events] == [
            "plan", "start", "issue", "result", "start", "result", "start", "result", "summary",
        ]  # fmt: skip
        assert events[0] == {
            "event": "plan",
            "version": "19",
            "modules": "all",
            "targets": [
                {"database": "v19_a", "reason": "never updated"},
                {"database": "v19_b", "reason": "never updated"},
                {"database": "v19_c", "reason": "never updated"},
            ],
            "skipped_current": [],
            "server_running": False,
        }
        starts = [(e["database"], e["index"], e["total"]) for e in events if e["event"] == "start"]
        assert starts == [("v19_a", 1, 3), ("v19_b", 2, 3), ("v19_c", 3, 3)]
        assert events[2] == {"event": "issue", "database": "v19_a", "level": "WARNING", "text": "odoo.addons.base: dubious"}
        failed = events[5]
        assert set(failed) == {
            "event", "database", "ok", "exit_code", "duration_s", "warnings", "errors", "last_error", "timed_out", "log",
        }  # fmt: skip
        assert failed["database"] == "v19_b" and failed["ok"] is False and failed["exit_code"] == 2
        assert failed["last_error"] == "odoo.registry: dead"
        summary = events[-1]
        assert summary["exit_code"] == 1 and len(summary["results"]) == 3 and summary["skipped_current"] == []

    def test_dry_run_emits_the_plan_only(self, env):
        cfg, runner = env
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "--dry-run", "--output", "ndjson"])
        assert result.exit_code == 0, result.output
        assert [e["event"] for e in _events(result)] == ["plan"]
        assert runner.calls == []

    def test_nothing_to_do_emits_plan_and_empty_summary(self, env):
        cfg, runner = env
        CliRunner().invoke(cli, ["db", "update", "19", "--all", "-y"])
        runner.calls.clear()
        result = CliRunner().invoke(cli, ["db", "update", "19", "--stale", "--output", "ndjson"])
        assert result.exit_code == 0, result.output
        events = _events(result)
        assert [e["event"] for e in events] == ["plan", "summary"]
        assert events[0]["targets"] == [] and events[0]["skipped_current"] == ["v19_a", "v19_b", "v19_c"]
        assert events[1] == {
            "event": "summary", "results": [], "skipped_current": ["v19_a", "v19_b", "v19_c"], "exit_code": 0,
        }  # fmt: skip
        assert runner.calls == []

    def test_stdout_carries_only_events(self, env):
        cfg, runner = env
        result = CliRunner().invoke(cli, ["db", "update", "19", "-n", "v19_a", "-n", "nope", "--output", "ndjson"])
        assert result.exit_code == 0, result.output
        assert [e["event"] for e in _events(result)] == ["plan", "start", "result", "summary"]
        assert "does not exist" in result.stderr
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --quiet pytest -q -p no:cacheprovider --no-cov tests/test_db_update.py::TestNdjson`
Expected: FAIL — `No such option: --output` (exit code 2) and the help assertion fails.

- [ ] **Step 3: Implement the sink and the NDJSON entry point** — in `odoodev/commands/db_update.py`:

Add `import json` to the top-level imports (keep alphabetical order: `contextlib, functools, json, os, sys`).

Insert above the `# Orchestration` banner:

```python
class _EventSink:
    """One JSON object per line on the real stdout (``--output ndjson``).

    Flushes after every event — a GUI reads the pipe live. Remembers which
    events it sent and which database is running, for the failure paths.
    """

    def __init__(self, out: Any) -> None:
        self.out = out
        self.current: str | None = None
        self.sent: set[str] = set()

    def emit(self, event: str, **fields: Any) -> None:
        self.out.write(json.dumps({"event": event, **fields}) + "\n")
        self.out.flush()
        self.sent.add(event)
```

Change `update_databases`: add the parameter `ndjson: bool = False` after `yes: bool = False`, extend the docstring with one sentence (`With ndjson stdout carries one JSON event per line.`), and make the first statement of the body:

```python
    if ndjson:
        return _run_ndjson(
            version, names, multi, select_all, name_filter, stale, modules, stop_on_error, timeout, dry_run, as_json
        )
```

Add below `update_databases`:

```python
def _run_ndjson(
    version: str,
    names: tuple[str, ...],
    multi: bool,
    select_all: bool,
    name_filter: str | None,
    stale: bool,
    modules: str,
    stop_on_error: bool,
    timeout: int,
    dry_run: bool,
    as_json: bool,
) -> int:
    sink = _EventSink(sys.stdout)
    with contextlib.redirect_stdout(sys.stderr):
        return _update_databases(
            version, names, multi, select_all, name_filter, stale, modules, stop_on_error, timeout, dry_run, False,
            True, json_out=sink.out, sink=sink,
        )  # fmt: skip
```

(`as_json` is used in Task 3.)

- [ ] **Step 4: Wire the events into `_update_databases`**

Signature: add `sink: "_EventSink | None" = None` after `json_out: Any,`. Then apply these edits inside the body:

1. Replace the selection check with a `machine` flag:

```python
    machine = as_json or sink is not None
    if machine and (multi or not (names or select_all or stale)):
        # A prompt would block a GUI/agent (and write to stdout) — refuse up front.
        flag = "--output ndjson" if sink is not None else "--json"
        print_error(f"{flag} needs an explicit selection: -n/--name, --all or --stale (no -m, no interactive select)")
        return 1
```

2. Directly after the stale filtering (after `targets = [db for db in targets if reasons[db] is not None]` block, before `if not targets:`):

```python
    if sink is not None:
        sink.emit(
            "plan",
            version=version,
            modules=modules,
            targets=[{"database": db, "reason": reasons.get(db)} for db in targets],
            skipped_current=skipped_current,
            server_running=server_running,
        )
```

3. In the `if not targets:` block, before `return 0`:

```python
        if sink is not None:
            sink.emit("summary", results=[], skipped_current=skipped_current, exit_code=0)
```

4. Change `if not as_json:` (the `_print_plan` call) to `if not machine:`.

5. Replace the whole execution block — from `    try:` down to and including the `        return 130` line of `except KeyboardInterrupt:` — with the following. The existing `    if as_json:` result branch that follows it stays unchanged; the new NDJSON summary branch is inserted directly before it:

```python
    try:
        if sink is not None:
            results = _run_with_events(
                sink, version, invocation, targets, modules, heads, state, state_path, timeout, stop_on_error
            )
        elif as_json:
            results = execute_updates(
                version, invocation, targets, modules, heads, state, state_path, timeout, stop_on_error
            )
        else:
            results = _run_with_progress(
                version, invocation, targets, modules, heads, state, state_path, timeout, stop_on_error
            )
    except KeyboardInterrupt:
        print_warning("Interrupted — the running odoo-bin was stopped; that database is not marked current.")
        return 130

    if sink is not None:
        rc = 0 if all(r.ok for r in results) else 1
        sink.emit(
            "summary", results=[r.to_dict() for r in results], skipped_current=skipped_current, exit_code=rc
        )
        return rc
```

(`    if as_json:` with `_emit_json(...)` and everything after it remains as it is.)

6. Add below `_run_with_progress`:

```python
def _run_with_events(
    sink: _EventSink,
    version: str,
    invocation: dict[str, Any],
    targets: list[str],
    modules: str,
    heads: dict[str, str],
    state: dict[str, Any],
    state_path: str,
    timeout: int,
    stop_on_error: bool,
) -> list[UpdateResult]:
    def on_start(db: str, index: int, total: int, log: str) -> None:
        sink.current = db
        sink.emit("start", database=db, index=index, total=total, log=log)

    def on_issue(db: str, level: str, text: str) -> None:
        sink.emit("issue", database=db, level=level, text=text)

    def on_result(result: UpdateResult) -> None:
        sink.current = None
        sink.emit("result", **result.to_dict())

    return execute_updates(
        version,
        invocation,
        targets,
        modules,
        heads,
        state,
        state_path,
        timeout,
        stop_on_error,
        on_issue=on_issue,
        on_result=on_result,
        on_start=on_start,
    )
```

- [ ] **Step 5: Add the Click option** — on `db_update`, directly after the `--json` option:

```python
@click.option(
    "--output",
    "output_format",
    type=click.Choice(["text", "ndjson"]),
    default="text",
    show_default=True,
    help="ndjson: one JSON event per line on stdout for GUIs (implies --yes; needs -n, --all or --stale)",
)
```

Add `output_format: str,` to the function parameters after `as_json: bool,` and pass `ndjson=output_format == "ndjson",` to `update_databases(...)` after `yes=yes,`.

- [ ] **Step 6: Run the tests**

Run: `uv run --quiet pytest -q -p no:cacheprovider --no-cov tests/test_db_update.py tests/test_module_update.py`
Expected: all PASS (existing text/`--json` tests unchanged)

- [ ] **Step 7: Lint and commit**

```bash
uv run --quiet ruff check odoodev tests && uv run --quiet ruff format --check odoodev tests
git add odoodev/commands/db_update.py tests/test_db_update.py
git commit -m "[ADD] db update --output ndjson: plan/start/issue/result/summary events"
```

---

### Task 3: NDJSON failure paths (error, interrupted, conflicts)

**Files:**
- Modify: `odoodev/commands/db_update.py`
- Test: `tests/test_db_update.py`

**Interfaces:**
- Consumes: `_EventSink`, `_run_ndjson`, `_update_databases(..., sink)` from Task 2.
- Produces: `_fail(sink, message, hint=None) -> int`; `class _LastLineTee` (`write`, `flush`, `isatty`, `encoding`, `last_line`); events `error {message}` and `interrupted {database}`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_db_update.py`:

```python
class TestNdjsonFailures:
    def test_env_not_ready_is_an_error_event(self, env, monkeypatch):
        monkeypatch.setattr(mod, "resolve_invocation", lambda c, e: None)
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "--output", "ndjson"])
        assert result.exit_code == 1
        assert _events(result) == [
            {
                "event": "error",
                "message": "Development environment not ready — need .venv, odoo-bin and a generated odoo_*.conf",
            }
        ]

    def test_systemexit_in_a_helper_becomes_an_error_event(self, env, monkeypatch):
        from odoodev.output import print_error

        def unreachable(version, params):
            print_error("PostgreSQL on 127.0.0.1:19432 is not reachable")
            raise SystemExit(1)

        monkeypatch.setattr("odoodev.commands.db._ensure_pg_reachable", unreachable)
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "--output", "ndjson"])
        assert result.exit_code == 1
        assert _events(result) == [{"event": "error", "message": "PostgreSQL on 127.0.0.1:19432 is not reachable"}]

    def test_interrupt_emits_interrupted_and_exits_130(self, env, monkeypatch):
        cfg, runner = env

        def flaky(db_name, *args, **kwargs):
            if db_name == "v19_b":
                raise KeyboardInterrupt
            return runner(db_name, *args, **kwargs)

        monkeypatch.setattr(mod, "run_module_update", flaky)
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "--output", "ndjson"])
        assert result.exit_code == 130
        events = _events(result)
        assert [e["event"] for e in events] == ["plan", "start", "result", "start", "interrupted"]
        assert events[-1] == {"event": "interrupted", "database": "v19_b"}

    @pytest.mark.parametrize("args", [["19", "--output", "ndjson"], ["19", "-m", "--output", "ndjson"]])
    def test_explicit_selection_required(self, env, args):
        result = CliRunner().invoke(cli, ["db", "update", *args])
        assert result.exit_code == 1
        events = _events(result)
        assert [e["event"] for e in events] == ["error"]
        assert "explicit selection" in events[0]["message"]

    def test_json_and_ndjson_cannot_be_combined(self, env):
        result = CliRunner().invoke(cli, ["db", "update", "19", "--all", "--json", "--output", "ndjson"])
        assert result.exit_code == 1
        assert _events(result) == [{"event": "error", "message": "--json and --output ndjson cannot be combined"}]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run --quiet pytest -q -p no:cacheprovider --no-cov tests/test_db_update.py::TestNdjsonFailures`
Expected: FAIL — no `error`/`interrupted` events are emitted yet (empty event lists / missing last event).

- [ ] **Step 3: Implement `_fail` and `_LastLineTee`** — insert next to `_EventSink`:

```python
class _LastLineTee:
    """stderr stand-in that forwards everything and remembers the last non-empty line.

    A helper that aborts with ``SystemExit`` (PostgreSQL unreachable, invalid
    names) has already printed its reason; NDJSON mode reports that line as the
    ``error`` event's message.
    """

    def __init__(self, target: Any) -> None:
        self.target = target
        self.last_line = ""
        self.encoding = getattr(target, "encoding", "utf-8") or "utf-8"

    def write(self, text: str) -> int:
        self.target.write(text)
        for line in text.splitlines():
            if line.strip():
                self.last_line = line.strip()
        return len(text)

    def flush(self) -> None:
        self.target.flush()

    def isatty(self) -> bool:
        return False


def _fail(sink: _EventSink | None, message: str, hint: str | None = None) -> int:
    """Report a preflight failure on stderr (and as an ``error`` event in NDJSON mode)."""
    print_error(message)
    if hint:
        print_info(hint)
    if sink is not None:
        sink.emit("error", message=message)
    return 1
```

- [ ] **Step 4: Route every early failure through `_fail`** — in `_update_databases` replace the four `print_error(...)`/`return 1` pairs and the env-not-ready block:

```python
    if sum([bool(names), multi, select_all]) > 1:
        return _fail(sink, "Choose only one selection mode: -n/--name, -m/--multi, or --all")
    if name_filter and names:
        return _fail(sink, "--filter cannot be combined with explicit -n/--name")
    if not modules.strip():
        return _fail(sink, "-u/--modules must not be empty")
    machine = as_json or sink is not None
    if machine and (multi or not (names or select_all or stale)):
        # A prompt would block a GUI/agent (and write to stdout) — refuse up front.
        flag = "--output ndjson" if sink is not None else "--json"
        return _fail(
            sink, f"{flag} needs an explicit selection: -n/--name, --all or --stale (no -m, no interactive select)"
        )
```

```python
    invocation = resolve_invocation(version_cfg, env_vars)
    if invocation is None:
        return _fail(
            sink,
            "Development environment not ready — need .venv, odoo-bin and a generated odoo_*.conf",
            hint=f"Run: odoodev venv setup {version}  /  odoodev repos {version}",
        )
```

In the `except KeyboardInterrupt:` block, before `return 130`:

```python
        if sink is not None:
            sink.emit("interrupted", database=sink.current)
```

- [ ] **Step 5: Catch conflicts and `SystemExit` in `_run_ndjson`** — replace its body:

```python
    sink = _EventSink(sys.stdout)
    if as_json:
        return _fail(sink, "--json and --output ndjson cannot be combined")
    tee = _LastLineTee(sys.stderr)
    with contextlib.redirect_stdout(tee), contextlib.redirect_stderr(tee):  # type: ignore[type-var]
        try:
            return _update_databases(
                version, names, multi, select_all, name_filter, stale, modules, stop_on_error, timeout, dry_run,
                False, True, json_out=sink.out, sink=sink,
            )  # fmt: skip
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            if code and not sink.sent & {"plan", "error"}:
                sink.emit("error", message=tee.last_line.removeprefix("[ERROR]").strip() or "preflight failed")
            return code
```

(If mypy does not flag the `redirect_*` calls, drop the `# type: ignore[type-var]` comment — run mypy in Step 6 and keep only what it needs.)

- [ ] **Step 6: Run tests, lint, types**

Run: `uv run --quiet pytest -q -p no:cacheprovider --no-cov tests/test_db_update.py tests/test_module_update.py tests/test_automation.py tests/test_pull.py`
Expected: all PASS
Run: `uv run --quiet ruff check odoodev tests && uv run --quiet ruff format --check odoodev tests && uv run --quiet mypy odoodev/commands/db_update.py`
Expected: `All checks passed!`, all files formatted, `Success: no issues found`

- [ ] **Step 7: Commit**

```bash
git add odoodev/commands/db_update.py tests/test_db_update.py
git commit -m "[ADD] db update --output ndjson: error and interrupted events, selection rules"
```

---

### Task 4: Documentation and version 0.69.0

**Files:**
- Modify: `usage/AGENT.md`, `RELEASE_NOTES.md`, `README.md`, `pyproject.toml`, `odoodev/__init__.py`, `uv.lock`

**Interfaces:**
- Consumes: the finished CLI behaviour from Tasks 1–3.
- Produces: version string `0.69.0` everywhere; documented NDJSON contract (the GUI plan relies on it).

- [ ] **Step 1: Version bump** — `pyproject.toml` `version = "0.69.0"`, `odoodev/__init__.py` `__version__ = "0.69.0"`, `uv.lock` the `version` line directly under `name = "odoodev-equitania"`. Verify: `uv lock --check --offline` → `Resolved … packages`.

- [ ] **Step 2: `usage/AGENT.md`**
  - Command table row `odoodev db update`: append `, --output text|ndjson` to the flag list.
  - "Machine-readable outputs": add after the `db update --json` bullet:

```markdown
- `odoodev db update --output ndjson` → one JSON event per line, flushed live (v0.69.0): `plan
  {version, modules, targets: [{database, reason}], skipped_current, server_running}`, per database
  `start {database, index, total, log}`, `issue {database, level: WARNING|ERROR|CRITICAL|RAW, text}`,
  `result {<same keys as --json results>}`, then `summary {results, skipped_current, exit_code}`.
  `--dry-run` → `plan` only; nothing to do → `plan` + empty `summary`. Failures before `plan` →
  exactly one `error {message}` (exit 1); SIGTERM/Ctrl+C → `interrupted {database}` (exit 130).
  Same selection rules as `--json`; stdout carries only events. Stop a run with SIGTERM, never
  SIGKILL — only then is Odoo's process group killed.
```

- [ ] **Step 3: `RELEASE_NOTES.md`** — insert above `## Version 0.68.1`, date from `date +%d.%m.%Y`:

```markdown
## Version 0.69.0 (DD.MM.YYYY)

### Added
- **`db update --output ndjson`** — live event stream for GUIs: one JSON object per line on stdout
  (`plan`, `start`, `issue`, `result`, `summary`, plus `error` for a failed preflight and
  `interrupted` on SIGTERM/Ctrl+C), each flushed immediately; all human-readable output goes to
  stderr. The events come from the same callbacks as the progress bar, so the stream and the text
  output cannot diverge. Requires an explicit selection like `--json`; `--json` and `--output
  ndjson` cannot be combined.
```

- [ ] **Step 4: `README.md`** — above `**Version 0.68.1:**` in the German changelog:

```markdown
**Version 0.69.0:**
- **Neu:** `odoodev db update --output ndjson` liefert den Fortschritt als Ereignisstrom (eine
  JSON-Zeile je Ereignis: Plan, Start, Warnung/Fehler, Ergebnis, Zusammenfassung, Abbruch) — die
  Grundlage für die Update-Ansicht der Desktop-GUI.
```

and above `**Version 0.68.1:**` in the English changelog:

```markdown
**Version 0.69.0:**
- **Added:** `odoodev db update --output ndjson` streams progress as events (one JSON line per
  event: plan, start, warning/error, result, summary, interruption) — the basis for the desktop
  GUI's update view.
```

- [ ] **Step 5: Full verification**

Run: `uv run --quiet pytest -q -p no:cacheprovider`
Expected: all tests PASS, `Required test coverage of 55% reached`
Run: `uv run --quiet ruff check odoodev tests && uv run --quiet ruff format --check odoodev tests && uv run --quiet mypy odoodev/commands/db_update.py odoodev/core/module_update.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add usage/AGENT.md RELEASE_NOTES.md README.md pyproject.toml odoodev/__init__.py uv.lock
git commit -m "[ADD] version 0.69.0: db update --output ndjson"
```

---

### Task 5: Release (only after the maintainer approves)

**Files:** none

**Interfaces:**
- Produces: tag `v0.69.0` on both remotes; the maintainer publishes to PyPI; the GUI plan starts only after 0.69.0 is on PyPI.

- [ ] **Step 1: Ask for approval** to tag and push. Do not continue without an explicit yes.

- [ ] **Step 2: Data scan of everything that will reach GitHub** (run under bash):

```bash
bash <<'SCRIPT'
set -euo pipefail
cd /Users/picard/gitbase/PyPi-Projects/odoo-dev
HITS=$(git log -p upstream/main..HEAD | grep -E '^\+' | grep -v '^+++' \
  | grep -Ei '[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+\.[a-z]{2,}|ownerp\.io|intra\.|/Users/' || true)
[ -z "$HITS" ] && echo "data scan clean" || { echo "$HITS"; exit 1; }
SCRIPT
```

Expected: `data scan clean` (Co-Authored-By lines use `noreply@anthropic.com`; if they match, confirm they are the only hits before continuing).

- [ ] **Step 3: Tag and push — tag individually, never `--tags`**

```bash
git tag -a v0.69.0 -m "Release v0.69.0"
git push origin main && git push upstream main
git push upstream refs/tags/v0.69.0 && git push origin refs/tags/v0.69.0
for R in origin upstream; do echo "$R $(git ls-remote $R refs/heads/main | cut -c1-7) $(git ls-remote $R 'refs/tags/v0.69.0^{}' | cut -c1-7)"; done
```

Expected: both remotes show the local `HEAD` short hash for `main` and the tag.

- [ ] **Step 4: Hand off PyPI publishing to the maintainer**, then verify once they report it published: `uv tool run --no-cache --refresh --from odoodev-equitania odoodev --version` → `odoodev, version 0.69.0`.
