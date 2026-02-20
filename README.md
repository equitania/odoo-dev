# odoodev — Unified Odoo Development CLI

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)]()
[![Python](https://img.shields.io/badge/python-≥3.10-yellow.svg)]()
[![License](https://img.shields.io/badge/license-AGPL--3.0-green.svg)]()

---

## Deutsche Dokumentation

### Projektübersicht

**odoodev** ist ein einheitliches CLI-Tool für die Verwaltung nativer Odoo-Entwicklungsumgebungen über mehrere Versionen hinweg (v16–v19). Es bietet vollständiges Lifecycle-Management für Odoo-Entwicklung, einschließlich Umgebungseinrichtung, Repository-Verwaltung, Datenbankoperationen und Docker-Service-Orchestrierung.

**Hauptfunktionen:**
- Multi-Version Support (v16, v17, v18, v19)
- Automatische Versionserkennung aus dem aktuellen Verzeichnis
- Native Entwicklung mit UV Virtual Environments
- Repository-Management (Odoo, OCA, Enterprise, Custom)
- Datenbank-Backup-Wiederherstellung (ZIP, 7z, tar, SQL)
- Docker-Service-Verwaltung (PostgreSQL, Mailpit)
- Shell-Integration (Fish, Bash, Zsh)
- Odoo-Konfigurationsgenerierung mit Template-System

### Voraussetzungen

- Python ≥ 3.10
- [UV](https://docs.astral.sh/uv/) Package Manager
- Docker & Docker Compose V2
- Git mit SSH-Zugang

### Installation

```bash
# Repository klonen
git clone https://gitlab.ownerp.io/pypi-projects/odoo-dev.git
cd odoo-dev

# Virtual Environment erstellen und aktivieren
uv venv && source .venv/bin/activate.fish  # Fish
# oder: source .venv/bin/activate           # Bash/Zsh

# Paket installieren (mit Entwicklungsabhängigkeiten)
uv pip install -e ".[dev]"
```

### Verwendung

#### Schnellstart

```bash
# Verfügbare Versionen anzeigen
odoodev config versions

# Neue Odoo 18 Umgebung initialisieren
odoodev init 18

# Odoo im Entwicklungsmodus starten
odoodev start 18 --dev

# Shell-Integration installieren
odoodev shell-setup
```

#### Befehle im Überblick

| Befehl | Beschreibung |
|--------|--------------|
| `odoodev init [VERSION]` | Neue Entwicklungsumgebung initialisieren |
| `odoodev start [VERSION]` | Odoo-Server starten |
| `odoodev repos [VERSION]` | Repositories klonen/aktualisieren |
| `odoodev db [SUBCOMMAND] [VERSION]` | Datenbankoperationen |
| `odoodev env [SUBCOMMAND] [VERSION]` | .env-Dateiverwaltung |
| `odoodev venv [SUBCOMMAND] [VERSION]` | Virtual Environment verwalten |
| `odoodev docker [SUBCOMMAND] [VERSION]` | Docker-Services steuern |
| `odoodev config [SUBCOMMAND]` | Konfiguration und Versionen |
| `odoodev shell-setup` | Shell-Wrapper installieren |

#### Umgebung initialisieren

```bash
# Interaktiv (mit Bestätigungsdialogen)
odoodev init 18

# Nicht-interaktiv (mit Standardwerten)
odoodev init 18 --non-interactive

# Ohne Repository-Klonen
odoodev init 18 --skip-repos

# Ohne Docker-Services
odoodev init 18 --skip-docker
```

#### Server starten

```bash
# Entwicklungsmodus (Hot-Reload)
odoodev start 18 --dev

# Interaktive Shell
odoodev start 18 --shell

# Tests ausführen
odoodev start 18 --test

# Venv aktivieren ohne Server zu starten
odoodev start 18 --prepare

# Zusätzliche Odoo-Argumente übergeben
odoodev start 18 -- -d mydb -u my_module
```

#### Repository-Verwaltung

```bash
# Alle Repositories klonen/aktualisieren
odoodev repos 18

# Nur Odoo-Server verarbeiten
odoodev repos 18 --server-only

# Nur Odoo-Konfiguration generieren
odoodev repos 18 --config-only

# Custom repos.yaml verwenden
odoodev repos 18 -c /pfad/zu/repos.yaml
```

#### Datenbankoperationen

```bash
# Datenbanken auflisten
odoodev db list 18

# Backup wiederherstellen
odoodev db restore 18 -n v18_test -z backup.zip

# Datenbank löschen
odoodev db drop 18 -n v18_test
```

#### Docker-Services

```bash
# Services starten
odoodev docker up 18

# Services stoppen
odoodev docker down 18

# Status anzeigen
odoodev docker status 18

# Logs anzeigen
odoodev docker logs 18 -f
```

### Unterstützte Versionen

| Version | Python | PostgreSQL | DB Port | Odoo Port |
|---------|--------|------------|---------|-----------|
| v16 | 3.12 | 16.11 | 16432 | 16069 |
| v17 | 3.12 | 16.11 | 17432 | 17069 |
| v18 | 3.12 | 16.11 | 18432 | 18069 |
| v19 | 3.13 | 17.4 | 19432 | 19069 |

### Architektur

```
odoodev/
├── cli.py                  # CLI-Einstiegspunkt (Click)
├── output.py               # Rich-Konsolenausgabe
├── commands/
│   ├── init_cmd.py         # Umgebungsinitialisierung
│   ├── start.py            # Server-Start
│   ├── repos.py            # Repository-Verwaltung
│   ├── db.py               # Datenbankoperationen
│   ├── env.py              # .env-Verwaltung
│   ├── venv.py             # Virtual Environment
│   ├── docker.py           # Docker-Services
│   ├── config.py           # Konfiguration
│   └── shell_setup.py      # Shell-Integration
├── core/
│   ├── version_registry.py # Versionsmanagement
│   ├── environment.py      # Plattformerkennung
│   ├── git_ops.py          # Git-Operationen
│   ├── database.py         # PostgreSQL-Operationen
│   ├── odoo_config.py      # Konfigurationsgenerierung
│   ├── venv_manager.py     # UV-Venv-Verwaltung
│   ├── docker_compose.py   # Docker-Compose-Operationen
│   ├── prerequisites.py    # Voraussetzungsprüfungen
│   └── shell_integration.py# Shell-Aktivierung
├── templates/              # Jinja2-Templates
│   ├── docker-compose.yml.j2
│   ├── env.template.j2
│   ├── odoo_template.conf.j2
│   └── shell/              # Shell-Aktivierungsskripte
└── data/
    └── versions.yaml       # Versionsregistry
```

### Entwicklung

```bash
# Entwicklungsumgebung einrichten
uv venv && source .venv/bin/activate.fish
uv pip install -e ".[dev]"

# Tests ausführen
pytest

# Linting
ruff check . && ruff format --check .

# Formatierung anwenden
ruff check --fix . && ruff format .

# Typ-Prüfung
mypy odoodev

# Paket bauen
uv build
```

### Lizenz

Dieses Projekt ist unter der [AGPL-3.0-or-later](LICENSE) Lizenz lizenziert.

### Kontakt

- **Firma:** Equitania Software GmbH
- **E-Mail:** info@equitania.de
- **Website:** https://www.equitania.de

---

## English Documentation

### Project Overview

**odoodev** is a unified CLI tool for native Odoo development environment management across versions (v16–v19). It provides complete lifecycle management for Odoo development, including environment setup, repository management, database operations, and Docker service orchestration.

**Key Features:**
- Multi-version support (v16, v17, v18, v19)
- Automatic version detection from current directory
- Native development with UV virtual environments
- Repository management (Odoo, OCA, Enterprise, Custom)
- Database backup restoration (ZIP, 7z, tar, SQL)
- Docker service management (PostgreSQL, Mailpit)
- Shell integration (Fish, Bash, Zsh)
- Odoo configuration generation with template system

### Prerequisites

- Python ≥ 3.10
- [UV](https://docs.astral.sh/uv/) package manager
- Docker & Docker Compose V2
- Git with SSH access

### Installation

```bash
# Clone repository
git clone https://gitlab.ownerp.io/pypi-projects/odoo-dev.git
cd odoo-dev

# Create and activate virtual environment
uv venv && source .venv/bin/activate.fish  # Fish
# or: source .venv/bin/activate             # Bash/Zsh

# Install package (with development dependencies)
uv pip install -e ".[dev]"
```

### Usage

#### Quick Start

```bash
# List available versions
odoodev config versions

# Initialize new Odoo 18 environment
odoodev init 18

# Start Odoo in development mode
odoodev start 18 --dev

# Install shell integration
odoodev shell-setup
```

#### Command Reference

| Command | Description |
|---------|-------------|
| `odoodev init [VERSION]` | Initialize new development environment |
| `odoodev start [VERSION]` | Start Odoo server |
| `odoodev repos [VERSION]` | Clone/update repositories |
| `odoodev db [SUBCOMMAND] [VERSION]` | Database operations |
| `odoodev env [SUBCOMMAND] [VERSION]` | .env file management |
| `odoodev venv [SUBCOMMAND] [VERSION]` | Virtual environment management |
| `odoodev docker [SUBCOMMAND] [VERSION]` | Docker service control |
| `odoodev config [SUBCOMMAND]` | Configuration and versions |
| `odoodev shell-setup` | Install shell wrapper functions |

#### Initialize Environment

```bash
# Interactive (with confirmation prompts)
odoodev init 18

# Non-interactive (with defaults)
odoodev init 18 --non-interactive

# Skip repository cloning
odoodev init 18 --skip-repos

# Skip Docker services
odoodev init 18 --skip-docker
```

#### Start Server

```bash
# Development mode (hot-reload)
odoodev start 18 --dev

# Interactive shell
odoodev start 18 --shell

# Run tests
odoodev start 18 --test

# Activate venv without starting server
odoodev start 18 --prepare

# Pass additional Odoo arguments
odoodev start 18 -- -d mydb -u my_module
```

#### Repository Management

```bash
# Clone/update all repositories
odoodev repos 18

# Process only Odoo server
odoodev repos 18 --server-only

# Generate Odoo config only
odoodev repos 18 --config-only

# Use custom repos.yaml
odoodev repos 18 -c /path/to/repos.yaml
```

#### Database Operations

```bash
# List databases
odoodev db list 18

# Restore backup
odoodev db restore 18 -n v18_test -z backup.zip

# Drop database
odoodev db drop 18 -n v18_test
```

#### Docker Services

```bash
# Start services
odoodev docker up 18

# Stop services
odoodev docker down 18

# Show status
odoodev docker status 18

# View logs
odoodev docker logs 18 -f
```

### Supported Versions

| Version | Python | PostgreSQL | DB Port | Odoo Port |
|---------|--------|------------|---------|-----------|
| v16 | 3.12 | 16.11 | 16432 | 16069 |
| v17 | 3.12 | 16.11 | 17432 | 17069 |
| v18 | 3.12 | 16.11 | 18432 | 18069 |
| v19 | 3.13 | 17.4 | 19432 | 19069 |

### Architecture

```
odoodev/
├── cli.py                  # CLI entry point (Click)
├── output.py               # Rich console output
├── commands/
│   ├── init_cmd.py         # Environment initialization
│   ├── start.py            # Server startup
│   ├── repos.py            # Repository management
│   ├── db.py               # Database operations
│   ├── env.py              # .env management
│   ├── venv.py             # Virtual environment
│   ├── docker.py           # Docker services
│   ├── config.py           # Configuration
│   └── shell_setup.py      # Shell integration
├── core/
│   ├── version_registry.py # Version management
│   ├── environment.py      # Platform detection
│   ├── git_ops.py          # Git operations
│   ├── database.py         # PostgreSQL operations
│   ├── odoo_config.py      # Config generation
│   ├── venv_manager.py     # UV venv management
│   ├── docker_compose.py   # Docker Compose operations
│   ├── prerequisites.py    # Prerequisite checks
│   └── shell_integration.py# Shell activation
├── templates/              # Jinja2 templates
│   ├── docker-compose.yml.j2
│   ├── env.template.j2
│   ├── odoo_template.conf.j2
│   └── shell/              # Shell activation scripts
└── data/
    └── versions.yaml       # Version registry
```

### Development

```bash
# Set up development environment
uv venv && source .venv/bin/activate.fish
uv pip install -e ".[dev]"

# Run tests
pytest

# Linting
ruff check . && ruff format --check .

# Apply formatting
ruff check --fix . && ruff format .

# Type checking
mypy odoodev

# Build package
uv build
```

### License

This project is licensed under [AGPL-3.0-or-later](LICENSE).

### Contact

- **Company:** Equitania Software GmbH
- **Email:** info@equitania.de
- **Website:** https://www.equitania.de
