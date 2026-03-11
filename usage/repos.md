# Repository Management

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

### Repository-Verwaltung

```bash
# Alle Repositories klonen/aktualisieren + Konfiguration generieren
odoodev repos 18

# Nur Odoo-Server verarbeiten
odoodev repos 18 --server-only

# Nur Odoo-Konfiguration generieren (kein git clone/pull)
odoodev repos 18 --config-only

# Custom repos.yaml verwenden
odoodev repos 18 -c /pfad/zu/repos.yaml
```

### Schneller Pull aller Repos

```bash
# Alle vorhandenen Repos aktualisieren (kein Clone, kein Access-Check)
odoodev pull 18

# Mit Custom repos.yaml
odoodev pull 18 -c /pfad/zu/repos.yaml

# Verbose-Modus (Debug-Logs pro Repository)
odoodev pull 18 --verbose
```

Der `pull`-Befehl zeigt bei fehlgeschlagenen Repos detaillierte Fehlermeldungen (z.B. Branch nicht gefunden, Merge-Konflikte).

### repos.yaml Format

Die Datei `repos.yaml` steuert, welche Repositories geklont und wie sie in der Odoo-Konfiguration organisiert werden. Erwartet unter `vXX-dev/scripts/repos.yaml`:

```yaml
version: "18"
branch: "develop"
ssh_key: "~/.ssh/id_rsa"

paths:
  base: ~/gitbase/v18
  template: ~/gitbase/v18/v18-dev/conf/odoo18_template.conf
  config_dir: ~/gitbase/v18/myconfs

base_addons:
  - $HOME/gitbase/v18/v18-server/odoo/addons
  - $HOME/gitbase/v18/v18-server/addons

addons:
  - key: eq_module
    path: v18-addons
    git_url: git@gitlab.ownerp.io:v18/v18-addons.git
    section: Equitania
    use: true
    suffix: ""

customers:
  - key: v18-customer
    path: v18-customer
    git_url: git@gitlab.ownerp.io:customer/v18-customer.git
    section: Customer
    use: false
```

### Felder-Referenz

| Feld | Pflicht | Beschreibung |
|------|---------|--------------|
| `version` | Ja | Odoo-Version (z.B. "18") |
| `branch` | Ja | Git-Branch fuer alle Repositories |
| `ssh_key` | Nein | Pfad zum SSH-Key (Standard: System-Default) |
| `paths.base` | Ja | Basis-Verzeichnis der Odoo-Version |
| `paths.template` | Ja | Pfad zum odoo_template.conf |
| `paths.config_dir` | Ja | Zielverzeichnis fuer generierte Configs |
| `base_addons` | Ja | Odoo Core- und Standard-Addon-Pfade |
| `addons[].key` | Ja | Eindeutiger Identifier fuer das Repository |
| `addons[].path` | Ja | Zielverzeichnis (relativ zu paths.base) |
| `addons[].git_url` | Ja | Git-Repository-URL |
| `addons[].section` | Nein | Gruppierung in odoo.conf (Standard: "Other") |
| `addons[].use` | Nein | `true` = aktiv, `false` = als Kommentar in odoo.conf (Standard: `true`) |
| `addons[].suffix` | Nein | Unterverzeichnis-Suffix fuer addons_path |

### Sektionen im addons_path

Reihenfolge in generierter odoo.conf:

1. Odoo (Core)
2. OCA
3. Enterprise
4. Syscoon
5. 3rd-party
6. Equitania
7. Customer
8. Other

**Repository-Abschnitte in repos.yaml:** `addons`, `additional`, `special`, `customers` — alle werden identisch verarbeitet.

### Fehlende repos.yaml

Wenn keine `repos.yaml` gefunden wird, kopiert odoodev ein Beispiel-Template und zeigt eine Anleitung zur Konfiguration.

---

## English Documentation

### Repository Management

```bash
# Clone/update all repositories + generate configuration
odoodev repos 18

# Process only Odoo server
odoodev repos 18 --server-only

# Generate Odoo config only (no git clone/pull)
odoodev repos 18 --config-only

# Use custom repos.yaml
odoodev repos 18 -c /path/to/repos.yaml
```

### Quick Pull All Repos

```bash
# Update all existing repos (no clone, no access check)
odoodev pull 18

# With custom repos.yaml
odoodev pull 18 -c /path/to/repos.yaml

# Verbose mode (debug logs per repository)
odoodev pull 18 --verbose
```

The `pull` command shows detailed error messages for failed repos (e.g. branch not found, merge conflicts).

### repos.yaml Format

The file `repos.yaml` controls which repositories are cloned and how they are organized in the Odoo configuration. Expected at `vXX-dev/scripts/repos.yaml`:

```yaml
version: "18"
branch: "develop"
ssh_key: "~/.ssh/id_rsa"

paths:
  base: ~/gitbase/v18
  template: ~/gitbase/v18/v18-dev/conf/odoo18_template.conf
  config_dir: ~/gitbase/v18/myconfs

base_addons:
  - $HOME/gitbase/v18/v18-server/odoo/addons
  - $HOME/gitbase/v18/v18-server/addons

addons:
  - key: eq_module
    path: v18-addons
    git_url: git@gitlab.ownerp.io:v18/v18-addons.git
    section: Equitania
    use: true
    suffix: ""

customers:
  - key: v18-customer
    path: v18-customer
    git_url: git@gitlab.ownerp.io:customer/v18-customer.git
    section: Customer
    use: false
```

### Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| `version` | Yes | Odoo version (e.g. "18") |
| `branch` | Yes | Git branch for all repositories |
| `ssh_key` | No | Path to SSH key (default: system default) |
| `paths.base` | Yes | Base directory of the Odoo version |
| `paths.template` | Yes | Path to odoo_template.conf |
| `paths.config_dir` | Yes | Target directory for generated configs |
| `base_addons` | Yes | Odoo core and standard addon paths |
| `addons[].key` | Yes | Unique identifier for the repository |
| `addons[].path` | Yes | Target directory (relative to paths.base) |
| `addons[].git_url` | Yes | Git repository URL |
| `addons[].section` | No | Grouping in odoo.conf (default: "Other") |
| `addons[].use` | No | `true` = active, `false` = as comment in odoo.conf (default: `true`) |
| `addons[].suffix` | No | Subdirectory suffix for addons_path |

### Sections in addons_path

Order in generated odoo.conf:

1. Odoo (Core)
2. OCA
3. Enterprise
4. Syscoon
5. 3rd-party
6. Equitania
7. Customer
8. Other

**Repository sections in repos.yaml:** `addons`, `additional`, `special`, `customers` — all processed identically.

### Missing repos.yaml

If no `repos.yaml` is found, odoodev copies an example template and shows guidance for configuration.
