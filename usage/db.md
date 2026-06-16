# Database Operations

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

### Datenbankoperationen

```bash
# Datenbanken auflisten
odoodev db list 18

# Datenbanken als JSON auflisten
odoodev db list 18 --json

# Backup erstellen (interaktiv) — landet standardmaessig in ~/Downloads/
odoodev db backup 18

# Backup als SQL-Dump (mit --output das Zielverzeichnis ueberschreiben)
odoodev db backup 18 -n v18_exam -t sql -o /tmp

# Backup als ZIP mit Filestore
odoodev db backup 18 -n v18_exam -t zip -o /tmp

# Backup wiederherstellen
odoodev db restore 18 -n v18_test -z backup.zip

# Datenbank kopieren
odoodev db copy 18 -s v18_prod -d v18_test

# Datenbank umbenennen
odoodev db rename 18 -s v18_old -d v18_new

# Datenbank loeschen
odoodev db drop 18 -n v18_test

# Datenbank loeschen ohne Bestaetigungsprompt
odoodev db drop 18 -n v18_test --yes
```

### Datenbank kopieren & umbenennen

```bash
# Datenbank kopieren (interaktive Quellauswahl wenn -s fehlt)
odoodev db copy 18 -s v18_prod -d v18_test
odoodev db copy 18 -d v18_test          # Quelle wird interaktiv gewaehlt
odoodev db copy 18 -s v18_prod -d v18_test --yes   # ohne Bestaetigungsprompt

# Mit aktiven Verbindungen (laufender Odoo-Server)
odoodev db copy 18 -s v18_prod -d v18_test --terminate-connections

# Datenbank umbenennen
odoodev db rename 18 -s v18_old -d v18_new
odoodev db rename 18 -s v18_old -d v18_new --yes
odoodev db rename 18 -s v18_old -d v18_new --terminate-connections
```

`db copy` verwendet `createdb -T` und kopiert zusaetzlich den Filestore nach
`~/odoo-share/filestore/{dst}/`. Das Ziel-Datenbankname darf noch nicht existieren;
die Quelle muss vorhanden sein. Hat die Quelldatenbank aktive Verbindungen (z.B. ein
laufender Odoo-Server), gibt der Befehl eine Warnung aus und bietet an, die
Verbindungen zu beenden — oder verlangt `--terminate-connections`, je nach interaktivem
Kontext.

`db rename` fuehrt `ALTER DATABASE ... RENAME TO ...` aus und verschiebt anschliessend
das Filestore-Verzeichnis. Verbindungsbehandlung identisch zu `db copy`.

### db list --json

```bash
odoodev db list 18 --json
```

Gibt ein einzeiliges JSON-Objekt aus:

```json
{"version": "18", "host": "localhost", "port": 18432, "databases": ["v18_prod", "v18_test"]}
```

Nuetzlich fuer Skripte und AI-Agenten.

### Interaktiver Modus

Wenn Flags weggelassen werden, fragt odoodev interaktiv nach:

- `odoodev db backup 18` → Auswahl der Datenbank und des Backup-Typs (Ziel standardmaessig `~/Downloads/`, mit `-o/--output` ueberschreibbar)
- `odoodev db restore 18` → Eingabe des Dateipfads und Datenbanknamens (mit Vorschlag aus Dateiname)
- `odoodev db drop 18` → Auswahl der Datenbank aus Liste
- `odoodev db copy 18 -d v18_test` → Auswahl der Quelldatenbank aus Liste

### Unterstuetzte Backup-Formate

| Format | Erkennung | Anmerkung |
|--------|-----------|-----------|
| ZIP | `zipfile.is_zipfile()` oder `.zip`-Endung | Standard-Odoo-Backup-Format (SQL + Filestore) |
| 7z | `.7z`-Endung | Verwendet `7zz` oder `7z`-Binary |
| tar/tgz | `.tar` oder `.tgz`-Endung | Komprimiertes Archiv |
| gz | `.gz`-Endung | Gunzip zu dump.sql |
| SQL | `.sql` oder `.dump`-Endung | Direkter SQL-Import |

### Filestore-Verwaltung

**Filestore-Pfad:** `~/odoo-share/filestore/{db_name}/`

Bei `odoodev db restore` wird der Filestore automatisch verwaltet:

1. Backup wird extrahiert (ZIP, 7z, tar, gz, SQL)
2. SQL-Dump wird in neue Datenbank eingespielt
3. Filestore wird nach `~/odoo-share/filestore/{db_name}/` kopiert

**Post-Restore Deaktivierungen (psql-Baseline):**
- Cron-Jobs (`ir_cron.active = false`)
- Mail-Server (`ir_mail_server.active = false`)
- Fetchmail-Server (`fetchmail_server.active = false`)

Diese psql-Baseline laeuft immer (kein lauffaehiges Odoo noetig) und stellt sicher, dass eine
restored Prod-Kopie keine Crons/Mails ausloest.

### Native Neutralisierung (`odoo-bin neutralize`, standardmaessig aktiv)

Zusaetzlich ruft `odoodev db restore` nach dem Import Odoos eingebautes `odoo-bin neutralize`
auf. Das fuehrt pro installiertem Modul dessen `data/neutralize.sql` aus und deckt damit weit
mehr ab als die psql-Baseline: **Payment-Provider, IAP-Accounts, Webhooks, Mass-Mailing,
OAuth-Tokens, das „NEUTRALIZED"-Banner** sowie jedes Custom-Modul mit eigener `neutralize.sql`
(inkl. der hauseigenen Nextcloud-/Office365-Module — daher gibt es keine separate
Cloud-Deaktivierung mehr).

- **Standardmaessig an** (`--no-neutralize` zum Abschalten).
- **Graceful-skip:** Fehlen venv, `odoo-bin` oder die generierte `odoo_*.conf`, wird der Schritt
  mit Warnung uebersprungen (non-fatal) — die psql-Baseline greift trotzdem.
- `neutralize` bootet **keinen** Server; es verbindet sich direkt auf PostgreSQL.

**Eigenstaendiger Befehl** (z.B. nachdem `repos` + `start -u all` die Module bereitgestellt haben):

```bash
odoodev db neutralize 18 -n v18_test            # neutralisieren
odoodev db neutralize 18 -n v18_test --stdout   # nur SQL ausgeben (Dry-Run, nichts anwenden)
```

Verifikation: `ir_config_parameter` enthaelt danach `database.is_neutralized = true`.

**Bank-Synchronisation (ergaenzend, unter `--neutralize`):** Odoos Neutralize setzt
`account_journal.bank_statements_source` nicht zurueck und loescht `account_online_link` nicht.
`odoodev` ergaenzt daher FK-sicher (Journals entkoppeln → `account_online_account` loeschen →
`account_online_link` loeschen, `bank_statements_source='undefined'`) — je Statement eine eigene
Transaktion, tabellen-geprueft (No-Op ohne Buchhaltungs-/Bank-Sync-Module).

### DSGVO-Anonymisierung (standardmaessig aktiv)

`odoodev db restore` anonymisiert personenbezogene Daten **standardmaessig** direkt nach dem
Import (DSGVO Art. 5 Datenminimierung, Art. 25 Privacy by Default). Mit `--no-anonymize`
laesst sich dies fuer Sonderfaelle deaktivieren.

Die Ersatzwerte werden mit **Faker** (`de_DE`, pro Datensatz-ID geseedet → reproduzierbar)
erzeugt. E-Mail- und Login-Felder werden bewusst **nicht** aus Faker generiert, sondern auf
reservierte, nicht zustellbare Werte gesetzt (`p{id}@example.invalid`, `user{id}`).

| Tabelle | Anonymisierte Felder |
|---------|----------------------|
| `res_partner` | Name (Firmen → `fake.company()`, Personen → `fake.name()`), E-Mail, Telefon/Mobil, Adresse, USt-IdNr., Website, Notiz, Funktion (nur Personen) |
| `crm_lead` | Kontakt-/Firmenname, E-Mail, Telefon/Mobil, Adresse, Beschreibung |
| `res_partner_bank` | Kontonummer (Fake-IBAN), bereinigte Kontonummer |
| `hr_employee` | Name, Work-E-Mail, Telefon, Privatadresse, Ausweis-/Pass-/SV-Nummern, Geburtsdaten, Ehepartner-/Notfalldaten, PIN/Barcode, Notizen, Bild-/Scan-Felder; Gehalt-/km-Felder → 0 |
| `hr_version` (v19) / `hr_contract` (v16/v18) | Gehalt (`wage` → 0), sensible Personaldaten (v19) |
| `employee_bank_account_rel` (v19) | M2M-Verknuepfung komplett geloescht |
| `mail_message` | `email_from`, Betreff (geleert), Body (Platzhalter) |
| `ir_attachment` | `index_content` (Volltext-Index geleert) |

> **`res_users` wird per Default NICHT anonymisiert** — Logins bleiben testbar. Opt-in via
> `--anonymize-users` (Login → `user{id}`, Passwort → Dev-Passwort `--user-password`, Default
> `ownerp`; `admin` bleibt unveraendert). HR-Spalten werden gegen das Live-Schema gefiltert,
> daher versionsrobust (v16/v18/v19). Fehlende Tabellen/Spalten werden uebersprungen (non-fatal).

```bash
odoodev db restore 18 -n v18_test -z prod_backup.zip                  # anonymisiert (Default), User bleiben
odoodev db restore 18 -n v18_test -z prod_backup.zip --anonymize-users # zusaetzlich res_users
odoodev db restore 18 -n v18_test -z prod_backup.zip --no-anonymize   # Rohdaten behalten
```

Bei `odoodev db drop` wird der Filestore-Ordner ebenfalls entfernt (mit Hinweis in der Bestaetigungsabfrage).

> **Tipp:** Nach dem Restore empfiehlt odoodev `odoodev start -d {name} -u all` um alle Module zu aktualisieren.

> **Kunden-Sonderdokument:** Eine ausfuehrliche, kundenfaehige Darstellung beider Schutzschichten
> (DSGVO-Kontext, vollstaendige Feldtabelle, Audit-Snippets, Restrisiken) liegt unter
> [data-protection.md](data-protection.md).

### Standard-Credentials

- **Benutzer:** `ownerp`
- **Passwort:** `CHANGE_AT_FIRST` (konfigurierbar via `odoodev setup`)

---

## English Documentation

### Database Operations

```bash
# List databases
odoodev db list 18

# List databases as JSON
odoodev db list 18 --json

# Create backup (interactive) — defaults to ~/Downloads/
odoodev db backup 18

# Backup as SQL dump (override the target dir with --output)
odoodev db backup 18 -n v18_exam -t sql -o /tmp

# Backup as ZIP with filestore
odoodev db backup 18 -n v18_exam -t zip -o /tmp

# Restore backup
odoodev db restore 18 -n v18_test -z backup.zip

# Copy database
odoodev db copy 18 -s v18_prod -d v18_test

# Rename database
odoodev db rename 18 -s v18_old -d v18_new

# Drop database
odoodev db drop 18 -n v18_test

# Drop database without confirmation prompt
odoodev db drop 18 -n v18_test --yes
```

### Copy & Rename Databases

```bash
# Copy database (interactive source selection when -s is omitted)
odoodev db copy 18 -s v18_prod -d v18_test
odoodev db copy 18 -d v18_test            # source selected interactively
odoodev db copy 18 -s v18_prod -d v18_test --yes   # no confirmation prompt

# With active connections (running Odoo server)
odoodev db copy 18 -s v18_prod -d v18_test --terminate-connections

# Rename database
odoodev db rename 18 -s v18_old -d v18_new
odoodev db rename 18 -s v18_old -d v18_new --yes
odoodev db rename 18 -s v18_old -d v18_new --terminate-connections
```

`db copy` uses `createdb -T` and additionally copies the filestore to
`~/odoo-share/filestore/{dst}/`. The destination database name must not yet exist;
the source must be present. If the source has active connections (e.g. a running
Odoo server), the command warns and offers to terminate them — or requires
`--terminate-connections` depending on interactive context.

`db rename` runs `ALTER DATABASE ... RENAME TO ...` and then moves the filestore
directory. Connection handling is identical to `db copy`.

### db list --json

```bash
odoodev db list 18 --json
```

Returns a single-line JSON object:

```json
{"version": "18", "host": "localhost", "port": 18432, "databases": ["v18_prod", "v18_test"]}
```

Useful for scripts and AI agents.

### Interactive Mode

When flags are omitted, odoodev prompts interactively:

- `odoodev db backup 18` → Select database and backup type
- `odoodev db restore 18` → Enter file path and database name (with suggestion from filename)
- `odoodev db drop 18` → Select database from list
- `odoodev db copy 18 -d v18_test` → Select source database from list

### Supported Backup Formats

| Format | Detection | Note |
|--------|-----------|------|
| ZIP | `zipfile.is_zipfile()` or `.zip` extension | Standard Odoo backup format (SQL + filestore) |
| 7z | `.7z` extension | Uses `7zz` or `7z` binary |
| tar/tgz | `.tar` or `.tgz` extension | Compressed archive |
| gz | `.gz` extension | Gunzip to dump.sql |
| SQL | `.sql` or `.dump` extension | Direct SQL import |

### Filestore Management

**Filestore path:** `~/odoo-share/filestore/{db_name}/`

During `odoodev db restore`, the filestore is managed automatically:

1. Backup is extracted (ZIP, 7z, tar, gz, SQL)
2. SQL dump is imported into new database
3. Filestore is copied to `~/odoo-share/filestore/{db_name}/`

**Post-restore deactivations (psql baseline):**
- Cron jobs (`ir_cron.active = false`)
- Mail servers (`ir_mail_server.active = false`)
- Fetchmail servers (`fetchmail_server.active = false`)

This psql baseline always runs (no running Odoo required) and guarantees a restored
production copy fires no crons/mails.

### Native neutralization (`odoo-bin neutralize`, on by default)

After the import, `odoodev db restore` additionally runs Odoo's built-in `odoo-bin neutralize`.
It executes each installed module's `data/neutralize.sql`, covering far more than the psql
baseline: **payment providers, IAP accounts, webhooks, mass mailing, OAuth tokens, the
"NEUTRALIZED" banner**, and any custom module shipping its own `neutralize.sql` (including the
in-house Nextcloud/Office365 modules — which is why there is no separate cloud deactivation
anymore).

- **On by default** (`--no-neutralize` to disable).
- **Graceful skip:** if venv, `odoo-bin` or the generated `odoo_*.conf` are missing, the step is
  skipped with a warning (non-fatal) — the psql baseline still applies.
- `neutralize` boots **no** server; it connects to PostgreSQL directly.

**Standalone command** (e.g. once `repos` + `start -u all` have populated the addons path):

```bash
odoodev db neutralize 18 -n v18_test            # neutralize
odoodev db neutralize 18 -n v18_test --stdout   # print SQL only (dry run, applies nothing)
```

Verification: afterwards `ir_config_parameter` holds `database.is_neutralized = true`.

**Bank synchronisation (supplementary, under `--neutralize`):** Odoo's neutralize does not reset
`account_journal.bank_statements_source` nor delete `account_online_link`. `odoodev` adds an
FK-safe cleanup (detach journals → delete `account_online_account` → delete `account_online_link`,
`bank_statements_source='undefined'`) — one transaction per statement, table guarded (no-op when
the accounting / bank-sync modules are absent).

### GDPR anonymization (on by default)

`odoodev db restore` anonymizes personal data **by default** right after the import
(GDPR Art. 5 data minimization, Art. 25 privacy by default). Use `--no-anonymize` to disable
it for special cases.

Replacement values are generated with **Faker** (`de_DE`, seeded per row id → reproducible).
E-mail and login columns are deliberately **not** taken from Faker but forced onto reserved,
non-deliverable values (`p{id}@example.invalid`, `user{id}`).

| Table | Anonymized fields |
|-------|-------------------|
| `res_partner` | name (companies → `fake.company()`, persons → `fake.name()`), email, phone/mobile, address, VAT, website, comment, function (persons only) |
| `crm_lead` | contact/company name, email, phone/mobile, address, description |
| `res_partner_bank` | account number (fake IBAN), sanitized account number |
| `hr_employee` | name, work email, phones, private address, ID/passport/SSN numbers, birth data, spouse/emergency data, PIN/barcode, notes, image/scan fields; salary/distance fields → 0 |
| `hr_version` (v19) / `hr_contract` (v16/v18) | wage → 0, sensitive personnel data (v19) |
| `employee_bank_account_rel` (v19) | M2M link deleted entirely |
| `mail_message` | `email_from`, subject (cleared), body (placeholder) |
| `ir_attachment` | `index_content` (full-text index cleared) |

> **`res_users` is NOT anonymized by default** — logins stay testable. Opt in via
> `--anonymize-users` (login → `user{id}`, password → dev password `--user-password`, default
> `ownerp`; `admin` stays unchanged). HR columns are filtered against the live schema, so it is
> version robust (v16/v18/v19). Missing tables/columns are skipped (non-fatal).

```bash
odoodev db restore 18 -n v18_test -z prod_backup.zip                  # anonymized (default), users kept
odoodev db restore 18 -n v18_test -z prod_backup.zip --anonymize-users # additionally res_users
odoodev db restore 18 -n v18_test -z prod_backup.zip --no-anonymize   # keep raw data
```

When running `odoodev db drop`, the filestore directory is also removed (with notice in the confirmation prompt).

> **Tip:** After restore, odoodev suggests running `odoodev start -d {name} -u all` to update all modules.

> **Customer-facing reference:** A detailed, customer-ready write-up of both protection layers
> (GDPR context, full field table, audit snippets, residual risks) lives at
> [data-protection.md](data-protection.md).

### Default Credentials

- **User:** `ownerp`
- **Password:** `CHANGE_AT_FIRST` (configurable via `odoodev setup`)
