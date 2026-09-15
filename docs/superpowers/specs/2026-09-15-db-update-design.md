# `odoodev db update` — module updates across many databases

**Date:** 15.09.2026 · **Target release:** 0.68.0 · **Status:** approved in chat, implementing

## Problem

A developer keeps several databases per Odoo version (v19: ten at the time of writing).
After every repository sync — Enterprise, OCA or our own `eq_*` modules — each of them
needs `odoo-bin -u all` before it runs cleanly again. Today that is one `odoodev start
-d <db> -u all` per database, by hand, and nothing tells the developer which databases
still need it.

## Decision

A new command `odoodev db update` runs `odoo-bin -c <conf> -d <db> -u <modules>
--stop-after-init` sequentially for a selection of databases, records which repository
commits every successful `-u all` was made against, and can therefore later update only
the databases that are *stale*. `odoodev pull --update` chains that onto a repository pull.
A playbook step `db.update` exposes the same core for unattended runs.

Rejected: a mere loop flag on `start` (`--all-databases`). It saves the same typing but
cannot answer "which database is out of date", so every run is a full run. Rejected:
parallel updates — ten concurrent `-u all` runs starve PostgreSQL and RAM on a laptop and
interleave their logs; sequential runs take 2–5 min per database and stay readable.
`--jobs` can be added later without changing the contract.

## Components

### `core/module_update.py` (new, pure logic + one subprocess runner)

- `collect_repo_heads(repos_config, base_path, version_cfg) -> dict[str, str]` — the
  `HEAD` commit of the server repo and every active repo in `repos.yaml` that exists on
  disk (`git rev-parse HEAD`). Missing directories are skipped, a failing git call is
  reported as `"?"` so it never equals a stored hash.
- Update state file `<native_dir>/.odoodev-update-state.yaml`:
  ```yaml
  databases:
    v19_example_test:
      updated_at: "2026-09-15T10:42:11"
      modules: all
      repos: {server: <sha>, v19-addons: <sha>, ...}
  ```
  `load_update_state`, `save_update_state`, `record_update`, `forget_database`.
- `stale_reason(state, db_name, heads) -> str | None` — `None` when the stored hashes
  equal the current ones; otherwise `"never updated"` or `"<n> repo(s) changed: a, b"`.
  A database with no entry is always stale. Only a successful `-u all` records state;
  a partial `-u eq_base` leaves the entry untouched (the database is still not in sync
  with the repos).
- `run_module_update(db_name, modules, invocation, log_path, on_issue, timeout) ->
  UpdateResult` — `Popen` with merged stdout/stderr, streams every line into the log
  file, parses it with `tui.log_parser.parse_line` and forwards WARNING / ERROR /
  CRITICAL entries (plus RAW continuation lines after an ERROR, i.e. tracebacks) to
  `on_issue`. INFO/DEBUG are file-only. Odoo 19 gets the same `--log-handler` mutes as
  `start`. `UpdateResult`: `db_name, ok, exit_code, duration_s, log_path, warnings,
  errors, last_error`. Timeout (default 3600 s) kills the process group and is a failure.

### `commands/db_update.py` (new; registered on the `db` group from `cli.py`)

`odoodev db update [VERSION] [-n DB]... [-m] [--all] [--filter TEXT] [--stale]
[-u MODULES] [--stop-on-error] [--timeout S] [--dry-run] [--json] [-y]`

- Selection rules copied from `db drop` (`-n` > `--all` > `-m` > single select), shared
  through a generalized `_resolve_multi_targets()` in `db.py`. `--stale` narrows any
  selection (or all databases when no other mode is given) to stale ones and shows the
  reason per database.
- Preflight: PostgreSQL reachable (`_ensure_pg_reachable`), dev env resolvable via
  `start.resolve_odoo_invocation` (venv, odoo-bin, generated conf) — otherwise exit 1
  with the usual hints. A warning if the Odoo port is busy: a running server needs a
  restart afterwards.
- Confirmation lists the targets with their stale reason; `-y` skips it.
- **Progress:** one Rich `Progress` bar — `n/total`, current database, elapsed time.
  Per database only the forwarded warnings and errors are printed above the bar as
  `WARN <logger>: <message>` / `ERROR <logger>: <message>` (timestamp/pid dropped,
  tracebacks indented). No INFO lines.
- **Summary table:** Database · Status · Duration · Warnings · Errors · Log. Exit 1 if any
  database failed. `--stop-on-error` aborts after the first failure; default continues.
- Logs: `~/odoodev-logs/update_v<version>_<db>_<timestamp>.log`.
- `--json`: single-line `{version, modules, results: [{database, ok, exit_code,
  duration_s, warnings, errors, last_error, log}], stale_skipped: [...]}`.

### `db list`

When a state file exists, each database gets a marker: `(stale: 2 repos changed)`,
`(never updated)` or nothing. `--json` gains `"stale": {db: reason}`.

### `pull --update`

After a successful pull (and config regeneration) runs the `db update --stale -y` path
in-process. Exit code follows the update. Without `--update`, `pull` prints a hint when
stale databases exist.

### Playbook step `db.update`

Args: `name` (string or list), `all: true`, `stale: true`, `modules` (default `all`),
`stop_on_error` (default false), `timeout`. Registered in `VALID_COMMANDS`,
`COMMAND_HANDLERS` and `STEP_ARG_SPECS` (dev mode). Non-interactive, no prompts,
per-database results in `StepResult.details`.

## Testing

Unit tests for the state file round trip, `stale_reason`, the issue filter (INFO
suppressed, ERROR + traceback forwarded, WARNING forwarded), the runner against a fake
`odoo-bin` script (exit 0 / exit 1 / timeout), CLI tests via `CliRunner` with the runner
patched (selection modes, `--stale`, `--dry-run`, `--json`, exit codes, summary table),
`pull --update` hand-off, and the automation handler.

## Documentation

RELEASE_NOTES 0.68.0, README changelog DE/EN, `usage/AGENT.md` (command table + recipe),
`docs/ARCHITECTURE.md` command table, odoo-dev skill.
