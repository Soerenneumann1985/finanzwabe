# Finanz-App – Regeln für Claude

## Projekt
Persönliche Finanz-App (Flask, SQLAlchemy, SQLite, pytest).
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

## Umgebung und Befehle
- Windows, PowerShell. Python 3.12 in der virtuellen Umgebung `.venv`.
- Python immer über die venv aufrufen: `.venv\Scripts\python`
- Pakete installieren: `.venv\Scripts\python -m pip install -r requirements.txt`
- Tests: `.venv\Scripts\python -m pytest`
