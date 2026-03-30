# Migration Mode — odoodev

## Overview

Migration Mode enables cross-version database migrations by sharing a PostgreSQL container and filestore between two Odoo versions. This eliminates the manual configuration normally required when migrating databases (e.g., v16 to v18).

**What is shared:**
- PostgreSQL Docker container (source version's container)
- Database port (source version's port)
- Filestore path (`~/odoo-share/migration/{name}/filestore/`)

**What stays separate (per version):**
- Python virtual environment (`.venv/`)
- Odoo server binary (`odoo-bin`)
- Odoo configuration (`odoo_YYMMDD.conf`)
- Repositories and addons
- Odoo HTTP port (e.g., v16 on 16069, v18 on 18069)

## Prerequisites

- Both Odoo versions must be initialized via `odoodev init`
- Source version must have a working database
- Docker must be running
- Both versions need their own Python virtual environments with dependencies installed

## How It Works

Migration state is persisted in `~/.config/odoodev/migration.yaml`. When a migration group is **active**, all `odoodev` commands automatically check for it:

- `load_versions()` overrides the target version's DB port to point at the source container
- `get_filestore_path()` redirects both versions to a shared filestore directory
- `docker up` on the target version redirects to the source container
- `docker down` on the source version warns about the shared dependency

A visual indicator `[MIGRATION]` appears in console output when migration mode is active.

**Scope**: Only the target version is redirected. All other versions remain completely isolated and unaffected.

## Usage

### Step 1: Create Migration Group

```bash
odoodev migrate create --from 16 --to 18
```

This creates a migration group named `16-to-18` with:
- Shared DB port: 16432 (source version's port)
- Shared filestore: `~/odoo-share/migration/16-to-18/filestore/`
- PostgreSQL image: source version's image (e.g., `16.11-alpine`)

Optional parameters:
- `--name custom-name` — Custom group name
- `--pg-version 16.11-alpine` — Override PostgreSQL image

### Step 2: Activate Migration Mode

```bash
odoodev migrate activate 16-to-18
```

From this point on, v18 commands use v16's PostgreSQL container and shared filestore. This applies to **all terminal sessions** — the config is persisted on disk.

### Step 3: Start Shared Database

```bash
odoodev docker up 16
```

Starts the PostgreSQL container. Both v16 and v18 Odoo instances will connect to this container.

Note: `odoodev docker up 18` will automatically redirect to v16's container with a `[MIGRATION]` hint.

### Step 4: Prepare Source Database

```bash
odoodev start 16 -d mydb
```

Verify that the source database works correctly before migrating.

### Step 5: Run Migration

```bash
odoodev start 18 -d mydb -u all
```

This starts Odoo v18 with:
- v18's own Python venv and `odoo-bin`
- v18's own `odoo_YYMMDD.conf`
- v16's PostgreSQL container (port 16432)
- Shared filestore

Odoo automatically performs the database migration when starting a newer version with `-u all`.

### Step 6: Verify Migration

```bash
odoodev start 18 -d mydb
```

Test the migrated database in normal mode. Check that all modules work correctly.

### Step 7: Deactivate and Cleanup

```bash
odoodev migrate deactivate          # Restore normal per-version isolation
odoodev migrate remove 16-to-18     # Remove the group definition
```

After deactivation, all versions return to their own isolated environments immediately.

## Command Reference

| Command | Description |
|---------|-------------|
| `odoodev migrate create --from X --to Y` | Create a migration group |
| `odoodev migrate activate NAME` | Activate a migration group |
| `odoodev migrate deactivate` | Deactivate current migration |
| `odoodev migrate status` | Show active migration details |
| `odoodev migrate list` | List all defined groups |
| `odoodev migrate remove NAME [--yes]` | Remove a group definition |

## Scope and Restrictions

- **Only the target version is redirected** — all other versions are unaffected
- **One active migration at a time** — only one group can be active
- **Global scope** — migration mode applies to all terminal sessions
- **Safety warnings** — `docker down` on source container and `db drop` during active migration trigger warnings
- **No Odoo Docker container** — Odoo always runs natively; only PostgreSQL runs in Docker

## PostgreSQL Compatibility

All Odoo versions 16–19 support PostgreSQL 14–16. The shared container always uses the source version's PostgreSQL image.

| Migration | Source PG | Target PG | Shared PG | Compatible |
|-----------|-----------|-----------|-----------|------------|
| v16 to v17 | 16.11 | 16.11 | 16.11 | Yes |
| v16 to v18 | 16.11 | 16.11 | 16.11 | Yes |
| v16 to v19 | 16.11 | 17.4 | 16.11 | Yes |
| v17 to v18 | 16.11 | 16.11 | 16.11 | Yes |
| v18 to v19 | 16.11 | 17.4 | 16.11 | Yes |

When source and target use different PostgreSQL major versions, `odoodev migrate create` shows a warning and defaults to the source version's image.

## Status and Troubleshooting

### Check Migration Status

```bash
odoodev migrate status
```

Shows: active group, source/target versions, shared port, filestore path, container status.

### Verify Port Override

```bash
odoodev config versions
```

When migration is active, the target version's DB port shows the shared (source) port.

### Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| v18 can't connect to DB | Source container not running | `odoodev docker up 16` |
| Filestore not found | Shared directory not created | Check `~/odoo-share/migration/{name}/filestore/` |
| Migration still active after deactivate | Cache issue | Restart the terminal session |
| Port conflict | Both versions started with own containers | Stop target's container, use source's |

## Configuration File

Migration config is stored at `~/.config/odoodev/migration.yaml`:

```yaml
# Managed by: odoodev migrate — do not edit manually
active: 16-to-18
groups:
  16-to-18:
    from_version: '16'
    to_version: '18'
    pg_version: 16.11-alpine
    shared_db_port: 16432
    shared_filestore_base: ~/odoo-share/migration/16-to-18
    created_at: '2026-03-30T10:00:00+00:00'
```
