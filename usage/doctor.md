# Environment Diagnostics (doctor)

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

### Umgebungsdiagnose

Der `doctor`-Befehl prueft alle Voraussetzungen der odoodev-Umgebung und gibt eine
uebersichtliche Rich-Tabelle mit dem Ergebnis aus.

```bash
# Alle Checks ohne Versionskontext
odoodev doctor

# Alle Checks inklusive versionsabhaengiger Pruefungen
odoodev doctor 18
```

### Verfuegbare Checks

| Check | Kategorie | Beschreibung |
|-------|-----------|--------------|
| `uv` | Hart | UV-Paketmanager vorhanden und ausfuehrbar |
| `docker` | Hart | Docker-Engine erreichbar |
| `docker_compose` | Hart | `docker compose` Plugin verfuegbar |
| `pg_tools` | Hart | `pg_dump` und `psql` im PATH |
| `postgres` | Hart | PostgreSQL-Port erreichbar (nur mit VERSION) |
| `python_packages` | Hart | Python-Abhaengigkeiten im Venv vollstaendig (nur mit VERSION + vorhandenem Venv) |
| `wkhtmltopdf` | Soft | wkhtmltopdf installiert und ausfuehrbar |
| `7zip` | Soft | 7-Zip-CLI (`7zz`/`7z`/`7za`) vorhanden — fuer `.7z`-Restore |
| `node` | Soft | Node.js vorhanden |
| `node_packages` | Soft | rtlcss, less, less-plugin-clean-css installiert |
| `system_libs` | Soft | Systembibliotheken (z.B. libxml2, libpq) |
| `pypi_freshness` | Info | Verfuegbare Version auf PyPI gegenueber installierter |

**Harte Checks** (Kategorie "Hart") liefern Exit-Code 1 bei Fehler.
**Soft Checks** erzeugen nur eine Warnung — der Befehl endet mit Exit-Code 0.

### Ohne Versionsangabe

Ohne `VERSION` werden folgende Checks uebersprungen:

- `postgres` — kein versionsabhaengiger Port bekannt
- `python_packages` — kein Venv-Pfad bekannt

Alle anderen Checks laufen immer.

### PyPI-Aktualitaetspruefung

Der `pypi_freshness`-Check ruft `https://pypi.org/pypi/odoodev-equitania/json` mit
2 Sekunden Timeout ab und vergleicht die neuste veroeffentlichte Version mit der
installierten. Moegliche Statusmeldungen:

| Status | Bedeutung |
|--------|-----------|
| `Up to date` | Installierte Version ist aktuell |
| `Update available: X.Y.Z` | Neuere Version auf PyPI verfuegbar |
| `skipped (offline)` | Kein Internetzugang oder Timeout |

Dieser Check ist niemals fatal (kein Exit-Code 1).

### Ausgabeformat

Nach den einzelnen Checks zeigt `doctor` eine Rich-Tabelle:

```
 Check              Status   Notes
 uv                 ok
 docker             ok
 docker_compose     ok
 wkhtmltopdf        warning  not found — PDF reports may not render
 7zip               ok
 pg_tools           ok
 postgres           ok       port 18432 reachable
 node               warning  not found — rtlcss/less unavailable
 node_packages      warning  skipped (node missing)
 system_libs        ok
 python_packages    ok       v18 venv checked
 pypi_freshness     info     Update available: 0.9.0
```

### Beispiele

```bash
# Schnellcheck ohne Versionskontext (kein laufendes Docker noetig)
odoodev doctor

# Vollstaendiger Check fuer v18 (PostgreSQL-Port und Venv werden geprueft)
odoodev doctor 18
```

---

## English Documentation

### Environment Diagnostics

The `doctor` command checks all prerequisites of the odoodev environment and prints
a Rich summary table with the results.

```bash
# All checks without version context
odoodev doctor

# All checks including version-specific prerequisites
odoodev doctor 18
```

### Available Checks

| Check | Category | Description |
|-------|----------|-------------|
| `uv` | Hard | UV package manager present and executable |
| `docker` | Hard | Docker engine reachable |
| `docker_compose` | Hard | `docker compose` plugin available |
| `pg_tools` | Hard | `pg_dump` and `psql` on PATH |
| `postgres` | Hard | PostgreSQL port reachable (only with VERSION) |
| `python_packages` | Hard | Python dependencies complete in venv (only with VERSION + existing venv) |
| `wkhtmltopdf` | Soft | wkhtmltopdf installed and executable |
| `7zip` | Soft | 7-Zip CLI (`7zz`/`7z`/`7za`) present — for `.7z` restore |
| `node` | Soft | Node.js present |
| `node_packages` | Soft | rtlcss, less, less-plugin-clean-css installed |
| `system_libs` | Soft | System libraries (e.g. libxml2, libpq) |
| `pypi_freshness` | Info | Available version on PyPI vs. installed |

**Hard checks** exit with code 1 on failure.
**Soft checks** emit a warning only — the command exits with code 0.

### Without Version Argument

Without `VERSION`, the following checks are skipped:

- `postgres` — no version-specific port known
- `python_packages` — no venv path known

All other checks always run.

### PyPI Freshness Check

The `pypi_freshness` check fetches `https://pypi.org/pypi/odoodev-equitania/json` with
a 2-second timeout and compares the latest published version against the installed one.
Possible status messages:

| Status | Meaning |
|--------|---------|
| `Up to date` | Installed version is current |
| `Update available: X.Y.Z` | Newer version available on PyPI |
| `skipped (offline)` | No internet access or timeout |

This check is never fatal (no exit code 1).

### Output Format

After the individual checks, `doctor` displays a Rich table:

```
 Check              Status   Notes
 uv                 ok
 docker             ok
 docker_compose     ok
 wkhtmltopdf        warning  not found — PDF reports may not render
 7zip               ok
 pg_tools           ok
 postgres           ok       port 18432 reachable
 node               warning  not found — rtlcss/less unavailable
 node_packages      warning  skipped (node missing)
 system_libs        ok
 python_packages    ok       v18 venv checked
 pypi_freshness     info     Update available: 0.9.0
```

### Examples

```bash
# Quick check without version context (no running Docker required)
odoodev doctor

# Full check for v18 (PostgreSQL port and venv are included)
odoodev doctor 18
```
