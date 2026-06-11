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

`odoodev venv check` and `odoodev start` check if a newer Python patch version is available on the system:

```
[WARNING] Newer Python available: venv has 3.13.10, system has 3.13.12
[INFO] Run: odoodev venv setup 18 --force
```

During `venv check`, an interactive offer to recreate the venv is shown.

### Interactive Mode

If `.venv` is missing, `venv check` and `venv activate` automatically offer to create it.
