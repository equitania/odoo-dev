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

> Technische Details und Troubleshooting: [docs/migration-mode.md](../docs/migration-mode.md)

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

> Technical details and troubleshooting: [docs/migration-mode.md](../docs/migration-mode.md)
