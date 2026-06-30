# Server Start & Stop

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

### Server starten

```bash
# Normaler Start (Version wird aus Verzeichnis erkannt)
odoodev start

# Explizite Version angeben
odoodev start 18

# Entwicklungsmodus (Hot-Reload)
odoodev start 18 --dev

# Interaktive Shell
odoodev start 18 --shell

# Tests ausfuehren
odoodev start 18 --test

# Venv aktivieren ohne Server zu starten
odoodev start 18 --prepare

# Odoo-Argumente direkt uebergeben
odoodev start 18 -d mydb -u my_module

# Auf allen Interfaces binden (z.B. fuer VM-Zugriff)
odoodev start 18 --host 0.0.0.0
```

### Start-Modi im Ueberblick

| Modus | Flag | Beschreibung |
|-------|------|-------------|
| **Normal** | *(kein Flag)* | Produktionsnaher Start. Views werden aus der Datenbank geladen, kein Auto-Reload. |
| **Development** | `--dev` | Entwicklungsmodus (`--dev=all`): Views aus XML-Dateien laden, Auto-Reload bei Code-Aenderungen, pdb-Debugger bei Exceptions. **Nur fuer Entwicklung!** |
| **Shell** | `--shell` | Interaktive Odoo-Python-Shell mit vollem Zugriff auf die ORM-API. |
| **Test** | `--test` | Startet Odoo mit `--test-enable --stop-after-init` — fuehrt Unit-Tests aus und beendet sich. |
| **Prepare** | `--prepare` | Aktiviert nur die virtuelle Umgebung und oeffnet eine Shell, ohne Odoo zu starten. |

> **Hinweis:** `--dev=all` aktiviert alle Entwickler-Features (XML-Reload, Python Auto-Reload, pdb-Debugger). Einzelne Features koennen kommagetrennt gewaehlt werden, z.B. `--dev=reload,xml`. Niemals in Produktion verwenden!

### TUI-Tastenkombinationen (`--tui`)

Der TUI-Modus (`odoodev start 18 --tui`) zeigt Logs mit Level-Filter, Suche und Clipboard-Export. Damit die Fußzeile auch auf schmalen Monitoren passt, zeigt sie nur noch `q Quit | m Menu | ? Help`. Mit `m` öffnet sich ein nach oben aufklappendes Menü (Pfeiltasten + Enter), das alle Aktionen nach Ansicht / Log / Export / Server gruppiert. Alle direkten Tasten unten funktionieren weiterhin. Mit `?` lässt sich die vollständige Tastenbelegung jederzeit anzeigen.

Der angezeigte Datenbankname wird live aus den Odoo-Logzeilen erkannt (die tatsächlich bediente DB) und ist im Export-Dialog als editierbares Feld vorbelegt. Die odoodev-Version wird unten rechts angezeigt.

**Maus-Selektion:** Text im Log mit der Maus markieren (der gezogene Bereich wird hervorgehoben) und mit der Taste `y` (yank) kopieren — kopiert wird **nur** der markierte Bereich. Bewusst eine eigene Taste statt `Ctrl+C`/`Cmd+C`, weil diese von praktisch jedem Terminal (Terminus, iTerm, Terminal.app) selbst abgefangen werden und die TUI gar nicht erreichen. Für ganze Zeilenblöcke gibt es weiterhin `c`/`e`/`w`.

| Taste | Funktion |
|-------|----------|
| `q` / `Ctrl+Q` | Beenden (stoppt den Server) |
| `m` | Schnellmenü öffnen (klappt von unten nach oben auf) |
| `r` | Odoo-Server neu starten |
| `u` | Modul aktualisieren (`-u`-Neustart oder XML-RPC Hot-Update) |
| `l` | Sprache laden / Uebersetzungen neu laden |
| `b` | Datenbank sichern nach `~/Downloads/` (ZIP mit Filestore oder nur SQL) |
| `d` | Datenbank wechseln (Server startet mit der gewaehlten DB neu) |
| `a` | Apps-Liste aktualisieren (`update_list` via XML-RPC) |
| `k` | Nicht-installierte Module aus dem Katalog entfernen |
| `?` | Tastenbelegung anzeigen |
| `0` | Alle Log-Level anzeigen |
| `1`–`5` | DEBUG / INFO / WARNING / ERROR / CRITICAL einzeln umschalten |
| `f` | Nur Probleme (WARN + ERROR + CRIT) |
| `/` | Log durchsuchen (`Escape` loescht die Suche) |
| `Space` | Auto-Scroll umschalten |
| `Ctrl+L` | Log-Anzeige leeren |
| `y` | Mit der Maus markierten Bereich kopieren (markieren, dann `y`) |
| `c` | Sichtbare (gefilterte) Zeilen in die Zwischenablage kopieren |
| `e` | Nur ERROR/CRITICAL kopieren |
| `w` | WARN + ERROR + CRIT kopieren |
| `s` | Sichtbares Log speichern nach `~/odoodev-logs/` |
| `x` | Modulliste als CSV nach `~/Downloads/` exportieren (Releasemanager-Format) |

### Bind-Host (`--host`)

Seit v0.4.50 bindet Odoo standardmaessig nur auf `127.0.0.1` (Loopback), damit der Dev-Server nicht ueber gemeinsame Netzwerk-Interfaces exponiert wird. Wer aus einer VM oder einem anderen Rechner auf Odoo zugreifen moechte, verwendet:

```bash
odoodev start 18 --host 0.0.0.0
```

### Container-Runtime (`--runtime`)

Muss `start` PostgreSQL erst hochfahren, nutzt es die konfigurierte Runtime
(`container_runtime`, Standard `docker`). Mit `--runtime docker|apple` lässt sich das
pro Aufruf überschreiben:

```bash
odoodev start 18 --runtime apple   # einmaliger Override
```

Weicht der gewählte Modus vom gespeicherten Standard ab, bietet odoodev an, ihn dauerhaft
zu speichern (`Save 'apple' as default runtime?`). Details und Mac-Setup:
[apple-container.md](apple-container.md).

### Server stoppen (`Ctrl+C`)

`Ctrl+C` beendet den Server seit v0.35.0 sauber inklusive aller Worker-Prozesse — der
Server läuft in einer eigenen Session und wird per Prozessgruppen-Signal gestoppt, sodass
der Port zuverlässig freigegeben wird. (Der interaktive `--shell`-Modus bleibt im
Vordergrund, damit die REPL Eingaben lesen kann.)

### Start-Voraussetzungen

Was `odoodev start` vor dem Start prueft:

1. `.env`-Datei existiert im native_dir — bietet Erstellung an wenn fehlend
2. `.venv/`-Verzeichnis existiert — bietet Erstellung an wenn fehlend
3. `odoo-bin` existiert im server_dir — bietet Repository-Klonen an wenn fehlend
4. `odoo_*.conf` existiert im myconfs_dir (verwendet neueste nach Datumsendung)
5. PostgreSQL-Port ist erreichbar — bietet Docker-Start an wenn nicht
6. `requirements.txt` SHA256-Hash unveraendert — bietet Update an wenn geaendert
7. Python-Patch-Version — Hinweis wenn neuere Version verfuegbar

### Server stoppen

```bash
# Odoo-Prozess und Docker-Services stoppen
odoodev stop 18

# Nur Odoo-Prozess stoppen (Docker weiter laufen lassen)
odoodev stop 18 --keep-docker

# Sofortiger Kill ohne graceful Shutdown
odoodev stop 18 --force
```

Der `stop`-Befehl erkennt den laufenden Odoo-Prozess anhand des konfigurierten Ports (via `lsof`) und beendet ihn zunaechst mit SIGTERM, dann bei Bedarf mit SIGKILL.

---

## English Documentation

### Start Server

```bash
# Normal start (version detected from directory)
odoodev start

# Specify version explicitly
odoodev start 18

# Development mode (hot-reload)
odoodev start 18 --dev

# Interactive shell
odoodev start 18 --shell

# Run tests
odoodev start 18 --test

# Activate venv without starting server
odoodev start 18 --prepare

# Pass Odoo arguments directly
odoodev start 18 -d mydb -u my_module

# Bind to all interfaces (e.g. for VM access)
odoodev start 18 --host 0.0.0.0
```

### Start Modes Overview

| Mode | Flag | Description |
|------|------|-------------|
| **Normal** | *(no flag)* | Production-like start. Views are loaded from the database, no auto-reload. |
| **Development** | `--dev` | Development mode (`--dev=all`): load views from XML files, auto-reload on code changes, pdb debugger on exceptions. **Development only!** |
| **Shell** | `--shell` | Interactive Odoo Python shell with full ORM API access. |
| **Test** | `--test` | Starts Odoo with `--test-enable --stop-after-init` — runs unit tests and exits. |
| **Prepare** | `--prepare` | Only activates the virtual environment and opens a shell without starting Odoo. |

> **Note:** `--dev=all` enables all developer features (XML reload, Python auto-reload, pdb debugger). Individual features can be selected comma-separated, e.g. `--dev=reload,xml`. Never use in production!

### TUI Keybindings (`--tui`)

TUI mode (`odoodev start 18 --tui`) shows logs with level filtering, search and clipboard export. To keep the footer readable on narrow terminals it now shows only `q Quit | m Menu | ? Help`. Press `m` for a menu that folds up from the bottom (arrow keys + Enter), grouping every action by View / Log / Export / Server. All direct keys still work. Press `?` for the full keybinding reference at any time.

The displayed database name is detected live from the Odoo log lines (the database actually served) and pre-fills the editable field in the export dialog. The odoodev version is shown in the bottom-right.

**Mouse selection:** Mark log text with the mouse (the dragged region is highlighted) and copy it with the `y` key (yank) — **only** the marked region is copied. A dedicated key rather than `Ctrl+C`/`Cmd+C`, because virtually every terminal (Terminus, iTerm, Terminal.app) intercepts those itself and they never reach the TUI. For whole line blocks, use `c`/`e`/`w`.

| Key | Action |
|-----|--------|
| `q` / `Ctrl+Q` | Quit (stops the server) |
| `m` | Open the quick menu (folds up from the bottom) |
| `r` | Restart Odoo server |
| `u` | Update module (`-u` restart or XML-RPC hot update) |
| `l` | Load language / reload translations |
| `b` | Back up database to `~/Downloads/` (ZIP with filestore or SQL only) |
| `d` | Switch database (restarts the server with the chosen DB) |
| `a` | Update apps list (`update_list` via XML-RPC) |
| `k` | Remove non-installed modules from the catalog |
| `?` | Show keybinding overlay |
| `0` | Show all log levels |
| `1`–`5` | Toggle DEBUG / INFO / WARNING / ERROR / CRITICAL individually |
| `f` | Issues only (WARN + ERROR + CRIT) |
| `/` | Search log output (`Escape` clears) |
| `Space` | Toggle auto-scroll |
| `Ctrl+L` | Clear log display |
| `y` | Copy the mouse-marked selection (mark, then `y`) |
| `c` | Copy visible (filtered) lines to clipboard |
| `e` | Copy ERROR/CRITICAL lines only |
| `w` | Copy WARN + ERROR + CRIT lines |
| `s` | Save visible log to `~/odoodev-logs/` |
| `x` | Export module list as CSV to `~/Downloads/` (Releasemanager format) |

### Bind Host (`--host`)

Since v0.4.50 Odoo binds to `127.0.0.1` (loopback) only by default, so the dev server is not exposed on shared network interfaces. To reach Odoo from a VM or another machine, use:

```bash
odoodev start 18 --host 0.0.0.0
```

### Container Runtime (`--runtime`)

When `start` has to bring PostgreSQL up, it uses the configured runtime
(`container_runtime`, default `docker`). Override it per call with `--runtime docker|apple`:

```bash
odoodev start 18 --runtime apple   # one-off override
```

If the chosen mode differs from the stored default, odoodev offers to persist it
(`Save 'apple' as default runtime?`). Details and Mac setup:
[apple-container.md](apple-container.md).

### Stopping the Server (`Ctrl+C`)

Since v0.35.0 `Ctrl+C` stops the server cleanly including all worker processes — the server
runs in its own session and is stopped via a process-group signal, so the port is reliably
released. (The interactive `--shell` mode stays in the foreground so the REPL can read input.)

### Start Prerequisites

What `odoodev start` checks before launching Odoo:

1. `.env` file exists in native_dir — offers creation if missing
2. `.venv/` directory exists — offers creation if missing
3. `odoo-bin` exists in server_dir — offers repository cloning if missing
4. `odoo_*.conf` exists in myconfs_dir (uses latest by date suffix)
5. PostgreSQL port is reachable — offers to start Docker if not
6. `requirements.txt` SHA256 hash unchanged — offers update if changed
7. Python patch version — advisory when newer version available

### Stop Server

```bash
# Stop Odoo process and Docker services
odoodev stop 18

# Stop only Odoo process (keep Docker running)
odoodev stop 18 --keep-docker

# Immediate kill without graceful shutdown
odoodev stop 18 --force
```

The `stop` command discovers the running Odoo process by configured port (via `lsof`) and terminates it with SIGTERM first, then SIGKILL if needed.
