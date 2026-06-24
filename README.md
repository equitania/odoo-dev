# odoodev — Unified Odoo Development CLI

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

[![Version](https://img.shields.io/badge/version-0.32.0-blue.svg)]()
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
- Datenbank-Backup & -Wiederherstellung (ZIP, 7z, tar, tar.zst, SQL)
- DSGVO-Anonymisierung beim Restore (standardmäßig aktiv, Faker-basiert, inkl. HR-/Mitarbeiterdaten, `--no-anonymize` zum Abschalten); `res_users` bleibt per Default testbar — optional via `--anonymize-users`
- Native Odoo-Neutralisierung beim Restore (`odoo-bin neutralize`, standardmäßig aktiv) + ergänzende Bank-Sync-Bereinigung + eigenständiger Befehl `db neutralize`
- Docker-Service-Verwaltung (PostgreSQL, Mailpit)
- Shell-Integration mit Tab-Completions (Fish, Bash, Zsh)
- YAML-Playbook-Automation für wiederkehrende Workflows
- Odoo-Konfigurationsgenerierung mit Template-System
- TUI-Modus mit Log-Viewer, Level-Filter, aufklappendem Schnellmenü (`m`) für schmale Monitore, Live-Erkennung der Datenbank aus den Logs und CSV-Modulexport im Releasemanager-Format
- Port-Konflikterkennung mit automatischer Prozessbereinigung
- Interaktiver Addon-Selektor für repos/pull (`--select`)
- Sprachladen und Übersetzungs-Overwrite (`--load-language`, `--i18n-overwrite`)
- Session-Bereinigung vor Odoo-Start (`--clean-sessions`)
- Debian 13 / Python 3.12+ Kompatibilität (setuptools, Build-Dependencies)
- Versionsübergreifender Migrationsmodus (geteilte PostgreSQL-Container und Filestore)
- `odoodev doctor` — alle Umgebungs-Checks auf einen Blick inkl. PyPI-Update-Hinweis
- Datenbank kopieren/umbenennen (`db copy`, `db rename`) inkl. Filestore
- Maschinenlesbare Ausgabe (`--json`) für `db list`, `config versions`, `venv check`
- Playbook-Variablen (`vars:`-Block, `{{ vars.x }}`, `{{ env.X }}`, `{{ date }}`, `--var`-Overrides) und Playbook-Discovery (`run --list`)

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

> **Dokumentation:**
> - **[Wiki: Odoo-Entwicklungs-Workflow](usage/odoo-development-workflow.md)** — End-to-End-Anleitung mit Hello-World-Modul (zweisprachig DE/EN)
> - [Setup & Ersteinrichtung](usage/setup.md) — Setup-Wizard, Init, .env-Verwaltung
> - [Server Start & Stop](usage/start.md) — Start-Modi, Voraussetzungen, TUI
> - [Repositories](usage/repos.md) — Klonen, Pull, Addon-Selektor
> - [Datenbank](usage/db.md) — Backup, Restore, List, Drop
> - [Virtual Environment](usage/venv.md) — UV-basierte venv-Verwaltung
> - [Docker](usage/docker.md) — PostgreSQL & Mailpit Services
> - [Konfiguration](usage/config.md) — Versionen, Plattforminfo, `config set`/`edit`
> - [Doctor](usage/doctor.md) — Umgebungs-Checks und PyPI-Update-Hinweis
> - [Playbooks](usage/run.md) — YAML-Automation und Inline-Steps
> - [Migration](usage/migrate.md) — Versionsuebergreifende DB-Migration
> - [Shell-Integration](usage/shell.md) — Completions, Wrapper, Aliase

### Befehle im Überblick

| Befehl | Beschreibung | Details |
|--------|--------------|---------|
| `odoodev setup` | Interaktiver Setup-Wizard | [setup.md](usage/setup.md) |
| `odoodev init [VERSION]` | Neue Entwicklungsumgebung initialisieren | [setup.md](usage/setup.md) |
| `odoodev start [VERSION]` | Odoo-Server starten | [start.md](usage/start.md) |
| `odoodev stop [VERSION]` | Odoo-Server und Docker stoppen | [start.md](usage/start.md) |
| `odoodev repos [VERSION]` | Repositories klonen/aktualisieren | [repos.md](usage/repos.md) |
| `odoodev pull [VERSION]` | Schneller `git pull` aller Repos | [repos.md](usage/repos.md) |
| `odoodev db [SUB] [VERSION]` | Datenbankoperationen (backup, restore, neutralize, list, drop) | [db.md](usage/db.md) |
| `odoodev env [SUB] [VERSION]` | .env-Dateiverwaltung (setup, check, show, dir) | [setup.md](usage/setup.md) |
| `odoodev venv [SUB] [VERSION]` | Virtual Environment verwalten | [venv.md](usage/venv.md) |
| `odoodev docker [SUB] [VERSION]` | Docker-Services steuern | [docker.md](usage/docker.md) |
| `odoodev doctor [VERSION]` | Umgebungs-Checks + PyPI-Update-Hinweis | [doctor.md](usage/doctor.md) |
| `odoodev config [SUB]` | Konfiguration und Versionen (inkl. `set`/`edit`) | [config.md](usage/config.md) |
| `odoodev run [PLAYBOOK]` | YAML-Playbook oder Inline-Steps (`--list`, `--var`) | [run.md](usage/run.md) |
| `odoodev migrate [SUB]` | Migrationsmodus für versionsübergreifende DB-Migration | [migrate.md](usage/migrate.md) |
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
├── tui/                   # TUI-Modus (Textual — Log-Viewer, Status, Schnellmenü, Modul-Export)
├── templates/              # Jinja2-Templates (docker-compose, .env, odoo.conf)
└── data/
    ├── versions.yaml       # Versionsregistry
    └── examples/           # Beispiel-Playbooks und Requirements-Templates
```

### Entwicklung

```bash
uv venv && source .venv/bin/activate.fish
uv pip install -e ".[dev]"
pytest                                  # Tests (776)
ruff check . && ruff format --check .   # Linting
mypy odoodev                            # Type-Check
uv build                                # Paket bauen
```

### Änderungsprotokoll

Die vollständige Versionshistorie steht in den [Release Notes](RELEASE_NOTES.md).

**Version 0.32.0:**
- **Neu:** `odoodev db restore` prüft vor dem Entpacken den freien Speicherplatz — die entpackte Größe wird geschätzt (ZIP exakt, komprimierte Formate konservativ `Größe × 3`) und gegen den freien Platz auf Extraktions- und Filestore-Dateisystem geprüft. Bei Knappheit: Warnung mit konkreten Zahlen + Rückfrage „Continue anyway?" (Default Nein) statt Abbruch mitten im Kopieren. Abschaltbar mit `--no-check-space`.
- **Neu:** `odoodev db restore` kann das Original-Backup am Ende optional löschen — nach erfolgreichem Restore Rückfrage „Delete original backup file?" (Default Nein, nie automatisch). Neue Flags `--delete-backup` (löschen ohne Frage) und `--keep-backup` (nie fragen/löschen) machen das skriptfähig.
- **Geändert:** Schlankeres Restore-Datenhandling — der Filestore wird jetzt verschoben statt kopiert. Bisher lag der Filestore dreifach auf der Platte (Backup + entpacktes Temp + kopiertes Ziel). Der Zieltransfer nutzt nun `shutil.move` (Rename auf demselben Dateisystem = instant, sonst Fallback copy+delete) und vermeidet die doppelte Datenhaltung. `--keep-temp` kopiert weiterhin (Temp bleibt zum Debuggen erhalten). Der Playbook-Restore wurde angeglichen.

**Version 0.31.4:**
- **Neu:** `odoodev db backup` unterstützt jetzt `.tar.zst`-Stream-Backups (`--type tar.zst`) — erzeugt ein Zstandard-komprimiertes tar (`dump.sql` + `filestore/`) passend zum Backup-Server (`container2backup` v4.7.0+) und zum Restore aus 0.31.2. Symmetrisch implementiert: ein Python-`tarfile`-Stream wird in die `zstd`-CLI gepipet (kein `zstandard`-Package nötig). Ideal für große Datenbanken mit umfangreichem Filestore. Die neue Option `--level/-l` setzt das zstd-Kompressionslevel (1=schnell .. 19/22=kleinste, Standard 5). Die interaktive Auswahl listet `TAR.ZST` neben `SQL` und `ZIP`; fehlt die `zstd`-CLI, bricht der Befehl frühzeitig mit Installationshinweis ab.

**Version 0.31.3:**
- **Behoben:** Der interaktive `Backup file:`-Prompt von `odoodev db restore` wies gültige Pfade mit umschließendem Whitespace ab — ein eingefügtes oder per Autovervollständigung erzeugtes Leerzeichen/Newline führte zu „File not found", obwohl die Datei existierte. Pfad-Eingaben werden jetzt vor der `~`-Expansion gestrippt.

**Version 0.31.2:**
- **Neu:** `odoodev db restore` unterstützt jetzt `.tar.zst`-Stream-Backups — der Backup-Server (`container2backup` v4.7.0+) erzeugt für große Datenbanken ein Zstandard-komprimiertes tar (`dump.sql` + `filestore/`) statt eines gestaffelten ZIP/7z. Der Restore entpackt dieses direkt per `zstd | tarfile`-Stream (kein Zwischen-`.tar` auf der Platte), mit Path-Traversal-Schutz; `odoodev doctor` prüft passend auf eine `zstd`-CLI.
- **Behoben:** `.tar.gz`-Backups wurden fälschlich als reiner SQL-Dump behandelt (der Filestore ging verloren) — sie werden jetzt korrekt als tar entpackt.

**Version 0.31.1:**
- **Behoben:** `.7z`-Backups ließen sich unter Debian/WSL2 nicht wiederherstellen — die Extraktion erkennt jetzt zusätzlich das Binary `7za` (von Debians `p7zip`), und die Fehlermeldung nennt die korrekten Pakete je Plattform.
- **Behoben:** Der wkhtmltopdf-Hinweis war unter Linux unbrauchbar — er verweist jetzt auf das patched-Qt-`.deb` von `github.com/wkhtmltopdf/packaging`; die Erkennung durchsucht zusätzlich `/opt/wkhtmltox/bin`.
- **Neu:** `odoodev doctor` prüft jetzt zusätzlich auf eine 7-Zip-CLI, sodass bei einer Neueinrichtung frühzeitig gewarnt wird, falls `.7z`-Backups nicht wiederherstellbar wären.

**Version 0.31.0:**
- **Neu:** Datenbank-Backup direkt aus dem TUI (`b`) — Dialog für DB + Typ (ZIP/SQL), läuft im Hintergrund-Thread, Datei landet in `~/Downloads/`.
- **Neu:** DB-Wechsel zur Laufzeit aus dem TUI (`d`) — Auswahl aus den verfügbaren Datenbanken, Server startet damit neu.
- **Neu:** Modul-Katalogpflege aus dem TUI (`a` = Apps-Liste aktualisieren, `k` = nicht-installierte Module entfernen) sowie zwei Checkboxen im CSV-Export-Dialog (`x`), damit die CSV nur tatsächlich installierte Module enthält.
- **Geändert:** `odoodev db backup` legt das Backup jetzt standardmäßig in `~/Downloads/` ab (statt im Arbeitsverzeichnis); `--output` überschreibt das weiterhin.

**Version 0.30.1:**
- **Behoben:** Das Schnellmenü (`m`) schnitt seinen letzten Eintrag (`Load language`) unten ab — die Höhe ist jetzt adaptiv (`95%`), alle Einträge sind sichtbar (und die Liste scrollt auf sehr kleinen Terminals).

**Version 0.30.0:**
- **Behoben:** Die Footer-Tastenleiste (`q | m | ?`) wurde von der Versionsanzeige verdeckt — die Version liegt jetzt auf einer eigenen Zeile direkt über dem Footer, beide sind sichtbar.
- **Geändert:** Das Schnellmenü (`m`) zeigt jetzt zu jeder Aktion die zugehörige Taste an (z. B. `0  Alle Level`, `s  Sichtbares Log speichern`).

**Version 0.11.0:**
- Semver-konformer Minor-Release des TUI-Funktionsumfangs (Schnellmenü `m`, Live-DB-Erkennung, editierbares Export-DB-Feld, Versionsanzeige) inkl. der Odoo-19-Fixes. Keine funktionalen Änderungen gegenüber 0.10.1.

**Version 0.10.1:**
- **Behoben:** Der TUI-Modulexport stürzte auf Odoo 19 ab (`installable` wurde aus `ir.module.module` entfernt) — der Filter nutzt jetzt das versionsübergreifende `state`-Feld.
- **Behoben:** Die `/xmlrpc/2`-Deprecation-Warnung auf Odoo 19 wird nun unterdrückt (der richtige `xmlrpc`-Controller-Logger wird stummgeschaltet).
- **Neu:** Die odoodev-Versionsnummer wird unten rechts im TUI angezeigt.

**Version 0.10.0:**
- **Behoben:** Der TUI-Modus nutzt jetzt die tatsächliche Datenbank (`-d`/`--database` bzw. `-- -d <db>`) statt eines geratenen Fallbacks; der bediente DB-Name wird zusätzlich live aus den Odoo-Logs erkannt und in der Statusleiste angezeigt.
- **Neu:** Aufklappendes Schnellmenü (`m`) für schmale Monitore — die Fußzeile zeigt nur noch `q Quit | m Menu | ? Help`, alle direkten Tasten bleiben aktiv.
- **Neu:** Editierbares Datenbankfeld im CSV-Export-Dialog, vorbelegt mit der erkannten DB.

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
- Database backup & restoration (ZIP, 7z, tar, tar.zst, SQL)
- GDPR anonymization on restore (on by default, Faker-based, incl. HR/employee data, `--no-anonymize` to disable); `res_users` stays testable by default — opt in via `--anonymize-users`
- Native Odoo neutralization on restore (`odoo-bin neutralize`, on by default) + supplementary bank-sync cleanup + standalone `db neutralize` command
- Docker service management (PostgreSQL, Mailpit)
- Shell integration with tab completions (Fish, Bash, Zsh)
- YAML playbook automation for recurring workflows
- Odoo configuration generation with template system
- TUI mode with log viewer, level filtering, an upward quick menu (`m`) for narrow terminals, live database detection from the logs, and module CSV export in Releasemanager format
- Port conflict detection with automatic process cleanup
- Interactive addon selector for repos/pull (`--select`)
- Language loading and translation overwrite (`--load-language`, `--i18n-overwrite`)
- Session cleanup before Odoo start (`--clean-sessions`)
- Debian 13 / Python 3.12+ compatibility (setuptools, build dependencies)
- Cross-version migration mode (shared PostgreSQL container and filestore)
- `odoodev doctor` — all environment checks at a glance incl. PyPI update notice
- Database copy/rename (`db copy`, `db rename`) incl. filestore
- Machine-readable output (`--json`) for `db list`, `config versions`, `venv check`
- Playbook variables (`vars:` block, `{{ vars.x }}`, `{{ env.X }}`, `{{ date }}`, `--var` overrides) and playbook discovery (`run --list`)

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

> **Documentation:**
> - **[Wiki: Odoo Development Workflow](usage/odoo-development-workflow.md)** — End-to-end guide with Hello-World module (bilingual DE/EN)
> - [Setup & First-Time Configuration](usage/setup.md) — Setup wizard, init, .env management
> - [Server Start & Stop](usage/start.md) — Start modes, prerequisites, TUI
> - [Repositories](usage/repos.md) — Clone, pull, addon selector
> - [Database](usage/db.md) — Backup, restore, list, drop
> - [Virtual Environment](usage/venv.md) — UV-based venv management
> - [Docker](usage/docker.md) — PostgreSQL & Mailpit services
> - [Configuration](usage/config.md) — Versions, platform info, `config set`/`edit`
> - [Doctor](usage/doctor.md) — Environment checks and PyPI update notice
> - [Playbooks](usage/run.md) — YAML automation and inline steps
> - [Migration](usage/migrate.md) — Cross-version DB migration
> - [Shell Integration](usage/shell.md) — Completions, wrappers, aliases

### Command Reference

| Command | Description | Details |
|---------|-------------|---------|
| `odoodev setup` | Interactive setup wizard | [setup.md](usage/setup.md) |
| `odoodev init [VERSION]` | Initialize new development environment | [setup.md](usage/setup.md) |
| `odoodev start [VERSION]` | Start Odoo server | [start.md](usage/start.md) |
| `odoodev stop [VERSION]` | Stop Odoo server and Docker | [start.md](usage/start.md) |
| `odoodev repos [VERSION]` | Clone/update repositories | [repos.md](usage/repos.md) |
| `odoodev pull [VERSION]` | Quick `git pull` across all repos | [repos.md](usage/repos.md) |
| `odoodev db [SUB] [VERSION]` | Database operations (backup, restore, neutralize, list, drop) | [db.md](usage/db.md) |
| `odoodev env [SUB] [VERSION]` | .env file management (setup, check, show, dir) | [setup.md](usage/setup.md) |
| `odoodev venv [SUB] [VERSION]` | Virtual environment management | [venv.md](usage/venv.md) |
| `odoodev docker [SUB] [VERSION]` | Docker service control | [docker.md](usage/docker.md) |
| `odoodev doctor [VERSION]` | Environment checks + PyPI update notice | [doctor.md](usage/doctor.md) |
| `odoodev config [SUB]` | Configuration and versions (incl. `set`/`edit`) | [config.md](usage/config.md) |
| `odoodev run [PLAYBOOK]` | YAML playbook or inline steps (`--list`, `--var`) | [run.md](usage/run.md) |
| `odoodev migrate [SUB]` | Migration mode for cross-version DB migration | [migrate.md](usage/migrate.md) |
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
├── tui/                   # TUI mode (Textual — log viewer, status, quick menu, module export)
├── templates/              # Jinja2 templates (docker-compose, .env, odoo.conf)
└── data/
    ├── versions.yaml       # Version registry
    └── examples/           # Example playbooks and requirements templates
```

### Development

```bash
uv venv && source .venv/bin/activate.fish
uv pip install -e ".[dev]"
pytest                                  # Tests (776)
ruff check . && ruff format --check .   # Linting
mypy odoodev                            # Type checking
uv build                                # Build package
```

### Changelog

The full version history is available in the [Release Notes](RELEASE_NOTES.md).

**Version 0.32.0:**
- **Added:** `odoodev db restore` checks free disk space before extracting — the uncompressed size is estimated (exact for ZIP, conservative `size × 3` for compressed formats) and compared against the free space on the extraction and filestore filesystems. If space is tight: a warning with concrete numbers plus a `Continue anyway?` prompt (default no) instead of failing mid-copy. Disable with `--no-check-space`.
- **Added:** `odoodev db restore` can optionally delete the original backup afterwards — after a successful restore it asks `Delete original backup file?` (default no, never automatic). New flags `--delete-backup` (delete without prompting) and `--keep-backup` (never ask/delete) make it scriptable.
- **Changed:** Leaner restore data handling — the filestore is now moved instead of copied. Previously it lived on disk three times (backup + extracted temp + copied destination). The destination transfer now uses `shutil.move` (instant rename on the same filesystem, copy+delete fallback across filesystems), eliminating the double storage. `--keep-temp` still copies (temp kept for debugging). The playbook restore path was aligned.

**Version 0.31.4:**
- **Added:** `odoodev db backup` now supports `.tar.zst` stream backups (`--type tar.zst`) — produces a Zstandard-compressed tar (`dump.sql` + `filestore/`) matching the backup server (`container2backup` v4.7.0+) and the restore added in 0.31.2. Implemented symmetrically: a Python `tarfile` stream is piped into the `zstd` CLI (no `zstandard` package needed). Well suited to large databases with a big filestore. A new `--level/-l` option sets the zstd compression level (1=fastest .. 19/22=smallest, default 5). The interactive picker lists `TAR.ZST` alongside `SQL` and `ZIP`; the command fails early with an install hint when the `zstd` CLI is missing.

**Version 0.31.3:**
- **Fixed:** `odoodev db restore`'s interactive `Backup file:` prompt rejected valid paths with surrounding whitespace — a pasted or autocompleted trailing space/newline caused "File not found" even though the file existed. Path inputs are now stripped before `~` expansion.

**Version 0.31.2:**
- **Added:** `odoodev db restore` now supports `.tar.zst` stream backups — the backup server (`container2backup` v4.7.0+) produces a Zstandard-compressed tar (`dump.sql` + `filestore/`) for large databases instead of a staged ZIP/7z. Restore decompresses these directly via a `zstd | tarfile` stream (no intermediate `.tar` on disk), with path-traversal protection; `odoodev doctor` gained a matching `zstd` check.
- **Fixed:** `.tar.gz` backups were mistreated as a plain SQL dump (the filestore was lost) — they now extract correctly as tar.

**Version 0.31.1:**
- **Fixed:** `.7z` backups could not be restored on Debian/WSL2 — extraction now also detects the `7za` binary (shipped by Debian's `p7zip`), and the error message names the correct packages per platform.
- **Fixed:** The wkhtmltopdf hint was unusable on Linux — it now points to the patched-Qt `.deb` from `github.com/wkhtmltopdf/packaging`; detection also searches `/opt/wkhtmltox/bin`.
- **Added:** `odoodev doctor` now also checks for a 7-Zip CLI, warning early during a fresh setup when `.7z` backups would not be restorable.

**Version 0.31.0:**
- **Added:** Database backup straight from the TUI (`b`) — dialog for DB + type (ZIP/SQL), runs in a worker thread, the file lands in `~/Downloads/`.
- **Added:** Runtime database switch from the TUI (`d`) — pick from the available databases, the server restarts bound to the choice.
- **Added:** Module-catalog maintenance from the TUI (`a` = update apps list, `k` = remove non-installed modules) plus two checkboxes in the CSV export dialog (`x`) so the CSV reflects only truly-installed modules.
- **Changed:** `odoodev db backup` now defaults to `~/Downloads/` (instead of the working directory); `--output` still overrides it.

**Version 0.30.1:**
- **Fixed:** The quick menu (`m`) clipped its last entry (`Load language`) — the height is now adaptive (`95%`), so all entries are visible (and the list scrolls on very small terminals).

**Version 0.30.0:**
- **Fixed:** The footer keybinding bar (`q | m | ?`) was hidden by the version label — the version now sits on its own row directly above the footer, both fully visible.
- **Changed:** The quick menu (`m`) now shows the direct shortcut key for each action (e.g. `0  All levels`, `s  Save visible log`).

**Version 0.11.0:**
- Semver-correct minor release of the TUI feature set (quick menu `m`, live DB detection, editable export DB field, version display) including the Odoo 19 fixes. No functional changes versus 0.10.1.

**Version 0.10.1:**
- **Fixed:** The TUI module export crashed on Odoo 19 (`installable` was removed from `ir.module.module`) — the filter now uses the cross-version `state` field.
- **Fixed:** The `/xmlrpc/2` deprecation warning on Odoo 19 is now silenced (the correct `xmlrpc` controller logger is muted).
- **Added:** The odoodev version number is shown in the bottom-right of the TUI.

**Version 0.10.0:**
- **Fixed:** The TUI now uses the actual database (`-d`/`--database` or `-- -d <db>`) instead of a guessed fallback; the served database is additionally detected live from the Odoo logs and shown in the status bar.
- **Added:** Upward quick menu (`m`) for narrow terminals — the footer is condensed to `q Quit | m Menu | ? Help`, all direct keys stay active.
- **Added:** Editable database field in the CSV export dialog, pre-filled with the detected DB.

### License

[AGPL-3.0-or-later](LICENSE) — Equitania Software GmbH

### Contact

- **Website:** https://www.equitania.de
- **Email:** info@equitania.de
