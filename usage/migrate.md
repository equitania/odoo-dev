# Migration Mode

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

### Uebersicht

Der Migrationsmodus ermoeglicht versionsuebergreifende Datenbank-Migrationen, indem ein PostgreSQL-Container und ein Filestore zwischen zwei Odoo-Versionen geteilt werden.

### Schnellstart

```bash
# 1. Migrationsgruppe erstellen
odoodev migrate create --from 16 --to 18

# 2. Migrationsmodus aktivieren
odoodev migrate activate 16-to-18

# 3. Quell-Datenbank starten
odoodev docker up 16

# 4. Quelldatenbank pruefen
odoodev start 16 -d mydb

# 5. Migration ausfuehren (v18 nutzt v16-Container)
odoodev start 18 -d mydb -u all

# 6. Migrierte Datenbank testen
odoodev start 18 -d mydb

# 7. Migrationsmodus beenden
odoodev migrate deactivate
odoodev migrate remove 16-to-18
```

### Subcommands

| Befehl | Beschreibung |
|--------|--------------|
| `odoodev migrate create --from X --to Y` | Migrationsgruppe erstellen |
| `odoodev migrate activate NAME` | Migrationsgruppe aktivieren |
| `odoodev migrate deactivate` | Aktive Migration deaktivieren |
| `odoodev migrate status` | Status der aktiven Migration anzeigen |
| `odoodev migrate list` | Alle definierten Gruppen auflisten |
| `odoodev migrate remove NAME [--yes]` | Gruppe entfernen |

### Optionen bei `create`

| Option | Beschreibung |
|--------|--------------|
| `--from VERSION` | Quellversion (erforderlich) |
| `--to VERSION` | Zielversion (erforderlich) |
| `--name NAME` | Benutzerdefinierter Gruppenname (Standard: `{from}-to-{to}`) |
| `--pg-version PG` | PostgreSQL-Image ueberschreiben (Standard: Image der Quellversion) |

### Was wird geteilt?

| Geteilt | Getrennt (pro Version) |
|---------|----------------------|
| PostgreSQL-Container (Quellversion) | Python Virtual Environment |
| Datenbank-Port (Quellversion) | Odoo-Server (`odoo-bin`) |
| Filestore (`~/odoo-share/migration/{name}/filestore/`) | Odoo-Konfiguration (`odoo_YYMMDD.conf`) |
| | Repositories und Addons |

### Transparente Integration

Bei aktivem Migrationsmodus erscheint `[MIGRATION]` in der Konsolenausgabe. Folgende Befehle werden automatisch umgeleitet:

- `odoodev docker up {ziel}` → startet den Quell-Container
- `odoodev docker down {quelle}` → Warnung wegen Abhaengigkeit
- `odoodev start {ziel}` → nutzt den DB-Port der Quellversion

### Voraussetzungen

- Beide Odoo-Versionen sind via `odoodev init` initialisiert
- Quellversion verfuegt ueber eine funktionierende Datenbank
- Docker laeuft
- Beide Versionen haben eigene venvs mit installierten Abhaengigkeiten

### Funktionsweise

Der Migrationsstatus wird in `~/.config/odoodev/migration.yaml` persistiert. Bei aktiver Gruppe pruefen alle `odoodev`-Befehle automatisch:

- `load_versions()` ueberschreibt den DB-Port der Zielversion auf den Quell-Container
- `get_filestore_path()` leitet beide Versionen auf einen gemeinsamen Filestore um
- `docker up` auf der Zielversion wird auf den Quell-Container umgeleitet
- `docker down` auf der Quellversion warnt wegen geteilter Abhaengigkeit

**Geltungsbereich:** Nur die Zielversion wird umgeleitet. Alle anderen Versionen bleiben vollstaendig isoliert und unbeeinflusst.

### Geltungsbereich und Einschraenkungen

- **Nur die Zielversion wird umgeleitet** — alle anderen Versionen bleiben unbeeinflusst
- **Eine aktive Migration zur selben Zeit** — es kann nur eine Gruppe aktiv sein
- **Globaler Geltungsbereich** — Migrationsmodus gilt fuer alle Terminal-Sessions
- **Sicherheitswarnungen** — `docker down` auf den Quell-Container und `db drop` waehrend aktiver Migration loesen Warnungen aus
- **Kein Odoo-Docker-Container** — Odoo laeuft immer nativ; nur PostgreSQL laeuft in Docker

### PostgreSQL-Kompatibilitaet

Alle Odoo-Versionen 16–19 unterstuetzen PostgreSQL 14–16. Der geteilte Container verwendet stets das Image der Quellversion.

| Migration | Quell-PG | Ziel-PG | Geteiltes PG | Kompatibel |
|-----------|----------|---------|--------------|------------|
| v16 zu v17 | 16.11 | 16.11 | 16.11 | Ja |
| v16 zu v18 | 16.11 | 16.11 | 16.11 | Ja |
| v16 zu v19 | 16.11 | 17.4 | 16.11 | Ja |
| v17 zu v18 | 16.11 | 16.11 | 16.11 | Ja |
| v18 zu v19 | 16.11 | 17.4 | 16.11 | Ja |

Wenn Quell- und Zielversion unterschiedliche PostgreSQL-Hauptversionen verwenden, zeigt `odoodev migrate create` eine Warnung an und nutzt standardmaessig das Image der Quellversion.

### Status und Troubleshooting

```bash
# Status anzeigen
odoodev migrate status

# Port-Override pruefen — bei aktiver Migration zeigt der Ziel-Port den geteilten (Quell-)Port
odoodev config versions
```

| Problem | Ursache | Loesung |
|---------|---------|---------|
| Zielversion kann sich nicht mit DB verbinden | Quell-Container laeuft nicht | `odoodev docker up {quelle}` |
| Filestore nicht gefunden | Geteiltes Verzeichnis nicht angelegt | Pruefe `~/odoo-share/migration/{name}/filestore/` |
| Migration nach `deactivate` weiterhin aktiv | Cache-Problem | Terminal-Session neu starten |
| Port-Konflikt | Beide Versionen mit eigenem Container gestartet | Container der Zielversion stoppen, Quell-Container nutzen |

### Konfigurationsdatei

Der Migrations-Status liegt unter `~/.config/odoodev/migration.yaml`:

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

---

## English Documentation

### Overview

Migration mode enables cross-version database migrations by sharing a PostgreSQL container and filestore between two Odoo versions.

### Quick Start

```bash
# 1. Create migration group
odoodev migrate create --from 16 --to 18

# 2. Activate migration mode
odoodev migrate activate 16-to-18

# 3. Start source database
odoodev docker up 16

# 4. Verify source database
odoodev start 16 -d mydb

# 5. Run migration (v18 uses v16 container)
odoodev start 18 -d mydb -u all

# 6. Test migrated database
odoodev start 18 -d mydb

# 7. Deactivate migration mode
odoodev migrate deactivate
odoodev migrate remove 16-to-18
```

### Subcommands

| Command | Description |
|---------|-------------|
| `odoodev migrate create --from X --to Y` | Create a migration group |
| `odoodev migrate activate NAME` | Activate a migration group |
| `odoodev migrate deactivate` | Deactivate current migration |
| `odoodev migrate status` | Show active migration details |
| `odoodev migrate list` | List all defined groups |
| `odoodev migrate remove NAME [--yes]` | Remove a group definition |

### Options for `create`

| Option | Description |
|--------|-------------|
| `--from VERSION` | Source version (required) |
| `--to VERSION` | Target version (required) |
| `--name NAME` | Custom group name (default: `{from}-to-{to}`) |
| `--pg-version PG` | Override PostgreSQL image (default: source version's image) |

### What Is Shared?

| Shared | Separate (per version) |
|--------|----------------------|
| PostgreSQL container (source version) | Python virtual environment |
| Database port (source version) | Odoo server (`odoo-bin`) |
| Filestore (`~/odoo-share/migration/{name}/filestore/`) | Odoo configuration (`odoo_YYMMDD.conf`) |
| | Repositories and addons |

### Transparent Integration

When migration mode is active, `[MIGRATION]` appears in console output. The following commands are automatically redirected:

- `odoodev docker up {target}` → starts the source container
- `odoodev docker down {source}` → warning about dependency
- `odoodev start {target}` → uses the source version's DB port

### Prerequisites

- Both Odoo versions must be initialized via `odoodev init`
- Source version must have a working database
- Docker must be running
- Both versions need their own Python virtual environments with dependencies installed

### How It Works

Migration state is persisted in `~/.config/odoodev/migration.yaml`. When a migration group is **active**, all `odoodev` commands automatically check for it:

- `load_versions()` overrides the target version's DB port to point at the source container
- `get_filestore_path()` redirects both versions to a shared filestore directory
- `docker up` on the target version redirects to the source container
- `docker down` on the source version warns about the shared dependency

**Scope:** Only the target version is redirected. All other versions remain completely isolated and unaffected.

### Scope and Restrictions

- **Only the target version is redirected** — all other versions are unaffected
- **One active migration at a time** — only one group can be active
- **Global scope** — migration mode applies to all terminal sessions
- **Safety warnings** — `docker down` on source container and `db drop` during active migration trigger warnings
- **No Odoo Docker container** — Odoo always runs natively; only PostgreSQL runs in Docker

### PostgreSQL Compatibility

All Odoo versions 16–19 support PostgreSQL 14–16. The shared container always uses the source version's PostgreSQL image.

| Migration | Source PG | Target PG | Shared PG | Compatible |
|-----------|-----------|-----------|-----------|------------|
| v16 to v17 | 16.11 | 16.11 | 16.11 | Yes |
| v16 to v18 | 16.11 | 16.11 | 16.11 | Yes |
| v16 to v19 | 16.11 | 17.4 | 16.11 | Yes |
| v17 to v18 | 16.11 | 16.11 | 16.11 | Yes |
| v18 to v19 | 16.11 | 17.4 | 16.11 | Yes |

When source and target use different PostgreSQL major versions, `odoodev migrate create` shows a warning and defaults to the source version's image.

### Status and Troubleshooting

```bash
# Show status
odoodev migrate status

# Verify port override — when migration is active, the target version's DB port shows the shared (source) port
odoodev config versions
```

| Problem | Cause | Fix |
|---------|-------|-----|
| Target version cannot connect to DB | Source container not running | `odoodev docker up {source}` |
| Filestore not found | Shared directory not created | Check `~/odoo-share/migration/{name}/filestore/` |
| Migration still active after `deactivate` | Cache issue | Restart the terminal session |
| Port conflict | Both versions started with own containers | Stop target's container, use source's |

### Configuration File

Migration state is stored at `~/.config/odoodev/migration.yaml`:

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
