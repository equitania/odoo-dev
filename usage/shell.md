# Shell Integration & Completions

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

### Shell-Integration installieren

```bash
odoodev shell-setup
```

Installiert fuer die erkannte Shell (Fish, Bash, Zsh):
- **`odoodev-activate`** Funktion — Venv aktivieren + in Projektverzeichnis wechseln
- **Tab-Completions** fuer alle `odoodev`-Befehle, Subcommands und Flags
- **Versions-Completions** fuer `odoodev-activate` (Tab zeigt 16, 17, 18, 19)
- **Abbreviations/Aliases** fuer Schnellzugriff

### Explizite Shell waehlen

```bash
odoodev shell-setup --shell fish
odoodev shell-setup --shell bash
odoodev shell-setup --shell zsh
```

### Was installiert wird

#### Fish Shell

**Datei:** `~/.config/fish/conf.d/odoodev.fish`

| Feature | Beschreibung |
|---------|-------------|
| `odoodev-activate <VERSION>` | Venv aktivieren + cd zum Projektverzeichnis |
| Tab-Completion fuer `odoodev` | Alle Commands, Subcommands und Flags |
| Tab-Completion fuer `odoodev-activate` | Dynamische Versionsliste |
| `oda` (Abbreviation) | Expandiert zu `odoodev-activate` |
| `odev` (Abbreviation) | Expandiert zu `odoodev` |

Fish-Abbreviations expandieren sichtbar beim Druecken von Space/Enter — der volle Befehl erscheint in der Kommandozeile und wird in der History gespeichert.

#### Bash Shell

**Datei:** `~/.bashrc` (angehaengt)

| Feature | Beschreibung |
|---------|-------------|
| `odoodev-activate <VERSION>` | Venv aktivieren + cd zum Projektverzeichnis |
| Tab-Completion fuer `odoodev` | Via Click's bash_source |
| Tab-Completion fuer `odoodev-activate` | Dynamische Versionsliste |
| `oda` (Alias) | Alias fuer `odoodev-activate` |
| `odev` (Alias) | Alias fuer `odoodev` |

#### Zsh Shell

**Datei:** `~/.zshrc` (angehaengt)

| Feature | Beschreibung |
|---------|-------------|
| `odoodev-activate <VERSION>` | Venv aktivieren + cd zum Projektverzeichnis |
| Tab-Completion fuer `odoodev` | Via Click's zsh_source |
| Tab-Completion fuer `odoodev-activate` | Dynamische Versionsliste (via `compdef`) |
| `oda` (Alias) | Alias fuer `odoodev-activate` |
| `odev` (Alias) | Alias fuer `odoodev` |

### Verwendung nach Installation

```bash
# Shell neu laden (oder Terminal neu starten)
source ~/.config/fish/conf.d/odoodev.fish  # Fish
source ~/.bashrc                            # Bash
source ~/.zshrc                             # Zsh

# Schnellzugriff
oda 18                    # = odoodev-activate 18
odev start 18 --dev       # = odoodev start 18 --dev

# Tab-Completion testen
odoodev <TAB>             # Zeigt: init, start, stop, repos, pull, db, ...
odoodev start --<TAB>     # Zeigt: --dev, --shell, --test, --prepare, ...
odoodev-activate <TAB>    # Zeigt: 16, 17, 18, 19
```

---

## English Documentation

### Install Shell Integration

```bash
odoodev shell-setup
```

Installs for the detected shell (Fish, Bash, Zsh):
- **`odoodev-activate`** function — activate venv + change to project directory
- **Tab completions** for all `odoodev` commands, subcommands, and flags
- **Version completions** for `odoodev-activate` (Tab shows 16, 17, 18, 19)
- **Abbreviations/Aliases** for quick access

### Choose Shell Explicitly

```bash
odoodev shell-setup --shell fish
odoodev shell-setup --shell bash
odoodev shell-setup --shell zsh
```

### What Gets Installed

#### Fish Shell

**File:** `~/.config/fish/conf.d/odoodev.fish`

| Feature | Description |
|---------|-------------|
| `odoodev-activate <VERSION>` | Activate venv + cd to project directory |
| Tab completion for `odoodev` | All commands, subcommands, and flags |
| Tab completion for `odoodev-activate` | Dynamic version list |
| `oda` (abbreviation) | Expands to `odoodev-activate` |
| `odev` (abbreviation) | Expands to `odoodev` |

Fish abbreviations expand visibly when pressing Space/Enter — the full command appears in the command line and is saved to history.

#### Bash Shell

**File:** `~/.bashrc` (appended)

| Feature | Description |
|---------|-------------|
| `odoodev-activate <VERSION>` | Activate venv + cd to project directory |
| Tab completion for `odoodev` | Via Click's bash_source |
| Tab completion for `odoodev-activate` | Dynamic version list |
| `oda` (alias) | Alias for `odoodev-activate` |
| `odev` (alias) | Alias for `odoodev` |

#### Zsh Shell

**File:** `~/.zshrc` (appended)

| Feature | Description |
|---------|-------------|
| `odoodev-activate <VERSION>` | Activate venv + cd to project directory |
| Tab completion for `odoodev` | Via Click's zsh_source |
| Tab completion for `odoodev-activate` | Dynamic version list (via `compdef`) |
| `oda` (alias) | Alias for `odoodev-activate` |
| `odev` (alias) | Alias for `odoodev` |

### Usage After Installation

```bash
# Reload shell (or restart terminal)
source ~/.config/fish/conf.d/odoodev.fish  # Fish
source ~/.bashrc                            # Bash
source ~/.zshrc                             # Zsh

# Quick access
oda 18                    # = odoodev-activate 18
odev start 18 --dev       # = odoodev start 18 --dev

# Test tab completion
odoodev <TAB>             # Shows: init, start, stop, repos, pull, db, ...
odoodev start --<TAB>     # Shows: --dev, --shell, --test, --prepare, ...
odoodev-activate <TAB>    # Shows: 16, 17, 18, 19
```
