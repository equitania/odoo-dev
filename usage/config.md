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

# Plattform und Konfiguration anzeigen
odoodev config show
```

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

# Show platform and configuration
odoodev config show
```

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
