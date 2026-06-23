# Release Notes

## Version 0.31.4 (23.06.2026)

### Added
- **`odoodev db backup` supports `.tar.zst` stream backups** — a third backup type (`--type tar.zst`) now produces a Zstandard-compressed tar (`dump.sql` + `filestore/`) matching the Equitania backup server (`container2backup` v4.7.0+) and the restore added in 0.31.2. Implemented symmetrically to the restore: a Python `tarfile` stream is piped into the `zstd` CLI (no `zstandard` package needed). Well suited to large databases with a big filestore. A new `--level/-l` option sets the zstd compression level (1=fastest .. 19/22=smallest, default 5, multi-threaded `-T0`). The interactive backup-type prompt lists `TAR.ZST` alongside `SQL` and `ZIP`, and the command fails early with an install hint if the `zstd` CLI is missing.

## Version 0.31.3 (19.06.2026)

### Fixed
- **Interactive backup-file prompt rejected valid paths with surrounding whitespace** — when a path pasted (or autocompleted) into `odoodev db restore`'s `Backup file:` prompt carried a trailing space or newline, `os.path.exists` failed and the restore aborted with "File not found" even though the file existed. `path_input` now strips surrounding whitespace before expanding `~`, so all interactive path prompts (restore, copy, …) tolerate stray whitespace.

## Version 0.31.2 (19.06.2026)

### Added
- **`odoodev db restore` supports `.tar.zst` stream backups** — the Equitania backup server (`container2backup` v4.7.0+) now produces a Zstandard-compressed tar (`dump.sql` + `filestore/`) for large databases instead of a staged ZIP/7z, avoiding the threefold disk overhead. Restore decompresses these directly via a `zstd | tarfile` stream (no intermediate uncompressed tar on disk), with path-traversal protection (`filter="data"`). `odoodev doctor` gained a matching `zstd` soft check with per-platform install hints (`brew install zstd` / `apt install zstd`).

## Version 0.31.1 (18.06.2026)

### Added
- **`odoodev doctor` now checks for a 7-Zip CLI** — a new soft check probes `7zz`/`7z`/`7za` so a fresh setup (e.g. Debian/WSL2) is warned up front when `.7z` backups would not be restorable, with the correct per-platform install hint (`brew install 7zip` / `apt install 7zip` / `p7zip-full`).

### Fixed
- **7z backups failed to restore on Debian/WSL2** — `odoodev db restore` only probed the `7zz` and `7z` binaries. Debian's `p7zip` package (without `-full`) ships only `7za`, so 7-Zip was effectively undetected and the restore aborted as "not supported" even though 7-Zip was installed. The extraction now also tries `7za`, and the not-found message names the correct packages per platform (`brew install 7zip`, `apt install 7zip`, `apt install p7zip-full`).
- **wkhtmltopdf install hint was unusable on Linux** — the "not found" message only said what *not* to do. It now points to the patched-Qt `.deb` from `github.com/wkhtmltopdf/packaging/releases` (`sudo dpkg -i …`) for Linux/Debian and keeps the `.pkg` hint for macOS. The detector also searches `/opt/wkhtmltox/bin` (default tarball/.deb location), and the `doctor` summary hint is now OS-aware.

## Version 0.31.0 (16.06.2026)

### Added
- **TUI database backup (`b`)** — back up the running database straight from the TUI. A dialog picks the (editable) target database and backup type (ZIP with filestore, or SQL only); the dump runs in a worker thread so the UI stays responsive and the file lands in `~/Downloads/`.
- **TUI database switch (`d`)** — switch the served database at runtime. A picker lists the available PostgreSQL databases (current one marked and listed first) and restarts Odoo bound to the choice; the status bar updates immediately.
- **TUI module-catalog maintenance (`a` / `k`)** — `a` runs *Update apps list* (`ir.module.module.update_list`) to re-scan the addons path; `k` removes all non-installed modules (`state != 'installed'`) from the catalog. Both run via XML-RPC in a worker thread.
- **Module-CSV export pre-steps** — the export dialog (`x`) gained two checkboxes: *Update apps list before export* and *Remove non-installed modules before export*. Cleanup runs first, then the update, so a CSV exported after a restore reflects only the modules truly installed on the current system.

### Changed
- **`odoodev db backup` now defaults to `~/Downloads/`** — previously the backup landed in the current working directory (`--output` default `.`, effectively `~/gitbase/`). It now follows the same convention as the module-CSV export. `--output` still overrides the destination.

## Version 0.30.1 (15.06.2026)

### Fixed
- **Quick menu (`m`) clipped its last entry (`Load language`)** — the fixed `max-height: 26` cut off the bottom row on normal terminals, hiding the `Load language` action. The menu height is now adaptive (`95%`), so all entries are visible (and the list scrolls on very small terminals). A regression test asserts every action — including `load_language` — is present in the menu.

## Version 0.30.0 (15.06.2026)

### Fixed
- **TUI footer (keybinding bar) was hidden by the version label** — The bottom-right `odoodev v{version}` label was a second `dock: bottom` widget, which Textual places on the *same* bottom row as the `Footer`, covering the `q Quit | m Menu | ? Help` keys. The version label is now a normal flow row directly above the docked footer, so both are fully visible. A regression test asserts the footer and version label occupy different rows.

### Changed
- **Quick menu (`m`) now shows the direct shortcut key for each action** — every entry is prefixed with its key (e.g. `0  All levels`, `s  Save visible log`, `x  Export modules as CSV`), so the menu doubles as a cheat sheet now that the footer only shows `q | m | ?`.

## Version 0.11.0 (15.06.2026)

Semver-correct minor release that promotes the TUI feature work shipped under
0.10.0–0.10.1 to a proper minor version. No functional changes versus 0.10.1 —
this release exists to reflect that the 0.10.x line introduced user-facing
features. Rolled-up highlights of the TUI feature set:

### Added
- **Quick action menu (`m`)** — bottom-anchored menu that folds upward, grouping View / Log / Export / Server actions (arrow keys + Enter); the footer stays minimal (`q Quit | m Menu | ? Help`) on narrow terminals.
- **Module CSV export** (Releasemanager format) with an **editable target-database field** in the dialog.
- **Live database detection** from the Odoo log lines, shown in the status bar.
- **odoodev version shown bottom-right** in the TUI.

### Fixed
- TUI database is resolved from `-d`/`--database` (and the `-- -d <db>` form) instead of being guessed.
- Module export works on Odoo 19 (`state`-based filter; the `installable` field was removed from `ir.module.module` in v19).
- Odoo 19 `/xmlrpc/2` deprecation warning is silenced (correct `xmlrpc` controller logger).

## Version 0.10.1 (15.06.2026)

### Fixed
- **TUI module export crashed on Odoo 19** — The export query filtered on `ir.module.module.installable`, but that field was removed from the model in Odoo 19, raising `ValueError: Invalid field ir.module.module.installable`. The non-installable filter now uses `state != 'uninstallable'` (and installed-only uses `state = 'installed'`), which is the core `state` field present across v16-v19. Behavior is unchanged on v16-v18.
- **Odoo 19 XML-RPC deprecation warning now silenced** — `_add_v19_log_handlers` only muted the `jsonrpc` controller, but the module export uses `/xmlrpc/2`, whose deprecation warning comes from the `xmlrpc` controller. Both controllers are now raised to ERROR on v19+, so the export no longer spams the deprecation warning into the TUI log.

### Added
- **TUI: odoodev version shown bottom-right** — The running odoodev version (`odoodev v{version}`) is now displayed in the bottom-right of the TUI, overlaid on the footer row.

## Version 0.10.0 (15.06.2026)

### Fixed
- **TUI: correct database is now used, not guessed** — `odoodev start <v> --tui -d <db>` (and the `-- -d <db>` form) previously passed the database to `odoo-bin` but the TUI ignored it, falling back to the `db_name` in `odoo.conf` or a hardcoded `v{version}_exam`. The export then targeted the wrong database. The TUI now resolves the database by priority: explicit `--database` → `-d`/`--database` in extra args → `odoo.conf` → fallback. Additionally, the **actually served database is detected live from the Odoo log lines** (`OdooLogEntry.database`) and shown in the status bar, so even a database opened at runtime is reflected.

### Added
- **TUI: quick action menu (`m`)** — A bottom-anchored menu that folds upward (Textual `OptionList`, arrow keys + Enter), grouping View / Log / Export / Server actions. Solves the overcrowded footer on narrow terminals. The footer now shows only `q Quit | m Menu | ? Help`; all direct keys still work and stay reachable via the menu. DE/EN localized.
- **Export dialog: editable target database** — The CSV export dialog now has an editable database field, pre-filled with the live-detected database. The user can override it (or type one when none could be detected). The export uses exactly this database for both the XML-RPC query and the output filename.

## Version 0.9.0 (15.06.2026)

### Added
- **TUI: module CSV export (`x`)** — Export the running instance's module list as an import-compatible Odoo CSV for the Equitania Releasemanager ("Import Module CSV"). A modal dialog offers three scopes: all available modules, all without Enterprise (`license = OEEL-1`), or installed only. Test (`test_*`) and hardware (`hw_*`) modules are always excluded, non-installable modules are dropped, and themes (`theme_*`) are always kept. The file is written to `~/Downloads/modules_{db}_{scope}_{timestamp}.csv` with the header `.id,name,installed_version,display_name`. Reuses the existing XML-RPC client; dialog and notifications are DE/EN localized.

## Version 0.8.0 (11.06.2026)

### Added
- **`odoodev doctor [VERSION]`** — All environment prerequisite checks (uv, Docker, Compose, wkhtmltopdf, pg tools, PostgreSQL port, Node.js + packages, system libs, venv packages) in one Rich summary table with per-check remediation hints. Hard requirements exit 1 on failure; the rest only warn. Includes a PyPI freshness check (2s timeout, graceful offline skip) that announces when a newer odoodev release is available. Wires the previously unused `run_all_checks()` into the CLI.
- **`db copy` / `db rename`** — Copy a database via `createdb -T` or rename it via `ALTER DATABASE`, both including the filestore (copy / move). Active connections (e.g. a running Odoo server) are detected; terminate them interactively or with `--terminate-connections`. All names pass the SQL identifier guard.
- **`config set <key> <value>` / `config edit`** — Change `base_dir`, `language`, `db.user`, `db.password` and `active_versions` from the CLI (validated whitelist, passwords never echoed), or open `config.yaml` in `$EDITOR`. No more hand-editing YAML for routine changes.
- **`venv remove [VERSION]`** — Cleanly delete a version's venv (confirmation unless `--yes/-y`, idempotent, symlink-safe). Counterpart to `venv setup`.
- **Machine-readable `--json` output** for `db list`, `config versions` and `venv check` (non-interactive; exit 1 when the venv is missing) — for scripts, CI and AI agents.
- **Playbook variables** — New `vars:` block plus optional `description:`; step args are rendered through a sandboxed Jinja2 environment with `{{ vars.x }}`, `{{ env.X }}` and `{{ date }}` (ISO). Override per run with `--var/-D KEY=VALUE`. Template errors fail the step and honor `on_error`.
- **`run --list`** — Discover playbooks (`*.yaml`/`*.yml`) in `./playbooks/` and `<native_dir>/scripts/playbooks/` with name, description, source and path (Rich table or `--output json`).
- **TUI: log export (`s`)** — Save the visible (filtered) log buffer to `~/odoodev-logs/odoo_{version}_{db}_{timestamp}.log`.
- **TUI: help overlay (`?`)** — Modal screen listing every keybinding grouped by Server / Filtering / Clipboard & Export; a test asserts the overlay stays complete. Full keybinding table added to `usage/start.md` (DE + EN).
- **Unified `--yes/-y`** — `-y` short form on `db drop` and `migrate remove`; hidden `--yes/-y` alias for `start --no-confirm`; new commands use `--yes/-y` natively.

### Fixed
- **`.pgpass`: passwords with `:` or `\` now work** — Previously a password containing a colon silently skipped the `.pgpass` write (falling back to env-var auth) and a backslash corrupted the entry. Fields are now escaped per pgpass(5) (`\\` and `\:`); only newlines (illegal in the format) still skip the write.
- **TUI: one-shot module update args** — `OdooProcess.restart(extra_args=["-u", ...])` no longer retains the extra args internally, so a later direct `start()` cannot accidentally repeat the module update.

## Version 0.7.2 (11.06.2026)

### Changed
- **passlib dependency removed** — The opt-in `res_users` anonymization now builds the Odoo-compatible `$pbkdf2-sha512$` password hash with the Python standard library (`hashlib.pbkdf2_hmac` + `secrets`, passlib "ab64" encoding, 25,000 rounds). passlib has been unmaintained since 2020; Odoo still verifies the format on its side, so nothing changes for restored databases. `passlib`/`types-passlib` were dropped from the project dependencies (the `data/examples/*/requirements.txt` keep `passlib` — that is Odoo's own dependency).

### Fixed
- **Security: credentials files now written with owner-only permissions** — `~/.config/odoodev/config.yaml` and the generated `.env` (both contain the PostgreSQL password in plaintext) are created with mode `0600`, the config directory with `0700`. Previously they inherited the umask and could be world-readable on shared systems.
- **Security: restored backup content restricted to the current user** — After extraction, `extract_backup()` chmods the extracted dump/filestore to `0700`/`0600`. Dumps contain production PII until anonymization completes; extracted files previously inherited the umask.
- **Security: SQL guards against identifier/WHERE injection** — New `_check_identifier()` (strict `[A-Za-z_][A-Za-z0-9_]*` regex) and `_check_where_fragment()` (rejects `;`, `--`, `/*`) validators fail fast in all f-string query builders (`_existing_columns`, `_build_static_update`, `_fetch_ids`, `_build_anonymize_sql`). All current callers pass hardcoded constants — this hardens the builders against future reuse with untrusted input.

## Version 0.7.1 (02.06.2026)

### Fixed
- **venv setup: stale uv index cache caused false "no solution found"** — When a version required by `requirements.txt` was just published to PyPI but not yet visible in uv's locally cached index, `odoodev venv setup` (and the `init` / `start` package-update paths) aborted with a misleading unsatisfiable-dependency error. `install_requirements()` now retries once with `uv pip install --refresh` on failure, which refreshes the index and recovers automatically; a warning is printed before the retry. The three inline `uv pip install` call sites (`venv setup`, `init`, `start`) were consolidated onto this single core function, which gained `capture` (stream vs. suppress uv output) and `cwd` parameters to preserve their existing behavior.

## Version 0.7.0 (29.05.2026)

### Added
- **db restore: bank-sync neutralization** — Native `odoo-bin neutralize` does not reset `account_journal.bank_statements_source` and only marks `account_online_link.client_id = 'duplicate'` (no delete). New `neutralize_bank_sync()` core function closes that gap FK-safely: it detaches journals (`bank_statements_source = 'undefined'`, online account/link FKs set to NULL), then deletes `account_online_account` (child) before `account_online_link` (parent). Each statement runs as its own `psql` call (separate transaction) — required because bundling the journal update and the deletes in one transaction can fail. Column/table guarded (no-op when the accounting/bank-sync modules are absent). Runs under the `--neutralize` flag (also in standalone `db neutralize`), even when native neutralize was skipped for lack of a venv.
- **db: HR/employee data anonymization** — `anonymize_database()` now anonymizes employee PII: `hr_employee` (name + work email per-row Faker; private address, phones, ID/passport/SSN numbers, birth/spouse/emergency data, PIN/barcode, notes, image & scan binaries wiped; salary/distance fields zeroed), `hr_version` (v19) and `hr_contract` (v16/v18) wages zeroed, and the v19 `employee_bank_account_rel` link table cleared. Version-robust via the new `_existing_columns()` helper: every column is matched against `information_schema` before the `UPDATE`, so the same spec works across v16/v18/v19 despite their differing HR schemas (v16 keeps private data on `res_partner`, v18 on `hr_employee`, v19 on `hr_version`).
- **db restore: optional res_users anonymization** — New `--anonymize-users/--no-anonymize-users` flag (off by default) plus `--user-password` (default `ownerp`). When enabled, non-system logins become `user{id}` and passwords are reset to one shared dev password stored as an Odoo-compatible `pbkdf2_sha512` hash (via the new `passlib` dependency) — so every user stays loginable as `user<id>` / `ownerp` while `admin` (id=1) keeps its original credentials.
- **start hint after restart-requiring operations** — New shared `print_start_hint(version, db_name)` helper. After `db restore`, `pull` and `repos`, odoodev now recommends the dev-mode start command including `--tui --dev` (e.g. `odoodev start 19 --tui --dev -d <db> -u all`, plus the no-update follow-up), as copy-pasteable green command lines.

### Changed
- **db restore: res_users no longer anonymized by default** — Previously the default anonymization cleared user logins/passwords, which made the restored database impossible to log into. `res_users` is now left untouched by default (keeping logins testable); use `--anonymize-users` to opt in. The customer-facing data-protection guide and `usage/db.md` were updated accordingly (HR tables, bank-sync, corrected login section, new audit queries).

### Fixed
- **path inputs: `~` was not expanded** — `odoodev db restore` (and other prompts) failed with "File not found" when a path like `~/Downloads/backup.7z` was entered interactively, because Python does not expand `~`. `path_input()` now runs the result through `os.path.expanduser()`, and a new `ExpandedPath` (`click.Path` subclass) expands `~` for the `--backup-file`, `--output`, `--config` and `playbook` CLI options too.

## Version 0.6.0 (27.05.2026)

### Added
- **db restore: native Odoo neutralization** — After the import, `odoodev db restore` now runs Odoo's built-in `odoo-bin neutralize` (new `run_neutralize()` core executor), which executes each installed module's `data/neutralize.sql`. This covers far more than the previous hand-picked SQL: payment providers, IAP accounts, webhooks, mass-mailing, OAuth tokens, the "NEUTRALIZED" banner, and any custom module shipping a `neutralize.sql` (including the in-house Nextcloud/Office365 modules). New `--neutralize/--no-neutralize` flag, **on by default** with graceful skip: if venv/odoo-bin/generated `odoo_*.conf` are not ready, the step is skipped with a warning (non-fatal) instead of failing. Neutralize is a standalone Odoo CLI subcommand — it connects directly to PostgreSQL and does not boot a server.
- **`odoodev db neutralize [VERSION] -n <db>`** — New standalone command to (re-)neutralize a database on demand, e.g. after `repos` + `start -u all` have populated the addons path. Supports `--stdout` to print the neutralization SQL instead of applying it (dry run). Available in playbooks via the `neutralize` arg on the `db.restore` step.

### Changed
- **db restore: replaced custom cloud deactivation with native neutralize** — Removed `deactivate_cloud()` and the `--deactivate-cloud-integrations/--no-deactivate-cloud-integrations` flag (and the `deactivate-cloud-integrations` playbook arg). Nextcloud/Office365 are now neutralized through their modules' own `data/neutralize.sql` via `odoo-bin neutralize`. The psql-only `deactivate_cronjobs()` remains as an always-available baseline (no running Odoo required).

## Version 0.5.0 (27.05.2026)

### Added
- **db restore: GDPR data anonymization** — `odoodev db restore` now anonymizes personal data after the import via a new `anonymize_database()` post-restore step (GDPR Art. 5 data minimization, Art. 25 privacy by default). Replacement values are generated with **Faker** (`de_DE`, seeded per row id so results are deterministic/reproducible) and applied as one bundled, chunked `UPDATE ... FROM (VALUES ...)` per table via `psql -f`. Covered: `res_partner` (split by `is_company` — companies get `fake.company()` names, persons get `fake.name()` plus a job title), `res_users` (system/admin accounts excluded), `crm_lead`, `res_partner_bank` (per-row Faker), plus `mail_message` and `ir_attachment` (whole-table wipes). E-mail and login columns are never Faker-generated but forced onto RFC 2606 reserved targets (`p{id}@example.invalid`, `user{id}`) so no real address is reachable and unique constraints hold. Missing tables (uninstalled modules) are skipped (non-fatal). New `Faker>=20.0.0` runtime dependency.

### Changed
- **db restore: anonymization is on by default (opt-out)** — The new `--anonymize/--no-anonymize` flag defaults to `--anonymize`. Restoring a production dump into the local dev environment now strips personal data unless `--no-anonymize` is passed. Non-system users end up with login `user{id}` and no password; the `admin` login stays usable.

## Version 0.4.54 (05.05.2026)

### Fixed
- **prereq: false positive for `libfreetype6-dev` on Debian 13** — `check_system_libs()` did a pure `dpkg -l <name>` lookup and hardcoded the legacy package names `libfreetype6-dev`, `libxslt1-dev`, and `libldap2-dev`. Debian 13 dropped these in favor of `libfreetype-dev`, `libxslt-dev`, and `libldap-dev`, so `odoodev init` warned about missing libraries that were actually installed and printed an apt install hint that no longer resolves. `LINUX_LIBS` is now a `dict[str, list[str]]` mapping each description to a list of candidate package names (modern first); the probe accepts the entry as soon as any candidate is installed, and the install hint always recommends the modern name.

## Version 0.4.53 (04.05.2026)

### Fixed
- **tui: per-level filter was cumulative and leaked RAW lines** — The TUI filter was a *minimum-level* filter (`level_ge`), so picking "WARNING" still showed ERROR and CRITICAL, and RAW lines (Odoo stdout, tracebacks, startup output) were always rendered regardless of the active level. Selecting "WARNING" therefore appeared to also show INFO-style output via these RAW lines. The filter is now a **multi-toggle**: each level (DEBUG, INFO, WARNING, ERROR, CRITICAL) is independently on/off. RAW continuation lines now inherit the level of the preceding structured log entry, so a traceback after an ERROR is filtered alongside that ERROR.

### Changed
- **tui: footer now exposes filter hotkeys** — Replaced the single `f` cycle binding with explicit per-level hotkeys: `0` activates all levels, `1`–`5` toggle DEBUG/INFO/WARNING/ERROR/CRITICAL individually, `f` jumps to "issues only" (WARNING + ERROR + CRITICAL). All filter bindings are visible in the footer with short labels. Copy bindings (`c`/`e`/`w`) moved to `show=False` to keep the footer focused on common actions.
- **tui: filter bar tabs are now toggle controls** — Each level tab independently shows active (bold green reverse) or inactive (dim) state. Clicking a tab toggles only that level instead of replacing the entire filter selection. Added a leading "Levels:" label for clarity.

## Version 0.4.52 (30.04.2026)

### Added
- **i18n: DE/EN localization for CLI guidance** — New `odoodev/i18n.py` module with flat dict-of-dicts MESSAGES, `t(key, **kwargs)` translator, and 5-tier precedence detection (`--lang` flag → `ODOODEV_LANG` env → `cli.language` in config → system locale → `en`). Phase-1 strings cover the setup wizard, `start` preflight, placeholder-password panel, and DB-restore hints. New global `--lang en|de` flag (`odoodev --lang de start 18`).
- **setup: language preference in wizard** — First wizard step now asks for the preferred CLI language and persists it to `~/.config/odoodev/config.yaml` under `cli.language`. New `CliConfig` dataclass in `core/global_config.py`.
- **start: blocking placeholder-password preflight** — New `_check_placeholder_password` preflight renders a Rich panel with the affected `.env` path and aborts unless the user explicitly confirms (TTY) or passes the new `--allow-default-credentials` flag (CI/scripts). Replaces the easily overlooked single-line `logger.warning`.
- **repos/pull: enterprise inclusion prompt** — `_prompt_enterprise_inclusion` detects repositories tagged `section: Enterprise` or matching the `vNNe` path convention (`v16e`, `v17e`, `v18e`, `v19e`) and offers to exclude them in this run. New `--no-enterprise-prompt` flag for non-interactive use. The `repos.yaml` is never modified.

### Fixed
- **start: hardcoded port fallback in URL panel** — `env.get("ODOO_PORT", "18069")` was a v18-only constant regardless of the version actually starting. Now falls back to `version_cfg.ports.odoo`, so `odoodev start 16` shows port `16069` instead of misleading users into typing `18069` in the browser.
- **start: URL panel hidden in --dev/--shell/--test** — The `Web: http://localhost:PORT` panel only rendered in normal mode. It now renders in every mode with the active mode annotated in the title (`Odoo v18 — Native Development (--dev)`).
- **database: placeholder warning visibility** — `_warn_once_on_placeholder` now uses `print_warning` (Rich panel) instead of `logger.warning`, so the warning is no longer drowned in standard log output.

### Changed
- **docs: workflow wiki hardening** — Port-overview table for all four versions added directly after the workflow diagram, plus a prominent `.env`-edit reminder. Cross-references rewritten to `usage/<file>.md` so paths stay readable without a Markdown renderer. Two new troubleshooting entries: "Connection refused" (port mix-ups) and "Insecure default credentials" (placeholder password). DE and EN sections kept symmetric.

## Version 0.4.51 (27.04.2026)

### Fixed
- **repos/pull: divergent branch handling** — `update_repo()` now uses `git pull --ff-only` instead of bare `git pull`. When local and remote branches have diverged, the command fails immediately with a clear, actionable hint pointing the user to `git -C <path> pull --rebase` or `--no-rebase`. Previously the failure surfaced as opaque git hint text and depended on the user's global `pull.rebase`/`pull.ff` configuration.

## Version 0.4.50 (22.04.2026)

### Fixed
- **security: TAR symlink/device-file hardening** — `tarfile.extractall()` now uses the `filter="data"` parameter (Python 3.12+) in addition to the explicit member-path check. This closes a residual gap where a prepared archive containing a relative symlink could redirect extraction outside the target directory despite the path check passing.
- **security: XML-RPC credential leakage on remote hosts** — `OdooXmlRpcClient` now refuses plaintext HTTP connections to non-local hosts by default (`ValueError` instead of a passive warning). New `use_https=True` parameter enables TLS; `allow_insecure_remote=True` provides an explicit opt-in for trusted LANs.
- **security: SSTI hardening in Jinja2 templates** — `commands/env.py` and `core/docker_compose.py` now use `jinja2.sandbox.SandboxedEnvironment` instead of the default `Environment`. Prevents template-expression injection via attacker-influenced config values (`db_password`, `dev_user`, etc.).
- **security: placeholder-password runtime warning** — One-shot warning when PostgreSQL commands fall back to the `CHANGE_AT_FIRST` placeholder (from `global_config.py` defaults, `PGPASSWORD` env, or `.env` file). Hints at `odoodev setup` to configure a real password.
- **security: Odoo server binds to loopback by default** — `odoodev start` now sets `HOST=127.0.0.1` instead of `0.0.0.0`, keeping the dev server off shared network interfaces. New `--host` option re-exposes the previous behaviour (`--host 0.0.0.0`) for VM-based or multi-host workflows.



### Fixed
- **security: TAR path traversal protection** — Backup extraction for `.tar`/`.tgz` files now validates all member paths before extraction (CWE-22), consistent with the existing ZIP protection.
- **security: password masking in CLI output** — `odoodev env show` now masks `PGPASSWORD`/`DB_PASSWORD` as `***` instead of displaying in cleartext. Setup summary also masks the DB password.
- **quality: coverage threshold raised** — Test coverage threshold increased from 20% to 55% (current coverage: 57.64%).

## Version 0.4.48 (31.03.2026)

### Fixed
- **db: migration-aware hints** — All database commands (`list`, `drop`, `backup`, `restore`) now display a `[MIGRATION]` hint when an active migration is detected, showing which PostgreSQL container is being accessed.
- **start: migration-aware Docker auto-start** — `_check_services()` now redirects the Docker auto-start to the source version's container when the target version is started during an active migration, preventing a wrong container from being launched.
- **stop: migration-aware Docker shutdown** — `odoodev stop` for the migration source now warns that the shared container will be stopped. For the migration target, `docker compose down` is skipped entirely since it has no own container.

## Version 0.4.47 (31.03.2026)

### Fixed
- **init: migration-aware Docker startup** — `odoodev init` no longer starts a separate PostgreSQL container when the version is the target of an active migration. Instead, it displays a `[MIGRATION]` hint and refers to the shared source container. When initializing the source version, the success message indicates the container is shared with the migration target.

### Changed
- **docs: README usage index** — Added complete usage documentation index (10 sections) after Quick Start in both DE and EN, replacing the single setup link.
- **docs: usage/migrate.md** — New bilingual usage page for the migration command with quick-start workflow, subcommand reference, and link to technical details.
- **docs: Obsolete Components removed** — Removed the "Obsolete Components" sections from README (both DE and EN) as they are no longer relevant.

## Version 0.4.46 (30.03.2026)

### Fixed
- **prerequisites: Node.js install hints** — Linux install hints now recommend NodeSource repository for Node.js 20+ instead of `apt install nodejs`. Upgrade hint shown when Node.js < 20 detected. `npm install -g` commands now include `sudo`. System library install command now lists only missing packages instead of all.
- **examples: v16 requirements.txt** — Unpinned `msal==1.31.1` to `msal>=1.31` to resolve dependency conflict with `cryptography==46.0.0` (msal 1.31.x requires cryptography<46).
- **examples: v17 repos.yaml** — Fixed server git URL from `v17/v17-server.git` to `v17-odoo/v17-server.git` (matching the actual GitLab namespace).
- **versions.yaml: v17 server URL** — Same fix applied to bundled version registry.

## Version 0.4.45 (30.03.2026)

### Added
- **migrate: Migration Mode for cross-version database migrations** — New `odoodev migrate` command group for sharing PostgreSQL containers and filestore paths between Odoo versions during database migrations. Supports the full migration workflow (v16→v17→v18→v19):
  - `odoodev migrate create --from 16 --to 18` — Create a migration group
  - `odoodev migrate activate 16-to-18` — Activate: target version uses source's DB container and shared filestore
  - `odoodev migrate deactivate` — Restore normal per-version isolation
  - `odoodev migrate status` — Show active migration, ports, filestore path, container status
  - `odoodev migrate list` — List all defined migration groups
  - `odoodev migrate remove` — Remove a migration group definition
- **Transparent integration**: Active migration automatically overrides target version's DB port in `load_versions()` and filestore path in `get_filestore_path()` — all existing commands (`start`, `db`, `docker`) work without changes
- **Safety warnings**: `docker down` on shared source container warns about disconnecting target version; `docker up` on target version redirects to source container
- **PostgreSQL compatibility check**: Warns when source and target use different PG major versions (e.g., v18 pg16 → v19 pg17)
- **Persistent config**: Migration state persisted in `~/.config/odoodev/migration.yaml` — survives shell restarts
- New `docs/migration-mode.md` with complete usage documentation
- 47 new tests covering migration config, CLI commands, version registry integration, and filestore path resolution

### Fixed
- **prerequisites: Missing Debian system libraries** — Added 6 missing packages to `LINUX_LIBS` check: `libssl-dev`, `libffi-dev`, `libpng-dev`, `libfreetype6-dev`, `libpq-dev`, `libcups2-dev`. These are required for compiling Python C extensions (cryptography, Pillow, psycopg2, pycups) on fresh Debian/Ubuntu installations.

## Version 0.4.44 (27.03.2026)

### Fixed
- **examples: Internal GitLab URLs** — All example `repos.yaml` files (v16-v19) now use `git@gitlab.ownerp.io` URLs instead of public GitHub URLs. Consistent with `versions.yaml` and production configurations. Replaces 3 separate OCA GitHub repos (rest-framework, web-api, server-auth) with single `vXX-oca` repo. Adds Equitania addons entry to all versions.

## Version 0.4.43 (26.03.2026)

### Added
- **TUI: Mouse support** — Full mouse interaction for the TUI log viewer (`odoodev start --tui`):
  - **Text selection**: Click-drag to select text in the log output, automatically copies to system clipboard via `pbcopy`/`xclip`/`xsel` (OSC 52 fallback)
  - **Clickable filter tabs**: Click on DEBUG/INFO/WARNING/ERROR/CRITICAL labels to switch log level filter directly
  - **Clickable auto-scroll toggle**: Click the auto-scroll indicator to toggle between auto-scroll and manual mode
  - **Clickable footer shortcuts**: All shortcuts in the footer bar are now clickable (built-in Textual 8.1.1)
- New `SelectableRichLog` widget subclass that overrides `get_selection()` to extract plain text from the internal Strip line buffer
- New `FilterBar` widget with `FilterTab` and `ScrollToggle` subwidgets replacing the static filter bar
- 7 new tests covering filter tab clicks, scroll toggle clicks, and text selection extraction

## Version 0.4.42 (26.03.2026)

### Changed
- **start: Explicit Odoo options `-d`, `-u`, `-i`** — The `--` separator is no longer needed for the most common Odoo flags. `odoodev start 19 --dev -d v19_equitania -u all` now works directly. Less common Odoo flags (`--workers`, `--log-level`, etc.) still use the `--` separator. Typos in odoodev's own flags are still caught by Click. Updated `db restore` hint and documentation accordingly.
- 16 new tests covering `_build_odoo_extra_args` helper and CLI option parsing

## Version 0.4.41 (26.03.2026)

### Fixed
- **pull: Double git operations eliminated** — `odoodev pull` no longer executes `git checkout` + `git pull` twice on all addon repositories. The config regeneration phase (`_process_repos`) now uses `skip_git=True` to only collect local paths without triggering git operations that were already performed. This fixes `index.lock` errors that occurred when the second git pass overlapped with lingering lock files.

## Version 0.4.40 (22.03.2026)

### Added
- **examples: OCA REST-Framework Stack** — Added 3 OCA repositories (rest-framework, web-api, server-auth) and 8 Python dependencies (fastapi, a2wsgi, ujson, python-multipart, extendable, extendable-pydantic, pyjwt, typing-extensions) to v18 and v19 example templates. Provides FastAPI endpoints, JWT auth, and API key auth for Odoo out of the box.

## Version 0.4.39 (20.03.2026)

### Added
- **start: Session cleanup (`--clean-sessions`)** — New `--clean-sessions` flag for `odoodev start` removes all Odoo session files from `data_dir/sessions/` before starting. Without the flag, an interactive prompt appears when sessions are found (default: No). `--no-confirm` skips the prompt without cleaning. Session directory is recreated empty after cleanup.
- **README.md updated** — Feature list now includes all features added since v0.4.30 (interactive addon selector, language loading, session cleanup) in both DE and EN sections. Badge version updated.
- **usage/repos.md updated** — Added `--select` flag documentation with examples for `repos` and `pull` commands in both DE and EN sections.
- 8 new tests covering session cleanup logic (no data_dir, no sessions dir, empty sessions, force flag, interactive yes/no, no-confirm skip, CLI flag presence)

## Version 0.4.38 (20.03.2026)

### Added
- **repos/pull: Interactive addon selector (`--select`)** — New `--select` flag for `odoodev repos` and `odoodev pull` commands. Shows a questionary checkbox UI grouped by section (OCA, Enterprise, Equitania, Customer, etc.) with pre-selection based on `repos.yaml` `use` field. Allows toggling individual addons on/off before config generation. Includes change summary output and TTY guard for CI/CD safety.
- **output: `checkbox_with_separators()`** — New output helper with section separators and patched checkbox indicators (`[✔]/[ ]`) for better terminal visibility
- **repos: DRY refactor** — `_collect_all_repos()` now delegates to `_collect_all_repos_with_status()`, eliminating duplicated use-field resolution logic
- **Circular import fix** — `resolve_version` import in `repos.py` made lazy to break `repos.py → cli.py → pull.py → repos.py` cycle
- 16 new tests covering addon selector logic, metadata updates, selection summary, CLI flag presence, and non-TTY fallback

## Version 0.4.37 (18.03.2026)

### Fixed
- **repos: Config generation now respects .env password** — `_generate_config()` previously read database credentials exclusively from global config (`~/.config/odoodev/config.yaml`), ignoring version-specific `.env` files. Now reads `PGUSER` and `PGPASSWORD` from the `.env` file in `native_dir` first, falling back to global config only if `.env` is missing or values are not set.

## Version 0.4.36 (18.03.2026)

### Fixed
- **wkhtmltopdf: Remove wrong Homebrew recommendation for macOS** — `brew install wkhtmltopdf` does not work on macOS. Prerequisite check now recommends the `.pkg` installer from wkhtmltopdf.org instead. Removed `/opt/homebrew/bin` from macOS search paths. Updated `env.template.j2` and `usage/setup.md` (DE/EN) accordingly.

## Version 0.4.35 (17.03.2026)

### Added
- **i18n/Language reload**: New CLI options `--load-language` and `--i18n-overwrite` for `odoodev start` — load or reload translations without manually passing Odoo flags via `--`
  - `odoodev start 18 --load-language=de_DE --i18n-overwrite -- -d v18_exam`
  - `odoodev start 18 --load-language=all` to reload all installed languages
  - `--i18n-overwrite` automatically adds `-u all` when no `-u` is provided (Odoo requirement)
  - Works with all start modes (normal, `--dev`, `--tui`)
- **TUI Language Load dialog**: Press `l` in TUI mode to open a modal dialog for language loading — enter language code and toggle overwrite option, then restart Odoo with the flags
- 10 new tests: 7 CLI tests (help text, command building, flag ordering, auto -u all), 3 TUI tests (keybinding, widgets, cancel)

## Version 0.4.33 (17.03.2026)

### Fixed
- **TUI: Ctrl+Q now stops Odoo process** — Textual's built-in `ctrl+q` binding called `action_quit()` which only exited the TUI without stopping Odoo. Now `action_quit()` is overridden to call `OdooProcess.stop()` before exit. Explicit `ctrl+q` binding also added to BINDINGS.
- **TUI: Safety-net process cleanup** — `_launch_tui()` in `start.py` now calls `app._odoo.stop()` after `app.run()` returns, ensuring Odoo is terminated even if the TUI exits abnormally (crash, exception, signal). `OdooProcess.stop()` is idempotent so double-calls are safe.

### Added
- 2 new TUI integration tests: `test_ctrl_q_stops_process`, `test_action_quit_override_stops_process`

## Version 0.4.31 (16.03.2026)

### Changed
- **start.py refactored**: Extracted 241-line `start()` command into 6 focused helper functions (`_check_env_file`, `_check_venv`, `_check_odoo_source`, `_check_odoo_config`, `_check_services`, `_launch_tui`) — `start()` itself is now ~70 lines of orchestration
- **Atomic .pgpass write**: `_write_pgpass()` now uses temp-file + `os.rename()` instead of `O_TRUNC` — prevents data loss on crash mid-write
- **Password validation for .pgpass**: Rejects passwords containing `:` or newline characters that would corrupt the pgpass format
- **XML-RPC non-localhost warning**: `OdooXmlRpcClient` logs a warning when connecting to non-local hosts over plaintext HTTP
- **Narrowed exception handling**: `_get_default_credentials()` in `database.py` now catches `(ImportError, AttributeError, KeyError, OSError)` instead of bare `Exception`
- **Dead code removed**: Identical if/else branches in `version_registry.py` load_versions() simplified to single assignment
- **Debug logging added**: Silent `except Exception` blocks in `screens.py`, `process_manager.py` now log to `logger.debug()` with traceback

### Fixed
- **Type safety**: `xmlrpc_client.py` `_uid` now uses explicit `int()` cast for XML-RPC authenticate return value

### Added
- **28 new tests for start.py**: `_find_odoo_config`, `_get_config_value`, `_load_env_file`, `_write_pgpass` (atomic write, permissions, colon/newline rejection), `_add_v19_log_handlers`
- **28 new tests for database.py**: `extract_backup` (ZIP, SQL, path traversal protection), `detect_backup_type`, `copy_filestore`, `format_size`, `get_filestore_path`, `get_restore_temp_dir`, `cleanup_restore_temp`
- **3 new tests for xmlrpc_client.py**: Non-localhost HTTP warning (localhost, 127.0.0.1, remote host)
- Test coverage increased from 21% to 52% (451 total tests)

## Version 0.4.30 (16.03.2026)

### Added
- **Port conflict detection**: `odoodev start` detects when the Odoo port is already in use, identifies the blocking process via `lsof`, and offers to kill it

## Version 0.4.29 (16.03.2026)

### Fixed
- **Werkzeug pinned** for v16/v17 compatibility in templates

## Version 0.4.28 (16.03.2026)

### Changed
- **Restore temp dir**: Linux always uses `$HOME/odoodev-tmp`, macOS uses system tmp

## Version 0.4.27 (16.03.2026)

### Fixed
- **TUI error copy**: Now includes full tracebacks in clipboard output

## Version 0.4.26 (16.03.2026)

### Fixed
- **setuptools pinned to <82**: Version 82+ removed `pkg_resources`

## Version 0.4.25 (16.03.2026)

### Fixed
- **setuptools**: Install during init, use `--reinstall` for UV

## Version 0.4.24 (16.03.2026)

### Added
- **Odoo 19 RPC deprecation warning mute**: Automatically adds `--log-handler=odoo.addons.rpc.controllers.jsonrpc:ERROR` for Odoo v19+ to suppress deprecated XML-RPC/JSON-RPC endpoint warnings (migration to `/json/2/` API planned for odoorpc-toolbox)
- **Restore temp directory space check**: `db restore` now checks free space on `/tmp` before extraction — falls back to `$HOME/odoodev-tmp` when system temp has insufficient space; auto-cleanup removes fallback directory after restore
- **Linux build dependency checks**: Added `python3-dev`, `build-essential`, `pkg-config` to system prerequisite checks — catches missing C compiler toolchain on fresh Debian/Ubuntu before `uv pip install` fails with cryptic errors
- **Auto-install setuptools for Odoo v16/v17**: `ensure_setuptools()` detects and installs `setuptools` (providing `pkg_resources`) automatically — required on Python 3.12+ where it is no longer bundled
- 18 new tests: v19 log handlers (7), restore temp dir + cleanup (11)

### Changed
- `format_size()` moved from `commands/db.py` to `core/database.py` to eliminate duplication
- `venv setup` for v16/v17: installs setuptools right after venv creation
- `start` for v16/v17: checks and auto-fixes missing setuptools before launching Odoo

## Version 0.4.21 (15.03.2026)

### Security
- **ZIP path traversal fix** (CWE-22): `extract_backup()` in `database.py` now validates all ZIP member paths before extraction — rejects entries containing `../` or absolute paths to prevent writing outside the target directory
- 3 new tests for ZIP traversal protection (safe extraction, `../` traversal, absolute paths)

### Changed
- Coverage threshold adjusted from 45% to 20% — many modules require a running Odoo/PostgreSQL server and cannot be unit-tested; actual coverage is 49.55%

## Version 0.4.20 (15.03.2026)

### Added
- **Clipboard copy** for TUI mode: Copy log output directly to system clipboard for AI/debugging transfer
  - `c` — Copy all currently visible (filtered) log lines
  - `e` — Copy only ERROR/CRITICAL lines
  - `w` — Copy WARNING + ERROR + CRITICAL lines
  - Cross-platform support: macOS (`pbcopy`), Linux (`xclip`, `xsel`)
- 5 new tests for clipboard and text extraction functions

## Version 0.4.19 (15.03.2026)

### Added
- **TUI runtime mode** (`odoodev start --tui`): Terminal UI for Odoo server management based on Textual
  - **Log Viewer**: Scrollable log output with level filtering (DEBUG/INFO/WARNING/ERROR/CRITICAL), search highlighting, and auto-scroll toggle
  - **Status Bar**: Real-time server state (Running/Stopped/Starting), version, port, database, uptime
  - **Module Update Dialog**: Update modules via restart with `-u` flag or XML-RPC hot upgrade without restart
  - **Keyboard Shortcuts**: `q` Quit, `r` Restart, `u` Update Module, `f` Filter Level, `/` Search, `Ctrl+L` Clear, `Space` Auto-scroll
  - **Process Group Isolation**: `os.setsid()` isolates Odoo in its own process group — Ctrl+C reliably terminates the entire process tree via `os.killpg(SIGTERM)` with SIGKILL escalation
  - `tui/log_parser.py`: Regex-based Odoo log line parser with `OdooLogEntry` frozen dataclass
  - `tui/odoo_process.py`: `OdooProcess` class with queue-based I/O, daemon threads, restart-with-extra-args
  - `tui/xmlrpc_client.py`: XML-RPC client for hot module upgrades via `ir.module.module.button_immediate_upgrade`
  - `tui/app.py`: Textual App with CSS layout, filter bar, and modal screens
  - `tui/widgets/log_viewer.py`: RichLog wrapper with 10,000-entry buffer and level/search filtering
  - `tui/widgets/status_bar.py`: Reactive status display with uptime formatting
- `stop_process_group()` in `process_manager.py`: Terminate entire process groups via `os.killpg()`
- `textual>=1.0.0` added as dependency
- `pytest-asyncio` and `textual-dev` added to dev dependencies
- 72 new tests: log parser (27), OdooProcess (14), process group (3), TUI app integration (18), XML-RPC client (10)

## Version 0.4.17 (14.03.2026)

### Security
- **SSH hardening**: Replaced `StrictHostKeyChecking=accept-new` with `StrictHostKeyChecking=yes` in `git_ops.py` to prevent automatic acceptance of unknown SSH host keys (MITM protection)
- **SSH key isolation**: SSH key path is now written to a temporary SSH config file (`~/.ssh/odoodev_config`) instead of being exposed in `GIT_SSH_COMMAND` environment variable (visible via `ps aux`)
- **PostgreSQL credentials**: Replaced `PGPASSWORD` environment variable with `.pgpass` file authentication in `start.py` and `database.py` — passwords no longer visible in process environment
- **Temp file race conditions**: Fixed TOCTOU vulnerabilities in `start.py` — temporary shell config files are now created with correct permissions atomically via `os.open()` with mode flags instead of post-creation `chmod()`
- **Temp cleanup logging**: Replaced `shutil.rmtree(ignore_errors=True)` with explicit error logging in `automation.py` and `db.py` — failed cleanup of temp directories containing sensitive data (SQL dumps) is now visible

### Added
- Database name validation: `db restore` now validates names against PostgreSQL naming rules (letters, digits, underscores; must not start with digit)
- `types-click` added to dev dependencies for improved mypy type checking of Click decorators
- pytest-cov integration: Coverage tracking enabled by default with 45% minimum threshold

## Version 0.4.16 (11.03.2026)

### Changed
- **Rename `commented` → `use` in repos.yaml**: The `commented` field (inverted logic: `true` = disabled) is replaced by the self-documenting `use` field (`true` = active, `false` = disabled). Legacy `commented` field is still supported for backwards compatibility.

## Version 0.4.15 (11.03.2026)

### Changed
- **Dynamic sections for addons_path**: Removed hardcoded `SECTION_ORDER` list from `odoo_config.py` — sections in the generated `odoo.conf` now follow the insertion order from `repos.yaml`. Any section name (e.g. "DACH", "Design", "Chatbot", "fast-report") is supported; previously only 8 fixed names were recognized and all others were silently dropped.

## Version 0.4.14 (11.03.2026)

### Added
- **Interpreter health check**: Detects broken UV tool environments where Python versions have been removed by `uv python` updates
  - `check_interpreter_health()`: Validates the running Python interpreter's symlink chain at CLI startup; exits with clear fix instruction (`uv tool upgrade --all`) if broken
  - `check_venv_interpreter()`: Validates Odoo venv Python symlink chains before `odoodev start`; suggests `odoodev venv setup <version> --force` if broken
  - `_resolve_symlink_chain()`: Utility to follow and report multi-level symlink chains with broken-link detection
- **Shell wrapper pre-flight checks**: `odoodev-activate` (Fish/Bash/Zsh) now verifies the odoodev interpreter is functional before calling it — catches the case where `odoodev` itself cannot start at all
- 14 new tests for interpreter health checks (symlink chain resolution, broken venvs, UV tool directory detection)

## Version 0.4.13 (11.03.2026)

### Added
- System dependency checks for `odoodev init`: Node.js, npm, Node packages (rtlcss, less, less-plugin-clean-css), and system libraries (libldap, libxml2, libxslt, libjpeg, cairo, fontconfig)
- Platform-specific install instructions: Homebrew (macOS) and apt-get (Linux/Debian)
- `check_node()`: Detects Node.js with version warning (< 20) and npm availability check
- `check_node_packages()`: Verifies rtlcss/lessc binaries and less-plugin-clean-css via npm
- `check_system_libs()`: Checks C-extension build dependencies via `brew --prefix` (macOS) or `dpkg -l` (Linux)
- 17 new tests for all prerequisite checks

### Changed
- All new checks are WARNING-level (non-blocking) — pre-built wheels don't need system libs

## Version 0.4.12 (09.03.2026)

### Added
- `odoodev pull`: Automatic Odoo config regeneration (`odoo_YYMMDD.conf`) after pulling repositories, so the `addons_path` stays up-to-date when new modules arrive via pull
- `odoodev pull --no-config`: Opt-out flag to skip config regeneration when only a quick pull is needed

## Version 0.4.11 (06.03.2026)

### Fixed
- **Security hardening**: Eliminated all `shell=True` subprocess calls in `database.py` and `git_ops.py` to prevent command injection via user-supplied database names, git URLs, and branch names
- `database.py`: All PostgreSQL commands (`psql`, `createdb`, `dropdb`, `pg_dump`) now use safe argument lists instead of shell string interpolation
- `git_ops.py`: `run_git_command()` signature changed from `str` to `list[str]`; all git operations (`clone`, `checkout`, `pull`, `ls-remote`) and `find` commands use argument lists
- `backup_database_sql()` and `extract_backup()` gz: Shell output redirects replaced with Python file handles
- Removed obsolete `S602` ruff ignores from `pyproject.toml`

## Version 0.4.10 (05.03.2026)

### Fixed
- `odoodev venv check`: Patch version upgrade now correctly passes the full Python version (e.g. `3.13.12`) to `venv setup`, so UV creates the venv with the exact detected version instead of the latest for the major.minor
- `odoodev venv setup`: Uses `--clear` flag when recreating an existing venv, preventing UV's interactive "replace?" prompt
- `odoodev core/venv_manager.py`: `create_venv()` now appends `--clear` when target directory exists

## Version 0.4.9 (05.03.2026)

### Fixed
- Fish shell: `odoodev-activate` used reserved `$version` variable (Fish built-in = Fish version e.g. `4.5.0`), causing all commands to receive wrong version. Renamed to `$_odoo_ver`.

## Version 0.4.8 (05.03.2026)

### Added
- Fish shell completions for all `odoodev` commands, subcommands, and flags via Click's built-in completion
- Dynamic version completions for `odoodev-activate` (Tab shows available versions like 16, 17, 18, 19)
- Fish abbreviations: `oda` -> `odoodev-activate`, `odev` -> `odoodev`
- Bash/Zsh completions for `odoodev` (via `eval`) and `odoodev-activate`
- Bash/Zsh aliases: `oda` -> `odoodev-activate`, `odev` -> `odoodev`
- `odoodev config versions --plain` flag for script-friendly output (one version per line)
- Python patch version advisory: `odoodev start` and `odoodev venv check` warn when a newer Python patch version is available on the system
- `get_full_python_version()` and `get_system_python_version()` in `venv_manager.py`
- Zsh now has its own completion block (using `compdef`) instead of sharing Bash's function
- 27 new tests for shell integration (completions, abbreviations, installation, `--plain` flag)

### Changed
- `odoodev shell-setup` now installs completions, abbreviations/aliases alongside the `odoodev-activate` function
- Shell setup output shows what was installed (completions, abbreviations/aliases)
- `tests/**` excluded from ruff S101 rule (assert is standard in pytest)
- README.md refactored: compact main README with links to `usage/` documentation files
- Separate bilingual docs (DE/EN) in `usage/` for: setup, start, db, repos, venv, docker, run, shell, config

## Version 0.4.7 (05.03.2026)

### Changed
- All commands now interactive when flags are omitted — "prompt if not provided" pattern
- `odoodev db drop` without `-n`: interactive database selection via `_select_database()`
- `odoodev db restore` without `-n`/`-z`: interactive file path and database name prompts with smart name suggestion from filename
- `odoodev run` without args: interactive mode selection (YAML playbook or inline step checkbox)
- `odoodev start` prerequisite checks: missing `.env`, `.venv`, `odoo-bin`, `odoo_*.conf` now offer to create/clone via `confirm()` + `ctx.invoke()` instead of showing error
- `odoodev env check`/`env show`: missing `.env` offers creation via `confirm()` + `ctx.invoke(env_setup)`
- `odoodev venv check`/`venv activate`: missing `.venv` offers creation via `confirm()` + `ctx.invoke(venv_setup)`
- `odoodev repos`/`pull`: missing `repos.yaml` copies example template and shows guidance instead of bare error
- New output helpers: `text_input()`, `path_input()`, `checkbox()` in `output.py`
- All commands remain fully scriptable — explicit flags skip interactive prompts

## Version 0.4.6 (05.03.2026)

### Changed
- Questionary as unified prompt system across all commands

## Version 0.4.5 (05.03.2026)

### Changed
- `odoodev db drop` now also removes the filestore directory (`~/odoo-share/vXX/filestore/{db_name}/`) when dropping a database
- Confirmation prompt includes filestore notice when a filestore exists
- `odoodev db restore` now shows a hint to run `odoodev start -- -d {name} -u all` after restore

## Version 0.4.4 (04.03.2026)

### Changed
- `odoodev pull` now shows detailed error messages when repository updates fail (e.g. branch not found, merge conflicts)
- `update_repo()` returns `tuple[bool, str]` instead of `bool` to propagate git error messages
- `--verbose` flag now produces debug logs per repository (updating, success/failure)
- Summary table displays error details below the table for each failed repository

## Version 0.4.0 (27.02.2026)

### Added
- `odoodev run` command — YAML-driven playbook automation for AI agents and scripted workflows
- Two execution modes: YAML playbook files (`odoodev run playbook.yaml`) and inline steps (`odoodev run --step docker.up --step pull -V 18`)
- 15 non-interactive command handlers: `docker.up`, `docker.down`, `docker.status`, `pull`, `repos`, `start`, `stop`, `db.list`, `db.backup`, `db.restore`, `db.drop`, `env.check`, `venv.check`, `venv.setup`
- `--dry-run` flag for previewing playbook steps without execution
- `--output json` for NDJSON machine-readable output (one JSON event per line)
- Per-step `on_error` override (stop/continue) with playbook-level default
- Non-blocking `start` handler — launches Odoo as background subprocess
- `--yes` flag for `odoodev db drop` to skip confirmation prompt
- 4 bundled example playbooks in `odoodev/data/examples/playbooks/`: daily-update, start-dev, full-refresh, restore-db
- `odoodev/core/playbook.py` — frozen dataclasses (`StepConfig`, `PlaybookConfig`, `StepResult`, `PlaybookResult`), YAML loader with validation, `PlaybookRunner`
- `odoodev/core/automation.py` — handler registry (`COMMAND_HANDLERS`) with non-interactive wrappers around core functions
- 69 new tests covering playbook engine, automation handlers, and CLI integration

### Fixed
- `odoodev start --no-confirm` now also skips the Docker start confirmation prompt

## Version 0.3.4 (27.02.2026)

### Fixed
- Odoo config templates (v16-v19): replaced deprecated `longpolling_port` with `gevent_port`
- Odoo config templates (v16-v19): corrected `limit_request` from `8192` to `65536` (official default)
- v16 template: replaced deprecated `osv_memory_age_limit` with `transient_age_limit = 1.0`
- v19 template: replaced `without_demo` with `with_demo` (new v19 parameter)
- Removed invalid parameters from all templates: `demo = {}`, `translate_modules`

### Changed
- Removed unused Jinja2 master template `odoo_template.conf.j2` (not version-specific, never used by repos command)
- Credentials in all example templates now use project standard (`ownerp`/`CHANGE_AT_FIRST`)

### Security
- Default password replaced with `CHANGE_AT_FIRST` across all source files, templates, and documentation
- Git history cleaned via `git filter-repo` to remove hardcoded credentials from all historical commits

## Version 0.3.3 (26.02.2026)

### Added
- `odoodev pull [VERSION]` command — quick `git pull` across all existing repositories without cloning, SSH access checks, or config regeneration
- `odoodev db backup [VERSION]` subcommand — create database backups as SQL dump (`pg_dump`) or ZIP with filestore (Odoo standard format)
- Interactive database and backup type selection when options are omitted
- Core functions `backup_database_sql()` and `create_backup_zip()` in `database.py`
- Rich summary table for pull results (Updated/Skipped/Failed)
- Tests for pull command (6 tests) and db backup (7 tests)

## Version 0.3.2 (26.02.2026)

### Added
- `odoodev stop [VERSION]` command — stops running Odoo process (via port-based process discovery) and Docker services
- `odoodev/core/process_manager.py` — reusable core module for process discovery via `lsof` and graceful termination (SIGTERM → SIGKILL)
- `--keep-docker` flag for `stop` — keeps PostgreSQL/Mailpit running while stopping Odoo
- `--force` flag for `stop` — immediate SIGKILL without graceful shutdown
- `odoodev init` now checks for `wkhtmltopdf` at startup — shows install hint if missing (non-blocking warning)
- Start modes overview table in README (DE + EN) documenting all `--dev`, `--shell`, `--test`, `--prepare` flags

### Changed
- Start prompt improved: "Start Odoo v18 server?" instead of unclear "in normal mode"; descriptive labels for dev/shell/test modes
- When declining start prompt, alternative modes (`--dev`, `--shell`, `--test`, `--prepare`) are now shown with descriptions

### Fixed
- Mailpit URL in start banner is now only displayed when the Mailpit service is actually reachable (port check via `check_port()`)
- `wkhtmltopdf` install hint now recommends the 'patched qt' binary from wkhtmltopdf.org instead of `brew install wkhtmltopdf` — Homebrew's version lacks patched Qt and may not render Odoo PDF reports correctly
- README installation instructions corrected accordingly (both DE and EN sections)

## Version 0.2.0 (24.02.2026)

### Added
- Interactive setup wizard (`odoodev setup`) with questionary-based prompts for base directory, active versions, and database credentials
- Global configuration infrastructure (`global_config.py`) with `GlobalConfig` and `DatabaseConfig` frozen dataclasses, YAML persistence, and module-level caching
- First-run detection hint when no configuration exists
- `--non-interactive` flag for automated setup with defaults
- `--reset` flag to restore default configuration
- Global Configuration section in `config show` output
- Dynamic base directory support — version paths automatically rebase when global config has custom `base_dir`

### Changed
- Database credentials in `.env` template are now parametrized via global config instead of hardcoded
- `database.py` reads credentials from global config at runtime with fallback to module constants
- `version_registry.py` uses global config `base_dir` for version auto-detection and path resolution
- README.md restructured with setup wizard documentation at prominent position
- Version bump to 0.2.0

### Fixed
- Version path rebasing respects explicit user overrides from `versions-override.yaml`

## Version 0.1.0

- Initial release with CLI commands: init, start, repos, db, env, venv, docker, config, shell-setup
- Version registry with frozen dataclasses and user override support
- Jinja2 template system for .env, docker-compose.yml, and odoo.conf generation
- UV-based virtual environment management with requirements hash tracking
- Rich console output helpers
