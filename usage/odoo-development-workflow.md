# Odoo Development Workflow (End-to-End)

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

> **Zweck dieses Artikels:** Du arbeitest diesen Wiki-Artikel von oben nach unten durch und hast am Ende ein lauffähiges Hello-World-Modul auf deiner lokalen Entwicklermaschine, das per Merge-Request auf den `develop`-Branch eingereicht ist.
>
> **Roter Faden:** Du entwickelst das Modul `eq_hello_world` — ein minimales Odoo-Modul mit Menüeintrag, Model und Listen-/Formular-View — vom ersten Setup bis zum Merge-Request.
>
> **Geltungsbereich:** Beispiele und Pfade beziehen sich auf Odoo 18. Der gesamte Workflow funktioniert identisch ab **Odoo 16** und unterstützt sowohl die **Community-** als auch die **Enterprise-Edition**. Für eine andere Version ersetzt du in allen Befehlen `18` durch `16`, `17` oder `19` — `odoodev` kennt alle vier Versionen über sein internes Versions-Registry.

### Inhaltsverzeichnis

1. [Eingesetzte Softwaremodule](#1-eingesetzte-softwaremodule)
2. [Workflow-Überblick](#2-workflow-überblick)
3. [Odoo-Dev-Server einrichten](#3-odoo-dev-server-einrichten)
4. [Git-Repositories klonen](#4-git-repositories-klonen)
5. [Odoo-Backup einspielen](#5-odoo-backup-einspielen)
6. [Odoo-Server starten](#6-odoo-server-starten)
7. [Hello-World-Modul anlegen](#7-hello-world-modul-anlegen)
8. [Lokale Verifikation](#8-lokale-verifikation)
9. [Push und Merge-Request](#9-push-und-merge-request)
10. [Troubleshooting](#10-troubleshooting)

### 1. Eingesetzte Softwaremodule

Auf der Entwicklermaschine werden ausschließlich folgende Komponenten eingesetzt:

| Komponente | Version | Zweck |
|---|---|---|
| Betriebssystem | Ubuntu 22.04 LTS / 24.04 LTS, Debian 12 / 13 oder macOS 14+ | Host für die Entwicklungsumgebung |
| Odoo | 16 / 17 / 18 / 19 (Community oder Enterprise) — Beispiele in diesem Artikel: 18 Community | Entwickelte Plattform |
| Python | 3.13 | Odoo-Runtime |
| PostgreSQL-Server | 16.11 (im Docker-Container) | Lokale Entwicklungs-Datenbank |
| PostgreSQL-Client | libpq 16 (`psql`, `pg_dump`) | Datenbank-Operationen |
| Docker Engine | aktuelle Stable | PostgreSQL- und Mailpit-Container |
| Docker Compose | v2 | Service-Orchestrierung |
| UV | aktuelle Stable | Python-Paketmanager / venv |
| Git | aktuelle Stable | Versionskontrolle |
| wkhtmltopdf | 0.12.6 patched qt | PDF-Reports |
| `odoodev-equitania` | 0.4.51 | CLI für Dev-Umgebung |
| IDE | PyCharm Professional oder VS Code | Entwicklung |
| GitLab-Web-UI / `glab` | aktuelle Stable | Merge-Requests |

Versionen prüfen:

```bash
uname -a                          # Linux + macOS
uv --version
docker --version && docker compose version
python3 --version
psql --version
git --version
wkhtmltopdf --version
odoodev --version
```

### 2. Workflow-Überblick

Der gesamte Ablauf vom ersten Setup bis zum Merge-Request:

```
┌─────────────────────────────────────────────────────────────────┐
│ Entwicklermaschine: odoodev installieren                        │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. odoodev setup → globale Konfiguration                        │
│ 2. odoodev init 18 → .env, Docker, venv                         │
│ 3. odoodev repos 18 → Repos klonen + odoo.conf                  │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. odoodev docker up 18 → PostgreSQL + Mailpit                  │
│ 5. odoodev db restore → vorliegendes Odoo-Backup einspielen     │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. Hello-World-Modul im Feature-Branch anlegen                  │
│ 7. odoodev start 18 --dev -i eq_hello_world                     │
│ 8. Lokale Verifikation (Checklist)                              │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 9. git push                                                     │
│ 10. Merge-Request gegen develop                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3. Odoo-Dev-Server einrichten

#### 3.1 Voraussetzungen installieren

Bevor `odoodev` installiert werden kann, müssen UV und die übrigen System-Tools auf der Entwicklermaschine vorhanden sein.

**macOS:**

```bash
# UV installieren
brew install uv

# PostgreSQL-Client (libpq)
brew install libpq && brew link libpq --force

# Docker Desktop von https://www.docker.com/products/docker-desktop installieren
# wkhtmltopdf: .pkg-Installer von https://wkhtmltopdf.org/downloads.html
#   — Homebrew enthält keine patched-qt-Version
```

**Ubuntu / Debian:**

```bash
# UV installieren
curl -LsSf https://astral.sh/uv/install.sh | sh
exec $SHELL  # Shell neu laden, damit uv im PATH liegt

# PostgreSQL-Client + Docker + Git
sudo apt-get update
sudo apt-get install -y postgresql-client docker.io docker-compose-plugin git

# wkhtmltopdf: patched-qt-Version von https://wkhtmltopdf.org/downloads.html
#   — das apt-Paket enthält kein patched Qt
```

#### 3.2 odoodev installieren (einmalig)

```bash
uv tool install odoodev-equitania

# Updates später:
uv tool upgrade odoodev-equitania

# Versionsprüfung
odoodev --version
```

#### 3.3 Globale Konfiguration anlegen

```bash
odoodev setup
```

Der Wizard fragt 4 Punkte ab:

| Schritt | Frage | Empfehlung |
|---|---|---|
| 1 | Basisverzeichnis | `~/gitbase` |
| 2 | Aktive Odoo-Versionen | `18` |
| 3 | PostgreSQL-Benutzer + Passwort | `ownerp` / projektspezifisch |
| 4 | Bestätigung | — |

Die Konfiguration landet in `~/.config/odoodev/config.yaml`.

#### 3.4 Shell-Integration installieren

```bash
odoodev shell-setup
exec $SHELL  # Shell neu laden
```

Damit stehen `odoodev-activate <version>`, `odev` (Alias für `odoodev`) und `oda` (Alias für `odoodev-activate`) zur Verfügung — inklusive Tab-Completion.

#### 3.5 Versions-Umgebung initialisieren

```bash
odoodev init 18
```

Erzeugt:
- `~/gitbase/v18/v18-dev/dev18_native/.env` — DB-Ports, Credentials, Pfade
- `~/gitbase/v18/v18-dev/dev18_native/docker-compose.yml` — PostgreSQL + Mailpit
- `~/gitbase/v18/v18-dev/dev18_native/.venv/` — Python-venv via UV

#### 3.6 Konfigurationsdateien & Pfade

| Datei | Pfad |
|---|---|
| Globale Config | `~/.config/odoodev/config.yaml` |
| Versions-Override (optional) | `~/.config/odoodev/versions-override.yaml` |
| `.env` | `~/gitbase/v18/v18-dev/dev18_native/.env` |
| `docker-compose.yml` | `~/gitbase/v18/v18-dev/dev18_native/docker-compose.yml` |
| Odoo-Config-Template | `~/gitbase/v18/v18-dev/conf/odoo18_template.conf` |
| Generierte Odoo-Config | `~/gitbase/v18/myconfs/odoo_<JJMMTT>.conf` |
| `requirements.txt` | `~/gitbase/v18/v18-dev/dev18_native/requirements.txt` |
| `repos.yaml` | `~/gitbase/v18/v18-dev/scripts/repos.yaml` |

#### 3.7 Verwendete Ports (v18)

| Service | Port |
|---|---|
| PostgreSQL | `18432` |
| Odoo Web | `18069` |
| Odoo Gevent (Long-Polling) | `18072` |
| Mailpit Web-UI | `18025` |
| Mailpit SMTP | `1025` |

Komplette Port-Tabelle aller Versionen: siehe [`config.md`](config.md).

### 4. Git-Repositories klonen

#### 4.1 Relevante Repositories

| Repository | URL | Zielverzeichnis |
|---|---|---|
| Odoo Server | `git@gitlab.ownerp.io:v18/v18-server.git` | `~/gitbase/v18/v18-server/` |
| Equitania-Addons | `git@gitlab.ownerp.io:v18/v18-addons.git` | `~/gitbase/v18/v18-addons/` |
| Customer-Addons | `git@gitlab.ownerp.io:customer/v18-customer.git` | `~/gitbase/v18/v18-customer/` |

#### 4.2 Branch-Strategie auf der Entwicklermaschine

```
develop                    ─── Sammelbranch (Ziel deines Merge-Requests)
   ▲
   │ Merge-Request nach Code-Review
   │
feature/eq_hello_world     ─── dein Feature-Branch
```

| Branch | Zweck |
|---|---|
| `feature/<name>` | Lokale Entwicklung |
| `develop` | Sammelbranch — hier landet deine Arbeit per Merge-Request |

#### 4.3 Wie `repos.yaml` und `odoo18_template.conf` zusammenarbeiten

`odoodev repos 18` macht zwei Dinge in einem Schritt: Repositories klonen **und** die Odoo-Konfigurationsdatei `~/gitbase/v18/myconfs/odoo_<JJMMTT>.conf` generieren. Diese Datei wird beim `odoodev start 18` automatisch an `odoo-bin -c <pfad>` übergeben. Die `docker-compose.yml` ist davon nicht betroffen — sie startet nur PostgreSQL (und optional Mailpit). Der Odoo-Server läuft nativ auf deiner Maschine.

##### Datenfluss

```
┌─────────────────────────────────┐    ┌─────────────────────────────────┐
│ vXX-dev/scripts/repos.yaml      │    │ vXX-dev/conf/odoo18_template.   │
│ (Strukturdefinition)            │    │   conf (Skelett-Config)         │
│ - paths.base / template /       │    │ - db_host, db_port, db_user     │
│   config_dir                    │    │ - addons_path =                 │
│ - base_addons                   │    │ - data_dir, logfile, …          │
│ - addons[] (key, path, section, │    │ - Platzhalter ${DEV_USER}       │
│   use, suffix)                  │    │                                 │
└────────────────┬────────────────┘    └────────────────┬────────────────┘
                 │                                      │
                 └──────────────┬───────────────────────┘
                                ▼
                  ┌──────────────────────────┐
                  │ odoodev repos 18         │
                  │  - klont alle Repos      │
                  │  - sammelt addons_path   │
                  │  - ersetzt Platzhalter   │
                  └────────────┬─────────────┘
                               ▼
              ~/gitbase/v18/myconfs/odoo_<JJMMTT>.conf
                               ▼
                       odoodev start 18
                               ▼
                    odoo-bin -c <jüngste conf>
```

##### Pflichtfelder in `repos.yaml`

Die Datei liegt unter `~/gitbase/v18/v18-dev/scripts/repos.yaml` und steuert die Generierung:

```yaml
version: "18"
branch: "develop"
ssh_key: "~/.ssh/id_rsa"

paths:
  base:        ~/gitbase/v18                                    # Wurzel aller geklonten Repos
  template:    ~/gitbase/v18/v18-dev/conf/odoo18_template.conf  # Quelle für die Generierung
  config_dir:  ~/gitbase/v18/myconfs                            # Zielordner der odoo_<JJMMTT>.conf

# Odoo-Core-Pfade (immer zuerst im addons_path)
base_addons:
  - $HOME/gitbase/v18/v18-server/odoo/addons
  - $HOME/gitbase/v18/v18-server/addons

# Eigene Repositories
addons:
  - key:     v18-addons
    path:    v18-addons              # relativ zu paths.base → ~/gitbase/v18/v18-addons
    git_url: git@gitlab.ownerp.io:v18/v18-addons.git
    section: Equitania               # Sektions-Überschrift in der generierten conf
    use:     true                    # false → Pfad als Kommentar im addons_path
    suffix:  ""                      # optional: Unter-Verzeichnis (z. B. "addons" bei OCA-Repos)

  - key:     v18-oca-server-tools
    path:    v18-oca/server-tools
    git_url: https://github.com/OCA/server-tools.git
    section: OCA
    use:     true
    suffix:  ""

# Beispiel Enterprise (nur falls Lizenz vorhanden)
  - key:     v18-enterprise
    path:    v18-enterprise
    git_url: git@gitlab.ownerp.io:v18/v18-enterprise.git
    section: Enterprise
    use:     true

customers:
  - key:     v18-customer
    path:    v18-customer
    git_url: git@gitlab.ownerp.io:customer/v18-customer.git
    section: Customer
    use:     false                   # erst aktivieren, wenn Kundenprojekt anliegt
```

##### Wie die Felder im `addons_path` landen

Reihenfolge der Sektionen in der generierten Config: `Odoo` (Core via `base_addons`) → die Sektionen aus `addons[]`/`customers[]` in der Reihenfolge ihres ersten Auftretens. Aus dem Beispiel oben wird:

```ini
addons_path =
    # Generated on YYYY-MM-DD HH:MM:SS
    /home/entwickler/gitbase/v18/v18-server/odoo/addons,
    /home/entwickler/gitbase/v18/v18-server/addons,
    # Equitania
    /home/entwickler/gitbase/v18/v18-addons,
    # OCA
    /home/entwickler/gitbase/v18/v18-oca/server-tools,
    # Enterprise
    /home/entwickler/gitbase/v18/v18-enterprise,
    # Customer
    # /home/entwickler/gitbase/v18/v18-customer,
```

Beachten:
- Der auskommentierte Customer-Pfad zeigt, was `use: false` macht — der Pfad bleibt sichtbar dokumentiert, wird aber nicht geladen.
- `suffix` wird an `path` angehängt — z. B. `path: v18-oca/server-tools` mit `suffix: addons` ergibt `~/gitbase/v18/v18-oca/server-tools/addons`. Praktisch für Repos, die ihren Modul-Code in einem Unterordner halten.

##### Was im Template ersetzt wird

`odoodev` ersetzt im `odoo18_template.conf` exakt diese Stellen:

| Im Template steht | Wird ersetzt durch |
|---|---|
| `addons_path = ` (leer oder mit Beispielen) | sektioniert generierte Liste aus `repos.yaml` |
| `${DEV_USER}` | aktueller Username (für Pfade wie `data_dir`, `logfile`) |
| `db_host = dev-db-18` *(Docker-Default)* | `localhost` (native) |
| `db_port = 5432` | `18432` (aus `versions.yaml` für v18) |
| `db_user`, `db_password`, `admin_passwd` | aus `~/.config/odoodev/config.yaml` (nur wenn dort gesetzt) |
| `$HOME` | absoluter Home-Pfad (native) |

Der Rest des Templates (Logging, Workers, Mail-SMTP-Server, Performance-Tuning) bleibt unverändert. Wenn du also einen neuen Default brauchst (z. B. `limit_time_cpu = 600`), trägst du das einmal im Template ein — bei jedem `odoodev repos 18` wird er mitgenommen.

##### Generierte Config prüfen

```bash
ls -lt ~/gitbase/v18/myconfs/                 # neueste odoo_*.conf finden
cat   ~/gitbase/v18/myconfs/odoo_$(date +%y%m%d).conf | head -40
```

##### Wann die Config neu generieren?

Immer wenn sich die Pfad-/Modul-Struktur ändert:

| Auslöser | Befehl |
|---|---|
| Neues Add-on-Repo in `repos.yaml` aufgenommen | `odoodev repos 18` |
| `use:` von `false` auf `true` umgeschaltet (oder umgekehrt) | `odoodev repos 18 --config-only` |
| Nur Template (`odoo18_template.conf`) verändert | `odoodev repos 18 --config-only` |
| Nur Code-Updates ziehen, keine Pfadänderung | `odoodev pull 18` *(generiert keine neue conf)* |

#### 4.4 Klonen via odoodev

`odoodev` klont alle in `repos.yaml` definierten Repos in einem Schritt:

```bash
odoodev repos 18
```

Das macht:
1. SSH-Key aus `repos.yaml` (Feld `ssh_key`) verwenden
2. Server-Repo + alle Addon-Repos klonen
3. Auf den in `repos.yaml` konfigurierten Branch (`develop`) wechseln
4. `~/gitbase/v18/myconfs/odoo_<JJMMTT>.conf` mit korrektem `addons_path` generieren

#### 4.5 Updates: Schneller Pull

```bash
odoodev pull 18
```

Nutzt `git pull --ff-only` und schlägt bei divergierenden Branches mit klarem Hinweis fehl — kein versehentlicher Merge-Commit. Details zur `repos.yaml`: siehe [`repos.md`](repos.md).

### 5. Odoo-Backup einspielen

Du hast ein Odoo-Backup (ZIP-Export aus dem Datenbank-Manager oder per `odoodev db backup` erzeugt). Lege es lokal ab und spiele es ein.

**Voraussetzungen:** `odoodev` ist installiert (Abschnitt 3), die Repositories sind geklont (Abschnitt 4), und der PostgreSQL-Container läuft.

| Element | Wert |
|---|---|
| Lokales Verzeichnis | `~/odoo-share/backups/` |
| Backup-Format | ZIP (Standard-Odoo-Backup, enthält SQL + Filestore) |
| Ziel-Datenbankname | `v18_devcopy` |

```bash
mkdir -p ~/odoo-share/backups/

# Backup an seinen Platz legen (z. B. per scp, rsync, manuelles Kopieren)
ls -lh ~/odoo-share/backups/

# PostgreSQL-Container starten (falls noch nicht aktiv)
odoodev docker up 18

# Restore über odoodev
odoodev db restore 18 -n v18_devcopy -z ~/odoo-share/backups/<dateiname>.zip
```

`odoodev db restore` deaktiviert nach dem Restore automatisch:
- alle Cron-Jobs (`ir_cron.active = false`)
- ausgehende Mail-Server (`ir_mail_server.active = false`)
- Fetchmail-Server, Nextcloud-, Office365-Konfiguration

So ist sichergestellt, dass aus deiner Dev-Kopie keine Mails oder Cloud-Aktionen gegen Fremdsysteme laufen. Weitere Backup-Formate (7z, tar, gz, SQL) und Optionen: siehe [`db.md`](db.md).

### 6. Odoo-Server starten

#### 6.1 Erststart

```bash
# In das Versionsverzeichnis wechseln (oder oda 18 verwenden)
cd ~/gitbase/v18/v18-dev/dev18_native

# PostgreSQL + Mailpit starten
odoodev docker up 18

# Odoo im Entwicklungsmodus starten (Hot-Reload)
odoodev start 18 --dev
```

Odoo ist anschließend erreichbar unter <http://127.0.0.1:18069>.

#### 6.2 Typische Startoptionen

```bash
# Datenbank wählen
odoodev start 18 --dev -d v18_devcopy

# Modul installieren
odoodev start 18 --dev -d v18_devcopy -i eq_hello_world

# Modul aktualisieren
odoodev start 18 --dev -d v18_devcopy -u eq_hello_world

# Mehrere Module gleichzeitig aktualisieren
odoodev start 18 --dev -d v18_devcopy -u eq_hello_world,sale,account

# Mit TUI (Live-Log mit Filter, Search, Clipboard-Copy)
odoodev start 18 --dev --tui -d v18_devcopy

# Tests ausführen
odoodev start 18 --test -d v18_test -i eq_hello_world

# Auf allen Interfaces binden (für VM-Zugriff)
odoodev start 18 --dev --host 0.0.0.0
```

#### 6.3 Stoppen

```bash
odoodev stop 18              # Odoo + Docker stoppen
odoodev stop 18 --keep-docker  # nur Odoo, Docker weiterlaufen lassen
```

Vollständige Optionsliste: siehe [`start.md`](start.md).

### 7. Hello-World-Modul anlegen

#### 7.1 Feature-Branch erstellen

```bash
cd ~/gitbase/v18/v18-addons/
git checkout develop
git pull --ff-only
git checkout -b feature/eq_hello_world
```

#### 7.2 Modulstruktur

```
~/gitbase/v18/v18-addons/eq_hello_world/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   └── hello_world.py
├── security/
│   └── ir.model.access.csv
└── views/
    └── hello_world_views.xml
```

#### 7.3 Dateien

**`__manifest__.py`**

```python
{
    "name": "Hello World",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "summary": "Minimal Hello-World example module",
    "author": "Equitania Software GmbH",
    "website": "https://www.equitania.de",
    "license": "AGPL-3",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "views/hello_world_views.xml",
    ],
    "installable": True,
    "application": True,
}
```

**`__init__.py`**

```python
from . import models
```

**`models/__init__.py`**

```python
from . import hello_world
```

**`models/hello_world.py`**

```python
from odoo import fields, models


class HelloWorld(models.Model):
    _name = "eq.hello.world"
    _description = "Hello World Entry"

    name = fields.Char(string="Name", required=True)
    message = fields.Text(string="Message", default="Hello, World!")
```

**`security/ir.model.access.csv`**

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_eq_hello_world_user,eq.hello.world.user,model_eq_hello_world,base.group_user,1,1,1,1
```

**`views/hello_world_views.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_eq_hello_world_list" model="ir.ui.view">
        <field name="name">eq.hello.world.list</field>
        <field name="model">eq.hello.world</field>
        <field name="arch" type="xml">
            <list string="Hello World">
                <field name="name"/>
                <field name="message"/>
            </list>
        </field>
    </record>

    <record id="view_eq_hello_world_form" model="ir.ui.view">
        <field name="name">eq.hello.world.form</field>
        <field name="model">eq.hello.world</field>
        <field name="arch" type="xml">
            <form string="Hello World">
                <sheet>
                    <group>
                        <field name="name"/>
                        <field name="message"/>
                    </group>
                </sheet>
            </form>
        </field>
    </record>

    <record id="action_eq_hello_world" model="ir.actions.act_window">
        <field name="name">Hello World</field>
        <field name="res_model">eq.hello.world</field>
        <field name="view_mode">list,form</field>
    </record>

    <menuitem id="menu_eq_hello_world_root"
              name="Hello World"
              sequence="100"/>
    <menuitem id="menu_eq_hello_world"
              name="Entries"
              parent="menu_eq_hello_world_root"
              action="action_eq_hello_world"
              sequence="10"/>
</odoo>
```

#### 7.4 Modul installieren

```bash
# Konfiguration neu generieren (eq_hello_world muss in addons_path landen)
odoodev repos 18 --config-only

# Modul installieren
odoodev start 18 --dev -d v18_devcopy -i eq_hello_world
```

#### 7.5 Commit

```bash
cd ~/gitbase/v18/v18-addons/
git add eq_hello_world/
git commit -m "[ADD] eq_hello_world: minimal Hello-World example module"
```

Commit-Prefix-Konvention: `[ADD]` neue Features, `[CHG]` Änderungen, `[FIX]` Bugfixes.

### 8. Lokale Verifikation

Nach `odoodev start 18 --dev -d v18_devcopy -i eq_hello_world` im Browser unter <http://127.0.0.1:18069> einloggen und folgende Punkte abhaken:

- [ ] Login auf der lokalen Datenbank `v18_devcopy` funktioniert
- [ ] Modul `eq_hello_world` ist im Apps-Menü installiert (Apps → Suche)
- [ ] Hauptmenü **Hello World** ist sichtbar
- [ ] Untermenü **Entries** öffnet die Listenansicht
- [ ] Neuer Eintrag kann angelegt, gespeichert und wieder gelöscht werden
- [ ] Default-Wert „Hello, World!" steht im Feld `message`
- [ ] Keine Fehler im Odoo-Log (Konsole oder TUI)
- [ ] Ein zweiter Start mit `-u eq_hello_world` läuft sauber durch (Modul-Update funktioniert)

### 9. Push und Merge-Request

#### 9.1 Push

```bash
git push -u origin feature/eq_hello_world
```

#### 9.2 Merge-Request anlegen

In der GitLab-UI:

1. Merge-Request erstellen unter `https://gitlab.ownerp.io/v18/v18-addons/-/merge_requests/new`
2. Source: `feature/eq_hello_world` → Target: `develop`
3. Beschreibung mit Bezug zum Ticket (`Closes #<id>`)
4. Reviewer setzen
5. Pipeline läuft automatisch (Lint, Test, Build)

Damit endet der Entwickler-Workflow. Die Promotion auf weitere Stages erfolgt anschließend durch das Operations-Team.

### 10. Troubleshooting

| Symptom | Ursache | Lösung |
|---|---|---|
| `odoodev: command not found` | UV-Tools nicht im PATH | `uv tool update-shell` oder Shell neu laden |
| `[ERROR] PostgreSQL port 18432 not reachable` | Docker nicht gestartet | `odoodev docker up 18` |
| `[ERROR] No odoo-bin found` | Server-Repo fehlt | `odoodev repos 18 --server-only` |
| `[ERROR] requirements.txt changed` | Abhängigkeiten geändert | `odoodev venv setup 18 --force` |
| Modul nicht in Apps-Liste sichtbar | Apps-Liste nicht aktualisiert | In Odoo: **Apps → Update Apps List** oder `odoodev start 18 --dev -u base` |
| Modul-Code-Änderung wird nicht übernommen | Kein Dev-Modus oder Modul nicht aktualisiert | `odoodev start 18 --dev -u eq_hello_world` |
| `git pull --ff-only` schlägt fehl | Lokaler Branch ist divergiert | `git -C <repo> pull --rebase` (nach Rücksprache) |
| `wkhtmltopdf` erzeugt fehlerhafte PDFs | Keine patched-qt-Version installiert | `.pkg`-Installer (macOS) bzw. patched-qt-Build (Linux) von <https://wkhtmltopdf.org/downloads.html> verwenden |

### Definition of Done

- [ ] Wiki-Artikel im GitLab-Wiki des Projekts veröffentlicht
- [ ] Ein neuer Entwickler hat den Artikel von oben nach unten durchgearbeitet und das Hello-World-Modul lokal lauffähig sowie als Merge-Request gegen `develop` eingereicht
- [ ] Review durch das Team erfolgt und freigegeben

### Referenzen

| Thema | Datei |
|---|---|
| odoodev-Installation, Setup-Wizard | [`setup.md`](setup.md) |
| Konfiguration & Versionen | [`config.md`](config.md) |
| Repository-Management & `repos.yaml` | [`repos.md`](repos.md) |
| Server starten/stoppen, alle Modi | [`start.md`](start.md) |
| Datenbank-Operationen, Backup-Formate | [`db.md`](db.md) |
| Docker-Services | [`docker.md`](docker.md) |
| Virtual-Environment-Verwaltung | [`venv.md`](venv.md) |
| Shell-Integration & Completions | [`shell.md`](shell.md) |
| Migrationsmodus (versionsübergreifend) | [`migrate.md`](migrate.md) |
| Playbook-Automation (`run`) | [`run.md`](run.md) |

### Quellcode

`odoodev` ist Open Source und wird auf GitHub entwickelt:

<https://github.com/equitania/odoo-dev>

Issues, Feature-Requests und Pull-Requests sind willkommen.

---

## English Documentation

> **Purpose of this article:** Work through this wiki article from top to bottom and you will have a working Hello-World module on your local development machine, submitted as a merge request against the `develop` branch.
>
> **Common thread:** You build the module `eq_hello_world` — a minimal Odoo module with a menu entry, model, and list/form view — from the initial setup all the way to the merge request.
>
> **Scope:** Examples and paths refer to Odoo 18. The entire workflow works the same way starting from **Odoo 16** and supports both the **Community** and the **Enterprise** edition. For a different version, replace `18` with `16`, `17`, or `19` in every command — `odoodev` knows all four versions through its internal version registry.

### Table of Contents

1. [Software Components in Use](#1-software-components-in-use)
2. [Workflow Overview](#2-workflow-overview)
3. [Setting Up the Odoo Dev Server](#3-setting-up-the-odoo-dev-server)
4. [Cloning Git Repositories](#4-cloning-git-repositories)
5. [Restoring an Odoo Backup](#5-restoring-an-odoo-backup)
6. [Starting the Odoo Server](#6-starting-the-odoo-server)
7. [Creating the Hello-World Module](#7-creating-the-hello-world-module)
8. [Local Verification](#8-local-verification)
9. [Push and Merge Request](#9-push-and-merge-request)
10. [Troubleshooting](#10-troubleshooting-1)

### 1. Software Components in Use

The development machine runs exclusively the following components:

| Component | Version | Purpose |
|---|---|---|
| Operating System | Ubuntu 22.04 LTS / 24.04 LTS, Debian 12 / 13 or macOS 14+ | Host for the development environment |
| Odoo | 16 / 17 / 18 / 19 (Community or Enterprise) — examples in this article: 18 Community | The platform being developed |
| Python | 3.13 | Odoo runtime |
| PostgreSQL Server | 16.11 (in Docker container) | Local development database |
| PostgreSQL Client | libpq 16 (`psql`, `pg_dump`) | Database operations |
| Docker Engine | current stable | PostgreSQL and Mailpit containers |
| Docker Compose | v2 | Service orchestration |
| UV | current stable | Python package manager / venv |
| Git | current stable | Version control |
| wkhtmltopdf | 0.12.6 patched qt | PDF reports |
| `odoodev-equitania` | 0.4.51 | CLI for the dev environment |
| IDE | PyCharm Professional or VS Code | Development |
| GitLab Web UI / `glab` | current stable | Merge requests |

Verify versions:

```bash
uname -a                          # Linux + macOS
uv --version
docker --version && docker compose version
python3 --version
psql --version
git --version
wkhtmltopdf --version
odoodev --version
```

### 2. Workflow Overview

End-to-end flow from the initial setup to the merge request:

```
┌─────────────────────────────────────────────────────────────────┐
│ Development machine: install odoodev                            │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 1. odoodev setup → global configuration                         │
│ 2. odoodev init 18 → .env, Docker, venv                         │
│ 3. odoodev repos 18 → clone repos + odoo.conf                   │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 4. odoodev docker up 18 → PostgreSQL + Mailpit                  │
│ 5. odoodev db restore → import existing Odoo backup             │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 6. Create the Hello-World module on a feature branch            │
│ 7. odoodev start 18 --dev -i eq_hello_world                     │
│ 8. Local verification (checklist)                               │
└──────────────────────────────┬──────────────────────────────────┘
                               ▼
┌─────────────────────────────────────────────────────────────────┐
│ 9. git push                                                     │
│ 10. Merge request against develop                               │
└─────────────────────────────────────────────────────────────────┘
```

### 3. Setting Up the Odoo Dev Server

#### 3.1 Install prerequisites

Before `odoodev` can be installed, UV and the remaining system tools must be present on the development machine.

**macOS:**

```bash
# Install UV
brew install uv

# PostgreSQL client (libpq)
brew install libpq && brew link libpq --force

# Install Docker Desktop from https://www.docker.com/products/docker-desktop
# wkhtmltopdf: .pkg installer from https://wkhtmltopdf.org/downloads.html
#   — Homebrew does not ship a patched-qt build
```

**Ubuntu / Debian:**

```bash
# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh
exec $SHELL  # reload shell so uv is on PATH

# PostgreSQL client + Docker + Git
sudo apt-get update
sudo apt-get install -y postgresql-client docker.io docker-compose-plugin git

# wkhtmltopdf: patched-qt build from https://wkhtmltopdf.org/downloads.html
#   — the apt package lacks patched Qt
```

#### 3.2 Install odoodev (one-time)

```bash
uv tool install odoodev-equitania

# Later upgrades:
uv tool upgrade odoodev-equitania

# Version check
odoodev --version
```

#### 3.3 Create the global configuration

```bash
odoodev setup
```

The wizard asks for four items:

| Step | Question | Recommendation |
|---|---|---|
| 1 | Base directory | `~/gitbase` |
| 2 | Active Odoo versions | `18` |
| 3 | PostgreSQL user + password | `ownerp` / project-specific |
| 4 | Confirmation | — |

The configuration is stored in `~/.config/odoodev/config.yaml`.

#### 3.4 Install the shell integration

```bash
odoodev shell-setup
exec $SHELL  # reload shell
```

This provides `odoodev-activate <version>`, `odev` (alias for `odoodev`) and `oda` (alias for `odoodev-activate`), including tab completion.

#### 3.5 Initialize the version environment

```bash
odoodev init 18
```

Creates:
- `~/gitbase/v18/v18-dev/dev18_native/.env` — DB ports, credentials, paths
- `~/gitbase/v18/v18-dev/dev18_native/docker-compose.yml` — PostgreSQL + Mailpit
- `~/gitbase/v18/v18-dev/dev18_native/.venv/` — Python venv via UV

#### 3.6 Configuration files & paths

| File | Path |
|---|---|
| Global config | `~/.config/odoodev/config.yaml` |
| Versions override (optional) | `~/.config/odoodev/versions-override.yaml` |
| `.env` | `~/gitbase/v18/v18-dev/dev18_native/.env` |
| `docker-compose.yml` | `~/gitbase/v18/v18-dev/dev18_native/docker-compose.yml` |
| Odoo config template | `~/gitbase/v18/v18-dev/conf/odoo18_template.conf` |
| Generated Odoo config | `~/gitbase/v18/myconfs/odoo_<YYMMDD>.conf` |
| `requirements.txt` | `~/gitbase/v18/v18-dev/dev18_native/requirements.txt` |
| `repos.yaml` | `~/gitbase/v18/v18-dev/scripts/repos.yaml` |

#### 3.7 Ports in use (v18)

| Service | Port |
|---|---|
| PostgreSQL | `18432` |
| Odoo Web | `18069` |
| Odoo Gevent (long polling) | `18072` |
| Mailpit Web UI | `18025` |
| Mailpit SMTP | `1025` |

Full port table for all versions: see [`config.md`](config.md).

### 4. Cloning Git Repositories

#### 4.1 Relevant repositories

| Repository | URL | Target directory |
|---|---|---|
| Odoo server | `git@gitlab.ownerp.io:v18/v18-server.git` | `~/gitbase/v18/v18-server/` |
| Equitania add-ons | `git@gitlab.ownerp.io:v18/v18-addons.git` | `~/gitbase/v18/v18-addons/` |
| Customer add-ons | `git@gitlab.ownerp.io:customer/v18-customer.git` | `~/gitbase/v18/v18-customer/` |

#### 4.2 Branch strategy on the development machine

```
develop                    ─── collection branch (target of your merge request)
   ▲
   │ merge request after code review
   │
feature/eq_hello_world     ─── your feature branch
```

| Branch | Purpose |
|---|---|
| `feature/<name>` | Local development |
| `develop` | Collection branch — your work lands here via merge request |

#### 4.3 How `repos.yaml` and `odoo18_template.conf` work together

`odoodev repos 18` does two things in one step: it clones the repositories **and** generates the Odoo configuration file `~/gitbase/v18/myconfs/odoo_<YYMMDD>.conf`. That file is automatically passed to `odoo-bin -c <path>` whenever you run `odoodev start 18`. The `docker-compose.yml` is not involved here — it only starts PostgreSQL (and optionally Mailpit). The Odoo server itself runs natively on your machine.

##### Data flow

```
┌─────────────────────────────────┐    ┌─────────────────────────────────┐
│ vXX-dev/scripts/repos.yaml      │    │ vXX-dev/conf/odoo18_template.   │
│ (structure definition)          │    │   conf (skeleton config)        │
│ - paths.base / template /       │    │ - db_host, db_port, db_user     │
│   config_dir                    │    │ - addons_path =                 │
│ - base_addons                   │    │ - data_dir, logfile, …          │
│ - addons[] (key, path, section, │    │ - placeholder ${DEV_USER}       │
│   use, suffix)                  │    │                                 │
└────────────────┬────────────────┘    └────────────────┬────────────────┘
                 │                                      │
                 └──────────────┬───────────────────────┘
                                ▼
                  ┌──────────────────────────┐
                  │ odoodev repos 18         │
                  │  - clones all repos      │
                  │  - assembles addons_path │
                  │  - replaces placeholders │
                  └────────────┬─────────────┘
                               ▼
              ~/gitbase/v18/myconfs/odoo_<YYMMDD>.conf
                               ▼
                       odoodev start 18
                               ▼
                    odoo-bin -c <latest conf>
```

##### Mandatory fields in `repos.yaml`

The file lives at `~/gitbase/v18/v18-dev/scripts/repos.yaml` and drives the generation:

```yaml
version: "18"
branch: "develop"
ssh_key: "~/.ssh/id_rsa"

paths:
  base:        ~/gitbase/v18                                    # Root of all cloned repos
  template:    ~/gitbase/v18/v18-dev/conf/odoo18_template.conf  # Source for generation
  config_dir:  ~/gitbase/v18/myconfs                            # Target dir for odoo_<YYMMDD>.conf

# Odoo core paths (always first in addons_path)
base_addons:
  - $HOME/gitbase/v18/v18-server/odoo/addons
  - $HOME/gitbase/v18/v18-server/addons

# Your repositories
addons:
  - key:     v18-addons
    path:    v18-addons              # relative to paths.base → ~/gitbase/v18/v18-addons
    git_url: git@gitlab.ownerp.io:v18/v18-addons.git
    section: Equitania               # section heading in the generated conf
    use:     true                    # false → path appears as comment in addons_path
    suffix:  ""                      # optional: subdirectory (e.g. "addons" for OCA repos)

  - key:     v18-oca-server-tools
    path:    v18-oca/server-tools
    git_url: https://github.com/OCA/server-tools.git
    section: OCA
    use:     true
    suffix:  ""

# Enterprise example (only when license available)
  - key:     v18-enterprise
    path:    v18-enterprise
    git_url: git@gitlab.ownerp.io:v18/v18-enterprise.git
    section: Enterprise
    use:     true

customers:
  - key:     v18-customer
    path:    v18-customer
    git_url: git@gitlab.ownerp.io:customer/v18-customer.git
    section: Customer
    use:     false                   # enable once a customer project starts
```

##### How the fields turn into `addons_path`

Section order in the generated config: `Odoo` (core via `base_addons`) → the sections from `addons[]`/`customers[]` in their order of first appearance. From the example above you get:

```ini
addons_path =
    # Generated on YYYY-MM-DD HH:MM:SS
    /home/developer/gitbase/v18/v18-server/odoo/addons,
    /home/developer/gitbase/v18/v18-server/addons,
    # Equitania
    /home/developer/gitbase/v18/v18-addons,
    # OCA
    /home/developer/gitbase/v18/v18-oca/server-tools,
    # Enterprise
    /home/developer/gitbase/v18/v18-enterprise,
    # Customer
    # /home/developer/gitbase/v18/v18-customer,
```

Notes:
- The commented-out customer path shows what `use: false` does — the path stays visible as documentation but is not loaded.
- `suffix` is appended to `path` — e.g. `path: v18-oca/server-tools` with `suffix: addons` becomes `~/gitbase/v18/v18-oca/server-tools/addons`. Useful for repositories that keep their module code in a sub-folder.

##### What gets replaced in the template

`odoodev` replaces exactly these spots in `odoo18_template.conf`:

| Template placeholder | Replaced by |
|---|---|
| `addons_path = ` (empty or with samples) | sectioned list generated from `repos.yaml` |
| `${DEV_USER}` | current username (for paths like `data_dir`, `logfile`) |
| `db_host = dev-db-18` *(Docker default)* | `localhost` (native) |
| `db_port = 5432` | `18432` (from `versions.yaml` for v18) |
| `db_user`, `db_password`, `admin_passwd` | from `~/.config/odoodev/config.yaml` (only if set there) |
| `$HOME` | absolute home path (native) |

Everything else in the template (logging, workers, mail SMTP, performance tuning) is preserved. So if you need a new default (e.g. `limit_time_cpu = 600`), you set it once in the template — every `odoodev repos 18` will pick it up.

##### Inspect the generated config

```bash
ls -lt ~/gitbase/v18/myconfs/                 # find the latest odoo_*.conf
cat   ~/gitbase/v18/myconfs/odoo_$(date +%y%m%d).conf | head -40
```

##### When to regenerate the config

Whenever the path or module structure changes:

| Trigger | Command |
|---|---|
| New add-on repo added to `repos.yaml` | `odoodev repos 18` |
| Toggled `use:` from `false` to `true` (or back) | `odoodev repos 18 --config-only` |
| Only the template (`odoo18_template.conf`) was changed | `odoodev repos 18 --config-only` |
| Just pulling code updates, no path changes | `odoodev pull 18` *(does not generate a new conf)* |

#### 4.4 Cloning via odoodev

`odoodev` clones every repo defined in `repos.yaml` in a single step:

```bash
odoodev repos 18
```

It performs:
1. Use the SSH key from `repos.yaml` (field `ssh_key`)
2. Clone the server repo and all add-on repos
3. Switch to the branch configured in `repos.yaml` (`develop`)
4. Generate `~/gitbase/v18/myconfs/odoo_<YYMMDD>.conf` with the correct `addons_path`

#### 4.5 Updates: quick pull

```bash
odoodev pull 18
```

Uses `git pull --ff-only` and fails on diverged branches with a clear hint — no accidental merge commits. Details on `repos.yaml`: see [`repos.md`](repos.md).

### 5. Restoring an Odoo Backup

You have an Odoo backup (a ZIP export from the database manager or produced via `odoodev db backup`). Place it locally and restore it.

**Prerequisites:** `odoodev` is installed (section 3), the repositories are cloned (section 4), and the PostgreSQL container is running.

| Item | Value |
|---|---|
| Local directory | `~/odoo-share/backups/` |
| Backup format | ZIP (standard Odoo backup, contains SQL + filestore) |
| Target database name | `v18_devcopy` |

```bash
mkdir -p ~/odoo-share/backups/

# Place the backup file (e.g. via scp, rsync, manual copy)
ls -lh ~/odoo-share/backups/

# Start the PostgreSQL container (if not already running)
odoodev docker up 18

# Restore via odoodev
odoodev db restore 18 -n v18_devcopy -z ~/odoo-share/backups/<filename>.zip
```

After the restore, `odoodev db restore` automatically deactivates:
- all cron jobs (`ir_cron.active = false`)
- outgoing mail servers (`ir_mail_server.active = false`)
- fetchmail servers, Nextcloud and Office365 configuration

This guarantees that your dev copy cannot trigger mails or cloud actions against external systems. Other backup formats (7z, tar, gz, SQL) and options: see [`db.md`](db.md).

### 6. Starting the Odoo Server

#### 6.1 First start

```bash
# Switch to the version directory (or use oda 18)
cd ~/gitbase/v18/v18-dev/dev18_native

# Start PostgreSQL + Mailpit
odoodev docker up 18

# Start Odoo in dev mode (hot reload)
odoodev start 18 --dev
```

Odoo is then available at <http://127.0.0.1:18069>.

#### 6.2 Common start options

```bash
# Choose database
odoodev start 18 --dev -d v18_devcopy

# Install module
odoodev start 18 --dev -d v18_devcopy -i eq_hello_world

# Update module
odoodev start 18 --dev -d v18_devcopy -u eq_hello_world

# Update multiple modules at once
odoodev start 18 --dev -d v18_devcopy -u eq_hello_world,sale,account

# With TUI (live log with filter, search, clipboard copy)
odoodev start 18 --dev --tui -d v18_devcopy

# Run tests
odoodev start 18 --test -d v18_test -i eq_hello_world

# Bind on all interfaces (for VM access)
odoodev start 18 --dev --host 0.0.0.0
```

#### 6.3 Stopping

```bash
odoodev stop 18              # stop Odoo + Docker
odoodev stop 18 --keep-docker  # only Odoo, keep Docker running
```

Full option list: see [`start.md`](start.md).

### 7. Creating the Hello-World Module

#### 7.1 Create the feature branch

```bash
cd ~/gitbase/v18/v18-addons/
git checkout develop
git pull --ff-only
git checkout -b feature/eq_hello_world
```

#### 7.2 Module structure

```
~/gitbase/v18/v18-addons/eq_hello_world/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   └── hello_world.py
├── security/
│   └── ir.model.access.csv
└── views/
    └── hello_world_views.xml
```

#### 7.3 Files

**`__manifest__.py`**

```python
{
    "name": "Hello World",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "summary": "Minimal Hello-World example module",
    "author": "Equitania Software GmbH",
    "website": "https://www.equitania.de",
    "license": "AGPL-3",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "views/hello_world_views.xml",
    ],
    "installable": True,
    "application": True,
}
```

**`__init__.py`**

```python
from . import models
```

**`models/__init__.py`**

```python
from . import hello_world
```

**`models/hello_world.py`**

```python
from odoo import fields, models


class HelloWorld(models.Model):
    _name = "eq.hello.world"
    _description = "Hello World Entry"

    name = fields.Char(string="Name", required=True)
    message = fields.Text(string="Message", default="Hello, World!")
```

**`security/ir.model.access.csv`**

```csv
id,name,model_id:id,group_id:id,perm_read,perm_write,perm_create,perm_unlink
access_eq_hello_world_user,eq.hello.world.user,model_eq_hello_world,base.group_user,1,1,1,1
```

**`views/hello_world_views.xml`**

```xml
<?xml version="1.0" encoding="utf-8"?>
<odoo>
    <record id="view_eq_hello_world_list" model="ir.ui.view">
        <field name="name">eq.hello.world.list</field>
        <field name="model">eq.hello.world</field>
        <field name="arch" type="xml">
            <list string="Hello World">
                <field name="name"/>
                <field name="message"/>
            </list>
        </field>
    </record>

    <record id="view_eq_hello_world_form" model="ir.ui.view">
        <field name="name">eq.hello.world.form</field>
        <field name="model">eq.hello.world</field>
        <field name="arch" type="xml">
            <form string="Hello World">
                <sheet>
                    <group>
                        <field name="name"/>
                        <field name="message"/>
                    </group>
                </sheet>
            </form>
        </field>
    </record>

    <record id="action_eq_hello_world" model="ir.actions.act_window">
        <field name="name">Hello World</field>
        <field name="res_model">eq.hello.world</field>
        <field name="view_mode">list,form</field>
    </record>

    <menuitem id="menu_eq_hello_world_root"
              name="Hello World"
              sequence="100"/>
    <menuitem id="menu_eq_hello_world"
              name="Entries"
              parent="menu_eq_hello_world_root"
              action="action_eq_hello_world"
              sequence="10"/>
</odoo>
```

#### 7.4 Install the module

```bash
# Regenerate config (eq_hello_world must end up in addons_path)
odoodev repos 18 --config-only

# Install module
odoodev start 18 --dev -d v18_devcopy -i eq_hello_world
```

#### 7.5 Commit

```bash
cd ~/gitbase/v18/v18-addons/
git add eq_hello_world/
git commit -m "[ADD] eq_hello_world: minimal Hello-World example module"
```

Commit prefix convention: `[ADD]` new features, `[CHG]` changes, `[FIX]` bugfixes.

### 8. Local Verification

After `odoodev start 18 --dev -d v18_devcopy -i eq_hello_world`, log in via the browser at <http://127.0.0.1:18069> and tick off the following:

- [ ] Login on the local database `v18_devcopy` works
- [ ] Module `eq_hello_world` is installed (Apps → search)
- [ ] Top-level menu **Hello World** is visible
- [ ] Sub-menu **Entries** opens the list view
- [ ] A new entry can be created, saved, and deleted again
- [ ] Default value "Hello, World!" appears in the `message` field
- [ ] No errors in the Odoo log (console or TUI)
- [ ] A second start with `-u eq_hello_world` runs cleanly (module update works)

### 9. Push and Merge Request

#### 9.1 Push

```bash
git push -u origin feature/eq_hello_world
```

#### 9.2 Open a merge request

In the GitLab UI:

1. Create the merge request at `https://gitlab.ownerp.io/v18/v18-addons/-/merge_requests/new`
2. Source: `feature/eq_hello_world` → target: `develop`
3. Description with ticket reference (`Closes #<id>`)
4. Assign reviewer
5. Pipeline runs automatically (lint, test, build)

This concludes the developer workflow. Promotion to further stages is then handled by the operations team.

### 10. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `odoodev: command not found` | UV tools not on PATH | `uv tool update-shell` or reload shell |
| `[ERROR] PostgreSQL port 18432 not reachable` | Docker not running | `odoodev docker up 18` |
| `[ERROR] No odoo-bin found` | Server repo missing | `odoodev repos 18 --server-only` |
| `[ERROR] requirements.txt changed` | Dependencies changed | `odoodev venv setup 18 --force` |
| Module not visible in apps list | Apps list outdated | In Odoo: **Apps → Update Apps List** or `odoodev start 18 --dev -u base` |
| Module code change is not picked up | Not in dev mode or module not updated | `odoodev start 18 --dev -u eq_hello_world` |
| `git pull --ff-only` fails | Local branch has diverged | `git -C <repo> pull --rebase` (after agreement) |
| `wkhtmltopdf` produces broken PDFs | No patched-qt build installed | Use the `.pkg` installer (macOS) or patched-qt build (Linux) from <https://wkhtmltopdf.org/downloads.html> |

### Definition of Done

- [ ] Wiki article published in the project's GitLab wiki
- [ ] A new developer has worked through the article top to bottom and has the Hello-World module running locally and submitted as a merge request against `develop`
- [ ] Reviewed and approved by the team

### References

| Topic | File |
|---|---|
| odoodev installation, setup wizard | [`setup.md`](setup.md) |
| Configuration & versions | [`config.md`](config.md) |
| Repository management & `repos.yaml` | [`repos.md`](repos.md) |
| Server start/stop, all modes | [`start.md`](start.md) |
| Database operations, backup formats | [`db.md`](db.md) |
| Docker services | [`docker.md`](docker.md) |
| Virtual environment management | [`venv.md`](venv.md) |
| Shell integration & completions | [`shell.md`](shell.md) |
| Migration mode (cross-version) | [`migrate.md`](migrate.md) |
| Playbook automation (`run`) | [`run.md`](run.md) |

### Source Code

`odoodev` is open source and developed on GitHub:

<https://github.com/equitania/odoo-dev>

Issues, feature requests, and pull requests are welcome.
