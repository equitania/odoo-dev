# Virtual Environment Management

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

### Venv-Verwaltung

```bash
# Venv erstellen/neu erstellen
odoodev venv setup 18

# Venv erzwungen neu erstellen
odoodev venv setup 18 --force

# Venv-Status pruefen
odoodev venv check 18

# Venv-Status als JSON pruefen (nicht-interaktiv)
odoodev venv check 18 --json

# Aktivierungsbefehl anzeigen
odoodev venv activate 18

# Venv-Pfad ausgeben
odoodev venv path 18

# Venv loeschen
odoodev venv remove 18

# Venv loeschen ohne Bestaetigungsprompt
odoodev venv remove 18 --yes
```

### Venv loeschen (`odoodev venv remove`)

```bash
odoodev venv remove 18          # mit Bestaetigungsprompt
odoodev venv remove 18 --yes    # ohne Prompt
odoodev venv remove 18 -y       # Kurzform
```

Loescht das `.venv`-Verzeichnis der angegebenen Version. Ist das Venv bereits nicht
vorhanden, laeuft der Befehl ohne Fehler durch (idempotent). Symlinks werden korrekt
behandelt (nur der Link wird entfernt, nicht das Ziel). Nach dem Loeschen kann das
Venv mit `odoodev venv setup 18` neu erstellt werden.

### venv check --json

```bash
odoodev venv check 18 --json
```

Nicht-interaktiver JSON-Output — geeignet fuer Skripte und AI-Agenten:

```json
{
  "version": "18",
  "venv_dir": "/Users/picard/gitbase/v18/v18-dev/dev18_native/.venv",
  "exists": true,
  "is_symlink": false,
  "python_version": "3.13.2",
  "python_matches": true,
  "python_pin": "3.13.2",
  "python_pin_source": "file",
  "requirements_current": true
}
```

Exit-Code 1, wenn das Venv fehlt (`"exists": false`).

### Funktionsweise

- **Erstellung:** Verwendet UV (`uv venv`) mit der fuer die Odoo-Version konfigurierten Python-Version
- **Abhaengigkeiten:** Installiert aus `vXX-dev/devXX_native/requirements.txt` via `uv pip install`
- **Hash-Tracking:** SHA256-Hash der requirements.txt wird in `.venv/.requirements.sha256` gespeichert
- **Freshness-Check:** Bei `odoodev start` und `odoodev venv check` wird der Hash verglichen — bei Aenderung wird ein Update angeboten

### Python-Patch-Version

`odoodev venv check` und `odoodev start` pruefen, ob eine neuere Python-Patch-Version auf dem System verfuegbar ist:

```
[WARNING] Neuere Python-Version verfuegbar: venv hat 3.13.10, System hat 3.13.12
[INFO] Run: odoodev venv setup 18 --force
```

Bei `venv check` wird interaktiv angeboten, das Venv neu zu erstellen.

### Interaktiver Modus

Wenn `.venv` fehlt, bieten `venv check` und `venv activate` automatisch die Erstellung an.

---

## English Documentation

### Venv Management

```bash
# Create/recreate venv
odoodev venv setup 18

# Force recreate venv
odoodev venv setup 18 --force

# Check venv status
odoodev venv check 18

# Check venv status as JSON (non-interactive)
odoodev venv check 18 --json

# Show activation command
odoodev venv activate 18

# Output venv path
odoodev venv path 18

# Remove venv
odoodev venv remove 18

# Remove venv without confirmation prompt
odoodev venv remove 18 --yes
```

### Remove Venv (`odoodev venv remove`)

```bash
odoodev venv remove 18          # with confirmation prompt
odoodev venv remove 18 --yes    # no prompt
odoodev venv remove 18 -y       # short form
```

Deletes the `.venv` directory for the given version. If the venv is already absent,
the command completes without error (idempotent). Symlinks are handled correctly —
only the link is removed, not the target. Recreate with `odoodev venv setup 18`.

### venv check --json

```bash
odoodev venv check 18 --json
```

Non-interactive JSON output — suitable for scripts and AI agents:

```json
{
  "version": "18",
  "venv_dir": "/Users/picard/gitbase/v18/v18-dev/dev18_native/.venv",
  "exists": true,
  "is_symlink": false,
  "python_version": "3.13.2",
  "python_matches": true,
  "requirements_current": true
}
```

Exit code 1 when the venv is missing (`"exists": false`).

### How It Works

- **Creation:** Uses UV (`uv venv`) with the Python version configured for the Odoo version
- **Dependencies:** Installs from `vXX-dev/devXX_native/requirements.txt` via `uv pip install`
- **Hash tracking:** SHA256 hash of requirements.txt is stored in `.venv/.requirements.sha256`
- **Freshness check:** During `odoodev start` and `odoodev venv check`, the hash is compared — if changed, an update is offered

### Python Patch Version

The version registry only knows `major.minor` (`python: "3.13"`). `uv venv --python 3.13`
resolves that to whichever 3.13 uv prefers — normally its own managed build under
`~/.local/share/uv/python/`, even when a newer 3.13 is installed. So when a newer patch
release shows up, `odoodev venv check` and `odoodev start` say so:

```
[WARNING] Newer Python available: venv has 3.13.12, system has 3.13.15
[INFO] Run: odoodev venv setup 19 --force --python-version 3.13.15
[INFO] Or pin it: echo 3.13.12 > ~/gitbase/v19/v19-dev/dev19_native/.python-version
```

`venv check` additionally offers to recreate the venv right away.

Note the full version in the suggested command: a plain `--force` would re-resolve `3.13`
from the registry and rebuild the identical interpreter, reinstalling only the requirements.

### Pinning an interpreter: `.python-version`

A `.python-version` file next to the venv pins the exact interpreter for that one
environment and overrides the registry everywhere — `venv setup`, `venv check`, `start`'s
preflight, `init` and the `venv.setup` playbook step:

```fish
printf '3.13.15\n' > ~/gitbase/v19/v19-dev/dev19_native/.python-version
odoodev venv setup 19 --force
```

Rules:

- Blank lines and `#` comments are skipped, the first remaining line wins
- uv's spellings are accepted: `3.13.15`, `3.13`, `cpython@3.13.15`,
  `cpython-3.13.15-macos-aarch64-none`
- Anything else — a leading `-`, an interpreter path, inner whitespace — is refused with a
  warning, and the registry value is used instead
- A pin from another release series than the registry expects (say `3.14.7` under Odoo 19)
  is honoured, but reported on every run
- With an **exact** pin the "newer Python available" advisory falls silent: pinning 3.13.12
  is a decision, not a lag. Only a venv that deviates from the pin is reported

Pinning a Homebrew interpreter (`3.13.15` above) is deliberate but not free: `brew upgrade
python@3.13` moves the Cellar path and breaks the venv — `check_venv_interpreter` catches
that at the next start. uv's own managed builds are stable across upgrades.

### Interactive Mode

If `.venv` is missing, `venv check` and `venv activate` automatically offer to create it.
