# Data Protection — Anonymization & Neutralization

> **Language / Sprache**: [DE](#deutsche-dokumentation) | [EN](#english-documentation)

---

## Deutsche Dokumentation

### Worum geht es?

Beim Restore einer Produktiv-Datenbank in eine Dev-, Test- oder Staging-Umgebung
schuetzt `odoodev db restore` die Daten **automatisch** in zwei aufeinander
aufbauenden Schichten:

| Schicht | Zweck | Risiko ohne diese Schicht |
|---------|-------|----------------------------|
| **1. Neutralisierung** (technisch) | Verhindert, dass das Test-System Aktionen nach aussen ausloest | Echte Zahlungen, E-Mails an echte Kunden, Webhooks an Produktivsysteme |
| **2. Anonymisierung** (rechtlich) | Ersetzt personenbezogene Daten durch nicht zuordenbare Werte | DSGVO-Verstoss: Verarbeitung personenbezogener Daten ohne Rechtsgrundlage |

Beide Schichten sind **standardmaessig aktiv** — sie greifen ohne weiteres
Zutun nach jedem `odoodev db restore`. Dies entspricht dem Prinzip "Privacy
by Default" und reduziert das Risiko einer versehentlichen Datenpanne.

### Rechtlicher Kontext (DSGVO)

Die automatische Anonymisierung adressiert konkret folgende Anforderungen der
EU-Datenschutz-Grundverordnung:

- **Art. 5 Abs. 1 lit. c (Datenminimierung):** In Dev/Test-Umgebungen werden
  nur die fuer den Entwicklungszweck noetigen Daten verarbeitet — Klarnamen,
  E-Mail-Adressen und Telefonnummern werden vorher entfernt.
- **Art. 25 (Privacy by Design):** Die Schutzmassnahmen sind als integrierter
  Bestandteil des Restore-Workflows verfuegbar. **Seit v0.43.0 sind sie Opt-in:**
  ein Entwickler aktiviert sie explizit per `--sanitize` (alle Schichten) oder
  einzeln per `--deactivate-cron` / `--neutralize` / `--anonymize` / `--wipe` —
  ohne Flags bleibt die restaurierte Datenbank unangetastet und die Ausgabe
  weist ausdruecklich darauf hin.
- **Art. 32 (Sicherheit der Verarbeitung):** Pseudonymisierung wird als
  empfohlene technisch-organisatorische Massnahme explizit genannt; die
  Anonymisierung geht noch einen Schritt weiter.

> **Hinweis:** Die Anonymisierung ist rechtlich keine Anonymisierung im
> strengen DSGVO-Sinn (Wiederherstellbarkeit aus dem Original-Backup
> bleibt theoretisch moeglich). Im Sprachgebrauch des Tools ist der Begriff
> als operative Pseudonymisierung des Arbeits-Datenbestands zu verstehen.

---

### Schicht 1 — Technische Neutralisierung

#### 1a) psql-Baseline (immer aktiv, kein Odoo-Boot noetig)

Direkt nach dem Import setzt `odoodev` per `psql` drei Tabellen still:

```sql
UPDATE ir_cron          SET active = false;
UPDATE ir_mail_server   SET active = false;
UPDATE fetchmail_server SET active = false;
```

Damit ist die wiederhergestellte Kopie **sofort sicher** — selbst wenn die
Schichten 1b und 2 wegen fehlender Voraussetzungen uebersprungen werden.

#### 1b) Native `odoo-bin neutralize`

Anschliessend ruft `odoodev` Odoos eingebautes Neutralisierungs-Kommando:

```bash
<venv>/bin/python <odoo>/odoo-bin neutralize -c odoo_*.conf -d <db>
```

Dieses fuehrt fuer **jedes installierte Modul** dessen `data/neutralize.sql`
aus und deckt damit weit mehr ab als die psql-Baseline:

| Bereich | Wirkung |
|---------|---------|
| Payment-Provider | Auf Testmodus / deaktiviert |
| IAP-Accounts | Tokens geleert |
| Webhooks | URLs entfernt |
| Mass-Mailing | Versand deaktiviert |
| OAuth-Tokens | Geleert |
| Banner | "NEUTRALIZED"-Hinweis im UI wird sichtbar |
| Custom-Module | Jedes Modul mit eigener `neutralize.sql` (z.B. Nextcloud-/Office365-Integration) wird mit-neutralisiert |

**Wichtige Eigenschaften:**

- `odoo-bin neutralize` bootet **keinen** Server. Es verbindet sich direkt
  per PostgreSQL und ist damit schnell und ressourcenschonend.
- **Graceful-skip:** Fehlt das venv, die `odoo-bin`-Datei oder die generierte
  `odoo_*.conf`, wird der Schritt mit Warnung uebersprungen (non-fatal).
  Die psql-Baseline aus 1a) greift trotzdem.
- Nicht installierte Module liefern keine `neutralize.sql` — Odoo
  ignoriert das stillschweigend.

**Verifikation nach Restore:**

```sql
SELECT value FROM ir_config_parameter WHERE key = 'database.is_neutralized';
-- erwartet: true
```

**Eigenstaendige Anwendung** (z.B. nachdem `repos` und `start -u all`
die Module nachinstalliert haben):

```bash
odoodev db neutralize 18 -n v18_test            # neutralisieren (inkl. Bank-Sync)
odoodev db neutralize 18 -n v18_test --stdout   # nur SQL ausgeben (Dry-Run)
```

#### 1c) Bank-Synchronisation deaktivieren (psql, ergaenzend)

Odoos `neutralize.sql` setzt **`account_journal.bank_statements_source` nicht
zurueck** und loescht `account_online_link` nicht (es markiert es nur per
`client_id = 'duplicate'`). `odoodev` ergaenzt daher — sofern die Buchhaltungs-/
Bank-Sync-Module installiert sind — folgende Bereinigung **FK-sicher** und in
**getrennten** Transaktionen:

```sql
-- 1. Journals entkoppeln + Quelle zuruecksetzen
UPDATE account_journal
   SET bank_statements_source = 'undefined',
       account_online_account_id = NULL,
       account_online_link_id = NULL;
-- 2. Kind-Datensaetze zuerst (FK), dann Eltern
DELETE FROM account_online_account;
DELETE FROM account_online_link;
```

Jedes Statement laeuft als eigener `psql`-Aufruf (eigene Transaktion) — das ist
notwendig, da das Buendeln von Journal-Update und Loeschungen in einer
Transaktion fehlschlagen kann. Spalten-/Tabellen-geprueft: fehlen die Module,
ist der Schritt ein No-Op. Laeuft unter dem `--neutralize`-Flag — auch dann,
wenn das native `odoo-bin neutralize` mangels venv uebersprungen wurde (reines
psql).

---

### Schicht 2 — DSGVO-Anonymisierung

Nach Neutralisierung ueberschreibt `odoodev` personenbezogene Daten mit
Ersatzwerten. Die Werte werden von **Faker** (`de_DE`) erzeugt und sind
**pro Datensatz-ID deterministisch geseedet** — derselbe Datensatz erhaelt
also bei jedem Lauf denselben Ersatzwert. Das ist nuetzlich fuer:

- Reproduzierbare Tests
- Wiedererkennung in Screenshots / Bug-Reports
- Vergleichbarkeit zwischen mehreren Restore-Vorgaengen

**E-Mail- und Login-Spalten werden bewusst nicht aus Faker gezogen.** Sie
werden auf reservierte, nicht zustellbare Werte gesetzt:

- E-Mails: `p{id}@example.invalid` bzw. `lead{id}@example.invalid` — die
  TLD `.invalid` ist per **RFC 2606** ausdruecklich nicht aufloesbar.
- Logins: `user{id}` — kein DNS-Lookup, keine Kollisionen mit echten Konten.

#### Vollstaendige Feldtabelle

| Tabelle | Filter | Ueberschriebene Felder | Ersatzwert |
|---------|--------|------------------------|------------|
| `res_partner` (Firmen) | `is_company = true` | name | `fake.company()` |
| | | email | `p{id}@example.invalid` |
| | | phone, mobile | `fake.phone_number()` |
| | | street, city, zip | `fake.street_address()`, `fake.city()`, `fake.postcode()` |
| | | street2, vat, website, comment | `NULL` |
| `res_partner` (Personen) | `is_company = false OR IS NULL` | name | `fake.name()` |
| | | function | `fake.job()` |
| | | (sonst wie Firmen) | |
| `crm_lead` | (alle) | contact_name, partner_name | `fake.name()`, `fake.company()` |
| | | email_from | `lead{id}@example.invalid` |
| | | phone, mobile, street, city, zip | Faker |
| | | description | `NULL` |
| `res_partner_bank` | (alle) | acc_number | `fake.iban()` |
| | | sanitized_acc_number | `NULL` |
| `hr_employee` | (alle) | name, work_email | `fake.name()`, `emp{id}@example.invalid` |
| | | work_phone, mobile_phone, private_*, identification_id, passport_id, ssnid, sinid, permit_no, visa_no, birthday, place_of_birth, country_of_birth, spouse_*, emergency_*, pin, barcode, notes, Bild-/Scan-Felder (`image_*`, `driving_license`, `has_work_permit`), … | `NULL` |
| | | children, km_home_work, distance_home_work | `0`; marital | `'single'` |
| `hr_version` (v19) | (alle) | wage | `0`; ssnid, passport_id, gender, spouse_*, … | `NULL` |
| `hr_contract` (v16/v18) | (alle) | wage | `0` |
| `employee_bank_account_rel` (v19) | (alle) | — | komplett geloescht (M2M-Verknuepfung) |
| `mail_message` | (alle) | email_from, subject | `NULL` |
| | | body | `'<p>[anonymized]</p>'` |
| `ir_attachment` | (alle) | index_content | `NULL` (Volltext-Index) |

> **Versionsrobust:** Die HR-Spalten unterscheiden sich je Odoo-Version (v16:
> Privatadresse in `res_partner`; v18: direkt auf `hr_employee`; v19: sensible
> Felder in `hr_version`). `odoodev` gleicht jede Spalte vor dem `UPDATE` gegen
> das Live-Schema ab (`information_schema`) — nicht existierende Spalten/Tabellen
> werden uebersprungen, dieselbe Konfiguration funktioniert fuer alle Versionen.

> **`res_users` wird per Default NICHT anonymisiert** — damit Logins testbar
> bleiben. Optionale Anonymisierung siehe Abschnitt
> [res_users (optional)](#res_users-optional-anonymisieren).

**Was bleibt absichtlich unveraendert:**

- **`res_users` (alle Logins und Passwoerter)** — per Default unangetastet,
  damit die Datenbank testbar bleibt (Login mit den Original-Zugangsdaten).
  Optionale Anonymisierung siehe unten.
- Strukturelle Beziehungen: Partner-IDs, Belegnummern, Buchungsketten,
  Datensatz-Zusammenhaenge bleiben vollstaendig erhalten.
- Dateien im Filestore (`~/odoo-share/filestore/{db}/`): PDFs, Bilder und
  Anhaenge selbst werden **nicht** veraendert — nur ihr Volltext-Index in
  `ir_attachment.index_content` wird geleert.

**Performance:** Die Anonymisierung schreibt in **gebuendelten** Statements
der Form

```sql
UPDATE res_partner AS t
   SET name = v.name, email = v.email, ...
  FROM (VALUES (1, 'Firma A', 'p1@example.invalid', ...),
               (2, 'Firma B', 'p2@example.invalid', ...),
               ...) AS v(id, name, email, ...)
 WHERE t.id = v.id;
```

mit einer Chunk-Groesse von 2000 Zeilen. Auch grosse Tabellen sind damit in
Sekundenbruchteilen abgearbeitet.

---

### res_users (optional) anonymisieren

Per Default bleibt `res_users` unangetastet, damit Logins testbar bleiben. Wer
auch die Benutzer anonymisieren will (z.B. fuer ein Staging-System mit
breiterem Zugriff), nutzt das Opt-in-Flag:

```bash
odoodev db restore 18 -n v18_test --anonymize-users
odoodev db restore 18 -n v18_test --anonymize-users --user-password geheim123
```

Wirkung (nur Nicht-System-Konten, `admin`/id=1 + technische Logins bleiben
unberuehrt):

- **Login** → `user{id}`
- **Passwort** → ein gemeinsames Dev-Passwort (Default `ownerp`), gespeichert
  als Odoo-kompatibler `pbkdf2_sha512`-Hash. Damit bleibt jeder Benutzer
  einloggbar: `user<id>` / `ownerp`. `admin` behaelt sein Original-Passwort.

Der Hash wird mit der Python-Standardbibliothek erzeugt (keine
Zusatzabhaengigkeit). Seit v0.43.0 eigenstaendig nutzbar — `--anonymize-users`
setzt kein `--anonymize` mehr voraus.

---

### Ablauf beim Restore

`odoodev db restore` fuehrt die (jeweils per Flag aktivierten) Schritte in
dieser Reihenfolge aus:

1. `deactivate_cronjobs()` — psql-Baseline (Schicht 1a, `--deactivate-cron`)
2. `run_neutralize()` — natives `odoo-bin neutralize` (Schicht 1b, `--neutralize`)
3. `neutralize_bank_sync()` — Bank-Sync-Bereinigung (Schicht 1c, unter `--neutralize`)
4. `anonymize_database()` — Faker-Anonymisierung inkl. HR (Schicht 2, `--anonymize`)
5. `wipe_database()` — Inhalte loeschen (Schicht 2b, `--wipe`)
6. `anonymize_users()` — nur bei `--anonymize-users` (optional)

Jeder Schritt ist **eigenstaendig abschaltbar** und **non-fatal**: schlaegt
ein Schritt fehl oder fehlt eine Voraussetzung, wird mit Warnung
weitergemacht — der Restore endet trotzdem mit "Database restore complete".

#### Flags und Defaults

| Flag | Default | Wirkung |
|------|---------|---------|
| `--sanitize` | **aus** | Sammel-Flag: aktiviert deactivate-cron + neutralize + anonymize + wipe; explizite `--no-*` gewinnen |
| `--deactivate-cron` / `--no-deactivate-cron` | **aus** | Schicht 1a (Cron/Mail/Fetchmail stilllegen) |
| `--neutralize` / `--no-neutralize` | **aus** | Schicht 1b + 1c (`odoo-bin neutralize` + Bank-Sync) |
| `--anonymize` / `--no-anonymize` | **aus** | Schicht 2 (Faker-Anonymisierung inkl. HR — nur Ersatzwerte) |
| `--wipe` / `--no-wipe` | **aus** | Schicht 2b (Inhalte loeschen: mail_message, ir_attachment-Index, Verknuepfungstabellen) |
| `--anonymize-users` / `--no-anonymize-users` | **aus** | Zusaetzlich `res_users` (Login + Dev-Passwort); NICHT in `--sanitize` enthalten |
| `--user-password TEXT` | `ownerp` | Dev-Passwort fuer anonymisierte Benutzer |

**Seit v0.43.0 sind alle Schichten Opt-in** — ohne Flags bleibt die Datenbank
unangetastet. Fuer den Standardfall „Produktions-Backup entschaerfen" genuegt
`--sanitize`; die Entscheidung liegt explizit beim Entwickler.

---

### Audit und Stichproben-Verifikation

Nach dem Restore koennen Sie folgende SQL-Abfragen ausfuehren, um die
Wirksamkeit der Massnahmen zu pruefen:

```sql
-- 1) Neutralisierungsbanner aktiv?
SELECT value FROM ir_config_parameter WHERE key = 'database.is_neutralized';

-- 2) Alle Cron-Jobs deaktiviert?
SELECT count(*) AS aktive_crons FROM ir_cron WHERE active = true;
-- erwartet: 0

-- 3) Mail- und Fetchmail-Server deaktiviert?
SELECT count(*) FROM ir_mail_server   WHERE active = true;  -- erwartet: 0
SELECT count(*) FROM fetchmail_server WHERE active = true;  -- erwartet: 0

-- 4) Partner-Mails alle auf .invalid?
SELECT count(*) FROM res_partner
 WHERE email IS NOT NULL AND email NOT LIKE '%@example.invalid';
-- erwartet: 0

-- 5) Bank-Sync deaktiviert?
SELECT DISTINCT bank_statements_source FROM account_journal;  -- erwartet: nur 'undefined'
SELECT count(*) FROM account_online_link;                      -- erwartet: 0

-- 6) Mitarbeiterdaten anonymisiert?
SELECT count(*) FROM hr_employee
 WHERE work_email IS NOT NULL AND work_email NOT LIKE '%@example.invalid';
-- erwartet: 0

-- 7) NUR bei --anonymize-users: echte Nicht-System-Logins entfernt?
SELECT login FROM res_users
 WHERE id > 1 AND login NOT IN ('admin', '__system__', 'default', 'public', 'portaltemplate')
   AND login NOT LIKE 'user%';
-- erwartet: keine Zeilen (ohne --anonymize-users bleiben die Original-Logins erhalten)
```

---

### Grenzen und Restrisiken

Die folgenden Punkte sollten Sie bei der Beurteilung des Datenschutzniveaus
beachten:

- **Custom-Felder werden nicht automatisch erkannt.** Wenn ein Modul
  zusaetzliche personenbezogene Felder einfuehrt (z.B. `x_geburtsdatum`,
  `x_ausweisnummer`), bleiben diese unveraendert. Hier ist eine manuelle
  Erweiterung des Anonymisierungs-Profils noetig.
- **Filestore-Dateien bleiben unangetastet.** Hochgeladene PDFs, Bilder
  oder Vertragsdokumente enthalten weiterhin Originaldaten. Bei besonders
  sensiblen Bestaenden ist das Filestore-Verzeichnis nach dem Restore
  separat zu bereinigen.
- **Quell-Backups enthalten weiterhin Originaldaten.** Die ZIP-/SQL-Datei,
  aus der wiederhergestellt wurde, muss nach dem Restore sicher abgelegt
  oder geloescht werden — die Anonymisierung wirkt nur in der
  Ziel-Datenbank.
- **Volltext-Suche ueber alte Anhaenge** funktioniert nach dem Leeren von
  `ir_attachment.index_content` nicht mehr. Bei Bedarf laesst sich der
  Index per Odoo neu aufbauen.
- **Reproduzierbarkeit als Feature, nicht als Schwaeche:** Da die
  Ersatzwerte per `id` deterministisch sind, lassen sich Original-IDs
  bei vorhandenem Backup theoretisch wieder zuordnen. Dies ist gewollt
  (Reproduzierbarkeit fuer Bug-Reports), aendert jedoch die
  rechtliche Einordnung Richtung "Pseudonymisierung" statt strenger
  Anonymisierung.

---

### Login nach Restore

Da `res_users` per Default **nicht** anonymisiert wird, bleiben die
**Original-Logins und -Passwoerter** der wiederhergestellten Datenbank gueltig —
ein Login ist also wie in der Produktiv-Datenbank moeglich (z.B. mit dem
`admin`-Account).

Wurde `--anonymize-users` gesetzt, sind nur noch folgende Logins moeglich:

- `admin` (id=1) — unveraendert, Original-Passwort
- alle anderen Benutzer: `user<id>` / das Dev-Passwort (Default `ownerp`)

> **Hinweis:** `ownerp` / `CHANGE_AT_FIRST` sind die PostgreSQL-Verbindungs-
> Credentials des Dev-Setups (konfigurierbar via `odoodev setup`) — **nicht**
> die Odoo-Login-Daten.

---

## English Documentation

### What is this about?

When restoring a production database into a development, test or staging
environment, `odoodev db restore` **automatically** protects the data in
two stacked layers:

| Layer | Purpose | Risk without this layer |
|-------|---------|--------------------------|
| **1. Neutralization** (technical) | Prevents the restored copy from triggering external actions | Real payments, e-mails to real customers, webhooks to production systems |
| **2. Anonymization** (legal) | Replaces personal data with non-attributable values | GDPR breach: processing of personal data without legal basis |

Both layers are **on by default** — they run after every `odoodev db
restore` without any extra opt-in. This follows the "Privacy by Default"
principle and minimizes the risk of an accidental data leak.

### Legal context (GDPR)

The automatic anonymization addresses these specific requirements of the
EU General Data Protection Regulation:

- **Art. 5(1)(c) (Data minimization):** Dev/test environments only process
  the data needed for their development purpose — real names, e-mail
  addresses and phone numbers are stripped beforehand.
- **Art. 25 (Privacy by Design):** Protective measures are available as an
  integrated part of the restore workflow. **Since v0.43.0 they are opt-in:**
  a developer enables them explicitly via `--sanitize` (all layers) or
  individually via `--deactivate-cron` / `--neutralize` / `--anonymize` /
  `--wipe` — without flags the restored database is left untouched and the
  output explicitly says so.
- **Art. 32 (Security of processing):** Pseudonymization is explicitly
  listed as a recommended technical and organizational measure; this tool
  goes one step further.

> **Note:** Strictly speaking this is not GDPR anonymization (re-identification
> from the original backup remains theoretically possible). In the tool's
> language the term refers to operational pseudonymization of the working
> dataset.

---

### Layer 1 — Technical neutralization

#### 1a) psql baseline (always on, no Odoo boot required)

Immediately after the import, `odoodev` quiets three tables via plain `psql`:

```sql
UPDATE ir_cron          SET active = false;
UPDATE ir_mail_server   SET active = false;
UPDATE fetchmail_server SET active = false;
```

This makes the restored copy **immediately safe** — even if layers 1b and 2
are skipped because of missing prerequisites.

#### 1b) Native `odoo-bin neutralize`

Next, `odoodev` calls Odoo's built-in neutralization command:

```bash
<venv>/bin/python <odoo>/odoo-bin neutralize -c odoo_*.conf -d <db>
```

This runs **every installed module's** `data/neutralize.sql`, covering far
more than the psql baseline:

| Area | Effect |
|------|--------|
| Payment providers | Set to test mode / disabled |
| IAP accounts | Tokens cleared |
| Webhooks | URLs removed |
| Mass mailing | Sending disabled |
| OAuth tokens | Cleared |
| Banner | "NEUTRALIZED" notice becomes visible in the UI |
| Custom modules | Any module shipping its own `neutralize.sql` (e.g. Nextcloud / Office365 integration) is neutralized too |

**Key properties:**

- `odoo-bin neutralize` boots **no** server. It connects directly via
  PostgreSQL — fast and resource-friendly.
- **Graceful skip:** if the venv, the `odoo-bin` binary or the generated
  `odoo_*.conf` is missing, the step is skipped with a warning (non-fatal).
  The psql baseline from 1a) still applies.
- Modules that are not installed simply do not ship a `neutralize.sql` —
  Odoo silently ignores them.

**Verification after restore:**

```sql
SELECT value FROM ir_config_parameter WHERE key = 'database.is_neutralized';
-- expected: true
```

**Standalone usage** (e.g. once `repos` and `start -u all` have populated
the modules):

```bash
odoodev db neutralize 18 -n v18_test            # neutralize (incl. bank sync)
odoodev db neutralize 18 -n v18_test --stdout   # print SQL only (dry run)
```

#### 1c) Disable bank synchronisation (psql, supplementary)

Odoo's `neutralize.sql` does **not** reset `account_journal.bank_statements_source`
and does not delete `account_online_link` (it only marks it via
`client_id = 'duplicate'`). When the accounting / bank-sync modules are
installed, `odoodev` therefore adds this cleanup **FK-safely** and in
**separate** transactions:

```sql
-- 1. detach journals + reset source
UPDATE account_journal
   SET bank_statements_source = 'undefined',
       account_online_account_id = NULL,
       account_online_link_id = NULL;
-- 2. child rows first (FK), then parents
DELETE FROM account_online_account;
DELETE FROM account_online_link;
```

Each statement runs as its own `psql` call (separate transaction) — required
because bundling the journal update and the deletes in one transaction can
fail. Column/table guarded: if the modules are absent it is a no-op. Runs under
the `--neutralize` flag — even when native `odoo-bin neutralize` was skipped for
lack of a venv (pure psql).

---

### Layer 2 — GDPR anonymization

After neutralization, `odoodev` overwrites personal data with replacement
values. The values are generated by **Faker** (`de_DE`) and are
**deterministically seeded per row id** — the same row always receives the
same replacement value. This is useful for:

- Reproducible tests
- Recognizability in screenshots / bug reports
- Comparability across multiple restore runs

**E-mail and login columns are deliberately not taken from Faker.** They
are forced onto reserved, non-deliverable values:

- E-mails: `p{id}@example.invalid` or `lead{id}@example.invalid` — the
  TLD `.invalid` is explicitly non-resolvable per **RFC 2606**.
- Logins: `user{id}` — no DNS lookup, no clashes with real accounts.

#### Complete field table

| Table | Filter | Overwritten fields | Replacement value |
|-------|--------|--------------------|-------------------|
| `res_partner` (companies) | `is_company = true` | name | `fake.company()` |
| | | email | `p{id}@example.invalid` |
| | | phone, mobile | `fake.phone_number()` |
| | | street, city, zip | `fake.street_address()`, `fake.city()`, `fake.postcode()` |
| | | street2, vat, website, comment | `NULL` |
| `res_partner` (persons) | `is_company = false OR IS NULL` | name | `fake.name()` |
| | | function | `fake.job()` |
| | | (rest same as companies) | |
| `crm_lead` | (all) | contact_name, partner_name | `fake.name()`, `fake.company()` |
| | | email_from | `lead{id}@example.invalid` |
| | | phone, mobile, street, city, zip | Faker |
| | | description | `NULL` |
| `res_partner_bank` | (all) | acc_number | `fake.iban()` |
| | | sanitized_acc_number | `NULL` |
| `hr_employee` | (all) | name, work_email | `fake.name()`, `emp{id}@example.invalid` |
| | | work_phone, mobile_phone, private_*, identification_id, passport_id, ssnid, sinid, permit_no, visa_no, birthday, place_of_birth, country_of_birth, spouse_*, emergency_*, pin, barcode, notes, image/scan fields (`image_*`, `driving_license`, `has_work_permit`), … | `NULL` |
| | | children, km_home_work, distance_home_work | `0`; marital | `'single'` |
| `hr_version` (v19) | (all) | wage | `0`; ssnid, passport_id, gender, spouse_*, … | `NULL` |
| `hr_contract` (v16/v18) | (all) | wage | `0` |
| `employee_bank_account_rel` (v19) | (all) | — | deleted entirely (M2M link) |
| `mail_message` | (all) | email_from, subject | `NULL` |
| | | body | `'<p>[anonymized]</p>'` |
| `ir_attachment` | (all) | index_content | `NULL` (full-text index) |

> **Version robust:** HR columns differ per Odoo version (v16: private address
> on `res_partner`; v18: directly on `hr_employee`; v19: sensitive fields on
> `hr_version`). `odoodev` matches every column against the live schema
> (`information_schema`) before the `UPDATE` — non-existing columns/tables are
> skipped, so the same configuration works across all versions.

> **`res_users` is NOT anonymized by default** — so logins stay testable.
> For optional anonymization see [res_users (optional)](#res_users-optional).

**What deliberately stays untouched:**

- **`res_users` (all logins and passwords)** — left intact by default so the
  database stays testable (log in with the original credentials). Optional
  anonymization see below.
- Structural relations: partner IDs, document numbers, posting chains
  and record links remain fully intact.
- Files in the filestore (`~/odoo-share/filestore/{db}/`): PDFs, images
  and attachments themselves are **not** modified — only their full-text
  index in `ir_attachment.index_content` is cleared.

**Performance:** Anonymization writes in **bundled** statements of the form

```sql
UPDATE res_partner AS t
   SET name = v.name, email = v.email, ...
  FROM (VALUES (1, 'Company A', 'p1@example.invalid', ...),
               (2, 'Company B', 'p2@example.invalid', ...),
               ...) AS v(id, name, email, ...)
 WHERE t.id = v.id;
```

with a chunk size of 2000 rows. Even large tables are processed in
fractions of a second.

---

### res_users (optional)

By default `res_users` stays untouched so logins remain testable. To also
anonymize the users (e.g. for a staging system with broader access), use the
opt-in flag:

```bash
odoodev db restore 18 -n v18_test --anonymize-users
odoodev db restore 18 -n v18_test --anonymize-users --user-password secret123
```

Effect (non-system accounts only; `admin`/id=1 + technical logins stay intact):

- **login** → `user{id}`
- **password** → one shared dev password (default `ownerp`), stored as an
  Odoo-compatible `pbkdf2_sha512` hash. Every user stays loginable as
  `user<id>` / `ownerp`; `admin` keeps its original password.

The hash is generated with the Python standard library (no extra
dependency). Standalone since v0.43.0 — `--anonymize-users` no longer
requires `--anonymize`.

---

### Restore flow

`odoodev db restore` executes the flag-enabled steps in this order:

1. `deactivate_cronjobs()` — psql baseline (layer 1a, `--deactivate-cron`)
2. `run_neutralize()` — native `odoo-bin neutralize` (layer 1b, `--neutralize`)
3. `neutralize_bank_sync()` — bank-sync cleanup (layer 1c, under `--neutralize`)
4. `anonymize_database()` — Faker anonymization incl. HR (layer 2, `--anonymize`)
5. `wipe_database()` — content deletion (layer 2b, `--wipe`)
6. `anonymize_users()` — only with `--anonymize-users` (optional)

Each step is **independently switchable** and **non-fatal**: if a step
fails or a prerequisite is missing, processing continues with a warning —
the restore still ends with "Database restore complete".

#### Flags and defaults

| Flag | Default | Effect |
|------|---------|--------|
| `--sanitize` | **off** | Convenience flag: enables deactivate-cron + neutralize + anonymize + wipe; explicit `--no-*` flags win |
| `--deactivate-cron` / `--no-deactivate-cron` | **off** | Layer 1a (quiet cron / mail / fetchmail) |
| `--neutralize` / `--no-neutralize` | **off** | Layer 1b + 1c (`odoo-bin neutralize` + bank sync) |
| `--anonymize` / `--no-anonymize` | **off** | Layer 2 (Faker anonymization incl. HR — replacement values only) |
| `--wipe` / `--no-wipe` | **off** | Layer 2b (content deletion: mail_message, ir_attachment index, linkage tables) |
| `--anonymize-users` / `--no-anonymize-users` | **off** | Additionally `res_users` (login + dev password); NOT included in `--sanitize` |
| `--user-password TEXT` | `ownerp` | Dev password set on anonymized users |

**Since v0.43.0 every layer is opt-in** — without flags the database is left
untouched. For the standard "defuse a production backup" case, `--sanitize`
is enough; the decision sits explicitly with the developer.

---

### Audit and sample verification

After the restore you can run the following SQL queries to verify the
effectiveness of the measures:

```sql
-- 1) Neutralization flag set?
SELECT value FROM ir_config_parameter WHERE key = 'database.is_neutralized';

-- 2) All cron jobs disabled?
SELECT count(*) AS active_crons FROM ir_cron WHERE active = true;
-- expected: 0

-- 3) Mail and fetchmail servers disabled?
SELECT count(*) FROM ir_mail_server   WHERE active = true;  -- expected: 0
SELECT count(*) FROM fetchmail_server WHERE active = true;  -- expected: 0

-- 4) All partner e-mails on .invalid?
SELECT count(*) FROM res_partner
 WHERE email IS NOT NULL AND email NOT LIKE '%@example.invalid';
-- expected: 0

-- 5) Bank sync disabled?
SELECT DISTINCT bank_statements_source FROM account_journal;  -- expected: only 'undefined'
SELECT count(*) FROM account_online_link;                      -- expected: 0

-- 6) Employee data anonymized?
SELECT count(*) FROM hr_employee
 WHERE work_email IS NOT NULL AND work_email NOT LIKE '%@example.invalid';
-- expected: 0

-- 7) ONLY with --anonymize-users: real non-system logins removed?
SELECT login FROM res_users
 WHERE id > 1 AND login NOT IN ('admin', '__system__', 'default', 'public', 'portaltemplate')
   AND login NOT LIKE 'user%';
-- expected: no rows (without --anonymize-users the original logins are kept)
```

---

### Limits and residual risks

Please consider the following points when judging the data-protection level:

- **Custom fields are not detected automatically.** If a module introduces
  additional personal-data fields (e.g. `x_birthdate`, `x_id_card_no`), those
  remain unchanged. Manual extension of the anonymization profile is
  required in that case.
- **Filestore files are left alone.** Uploaded PDFs, images and contract
  documents still contain original data. For particularly sensitive
  contents the filestore directory must be cleaned up separately after
  the restore.
- **Source backups still contain original data.** The ZIP/SQL file the
  restore came from must be stored securely or deleted after the
  restore — the anonymization only takes effect inside the target
  database.
- **Full-text search over old attachments** no longer works after clearing
  `ir_attachment.index_content`. If needed, the index can be rebuilt by
  Odoo.
- **Reproducibility is a feature, not a weakness:** because replacement
  values are deterministic per `id`, original IDs could theoretically be
  re-mapped if the backup is still available. This is intended (for
  reproducible bug reports) but shifts the legal classification toward
  "pseudonymization" rather than strict anonymization.

---

### Login after restore

Because `res_users` is **not** anonymized by default, the **original logins and
passwords** of the restored database stay valid — you log in just like in
production (e.g. with the `admin` account).

If `--anonymize-users` was passed, only these logins remain:

- `admin` (id=1) — unchanged, original password
- all other users: `user<id>` / the dev password (default `ownerp`)

> **Note:** `ownerp` / `CHANGE_AT_FIRST` are the PostgreSQL connection
> credentials of the dev setup (configurable via `odoodev setup`) — **not** the
> Odoo login credentials.
