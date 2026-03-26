# odoodev — Unified Odoo Development CLI

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

[![Version](https://img.shields.io/badge/version-0.4.42-blue.svg)]()
[![Python](https://img.shields.io/badge/python-≥3.12-yellow.svg)]()
[![License](https://img.shields.io/badge/license-AGPL--3.0-green.svg)]()

---

## Deutsche Dokumentation

### Projektübersicht

**odoodev** ist ein einheitliches CLI-Tool für die Verwaltung nativer Odoo-Entwicklungsumgebungen über mehrere Versionen hinweg (v16–v19). Es ersetzt eine Vielzahl manueller Skripte, Shell-Funktionen und Konfigurationsdateien durch ein konsistentes Werkzeug mit vollständigem Lifecycle-Management.

**Hauptfunktionen:**
- Multi-Version Support (v16, v17, v18, v19)
- Automatische Versionserkennung aus dem aktuellen Verzeichnis
- Interaktiver Setup-Wizard für die Ersteinrichtung
- Native Entwicklung mit UV Virtual Environments
- Repository-Management mit frei benennbaren Sections in repos.yaml
- Datenbank-Backup & -Wiederherstellung (ZIP, 7z, tar, SQL)
- Docker-Service-Verwaltung (PostgreSQL, Mailpit)
- Shell-Integration mit Tab-Completions (Fish, Bash, Zsh)
- YAML-Playbook-Automation für wiederkehrende Workflows
- Odoo-Konfigurationsgenerierung mit Template-System
- TUI-Modus mit Log-Viewer, Level-Filter und Traceback-Kopie
- Port-Konflikterkennung mit automatischer Prozessbereinigung
- Interaktiver Addon-Selektor für repos/pull (`--select`)
- Sprachladen und Übersetzungs-Overwrite (`--load-language`, `--i18n-overwrite`)
- Session-Bereinigung vor Odoo-Start (`--clean-sessions`)
- Debian 13 / Python 3.12+ Kompatibilität (setuptools, Build-Dependencies)

### Schnellstart

```bash
# 1. Installieren
uv tool install odoodev-equitania

# 2. Setup-Wizard (einmalig)
odoodev setup

# 3. Umgebung initialisieren
odoodev init 18

# 4. Shell-Integration installieren (Tab-Completions!)
odoodev shell-setup

# 5. Odoo starten
odoodev start 18 --dev
```

> Detaillierte Installationsanleitung: [usage/setup.md](usage/setup.md)

### Befehle im Überblick

| Befehl | Beschreibung | Details |
|--------|--------------|---------|
| `odoodev setup` | Interaktiver Setup-Wizard | [setup.md](usage/setup.md) |
| `odoodev init [VERSION]` | Neue Entwicklungsumgebung initialisieren | [setup.md](usage/setup.md) |
| `odoodev start [VERSION]` | Odoo-Server starten | [start.md](usage/start.md) |
| `odoodev stop [VERSION]` | Odoo-Server und Docker stoppen | [start.md](usage/start.md) |
| `odoodev repos [VERSION]` | Repositories klonen/aktualisieren | [repos.md](usage/repos.md) |
| `odoodev pull [VERSION]` | Schneller `git pull` aller Repos | [repos.md](usage/repos.md) |
| `odoodev db [SUB] [VERSION]` | Datenbankoperationen (backup, restore, list, drop) | [db.md](usage/db.md) |
| `odoodev env [SUB] [VERSION]` | .env-Dateiverwaltung (setup, check, show, dir) | [setup.md](usage/setup.md) |
| `odoodev venv [SUB] [VERSION]` | Virtual Environment verwalten | [venv.md](usage/venv.md) |
| `odoodev docker [SUB] [VERSION]` | Docker-Services steuern | [docker.md](usage/docker.md) |
| `odoodev config [SUB]` | Konfiguration und Versionen | [config.md](usage/config.md) |
| `odoodev run [PLAYBOOK]` | YAML-Playbook oder Inline-Steps | [run.md](usage/run.md) |
| `odoodev shell-setup` | Shell-Completions und Wrapper installieren | [shell.md](usage/shell.md) |

### Unterstützte Versionen

| Version | Python | PostgreSQL | DB Port | Odoo Port | Gevent | Mailpit |
|---------|--------|------------|---------|-----------|--------|---------|
| v16 | 3.12 | 16.11 | 16432 | 16069 | 16072 | 16025 |
| v17 | 3.12 | 16.11 | 17432 | 17069 | 17072 | 17025 |
| v18 | 3.13 | 16.11 | 18432 | 18069 | 18072 | 18025 |
| v19 | 3.13 | 17.4 | 19432 | 19069 | 19072 | 19025 |

Port-Schema: `{version}{service}` — z.B. v18: DB=18432, Odoo=18069

### Verzeichnisstruktur

```
~/.config/odoodev/
├── config.yaml                      # [GENERATED] odoodev setup
└── versions-override.yaml           # [MANUELL] Optionale Overrides

~/gitbase/vXX/                       # (oder eigener base_dir)
├── vXX-server/                      # [REPOS] Odoo-Server
│   └── odoo-bin
├── vXX-dev/
│   ├── devXX_native/                # [INIT] Arbeitsverzeichnis
│   │   ├── .env                     # [GENERATED]
│   │   ├── docker-compose.yml       # [GENERATED]
│   │   ├── .venv/                   # [GENERATED]
│   │   └── requirements.txt         # [MANUELL]
│   ├── conf/odooXX_template.conf    # [MANUELL]
│   └── scripts/repos.yaml           # [MANUELL]
├── myconfs/odoo_YYMMDD.conf         # [GENERATED]
└── vXX-addons/, vXX-oca/, ...       # [REPOS]
```

**Legende:** `[GENERATED]` = von odoodev erzeugt | `[REPOS]` = per git clone | `[MANUELL]` = vom Benutzer

### Datenfluss

```
odoodev setup → config.yaml (Basispfad, DB-Credentials)
                    ↓
odoodev init  → Verzeichnisse + .env + docker-compose.yml + .venv + repos
                    ↓
odoodev repos → repos.yaml → git clone → odoo_YYMMDD.conf
                    ↓
odoodev start → .env laden → Voraussetzungen prüfen → odoo-bin starten
```

### Architektur

```
odoodev/
├── cli.py                  # CLI-Einstiegspunkt (Click)
├── output.py               # Rich-Konsolenausgabe
├── commands/               # Click-Commands (init, start, stop, repos, db, ...)
├── core/                   # Kernmodule (version_registry, database, git_ops, ...)
├── tui/                   # TUI-Modus (Textual — Log-Viewer, Status, Module-Update)
├── templates/              # Jinja2-Templates (docker-compose, .env, odoo.conf)
└── data/
    ├── versions.yaml       # Versionsregistry
    └── examples/           # Beispiel-Playbooks und Requirements-Templates
```

### Obsolete Komponenten

odoodev ersetzt:

| Alt | Neu |
|-----|-----|
| `start-native.sh` | `odoodev start` |
| `.env.template` | `odoodev env setup` |
| `docker-compose.yml` (manuell) | `odoodev init` |
| Fish-Funktionen (`odoo-env`, `odoo-start`) | `odoodev` CLI |
| Fish-Aliase (`dev16`, `dev18`) | `odoodev-activate` / `oda` |
| Manuelle `git clone` | `odoodev repos` |
| `docker-compose-arm64.yml` | `odoodev init` (Plattform-Detection) |

### Entwicklung

```bash
uv venv && source .venv/bin/activate.fish
uv pip install -e ".[dev]"
pytest                                  # Tests (390+)
ruff check . && ruff format --check .   # Linting
mypy odoodev                            # Type-Check
uv build                                # Paket bauen
```

### Lizenz

[AGPL-3.0-or-later](LICENSE) — Equitania Software GmbH

### Kontakt

- **Website:** https://www.equitania.de
- **E-Mail:** info@equitania.de

---

## English Documentation

### Project Overview

**odoodev** is a unified CLI tool for native Odoo development environment management across versions (v16–v19). It replaces a variety of manual scripts, shell functions, and configuration files with a consistent tool providing complete lifecycle management.

**Key Features:**
- Multi-version support (v16, v17, v18, v19)
- Automatic version detection from current directory
- Interactive setup wizard for first-time configuration
- Native development with UV virtual environments
- Repository management with freely nameable sections in repos.yaml
- Database backup & restoration (ZIP, 7z, tar, SQL)
- Docker service management (PostgreSQL, Mailpit)
- Shell integration with tab completions (Fish, Bash, Zsh)
- YAML playbook automation for recurring workflows
- Odoo configuration generation with template system
- TUI mode with log viewer, level filtering and traceback copy
- Port conflict detection with automatic process cleanup
- Interactive addon selector for repos/pull (`--select`)
- Language loading and translation overwrite (`--load-language`, `--i18n-overwrite`)
- Session cleanup before Odoo start (`--clean-sessions`)
- Debian 13 / Python 3.12+ compatibility (setuptools, build dependencies)

### Quick Start

```bash
# 1. Install
uv tool install odoodev-equitania

# 2. Setup wizard (one-time)
odoodev setup

# 3. Initialize environment
odoodev init 18

# 4. Install shell integration (tab completions!)
odoodev shell-setup

# 5. Start Odoo
odoodev start 18 --dev
```

> Detailed installation guide: [usage/setup.md](usage/setup.md)

### Command Reference

| Command | Description | Details |
|---------|-------------|---------|
| `odoodev setup` | Interactive setup wizard | [setup.md](usage/setup.md) |
| `odoodev init [VERSION]` | Initialize new development environment | [setup.md](usage/setup.md) |
| `odoodev start [VERSION]` | Start Odoo server | [start.md](usage/start.md) |
| `odoodev stop [VERSION]` | Stop Odoo server and Docker | [start.md](usage/start.md) |
| `odoodev repos [VERSION]` | Clone/update repositories | [repos.md](usage/repos.md) |
| `odoodev pull [VERSION]` | Quick `git pull` across all repos | [repos.md](usage/repos.md) |
| `odoodev db [SUB] [VERSION]` | Database operations (backup, restore, list, drop) | [db.md](usage/db.md) |
| `odoodev env [SUB] [VERSION]` | .env file management (setup, check, show, dir) | [setup.md](usage/setup.md) |
| `odoodev venv [SUB] [VERSION]` | Virtual environment management | [venv.md](usage/venv.md) |
| `odoodev docker [SUB] [VERSION]` | Docker service control | [docker.md](usage/docker.md) |
| `odoodev config [SUB]` | Configuration and versions | [config.md](usage/config.md) |
| `odoodev run [PLAYBOOK]` | YAML playbook or inline steps | [run.md](usage/run.md) |
| `odoodev shell-setup` | Install shell completions and wrappers | [shell.md](usage/shell.md) |

### Supported Versions

| Version | Python | PostgreSQL | DB Port | Odoo Port | Gevent | Mailpit |
|---------|--------|------------|---------|-----------|--------|---------|
| v16 | 3.12 | 16.11 | 16432 | 16069 | 16072 | 16025 |
| v17 | 3.12 | 16.11 | 17432 | 17069 | 17072 | 17025 |
| v18 | 3.13 | 16.11 | 18432 | 18069 | 18072 | 18025 |
| v19 | 3.13 | 17.4 | 19432 | 19069 | 19072 | 19025 |

Port schema: `{version}{service}` — e.g. v18: DB=18432, Odoo=18069

### Directory Structure

```
~/.config/odoodev/
├── config.yaml                      # [GENERATED] odoodev setup
└── versions-override.yaml           # [MANUAL] Optional overrides

~/gitbase/vXX/                       # (or custom base_dir)
├── vXX-server/                      # [REPOS] Odoo server
│   └── odoo-bin
├── vXX-dev/
│   ├── devXX_native/                # [INIT] Working directory
│   │   ├── .env                     # [GENERATED]
│   │   ├── docker-compose.yml       # [GENERATED]
│   │   ├── .venv/                   # [GENERATED]
│   │   └── requirements.txt         # [MANUAL]
│   ├── conf/odooXX_template.conf    # [MANUAL]
│   └── scripts/repos.yaml           # [MANUAL]
├── myconfs/odoo_YYMMDD.conf         # [GENERATED]
└── vXX-addons/, vXX-oca/, ...       # [REPOS]
```

**Legend:** `[GENERATED]` = created by odoodev | `[REPOS]` = via git clone | `[MANUAL]` = user-provided

### Data Flow

```
odoodev setup → config.yaml (base path, DB credentials)
                    ↓
odoodev init  → directories + .env + docker-compose.yml + .venv + repos
                    ↓
odoodev repos → repos.yaml → git clone → odoo_YYMMDD.conf
                    ↓
odoodev start → load .env → check prerequisites → start odoo-bin
```

### Architecture

```
odoodev/
├── cli.py                  # CLI entry point (Click)
├── output.py               # Rich console output
├── commands/               # Click commands (init, start, stop, repos, db, ...)
├── core/                   # Core modules (version_registry, database, git_ops, ...)
├── tui/                   # TUI mode (Textual — log viewer, status, module update)
├── templates/              # Jinja2 templates (docker-compose, .env, odoo.conf)
└── data/
    ├── versions.yaml       # Version registry
    └── examples/           # Example playbooks and requirements templates
```

### Obsolete Components

odoodev replaces:

| Old | New |
|-----|-----|
| `start-native.sh` | `odoodev start` |
| `.env.template` | `odoodev env setup` |
| `docker-compose.yml` (manual) | `odoodev init` |
| Fish functions (`odoo-env`, `odoo-start`) | `odoodev` CLI |
| Fish aliases (`dev16`, `dev18`) | `odoodev-activate` / `oda` |
| Manual `git clone` | `odoodev repos` |
| `docker-compose-arm64.yml` | `odoodev init` (platform detection) |

### Development

```bash
uv venv && source .venv/bin/activate.fish
uv pip install -e ".[dev]"
pytest                                  # Tests (390+)
ruff check . && ruff format --check .   # Linting
mypy odoodev                            # Type checking
uv build                                # Build package
```

### License

[AGPL-3.0-or-later](LICENSE) — Equitania Software GmbH

### Contact

- **Website:** https://www.equitania.de
- **Email:** info@equitania.de
