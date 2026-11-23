# Änderungen

Alle wichtigen Änderungen an Finanzwabe stehen hier. Das Format folgt
[Keep a Changelog](https://keepachangelog.com/de/1.1.0/), die Versionsnummern folgen
[Semantic Versioning](https://semver.org/lang/de/).

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

[0.2.0]: https://github.com/Soerenneumann1985/finanzwabe/releases/tag/v0.2.0
