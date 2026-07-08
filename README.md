# odoodev — Unified Odoo Development CLI

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

[![Version](https://img.shields.io/badge/version-0.45.0-blue.svg)]()
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
| `odoodev env [SUB] [VERSION]` | .env-Dateiverwaltung (setup, check, show, dir) | [setup.md](usage/setup.md) |
| `odoodev venv [SUB] [VERSION]` | Virtual Environment verwalten | [venv.md](usage/venv.md) |
| `odoodev docker [SUB] [VERSION]` | Lokale Container-Services steuern (Docker / Apple Container, `--runtime`) | [docker.md](usage/docker.md) |
| `odoodev bench [VERSION]` | PostgreSQL-Benchmark Docker vs Apple Container | [apple-container.md](usage/apple-container.md) |
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
pytest                                  # Tests (907)
ruff check . && ruff format --check .   # Linting
mypy odoodev                            # Type-Check
uv build                                # Paket bauen
```

### Änderungsprotokoll

Die vollständige Versionshistorie steht in den [Release Notes](RELEASE_NOTES.md).

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
| `odoodev env [SUB] [VERSION]` | .env file management (setup, check, show, dir) | [setup.md](usage/setup.md) |
| `odoodev venv [SUB] [VERSION]` | Virtual environment management | [venv.md](usage/venv.md) |
| `odoodev docker [SUB] [VERSION]` | Local container service control (Docker / Apple Container, `--runtime`) | [docker.md](usage/docker.md) |
| `odoodev bench [VERSION]` | PostgreSQL benchmark Docker vs Apple Container | [apple-container.md](usage/apple-container.md) |
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
pytest                                  # Tests (907)
ruff check . && ruff format --check .   # Linting
mypy odoodev                            # Type checking
uv build                                # Build package
```

### Changelog

The full version history is available in the [Release Notes](RELEASE_NOTES.md).

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
