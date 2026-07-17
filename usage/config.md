# Configuration & Versions

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

### Konfigurationsbefehle

```bash
# Alle Versionen mit Konfiguration anzeigen
odoodev config versions

# Nur Versionsnummern (fuer Skripte)
odoodev config versions --plain

# Versionen als JSON ausgeben
odoodev config versions --json

# Plattform und Konfiguration anzeigen
odoodev config show

# Konfigurationswert setzen
odoodev config set base_dir ~/projects/odoo
odoodev config set language de
odoodev config set db.user ownerp
odoodev config set db.password geheim
odoodev config set active_versions 16,17,18,19

# Konfigurationsdatei im Editor oeffnen
odoodev config edit
```

### Konfiguration setzen (`odoodev config set`)

```bash
odoodev config set <key> <value>
```

Setzt einen einzelnen Konfigurationswert in `~/.config/odoodev/config.yaml`.
Unbekannte Schluessel werden abgewiesen. Passwoerter werden nicht auf dem Terminal
wiederholt (silent).

| Schluessel | Werte |
|------------|-------|
| `base_dir` | Pfad, z.B. `~/projects/odoo` |
| `language` | `en` oder `de` |
| `db.user` | PostgreSQL-Benutzername |
| `db.password` | PostgreSQL-Passwort (nicht echo) |
| `odoo_login.username` | Odoo-XML-RPC-Login (res.users) fuer Modul-Aktionen/Export (v0.59.0, Default `admin`) |
| `odoo_login.password` | Odoo-XML-RPC-Passwort (maskiert ausgegeben, Default `admin`) |
| `active_versions` | Kommagetrennt, z.B. `16,17,18,19` |
| `container_runtime` | `docker` oder `apple` |

### Konfiguration im Editor oeffnen (`odoodev config edit`)

```bash
odoodev config edit
```

Oeffnet `~/.config/odoodev/config.yaml` im Editor (`$EDITOR`, Fallback `$VISUAL`,
dann `vi`). Existiert die Datei noch nicht, werden Standardwerte erstellt.

### config versions --json

```bash
odoodev config versions --json
```

Gibt ein JSON-Objekt aus, das nach Versionsnummer indiziert ist:

```json
{
  "18": {
    "python": "3.13",
    "postgres": "16.11",
    "ports": {"db": 18432, "odoo": 18069, "gevent": 18072, "mailpit": 18025},
    "effective_ports": {"db": 28432, "odoo": 28069, "gevent": 28072, "mailpit": 28025},
    "base": "~/gitbase/v18"
  }
}
```

`effective_ports` (seit 0.58.0) sind die tatsaechlich genutzten Laufzeit-Ports:
Registry-Defaults, ueberschrieben durch `DB_PORT`/`ODOO_PORT`/`GEVENT_PORT`/
`MAILPIT_PORT` aus der `.env` der Version. Auf Multi-User-Hosts hat jeder
Benutzer ein eigenes Port-Praefix — Konsumenten (GUI, Agents) muessen Container
und URLs gegen `effective_ports` aufloesen, nicht gegen `ports`.

`--plain` und `--json` sind gegenseitig ausschliessend.

### Unterstuetzte Versionen

| Version | Python | PostgreSQL | DB Port | Odoo Port | Gevent | Mailpit | SMTP |
|---------|--------|------------|---------|-----------|--------|---------|------|
| v16 | 3.12 | 16.11 | 16432 | 16069 | 16072 | 16025 | 11025 |
| v17 | 3.12 | 16.11 | 17432 | 17069 | 17072 | 17025 | 11725 |
| v18 | 3.13 | 16.11 | 18432 | 18069 | 18072 | 18025 | 1025 |
| v19 | 3.13 | 17.4 | 19432 | 19069 | 19072 | 19025 | 1925 |

Port-Schema: `{version}{service}` — z.B. v18: DB=18432, Odoo=18069, Gevent=18072

### Globale Konfiguration (`odoodev setup`)

Gespeichert in `~/.config/odoodev/config.yaml`:

| Einstellung | Standard | Beschreibung |
|-------------|----------|--------------|
| `base_dir` | `~/gitbase` | Basisverzeichnis fuer alle Odoo-Versionen |
| `database.user` | `ownerp` | Standard-PostgreSQL-Benutzer |
| `database.password` | `CHANGE_AT_FIRST` | Standard-PostgreSQL-Passwort |
| `active_versions` | `16, 17, 18, 19` | Aktive Odoo-Versionen |

Die DB-Credentials aus `config.yaml` werden automatisch in `.env`-Dateien und Datenbankoperationen verwendet.

### Versionsspezifische Overrides

**Datei:** `~/.config/odoodev/versions-override.yaml`

```yaml
versions:
  "18":
    ports:
      db: 15432          # Eigener PostgreSQL-Port
      odoo: 8069         # Standard-Odoo-Port statt 18069
    paths:
      base: "~/projects/odoo18"
    git:
      branch: "main"     # Anderer Default-Branch
```

Nur angegebene Felder werden ueberschrieben — alle anderen behalten ihre Standardwerte.

### Konfigurationsprioritaet

1. `versions-override.yaml` (hoechste — Pfade werden **nicht** von `base_dir` umgebogen)
2. `config.yaml` (globale Einstellungen wie `base_dir`)
3. `versions.yaml` im Paket (Standardwerte)

### Automatische Versionserkennung

Die Odoo-Version wird aus dem aktuellen Verzeichnispfad erkannt:

```
~/gitbase/v18/v18-dev/dev18_native/ → Version 18
~/gitbase/v16/v16-dev/3.11/         → Version 16
```

Wenn nicht erkennbar, muss die Version explizit angegeben werden:

```bash
odoodev start 18
```

---

## English Documentation

### Configuration Commands

```bash
# Show all versions with configuration
odoodev config versions

# Version numbers only (for scripts)
odoodev config versions --plain

# Versions as JSON
odoodev config versions --json

# Show platform and configuration
odoodev config show

# Set a configuration value
odoodev config set base_dir ~/projects/odoo
odoodev config set language en
odoodev config set db.user ownerp
odoodev config set db.password secret
odoodev config set active_versions 16,17,18,19

# Open configuration file in editor
odoodev config edit
```

### Set Configuration Values (`odoodev config set`)

```bash
odoodev config set <key> <value>
```

Sets a single configuration value in `~/.config/odoodev/config.yaml`.
Unknown keys are rejected. Passwords are never echoed to the terminal.

| Key | Values |
|-----|--------|
| `base_dir` | Path, e.g. `~/projects/odoo` |
| `language` | `en` or `de` |
| `db.user` | PostgreSQL username |
| `db.password` | PostgreSQL password (not echoed) |
| `odoo_login.username` | Odoo XML-RPC login (res.users) for module actions/export (v0.59.0, default `admin`) |
| `odoo_login.password` | Odoo XML-RPC password (masked output, default `admin`) |
| `active_versions` | Comma-separated, e.g. `16,17,18,19` |
| `container_runtime` | `docker` or `apple` |

### Open Configuration in Editor (`odoodev config edit`)

```bash
odoodev config edit
```

Opens `~/.config/odoodev/config.yaml` in the editor (`$EDITOR`, fallback `$VISUAL`,
then `vi`). If the file does not yet exist, defaults are created first.

### config versions --json

```bash
odoodev config versions --json
```

Returns a JSON object keyed by version number:

```json
{
  "18": {
    "python": "3.13",
    "postgres": "16.11",
    "ports": {"db": 18432, "odoo": 18069, "gevent": 18072, "mailpit": 18025},
    "effective_ports": {"db": 28432, "odoo": 28069, "gevent": 28072, "mailpit": 28025},
    "base": "~/gitbase/v18"
  }
}
```

`effective_ports` (since 0.58.0) are the ports actually used at runtime:
registry defaults overridden by `DB_PORT`/`ODOO_PORT`/`GEVENT_PORT`/
`MAILPIT_PORT` from the version's `.env`. On multi-user hosts every user has
an own port prefix — consumers (GUI, agents) must resolve containers and URLs
against `effective_ports`, not `ports`.

`--plain` and `--json` are mutually exclusive.

### Supported Versions

| Version | Python | PostgreSQL | DB Port | Odoo Port | Gevent | Mailpit | SMTP |
|---------|--------|------------|---------|-----------|--------|---------|------|
| v16 | 3.12 | 16.11 | 16432 | 16069 | 16072 | 16025 | 11025 |
| v17 | 3.12 | 16.11 | 17432 | 17069 | 17072 | 17025 | 11725 |
| v18 | 3.13 | 16.11 | 18432 | 18069 | 18072 | 18025 | 1025 |
| v19 | 3.13 | 17.4 | 19432 | 19069 | 19072 | 19025 | 1925 |

Port schema: `{version}{service}` — e.g. v18: DB=18432, Odoo=18069, Gevent=18072

### Global Configuration (`odoodev setup`)

Stored in `~/.config/odoodev/config.yaml`:

| Setting | Default | Description |
|---------|---------|-------------|
| `base_dir` | `~/gitbase` | Base directory for all Odoo versions |
| `database.user` | `ownerp` | Default PostgreSQL user |
| `database.password` | `CHANGE_AT_FIRST` | Default PostgreSQL password |
| `active_versions` | `16, 17, 18, 19` | Active Odoo versions |

DB credentials from `config.yaml` are automatically used in `.env` files and database operations.

### Version-Specific Overrides

**File:** `~/.config/odoodev/versions-override.yaml`

```yaml
versions:
  "18":
    ports:
      db: 15432          # Custom PostgreSQL port
      odoo: 8069         # Standard Odoo port instead of 18069
    paths:
      base: "~/projects/odoo18"
    git:
      branch: "main"     # Different default branch
```

Only specified fields are overridden — all others retain their default values.

### Configuration Priority

1. `versions-override.yaml` (highest — paths are **not** rebased by `base_dir`)
2. `config.yaml` (global settings like `base_dir`)
3. `versions.yaml` in the package (defaults)

### Automatic Version Detection

The Odoo version is detected from the current directory path:

```
~/gitbase/v18/v18-dev/dev18_native/ → Version 18
~/gitbase/v16/v16-dev/3.11/         → Version 16
```

If not detectable, the version must be specified explicitly:

```bash
odoodev start 18
```
