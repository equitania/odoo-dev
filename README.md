# odoodev — Unified Odoo Development CLI

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

[![Version](https://img.shields.io/badge/version-0.48.0-blue.svg)]()
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
- Restore-Nachbehandlung komplett opt-in (seit v0.43.0): standardmäßig bleibt die DB unangetastet; per Flag `--deactivate-cron`/`--neutralize`/`--anonymize`/`--wipe` oder gesammelt `--sanitize`
- DSGVO-Anonymisierung (Faker-basiert, inkl. HR-/Mitarbeiterdaten) mit automatischem Neuberechnen gespeicherter Computed Fields (`complete_name`), sodass Übersichten die anonymisierten Daten zeigen; `res_users` optional via `--anonymize-users`; eigenständiger Befehl `db recompute`
- Bewegungsdaten-Reset für Stresstests: `db purge` / `db restore --purge-transactions` löscht Lager/Verkauf/Einkauf/Buchhaltung/MRP/POS und setzt Bestände auf 0 — Produkte, Preislisten und Adressen bleiben erhalten
- Native Odoo-Neutralisierung beim Restore (`odoo-bin neutralize`, opt-in) + ergänzende Bank-Sync-Bereinigung + eigenständiger Befehl `db neutralize`
- Modul-Deinstallation vor den Sanitize-Schritten: `db restore --uninstall-modules mod1,mod2` (interaktive Abfrage ohne Flag) + eigenständiger Befehl `db uninstall`
- Benutzer-Verwaltung als TUI: `db users` — Passwort-Reset und 2FA-Deaktivierung (TOTP) nach einem Restore, mit Suche und DB-Wechsel
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
- Server-Modus-Playbooks: automatisiertes Live→Test-Spiegeln auf Kundenservern (Docker-Container ohne Dev-Layout) — `targets:`/`env_file:`/`rpc:`-Sektionen, Steps `server.backup`, `server.restore`, `server.neutralize`, `server.update-all`, `container.stop/start`, `sql.execute`, `rpc.execute` (Beispiel: `data/examples/playbooks/server-mirror.yaml`)

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
| `odoodev start [VERSION]` | Odoo-Server starten (`--runtime docker\|apple`) | [start.md](usage/start.md) |
| `odoodev stop [VERSION]` | Odoo-Server und Docker stoppen | [start.md](usage/start.md) |
| `odoodev repos [VERSION]` | Repositories klonen/aktualisieren | [repos.md](usage/repos.md) |
| `odoodev pull [VERSION]` | Schneller `git pull` aller Repos | [repos.md](usage/repos.md) |
| `odoodev db [SUB] [VERSION]` | Datenbankoperationen (backup, restore, purge, recompute, neutralize, list, drop) | [db.md](usage/db.md) |
| `odoodev export modules [VERSION]` | Modulliste als Releasemanager-CSV per XML-RPC exportieren (`--json` für GUIs) | [export.md](usage/export.md) |
| `odoodev env [SUB] [VERSION]` | .env-Dateiverwaltung (setup, check, show, dir) | [setup.md](usage/setup.md) |
| `odoodev venv [SUB] [VERSION]` | Virtual Environment verwalten | [venv.md](usage/venv.md) |
| `odoodev docker [SUB] [VERSION]` | Lokale Container-Services steuern (Docker / Apple Container, `--runtime`) | [docker.md](usage/docker.md) |
| `odoodev bench [VERSION]` | PostgreSQL-Benchmark Docker vs Apple Container | [apple-container.md](usage/apple-container.md) |
| `odoodev doctor [VERSION]` | Umgebungs-Checks + PyPI-Update-Hinweis | [doctor.md](usage/doctor.md) |
| `odoodev config [SUB]` | Konfiguration und Versionen (inkl. `set`/`edit`) | [config.md](usage/config.md) |
| `odoodev run [PLAYBOOK]` | YAML-Playbook oder Inline-Steps (`--list`, `--var`) | [run.md](usage/run.md) |
| `odoodev requirements [SUB] [VERSION]` | Requirements-Baseline + lokales Overlay abgleichen (`sync`, `diff`, `adopt`) | siehe unten |
| `odoodev playbook [SUB]` | Playbook-Assistent: interaktiv erstellen (`create`), Feldschema für GUIs (`schema --json`), prüfen (`validate`) | [playbook.md](usage/playbook.md) |
| `odoodev migrate [SUB]` | Migrationsmodus für versionsübergreifende DB-Migration | [migrate.md](usage/migrate.md) |
| `odoodev shell-setup` | Shell-Completions und Wrapper installieren | [shell.md](usage/shell.md) |
| `odoodev capability-card` | Agent Capability Card ausgeben (rohes Markdown für KI-Agenten, Version live injiziert) | [AGENT.md](usage/AGENT.md) |

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
│   │   ├── requirements.local.txt   # [MANUELL] Overlay (v0.63.0)
│   │   └── requirements.txt         # [GENERATED] Baseline + Overlay
│   ├── conf/odooXX_template.conf    # [MANUELL]
│   └── scripts/repos.yaml           # [MANUELL]
├── myconfs/odoo_YYMMDD.conf         # [GENERATED]
└── vXX-addons/, vXX-oca/, ...       # [REPOS]
```

**Legende:** `[GENERATED]` = von odoodev erzeugt | `[REPOS]` = per git clone | `[MANUELL]` = vom Benutzer

### Requirements: Baseline + Overlay

Seit v0.63.0 ist `requirements.txt` eine generierte Datei, keine mehr zum Bearbeiten. Drei Dateien
sind beteiligt:

| Datei | Herkunft | Bearbeitet der Benutzer? |
|-------|----------|---------------------------|
| `requirements.base.txt` | Mit odoodev ausgeliefert (`data/examples/vXX/`) | Nein |
| `requirements.local.txt` | Maschinenlokales Overlay (`vXX-dev/devXX_native/`) | **Ja — hier eintragen** |
| `requirements.txt` | Generiert aus Baseline + Overlay | Nein — wird überschrieben |

Overlay-Einträge ersetzen den passenden Baseline-Eintrag an Ort und Stelle (Abgleich über
Paketname + Environment-Marker, z. B. `python_version`), zusätzliche Einträge werden angehängt.
`odoodev requirements sync` regeneriert die Datei; `odoodev requirements diff` zeigt Baseline vs.
Overlay vs. installiert; `odoodev requirements adopt` überführt eine handgepflegte
`requirements.txt` einmalig verlustfrei in Baseline + Overlay (Backup als `.pre-adopt`). Hält ein
Overlay-Pin ein Baseline-Update zurück (etwa `Werkzeug==3.0.6` unter v16, weil Odoos `http.py` das
in Werkzeug 3.1 entfernte `werkzeug.__version__` liest), meldet jeder Sync das explizit.

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
pytest                                  # Tests (907)
ruff check . && ruff format --check .   # Linting
mypy odoodev                            # Type-Check
uv build                                # Paket bauen
```

### Änderungsprotokoll

Die vollständige Versionshistorie steht in den [Release Notes](RELEASE_NOTES.md).

**Version 0.63.0:**
- **Neu:** Requirements sind jetzt Baseline (mitgeliefert) plus lokales Overlay
  (`requirements.local.txt`, nie von odoodev überschrieben) — die wirksame `requirements.txt` wird
  aus beiden generiert. Overlay-Einträge ersetzen den passenden Baseline-Eintrag, abgeglichen über
  `(PEP-503-Name, Environment-Marker)` — v17 pinnt sechs Pakete zweimal, unterschieden nur durch
  einen `python_version`-Marker.
- **Neu:** Befehlsgruppe `odoodev requirements`: `sync` (regenerieren, `--all`, `--check` für CI),
  `diff` (Baseline vs. Overlay vs. installiert, `--json`), `adopt` (einmalige verlustfreie
  Migration einer handgepflegten Datei, Backup als `requirements.txt.pre-adopt`).
- **Neu:** Ein zurückgehaltener Pin wird jetzt gemeldet — hält ein Overlay-Eintrag ein
  Baseline-Update zurück, meldet jeder Sync das explizit (`Werkzeug: overlay holds 3.0.6 back
  (base: 3.1.3)`).
- **Geändert:** `odoodev start` regeneriert `requirements.txt`, wenn sich die mitgelieferte
  Baseline geändert hat — direkt vor der bestehenden SHA256-Frische-Prüfung.
- **Sicherheit:** `requirements sync` verweigert den Lauf, wenn die vorhandene `requirements.txt`
  nicht von odoodev generiert wurde und kein Overlay existiert, und verweist auf `adopt`.

**Version 0.62.2:**
- **Behoben:** `--wipe` hat die Quelldateien der Asset-Bundles gelöscht. Nach einem Wipe zeigte das Backend dauerhaft die rote Meldung „Stilfehler“: `web.assets_frontend` und `web.report_assets_common` ließen sich nicht mehr kompilieren. Geschützt war nur `res_model IN ('ir.ui.view','ir.ui.menu')` — jede Asset-Quelle hat aber `res_model IS NULL` und wurde damit genau von dem Zweig erfasst, der herrenlose Uploads treffen sollte: die Theme-SCSS unter `/_custom/…`, `web.asset_styles_company_report` und die Standardbilder der Website-Snippets. Da `ir_model_data` keinen Fremdschlüssel auf `ir_attachment` hat, blieben die XML-IDs stehen, `env.ref('web.asset_styles_company_report')` zeigte ins Leere und Odoos eigene Reparatur lief wirkungslos. Der Wipe verschont jetzt zusätzlich jeden Anhang mit `url` (die Asset-Quellen) und jeden Anhang mit XML-ID (Moduldaten, kein Nutzerinhalt). Rechnungs-PDFs, Chatter-Uploads und Anhänge ohne `res_model` und ohne XML-ID werden weiterhin gelöscht.
- **Geändert:** Der Wipe repariert, was ein Wipe unter 0.62.0 hinterlassen hat: verwaiste `ir_model_data`-Zeilen und `/_custom/`-`ir_asset`-Records ohne Quell-Attachment werden entfernt, sodass Odoo die Bundles wieder aus den Originaldateien baut. Auf einer gesunden Datenbank passiert nichts. Die gelöschten Anhänge selbst kommen mit einem Modul-Update zurück: `odoodev start 18 -d <db> -u web,website`.
- **Geändert:** Der Hilfetext von `--wipe` versprach „keeps asset bundles and image fields“ — richtig für die kompilierten Bundles, falsch für die Quellen, aus denen sie gebaut werden. Er benennt jetzt, was tatsächlich erhalten bleibt.

**Version 0.62.1:**
- **Behoben:** `odoodev repos` konnte eine Konfiguration mit kaputtem `addons_path` erzeugen. Der Ersetzungs-Ausdruck traf nur die Schlüsselzeile, sodass die alten Pfade stehen blieben und der neu erzeugte Block ihnen lediglich vorangestellt wurde — jeder Pfad tauchte doppelt auf, und an der Nahtstelle verklebten zwei Pfade über einen Zeilenumbruch hinweg zu einem einzigen, nicht existierenden Pfad. Odoo meldet das nur auf Debug-Ebene; sichtbar wurde es unter v16 als HTTP 500 auf der Bildplatzhalter-Route. Die Ersetzung erfasst jetzt die Schlüsselzeile samt aller eingerückten Folgezeilen und ist idempotent.

**Version 0.62.0:**
- **Behoben:** `--wipe` hat nichts gelöscht. Statt der versprochenen Löschung von Nachrichten und Anhängen liefen nur zwei `UPDATE`s: der Nachrichten-Body wurde durch einen Platzhalter ersetzt und der Volltextindex der Anhänge geleert. Folge auf einer zurückgespielten Produktivdatenbank: Der Chatter blieb vollständig lesbar — Tracking-Historie (die im Chatter angezeigten Feldänderungen), Follower und Aktivitäten wurden nie angefasst — und sämtliche Anhänge blieben erhalten, Rechnungs-PDFs sowohl in der Datenbank als auch im Filestore. `--wipe` löscht jetzt tatsächlich: die Chatter-Tabellen (Kind vor Eltern, damit es auch bei `NO ACTION`-Fremdschlüsseln durchläuft), die Anhang-Zeilen und — neu — die verwaisten Dateien im Filestore.
- **Neu:** `gc_filestore()` entfernt Filestore-Dateien, auf die kein verbliebener Anhang mehr zeigt (analog zu Odoos eigenem `ir.attachment._gc_file_store`). Die überlebenden Referenzen werden *nach* dem Löschen gelesen, damit eine von Odoo per Prüfsumme geteilte Datei erhalten bleibt. Zwei Schutzmechanismen verhindern ein Löschen im falschen Verzeichnis: Eine fehlgeschlagene Abfrage bricht ab, statt als „nichts referenziert" gelesen zu werden, und das Verzeichnis muss nach der Datenbank benannt sein.
- **Bewusst erhalten:** Anhänge mit gesetztem `res_field` (Odoo legt `fields.Image` in `ir_attachment` ab — ein pauschales Löschen würde jedes Produktbild und jeden Avatar entfernen) sowie die kompilierten Asset-Bundles auf `ir.ui.view` / `ir.ui.menu`. Anhänge ohne `res_model` werden dagegen jetzt mitgelöscht; ein einfaches `NOT IN (...)` hätte sie stillschweigend behalten, da `NULL NOT IN (...)` zu `NULL` auswertet.

**Version 0.61.2:**
- **Behoben (Sicherheit):** Datenbank-Backups wurden mit den Standardrechten der umask angelegt (typisch `0644`) — obwohl ein Backup die komplette Datenbank inklusive der Passwort-Hashes aus `res_users` enthält, war es damit für jedes andere lokale Konto lesbar. SQL-Dump, ZIP und `.tar.zst` werden jetzt alle mit `0600` geschrieben, auch wenn ein früherer Lauf die Datei mit weiteren Rechten hinterlassen hat. Das Archivformat ist unverändert.
- **Behoben:** Die Mindestversionen von `textual`, `Faker` und `rich` lagen weit unter den tatsächlich verwendeten Versionen. Da `uv.lock` nicht im Wheel mitgeliefert wird, konnte eine Neuinstallation per `pip` ein inkompatibles `textual` 1.x auflösen und die TUI zur Laufzeit lahmlegen. Die Untergrenzen sind jetzt `textual>=8.0.0`, `Faker>=40.0.0`, `rich>=15.0.0`.
- **Geändert:** Die Testsuite braucht keine laufende Container-Runtime mehr. 47 von 1464 Tests scheiterten auf jedem Rechner ohne gestartetes Docker bzw. Apple Container, weil sie `db`-Befehle über den echten PostgreSQL-Preflight laufen ließen. Der Preflight wird jetzt zentral in `tests/conftest.py` neutralisiert — ein neu hinzugefügter `db`-Test kann die Abhängigkeit nicht mehr versehentlich wieder einbauen.

**Version 0.61.1:**
- **Behoben (Sicherheit):** Eine `git_url` aus `repos.yaml` ging ungeprüft an `git clone`. Gits Standard-Policy erlaubt beim direkten Aufruf den `ext::`-Transport, der einen beliebigen Shell-Befehl ausführt — eine manipulierte `repos.yaml` konnte damit Code unter deiner Kennung starten. Jede URL wird jetzt vor der Übergabe an git validiert: führendes `-` und alles mit `::` wird abgelehnt, erlaubt sind `ssh://`, `https://`, `http://`, `git://` und die Kurzform `user@host:pfad`.
- **Behoben (Sicherheit):** Die generierte `odoo_YYMMDD.conf` enthält DB- und Odoo-Master-Passwort im Klartext, wurde aber mit den Standardrechten der umask geschrieben (typisch `0644`) — auf geteilten Entwicklungs- oder CI-Rechnern für jedes andere lokale Konto lesbar. Sie wird jetzt mit `0600` angelegt, auch wenn ein früherer Lauf die Datei mit weiteren Rechten hinterlassen hat.

**Version 0.61.0:**
- **Neu:** `odoodev db restore --dry-run` — Restore-Preflight ohne jede Änderung: prüft Backup-Datei (Pfad + Größe), Ziel-Datenbank (würde mit `--drop` überschrieben, harter Fehler mit `--no-drop`) und freien Speicherplatz, und listet die geplanten Post-Restore-Schritte aus den gesetzten Sanitize-Flags auf. Exit-Code 0 = Restore würde durchlaufen, 1 = würde fehlschlagen; garantiert ohne Drop/Create/Extract/Restore. Grundlage des Dry-Run-Buttons im Restore-Wizard der GUI.

**Version 0.60.0:**
- **Neu:** `odoodev db cleanup` — Filestore↔Datenbank-Konsistenzcheck pro Version: verwaiste Filestores (Verzeichnis ohne Datenbank, mit Größenangabe) und Datenbanken ohne Filestore werden gemeldet. Standardmäßig nur Bericht; `--delete-orphans` löscht verwaiste Filestores nach y/N-Rückfrage (`-y` für Skripte), `--json` liefert den GUI/Agent-Kontrakt (löscht nie). Ein aktiver Migrations-Modus (geteilter Filestore) wird berücksichtigt.
- **Neu:** Runtime-bewusste Container-Diagnose. Ist PostgreSQL nicht erreichbar, prüft odoodev die konfigurierte Runtime (Docker oder Apple Container) — CLI installiert? Daemon bzw. `container-apiserver` läuft? — und nennt die konkrete Abhilfe (`container system start`, `open -a Docker`, Installations-/Umschalt-Hinweise) statt eines pauschalen Docker-Verweises. `odoodev docker up` ist selbstheilend: Ein gestoppter Apple-Container-API-Server wird automatisch mitgestartet; `docker status` meldet eine nicht bereite Runtime samt Abhilfe, ohne Zustand zu verändern.

**Version 0.59.1:**
- **Behoben:** Der Export-Button im TUI-Export-Dialog wurde auf üblichen Terminalhöhen unterhalb des sichtbaren Bereichs abgeschnitten. Das Layout ist jetzt kompakt (Login + Passwort nebeneinander), der Dialog scrollt bei sehr kleinen Terminals, und Enter in einem Eingabefeld startet den Export direkt. `odoodev export --help` liefert jetzt eine vollwertige Hilfeseite mit Beispielen und Credential-Reihenfolge.

**Version 0.59.0:**
- **Neu:** `odoodev export modules` — der Releasemanager-CSV-Export ist jetzt ein eigenständiger CLI-Befehl mit demselben Kern wie der TUI-Export (`x`). Für GUIs/Agenten: `--json` liefert ein einzeiliges Ergebnis (`path`, `count`, `updated`, `cleaned`); Zugangsdaten per Flags, `ODOODEV_ODOO_USER`/`ODOODEV_ODOO_PASSWORD` oder der neuen `odoo_login`-Sektion der globalen Config (`config set odoo_login.username/password`). Der TUI-Export-Dialog hat jetzt Benutzer/Passwort-Felder (vorbelegt aus der Config, optional speicherbar), läuft in einem Worker-Thread und zeigt einen Fortschritts-Overlay statt die Oberfläche zu blockieren.
- **Geändert:** `odoodev start` zeigt die Instanz-Informationen (Ports, Datenbank, Config, Verzeichnisse) ZUERST, gefolgt von genau einer Bestätigungsfrage; erst danach laufen die Preflight-Checks mit Seiteneffekten. `--yes/-y` ist dokumentiert und überspringt nur die Frage. Wer den Start ablehnt, hinterlässt keine Spuren mehr (kein `.pgpass`-Write, kein Container-Start).
- **Behoben:** Neue Einträge in `repos.yaml` wurden nie geklont, wenn der SSH-Access-Check fehlschlug oder der Klon scheiterte — Fehler wurden verschluckt. `odoodev repos` versucht den Klon jetzt immer, meldet Fehler pro Repo, zeigt eine Cloned/Updated/Skipped/Failed-Tabelle und beendet mit Exit-Code 1 bei Fehlern. `--config-only` führt wirklich keine Git-Operationen mehr aus.
- **Behoben:** Die von `odoodev start` angebotene `requirements.txt`-Aktualisierung speicherte den Hash nicht — die Frage kam bei jedem Start erneut. Der Hash wird jetzt nach erfolgreicher Installation gespeichert.

**Version 0.58.0:**
- **Neu:** `effective_ports` in `config versions --json` — jede Version meldet zusätzlich die zur Laufzeit wirksamen Ports (Registry-Defaults überschrieben durch die `.env` der Version); GUIs und Agenten matchen Container und bauen URLs gegen diese Werte.

**Version 0.57.0:**
- **Neu:** `backup_source.mode: from_backup_step` — der Playbook-Runner reicht die vom `server.backup`-Step erzeugte Datei jetzt direkt an `server.restore` im selben Lauf weiter. Kein Pattern-Raten mehr zwischen Backup und Restore; `file` und `newest_in_dir` bleiben voll unterstützt.
- **Geändert:** Assistenten-Logik nach dem zweiten Praxistest: (1) Beim frischen Backup entfallen alle Pattern-/Ableitungsfragen — das Playbook nutzt automatisch `from_backup_step`. (2) Was mit der wiederhergestellten Datenbank passiert, ist EINE Entscheidung: Die Frage „Was soll mit der wiederhergestellten Datenbank passieren?" deckt mit `neutralize` sowohl das psql-Sanitize-Flag als auch den `server.neutralize`-Step ab (Neutralize taucht nicht mehr doppelt auf); die Options-Checkbox enthält nur noch Infrastruktur-Schritte. Schema-Version 3; Answers-Dateien der Versionen 1 und 2 bleiben gültig.

**Version 0.56.0:**
- **Neu:** Sprachwahl im Playbook-Assistenten. Ist keine Sprache explizit konfiguriert (`--lang`, `ODOODEV_LANG`, `cli.language` in der Config), startet der Assistent mit „Sprache / Language?" (Deutsch/English, Vorbelegung aus der Shell-Locale) und speichert die Wahl auf Wunsch als odoodev-weiten Standard.
- **Geändert:** Geführte Usability durch den ganzen Assistenten: nummerierte Schritte („Schritt 1/6 — Grundlagen" … „Schritt 6/6 — Zusammenfassung", Dev-Zweig 4 Schritte) mit Kurz-Intro zum Mirror-Modell QUELLE → ZIEL; der Quell-Block fragt „Quell-Name", der Ziel-Block „Ziel-Name" (das generische „Target-Name" bleibt den Zusatz-Targets vorbehalten); einfache Formulierungen mit beschrifteten Auswahloptionen („Was soll bei einem Fehler passieren?" — Anhalten/Weitermachen; Sanitize-Flags mit Klartext-Beschreibung). Gespeicherte Werte, Answers-Dateien und erzeugte YAML bleiben unverändert. **Fix:** Die Shell-Locale-Erkennung der Sprache griff nie, weil die Config-Abfrage auch ohne Config-Datei „en" lieferte.

**Version 0.55.0:**
- **Geändert:** Playbook-Assistent mit Quelle-zuerst-Führung. Der Server-Zweig fragt jetzt explizit „Was ist die QUELLE des Mirrors?" (frisches Backup von einem Container-Paar mit automatisch abgeleitetem Restore-Pattern, bestehende Backup-Datei oder neuestes Backup nach Muster) und danach getrennt das Ziel — mit Self-Mirror-Guard: Ein Restore zurück auf das gerade gesicherte System erfordert eine explizite Bestätigung, die Builder-Validierung lehnt Backup-Quelle == Restore-Ziel ab. `server.restore` ist immer Teil des Mirrors; die Options-Checkbox umfasst nur noch die Zusatzschritte. Schema-Version 2 (Answers-Dateien der Version 1 bleiben gültig). **Fixes:** Server-Pfade (`~/update_docker_odoo.py` etc.) werden nicht mehr lokal expandiert, sondern bleiben wörtlich in der YAML; ohne eingegebene Secret-Werte wird keine leere env-Datei mehr geschrieben.

**Version 0.54.0:**
- **Neu:** `odoodev playbook create` — interaktiver Playbook-Assistent. Der Server-Zweig führt geführt durch das Live→Test-Mirror-Rezept (Backup → optionaler Container-Neuaufbau via `server.rebuild`/`update_docker_odoo.py` → Stop → Restore mit Sanitize-Auswahl → SQL-Presets für Enterprise-Code, eq_cloud-Bereinigung und Website-Domain-Tausch → Start → Neutralize → Update-all → RPC), der Dev-Zweig über eine gruppierte Schritt-Checkbox. Secrets landen nie in der YAML: Der Assistent schreibt sie auf Wunsch in eine env_file mit Rechten 600 (Merge bei bestehender Datei) und erkennt alle `{{ env.X }}`-Referenzen automatisch. Für GUI und Agenten: `playbook create --answers datei.json --non-interactive` (derselbe Generator-Kern, kein Drift möglich), `playbook schema --json` (Formular-Kontrakt) und `playbook validate [--json]`. Jedes erzeugte Playbook wird vor dem Schreiben durch die Runner-Validierung geprüft.

**Version 0.52.0:**
- **Neu:** `odoodev capability-card` — das Tool liefert seine eigene KI-Anleitung selbst aus. Der Befehl gibt die Agent Capability Card (`usage/AGENT.md`) als rohes Markdown auf stdout aus; die Versionszeile wird beim Ausgeben live aus `__version__` injiziert und kann damit nie mehr veralten. Die Karte wird per hatchling force-include ins Wheel gebündelt (`odoodev/data/AGENT.md`), im Repo-Checkout greift ein Fallback auf `usage/AGENT.md`. KI-Agenten brauchen damit weder Repo- noch Web-Zugriff: `odoodev capability-card` genügt als vollständige Selbstbeschreibung.

**Version 0.50.0:**
- **Neu:** Server-Modus-Playbooks — der manuelle Live→Test-Restore-Prozess auf Kundenservern läuft jetzt vollautomatisch über `odoodev run`. Playbooks definieren `targets:` (Container-Paare wie `live-odoo`/`live-db`, `test-odoo`/`test-db`), eine `env_file:` für Secrets (Werte der Datei gewinnen über die Prozess-Umgebung, nie im YAML) und eine `rpc:`-Sektion für API-Zugriff. Der komplette Ablauf: frisches Live-Backup (`server.backup`, container2backup-kompatibles `.tar.zst`) oder neuestes vorhandenes Backup per Glob-Pattern (`newest_in_dir`), `container.stop`, `server.restore` (Drop + `TEMPLATE template0`, Dump via `docker exec psql`, Filestore-Tausch über `docker inspect`-Mount-Auflösung inkl. `chown`, Sessions-Bereinigung, opt-in Sanitize-Schritte der bestehenden `db restore`-Maschinerie), kundenspezifisches SQL (`sql.execute`, Jinja-Templates in Statement-Listen), `container.start`, `server.neutralize`/`server.update-all` (odoo-bin im laufenden Container, Update mit anschließendem Neustart) und deklarative RPC-Konfiguration (`rpc.execute` via `odoorpc-toolbox`, neues Extra `odoodev-equitania[rpc]`). Beispiel-Playbook: `data/examples/playbooks/server-mirror.yaml`.
- **Neu:** `pg_exec_container()` — alle psql/pg_dump-Aufrufe gezielt per Container-Name durch `docker exec` routen (DB-Container ohne publizierte Ports); Jinja-Rendering der Step-Argumente jetzt rekursiv (verschachtelte Mappings und Listen).

**Version 0.49.1:**
- **Behoben:** Master-Data-Purge brach an transienten Wizard-Tabellen ab. Auf einer echten Odoo-16-DB rollte `db restore --sanitize` (und `db purge-master-data`) mit `unhandled FK account_payment_register.partner_id` zurück — `account_payment_register` ist ein Odoo-TransientModel (Wizard „Zahlung erfassen") mit einer `NO ACTION`-FK, die den Drift-Guard auslöste. odoodev fragt jetzt `ir_model.transient` ab und leert solche Wegwerf-Wizard-Tabellen automatisch, bevor die Partner gelöscht werden — generisch für alle aktuellen und künftigen Wizards. Nicht-transiente unbekannte FKs lösen weiterhin den Guard-Abbruch aus (Schutz echter Stammdaten aus Custom-/OCA-Modulen).

**Version 0.49.0:**
- **Behoben:** Destruktive Bestätigungen vereinheitlicht auf ein einfaches `y/N`. Der Bulk-`db drop`, `db purge-master-data` und der Master-Data-Purge-Schritt von `db restore` verlangten zuvor die Eingabe der exakten Anzahl und brachen bei allem anderen still ab — wer `yes` eintippte, brach ungewollt ab. Alle drei nutzen jetzt das übliche `y/N` (Default Nein); der laute WARN-Block bleibt, `-y/--yes` überspringt weiterhin.
- **Behoben:** Verklebte Ausgabe nach dem Restore unter der docker-exec-psql-Fallback. `docker exec -i` schaltete mit dem TTY als stdin das Terminal in den Raw-Modus (ONLCR aus), sodass ab der Sanitize-Pipeline alle Zeilen ohne Umbruch aneinanderklebten. Die psql-/pg_dump-/`odoo-bin neutralize`-Subprozesse laufen jetzt mit `stdin=DEVNULL` und lassen das Terminal unangetastet.

**Version 0.48.0:**
- **Geändert (BREAKING):** `db restore --sanitize` ist jetzt ein vollständiger „Template-DB-aus-Produktion"-Reset. Zusätzlich zum Anonymisieren LÖSCHT es nun alle Bewegungsdaten, CRM-Leads, HR-Mitarbeiter, Helpdesk-Tickets, Nachrichten/Aktivitäten, die Kunden-/Lieferanten-/Kontakt-Partner und deren Anhänge. **Behalten:** Produkte, Preislisten, Benutzer (+ deren Partner), eigene Firmen (+ deren Partner), Konfiguration. Ausstieg mit `--no-purge-master-data`; die Löschung erfordert die Eingabe der Partner-Anzahl (mit `-y` übersprungen — Automatisierung prüfen!).
- **Neu:** Flag `--purge-master-data/--no-purge-master-data` und eigenständiger Befehl `odoodev db purge-master-data` (`--dry-run`, `-y`). Läuft in einer `session_replication_role=replica`-Transaktion (Superuser nötig): folgt dem FK-Graph (Multi-Hop-Kaskaden, SET-NULL-Rückreferenzen, Ahnen-Keep-Set), bricht ohne Löschung ab, falls eine geschützte Stammtabelle oder eine unbehandelte RESTRICT-Referenz betroffen wäre. Produktbilder und System-Assets bleiben unangetastet.
- **Neu:** `--anonymize` hält auch den Partner der eigenen Firma lesbar (Keep-Set schließt jetzt `res_company`-Partner ein).

**Version 0.47.0:**
- **Neu:** `db drop` kann jetzt mehrere Datenbanken auf einmal löschen — ideal zum Aufräumen nach vielen fehlgeschlagenen Testläufen. `-m/--multi` öffnet eine Checkbox-Mehrfachauswahl, `-n` ist wiederholbar (`-n a -n b`), `--all` zielt auf alle Nicht-System-DBs, `--filter test_` grenzt die Auswahl ein, `--terminate-connections` beendet offene Verbindungen vorher. System-DBs sind geschützt; Massenlöschungen erfordern die Eingabe der Anzahl zur Bestätigung. Filestore-Entfernung und Erfolgs-/Fehler-Bilanz je DB inklusive.
- **Behoben:** `--anonymize` benennt interne Benutzer nicht mehr um. Die `res_partner`-Anonymisierung traf auch die zu `res_users` gehörenden Partner, sodass nach dem Sanitize Faker-Namen in der Benutzerliste standen — obwohl `res_users` bewusst unangetastet bleibt. Partner mit einem `res_users`-Bezug werden jetzt von jeder `res_partner`-Anonymisierung ausgenommen; interne Benutzer behalten Name und Kontaktdaten. Benutzer-Anonymisierung weiterhin per `--anonymize-users` opt-in.

**Version 0.46.2:**
- **Behoben:** `db users` zeigte immer „No users found" — die Benutzerliste baute eine tab-verkettete Textspalte, aber psqls Standard-Ausgabeformat rendert eingebettete Tabs als Leerzeichen, sodass keine Zeile geparst wurde. Zeilen-Abfragen laufen jetzt über `psql -t -A -F <tab>` (unaligned, Booleans nativ `t`/`f`).
- **Behoben:** `db restore --uninstall-modules` stürzte bei mehreren Modulen mit `Expected singleton` ab, weil Drittmodule `button_immediate_uninstall` mit Singleton-Annahme überschreiben. Module werden jetzt einzeln in der angegebenen Reihenfolge deinstalliert (frisches Environment je Iteration); ein fehlschlagendes Modul blockiert die übrigen nicht mehr.

**Version 0.46.1:**
- **Neu:** `odoodev start -c <pfad>` / `--config` — explizite Konfigurationsdatei statt glob-basierter "neueste gewinnt"-Auswahl in `myconfs/`. Bei mehreren `odoo_*.conf` für verschiedene Systeme kann jetzt eine konkrete ausgewählt werden. Ohne `-c` bleibt die bisherige Logik. Playbook-Argument `config` für den `start`-Schritt entsprechend.
- **Behoben (v0.46.0):** Second-Order-SQL-Injection in der Purge-Introspektion (`_null_repair_targets`) — DB-gelesene Tabellennamen werden jetzt via `_check_identifier` validiert.
- **Geändert (v0.46.0):** `db restore` intern in `RestorePipeline`-Klasse + `RestoreOptions`-Dataclass refactored (keine Verhaltensänderung); `VersionConfigProtocol` ersetzt 13 `type: ignore`; mypy-Konfiguration, `SECURITY.md`, `.pre-commit-config.yaml` hinzugefügt.

**Version 0.45.0:**
- **Neu:** `db users` — interaktive TUI für die Benutzer-Verwaltung nach einem Restore: Benutzerliste mit 2FA-Status, `p` setzt ein neues Passwort (pbkdf2_sha512-Hash), `t` deaktiviert TOTP-2FA (Secret + vertrauenswürdige Geräte), `/` Suche, `d` Datenbank-Wechsel.
- **Neu:** Modul-Deinstallation vor dem Sanitize: `db restore --uninstall-modules mod1,mod2` bzw. interaktive Abfrage (Enter überspringt) deinstalliert störende Module via `odoo-bin shell`, bevor Neutralize/Anonymize/Wipe laufen; zusätzlich eigenständiges `db uninstall` und Playbook-Argument `uninstall-modules`. `db restore` hat jetzt `-y/--yes` für Skripte.
- **Geändert:** Apple Container wird nur noch auf macOS angeboten — auf Linux reduziert sich die Runtime-Auswahl auf eine Docker-Bestätigung; konfiguriertes `apple` fällt mit Warnung auf Docker zurück, explizites `--runtime apple` bricht ab.

**Version 0.44.0:**
- **Neu:** `db purge` / `db restore --purge-transactions` setzt eine Datenbank für Stresstests auf einen leeren Bewegungsdaten-Stand zurück — löscht Lagerbewegungen, Aufträge, Rechnungen, Lieferscheine (MRP/POS inklusive) und setzt Bestände auf 0, behält aber Produkte, Preislisten, Adressen, Benutzer und Konfiguration. Mit `--anonymize` kombinierbar. `--dry-run` zeigt die Zieltabellen; separates Opt-in (nicht in `--sanitize`).
- **Behoben:** Nach der Anonymisierung zeigen Kanban- und Rechnungsübersichten jetzt die anonymisierten Daten. Die per Raw-SQL geänderten Felder ließen das gespeicherte `complete_name` (aus dem `display_name` liest) veraltet — `db restore --anonymize` berechnet die betroffenen Computed Fields jetzt via `odoo-bin shell` neu; eigenständiger Befehl `db recompute`, abschaltbar mit `--no-recompute`.

**Version 0.43.0:**
- **Geändert (BREAKING):** `db restore` lässt die wiederhergestellte Datenbank standardmäßig komplett unangetastet. Alle Nachbehandlungen sind jetzt Opt-in statt Opt-out: `--deactivate-cron`, `--neutralize`, `--anonymize` (nur noch Faker-Ersatzwerte), neu `--wipe` (Löschen von Nachrichteninhalten, Anhang-Index und Verknüpfungstabellen — aus `--anonymize` herausgelöst) und neu `--sanitize` als Sammel-Flag für alle vier (explizite `--no-*` gewinnen). `--anonymize-users` funktioniert jetzt eigenständig. Ohne Flags weist die Ausgabe darauf hin, dass die Datenbank unverändert blieb.

**Version 0.42.2:**
- **Behoben:** `odoodev start` startet Odoo nicht mehr, bevor PostgreSQL wirklich bereit ist. Bei Apple Container nimmt der Port-Forwarder der Micro-VM TCP-Verbindungen an, bevor PostgreSQL in der VM antwortet — Odoo hing dadurch 10–30 s in stillen Verbindungs-Retries, bevor z. B. ein `-u all` losläuft. Die Bereitschaft wird jetzt auf PostgreSQL-Protokollebene geprüft (Host-`pg_isready` wenn vorhanden, sonst abhängigkeitsfreie Socket-Probe) und bis zu 60 s mit Spinner abgewartet; `odoodev docker up` wartet ebenso. Auch langsame Docker-Container-Starts sind damit abgedeckt.

**Version 0.42.1:**
- **Behoben:** Im Migrationsmodus übersteuerte die `.env` der Zielversion (mit ihrem regulären `DB_PORT`) den geteilten Quell-Port — `db backup 18`, `start 18` & Co. versuchten den falschen Port, nur die Quellversion funktionierte. Neuer zentraler Resolver mit Vorrang Migration-Ziel-Port > `.env` > Registry, angewandt an allen acht Auflösungsstellen (inkl. `PGPORT` für odoo-bin und der odoo.conf-Generierung).

**Version 0.42.0:**
- **Neu:** Alle `db`-Befehle funktionieren jetzt auch ohne installierte PostgreSQL-Client-Tools auf dem Host — fehlen `psql`/`pg_dump`, laufen die Kommandos automatisch per `docker exec` im Container, der den Ziel-Port veröffentlicht (typischer Fall: Migrationsserver). Das umgeht auch Versionskonflikte des Host-Clients (z.B. Debian 12: Client 15 gegen Postgres-16-Container). Erzwingbar per `ODOODEV_PG_EXEC=host|container`.
- **Neu:** Saubere, handlungsorientierte Fehlermeldungen statt Tracebacks — sind weder Client-Tools noch ein laufender Container vorhanden, nennt der Befehl beide Lösungswege (Tools installieren oder `odoodev docker up`).
- **Geändert:** `db restore` und die Anonymisierung pipen SQL-Dumps jetzt per stdin statt `psql -f` (nötig für den Container-Fallback, im Host-Modus verhaltensgleich).

**Version 0.41.0:**
- **Behoben:** Der markierte Text im TUI-Log wird jetzt tatsächlich hervorgehoben. Zwei Ursachen: (1) `render_line` trug die Selektionsfarbe per `apply_style` auf, das aber als `(Selektionsstil + Segmentstil)` kombiniert — der eigene Log-Hintergrund jedes Segments übermalte die Markierung, sie blieb unsichtbar. Der Bereich wird jetzt umgekehrt zusammengesetzt (`Segmentstil + Selektionsstil`), sodass die Selektionsfarbe gewinnt. (2) Textuals `selection_updated` löste keinen vollständigen Repaint aus (RichLogs eigener `_line_cache` blieb ungeleert), wodurch alte Markierungen „einbrannten" — jetzt wie in Textuals `Log`-Widget behoben.
- **Geändert:** Markiermodus deutlich sichtbar — dauerhafter Hinweis `y = mark mode` über dem Footer, im Modus `◉ MARK · drag · y copies · Esc cancels · auto-scroll paused`, Statusleisten-Badge `● MARK` und FilterBar-Scroll-Indikator zeigen den Modus. Die Kopier-Meldung unterscheidet jetzt Teilzeile vs. mehrere Zeilen.

**Version 0.40.0:**
- **Behoben:** Das Markieren mit der Maus im TUI-Log funktioniert endlich — und man sieht, was man markiert. Wahre Ursache hinter vier Fehlversuchen (0.36–0.39): Textuals `RichLog.render_line` bettet (anders als das `Log`-Widget) nie das `offset`-Meta ein, das der Compositor braucht, um eine Mausposition auf eine Textstelle abzubilden — dadurch blieb die Selektion intern immer leer (kein Highlight; das Terminal griff ein und kopierte „alles Sichtbare"). Jetzt werden die Offsets gesetzt, Selektion, Hervorhebung und Kopieren funktionieren.
- **Geändert:** Bewusster Markierungsmodus, umgeschaltet mit `y` (wie tmux-Copy-Mode). `y` startet den Modus: Auto-Scroll friert ein, das Log bekommt einen farbigen Rahmen und die Statusleiste zeigt `● MARK`. Mit der Maus ziehen → Bereich sichtbar hervorgehoben. `y` erneut → kopiert **genau** diesen Bereich und verlässt den Modus; `Esc` bricht ohne Kopieren ab. Außerhalb des Modus gehört die Maus wie gewohnt dem Terminal, es wird nie automatisch kopiert.

**Version 0.39.0:**
- **Behoben:** Die mit der Maus markierte Auswahl im TUI wird jetzt sichtbar hervorgehoben (vorher unsichtbar — Textuals `RichLog` rendert das Selection-Styling von Haus aus nicht).
- **Behoben:** Mit der Maus gezogener Text wird beim Loslassen automatisch in die Zwischenablage kopiert — wie in Claude Workbench, ganz ohne Taste. Das automatische Kopieren wurde 0.37.0 zurückgenommen, weil im live mitlaufenden Log jedes Loslassen versehentlich alle sichtbaren Zeilen erfasste; Ursache war ein driftendes Koordinaten-Mapping durch das Auto-Scrollen während des Ziehens. Das Log friert Auto-Scroll jetzt für die Dauer des Markierens ein, wodurch die Zuordnung stabil bleibt. `y` funktioniert weiterhin als manueller Fallback.

**Version 0.38.0:**
- **Geändert:** Den mit der Maus markierten Bereich kopiert im TUI jetzt die Taste `y` (yank) statt `Ctrl+C`. `Ctrl+C`/`Cmd+C` werden von praktisch jedem Terminal (Terminus, iTerm, Terminal.app) selbst abgefangen und erreichen die TUI nicht — daher eine eigene, terminal-unabhängige Taste: Bereich markieren (bleibt hervorgehoben), dann `y` drücken → kopiert **genau** die Markierung. `c`/`e`/`w` unverändert.

**Version 0.37.0:**
- **Geändert:** TUI-Maus-Kopieren überarbeitet. Das automatische Kopieren beim Loslassen der Maustaste (0.36.0) erwies sich im live mitlaufenden Log als unbrauchbar (kopierte ungewollt alle sichtbaren Zeilen). Jetzt **markiert** die Maus nur einen Bereich (sichtbar hervorgehoben), und kopiert wird **ausschließlich** auf bewusstes `Ctrl+C`/`Cmd+C` — und zwar **genau** der markierte Bereich. (Unter macOS fängt das Terminal `Cmd+C` oft selbst ab; `Ctrl+C` ist der zuverlässige Weg.) Die Tasten `c`/`e`/`w` (sichtbare/Error/Warn-Zeilen) sind unverändert.

**Version 0.36.0:**
- **Neu:** Im TUI-Modus mausbasiertes Kopieren eingeführt (in 0.37.0 überarbeitet — siehe oben).

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
- Restore post-processing is fully opt-in (since v0.43.0): the DB is left untouched by default; enable per flag `--deactivate-cron`/`--neutralize`/`--anonymize`/`--wipe` or all at once with `--sanitize`
- GDPR anonymization (Faker-based, incl. HR/employee data) with automatic recompute of stored computed fields (`complete_name`) so overviews show the anonymized data; `res_users` opt-in via `--anonymize-users`; standalone `db recompute` command
- Transactional-data reset for stress tests: `db purge` / `db restore --purge-transactions` deletes stock/sale/purchase/accounting/MRP/POS data and zeroes stock — products, pricelists and partners are kept
- Native Odoo neutralization on restore (`odoo-bin neutralize`, opt-in) + supplementary bank-sync cleanup + standalone `db neutralize` command
- Module uninstall before the sanitize steps: `db restore --uninstall-modules mod1,mod2` (interactive prompt without the flag) + standalone `db uninstall` command
- User management TUI: `db users` — password reset and 2FA (TOTP) disable after a restore, with search and DB switching
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
- Server-mode playbooks: automated live→test mirroring on customer servers (Docker containers without a dev layout) — `targets:`/`env_file:`/`rpc:` sections, steps `server.backup`, `server.restore`, `server.neutralize`, `server.update-all`, `container.stop/start`, `sql.execute`, `rpc.execute` (example: `data/examples/playbooks/server-mirror.yaml`)

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
| `odoodev start [VERSION]` | Start Odoo server (`--runtime docker\|apple`) | [start.md](usage/start.md) |
| `odoodev stop [VERSION]` | Stop Odoo server and Docker | [start.md](usage/start.md) |
| `odoodev repos [VERSION]` | Clone/update repositories | [repos.md](usage/repos.md) |
| `odoodev pull [VERSION]` | Quick `git pull` across all repos | [repos.md](usage/repos.md) |
| `odoodev db [SUB] [VERSION]` | Database operations (backup, restore, purge, recompute, neutralize, list, drop) | [db.md](usage/db.md) |
| `odoodev export modules [VERSION]` | Export the module list as Releasemanager CSV via XML-RPC (`--json` for GUIs) | [export.md](usage/export.md) |
| `odoodev env [SUB] [VERSION]` | .env file management (setup, check, show, dir) | [setup.md](usage/setup.md) |
| `odoodev venv [SUB] [VERSION]` | Virtual environment management | [venv.md](usage/venv.md) |
| `odoodev docker [SUB] [VERSION]` | Local container service control (Docker / Apple Container, `--runtime`) | [docker.md](usage/docker.md) |
| `odoodev bench [VERSION]` | PostgreSQL benchmark Docker vs Apple Container | [apple-container.md](usage/apple-container.md) |
| `odoodev doctor [VERSION]` | Environment checks + PyPI update notice | [doctor.md](usage/doctor.md) |
| `odoodev config [SUB]` | Configuration and versions (incl. `set`/`edit`) | [config.md](usage/config.md) |
| `odoodev run [PLAYBOOK]` | YAML playbook or inline steps (`--list`, `--var`) | [run.md](usage/run.md) |
| `odoodev requirements [SUB] [VERSION]` | Reconcile the requirements baseline with the local overlay (`sync`, `diff`, `adopt`) | see below |
| `odoodev playbook [SUB]` | Playbook assistant: interactive creation (`create`), GUI field schema (`schema --json`), validation (`validate`) | [playbook.md](usage/playbook.md) |
| `odoodev migrate [SUB]` | Migration mode for cross-version DB migration | [migrate.md](usage/migrate.md) |
| `odoodev shell-setup` | Install shell completions and wrappers | [shell.md](usage/shell.md) |
| `odoodev capability-card` | Print the agent capability card (raw Markdown for AI agents, live version injection) | [AGENT.md](usage/AGENT.md) |

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
│   │   ├── requirements.local.txt   # [MANUAL] Overlay (v0.63.0)
│   │   └── requirements.txt         # [GENERATED] Baseline + overlay
│   ├── conf/odooXX_template.conf    # [MANUAL]
│   └── scripts/repos.yaml           # [MANUAL]
├── myconfs/odoo_YYMMDD.conf         # [GENERATED]
└── vXX-addons/, vXX-oca/, ...       # [REPOS]
```

**Legend:** `[GENERATED]` = created by odoodev | `[REPOS]` = via git clone | `[MANUAL]` = user-provided

### Requirements: Baseline + Overlay

Since v0.63.0, `requirements.txt` is a generated file — no longer one to edit. Three files are
involved:

| File | Origin | User-edited? |
|------|--------|---------------|
| `requirements.base.txt` | Shipped with odoodev (`data/examples/vXX/`) | No |
| `requirements.local.txt` | Machine-local overlay (`vXX-dev/devXX_native/`) | **Yes — edit here** |
| `requirements.txt` | Generated from baseline + overlay | No — gets overwritten |

Overlay entries replace their matching baseline entry in place (matched on package name +
environment marker, e.g. `python_version`); entries with no baseline counterpart are appended.
`odoodev requirements sync` regenerates the file; `odoodev requirements diff` shows baseline vs.
overlay vs. installed; `odoodev requirements adopt` migrates a hand-maintained `requirements.txt`
into baseline + overlay once, losslessly (keeps a `.pre-adopt` backup). When an overlay pin holds
back a baseline update — e.g. `Werkzeug==3.0.6` on v16, because Odoo's `http.py` reads
`werkzeug.__version__`, which Werkzeug 3.1 removed — every sync reports it explicitly.

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
pytest                                  # Tests (907)
ruff check . && ruff format --check .   # Linting
mypy odoodev                            # Type checking
uv build                                # Build package
```

### Changelog

The full version history is available in the [Release Notes](RELEASE_NOTES.md).

**Version 0.63.0:**
- **Added:** Requirements are now a shipped baseline plus a local overlay (`requirements.local.txt`,
  never overwritten by odoodev) — the effective `requirements.txt` is generated from both. Overlay
  entries replace their baseline counterpart, matched on `(PEP 503 name, environment marker)` — v17
  pins six packages twice, distinguished only by a `python_version` marker.
- **Added:** New command group `odoodev requirements`: `sync` (regenerate, `--all`, `--check` for
  CI), `diff` (baseline vs. overlay vs. installed, `--json`), `adopt` (one-time lossless migration
  of a hand-maintained file, keeping a `requirements.txt.pre-adopt` backup).
- **Added:** A held-back pin is now reported — when an overlay entry blocks a baseline bump, every
  sync says so explicitly (`Werkzeug: overlay holds 3.0.6 back (base: 3.1.3)`).
- **Changed:** `odoodev start` regenerates `requirements.txt` when the shipped baseline moved on,
  immediately before the existing SHA256 freshness check.
- **Safety:** `requirements sync` refuses to run when the existing `requirements.txt` was not
  generated by odoodev and no overlay exists, and points at `adopt`.

**Version 0.62.2:**
- **Fixed:** `--wipe` deleted the source files behind the asset bundles. After a wipe the backend showed a permanent red *"style error"* banner: `web.assets_frontend` and `web.report_assets_common` no longer compiled. Only `res_model IN ('ir.ui.view','ir.ui.menu')` was protected — but every asset source has `res_model IS NULL` and was therefore caught by the very branch meant for orphaned uploads: the theme SCSS under `/_custom/…`, `web.asset_styles_company_report` and the website snippets' default images. Since `ir_model_data` has no foreign key to `ir_attachment`, the XML IDs survived, `env.ref('web.asset_styles_company_report')` pointed at a dead id and Odoo's own repair did nothing. The wipe now additionally spares every attachment with a `url` (the asset sources) and every attachment with an XML ID (module data, not user content). Invoice PDFs, chatter uploads and attachments without a `res_model` and without an XML ID are still deleted.
- **Changed:** The wipe repairs what a wipe under 0.62.0 left behind: dangling `ir_model_data` rows and `/_custom/` `ir_asset` records without a source attachment are removed, so Odoo rebuilds the bundles from the original module files. Nothing happens on a healthy database. The deleted attachments themselves come back with a module update: `odoodev start 18 -d <db> -u web,website`.
- **Changed:** The `--wipe` help text promised "keeps asset bundles and image fields" — true for the compiled bundles, wrong for the sources they are built from. It now names what is actually kept.

**Version 0.62.1:**
- **Fixed:** `odoodev repos` could produce a config with a broken `addons_path`. The replacement pattern only ever matched the key line, so the old paths survived and the freshly generated block was merely prepended to them — every path appeared twice, and at the seam two paths were glued across a newline into a single, non-existent path. Odoo reports that nothing above debug level; under v16 it surfaced as an HTTP 500 on the image placeholder route. The replacement now covers the key line plus every indented continuation line and is idempotent.

**Version 0.62.0:**
- **Fixed:** `--wipe` did not delete anything. Instead of the promised deletion of messages and attachments it ran just two `UPDATE`s: the message body was replaced with a placeholder and the attachments' full-text index was cleared. On a restored production database that meant the chatter stayed fully readable — the tracking history (the field changes rendered in the chatter), followers and activities were never touched — and every attachment survived, invoice PDFs both in the database and in the filestore. `--wipe` now really deletes: the chatter tables (child before parent, so it also works where a foreign key is `NO ACTION`), the attachment rows and — new — the orphaned files in the filestore.
- **Added:** `gc_filestore()` removes filestore files no longer referenced by any surviving attachment (mirroring Odoo's own `ir.attachment._gc_file_store`). The surviving references are read *after* the delete, so a file shared via Odoo's checksum deduplication is preserved. Two guards prevent deleting the wrong tree: a failed query aborts instead of being read as "nothing is referenced", and the directory must be named after the database.
- **Deliberately kept:** attachments with `res_field` set (Odoo stores `fields.Image` in `ir_attachment`, so a blanket delete would strip every product image and avatar) and the compiled asset bundles on `ir.ui.view` / `ir.ui.menu`. Attachments without a `res_model` are now included in the delete; a plain `NOT IN (...)` would have silently kept them, since `NULL NOT IN (...)` evaluates to `NULL`.

**Version 0.61.2:**
- **Fixed (security):** Database backups were created with the process umask (typically `0644`) — even though a backup holds the complete database including the password hashes from `res_users`, making it readable by every other local account. SQL dump, ZIP and `.tar.zst` are all written with `0600` now, including when an earlier run left the file with looser permissions. The archive format is unchanged.
- **Fixed:** The minimum versions of `textual`, `Faker` and `rich` were far below the versions actually in use. Since `uv.lock` is not shipped inside the wheel, a fresh `pip` install could resolve an incompatible `textual` 1.x and break the TUI at runtime. The floors are now `textual>=8.0.0`, `Faker>=40.0.0`, `rich>=15.0.0`.
- **Changed:** The test suite no longer requires a running container runtime. 47 of 1464 tests failed on any machine without Docker / Apple Container started, because they exercised `db` commands through the real PostgreSQL preflight. That preflight is now neutralized centrally in `tests/conftest.py` — a newly added `db` test can no longer reintroduce the dependency by accident.

**Version 0.61.1:**
- **Fixed (security):** A `git_url` from `repos.yaml` reached `git clone` unvalidated. On a direct git invocation git's default policy honors the `ext::` transport, which runs an arbitrary shell command — a tampered `repos.yaml` could therefore execute code under your account. Every URL is now validated before it reaches git: a leading `-` and anything containing `::` are rejected; `ssh://`, `https://`, `http://`, `git://` and the `user@host:path` shorthand are accepted.
- **Fixed (security):** The generated `odoo_YYMMDD.conf` holds the database and Odoo master password in plaintext but was written with the process umask (typically `0644`) — readable by every other local account on a shared development or CI host. It is now created with `0600`, including when an earlier run left the file with looser permissions.

**Version 0.61.0:**
- **Added:** `odoodev db restore --dry-run` — restore preflight that changes nothing: validates the backup file (path + size), the target database (would be overwritten with `--drop`, hard failure with `--no-drop`) and free disk space, and lists the planned post-restore steps derived from the given sanitize flags. Exit code 0 = the restore would proceed, 1 = it would fail; guaranteed no drop/create/extract/restore. This backs the Dry-Run button in the GUI restore wizard.

**Version 0.60.0:**
- **Added:** `odoodev db cleanup` — per-version filestore↔database consistency check: orphaned filestores (directory without a database, listed with size) and databases without a filestore are reported. Report-only by default; `--delete-orphans` removes orphaned filestores after a y/N confirmation (`-y` for scripts), `--json` provides the GUI/agent contract (never deletes). An active migration group (shared filestore) is honored.
- **Added:** Runtime-aware container diagnosis. When PostgreSQL is unreachable, odoodev probes the configured runtime (Docker or Apple Container) — CLI installed? daemon / `container-apiserver` running? — and surfaces the concrete remedy (`container system start`, `open -a Docker`, install/switch hints) instead of a blanket Docker reference. `odoodev docker up` is self-healing: a stopped Apple Container API server is started transparently; `docker status` reports a non-ready runtime with its remedy without mutating state.

**Version 0.59.1:**
- **Fixed:** The Export button in the TUI export dialog was clipped below the visible area on typical terminal heights. The layout is compact now (login + password side by side), the dialog scrolls on very short terminals, and Enter in any input field submits the export directly. `odoodev export --help` now provides a full help page with examples and the credential precedence chain.

**Version 0.59.0:**
- **Added:** `odoodev export modules` — the Releasemanager CSV export is now a standalone CLI command sharing its core with the TUI export (`x`). For GUIs/agents: `--json` returns a single-line result (`path`, `count`, `updated`, `cleaned`); credentials via flags, `ODOODEV_ODOO_USER`/`ODOODEV_ODOO_PASSWORD`, or the new `odoo_login` section of the global config (`config set odoo_login.username/password`). The TUI export dialog gains username/password fields (pre-filled from the config, optionally persisted), runs in a worker thread, and shows a progress overlay instead of freezing the UI.
- **Changed:** `odoodev start` prints the instance information (ports, database, config, directories) FIRST, followed by exactly one confirmation prompt; the side-effecting preflight checks only run afterwards. `--yes/-y` is documented and skips only the prompt. Declining the start leaves the system untouched (no `.pgpass` write, no container start).
- **Fixed:** New `repos.yaml` entries were never cloned when the SSH access check failed or the clone errored — failures were swallowed. `odoodev repos` now always attempts the clone, reports per-repo errors, prints a Cloned/Updated/Skipped/Failed summary table, and exits 1 on failures. `--config-only` really performs no git operations anymore.
- **Fixed:** The `requirements.txt` update offered by `odoodev start` never stored the hash — the prompt reappeared on every start. The hash is now stored after a successful install.

**Version 0.58.0:**
- **Added:** `effective_ports` in `config versions --json` — each version additionally reports the ports effective at runtime (registry defaults overridden by the version's `.env`); GUIs and agents match containers and build URLs against these values.

**Version 0.57.0:**
- **Added:** `backup_source.mode: from_backup_step` — the playbook runner now hands the file created by the `server.backup` step directly to `server.restore` in the same run. No more pattern guessing between backup and restore; `file` and `newest_in_dir` remain fully supported.
- **Changed:** Assistant logic after the second field test: (1) fresh backups no longer trigger any pattern/derivation questions — the playbook simply uses `from_backup_step`; (2) what happens to the restored database is ONE decision: "What should happen to the restored database?" covers both the psql sanitize flag and the `server.neutralize` step when `neutralize` is picked (neutralize no longer appears twice); the options checkbox only contains infrastructure steps. Schema version 3; answers files of versions 1 and 2 stay valid.

**Version 0.56.0:**
- **Added:** Language question in the playbook assistant. When no language is explicitly configured (`--lang`, `ODOODEV_LANG`, `cli.language` in the config), the wizard opens with "Sprache / Language?" (Deutsch/English, defaulting from the shell locale) and can persist the choice as the odoodev-wide default.
- **Changed:** Guided usability throughout the assistant: numbered steps ("Step 1/6 — Basics" … "Step 6/6 — Summary", dev branch 4 steps) with a short intro explaining the SOURCE -> DESTINATION mirror model; the source block asks "Source name:", the destination block "Destination name:" (the generic "Target name:" is reserved for extra targets); plain-language questions with labeled choices ("What should happen when a step fails?" — stop/continue; sanitize flags with descriptive labels). Stored values, answers files and generated YAML are unchanged. **Fix:** shell-locale language detection never kicked in because the config lookup returned "en" even without a config file.

**Version 0.55.0:**
- **Changed:** Playbook assistant with source-first guidance. The server branch now explicitly asks "What is the SOURCE of the mirror?" (fresh backup from a container pair with auto-derived restore pattern, an existing backup file, or the newest backup by pattern) and then the destination separately — with a self-mirror guard: restoring back onto the system that was just backed up requires explicit confirmation, and builder validation rejects backup source == restore destination. `server.restore` is always part of the mirror; the options checkbox only covers the extra steps. Schema version 2 (version-1 answers files remain valid). **Fixes:** server-side paths (`~/update_docker_odoo.py` etc.) are no longer expanded locally and stay literal in the YAML; no more empty env files when no secret values were entered.

**Version 0.54.0:**
- **Added:** `odoodev playbook create` — interactive playbook assistant. The server branch guides through the live→test mirror recipe (backup → optional container rebuild via `server.rebuild`/`update_docker_odoo.py` → stop → restore with sanitize checkbox → SQL presets for enterprise code, eq_cloud cleanup and website-domain swap → start → neutralize → update-all → RPC), the dev branch uses a grouped step checkbox. Secrets never land in the YAML: on request the assistant writes them into a 0600 env_file (merge-aware for existing files) and auto-detects every `{{ env.X }}` reference. For GUI and agents: `playbook create --answers file.json --non-interactive` (one shared generator core, no drift possible), `playbook schema --json` (form contract) and `playbook validate [--json]`. Every generated playbook is validated through the runner's own validation before it is written.

**Version 0.52.0:**
- **Added:** `odoodev capability-card` — the tool now serves its own AI documentation. The command prints the agent capability card (`usage/AGENT.md`) as raw Markdown on stdout; the version line is injected live from `__version__` at print time, so it can never go stale. The card is bundled into the wheel via hatchling force-include (`odoodev/data/AGENT.md`), with a repo-checkout fallback to `usage/AGENT.md`. AI agents no longer need repo or web access: `odoodev capability-card` is the complete self-description surface.

**Version 0.50.0:**
- **Added:** Server-mode playbooks — the manual live→test restore process on customer servers now runs fully automated via `odoodev run`. Playbooks define `targets:` (container pairs like `live-odoo`/`live-db`, `test-odoo`/`test-db`), an `env_file:` for secrets (file values win over the process environment, never stored in YAML) and an `rpc:` section for API access. The complete flow: fresh live backup (`server.backup`, container2backup-compatible `.tar.zst`) or the newest existing backup by glob pattern (`newest_in_dir`), `container.stop`, `server.restore` (drop + `TEMPLATE template0`, dump via `docker exec psql`, filestore swap through `docker inspect` mount resolution incl. `chown`, sessions cleanup, opt-in sanitize steps reusing the existing `db restore` machinery), customer-specific SQL (`sql.execute`, Jinja templates inside statement lists), `container.start`, `server.neutralize`/`server.update-all` (odoo-bin inside the running container, update with subsequent restart) and declarative RPC configuration (`rpc.execute` via `odoorpc-toolbox`, new extra `odoodev-equitania[rpc]`). Example playbook: `data/examples/playbooks/server-mirror.yaml`.
- **Added:** `pg_exec_container()` — route all psql/pg_dump calls through `docker exec` by explicit container name (DB containers without published ports); Jinja rendering of step args is now recursive (nested mappings and lists).

**Version 0.49.1:**
- **Fixed:** Master-data purge aborted on transient wizard tables. On a real Odoo 16 DB, `db restore --sanitize` (and `db purge-master-data`) rolled back with `unhandled FK account_payment_register.partner_id` — `account_payment_register` is an Odoo TransientModel (the "Register Payment" wizard) with a `NO ACTION` FK that tripped the drift guard. odoodev now introspects `ir_model.transient` and clears such throwaway wizard tables automatically before deleting partners — generically, for every current and future wizard. Non-transient unknown FKs still trigger the guard abort (protecting real master data from custom/OCA modules).

**Version 0.49.0:**
- **Fixed:** Destructive confirmations unified to a plain `y/N`. The bulk `db drop`, `db purge-master-data` and the `db restore` master-data-purge step previously demanded typing the exact record count and aborted silently on anything else — answering `yes` cancelled the operation. All three now use the standard `y/N` (default No); the loud WARN block stays and `-y/--yes` still skips the prompt.
- **Fixed:** Garbled post-restore output under the docker-exec psql fallback. With the controlling TTY as stdin, `docker exec -i` switched the terminal to raw mode (ONLCR off) and left it there, so every line from the sanitize pipeline onward ran together. The psql/pg_dump/`odoo-bin neutralize` subprocesses now run with `stdin=DEVNULL`, leaving the terminal untouched.

**Version 0.48.0:**
- **Changed (BREAKING):** `db restore --sanitize` is now a full "template DB from production" reset. On top of anonymizing, it now DELETES all movement data, CRM leads, HR employees, helpdesk tickets, messages/activities, the customer/vendor/contact partners and their attachments. **Kept:** products, pricelists, users (+ their partner), companies (+ their partner), config. Opt out with `--no-purge-master-data`; the deletion requires typing the partner count (skipped with `-y` — review your automation!).
- **Added:** `--purge-master-data/--no-purge-master-data` flag and standalone `odoodev db purge-master-data` command (`--dry-run`, `-y`). Runs in one `session_replication_role=replica` transaction (superuser required): follows the FK graph (multi-hop cascades, SET-NULL back-references, ancestor keep-set), aborts with no deletion if a protected master table or an unhandled RESTRICT reference would be hit. Product images and system assets are never targeted.
- **Added:** `--anonymize` also keeps the own company's partner legible (keep-set now includes `res_company` partners).

**Version 0.47.0:**
- **Added:** `db drop` can now delete multiple databases at once — ideal for cleaning up after many failed test runs. `-m/--multi` opens a checkbox multi-select, `-n` is repeatable (`-n a -n b`), `--all` targets every non-system DB, `--filter test_` narrows the selection, `--terminate-connections` kills open connections first. System DBs are protected; bulk deletions require typing the count to confirm. Per-DB filestore removal and a dropped/failed tally included.
- **Fixed:** `--anonymize` no longer renames internal users. The `res_partner` anonymization also hit the partners linked to `res_users`, so after a sanitize the user list showed Faker names even though `res_users` is deliberately left untouched. Partners referenced by a `res_users.partner_id` are now excluded from every `res_partner` anonymization pass; internal users keep their real name and contact data. User anonymization stays opt-in via `--anonymize-users`.

**Version 0.46.2:**
- **Fixed:** `db users` always showed "No users found" — the user list built a tab-joined text column, but psql's default aligned format renders embedded tabs as spaces, so no row ever parsed. Row queries now run via `psql -t -A -F <tab>` (unaligned, booleans natively `t`/`f`).
- **Fixed:** `db restore --uninstall-modules` crashed with `Expected singleton` on multiple modules, because third-party modules override `button_immediate_uninstall` with singleton assumptions. Modules are now uninstalled one at a time in the given order (fresh environment per iteration); a failing module no longer blocks the rest.

**Version 0.46.1:**
- **Added:** `odoodev start -c <path>` / `--config` — explicit config file instead of glob-based latest-wins selection in `myconfs/`. When multiple `odoo_*.conf` exist for different systems, a specific one can be selected. Without `-c` the existing logic is unchanged. Playbook arg `config` for the `start` step accordingly.
- **Fixed (v0.46.0):** Second-order SQL injection in purge introspection (`_null_repair_targets`) — DB-sourced table names are now validated via `_check_identifier`.
- **Changed (v0.46.0):** `db restore` internals refactored into `RestorePipeline` class + `RestoreOptions` dataclass (no behavioral change); `VersionConfigProtocol` replaces 13 `type: ignore`; mypy config, `SECURITY.md`, `.pre-commit-config.yaml` added.

**Version 0.45.0:**
- **Added:** `db users` — interactive TUI for user management after a restore: user list with 2FA status, `p` sets a new password (pbkdf2_sha512 hash), `t` disables TOTP 2FA (secret + trusted devices), `/` search, `d` database switch.
- **Added:** Module uninstall before sanitizing: `db restore --uninstall-modules mod1,mod2` or an interactive prompt (Enter skips) uninstalls conflicting modules via `odoo-bin shell` before neutralize/anonymize/wipe run; also standalone `db uninstall` and playbook arg `uninstall-modules`. `db restore` gained `-y/--yes` for scripting.
- **Changed:** Apple Container is only offered on macOS — on Linux the runtime picker collapses to a Docker confirm; a configured `apple` falls back to Docker with a warning, an explicit `--runtime apple` errors out.

**Version 0.44.0:**
- **Added:** `db purge` / `db restore --purge-transactions` resets a database to an empty transactional state for stress tests — deletes stock moves, orders, invoices, deliveries (incl. MRP/POS) and zeroes stock, while keeping products, pricelists, partners, users and configuration. Combines with `--anonymize`. `--dry-run` lists the target tables; a separate opt-in (not in `--sanitize`).
- **Fixed:** Kanban and invoice overviews now show the anonymized data. Raw-SQL anonymization left the stored `complete_name` (which `display_name` reads) stale — `db restore --anonymize` now recomputes the affected computed fields via `odoo-bin shell`; standalone `db recompute` command, disable with `--no-recompute`.

**Version 0.43.0:**
- **Changed (BREAKING):** `db restore` leaves the restored database completely untouched by default. All post-restore processing is now opt-in instead of opt-out: `--deactivate-cron`, `--neutralize`, `--anonymize` (Faker replacement values only), new `--wipe` (deletion of message content, attachment index and linkage tables — split out of `--anonymize`) and new `--sanitize` as a convenience flag for all four (explicit `--no-*` flags win). `--anonymize-users` now works standalone. Without flags the output notes that the database was left unchanged.

**Version 0.42.2:**
- **Fixed:** `odoodev start` no longer launches Odoo before PostgreSQL is actually ready. On Apple Container the micro-VM's port forwarder accepts TCP before PostgreSQL inside answers — Odoo sat 10-30s in silent connection retries before e.g. a `-u all` began. Readiness is now verified at the PostgreSQL protocol level (host `pg_isready` when available, otherwise a dependency-free socket probe) with up to 60s of spinner-backed polling; `odoodev docker up` waits the same way. Slow Docker container boots are covered too.

**Version 0.42.1:**
- **Fixed:** In migration mode the target version's `.env` (with its regular `DB_PORT`) overrode the shared source port — `db backup 18`, `start 18` etc. tried the wrong port; only the source version worked. New central resolver with precedence migration-target port > `.env` > registry, applied at all eight resolution sites (incl. `PGPORT` for odoo-bin and odoo.conf generation).

**Version 0.42.0:**
- **Added:** All `db` commands now work without PostgreSQL client tools installed on the host — when `psql`/`pg_dump` are missing, commands run automatically via `docker exec` inside the container publishing the target port (typical case: migration servers). This also sidesteps host client version mismatches (e.g. Debian 12: client 15 against a Postgres 16 container). Force a mode with `ODOODEV_PG_EXEC=host|container`.
- **Added:** Clean, actionable error messages instead of tracebacks — if neither client tools nor a running container are available, the command names both remedies (install the tools or `odoodev docker up`).
- **Changed:** `db restore` and the anonymization pipe SQL dumps via stdin instead of `psql -f` (required for the container fallback, behavior-identical in host mode).

**Version 0.41.0:**
- **Fixed:** The marked text in the TUI log is now actually highlighted. Two causes: (1) `render_line` applied the selection colour via `apply_style`, which combines as `(selection + segment)` — each segment's own log background overrode the selection, leaving it invisible. The span is now rebuilt as `(segment + selection)` so the selection colour wins. (2) Textual's `selection_updated` didn't force a full repaint (RichLog's own `_line_cache` was never cleared), so old selections lingered — now fixed the same way Textual's `Log` widget does.
- **Changed:** Mark mode is now clearly visible — persistent `y = mark mode` hint above the footer, `◉ MARK · drag · y copies · Esc cancels · auto-scroll paused` while marking, a `● MARK` status-bar badge, and the FilterBar auto-scroll indicator. The copy toast now distinguishes a partial-line selection from multiple lines.

**Version 0.40.0:**
- **Fixed:** Mouse selection in the TUI log finally works — and you can see what you mark. The real root cause behind four failed attempts (0.36–0.39): unlike Textual's `Log` widget, `RichLog.render_line` never embeds the `offset` meta the compositor needs to map a mouse position to a content offset, so the selection stayed empty forever (no highlight; the terminal took over and grabbed "all visible lines"). Offsets are now embedded, so selection, highlight and copy all work.
- **Changed:** Deliberate selection ("mark") mode toggled with `y` (tmux-copy-mode style). `y` enters the mode: auto-scroll freezes, the log gets an accent border and the status bar shows `● MARK`. Drag with the mouse → the region is visibly highlighted. Press `y` again to copy exactly that region and leave the mode; `Esc` cancels without copying. Outside the mode the mouse behaves normally and nothing is ever auto-copied.

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
