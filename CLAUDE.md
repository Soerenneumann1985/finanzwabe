# Finanzwabe – Regeln für Claude

## Projekt
Finanzwabe – Finanz-App mit Slogan „Wabe für Wabe schuldenfrei.“
(Flask, SQLAlchemy, SQLite, pytest). Projektordner heißt weiter finanz-app.
Das vollständige Konzept steht in KONZEPT.md.

## Arbeitsweise
- Arbeite selbstständig und vollständig durch. Frag nur bei wirklich
  wichtigen Entscheidungen nach, nicht vor jedem Schritt.
- Ich bin Quereinsteiger und lerne Python. Fasse am Ende kurz zusammen,
  was du gemacht hast und warum.
- Wenn ich "Lernmodus" sage: gib mir ein Gerüst mit TODO-Kommentaren
  und Hinweisen statt fertigem Code.
- Antworte auf Deutsch, Code und Bezeichner auf Englisch.
- Die App soll im Browser und auf dem Smartphone (Android) laufen:
  mobile-first, als installierbare Web-App (PWA).

## Technische Regeln
- Beträge immer als Integer in Cent speichern und rechnen.
- Jede Buchung hat genau eine Kategorie.
- Rechenlogik nur in calculations.py, als reine Funktionen mit Tests.
- Keine echten Finanzdaten ins Repo. Die .db-Datei steht in .gitignore.
- Nach jedem Schritt: Tests laufen lassen, dann committen.

## Design
- Königsblau (#1f4fd1) mit 3D-Wabenstruktur: Band oben auf jeder Seite,
  Sechseck-Symbole, sechseckiger „+“-Knopf. Heller und dunkler Modus.
- Wabenmuster und App-Symbole erzeugt `tools/make_graphics.py` (braucht Pillow).
- Diagramme sind eigenes HTML/CSS (charts.py + _macros.html), keine externen Bibliotheken.

## Aufbau
- calculations.py: Rechenregeln (rein). services.py: Datenbank pro Nutzer.
- views/: Flask-Blueprints. templates/: Jinja. static/: CSS, JS, PWA-Dateien.
- Jede Abfrage filtert nach user_id; neue Seiten laden Zeilen mit owned_or_404().
- Kontostand = base_balance_cents + Buchungen − eingehende Umbuchungen (berechnet).
- Tabellen werden per create_all angelegt. Vor Schema-Änderungen mit echten
  Daten: Alembic-Migration einführen.

## Umgebung und Befehle
- Windows, PowerShell. Python 3.12 in der virtuellen Umgebung `.venv`.
- Python immer über die venv aufrufen: `.venv\Scripts\python`
- Pakete installieren: `.venv\Scripts\python -m pip install -r requirements.txt`
- Tests: `.venv\Scripts\python -m pytest`
- App starten: `.venv\Scripts\python serve.py` (Demo-Daten: `--demo`)
