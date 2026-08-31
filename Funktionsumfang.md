---
projekttyp: python-paket
modul: odoo-dev
anzeigename: odoodev
version: 0.63.0
lizenz: AGPL-3
erstellt_am: 31.08.2026
---

# Funktionsumfang: odoodev

## Kurzbeschreibung
odoodev ist ein Kommandozeilen-Werkzeug, das Odoo-Entwicklern eine komplette Entwicklungsumgebung
für alle Odoo-Versionen (16 bis 19) einheitlich einrichtet, startet und pflegt. Odoo läuft dabei
direkt auf dem eigenen Rechner, während Datenbank und Test-Mailserver im Hintergrund bereitstehen –
ein Befehl statt vieler Handgriffe.

## Hauptnutzen für Anwender
- **Eine Bedienung für alle Versionen** – zwischen Odoo 16, 17, 18 und 19 wechseln, ohne jede
  Umgebung einzeln von Hand zu pflegen.
- **Sofort startklar** – den Server mit einem einzigen Befehl in der gewünschten Betriebsart starten
  (normal, Entwicklung mit automatischem Neuladen, interaktive Shell oder Testlauf).
- **Alles im Blick** – eine aufgeräumte Terminal-Oberfläche zeigt das Server-Geschehen live, lässt
  nach Dringlichkeit filtern, durchsuchen und markierten Text bequem in die Zwischenablage kopieren.
- **Gefahrloser Umgang mit Kundendaten** – beim Einspielen einer Datenbank lassen sich auf Wunsch
  echte Kontaktdaten anonymisieren, Zahlungs-, Versand- und Cloud-Verbindungen stilllegen,
  Nachrichteninhalte löschen sowie automatische Aufgaben und der E-Mail-Versand abschalten – einzeln
  wählbar oder gesammelt mit einer einzigen Option. So geht nichts versehentlich an echte Empfänger.
- **Vollständige Datenbank-Verwaltung** – sichern, zurückspielen, kopieren, umbenennen und löschen,
  jeweils inklusive der zugehörigen Dateianhänge.
- **Schneller Einstieg** – eine neue Umgebung entsteht von Grund auf oder komfortabel über einen
  geführten Assistenten.
- **Eigene Vorgaben überstehen jedes Update** – wer eine bestimmte Version einer Programmbibliothek
  braucht, trägt sie ein einziges Mal ein. Sie bleibt erhalten, auch wenn odoodev die mitgelieferte
  Vorgabenliste erneuert; steht in der Vorgabenliste inzwischen eine neuere Version, wird darauf
  hingewiesen.
- **Freie Wahl im Hintergrund** – die Begleitdienste laufen wahlweise über Docker oder über Apple
  Container.

## Funktionen im Detail
- Eine komplette Umgebung für eine Odoo-Version von Grund auf einrichten – samt aller benötigten
  Verzeichnisse, Konfiguration und Programmbibliotheken; auf Wunsch Schritt für Schritt per Assistent.
- Den Odoo-Server starten und wieder stoppen. Im Entwicklungsmodus werden Änderungen sofort
  übernommen; ein Testmodus führt automatische Prüfungen aus und beendet sich danach von selbst.
- Das Server-Geschehen live in einer übersichtlichen Terminal-Oberfläche verfolgen: Meldungen nach
  Dringlichkeit ein- und ausblenden, durchsuchen und im Markiermodus gezielt Textstellen herauskopieren.
- Datenbanken in verschiedenen Formaten sichern (inklusive Dateianhänge), wieder einspielen, kopieren,
  umbenennen oder löschen – auch auf Servern ohne installierte Datenbank-Werkzeuge: fehlen diese,
  arbeitet odoodev automatisch direkt im Datenbank-Container weiter.
- Beim Einspielen bleibt die Datenbank standardmäßig unverändert; auf Wunsch werden Kontaktdaten
  anonymisiert, sensible Verbindungen neutralisiert, Nachrichteninhalte gelöscht sowie automatische
  Aufgaben und der Mailversand abgeschaltet – jede Schutzmaßnahme einzeln oder alle gesammelt
  aktivierbar. Vor dem Entpacken wird zudem der freie Speicherplatz geprüft.
- Die benötigten Quell-Repositories holen und aktuell halten; die passende Konfiguration wird dabei
  automatisch erzeugt.
- Die benötigten Programmbibliotheken je Odoo-Version aus einer mitgelieferten Vorgabenliste und den
  eigenen Abweichungen zusammensetzen. Die eigenen Einträge liegen getrennt und werden nie
  überschrieben; die wirksame Liste erneuert sich beim Start von selbst, sobald die Vorgaben sich
  geändert haben. Eine Gegenüberstellung zeigt jederzeit, wo Vorgabe, eigene Wahl und tatsächlich
  installierter Stand auseinanderlaufen. Eine bereits von Hand gepflegte Liste lässt sich einmalig
  übernehmen, ohne dass ein Eintrag verloren geht – die bisherige Fassung wird vorher gesichert.
- Getrennte, aufeinander abgestimmte Arbeitsumgebungen je Version verwalten und deren Zustand prüfen.
- Umzugsgruppen für den Wechsel zwischen Odoo-Versionen festlegen und aktivieren.
- Die Begleitdienste (Datenbank, Test-Mailserver) starten, stoppen und ihre Protokolle einsehen –
  wahlweise über Docker oder Apple Container.
- Die Datenbankleistung zwischen Docker und Apple Container vergleichen.
- Wiederkehrende Abläufe unbeaufsichtigt ausführen lassen – mit maschinenlesbarer Ausgabe, ideal für
  Automatisierung.
- Einen Gesundheitscheck der Umgebung durchführen und die eigene Shell so einrichten, dass sich die
  passende Umgebung mit einem kurzen Kürzel aktivieren lässt.

## Anwendungsfälle
- **Entwickeln über mehrere Odoo-Versionen:** zwischen v16 und v19 wechseln, ohne jede
  Umgebung einzeln von Hand aufzusetzen.
- **Neuer Rechner, neues Projekt:** in wenigen Minuten per Assistent eine lauffähige Umgebung
  einrichten und direkt loslegen.
- **Arbeiten mit Produktivdaten:** eine Kundendatenbank lokal einspielen und dabei per Option
  anonymisieren und entschärfen – ohne Risiko, dass Mails oder Zahlungen nach außen gehen.
- **Fehlersuche am laufenden Server:** die Ausgaben live verfolgen, nach Warnungen und Fehlern filtern
  und die relevanten Zeilen direkt herauskopieren.
- **Eine Programmbibliothek muss zurückgehalten werden:** die passende ältere Version einmal
  eintragen – sie bleibt bei jedem Update bestehen, und jeder Abgleich weist darauf hin, dass sie
  eine neuere Vorgabe zurückhält.
- **Wiederkehrende Routine:** immer gleiche Arbeitsschritte als Ablauf hinterlegen und unbeaufsichtigt
  durchlaufen lassen.
