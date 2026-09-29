# Finanz-App – Konzept für Claude Code

Sep 29, 2026 · @Sören

## Ziel und Idee

Die App ersetzt meine selbst gebaute Excel-Finanztabelle und automatisiert, was dort heute von Hand passiert. Sie beantwortet drei Fragen auf einen Blick:

1. **Wofür gebe ich mein Geld aus?** Einnahmen und Ausgaben pro Monat, nach Kategorien.
2. **Wie stehe ich insgesamt da?** Guthaben (Girokonto, Depot, Sparkonto) minus Schulden (Kredite, Kreditkarten, Darlehen) ergibt das Nettovermögen.
3. **Wie schnell baue ich Schulden ab?** Restschuld und Tilgungsverlauf pro Kredit, freier Rahmen pro Kreditkarte.

Zielgruppe sind Menschen, die ihre Finanzen bewusst im Griff haben wollen und neben den Ausgaben auch Kredite abzahlen. Punkt 2 und 3 unterscheiden die App von reinen Haushaltsbuch-Apps.

Weg zum Verkauf: erst eine Version bauen, die ich selbst statt der Excel-Tabelle nutze, dann Testnutzer finden, erst danach über Verkauf entscheiden.

## Das Vorbild: meine Excel-Tabelle

Jeder Monat ist in der Tabelle ein geschlossener Block aus drei Teilen. Die App übernimmt genau diese Logik.

| Teil | Inhalt in Excel | Was die App daraus macht |
| --- | --- | --- |
| Buchungen | Datum, Betrag (negativ = Ausgabe), Beschreibung | Buchung mit Kategorie und Konto |
| Monatsauswertung | Einnahmen, Gesamtkosten, Summen für Fixe Kosten, Tankstelle, Supermarkt, Bargeld, Versicherungen | Automatisch aus den Kategorien berechnet |
| Vermögens-Snapshot | Kontostände, Kredit-Restschulden, Kreditkarten-Salden mit freiem Rahmen, Umbuchung vom Sparkonto | Automatisch aus Konten und Krediten berechnet |

Schwächen der Excel-Lösung, die die App beheben muss:

- Kategorie-Summen verweisen auf einzeln ausgewählte Zellen. Jede neue Buchung muss von Hand in die richtige Formel.
- Kredit-Restschulden werden als wachsende Kette gerechnet (Startbetrag + Rate + Rate + …).
- Buchungen können doppelt zählen: Eine Zeile stand in zwei Kategorien, und Versicherungen zählen zusätzlich in den Fixkosten.
- Jedes Jahr ist ein neues Blatt, Vergleiche über Jahre sind mühsam.

**Grundregel für die App:** Jede Buchung hat genau eine Kategorie. Alle Summen werden daraus berechnet, nie von Hand eingetragen.

## Datenmodell

Vier Tabellen reichen für die erste Version. Beträge werden als ganze Cent (Integer) gespeichert, damit keine Rundungsfehler entstehen.

**account (Konto)**

| Feld | Typ | Bedeutung |
| --- | --- | --- |
| id | int | Primärschlüssel |
| name | text | z. B. „Girokonto“, „Depot“, „Kreditkarte Gold“ |
| type | text | `giro`, `savings`, `depot`, `credit_card`, `loan` |
| balance\_cents | int | aktueller Stand, Schulden negativ |
| credit\_limit\_cents | int, optional | nur Kreditkarten: Rahmen |

**category (Kategorie)**

| Feld | Typ | Bedeutung |
| --- | --- | --- |
| id | int | Primärschlüssel |
| name | text | z. B. Supermarkt, Tankstelle, Versicherung, Miete, Abos |
| kind | text | `income`, `expense`, `transfer` |
| is\_fixed | bool | zählt zu den Fixkosten |

`is_fixed` löst das Doppelzähl-Problem: „Fixe Kosten“ ist keine eigene Kategorie mehr, sondern eine Eigenschaft. Versicherung bleibt Versicherung und zählt trotzdem zu den Fixkosten, aber nur einmal in der Gesamtsumme. `transfer` steht für Umbuchungen (Sparkonto, Depot, Kreditrate) und zählt weder als Einnahme noch als Ausgabe.

**transaction (Buchung)**

| Feld | Typ | Bedeutung |
| --- | --- | --- |
| id | int | Primärschlüssel |
| date | date | Buchungstag |
| amount\_cents | int | positiv = Einnahme, negativ = Ausgabe |
| description | text | z. B. „Wocheneinkauf“ |
| category\_id | int | genau eine Kategorie (Pflicht) |
| account\_id | int | von welchem Konto |

**loan (Kredit)**

| Feld | Typ | Bedeutung |
| --- | --- | --- |
| id | int | Primärschlüssel |
| name | text | z. B. „Autokredit“, „Bafög-Darlehen“ |
| start\_amount\_cents | int | ursprüngliche Schuld |
| monthly\_rate\_cents | int | monatliche Rate |
| start\_date | date | erste Rate |
| account\_id | int | zugehöriges Konto vom Typ `loan` |

## Kernfunktionen der ersten Version (MVP)

Das MVP bildet meine Excel-Tabelle vollständig ab, ohne Extras.

1. **Konten verwalten:** anlegen, bearbeiten, löschen (Girokonto, Sparkonto, Depot, Kreditkarte, Kredit).
2. **Kategorien verwalten:** anlegen mit Art (Einnahme/Ausgabe/Umbuchung) und Fixkosten-Haken. Beim ersten Start werden Standardkategorien angelegt.
3. **Buchungen erfassen:** Datum, Betrag, Beschreibung, Kategorie, Konto. Bearbeiten und löschen möglich.
4. **Monatsübersicht:** Monat wählen, Liste der Buchungen, darunter die Auswertung.
5. **Vermögensübersicht:** alle Konten, Kredite und Kreditkarten mit Nettovermögen.

Rechenregeln (die App rechnet alles selbst, nichts wird von Hand summiert):

| Wert | Regel |
| --- | --- |
| Einnahmen im Monat | Summe aller Buchungen mit Kategorie-Art `income` |
| Ausgaben im Monat | Summe aller Buchungen mit Kategorie-Art `expense` |
| Summe je Kategorie | Summe der Buchungen dieser Kategorie im Monat |
| Fixkosten | Summe der Ausgaben, deren Kategorie `is_fixed` hat |
| Saldo des Monats | Einnahmen minus Ausgaben (Umbuchungen zählen nicht) |
| Freier Kreditkartenrahmen | Limit + Kontostand (Stand ist negativ) |
| Restschuld Kredit | Startbetrag minus Rate × Anzahl gezahlter Monate seit Startdatum, mindestens 0 |
| Nettovermögen | Summe aller Guthaben minus Summe aller Schulden |

Die Restschuld-Regel ist eine Vereinfachung ohne Zinsen. Sie entspricht meiner bisherigen Rechnung in Excel. Zinsen sind eine spätere Ausbaustufe.

Jede Rechenregel bekommt einen eigenen automatisierten Test (pytest), damit Fehler wie das Doppelzählen gar nicht erst entstehen.

## Technik und Projektstruktur

Die App wird eine Web-App mit Python, die zunächst lokal auf meinem Rechner läuft. Der Stack baut auf dem auf, was ich schon kenne.

| Baustein | Wahl | Warum |
| --- | --- | --- |
| Sprache | Python 3.12 | kenne ich aus dem Kurs |
| Datenbank | SQLite | eine Datei, keine Installation |
| Datenbankzugriff | SQLAlchemy (ORM) | kenne ich aus dem Flugdaten-Projekt |
| Web-Framework | Flask mit Jinja-Templates | einfach, gut für den Einstieg, HTML/CSS kenne ich von meiner Homepage |
| Diagramme | Chart.js (ab Ausbaustufe 2) | einfache Balken- und Liniendiagramme im Browser |
| Tests | pytest | für alle Rechenregeln |
| Versionskontrolle | Git + GitHub | kleine Commits nach jedem Schritt |

Geplante Ordnerstruktur:

```
finanz-app/
├── app.py              # Flask-Start, Routen
├── models.py           # SQLAlchemy-Modelle (account, category, transaction, loan)
├── calculations.py     # alle Rechenregeln als reine Funktionen
├── seed.py             # Standardkategorien + Beispieldaten
├── templates/          # HTML-Seiten (Jinja)
├── static/             # CSS, später JavaScript
├── tests/
│   └── test_calculations.py
├── requirements.txt
├── CLAUDE.md           # Regeln für Claude Code (siehe unten)
└── README.md
```

`calculations.py` enthält nur reine Funktionen ohne Datenbank- oder Web-Code. So lassen sie sich leicht testen und später in eine andere Oberfläche (z. B. Handy-App) übernehmen.

**Datenschutz:** Meine echten Finanzdaten kommen nie ins Git-Repository. Die Datenbankdatei steht in `.gitignore`, `seed.py` erzeugt nur erfundene Beispieldaten.

## Ausbaustufen nach dem MVP

Erst wenn ich das MVP einen Monat lang statt der Excel-Tabelle benutzt habe, kommen Extras dazu. Reihenfolge nach Nutzen:

| Stufe | Funktion | Nutzen |
| --- | --- | --- |
| 2 | Diagramme: Ausgaben je Kategorie, Monatsvergleich, Nettovermögen über Zeit | Entwicklung auf einen Blick |
| 2 | Jahresübersicht und Vergleich mehrerer Jahre | ersetzt die Jahresblätter |
| 3 | CSV-Import von Kontoauszügen | kein Abtippen mehr |
| 3 | Automatische Kategorie-Vorschläge („Supermarkt“ erkannt an der Beschreibung) | schnelleres Erfassen |
| 3 | Wiederkehrende Buchungen (Miete, Abos, Kreditraten) | Fixkosten tragen sich selbst ein |
| 4 | Excel-Import meiner alten Tabelle | meine Daten ab 2016 übernehmen |
| 4 | Kredite mit Zinsen und Prognose „schuldenfrei am …“ | stärkstes Verkaufsargument |
| 4 | Budgets je Kategorie mit Warnung | Ausgaben begrenzen |
| 5 | Benutzerkonten, Login, Hosting online | Voraussetzung für Testnutzer und Verkauf |

Stufe 5 ist der Schritt zum Produkt. Ab da gelten Datenschutzpflichten (DSGVO), weil fremde Finanzdaten gespeichert werden. Das kläre ich vorher, notfalls mit Beratung. Stufe 5 passt außerdem zu meinem Cloud-Schwerpunkt in der Ausbildung.

## Arbeitsweise mit Claude Code

Ich baue die App Schritt für Schritt, jeder Schritt endet mit einem laufenden Stand und einem Git-Commit. So lerne ich mit und behalte den Überblick.

### Bauplan für das MVP

1. Projekt anlegen: Ordner, virtuelle Umgebung, `requirements.txt`, Git, `.gitignore`, `CLAUDE.md`.
2. `models.py`: die vier Tabellen mit SQLAlchemy, Datenbank erzeugen.
3. `seed.py`: Standardkategorien und erfundene Beispieldaten für zwei Monate.
4. `calculations.py` + Tests: alle Rechenregeln aus dem Abschnitt Kernfunktionen, zuerst die Tests.
5. Flask-Grundgerüst: Startseite mit Monatsübersicht (nur lesen).
6. Formulare: Buchungen anlegen, bearbeiten, löschen.
7. Konten, Kategorien und Kredite verwalten.
8. Vermögensübersicht mit Nettovermögen, Restschulden, freiem Kreditrahmen.
9. Einfaches, sauberes CSS.
10. README mit Installationsanleitung und Screenshots.

### Inhalt für CLAUDE.md

Diese Datei legt Claude Code ins Projekt. Sie gilt dann für jede Sitzung.

```markdown
# Finanz-App – Regeln für Claude

## Projekt
Persönliche Finanz-App (Flask, SQLAlchemy, SQLite, pytest).
Das vollständige Konzept steht in KONZEPT.md.

## Ich lerne dabei
- Ich bin Quereinsteiger und lerne Python. Erkläre, was du tust und warum.
- Arbeite immer nur an EINEM Schritt aus dem Bauplan. Frag vor dem nächsten.
- Wenn ich "Lernmodus" sage: gib mir ein Gerüst mit TODO-Kommentaren
  und Hinweisen statt fertigem Code.
- Antworte auf Deutsch, Code und Bezeichner auf Englisch.

## Technische Regeln
- Beträge immer als Integer in Cent speichern und rechnen.
- Jede Buchung hat genau eine Kategorie.
- Rechenlogik nur in calculations.py, als reine Funktionen mit Tests.
- Keine echten Finanzdaten ins Repo. Die .db-Datei steht in .gitignore.
- Nach jedem Schritt: Tests laufen lassen, dann Commit vorschlagen.
```

### Start-Prompt für die erste Sitzung

Dieses Dokument als `KONZEPT.md` in den leeren Projektordner legen, Claude Code dort starten und schreiben:

> Lies KONZEPT.md. Das ist das Konzept für meine Finanz-App. Stell mir zuerst Fragen, falls etwas unklar ist. Dann setze Schritt 1 aus dem Bauplan um: Projekt anlegen und CLAUDE.md mit dem Inhalt aus dem Konzept erstellen. Erkläre mir jeden Befehl. Mach danach eine Pause, bevor wir Schritt 2 angehen.

In den folgenden Sitzungen reicht: „Weiter mit Schritt X aus dem Bauplan.“ Mit „im Lernmodus“ dahinter bekomme ich ein Gerüst zum Selbermachen.
