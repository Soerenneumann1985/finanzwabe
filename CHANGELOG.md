# Änderungen

Alle wichtigen Änderungen an Finanzwabe stehen hier. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionsnummern folgen
[Semantic Versioning](https://semver.org/lang/de/).

## [Unveröffentlicht]

### Hinzugefügt
- **Lizenz:** `LICENSE` mit der PolyForm Noncommercial License 1.0.0 (Originalwortlaut, Rechteinhaber Sören
  Neumann). Private und nicht kommerzielle Nutzung ist erlaubt, kommerzielle Nutzung durch Dritte nicht.
  Dazu ein Abschnitt „Lizenz“ in der README. Die Lizenz gilt ab diesem Stand; frühere Versionen (bis 0.4.0)
  wurden ohne Lizenz veröffentlicht.

## [0.4.0] – 2026-11-23

Finanzwabe als Windows-Programm: herunterladen, doppelklicken, benutzen.

### Hinzugefügt
- **Windows-Programm** `Finanzwabe-0.4.0-windows.exe` als Download im Release. Kein Python, kein Terminal nötig.
  Doppelklick öffnet den Browser; ein kleines Fenster zeigt die Adresse und den Datenordner, Schließen beendet
  das Programm vollständig. Ein zweiter Doppelklick öffnet nur den Browser.
- `launcher.py` (Startprogramm) und `finanzwabe.spec` (Bauanleitung für PyInstaller), dazu
  `requirements-build.txt`. Fehler stehen in `finanzwabe.log` im Datenordner.
- README: Abschnitt **Installation (Windows, ohne Python)** mit Hinweis zur SmartScreen-Warnung (die Datei ist
  nicht signiert) und zur SHA256-Prüfsumme.

### Geändert
- Das Programm ist nur auf diesem PC erreichbar (`127.0.0.1`), nicht im WLAN. Die Entwickler-Variante
  `serve.py` bleibt unverändert.
- Die `.exe` schreibt nichts in ihren eigenen Ordner; Daten liegen im Datenordner (siehe 0.3.0).

## [0.3.0] – 2026-11-23

Vorbereitung, damit auch andere Finanzwabe nutzen können.

### Hinzugefügt
- **Datenordner im Benutzerordner:** Standard ist jetzt `%LOCALAPPDATA%\Finanzwabe` (macOS:
  `~/Library/Application Support/Finanzwabe`, Linux: `~/.local/share/finanzwabe`). Der Ordner wird beim ersten
  Start angelegt, die App startet auch ohne vorhandene Datenbank mit einer leeren.
- Beim Start zeigt `serve.py` an, wo die Daten liegen, und meldet den ersten Start.
- **Wabi mit eigenem Schlüssel:** Unter *Einstellungen → Wabi – KI-Assistent* trägt man den eigenen
  Anthropic-Schlüssel ein oder entfernt ihn. Der Hinweis dort sagt klar, dass der Schlüssel von Anthropic
  (console.anthropic.com) kommt und die Kosten der KI-Anfragen der Nutzer selbst trägt.
- Neues Modul `datadir.py` (Suche des Datenordners) und neue Tests für Datenordner und Schlüssel.

### Geändert
- Eigene Ordner bleiben möglich: `FINANZ_DATA_DIR` oder ein vorhandener OneDrive-Ordner `Finanzwabe` haben
  Vorrang vor dem Benutzerordner (so bleiben Daten auf mehreren PCs nutzbar). Eine ältere `instance/finanz.db`
  im Projekt wird weiter gefunden.
- Ohne Schlüssel läuft die App normal; Wabi ist dann ausgeschaltet (Chat gesperrt, Hinweis mit Link zu den
  Einstellungen). Vorher musste eine Schlüsseldatei von Hand in einen Ordner gelegt werden.
- Den Schlüssel darf nur das erste Konto der Installation ändern, er wird nie wieder angezeigt.

### Sicherheit
- Es wird kein Schlüssel mitgeliefert und kein Schlüssel hat einen Standardwert; ein Test prüft den
  Quelltext auf Schlüsselmuster. Der Schlüssel liegt im Datenordner des Nutzers, nie im Projekt.

## [0.2.0] – 2026-11-23

### Hinzugefügt
- **Wabi, der KI-Assistent** (Claude-API): beantwortet Fragen zu den eigenen Zahlen, führt durch die App mit
  Link-Knöpfen und schlägt Buchungen vor, die erst nach „Bestätigen“ gespeichert werden. Mit Spracheingabe,
  Handy-Ansicht und Hinweisen zum Datenschutz. Ohne API-Schlüssel bleibt die App voll nutzbar.
- **Bankprofile** (`bank_profile/olb.json`): Der CSV-Import erkennt die Bank an der Kopfzeile. Mitgeliefert
  ist das Profil der OLB.
- **Spalten-Dialog** für unbekannte CSV-Dateien: Die App rät nicht, du ordnest die Spalten zu und kannst
  sie als neues Profil speichern.
- **PayPal-Händler** werden aus dem Verwendungszweck gelesen (vier bekannte Schreibweisen).
- **Kundenreferenz** (`transaction.customer_reference`): Doppelte werden über die Referenz erkannt, nicht
  nur über Datum und Betrag. Gleiche Beträge am selben Tag mit verschiedenen Referenzen bleiben getrennt.
- Hinweis, wenn Zeilen einer CSV nicht gelesen werden konnten.
- `.gitignore` schließt zusätzlich weitere Excel-/Tabellenformate und `.env.*` aus.

### Geändert
- Der CSV-Import rät Spalten nicht mehr aus einer Namensliste. Passt kein Profil, kommt der Zuordnungs-Dialog.
- Zeichensatz: erst UTF-8 (auch mit BOM), danach der Zeichensatz des Profils (Windows-1252).
- Die neue Spalte `customer_reference` wird beim Start automatisch ergänzt (optionale Spalte, keine Migration nötig).

### Hinweis
- `bank_import.parse_csv()` (alte Spaltenerkennung) bleibt im Code, wird aber von der Seite nicht mehr benutzt.

## [0.1.0] – früherer Stand (ohne Tag)

Grundfunktionen: Übersicht, Monat, Jahr, Vermögen, Kredite, Buchungen, Daueraufträge, Kategorien mit Budget,
Suche und Export, Excel-Import, Textimport aus dem Online-Banking, Mehrbenutzer-Login, installierbare
Web-App (PWA), hell und dunkel.

[0.4.0]: https://github.com/Soerenneumann1985/finanzwabe/releases/tag/v0.4.0
[0.3.0]: https://github.com/Soerenneumann1985/finanzwabe/releases/tag/v0.3.0
[0.2.0]: https://github.com/Soerenneumann1985/finanzwabe/releases/tag/v0.2.0
