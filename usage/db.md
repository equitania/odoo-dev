# Database Operations

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

### Datenbankoperationen

```bash
# Datenbanken auflisten
odoodev db list 18

# Backup erstellen (interaktiv)
odoodev db backup 18

# Backup als SQL-Dump
odoodev db backup 18 -n v18_exam -t sql -o /tmp

# Backup als ZIP mit Filestore
odoodev db backup 18 -n v18_exam -t zip -o /tmp

# Backup wiederherstellen
odoodev db restore 18 -n v18_test -z backup.zip

# Datenbank loeschen
odoodev db drop 18 -n v18_test

# Datenbank loeschen ohne Bestaetigungsprompt
odoodev db drop 18 -n v18_test --yes
```

### Interaktiver Modus

Wenn Flags weggelassen werden, fragt odoodev interaktiv nach:

- `odoodev db backup 18` → Auswahl der Datenbank und des Backup-Typs
- `odoodev db restore 18` → Eingabe des Dateipfads und Datenbanknamens (mit Vorschlag aus Dateiname)
- `odoodev db drop 18` → Auswahl der Datenbank aus Liste

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

**Post-Restore Deaktivierungen:**
- Cron-Jobs (`ir_cron.active = false`)
- Mail-Server (`ir_mail_server.active = false`)
- Fetchmail-Server (`fetchmail_server.active = false`)
- Nextcloud-Integration (Config-Parameter geleert)
- Office365-Integration (Config-Parameter geleert)

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
| `res_users` | Login (`user{id}`), Passwort (geleert) — **System/Admin bleiben unveraendert** |
| `crm_lead` | Kontakt-/Firmenname, E-Mail, Telefon/Mobil, Adresse, Beschreibung |
| `res_partner_bank` | Kontonummer (Fake-IBAN), bereinigte Kontonummer |
| `mail_message` | `email_from`, Betreff (geleert), Body (Platzhalter) |
| `ir_attachment` | `index_content` (Volltext-Index geleert) |

> **Hinweis:** Nicht-System-Benutzer haben danach kein Passwort und den Login `user{id}`.
> Der `admin`-Login bleibt nutzbar. Nicht installierte Module (fehlende Tabellen) werden
> uebersprungen (non-fatal).

```bash
odoodev db restore 18 -n v18_test -z prod_backup.zip          # anonymisiert (Default)
odoodev db restore 18 -n v18_test -z prod_backup.zip --no-anonymize   # Rohdaten behalten
```

Bei `odoodev db drop` wird der Filestore-Ordner ebenfalls entfernt (mit Hinweis in der Bestaetigungsabfrage).

> **Tipp:** Nach dem Restore empfiehlt odoodev `odoodev start -d {name} -u all` um alle Module zu aktualisieren.

### Standard-Credentials

- **Benutzer:** `ownerp`
- **Passwort:** `CHANGE_AT_FIRST` (konfigurierbar via `odoodev setup`)

---

## English Documentation

### Database Operations

```bash
# List databases
odoodev db list 18

# Create backup (interactive)
odoodev db backup 18

# Backup as SQL dump
odoodev db backup 18 -n v18_exam -t sql -o /tmp

# Backup as ZIP with filestore
odoodev db backup 18 -n v18_exam -t zip -o /tmp

# Restore backup
odoodev db restore 18 -n v18_test -z backup.zip

# Drop database
odoodev db drop 18 -n v18_test

# Drop database without confirmation prompt
odoodev db drop 18 -n v18_test --yes
```

### Interactive Mode

When flags are omitted, odoodev prompts interactively:

- `odoodev db backup 18` → Select database and backup type
- `odoodev db restore 18` → Enter file path and database name (with suggestion from filename)
- `odoodev db drop 18` → Select database from list

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

**Post-restore deactivations:**
- Cron jobs (`ir_cron.active = false`)
- Mail servers (`ir_mail_server.active = false`)
- Fetchmail servers (`fetchmail_server.active = false`)
- Nextcloud integration (config parameters cleared)
- Office365 integration (config parameters cleared)

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
| `res_users` | login (`user{id}`), password (cleared) — **system/admin left untouched** |
| `crm_lead` | contact/company name, email, phone/mobile, address, description |
| `res_partner_bank` | account number (fake IBAN), sanitized account number |
| `mail_message` | `email_from`, subject (cleared), body (placeholder) |
| `ir_attachment` | `index_content` (full-text index cleared) |

> **Note:** Non-system users end up with no password and the login `user{id}`. The `admin`
> login stays usable. Tables of uninstalled modules are skipped (non-fatal).

```bash
odoodev db restore 18 -n v18_test -z prod_backup.zip          # anonymized (default)
odoodev db restore 18 -n v18_test -z prod_backup.zip --no-anonymize   # keep raw data
```

When running `odoodev db drop`, the filestore directory is also removed (with notice in the confirmation prompt).

> **Tip:** After restore, odoodev suggests running `odoodev start -d {name} -u all` to update all modules.

### Default Credentials

- **User:** `ownerp`
- **Password:** `CHANGE_AT_FIRST` (configurable via `odoodev setup`)
