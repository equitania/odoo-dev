# Apple Container Runtime (macOS)

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

odoodev kann den lokalen PostgreSQL-Dienst entweder über **Docker** (Standard, via
docker-compose) oder über **Apple Container** (`container run`) betreiben. Auf einem
Mac mit Apple Silicon ist Apple Container eine leichtgewichtige Alternative zu Docker
Desktop.

### Voraussetzungen

- macOS 26 auf Apple Silicon (arm64)
- Apples `container`-CLI installiert (https://github.com/apple/container, v1.0.0+)
- Laufender API-Server: `container system status` muss `running` melden

### Apple Container dauerhaft als Standard setzen

Damit `--runtime` nicht bei jedem Aufruf nötig ist, den Modus einmalig persistieren:

```bash
odoodev config set container_runtime apple   # schreibt nach ~/.config/odoodev/config.yaml
odoodev config show                           # Zeile „Container Runtime | apple"
```

Alternativ über den interaktiven Assistenten: `odoodev setup` (Schritt „Container runtime").

Danach nutzt jeder `odoodev start` automatisch Apple Container — ohne weitere Flags.

### Starten

```bash
# Nutzt die konfigurierte Runtime (apple, falls oben gesetzt)
odoodev start 18

# Einmaliger Override; weicht er vom gespeicherten Standard ab, fragt odoodev:
#   „Save 'apple' as default runtime?" → bei „ja" wird es persistiert
odoodev start 18 --runtime apple
```

Wird PostgreSQL nicht erreicht, startet odoodev den Container und nennt anschließend
dessen Namen, z. B.:

```
[OK] Apple Container 'picard-dev-db-18-native' is running — inspect with: container ls
```

**Bereitschafts-Wartezeit (v0.42.2):** Der Port-Forwarder der Micro-VM nimmt TCP-Verbindungen
an, bevor PostgreSQL in der VM tatsächlich bereit ist (VM-Boot, ggf. erstmaliges `initdb`).
`odoodev start` und `odoodev docker up` prüfen die Bereitschaft deshalb auf
PostgreSQL-Protokollebene (`pg_isready` bzw. Socket-Probe) und pollen bis zu 60 s mit
Spinner — Odoo startet erst, wenn PostgreSQL wirklich antwortet.

### Status / laufenden Container sehen

**Wichtig:** `container machine list` zeigt **nichts** an — das listet nur die VM-Infra­struktur,
nicht die Container. Laufende Container sieht man mit:

```bash
container ls                              # laufende Container
container ls -a                           # inkl. gestoppte
odoodev docker status 18 --runtime apple  # nennt den erwarteten Container-Namen + container ls -a
```

Der Container-Name folgt dem Schema `{user}-dev-db-{version}-native`
(z. B. `picard-dev-db-18-native`); das Datenvolume `{user}-vol-dev-db-{version}-native`
bleibt über Stop/Start hinweg erhalten.

### Stoppen

```bash
# Odoo-Server: Ctrl+C im Terminal beendet ihn sauber (inkl. Worker)
# PostgreSQL-Container stoppen (Datenvolume bleibt erhalten):
odoodev docker down 18 --runtime apple
```

### Troubleshooting

- **`container machine list` ist leer:** Korrektes Verhalten — `container ls` verwenden.
- **`container system status` ≠ running:** API-Server starten (`container system start`)
  bzw. die `container`-Installation prüfen.
- **Ctrl+C stoppt Odoo nicht (ältere Versionen):** In v0.35.0 behoben — der Server läuft in
  einer eigenen Session und wird per Prozessgruppen-Signal beendet. `uv pip install -e .`
  aktualisiert einen veralteten Editable-Install.
- **`config show` zeigt keine „Container Runtime"-Zeile:** Installierte Version ist älter als
  der Code — `uv pip install -e .` neu ziehen.

---

## English Documentation

odoodev can run the local PostgreSQL service either on **Docker** (default, via
docker-compose) or on **Apple Container** (`container run`). On an Apple-silicon Mac,
Apple Container is a lightweight alternative to Docker Desktop.

### Prerequisites

- macOS 26 on Apple silicon (arm64)
- Apple's `container` CLI installed (https://github.com/apple/container, v1.0.0+)
- API server running: `container system status` must report `running`

### Make Apple Container the persistent default

So you don't need `--runtime` on every call, persist the mode once:

```bash
odoodev config set container_runtime apple   # writes ~/.config/odoodev/config.yaml
odoodev config show                           # row "Container Runtime | apple"
```

Or via the interactive wizard: `odoodev setup` (step "Container runtime").

After that every `odoodev start` uses Apple Container automatically — no extra flags.

### Starting

```bash
# Uses the configured runtime (apple, if set above)
odoodev start 18

# One-off override; if it differs from the stored default, odoodev asks:
#   "Save 'apple' as default runtime?" → "yes" persists it
odoodev start 18 --runtime apple
```

When PostgreSQL is unreachable, odoodev starts the container and then prints its name:

```
[OK] Apple Container 'picard-dev-db-18-native' is running — inspect with: container ls
```

**Readiness wait (v0.42.2):** the micro-VM's port forwarder accepts TCP connections before
PostgreSQL inside the VM is actually ready (VM boot, possibly first-time `initdb`).
`odoodev start` and `odoodev docker up` therefore verify readiness at the PostgreSQL protocol
level (`pg_isready` or a socket probe) and poll up to 60s with a spinner — Odoo only launches
once PostgreSQL really answers.

### Status / seeing the running container

**Important:** `container machine list` shows **nothing** — it only lists VM infrastructure,
not containers. To see running containers:

```bash
container ls                              # running containers
container ls -a                           # including stopped
odoodev docker status 18 --runtime apple  # names the expected container + container ls -a
```

The container name follows `{user}-dev-db-{version}-native`
(e.g. `picard-dev-db-18-native`); the data volume `{user}-vol-dev-db-{version}-native`
survives stop/start.

### Stopping

```bash
# Odoo server: Ctrl+C in the terminal stops it cleanly (workers included)
# Stop the PostgreSQL container (the data volume is kept):
odoodev docker down 18 --runtime apple
```

### Troubleshooting

- **`container machine list` is empty:** Expected — use `container ls`.
- **`container system status` ≠ running:** Start the API server (`container system start`)
  or check the `container` installation.
- **Ctrl+C does not stop Odoo (older versions):** Fixed in v0.35.0 — the server runs in its
  own session and is stopped via a process-group signal. `uv pip install -e .` updates a stale
  editable install.
- **`config show` has no "Container Runtime" row:** The installed build is older than the
  code — re-run `uv pip install -e .`.
