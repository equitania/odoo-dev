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

### Datenbank-Handling waehrend der Migration

Bei aktiver Migration zeigen Quell- **und** Zielversion auf denselben PostgreSQL-Container. Alle `odoodev db`-Befehle (`list`, `backup`, `restore`, `copy`, `rename`, `drop`, `neutralize`) erreichen daher mit beiden Versionsnummern dieselben Datenbanken — die Umleitung passiert automatisch, erkennbar an der `[MIGRATION]`-Zeile:

```bash
odoodev db list 16   # identische Liste ...
odoodev db list 18   # ... beide zeigen auf den geteilten Port (z.B. 16432)
```

#### Empfohlener Backup-/Restore-Workflow

Grundregel: **nie am Original migrieren.** Erst Sicherungspunkt, dann Arbeitskopie, dann migrieren.

```bash
# 1. Sicherungspunkt VOR der Migration (ZIP = Dump + Filestore, landet in ~/Downloads/)
odoodev db backup 16 -n mydb -t zip
# grosse Datenbanken: tar.zst (Streaming, stark komprimiert, Kompressionslevel 1-22)
odoodev db backup 16 -n mydb -t tar.zst -l 10

# 2. Arbeitskopie anlegen und diese migrieren (Original bleibt unberuehrt)
odoodev db copy 16 -s mydb -d mydb_v18
odoodev start 18 -d mydb_v18 -u all

# 3. Nach erfolgreicher Migration erneut sichern
odoodev db backup 18 -n mydb_v18 -t zip

# 4. Fehlversuch verwerfen und neu ansetzen
odoodev db drop 18 -n mydb_v18 --yes
odoodev db copy 16 -s mydb -d mydb_v18          # frische Kopie vom Original
# oder vom Sicherungspunkt wiederherstellen:
odoodev db restore 16 -z ~/Downloads/mydb_*.zip -n mydb_v18
```

Hinweise:

- `db drop` loest waehrend aktiver Migration bewusst eine Warnung aus — Quell- und Ziel-Datenbanken liegen im selben Container, ein Tippfehler bei der Versionsnummer schuetzt nicht vor dem Loeschen.
- `db restore` deaktiviert standardmaessig Cronjobs/Mailserver und bietet Neutralisierung + Anonymisierung an — fuer Migrations-Arbeitskopien in der Regel erwuenscht (`--no-deactivate-cron` etc. zum Abschalten).
- `db copy` verlangt eine verbindungsfreie Quelldatenbank; laufende Odoo-Instanz vorher stoppen oder `--terminate-connections` nutzen.

#### Filestore im Migrationsumfeld

Waehrend aktiver Migration nutzen beide Versionen den **geteilten** Filestore `~/odoo-share/migration/{name}/filestore/{db}`. `db backup` (ZIP/tar.zst) sichert ihn automatisch mit; `db copy`, `db rename` und `db drop` behandeln ihn am geteilten Pfad.

Nach `migrate deactivate` zeigt jede Version wieder auf ihren eigenen Pfad (`~/odoo-share/v{XX}/filestore/`) — die Anhaenge der migrierten Datenbank blieben sonst im Migrationsverzeichnis zurueck. Saubere Uebergabe in die Zielumgebung:

```bash
# noch IM Migrationsmodus: Komplett-Backup (Dump + geteilter Filestore)
odoodev db backup 18 -n mydb_v18 -t zip

# Migrationsmodus beenden
odoodev migrate deactivate

# in der regulaeren Zielumgebung wiederherstellen
odoodev docker up 18
odoodev db restore 18 -z ~/Downloads/mydb_v18_*.zip -n mydb
```

`db restore` legt den Filestore dabei automatisch am regulaeren Pfad der Zielversion ab.

#### Ohne PostgreSQL-Client-Tools (Migrationsserver)

Auf Migrationsservern laeuft PostgreSQL oft nur im Docker-Container und der Host hat kein `psql`/`pg_dump`. Seit v0.42.0 laufen alle `db`-Befehle dann automatisch per `docker exec` im Container (einmalige `[INFO]`-Zeile beim ersten Aufruf). Das umgeht auch Versionskonflikte des Host-Clients (z.B. Debian 12: `postgresql-client-15` gegen einen Postgres-16-Container) — im Container passt die Client-Version immer.

- Sind weder Client-Tools noch ein laufender Container vorhanden, bricht der Befehl mit einer klaren Meldung ab (Tools installieren **oder** `odoodev docker up`).
- Erzwingen laesst sich der Modus per `ODOODEV_PG_EXEC=host|container`.
- Der Fallback ist Docker-only; unter Apple Container stattdessen `brew install libpq`.

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
| `db backup {ziel}` / `start {ziel}` versucht den regulaeren Port statt des geteilten (z.B. 18432 statt 16432) | odoodev < 0.42.1: `.env`-`DB_PORT` der Zielversion uebersteuerte die Migration | Update auf >= 0.42.1 (`uv tool upgrade odoodev-equitania`) |
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

### Database Handling During Migration

While a migration is active, source **and** target version point at the same PostgreSQL container. All `odoodev db` commands (`list`, `backup`, `restore`, `copy`, `rename`, `drop`, `neutralize`) therefore reach the same databases with either version number — the redirection is automatic, indicated by the `[MIGRATION]` line:

```bash
odoodev db list 16   # identical list ...
odoodev db list 18   # ... both point at the shared port (e.g. 16432)
```

#### Recommended Backup/Restore Workflow

Ground rule: **never migrate the original.** Safety backup first, then a working copy, then migrate.

```bash
# 1. Safety backup BEFORE the migration (ZIP = dump + filestore, written to ~/Downloads/)
odoodev db backup 16 -n mydb -t zip
# large databases: tar.zst (streaming, highly compressed, compression level 1-22)
odoodev db backup 16 -n mydb -t tar.zst -l 10

# 2. Create a working copy and migrate that one (original stays untouched)
odoodev db copy 16 -s mydb -d mydb_v18
odoodev start 18 -d mydb_v18 -u all

# 3. Back up again after a successful migration
odoodev db backup 18 -n mydb_v18 -t zip

# 4. Discard a failed attempt and start over
odoodev db drop 18 -n mydb_v18 --yes
odoodev db copy 16 -s mydb -d mydb_v18          # fresh copy from the original
# or restore from the safety backup:
odoodev db restore 16 -z ~/Downloads/mydb_*.zip -n mydb_v18
```

Notes:

- `db drop` deliberately triggers a warning while a migration is active — source and target databases live in the same container, so a typo in the version number does not protect against deletion.
- `db restore` deactivates cron jobs/mail servers by default and offers neutralization + anonymization — usually desirable for migration working copies (`--no-deactivate-cron` etc. to opt out).
- `db copy` requires a connection-free source database; stop a running Odoo instance first or use `--terminate-connections`.

#### Filestore in the Migration Environment

While a migration is active, both versions use the **shared** filestore `~/odoo-share/migration/{name}/filestore/{db}`. `db backup` (ZIP/tar.zst) includes it automatically; `db copy`, `db rename` and `db drop` handle it at the shared path.

After `migrate deactivate`, each version points back at its own path (`~/odoo-share/v{XX}/filestore/`) — the migrated database's attachments would otherwise be left behind in the migration directory. Clean handover into the target environment:

```bash
# still IN migration mode: full backup (dump + shared filestore)
odoodev db backup 18 -n mydb_v18 -t zip

# leave migration mode
odoodev migrate deactivate

# restore in the regular target environment
odoodev docker up 18
odoodev db restore 18 -z ~/Downloads/mydb_v18_*.zip -n mydb
```

`db restore` then places the filestore at the target version's regular path automatically.

#### Without PostgreSQL Client Tools (Migration Servers)

On migration servers PostgreSQL often runs only inside the Docker container and the host has no `psql`/`pg_dump`. Since v0.42.0, all `db` commands then run automatically via `docker exec` inside the container (a one-time `[INFO]` line on first use). This also sidesteps host client version mismatches (e.g. Debian 12: `postgresql-client-15` against a Postgres 16 container) — inside the container the client version always matches.

- If neither client tools nor a running container are available, the command aborts with a clear message (install the tools **or** `odoodev docker up`).
- The mode can be forced via `ODOODEV_PG_EXEC=host|container`.
- The fallback is Docker-only; on Apple Container install `brew install libpq` instead.

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
| `db backup {target}` / `start {target}` tries the regular port instead of the shared one (e.g. 18432 instead of 16432) | odoodev < 0.42.1: the target's `.env` `DB_PORT` overrode the migration | Update to >= 0.42.1 (`uv tool upgrade odoodev-equitania`) |
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
