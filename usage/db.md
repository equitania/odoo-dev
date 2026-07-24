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

# Mehrere Datenbanken auf einmal (Checkbox-Mehrfachauswahl)
odoodev db drop 18 -m

# Alle Test-Datenbanken aufraeumen (Namensfilter)
odoodev db drop 18 --all --filter test_

# Mehrere explizit, offene Verbindungen vorher beenden
odoodev db drop 18 -n v18_a -n v18_b --terminate-connections
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
| 7z | `.7z`-Endung | Verwendet `7zz`-, `7z`- oder `7za`-Binary (Debians `p7zip` liefert `7za`) |
| tar.zst | `.tar.zst`-Endung | Stream-Backup (`container2backup` v4.7.0+); gestreamt per `zstd \| tarfile`, benoetigt die `zstd`-CLI |
| tar/tgz/tar.gz | `.tar`/`.tgz`-Endung oder `.tar.gz`-Suffix | Komprimiertes Archiv; `.tar.gz` wird explizit als tar erkannt |
| gz | `.gz`-Endung (kein tar) | Gunzip zu dump.sql |
| SQL | `.sql` oder `.dump`-Endung | Direkter SQL-Import |

### Filestore-Verwaltung

**Filestore-Pfad:** `~/odoo-share/filestore/{db_name}/`

Bei `odoodev db restore` wird der Filestore automatisch verwaltet:

1. **Speicherplatz-Vorpruefung** (`--check-space`, Default an): die entpackte Groesse wird
   geschaetzt (ZIP exakt, komprimierte Formate konservativ `Groesse × 3`) und gegen den freien
   Platz auf Temp- und Filestore-Dateisystem geprueft. Bei Knappheit: Warnung mit konkreten
   Zahlen + Rueckfrage „Continue anyway?" (Default Nein). Abschaltbar mit `--no-check-space`.
2. Backup wird extrahiert (ZIP, 7z, tar, tar.zst, gz, SQL)
3. SQL-Dump wird in neue Datenbank eingespielt
4. Filestore wird nach `~/odoo-share/filestore/{db_name}/` **verschoben** (`shutil.move` —
   Rename auf demselben Dateisystem = instant, keine doppelte Datenhaltung). Mit `--keep-temp`
   wird stattdessen kopiert, damit das entpackte Temp-Verzeichnis zum Debuggen erhalten bleibt.
5. Optional am Ende: Rueckfrage „Delete original backup file?" (Default Nein — ein Backup wird
   nie automatisch geloescht). Steuerbar per `--delete-backup` (loeschen ohne Frage) und
   `--keep-backup` (nie fragen/loeschen, fuer Skripte).

**Dry-Run** (`--dry-run`, seit v0.61.0): fuehrt nichts davon aus. odoodev prueft nur
Backup-Datei, Ziel-Datenbank (Kollision bzw. Drop) und Speicherplatz, listet die geplanten
Post-Restore-Schritte auf und beendet sich mit Exit-Code 0 (Restore wuerde durchlaufen)
bzw. 1 (wuerde fehlschlagen). Grundlage des Dry-Run-Buttons im Restore-Wizard der GUI.

### Filestore-Konsistenz-Check (`db cleanup`, seit v0.60.0)

Vergleicht das Filestore-Verzeichnis der Version (`~/odoo-share/vXX/filestore/`)
mit den Datenbanken auf ihrer PostgreSQL-Instanz — in beide Richtungen:

```bash
odoodev db cleanup 18                     # Nur Bericht (loescht nichts)
odoodev db cleanup 18 --delete-orphans    # Verwaiste Filestores loeschen (y/N-Rueckfrage)
odoodev db cleanup 18 --delete-orphans -y # ... ohne Rueckfrage (Skripte)
odoodev db cleanup 18 --json              # Maschinenlesbar (GUI/Agent, nie loeschend)
```

- **Verwaiste Filestores** (Verzeichnis ohne zugehoerige Datenbank): werden mit
  Groesse gelistet; Loeschung nur mit explizitem `--delete-orphans` nach einer
  y/N-Bestaetigung (Default Nein).
- **Datenbanken ohne Filestore**: werden nur gemeldet — eine frische Datenbank
  oder eine ohne Anhaenge hat legitimerweise keinen Filestore.
- Ein aktiver Migrations-Modus wird beruecksichtigt (geteiltes Filestore-Verzeichnis
  via `get_filestore_path`).

### Post-Restore-Verarbeitung: alles Opt-in (seit v0.43.0)

**Standardmaessig laesst `db restore` die wiederhergestellte Datenbank komplett unangetastet** —
jede Nachbehandlung muss explizit per Flag angefordert werden:

| Flag | Wirkung |
|------|---------|
| `--deactivate-cron` | Cron-Jobs, Mail- und Fetchmail-Server deaktivieren (psql-Baseline) |
| `--neutralize` | Natives `odoo-bin neutralize` + Bank-Sync-Bereinigung |
| `--anonymize` | DSGVO-Anonymisierung mit Faker (nur Ersatzwerte, keine Loeschung) |
| `--wipe` | Inhalte loeschen: mail_message, ir_attachment-Index, Verknuepfungstabellen |
| `--sanitize` | Sammel-Flag: aktiviert alle vier obigen auf einmal; explizite `--no-*` gewinnen |
| `--anonymize-users` | `res_users` anonymisieren — eigenstaendig, NICHT in `--sanitize` enthalten |
| `--purge-transactions` | Transaktionsdaten loeschen (Lager/Verkauf/Einkauf/Buchhaltung/MRP/POS) fuer eine saubere Stresstest-DB — eigenstaendig, NICHT in `--sanitize` enthalten (seit v0.44.0) |
| `--recompute` | Stored-Computed-Felder neu berechnen (z.B. `complete_name`) — automatisch nach `--anonymize`, abschaltbar mit `--no-recompute` (seit v0.44.0) |
| `--uninstall-modules` | Module VOR den Sanitize-Schritten deinstallieren (kommagetrennte technische Namen); ohne Flag fragt der interaktive Modus nach, wenn ein Sanitize-Schritt aktiv ist (seit v0.45.0) |
| `-y/--yes` | Interaktive Rueckfragen ueberspringen (Modul-Abfrage, Fehler-Bestaetigung) — fuer Skripte (seit v0.45.0) |

Ohne Flags weist die Ausgabe darauf hin, dass die Datenbank unangetastet blieb.

```bash
odoodev db restore 18 -n v18_test -z prod.zip                  # nur restore, DB unveraendert
odoodev db restore 18 -n v18_test -z prod.zip --sanitize        # Template-Reset: anonymisieren + Bewegungs-/Kundendaten LOESCHEN (v0.48.0)
odoodev db restore 18 -n v18_test -z prod.zip --sanitize --no-purge-master-data  # nur anonymisieren (altes --sanitize)
odoodev db restore 18 -n v18_test -z prod.zip --neutralize      # nur neutralisieren
odoodev db restore 18 -n v18_test -z prod.zip --sanitize --no-wipe  # alles ausser Inhalts-Loeschung

# Template-DB-Reset auf einer bereits wiederhergestellten DB (eigenstaendig)
odoodev db purge-master-data 18 -n v18_test --dry-run           # Vorschau, loescht nichts
odoodev db purge-master-data 18 -n v18_test -y                  # ausfuehren ohne Rueckfrage
```

**Cron-/Mail-Deaktivierung (`--deactivate-cron`, psql-Baseline):**
- Cron-Jobs (`ir_cron.active = false`)
- Mail-Server (`ir_mail_server.active = false`)
- Fetchmail-Server (`fetchmail_server.active = false`)

Die psql-Baseline braucht kein lauffaehiges Odoo und stellt sicher, dass eine restored
Prod-Kopie keine Crons/Mails ausloest.

### Native Neutralisierung (`odoo-bin neutralize`, Opt-in via `--neutralize`)

Mit `--neutralize` ruft `odoodev db restore` nach dem Import Odoos eingebautes `odoo-bin
neutralize` auf. Das fuehrt pro installiertem Modul dessen `data/neutralize.sql` aus und deckt
damit weit mehr ab als die psql-Baseline: **Payment-Provider, IAP-Accounts, Webhooks,
Mass-Mailing, OAuth-Tokens, das „NEUTRALIZED"-Banner** sowie jedes Custom-Modul mit eigener
`neutralize.sql` (inkl. der hauseigenen Nextcloud-/Office365-Module — daher gibt es keine
separate Cloud-Deaktivierung mehr).

- **Opt-in** (seit v0.43.0; in `--sanitize` enthalten).
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

### DSGVO-Anonymisierung (Opt-in via `--anonymize` / `--wipe`)

Mit `--anonymize` anonymisiert `odoodev db restore` personenbezogene Daten direkt nach dem
Import (DSGVO Art. 5 Datenminimierung). Seit v0.43.0 ist die **Loeschung von Inhalten ein
eigenes Flag `--wipe`** (mail_message-Inhalte, ir_attachment-Volltextindex,
Verknuepfungstabellen) — `--anonymize` ersetzt nur noch Werte, loescht aber nichts.

Die Ersatzwerte werden mit **Faker** (`de_DE`, pro Datensatz-ID geseedet → reproduzierbar)
erzeugt. E-Mail- und Login-Felder werden bewusst **nicht** aus Faker generiert, sondern auf
reservierte, nicht zustellbare Werte gesetzt (`p{id}@example.invalid`, `user{id}`).

| Tabelle | Flag | Wirkung |
|---------|------|---------|
| `res_partner` | `--anonymize` | Name (Firmen → `fake.company()`, Personen → `fake.name()`), E-Mail, Telefon/Mobil, Adresse, USt-IdNr., Website, Notiz, Funktion (nur Personen) |
| `crm_lead` | `--anonymize` | Kontakt-/Firmenname, E-Mail, Telefon/Mobil, Adresse, Beschreibung |
| `res_partner_bank` | `--anonymize` | Kontonummer (Fake-IBAN), bereinigte Kontonummer |
| `hr_employee` | `--anonymize` | Name, Work-E-Mail, Telefon, Privatadresse, Ausweis-/Pass-/SV-Nummern, Geburtsdaten, Ehepartner-/Notfalldaten, PIN/Barcode, Notizen, Bild-/Scan-Felder; Gehalt-/km-Felder → 0 |
| `hr_version` (v19) / `hr_contract` (v16/v18) | `--anonymize` | Gehalt (`wage` → 0), sensible Personaldaten (v19) |
| `employee_bank_account_rel` (v19) | `--wipe` | M2M-Verknuepfung komplett geloescht |
| `mail_message` | `--wipe` | `email_from`, Betreff (geleert), Body (Platzhalter) |
| `ir_attachment` | `--wipe` | `index_content` (Volltext-Index geleert) |

> **`res_users` wird per Default NICHT anonymisiert** — Logins bleiben testbar. Opt-in via
> `--anonymize-users` (Login → `user{id}`, Passwort → Dev-Passwort `--user-password`, Default
> `ownerp`; `admin` bleibt unveraendert). HR-Spalten werden gegen das Live-Schema gefiltert,
> daher versionsrobust (v16/v18/v19). Fehlende Tabellen/Spalten werden uebersprungen (non-fatal).

> **Seit v0.44.0: Stored-Computed-Felder werden nachgerechnet.** Die Anonymisierung schreibt per
> Raw-SQL direkt in `res_partner.name` & Co. Am ORM vorbei bleibt das gespeicherte
> `complete_name` (von dem das live berechnete `display_name` abhaengt) sonst auf dem
> Originalwert stehen — Kanban-Karten und Listenspalten (z.B. der Partner in
> Rechnungsuebersichten) zeigten dann weiterhin den echten Namen. `odoodev` rechnet die
> betroffenen Stored-Computed-Felder danach per `odoo-bin shell` neu. Laeuft automatisch nach
> `--anonymize` (abschaltbar mit `--no-recompute`), eigenstaendig per
> `odoodev db recompute 18 -n v18_test`. Wird mit Warnung uebersprungen, wenn die Dev-Umgebung
> (venv/odoo-bin/odoo_*.conf) nicht bereitsteht.

```bash
odoodev db restore 18 -n v18_test -z prod_backup.zip                    # Rohdaten (Default seit v0.43.0)
odoodev db restore 18 -n v18_test -z prod_backup.zip --anonymize --wipe # anonymisieren + Inhalte loeschen
odoodev db restore 18 -n v18_test -z prod_backup.zip --sanitize --anonymize-users # alles inkl. res_users
```

Bei `odoodev db drop` wird der Filestore-Ordner ebenfalls entfernt (mit Hinweis in der Bestaetigungsabfrage).

> **Tipp:** Nach dem Restore empfiehlt odoodev `odoodev start -d {name} -u all` um alle Module zu aktualisieren.

> **Kunden-Sonderdokument:** Eine ausfuehrliche, kundenfaehige Darstellung beider Schutzschichten
> (DSGVO-Kontext, vollstaendige Feldtabelle, Audit-Snippets, Restrisiken) liegt unter
> [data-protection.md](data-protection.md).

### Modul-Deinstallation vor Sanitize (`--uninstall-modules` / `db uninstall`, seit v0.45.0)

Manche installierten Module vertragen sich nicht mit den Sanitize-Schritten (z.B.
Bank-Sync-/Cloud-Module). `db restore` kann sie deshalb VOR neutralize/anonymize/wipe
deinstallieren — via `odoo-bin shell` (`button_immediate_uninstall`):

```bash
# Explizit per Flag
odoodev db restore 18 -n v18_test -z prod.zip --sanitize --uninstall-modules account_online_synchronization,l10n_de_datev

# Interaktiv: ohne Flag fragt der Restore nach, wenn ein Sanitize-Schritt aktiv ist
# (Enter ueberspringt); -y unterdrueckt die Abfrage
odoodev db restore 18 -n v18_test -z prod.zip --sanitize
```

- Nicht gefundene oder nicht installierte Modulnamen sind Warnungen, keine Fehler.
- Schlaegt die Deinstallation fehl, fragt der interaktive Modus, ob die Sanitize-Pipeline
  trotzdem fortgesetzt werden soll (Standard: Abbruch); mit `-y` laeuft sie mit Warnung weiter.
- Braucht eine fertige Dev-Umgebung (venv, odoo-bin, odoo_*.conf) — sonst graceful skip.

Eigenstaendig, wenn die DB schon restored ist:

```bash
odoodev db uninstall 18 -n v18_test -m account_online_synchronization,l10n_de_datev
odoodev db uninstall 18 -n v18_test -m eq_xyz -y    # ohne Rueckfrage
```

Im Playbook (`db.restore`): `uninstall-modules: [mod1, mod2]` (oder kommagetrennter String).

### Benutzer-Verwaltung (`db users`, seit v0.45.0)

Interaktive TUI fuer den Dev-Alltag nach einem Restore — Passwort zuruecksetzen und
Zwei-Faktor-Authentifizierung (TOTP) deaktivieren:

```bash
odoodev db users 18                 # DB-Auswahl in der TUI
odoodev db users 18 -n v18_test     # direkt in die Benutzerliste
```

| Taste | Aktion |
|-------|--------|
| `p` | Neues Passwort setzen (vorbelegt mit dem Dev-Passwort, als pbkdf2_sha512-Hash gespeichert) |
| `t` | 2FA deaktivieren: `totp_secret` leeren + `auth_totp_device` (vertrauenswuerdige Geraete) loeschen |
| `d` | Datenbank wechseln |
| `/` | Suche (Login/Name), `Esc` leert den Filter |
| `a` | Portal-Benutzer ein-/ausblenden |
| `r` | Liste neu laden |
| `q` | Beenden |

Die 2FA-Spalte zeigt `totp_secret IS NOT NULL`; Datenbanken ohne `auth_totp`-Modul werden
schema-geschuetzt behandelt (Deaktivieren ist dann ein No-op). Technische Konten
(`__system__`, `public`, ...) sind ausgeblendet, `admin` bleibt sichtbar.

### Transaktionsdaten purgen (`db purge` / `--purge-transactions`, seit v0.44.0)

Fuer eine saubere Stresstest-Datenbank loescht `odoodev` alle Bewegungs-/Transaktionsdaten,
waehrend Produkte, Preislisten, Partner, Benutzer und Konfiguration erhalten bleiben.

**Wird geleert:** Lagerbewegungen/-zeilen/-lieferungen/-quants/-schrott/-lose, Verkaufsauftraege +
-zeilen, Einkaufsauftraege + -zeilen, Buchhaltung (`account_move` + Zeilen, Zahlungen,
Ausgleiche, Kontoauszuege), MRP (Fertigungsauftraege + Arbeitsgaenge), POS
(Auftraege/Zeilen/Zahlungen/Sitzungen). Das Leeren von `stock_quant` setzt den Lagerbestand auf
null (`qty_available` ist berechnet, nicht gespeichert — an den Produkten selbst muss nichts
geaendert werden).

**Bleibt erhalten:** `product.template`/`product.product`, `product.pricelist` (+ Items),
`res.partner`, `res.users`, `res.company`, Kontenplan (`account_account`), Journale, saemtliche
Konfiguration.

Kombination mit Anonymisierung: `odoodev db restore … --purge-transactions --anonymize` liefert
eine anonymisierte, bewegungsfreie Kopie.

```bash
# Standalone-Befehl
odoodev db purge 18 -n v18_test                 # loeschen (mit Bestaetigungsprompt)
odoodev db purge 18 -n v18_test --dry-run       # nur Zieltabellen auflisten, nichts loeschen
odoodev db purge 18 -n v18_test -y              # ohne Bestaetigungsprompt

# Als Restore-Flag
odoodev db restore 18 -n v18_test -z prod.zip --purge-transactions --anonymize
```

**Mechanismus:** Ein simples `TRUNCATE … CASCADE` waere naheliegend, wuerde ueber PostgreSQLs
CASCADE-Traversal aber auch `res_company` mitreissen (das per `account_opening_move_id` auf
`account_move` zeigt) und alles, was daran haengt — TRUNCATE ignoriert die ON-DELETE-Aktion der
einzelnen Fremdschluessel. Stattdessen ermittelt `odoodev` die ON-DELETE-CASCADE-Huelle der
Bewegungs-Wurzeltabellen per `pg_constraint`-Introspektion (folgt nur `confdeltype='c'`-Kanten)
und loescht sie in einer Transaktion mit `session_replication_role = replica` (FK-Pruefung +
-Reihenfolge deaktiviert); anschliessend werden die `ON DELETE SET NULL`-Rueckverweise von
erhaltenen Tabellen (z.B. `res_company.account_opening_move_id`) auf `NULL` gesetzt. Eine
Sicherheitspruefung bricht **ohne Loeschung** mit klarer Fehlermeldung ab, falls die Huelle eine
geschuetzte Stammdaten-Tabelle (`res_partner`/`res_users`/`res_company`/`product_*`/
`product_pricelist*`) erreichen wuerde — das faengt z.B. eine benutzerdefinierte/OCA-CASCADE-FK
ab. Erfordert eine PostgreSQL-Superuser-Rolle (zum Abschalten der FK-Pruefung); bricht sonst mit
klarer Meldung ab.

### PostgreSQL-Client: Host oder Container (exec-Fallback)

Alle `db`-Befehle nutzen die PostgreSQL-Client-Tools (`psql`, `pg_dump`, `createdb`, `dropdb`).
Fehlen diese auf dem Host — typisch auf Migrationsservern, wo PostgreSQL nur im Docker-Container
laeuft — werden die Befehle seit v0.42.0 automatisch per `docker exec` im Container ausgefuehrt,
der den Ziel-Port veroeffentlicht (einmalige `[INFO]`-Zeile beim ersten Aufruf).

- **Kein Versionskonflikt:** Im Container passt die Client-Version immer zum Server (umgeht z.B.
  Debian 12: `postgresql-client-15` gegen einen Postgres-16-Container).
- **Klare Fehlermeldung:** Sind weder Client-Tools noch ein laufender Container vorhanden, bricht
  der Befehl mit zwei Handlungsoptionen ab (Tools installieren oder `odoodev docker up`).
- **Override:** `ODOODEV_PG_EXEC=host|container` erzwingt einen Modus.
- **Docker-only:** Unter Apple Container stattdessen `brew install libpq`.

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

# Drop several databases at once (checkbox multi-select)
odoodev db drop 18 -m

# Clean up all test databases (name filter)
odoodev db drop 18 --all --filter test_

# Several explicit names, terminate open connections first
odoodev db drop 18 -n v18_a -n v18_b --terminate-connections
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
| 7z | `.7z` extension | Uses `7zz`, `7z`, or `7za` binary (Debian's `p7zip` ships `7za`) |
| tar.zst | `.tar.zst` extension | Stream backup (`container2backup` v4.7.0+); streamed via `zstd \| tarfile`, needs the `zstd` CLI |
| tar/tgz/tar.gz | `.tar`/`.tgz` extension or `.tar.gz` suffix | Compressed archive; `.tar.gz` is matched explicitly as tar |
| gz | `.gz` extension (non-tar) | Gunzip to dump.sql |
| SQL | `.sql` or `.dump` extension | Direct SQL import |

### Filestore Management

**Filestore path:** `~/odoo-share/filestore/{db_name}/`

During `odoodev db restore`, the filestore is managed automatically:

1. **Disk-space pre-check** (`--check-space`, on by default): the uncompressed size is estimated
   (exact for ZIP, conservative `size × 3` for compressed formats) and compared against the free
   space on the temp and filestore filesystems. If space is tight: a warning with concrete numbers
   plus a `Continue anyway?` prompt (default no). Disable with `--no-check-space`.
2. Backup is extracted (ZIP, 7z, tar, tar.zst, gz, SQL)
3. SQL dump is imported into new database
4. Filestore is **moved** to `~/odoo-share/filestore/{db_name}/` (`shutil.move` — a rename on the
   same filesystem is instant and avoids double storage). With `--keep-temp` it is copied instead,
   so the extracted temp directory stays intact for debugging.
5. Optionally at the end: a `Delete original backup file?` prompt (default no — a backup is never
   removed automatically). Controlled via `--delete-backup` (delete without prompting) and
   `--keep-backup` (never ask/delete, for scripts).

**Dry run** (`--dry-run`, since v0.61.0): executes none of the above. odoodev only validates
the backup file, the target database (collision or drop) and the disk space, lists the planned
post-restore steps, and exits 0 (restore would proceed) or 1 (it would fail). This backs the
Dry-Run button in the GUI restore wizard.

### Filestore consistency check (`db cleanup`, since v0.60.0)

Compares the version's filestore directory (`~/odoo-share/vXX/filestore/`)
against the databases on its PostgreSQL instance — in both directions:

```bash
odoodev db cleanup 18                     # report only (deletes nothing)
odoodev db cleanup 18 --delete-orphans    # delete orphaned filestores (y/N confirmation)
odoodev db cleanup 18 --delete-orphans -y # ... without confirmation (scripts)
odoodev db cleanup 18 --json              # machine-readable (GUI/agent, never deletes)
```

- **Orphaned filestores** (directory without a matching database) are listed
  with their size; deletion only via explicit `--delete-orphans` after a y/N
  confirmation (default No).
- **Databases without a filestore** are report-only — a fresh or
  attachment-free database legitimately has none.
- An active migration group is honored (shared filestore base via
  `get_filestore_path`).

### Post-restore processing: everything opt-in (since v0.43.0)

**By default `db restore` leaves the restored database completely untouched** — every
post-processing step must be requested explicitly:

| Flag | Effect |
|------|--------|
| `--deactivate-cron` | Deactivate cron jobs, mail and fetchmail servers (psql baseline) |
| `--neutralize` | Native `odoo-bin neutralize` + bank-sync cleanup |
| `--anonymize` | GDPR anonymization with Faker (replacement values only, no deletion) |
| `--wipe` | Delete content: mail_message, ir_attachment index, linkage tables |
| `--sanitize` | Convenience flag: enables all four above at once; explicit `--no-*` flags win |
| `--anonymize-users` | Anonymize `res_users` — standalone, NOT included in `--sanitize` |
| `--purge-transactions` | Delete transactional data (stock/sales/purchase/accounting/MRP/POS) for a clean stress-test DB — standalone, NOT included in `--sanitize` (since v0.44.0) |
| `--recompute` | Recompute stored computed fields (e.g. `complete_name`) — automatic after `--anonymize`, disable with `--no-recompute` (since v0.44.0) |
| `--uninstall-modules` | Uninstall modules BEFORE the sanitize steps (comma-separated technical names); without the flag the interactive mode asks when a sanitize step is enabled (since v0.45.0) |
| `-y/--yes` | Skip interactive prompts (module question, failure confirmation) — for scripts (since v0.45.0) |

Without processing flags the output notes that the database was left untouched.

```bash
odoodev db restore 18 -n v18_test -z prod.zip                  # plain restore, DB unchanged
odoodev db restore 18 -n v18_test -z prod.zip --sanitize        # fully defused
odoodev db restore 18 -n v18_test -z prod.zip --neutralize      # neutralize only
odoodev db restore 18 -n v18_test -z prod.zip --sanitize --no-wipe  # everything except deletion
```

**Cron/mail deactivation (`--deactivate-cron`, psql baseline):**
- Cron jobs (`ir_cron.active = false`)
- Mail servers (`ir_mail_server.active = false`)
- Fetchmail servers (`fetchmail_server.active = false`)

The psql baseline needs no running Odoo and guarantees a restored production copy fires no
crons/mails.

### Native neutralization (`odoo-bin neutralize`, opt-in via `--neutralize`)

With `--neutralize`, `odoodev db restore` runs Odoo's built-in `odoo-bin neutralize` after the
import. It executes each installed module's `data/neutralize.sql`, covering far more than the
psql baseline: **payment providers, IAP accounts, webhooks, mass mailing, OAuth tokens, the
"NEUTRALIZED" banner**, and any custom module shipping its own `neutralize.sql` (including the
in-house Nextcloud/Office365 modules — which is why there is no separate cloud deactivation
anymore).

- **Opt-in** (since v0.43.0; included in `--sanitize`).
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

### GDPR anonymization (opt-in via `--anonymize` / `--wipe`)

With `--anonymize`, `odoodev db restore` anonymizes personal data right after the import
(GDPR Art. 5 data minimization). Since v0.43.0 **content deletion is a separate `--wipe`
flag** (mail_message content, ir_attachment full-text index, linkage tables) — `--anonymize`
only replaces values and deletes nothing.

Replacement values are generated with **Faker** (`de_DE`, seeded per row id → reproducible).
E-mail and login columns are deliberately **not** taken from Faker but forced onto reserved,
non-deliverable values (`p{id}@example.invalid`, `user{id}`).

| Table | Flag | Effect |
|-------|------|--------|
| `res_partner` | `--anonymize` | name (companies → `fake.company()`, persons → `fake.name()`), email, phone/mobile, address, VAT, website, comment, function (persons only) |
| `crm_lead` | `--anonymize` | contact/company name, email, phone/mobile, address, description |
| `res_partner_bank` | `--anonymize` | account number (fake IBAN), sanitized account number |
| `hr_employee` | `--anonymize` | name, work email, phones, private address, ID/passport/SSN numbers, birth data, spouse/emergency data, PIN/barcode, notes, image/scan fields; salary/distance fields → 0 |
| `hr_version` (v19) / `hr_contract` (v16/v18) | `--anonymize` | wage → 0, sensitive personnel data (v19) |
| `employee_bank_account_rel` (v19) | `--wipe` | M2M link deleted entirely |
| `mail_message` | `--wipe` | `email_from`, subject (cleared), body (placeholder) |
| `ir_attachment` | `--wipe` | `index_content` (full-text index cleared) |

> **`res_users` is NOT anonymized by default** — logins stay testable. Opt in via
> `--anonymize-users` (login → `user{id}`, password → dev password `--user-password`, default
> `ownerp`; `admin` stays unchanged). HR columns are filtered against the live schema, so it is
> version robust (v16/v18/v19). Missing tables/columns are skipped (non-fatal).

> **Since v0.44.0: stored computed fields are recomputed.** Anonymization writes directly into
> `res_partner.name` & co. via raw SQL. Bypassing the ORM this way leaves the stored
> `complete_name` (which the live-computed `display_name` reads) at its original value —
> kanban cards and list columns (e.g. the partner column on invoice overviews) kept showing the
> real name. `odoodev` now recomputes the affected stored computed fields afterwards via
> `odoo-bin shell`. Runs automatically after `--anonymize` (disable with `--no-recompute`),
> standalone via `odoodev db recompute 18 -n v18_test`. Skipped with a warning when the dev env
> (venv/odoo-bin/odoo_*.conf) is not ready.

```bash
odoodev db restore 18 -n v18_test -z prod_backup.zip                    # raw data (default since v0.43.0)
odoodev db restore 18 -n v18_test -z prod_backup.zip --anonymize --wipe # anonymize + delete content
odoodev db restore 18 -n v18_test -z prod_backup.zip --sanitize --anonymize-users # everything incl. res_users
```

When running `odoodev db drop`, the filestore directory is also removed (with notice in the confirmation prompt).

> **Tip:** After restore, odoodev suggests running `odoodev start -d {name} -u all` to update all modules.

> **Customer-facing reference:** A detailed, customer-ready write-up of both protection layers
> (GDPR context, full field table, audit snippets, residual risks) lives at
> [data-protection.md](data-protection.md).

### Module uninstall before sanitizing (`--uninstall-modules` / `db uninstall`, since v0.45.0)

Some installed modules conflict with the sanitize steps (e.g. bank-sync/cloud modules).
`db restore` can therefore uninstall them BEFORE neutralize/anonymize/wipe run — via
`odoo-bin shell` (`button_immediate_uninstall`):

```bash
# Explicit flag
odoodev db restore 18 -n v18_test -z prod.zip --sanitize --uninstall-modules account_online_synchronization,l10n_de_datev

# Interactive: without the flag the restore asks when a sanitize step is enabled
# (Enter skips); -y suppresses the prompt
odoodev db restore 18 -n v18_test -z prod.zip --sanitize
```

- Module names that don't exist or aren't installed are warnings, not errors.
- If the uninstall fails, the interactive mode asks whether to continue the sanitize
  pipeline anyway (default: abort); with `-y` it continues with a warning.
- Requires a ready dev environment (venv, odoo-bin, odoo_*.conf) — graceful skip otherwise.

Standalone, when the DB is already restored:

```bash
odoodev db uninstall 18 -n v18_test -m account_online_synchronization,l10n_de_datev
odoodev db uninstall 18 -n v18_test -m eq_xyz -y    # without confirmation
```

In playbooks (`db.restore`): `uninstall-modules: [mod1, mod2]` (or a comma-separated string).

### User management (`db users`, since v0.45.0)

Interactive TUI for the dev workflow after a restore — reset passwords and disable
two-factor authentication (TOTP):

```bash
odoodev db users 18                 # database picker inside the TUI
odoodev db users 18 -n v18_test     # straight into the user list
```

| Key | Action |
|-----|--------|
| `p` | Set a new password (pre-filled with the dev password, stored as a pbkdf2_sha512 hash) |
| `t` | Disable 2FA: clear `totp_secret` + delete `auth_totp_device` (trusted devices) |
| `d` | Switch database |
| `/` | Search (login/name), `Esc` clears the filter |
| `a` | Show/hide portal users |
| `r` | Reload the list |
| `q` | Quit |

The 2FA column shows `totp_secret IS NOT NULL`; databases without the `auth_totp` module
are schema-guarded (disabling is a no-op there). Technical accounts (`__system__`,
`public`, ...) are hidden, `admin` stays visible.

### Purge transactional data (`db purge` / `--purge-transactions`, since v0.44.0)

For a clean stress-test database, `odoodev` can delete all transactional/movement data while
keeping products, pricelists, partners, users and configuration intact.

**Emptied:** stock moves/move-lines/pickings/quants/scrap/lots, sale orders + lines, purchase
orders + lines, accounting (`account_move` + lines, payments, reconciliations, bank statements),
MRP (production orders + workorders), POS (orders/lines/payments/sessions). Emptying
`stock_quant` zeroes on-hand stock (`qty_available` is computed, not stored — products need no
change themselves).

**Kept:** `product.template`/`product.product`, `product.pricelist` (+ items), `res.partner`,
`res.users`, `res.company`, chart of accounts (`account_account`), journals, all configuration.

Combine with anonymization: `odoodev db restore … --purge-transactions --anonymize` gives an
anonymized, movement-free copy.

```bash
# Standalone command
odoodev db purge 18 -n v18_test                 # delete (with confirmation prompt)
odoodev db purge 18 -n v18_test --dry-run       # only list target tables, delete nothing
odoodev db purge 18 -n v18_test -y              # skip the confirmation prompt

# As a restore flag
odoodev db restore 18 -n v18_test -z prod.zip --purge-transactions --anonymize
```

**Mechanism:** a plain `TRUNCATE … CASCADE` looks tempting but PostgreSQL's CASCADE traversal
would also wipe `res_company` (which references `account_move` via the opening-balance entry
`account_opening_move_id`) and everything chained off it — TRUNCATE ignores each foreign key's
own ON DELETE action. Instead, `odoodev` computes the ON-DELETE-CASCADE closure of the movement
root tables via `pg_constraint` introspection (following only `confdeltype='c'` edges) and
DELETEs it in one transaction with `session_replication_role = replica` (FK enforcement and
ordering disabled); the `ON DELETE SET NULL` back-references from kept tables (e.g.
`res_company.account_opening_move_id`) are then nulled. A safety pre-check aborts **with no
deletion** and a clear message if the closure would reach a protected master table
(`res_partner`/`res_users`/`res_company`/`product_*`/`product_pricelist*`) — catching a
custom/OCA CASCADE FK. Requires a PostgreSQL superuser role (to disable FK enforcement);
aborts clearly otherwise.

### PostgreSQL Client: Host or Container (exec fallback)

All `db` commands use the PostgreSQL client tools (`psql`, `pg_dump`, `createdb`, `dropdb`).
When these are missing on the host — typical on migration servers where PostgreSQL runs only
inside the Docker container — commands are executed automatically via `docker exec` inside the
container publishing the target port since v0.42.0 (a one-time `[INFO]` line on first use).

- **No version mismatch:** inside the container the client version always matches the server
  (sidesteps e.g. Debian 12's `postgresql-client-15` against a Postgres 16 container).
- **Clear error:** if neither client tools nor a running container are available, the command
  aborts with two remediation options (install the tools or `odoodev docker up`).
- **Override:** `ODOODEV_PG_EXEC=host|container` forces a mode.
- **Docker-only:** on Apple Container install `brew install libpq` instead.

### Default Credentials

- **User:** `ownerp`
- **Password:** `CHANGE_AT_FIRST` (configurable via `odoodev setup`)
