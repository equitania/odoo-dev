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
