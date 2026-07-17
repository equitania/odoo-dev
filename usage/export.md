# Modul-Export (Releasemanager CSV)

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

### Ueberblick

`odoodev export modules` exportiert die Modulliste einer **laufenden**
Odoo-Instanz als Releasemanager-kompatible CSV (`.id,name,installed_version,display_name`).
Der Befehl teilt sich seinen Kern (`core/xmlrpc_client.py` + `core/module_export.py`)
mit dem TUI-Export (`x`-Taste) — Ergebnisse sind identisch, und GUIs koennen den
Befehl direkt aufrufen statt die RPC-Logik nachzubauen.

### Verwendung

```bash
# Interaktiv: Datenbank-Auswahl, Standard-Scope "all"
odoodev export modules 18

# Explizite Datenbank und Scope
odoodev export modules 18 -d v18_exam --scope installed

# Ohne Enterprise-Module, mit Katalog-Pflege vor dem Export
odoodev export modules 18 -d v18_exam --scope no-enterprise --cleanup --update-list

# Eigener Zielpfad (Default: ~/Downloads/modules_<db>_<scope>_<timestamp>.csv)
odoodev export modules 18 -d v18_exam --output /tmp/module_liste.csv

# Maschinenlesbar fuer GUIs/Agenten (impliziert --yes)
odoodev export modules 18 -d v18_exam --json
```

### Scopes

| Scope | Bedeutung |
|-------|-----------|
| `all` | Alle verfuegbaren Module (Default) |
| `no-enterprise` | Alle Module ohne Enterprise |
| `installed` | Nur installierte Module |

`test_*`- und `*hw_*`-Module werden immer herausgefiltert; `theme_*` bleibt erhalten.

### Zugangsdaten

Der Export authentifiziert sich per XML-RPC als Odoo-Benutzer (res.users).
Praezedenz der Quellen:

1. CLI-Flags `--user` / `--password`
2. Umgebungsvariablen `ODOODEV_ODOO_USER` / `ODOODEV_ODOO_PASSWORD`
3. Gespeicherte globale Konfiguration: `odoodev config set odoo_login.username` / `odoo_login.password`
4. Fallback `admin`/`admin` (Dev-Konvention)

### Vorbereitende Schritte

- `--cleanup` entfernt nicht-installierte Modul-Datensaetze aus dem Katalog
- `--update-list` aktualisiert die Apps-Liste (`ir.module.module.update_list`)
- Reihenfolge: erst Cleanup, dann Update — der Katalog spiegelt danach das reale System

### JSON-Kontrakt (`--json`)

Einzeiliges JSON-Objekt auf stdout:

```json
{"version": "18", "database": "v18_exam", "scope": "installed",
 "path": "/Users/x/Downloads/modules_v18_exam_installed_20260717_104500.csv",
 "count": 214, "updated": null, "cleaned": null}
```

- `updated`/`cleaned` sind `null`, wenn `--update-list`/`--cleanup` nicht gesetzt waren, sonst Zaehler
- Leere Modulliste ist KEIN Fehler: `count: 0`, `path: null`, Exit-Code 0
- Verbindungs-/Auth-Fehler: Meldung auf stderr, Exit-Code 1

### Voraussetzungen

Die Odoo-Instanz muss laufen (`odoodev start <version>`). Der Port wird aus den
effektiven Ports der Version aufgeloest (`.env`-`ODOO_PORT` gewinnt ueber den
Registry-Default); `--port` uebersteuert.

---

## English Documentation

### Overview

`odoodev export modules` exports the module list of a **running** Odoo instance
as a Releasemanager-compatible CSV (`.id,name,installed_version,display_name`).
The command shares its core (`core/xmlrpc_client.py` + `core/module_export.py`)
with the TUI export (`x` key) — results are identical, and GUIs can shell out to
this command instead of reimplementing the RPC logic.

### Usage

```bash
# Interactive: database picker, default scope "all"
odoodev export modules 18

# Explicit database and scope
odoodev export modules 18 -d v18_exam --scope installed

# Without Enterprise modules, with catalog maintenance before the export
odoodev export modules 18 -d v18_exam --scope no-enterprise --cleanup --update-list

# Custom output path (default: ~/Downloads/modules_<db>_<scope>_<timestamp>.csv)
odoodev export modules 18 -d v18_exam --output /tmp/module_list.csv

# Machine-readable for GUIs/agents (implies --yes)
odoodev export modules 18 -d v18_exam --json
```

### Scopes

| Scope | Meaning |
|-------|---------|
| `all` | All available modules (default) |
| `no-enterprise` | All modules without Enterprise |
| `installed` | Installed modules only |

`test_*` and `*hw_*` modules are always filtered out; `theme_*` is kept.

### Credentials

The export authenticates via XML-RPC as an Odoo user (res.users).
Source precedence:

1. CLI flags `--user` / `--password`
2. Environment variables `ODOODEV_ODOO_USER` / `ODOODEV_ODOO_PASSWORD`
3. Stored global configuration: `odoodev config set odoo_login.username` / `odoo_login.password`
4. Fallback `admin`/`admin` (dev convention)

### Pre-export steps

- `--cleanup` removes non-installed module records from the catalog
- `--update-list` refreshes the apps list (`ir.module.module.update_list`)
- Order: cleanup first, then update — the catalog then reflects the real system

### JSON contract (`--json`)

Single-line JSON object on stdout:

```json
{"version": "18", "database": "v18_exam", "scope": "installed",
 "path": "/Users/x/Downloads/modules_v18_exam_installed_20260717_104500.csv",
 "count": 214, "updated": null, "cleaned": null}
```

- `updated`/`cleaned` are `null` unless `--update-list`/`--cleanup` were passed, counters otherwise
- An empty module list is NOT an error: `count: 0`, `path: null`, exit code 0
- Connection/auth errors: message on stderr, exit code 1

### Prerequisites

The Odoo instance must be running (`odoodev start <version>`). The port is
resolved from the version's effective ports (`.env` `ODOO_PORT` wins over the
registry default); `--port` overrides.
