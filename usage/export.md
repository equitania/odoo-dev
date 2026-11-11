# Modul-Export (Releasemanager CSV)

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

### Ueberblick

`odoodev export modules` exportiert die Modulliste einer
Odoo-Instanz als Releasemanager-kompatible CSV (`.id,name,installed_version,display_name`).
Standardweg ist seit 0.77.0 `odoo-bin shell` als Superuser: kein Odoo-Login noetig, der
Server muss nicht laufen. Der Befehl teilt sich seinen Kern (`core/module_export.py`)
mit dem TUI-Export (`x`-Taste) — Ergebnisse sind identisch, und GUIs koennen den
Befehl direkt aufrufen statt die Logik nachzubauen.

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

# Shell erzwingen (kein Fallback auf XML-RPC)
odoodev export modules 19 -d v19_demo --via-shell

# XML-RPC gegen einen LAUFENDEN Odoo (Odoo-Login noetig)
odoodev export modules 18 -d v18_exam --via-rpc --user admin
```

### Scopes

| Scope | Bedeutung |
|-------|-----------|
| `all` | Alle verfuegbaren Module (Default) |
| `no-enterprise` | Alle Module ohne Enterprise |
| `installed` | Nur installierte Module |

`test_*`- und `*hw_*`-Module werden immer herausgefiltert; `theme_*` bleibt erhalten.

### Weg des Exports: Shell (Standard) oder XML-RPC

**Standard: `odoo-bin shell`.** Der Export liest die Module als Superuser ueber
`odoo-bin shell` — kein Odoo-Login, keine Zugangsdaten, der Server muss nicht laufen
(darf aber; die Shell startet mit `--no-http`). Voraussetzung: venv, `odoo-bin` und
eine generierte `odoo_*.conf` der Version. `--cleanup`/`--update-list` und `--json`
verhalten sich auf beiden Wegen gleich.

**XML-RPC** gegen einen laufenden Odoo wird nur genutzt, wenn du es verlangst:
mit `--via-rpc` oder implizit durch eines von `--user`, `--password`, `--host`,
`--port` — sowie automatisch (mit Hinweis), wenn der Rechner fuer die Version keine
odoo-bin-Umgebung hat. `--via-shell` erzwingt die Shell und faellt nie zurueck;
`--via-shell` zusammen mit `--via-rpc` ist ein Aufruffehler. `--host` hat keinen
angezeigten Default (bei XML-RPC gilt `localhost`).

Zugangsdaten gelten **nur fuer den XML-RPC-Weg** (Odoo-Benutzer, res.users).
Praezedenz der Quellen:

1. CLI-Flags `--user` / `--password`
2. Umgebungsvariablen `ODOODEV_ODOO_USER` / `ODOODEV_ODOO_PASSWORD`
3. Gespeicherte globale Konfiguration: `odoodev config set odoo_login.username` / `odoo_login.password`
4. Fallback `admin`/`admin` (Dev-Konvention)

Im TUI-Exportdialog (`x`) gibt es keinen Login: er fragt nur Datenbank, Umfang
(alle / alle ohne Enterprise / nur installierte) und die beiden Optionen „Apps-Liste
vor dem Export aktualisieren“ und „Nicht installierte Module vor dem Export entfernen“
ab und laeuft immer ueber `odoo-bin shell`.

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
- Fehler (Verbindung/Auth bei XML-RPC, Shell-Fehler): Meldung auf stderr, Exit-Code 1

### Voraussetzungen

Shell-Weg (Standard): venv, `odoo-bin` und eine generierte `odoo_*.conf` der Version;
der Server muss nicht laufen. XML-RPC-Weg: die Odoo-Instanz muss laufen
(`odoodev start <version>`); der Port wird aus den effektiven Ports der Version
aufgeloest (`.env`-`ODOO_PORT` gewinnt ueber den Registry-Default); `--port` uebersteuert.

---

## English Documentation

### Overview

`odoodev export modules` exports the module list of an Odoo instance
as a Releasemanager-compatible CSV (`.id,name,installed_version,display_name`).
Since 0.77.0 the default path is `odoo-bin shell` as superuser: no Odoo login needed,
the server need not be running. The command shares its core (`core/module_export.py`)
with the TUI export (`x` key) — results are identical, and GUIs can shell out to
this command instead of reimplementing the logic.

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

# Force the shell (never falls back to XML-RPC)
odoodev export modules 19 -d v19_demo --via-shell

# XML-RPC against a RUNNING Odoo (needs an Odoo login)
odoodev export modules 18 -d v18_exam --via-rpc --user admin
```

### Scopes

| Scope | Meaning |
|-------|---------|
| `all` | All available modules (default) |
| `no-enterprise` | All modules without Enterprise |
| `installed` | Installed modules only |

`test_*` and `*hw_*` modules are always filtered out; `theme_*` is kept.

### Export path: shell (default) or XML-RPC

**Default: `odoo-bin shell`.** The export reads the modules as superuser through
`odoo-bin shell` — no Odoo login, no credentials, the server need not run (but may;
the shell starts with `--no-http`). Requires the version's venv, `odoo-bin` and a
generated `odoo_*.conf`. `--cleanup`/`--update-list` and `--json` behave the same on
both paths.

**XML-RPC** against a running Odoo is used only when you ask for it: with `--via-rpc`,
or implied by any of `--user`, `--password`, `--host`, `--port` — and automatically
(with a notice) when the machine has no odoo-bin environment for the version.
`--via-shell` forces the shell and never falls back; `--via-shell` together with
`--via-rpc` is a usage error. `--host` has no shown default (`localhost` when
XML-RPC is used).

Credentials apply to the **XML-RPC path only** (Odoo user, res.users). Source precedence:

1. CLI flags `--user` / `--password`
2. Environment variables `ODOODEV_ODOO_USER` / `ODOODEV_ODOO_PASSWORD`
3. Stored global configuration: `odoodev config set odoo_login.username` / `odoo_login.password`
4. Fallback `admin`/`admin` (dev convention)

The TUI export dialog (`x`) has no login: it asks only for the database, the scope
(all / all without Enterprise / installed only) and the two options "Update apps list
before export" and "Remove non-installed modules before export", and always runs
through `odoo-bin shell`.

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
- Errors (connection/auth on XML-RPC, shell failures): message on stderr, exit code 1

### Prerequisites

Shell path (default): the version's venv, `odoo-bin` and a generated `odoo_*.conf`;
the server need not run. XML-RPC path: the Odoo instance must be running
(`odoodev start <version>`); the port is resolved from the version's effective ports
(`.env` `ODOO_PORT` wins over the registry default); `--port` overrides.
