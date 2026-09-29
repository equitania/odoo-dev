# Docker Services

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

### Docker-Service-Verwaltung

odoodev verwaltet Docker-Services (PostgreSQL + Mailpit) fuer die lokale Odoo-Entwicklung.

```bash
# Services starten
odoodev docker up 18

# Services stoppen
odoodev docker down 18

# Status anzeigen
odoodev docker status 18

# Logs anzeigen (follow-Modus)
odoodev docker logs 18 -f
```

`docker up` meldet Erfolg erst, wenn PostgreSQL auf Protokollebene bereit ist
(`pg_isready` bzw. Socket-Probe, bis zu 60 s Polling) — nicht schon beim Container-Start.

### Runtime-Diagnose & Selbstheilung (seit v0.60.0)

Vor jedem Service-Start wird die konfigurierte Runtime geprueft:

- **Apple Container**: Ein gestoppter `container-apiserver` wird transparent
  mitgestartet (`container system start`) — kein manueller Zwischenschritt mehr.
- **Docker**: Ein gestoppter Daemon fuehrt zu einem klaren Fehler mit Startbefehl
  (`open -a Docker` auf macOS, `sudo systemctl start docker` auf Linux) statt
  eines rohen Compose-Fehlers.
- **Fehlende CLI**: Installations- und Umschalt-Hinweise
  (`odoodev config set container_runtime docker|apple`).

`docker status` startet nichts automatisch, sondern meldet eine nicht bereite
Runtime samt konkreter Abhilfe (Exit-Code 1).

### Services

| Service | Image | Zweck |
|---------|-------|-------|
| PostgreSQL | `postgres:16.11-alpine` (versionsspezifisch) | Datenbank-Server |
| Mailpit | `axllent/mailpit` | SMTP-Test-Server mit Web-UI |

### pgvector (seit v0.71.0, Standard: aus)

Mit `PGVECTOR=true` in der `.env` der Version baut `odoodev docker up` einmalig das Image
`odoodev-postgres-pgvector:<POSTGRES_VERSION>` und startet PostgreSQL damit. Grundlage ist dasselbe
`postgres:<Version>`-Image wie ohne pgvector: Auf Alpine wird pgvector aus dem Quellcode gebaut, damit
bleibt das bestehende Datenvolume samt Sortierregeln gültig; auf Debian kommt das Paket aus
apt.postgresql.org. Der Build braucht Internetzugang (github.com bzw. apt.postgresql.org); gesetzte
Proxy-Variablen werden durchgereicht.

Warum nicht standardmäßig: Odoo 19 Enterprise bringt `ai_auto_install` mit. Bietet der Server pgvector
an, installiert Odoo in **jeder neuen Datenbank** das KI-Modul `ai`, ohne zu fragen. Einschalten, wenn
ein Backup mit KI-Modul eingespielt werden soll (siehe `db restore`) oder die KI-Funktionen selbst
entwickelt werden. Ausschalten: `PGVECTOR=false`, dann `odoodev docker up`.

Docker-Runtime: Eine `docker-compose.yml` von vor v0.71.0 kennt `POSTGRES_IMAGE` noch nicht;
`docker up` meldet das und nennt die Zeile, die ihre `image:`-Zeile ersetzt.

### Ports

Die Ports sind versionsspezifisch und vermeiden Konflikte bei paralleler Entwicklung:

| Version | DB Port | Mailpit Web | SMTP |
|---------|---------|-------------|------|
| v16 | 16432 | 16025 | 11025 |
| v17 | 17432 | 17025 | 11725 |
| v18 | 18432 | 18025 | 1025 |
| v19 | 19432 | 19025 | 1925 |
| v20 | 20432 | 20025 | 2025 |

### docker-compose.yml

Die `docker-compose.yml` wird von `odoodev init` aus einem Jinja2-Template generiert. Sie liegt unter `vXX-dev/devXX_native/docker-compose.yml`.

Die Plattform (arm64/amd64) wird automatisch erkannt — es gibt keine separaten Compose-Dateien mehr fuer verschiedene Architekturen.

---

## English Documentation

### Docker Service Management

odoodev manages Docker services (PostgreSQL + Mailpit) for local Odoo development.

```bash
# Start services
odoodev docker up 18

# Stop services
odoodev docker down 18

# Show status
odoodev docker status 18

# View logs (follow mode)
odoodev docker logs 18 -f
```

`docker up` only reports success once PostgreSQL is ready at the protocol level
(`pg_isready` or a socket probe, polling up to 60s) — not merely when the container starts.

### Runtime diagnosis & self-healing (since v0.60.0)

The configured runtime is verified before every service start:

- **Apple Container**: a stopped `container-apiserver` is started transparently
  (`container system start`) — no manual intermediate step anymore.
- **Docker**: a stopped daemon produces a clear error with the start command
  (`open -a Docker` on macOS, `sudo systemctl start docker` on Linux) instead
  of a raw compose failure.
- **Missing CLI**: install and switch hints
  (`odoodev config set container_runtime docker|apple`).

`docker status` never starts anything — it reports a non-ready runtime with
its concrete remedy (exit code 1).

### Services

| Service | Image | Purpose |
|---------|-------|---------|
| PostgreSQL | `postgres:16.11-alpine` (version-specific) | Database server |
| Mailpit | `axllent/mailpit` | SMTP test server with web UI |

### pgvector (since v0.71.0, default: off)

With `PGVECTOR=true` in the version's `.env`, `odoodev docker up` builds the image
`odoodev-postgres-pgvector:<POSTGRES_VERSION>` once and starts PostgreSQL from it. It is based on the
same `postgres:<version>` image as without pgvector: on Alpine pgvector is compiled from source, so the
existing data volume and its collations stay valid; on Debian the package comes from
apt.postgresql.org. The build needs internet access (github.com or apt.postgresql.org); proxy
variables that are set are passed through.

Why not by default: Odoo 19 Enterprise ships `ai_auto_install`. When the server offers pgvector, Odoo
installs the AI module `ai` in **every new database** without asking. Switch it on to restore a backup
that uses the AI module (see `db restore`) or to develop the AI features themselves. Off again:
`PGVECTOR=false`, then `odoodev docker up`.

Docker runtime: a `docker-compose.yml` from before v0.71.0 does not know `POSTGRES_IMAGE` yet;
`docker up` says so and prints the line that replaces its `image:` line.

### Ports

Ports are version-specific to avoid conflicts during parallel development:

| Version | DB Port | Mailpit Web | SMTP |
|---------|---------|-------------|------|
| v16 | 16432 | 16025 | 11025 |
| v17 | 17432 | 17025 | 11725 |
| v18 | 18432 | 18025 | 1025 |
| v19 | 19432 | 19025 | 1925 |
| v20 | 20432 | 20025 | 2025 |

### docker-compose.yml

The `docker-compose.yml` is generated by `odoodev init` from a Jinja2 template. It resides at `vXX-dev/devXX_native/docker-compose.yml`.

The platform (arm64/amd64) is automatically detected — there are no longer separate compose files for different architectures.
